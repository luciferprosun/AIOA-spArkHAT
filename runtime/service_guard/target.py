"""Disposable loopback service and protected Core client; never host service control.

The operator-owned process/key and private state directory are trusted host
composition. Model text never receives these handles. State and target receipt
commit atomically; Core still has to independently verify the subsequent GET.
"""

from contextlib import contextmanager
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
import weakref

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contract import parse_request
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.nonzero_cloudops.state.files import (
    atomic_write_private_json, locked_private_file, open_local_payload,
    read_private_json, seal_local_payload, validate_local_path,
)
from runtime.service_guard.contracts import EFFECT, GuardError

_ISSUED = weakref.WeakSet()
_ISSUED_LOCK = threading.Lock()
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class TargetUnknown(GuardError):
    def __init__(self):
        super().__init__("TARGET_OUTCOME_UNKNOWN")


class _EffectAuthorization:
    __slots__ = ("client", "digest", "guard", "scheduler", "principal", "operation_id",
                 "proposal", "lock", "used", "__weakref__")

    def __init__(self, guard, scheduler, principal, operation_id, proposal, command):
        for key, value in dict(client=guard.target, digest=canonical_sha256(command),
                               guard=guard, scheduler=scheduler, principal=principal,
                               operation_id=operation_id, proposal=proposal,
                               lock=guard._effect_lock, used=False).items():
            object.__setattr__(self, key, value)

    def __setattr__(self, name, value):
        raise AttributeError("IMMUTABLE_EFFECT_AUTHORIZATION")

    @contextmanager
    def consume(self, client, command):
        # Revocation and the final effect boundary serialize in the one Core.
        with self.lock:
            with _ISSUED_LOCK:
                if (self not in _ISSUED or self.used or client is not self.client
                        or canonical_sha256(command) != self.digest):
                    raise GuardError("EFFECT_AUTHORIZATION_DENIED")
                object.__setattr__(self, "used", True)
                _ISSUED.discard(self)
            from runtime.service_guard.service import CoreServiceGuard
            CoreServiceGuard._boundary_check(self.guard, self.principal, self.operation_id,
                                             self.proposal, command, self.scheduler)
            yield


def _issue_effect(guard, scheduler, principal, operation_id, proposal, command):
    """Internal Core composition only; no model/JSON authority constructor."""
    from runtime.core_admission import Capability
    from runtime.service_guard.service import CoreServiceGuard
    if type(guard) is not CoreServiceGuard:
        raise GuardError("EFFECT_AUTHORIZATION_DENIED")
    guard.core.require(principal, Capability.COMMIT, scope=guard.policy.scope)
    value = _EffectAuthorization(guard, scheduler, principal, operation_id, proposal, command)
    with _ISSUED_LOCK:
        _ISSUED.add(value)
    return value


class LoopbackTargetClient:
    __slots__ = ("port", "scope", "target_id", "_key", "timeout")

    def __init__(self, *, port, scope, target_id, key, timeout=5):
        if (type(port) is not int or not 1024 <= port <= 65535
                or type(scope) is not OwnerScope or type(key) is not bytes
                or len(key) != 32 or type(timeout) is not int or not 1 <= timeout <= 15):
            raise GuardError("INVALID_LOCAL_TARGET_HANDLE")
        for name, value in dict(port=port, scope=scope, target_id=target_id,
                                _key=key, timeout=timeout).items():
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError("IMMUTABLE_TARGET_HANDLE")

    def read(self):
        return self._exchange("GET", "/state")

    def receipt(self, key):
        if type(key) is not str or _HEX.fullmatch(key) is None:
            raise GuardError("INVALID_EFFECT_KEY")
        return self._exchange("GET", "/receipts/" + key)

    def dispatch(self, command, authorization=None):
        return self._exchange("POST", "/effect", command, authorization)

    def _exchange(self, method, path, command=None, authorization=None):
        # The actual mutating HTTP boundary is guarded, including direct calls.
        if method == "POST" and path == "/effect":
            if type(authorization) is not _EffectAuthorization:
                raise GuardError("EFFECT_AUTHORIZATION_DENIED")
            boundary = authorization.consume(self, command)
        elif method == "GET" and (path == "/state" or re.fullmatch(r"/receipts/[0-9a-f]{64}", path)):
            boundary = _read_only()
        else:
            raise GuardError("TARGET_OPERATION_DENIED")
        with boundary:
            body = b"" if command is None else canonical_json_bytes(command)
            material = method.encode() + b"\n" + path.encode() + b"\n" + body
            signature = hmac.digest(self._key, material, "sha256").hex()
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
            try:
                connection.request(method, path, body=body, headers={
                    "X-Target-Proof": signature, "Content-Type": "application/json"})
                response = connection.getresponse()
                raw = response.read(16385)
                if len(raw) > 16384 or response.status != 200:
                    raise TargetUnknown()
                parsed = parse_request(raw.decode())
                return parsed.get("receipt") if path.startswith("/receipts/") else parsed
            except (OSError, http.client.HTTPException, ValueError):
                raise TargetUnknown() from None
            finally:
                connection.close()


@contextmanager
def _read_only():
    yield


