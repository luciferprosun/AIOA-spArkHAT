"""Bounded Unix IPC and attempt fencing for the disposable Native CAS prototype."""

import fcntl
import hashlib
import json
import os
import re
import socket
import stat
import struct
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission.sandbox_linux import LinuxSandboxBroker, mountid
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.witness import WitnessBinding


SCHEMA = "aioa.redhat.fixture-cas-request.v1"
MAX_FRAME = 8192
MAX_ATTEMPTS = 256
FRAME_TIMEOUT = 2.0
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9_-]{0,95}(?:/[A-Za-z0-9][A-Za-z0-9_-]{0,95})*")
_OPEN_FILE = os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class ProtocolError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ProtocolError(code)


def digest(value):
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class BrokerRequest:
    operation_id: str
    attempt_id: str
    owner_id: str
    device_id: str
    executor_id: str
    executor_key_id: str
    key_epoch: int
    start_digest: str
    intent_digest: str
    warrant_digest: str
    reservation_digest: str
    commit_permit_digest: str
    core_epoch: int
    broker_epoch: int
    nonce: str
    challenge: str
    repository_dev: int
    repository_inode: int
    ref_directory_dev: int
    ref_directory_inode: int
    exact_ref: str
    old_oid: str
    new_oid: str
    issued_at: int
    expires_at: int

    def __post_init__(self):
        require(all(_matches(_IDENTIFIER, value) for value in (
            self.operation_id, self.attempt_id, self.owner_id, self.device_id,
        )) and all(_matches(_DIGEST, value) for value in (
            self.nonce, self.challenge, self.commit_permit_digest,
        )) and all(type(value) is int and 0 < value < 2**63 for value in (
            self.key_epoch, self.broker_epoch, self.core_epoch,
        )) and _matches(_REF, self.exact_ref)
            and type(self.old_oid) is str, "BROKER_REQUEST_SCHEMA")
        try:
            self.witness_binding()
        except ValueError as error:
            raise ProtocolError("BROKER_REQUEST_SCHEMA") from error

    def to_wire(self):
        return {"schema": SCHEMA, **asdict(self)}

    @classmethod
    def from_wire(cls, payload):
        expected = {"schema"} | {field.name for field in fields(cls)}
        require(type(payload) is dict and set(payload) == expected
                and payload["schema"] == SCHEMA, "BROKER_REQUEST_SCHEMA")
        return cls(**{key: value for key, value in payload.items() if key != "schema"})

    @staticmethod
    def permit_digest(bindings):
        return digest({"schema": "aioa.redhat.fixture-commit-permit.v1", "bindings": bindings})

    @classmethod
    def for_fixture(cls, **bindings):
        """Construct the trusted fixture grant. This digest conveys no authority alone."""
        return cls(**bindings, commit_permit_digest=cls.permit_digest(bindings))

    def require_permit(self, now):
        bindings = asdict(self)
        bindings.pop("commit_permit_digest")
        require(type(now) is int and self.issued_at <= now < self.expires_at
                and self.commit_permit_digest == self.permit_digest(bindings),
                "BROKER_PERMIT")

    @property
    def repository(self):
        return self.repository_dev, self.repository_inode

    @property
    def ref_directory(self):
        return self.ref_directory_dev, self.ref_directory_inode

    def witness_binding(self):
        # v1's nonce field binds the entire IPC request, including the original nonce.
        return WitnessBinding(
            self.executor_id, self.executor_key_id, digest(self.to_wire()),
            self.start_digest, self.intent_digest, self.warrant_digest,
            self.reservation_digest, self.core_epoch, self.repository, self.ref_directory,
            self.exact_ref, self.old_oid, self.new_oid, self.issued_at, self.expires_at,
        )


@dataclass(frozen=True, slots=True)
class Peer:
    pid: int
    uid: int
    gid: int

    def __post_init__(self):
        require(type(self.pid) is int and self.pid > 0
                and all(type(value) is int and value >= 0 for value in (self.uid, self.gid)),
                "BROKER_PEER")


