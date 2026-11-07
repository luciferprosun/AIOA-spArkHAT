"""Strict Codex wire boundary; production adapter deliberately NOT_CERTIFIED.

Adapted from NonZero W7A agent/codex_app_server.py at
392487849eddc7444f5159994b66b72e73f15934; MIT attribution is shipped in
runtime/nonzero_cloudops/LICENSE-NONZERO.txt. This module starts no process.
Only the existing Core sandbox can own a future executable worker.
"""

import json
import time

from runtime.mission.contracts import bounded_int, logical_id
from runtime.mission.worker import SyntheticWorker, WorkerError, require
from runtime.nonzero_cloudops.models.redaction import contains_sensitive_material

CODEX_CERTIFICATION = "NOT_CERTIFIED"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "PROTOCOL_DUPLICATE_FIELD")
        result[key] = value
    return result


def _constant(_value):
    raise WorkerError("PROTOCOL_NONFINITE_JSON")


class JsonlFramer:
    def __init__(self, *, max_bytes=65536):
        bounded_int(max_bytes, 1, 1048576)
        self.max_bytes, self._buffer, self._closed = max_bytes, bytearray(), False

    def feed(self, data):
        require(type(data) is bytes and not self._closed, "PROTOCOL_CLOSED")
        require(len(data) <= self.max_bytes * 256, "PROTOCOL_BATCH_BOUND")
        messages = []
        for part in data.splitlines(keepends=True):
            self._buffer.extend(part)
            require(len(self._buffer) <= self.max_bytes, "PROTOCOL_MESSAGE_BOUND")
            if not self._buffer.endswith(b"\n"):
                continue
            raw = bytes(self._buffer)
            self._buffer.clear()
            try:
                value = json.loads(
                    raw.decode("utf-8"),
                    object_pairs_hook=_pairs,
                    parse_constant=_constant,
                )
            except (ValueError, UnicodeError, RecursionError):
                raise WorkerError("PROTOCOL_JSON") from None
            require(type(value) is dict, "PROTOCOL_OBJECT_REQUIRED")
            messages.append(value)
            require(len(messages) <= 256, "PROTOCOL_BATCH_BOUND")
        return tuple(messages)

    def finish(self):
        self._closed = True
        require(not self._buffer.strip(), "PROTOCOL_TRUNCATED_EOF")


class CodexProtocol:
    """Correlate an already owned turn; text and tool requests grant nothing."""

    def __init__(self, thread_id, turn_id):
        self.thread_id, self.turn_id = logical_id(thread_id), logical_id(turn_id)
        self.terminal_status = None

    def observe(self, message):
        require(
            type(message) is dict and self.terminal_status is None,
            "PROTOCOL_LATE_EVENT",
        )
        method = message.get("method")
        require(type(method) is str and 1 <= len(method) <= 256, "PROTOCOL_METHOD")
        params = message.get("params", {})
        require(type(params) is dict, "PROTOCOL_PARAMS")
        if "id" in message:
            request_id = message["id"]
            require(
                (type(request_id) is int and 0 <= request_id <= 2**31)
                or (
                    type(request_id) is str
                    and logical_id(request_id)
                    and not contains_sensitive_material(request_id)
                ),
                "PROTOCOL_REQUEST_ID",
            )
            return {
                "id": request_id,
                "error": {
                    "code": -32601,
                    "message": "AIOA approval is required outside the worker",
                },
            }
        if "threadId" in params:
            require(params["threadId"] == self.thread_id, "PROTOCOL_THREAD_BINDING")
        if "turnId" in params:
            require(params["turnId"] == self.turn_id, "PROTOCOL_TURN_BINDING")
        if method in ("turn/started", "turn/completed"):
            turn = params.get("turn")
            require(
                type(turn) is dict
                and turn.get("id") == self.turn_id
                and params.get("threadId") == self.thread_id,
                "PROTOCOL_TURN_BINDING",
            )
            if method == "turn/completed":
                status = turn.get("status")
                require(
                    status in ("completed", "failed", "interrupted"),
                    "PROTOCOL_TERMINAL",
                )
                self.terminal_status = (
                    "SUCCEEDED"
                    if status == "completed" and not turn.get("error")
                    else "CANCELLED"
                    if status == "interrupted"
                    else "FAILED"
                )
        elif method == "error":
            self.terminal_status = "FAILED"
        return None


class CodexWorker(SyntheticWorker):
    """Typed refusal until a Core-owned executable backend is certified.

    Reuses only the bounded mailbox lifecycle. There are no candidates,
    subprocess, fallback provider, credentials or enable-live constructor flag.
    """

    def __init__(self, *, clock=time.time):
        super().__init__((), model_id="codex", clock=clock)

    def start(self, task):
        session = super().start(task)
        self._box.fail(session, "NOT_CERTIFIED")
        return session


