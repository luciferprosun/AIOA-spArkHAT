"""Opt-in local IPC sequencer for disposable Native STOP/CAS qualification."""

import fcntl
import os
import secrets
import socket
import stat
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.persistence.ports import transaction_active
from runtime.red_hat.broker_protocol import Peer, authenticate, decode_record, publish_record, recv_data, require
from runtime.red_hat.execution_binding import digest_string
from runtime.red_hat.fixture_repository import require_private


SCHEMA = "aioa.redhat.fixture-sequencer.v1"
MAX_MESSAGE = 1024
MAX_CONNECTIONS = 8
SLOT = "outstanding"
_S1_INCARNATION = "s1-sequencer-incarnation"
_HEADER = struct.Struct("!I")


def _send(stream, value, timeout):
    raw = canonical_json_bytes(value)
    require(0 < len(raw) <= MAX_MESSAGE, "RH07_SEQUENCE_SIZE")
    stream.settimeout(timeout)
    stream.sendall(_HEADER.pack(len(raw)) + raw)


def _read(stream, timeout):
    deadline = time.monotonic() + timeout

    def exact(size):
        data = bytearray()
        while len(data) < size:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "RH07_SEQUENCE_TIMEOUT")
            stream.settimeout(remaining)
            part = recv_data(stream, size - len(data))
            require(part, "RH07_SEQUENCE_EOF")
            data.extend(part)
        return data

    size, = _HEADER.unpack(exact(_HEADER.size))
    require(0 < size <= MAX_MESSAGE, "RH07_SEQUENCE_SIZE")
    return decode_record(bytes(exact(size)))


def _limits(epoch, timeout):
    require(type(epoch) is int and 0 < epoch < 2**63
            and type(timeout) in (int, float) and 0 < timeout <= 20,
            "RH07_SEQUENCE_CONFIGURATION")


def _message(epoch, action, binding, **extra):
    return {"schema": SCHEMA, "epoch": epoch, "action": action, "binding": binding, **extra}


@dataclass(frozen=True, slots=True)
class SequenceClient:
    endpoint: str
    peer: Peer
    epoch: int
    timeout: float = 3.0

    def __post_init__(self):
        _limits(self.epoch, self.timeout)
        require(type(self.peer) is Peer and type(self.endpoint) is str
                and os.path.isabs(self.endpoint), "RH07_SEQUENCE_CONFIGURATION")

    @contextmanager
    def _connect(self):
        require(not transaction_active(), "RH07_IPC_IN_TRANSACTION")
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(self.timeout)
            stream.connect(self.endpoint)
            authenticate(stream, self.peer)
            yield stream

    @contextmanager
    def hold(self, *, binding=None):
        require(binding is None or digest_string(binding), "RH07_SEQUENCE_BINDING")
        process = os.getpid()
        action = "control" if binding is None else "publish"
        with self._connect() as stream:
            _send(stream, _message(self.epoch, action, binding), self.timeout)
            grant = _read(stream, self.timeout)
            require(type(grant) is dict and digest_string(grant.get("token"))
                    and grant == _message(self.epoch, "granted", binding, token=grant["token"]),
                    "RH07_SEQUENCE_NOT_GRANTED")
            token = grant["token"]
            # An exception or disappearance is ambiguous. Never send DONE for it.
            yield token
            require(os.getpid() == process, "RH07_SEQUENCE_FORK")
            _send(stream, _message(self.epoch, "done", binding, token=token), self.timeout)
            require(_read(stream, self.timeout) == _message(self.epoch, "closed", binding, token=token),
                    "RH07_SEQUENCE_CLOSE_UNKNOWN")

    def check_publisher(self, binding, token):
        require(digest_string(binding) and digest_string(token), "RH07_SEQUENCE_BINDING")
        with self._connect() as stream:
            _send(stream, _message(self.epoch, "check", binding, token=token), self.timeout)
            require(_read(stream, self.timeout) == _message(self.epoch, "active", binding, token=token),
                    "RH07_SEQUENCE_NOT_ACTIVE")


class SequencedCoreGate:
    """Reentrant adapter for existing nested Core control mutations."""

    def __init__(self, client, *, enabled=False):
        require(enabled is True and type(client) is SequenceClient, "RH07_DISABLED")
        self._client = client
        self._thread = threading.local()
        self._pid = os.getpid()

    @contextmanager
    def hold(self):
        require(os.getpid() == self._pid, "RH07_SEQUENCE_FORK")
        if getattr(self._thread, "owns", False):
            yield
            return
        with self._client.hold():
            self._thread.owns = True
            try:
                yield
            finally:
                self._thread.owns = False


def bind_fixture_runner(runner, gate, *, enabled=False):
    """Attach the adapter only to an explicitly supplied, unused fixture runner."""
    from runtime.memory_patch.persistence.ports import TransactionRunner

    require(enabled is True and type(gate) is SequencedCoreGate
            and type(runner) is TransactionRunner, "RH07_DISABLED")
    admission = getattr(runner, "_admission", None)
    require(admission is not None and getattr(runner, "execution_gate", None) is None
            and getattr(admission, "execution_gate", None) is None, "RH07_SEQUENCE_CORE_BINDING")
    runner.execution_gate = admission.execution_gate = gate