def authenticate(stream, expected):
    require(stream.family == socket.AF_UNIX and stream.type == socket.SOCK_STREAM,
            "BROKER_PEER")
    credentials = struct.Struct("=iII")
    actual = Peer(*credentials.unpack(
        stream.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, credentials.size)
    ))
    require(type(expected) is Peer and expected == actual, "BROKER_PEER")


def decode_record(raw):
    try:
        value = json.loads(raw)
        require(canonical_json_bytes(value) == raw, "BROKER_FRAME_CANONICAL")
        return value
    except (ValueError, TypeError, RecursionError):
        raise ProtocolError("BROKER_FRAME_CANONICAL") from None


def send_frame(stream, payload, *, body=b""):
    raw = canonical_json_bytes(payload)
    require(0 < len(raw) <= MAX_FRAME, "BROKER_FRAME_SIZE")
    stream.settimeout(FRAME_TIMEOUT)
    stream.sendall(struct.pack("!I", len(raw)) + raw)
    if body:
        stream.sendall(body)
    stream.shutdown(socket.SHUT_WR)


def read_frame(stream, *, receive_body=None):
    deadline = time.monotonic() + FRAME_TIMEOUT

    def read(size):
        remaining = deadline - time.monotonic()
        require(remaining > 0, "BROKER_FRAME_TIMEOUT")
        stream.settimeout(remaining)
        try:
            return stream.recv(size)
        except TimeoutError:
            raise ProtocolError("BROKER_FRAME_TIMEOUT") from None

    def exact(size):
        result = bytearray()
        while len(result) < size:
            part = read(size - len(result))
            require(part, "BROKER_FRAME_TRUNCATED")
            result.extend(part)
        return bytes(result)

    size, = struct.unpack("!I", exact(4))
    require(0 < size <= MAX_FRAME, "BROKER_FRAME_SIZE")
    frame = decode_record(exact(size))
    result = frame if receive_body is None else receive_body(frame, exact)
    require(not read(1), "BROKER_FRAME_TRAILING")
    return result


def require_admission(request, enrollment, *, now, core_epoch, broker_epoch):
    require(type(core_epoch) is int and request.core_epoch == core_epoch
            and type(broker_epoch) is int and request.broker_epoch == broker_epoch,
            "BROKER_EPOCH")
    require(type(enrollment) is ExecutorEnrollment and enrollment.permits(request, now),
            "BROKER_ENROLLMENT")
    request.require_permit(now)


def receive_request(stream, peer, expected, enrollment, *, now, core_epoch, broker_epoch):
    authenticate(stream, peer)
    request = BrokerRequest.from_wire(read_frame(stream))
    require(type(expected) is BrokerRequest and request == expected, "BROKER_BINDING")
    require_admission(request, enrollment, now=now, core_epoch=core_epoch,
                      broker_epoch=broker_epoch)
    return request


def file_identity(info):
    return info.st_dev, info.st_ino


