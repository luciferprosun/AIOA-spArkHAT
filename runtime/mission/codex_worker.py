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