class _Sequencer:
    def __init__(self, directory, core_peer, broker_peer, epoch, timeout, active_timeout, fault):
        self.directory, self.core_peer, self.broker_peer = directory, core_peer, broker_peer
        self.epoch, self.timeout, self.active_timeout = epoch, timeout, active_timeout
        self.fault = fault
        self.condition = threading.Condition()
        self.control_waiters = 0
        self.slot = None
        try:
            os.stat(SLOT, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            self.poisoned = False
        else:
            self.poisoned = True

    def _request(self, stream):
        try:
            authenticate(stream, self.core_peer)
        except ValueError:
            authenticate(stream, self.broker_peer)
            role = "broker"
        else:
            role = "core"
        request = _read(stream, self.timeout)
        require(type(request) is dict and type(request.get("epoch")) is int
                and request["epoch"] == self.epoch, "RH07_SEQUENCE_EPOCH")
        action, binding = request.get("action"), request.get("binding")
        require(role == ("broker" if action == "publish" else "core"),
                "RH07_SEQUENCE_ROLE")
        if action == "check":
            token = request.get("token")
            require(digest_string(binding) and digest_string(token)
                    and request == _message(self.epoch, action, binding, token=token),
                    "RH07_SEQUENCE_REQUEST")
            with self.condition:
                require(not self.poisoned and self.slot == (binding, token), "RH07_SEQUENCE_NOT_ACTIVE")
            _send(stream, _message(self.epoch, "active", binding, token=token), self.timeout)
            return
        require(action in ("control", "publish")
                and (binding is None if action == "control" else digest_string(binding))
                and request == _message(self.epoch, action, binding), "RH07_SEQUENCE_REQUEST")
        self._lease(stream, binding)

    def _lease(self, stream, binding):
        control = binding is None
        token = secrets.token_hex(32)
        with self.condition:
            self.control_waiters += int(control)
            try:
                if control and self.slot is not None:
                    self.fault("control_waiting")
                ready = self.condition.wait_for(lambda: self.poisoned or (
                    self.slot is None and (control or not self.control_waiters)), timeout=self.timeout)
                require(ready and not self.poisoned, "RH07_SEQUENCE_NOT_GRANTED")
                self.slot = (binding, token)
            finally:
                self.control_waiters -= int(control)
                self.condition.notify_all()
        try:
            # Record uncertainty before transferring a capability to proceed.
            publish_record(self.directory, SLOT, _message(self.epoch, "outstanding", binding, token=token))
            self.fault("slot_durable")
            _send(stream, _message(self.epoch, "granted", binding, token=token), self.timeout)
            require(_read(stream, self.active_timeout) == _message(self.epoch, "done", binding, token=token),
                    "RH07_SEQUENCE_UNCERTAIN")
            self.fault("done_received")
            os.unlink(SLOT, dir_fd=self.directory)
            os.fsync(self.directory)
        except BaseException:
            with self.condition:
                self.poisoned = True
                self.condition.notify_all()
            raise
        else:
            with self.condition:
                self.slot = None
                self.condition.notify_all()
            self.fault("slot_closed")
            _send(stream, _message(self.epoch, "closed", binding, token=token), self.timeout)

    def handle(self, stream):
        with stream:
            try:
                self._request(stream)
            except (OSError, ValueError):
                try:
                    _send(stream, {"denied": True}, self.timeout)
                except OSError:
                    pass


def serve_sequencer(listener, *, directory, core_peer, broker_peer, epoch, timeout=2.0,
                    active_timeout=5.0, stop=None, fault=lambda _: None, enabled=False, on_ready=None,
                    fence_restart=False):
    """Serve ordered capabilities over a trusted listener, with bounded concurrency."""
    require(enabled is True, "RH07_DISABLED")
    require(type(fence_restart) is bool, "RH07_SEQUENCE_CONFIGURATION")
    _limits(epoch, timeout)
    _limits(epoch, active_timeout)
    require(listener.family == socket.AF_UNIX and listener.type == socket.SOCK_STREAM
            and type(core_peer) is Peer and type(broker_peer) is Peer
            and core_peer.pid != broker_peer.pid, "RH07_SEQUENCE_CONFIGURATION")
    require_private(directory, os.geteuid())
    leader = os.open("leader", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
                     | os.O_NONBLOCK, 0o600, dir_fd=directory)
    try:
        info = os.fstat(leader)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
                "RH07_SEQUENCE_STORAGE")
        fcntl.flock(leader, fcntl.LOCK_EX | fcntl.LOCK_NB)
        service = _Sequencer(directory, core_peer, broker_peer, epoch, timeout, active_timeout, fault)
        if fence_restart:
            # S1 uses one sequencer process per aperture. Readback needs no slot.
            # If unlink of SLOT becomes visible before fsync fails, a process
            # restart must still fail closed, including under a new epoch.
            require(not service.poisoned, "RH07_SEQUENCE_OUTSTANDING")
            publish_record(directory, _S1_INCARNATION,
                           {"schema": "aioa.redhat.s1.sequencer-incarnation.v1", "epoch": epoch})
        available = threading.BoundedSemaphore(MAX_CONNECTIONS)

        def handle(peer):
            try:
                service.handle(peer)
            finally:
                available.release()

        listener.settimeout(0.25)
        if on_ready is not None:
            require(not service.poisoned, "RH07_SEQUENCE_OUTSTANDING")
            on_ready()
        with ThreadPoolExecutor(max_workers=MAX_CONNECTIONS) as pool:
            while stop is None or not stop.is_set():
                try:
                    peer, _ = listener.accept()
                except TimeoutError:
                    continue
                if available.acquire(blocking=False):
                    pool.submit(handle, peer)
                else:
                    peer.close()
    finally:
        os.close(leader)