def _stamp(info):
    return (*file_identity(info), info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def read_record(directory, name, uid, *, maximum=MAX_FRAME, sync=False, reader_gid=None):
    fd = os.open(name, os.O_RDONLY | _OPEN_FILE, dir_fd=directory)
    try:
        initial = os.fstat(fd)
        require(stat.S_ISREG(initial.st_mode) and initial.st_uid == uid
                and (stat.S_IMODE(initial.st_mode) == 0o400 if reader_gid is None
                     else initial.st_gid == reader_gid and stat.S_IMODE(initial.st_mode) == 0o440
                     and mountid(fd) == mountid(directory))
                and initial.st_nlink == 1 and 0 < initial.st_size <= maximum,
                "BROKER_RECORD_STORAGE")
        raw = os.pread(fd, maximum + 1, 0)
        if sync:
            os.fsync(fd)
            os.fsync(directory)
        require(len(raw) == initial.st_size
                and _stamp(initial) == _stamp(os.fstat(fd))
                == _stamp(os.stat(name, dir_fd=directory, follow_symlinks=False)),
                "BROKER_RECORD_MOVED")
        return raw
    finally:
        os.close(fd)


def publish_record(directory, name, value, *, reader_gid=None):
    require(LinuxSandboxBroker._git_publish_new(
        directory, name, canonical_json_bytes(value), cancel=None, reader_gid=reader_gid
    ), "BROKER_RECORD_EXISTS")


def _no_fault(_):
    pass


class AttemptGuard:
    """Crash fence for a single private fixture directory shared by trusted roles."""

    def __init__(self, directory):
        info = os.fstat(directory)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
                and stat.S_IMODE(info.st_mode) == 0o700, "BROKER_STATE_DIRECTORY")
        self.directory = directory

    @contextmanager
    def locked(self):
        # Each participant opens a new description of the same protected inode.
        lock = os.open("lock", os.O_RDWR | os.O_CREAT | _OPEN_FILE, 0o600,
                       dir_fd=self.directory)
        try:
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                    and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1, "BROKER_STATE_LOCK")
            fcntl.flock(lock, fcntl.LOCK_EX)
            require(_stamp(os.fstat(lock)) == _stamp(os.stat(
                "lock", dir_fd=self.directory, follow_symlinks=False
            )), "BROKER_STATE_LOCK")
            yield
        finally:
            os.close(lock)

    def require_running(self):
        try:
            os.stat("stopped", dir_fd=self.directory, follow_symlinks=False)
        except FileNotFoundError:
            return
        raise ProtocolError("BROKER_STOPPED")

    def stop(self):
        with self.locked():
            try:
                self.require_running()
            except ProtocolError:
                raw = read_record(self.directory, "stopped", os.geteuid(), sync=True)
                require(raw == canonical_json_bytes({"stopped": True}), "BROKER_STATE_RECORD")
                return
            publish_record(self.directory, "stopped", {"stopped": True})

    def consume(self, request, fault=_no_fault, *, authorize=None):
        operation = digest([request.owner_id, request.device_id, request.operation_id])
        record = {"operation": operation, "attempt": request.attempt_id,
                  "nonce": request.nonce, "request": digest(request.to_wire())}
        with self.locked():
            self.require_running()
            permits, attempts = {}, {}
            with os.scandir(self.directory) as entries:
                for row, entry in enumerate(entries):
                    require(row < MAX_ATTEMPTS * 2 + 2, "BROKER_STATE_FULL")
                    if entry.name in ("lock", "stopped"):
                        continue
                    kind, _, operation_id = entry.name.partition("-")
                    require(kind in ("permit", "attempt"), "BROKER_STATE_RECORD")
                    past = decode_record(read_record(self.directory, entry.name, os.geteuid()))
                    require(type(past) is dict and set(past) == set(record)
                            and all(_matches(_DIGEST, past[key])
                                    for key in ("operation", "nonce", "request"))
                            and _matches(_IDENTIFIER, past["attempt"])
                            and operation_id == past["operation"], "BROKER_STATE_RECORD")
                    (permits if kind == "permit" else attempts)[operation_id] = past
                    require(all(record[key] != past[key] for key in ("operation", "attempt", "nonce")),
                            "BROKER_REPLAY")
            require(all(permits.get(key) == value for key, value in attempts.items()),
                    "BROKER_STATE_RECORD")
            require(len(permits) < MAX_ATTEMPTS, "BROKER_STATE_FULL")
            if authorize is not None:
                authorize()
            # This first durable record already fences the operation after a crash.
            publish_record(self.directory, "permit-" + operation, record)
            fault("permit_durable")
            publish_record(self.directory, "attempt-" + operation, record)
            fault("attempt_consumed")