class DisposableTargetState:
    """Real disposable state, with no adapter to OS services/cloud/user files."""
    def __init__(self, root, scope, target_id):
        self.root, self.scope, self.target_id = Path(root).absolute(), scope, target_id
        self.path = self.root / "target-state.json"
        validate_local_path(self.path)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_uid != os.getuid() or self.root.stat().st_mode & 0o077:
            raise GuardError("UNSAFE_TARGET_DIRECTORY")
        self.lock_path = self.root / "target-state.lock"
        with locked_private_file(self.lock_path, exclusive=True):
            if not self.path.exists():
                self._write({"target_id": target_id, "scope": list(scope.binding()),
                             "mode": "NORMAL", "revision": 1, "effect_count": 0,
                             "receipts": {}})
            self._load()

    def _load(self):
        value, _ = open_local_payload(read_private_json(self.path), payload_type="AIOA_DISPOSABLE_SERVICE")
        if value["scope"] != list(self.scope.binding()) or value["target_id"] != self.target_id:
            raise GuardError("TARGET_IDENTITY_MISMATCH")
        return dict(value)

    def _write(self, value):
        atomic_write_private_json(self.path, seal_local_payload(value, payload_type="AIOA_DISPOSABLE_SERVICE"))

    def read(self):
        with locked_private_file(self.lock_path, exclusive=False):
            value = self._load()
            return {key: item for key, item in value.items() if key != "receipts"}

    def receipt(self, key):
        with locked_private_file(self.lock_path, exclusive=False):
            return self._load()["receipts"].get(key)

    def apply(self, command):
        required = {"operation_id", "scope", "target_id", "expected_revision", "before_effect_count",
                    "effect_class", "approval_digest", "policy_digest", "proposal_digest",
                    "expires_at", "idempotency_key", "request_digest"}
        if (type(command) is not dict or set(command) != required
                or command["scope"] != list(self.scope.binding())
                or command["target_id"] != self.target_id or command["effect_class"] != EFFECT
                or type(command["expected_revision"]) is not int
                or type(command["before_effect_count"]) is not int
                or type(command["expires_at"]) is not int
                or _HEX.fullmatch(command["idempotency_key"]) is None
                or canonical_sha256({k:v for k,v in command.items() if k != "request_digest"}) != command["request_digest"]):
            raise GuardError("TARGET_COMMAND_DENIED")
        with locked_private_file(self.lock_path, exclusive=True):
            state = self._load()
            previous = state["receipts"].get(command["idempotency_key"])
            if previous:
                if previous["request_digest"] != command["request_digest"]:
                    raise GuardError("TARGET_IDEMPOTENCY_CONFLICT")
                return previous
            if (time.time() >= command["expires_at"] or state["mode"] != "NORMAL"
                    or state["revision"] != command["expected_revision"]
                    or state["effect_count"] != command["before_effect_count"]):
                raise GuardError("STALE_TARGET")
            if len(state["receipts"]) >= 128:
                raise GuardError("TARGET_RECEIPT_LIMIT")
            state.update(mode="MAINTENANCE", revision=state["revision"] + 1,
                         effect_count=state["effect_count"] + 1)
            receipt = {**command, "receipt_id": "target-" + command["idempotency_key"],
                       "new_revision": state["revision"], "effect_count": state["effect_count"],
                       "mode": state["mode"], "dispatched_at": int(time.time())}
            state["receipts"][command["idempotency_key"]] = receipt
            self._write(state)
            return receipt

    def operator_advance(self, *, mode="NORMAL"):
        """Explicit disposable-test controller mutation, never an HTTP/actor tool."""
        if mode not in {"NORMAL", "MAINTENANCE"}:
            raise GuardError("INVALID_TARGET_MODE")
        with locked_private_file(self.lock_path, exclusive=True):
            state = self._load()
            state.update(mode=mode, revision=state["revision"] + 1)
            self._write(state)


def serve(config):
    scope = OwnerScope(*config["scope"])
    state = DisposableTargetState(config["root"], scope, config["target_id"])
    key = bytes.fromhex(config["key"])
    if len(key) != 32:
        raise GuardError("INVALID_LOCAL_TARGET_HANDLE")
    drop_ack = config.get("drop_ack", False)  # Explicit controlled fault, never actor input.

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 16384:
                    raise GuardError("TARGET_REQUEST_LIMIT")
                body = self.rfile.read(size)
                material = self.command.encode() + b"\n" + self.path.encode() + b"\n" + body
                expected = hmac.digest(key, material, "sha256").hex()
                if not hmac.compare_digest(self.headers.get("X-Target-Proof", ""), expected):
                    raise GuardError("TARGET_AUTHENTICATION_DENIED")
                if self.command == "GET" and self.path == "/state":
                    result = state.read()
                elif self.command == "GET" and re.fullmatch(r"/receipts/[0-9a-f]{64}", self.path):
                    result = {"receipt": state.receipt(self.path.rsplit("/", 1)[1])}
                elif self.command == "POST" and self.path == "/effect":
                    result = state.apply(parse_request(body.decode()))
                    if drop_ack:
                        self.connection.shutdown(socket.SHUT_RDWR)
                        self.connection.close()
                        return
                else:
                    raise GuardError("TARGET_OPERATION_DENIED")
                data, status = canonical_json_bytes(result), 200
            except Exception:
                data, status = b'{"error":"TARGET_REQUEST_DENIED"}', 403
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        print(json.dumps({"port": server.server_port, "target_id": state.target_id}), flush=True)
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    # Private host bootstrap arrives over an inherited pipe, never argv or logs.
    serve(parse_request(sys.stdin.buffer.readline(16385).decode()))