class OwnedCodexProtocol:
    """Bounded v2 diagnostics over an ALREADY owned, isolated process's pipes.

    This is not an executor or a certified inference WorkerPort. It has no
    process launcher, credentials, generic RPC, tool approval or turn/start.
    The existing Core host must supply ownership and isolation separately.
    """

    authority = "NONE"

    def __init__(self, read_fd, write_fd):
        import os

        require(
            type(read_fd) is int and type(write_fd) is int,
            "PROTOCOL_OWNED_PIPES_REQUIRED",
        )
        self.read_fd, self.write_fd = os.dup(read_fd), os.dup(write_fd)
        os.set_blocking(self.read_fd, False)
        os.set_blocking(self.write_fd, False)
        self.framer = JsonlFramer(max_bytes=65536)
        self.events, self._messages = [], []
        self.protocol, self._pending, self._next_id = None, None, 0
        self.closed, self.initialized = False, False

    def _send(self, message, *, deadline):
        import os
        import select

        raw = (
            json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        )
        require(len(raw) <= 8192 and not self.closed, "PROTOCOL_WRITE_BOUND")
        view = memoryview(raw)
        while view:
            require(time.monotonic() < deadline, "PROTOCOL_TIMEOUT")
            _, ready, _ = select.select(
                [], [self.write_fd], [], min(0.05, max(0, deadline - time.monotonic()))
            )
            if not ready:
                continue
            try:
                written = os.write(self.write_fd, view)
            except (BrokenPipeError, OSError):
                raise WorkerError("PROTOCOL_EOF") from None
            require(written > 0, "PROTOCOL_EOF")
            view = view[written:]

    def _read(self, deadline, cancel):
        import os
        import select

        while not self._messages:
            require(not self.closed, "PROTOCOL_CLOSED")
            require(cancel is None or not cancel.cancelled, "CANCELLED")
            require(time.monotonic() < deadline, "PROTOCOL_TIMEOUT")
            ready, _, _ = select.select(
                [self.read_fd], [], [], min(0.05, max(0, deadline - time.monotonic()))
            )
            if not ready:
                continue
            raw = os.read(self.read_fd, 65536)
            if not raw:
                self.framer.finish()
                raise WorkerError("PROTOCOL_EOF")
            self._messages.extend(self.framer.feed(raw))
            require(len(self._messages) <= 64, "PROTOCOL_EVENT_LIMIT")
        return self._messages.pop(0)

    def _observe(self, message, deadline):
        import re

        from runtime.memory_patch.contracts.serialization import canonical_sha256

        method = message.get("method")
        require(
            type(method) is str
            and re.fullmatch(r"[A-Za-z0-9_/.-]{1,128}", method)
            and not contains_sensitive_material(method),
            "PROTOCOL_METHOD",
        )
        require(len(self.events) < 64, "PROTOCOL_EVENT_LIMIT")
        if self.protocol is not None:
            reply = self.protocol.observe(message)
        elif "id" in message:
            identity = message["id"]
            require(
                type(identity) is int and 0 <= identity <= 2**31, "PROTOCOL_REQUEST_ID"
            )
            reply = {
                "id": identity,
                "error": {"code": -32601, "message": "AIOA tool approval denied"},
            }
        else:
            reply = None
        if reply is not None:
            self._send(reply, deadline=deadline)
        self.events.append(
            {"method": method, "evidence_digest": canonical_sha256(message)}
        )

    def _request(self, method, params, *, seconds=5, cancel=None):
        require(
            method in ("initialize", "thread/start", "turn/interrupt")
            and self._pending is None
            and self._next_id < 8
            and type(seconds) in (int, float)
            and 0 < seconds <= 10,
            "PROTOCOL_REQUEST_BOUND",
        )
        self._next_id += 1
        identity = self._next_id
        self._pending = identity
        deadline = time.monotonic() + seconds
        self._send(
            {"id": identity, "method": method, "params": params}, deadline=deadline
        )
        try:
            for _ in range(65):
                message = self._read(deadline, cancel)
                if "method" in message:
                    self._observe(message, deadline)
                    continue
                require(
                    set(message)
                    in (
                        {"id", "result"},
                        {"id", "error"},
                        {"jsonrpc", "id", "result"},
                        {"jsonrpc", "id", "error"},
                    )
                    and type(message["id"]) is int
                    and message["id"] == identity,
                    "PROTOCOL_RESPONSE_BINDING",
                )
                require(
                    "error" not in message and type(message.get("result")) is dict,
                    "PROTOCOL_RPC_ERROR",
                )
                return message["result"]
            raise WorkerError("PROTOCOL_EVENT_LIMIT")
        finally:
            self._pending = None

    def initialize(self):
        require(not self.initialized, "PROTOCOL_INITIALIZE_ORDER")
        result = self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "aioa-nz11-probe",
                    "title": "AIOA offline protocol probe",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": False},
            },
        )
        self._send(
            {"method": "initialized", "params": {}}, deadline=time.monotonic() + 1
        )
        self.initialized = True
        return result

    def thread_start(self):
        require(self.initialized, "PROTOCOL_INITIALIZE_REQUIRED")
        return self._request(
            "thread/start",
            {
                "cwd": "/fixture",
                "sandbox": "read-only",
                "approvalPolicy": "never",
                "ephemeral": True,
                "config": {"web_search": "disabled", "analytics.enabled": False},
            },
        )

    def bind_turn(self, thread_id, turn_id):
        require(self.protocol is None, "PROTOCOL_TURN_ALREADY_BOUND")
        self.protocol = CodexProtocol(thread_id, turn_id)

    def interrupt(self, thread_id, turn_id):
        require(
            self.protocol is not None
            and self.protocol.thread_id == thread_id
            and self.protocol.turn_id == turn_id,
            "PROTOCOL_TURN_BINDING",
        )
        return self._request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
        )

    def next_event(self, *, seconds=1, cancel=None):
        require(
            type(seconds) in (int, float) and 0 < seconds <= 10, "PROTOCOL_WAIT_BOUND"
        )
        deadline = time.monotonic() + seconds
        message = self._read(deadline, cancel)
        require("method" in message, "PROTOCOL_RESPONSE_BINDING")
        self._observe(message, deadline)
        return self.events[-1]

    def close(self):
        import os

        if not self.closed:
            self.closed = True
            os.close(self.read_fd)
            os.close(self.write_fd)
