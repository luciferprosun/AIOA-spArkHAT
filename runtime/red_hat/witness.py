"""Native CAS witness primitives for a future registered executor.

Inputs come from trusted admission and pinned descriptors. These primitives
do not enroll an executor, authorize publication, or settle an intent.
"""

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission.sandbox_linux import LinuxSandboxBroker
from runtime.mobile_gateway.wire import public_key, unbase64

SCHEMA = "aioa.native-cas-witness.v1"
STAGE = "EXCLUSIVE_LINK_AND_DIRECTORY_FSYNC"
MAX_WITNESS_BYTES = 8192
_OID = re.compile(r"[0-9a-f]{40}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_REF = re.compile(r"refs/heads/[A-Za-z0-9][A-Za-z0-9/_-]{0,127}")
_EXECUTOR = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


def _physical(identity):
    return (
        type(identity) is tuple
        and len(identity) == 2
        and all(type(value) is int and 0 < value < 2**64 for value in identity)
    )


def _matches(pattern, value):
    return type(value) is str and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class WitnessBinding:
    executor: str
    key_id: str
    nonce: str
    start_digest: str
    intent_digest: str
    warrant_digest: str
    reservation_digest: str
    epoch: int
    repository: tuple[int, int]
    ref_directory: tuple[int, int]
    ref: str
    old_oid: str
    new_oid: str
    issued_at: int
    expires_at: int

    def __post_init__(self):
        if (
            not _matches(_EXECUTOR, self.executor)
            or not all(_matches(_DIGEST, value) for value in (
                self.key_id, self.nonce, self.start_digest, self.intent_digest,
                self.warrant_digest, self.reservation_digest,
            ))
            or type(self.epoch) is not int
            or not 0 < self.epoch < 2**63
            or not _physical(self.repository)
            or not _physical(self.ref_directory)
            or not _matches(_REF, self.ref)
            or "//" in self.ref
            or self.ref.endswith("/")
            or self.old_oid != "0" * 40
            or not _matches(_OID, self.new_oid)
            or self.new_oid == self.old_oid
            or type(self.issued_at) is not int
            or type(self.expires_at) is not int
            or not 0 < self.issued_at < self.expires_at < 2**63
            or self.expires_at - self.issued_at > 300
        ):
            raise ValueError("CAS_WITNESS_BINDING")

    @property
    def witness_id(self):
        return hashlib.sha256(canonical_json_bytes(asdict(self))).hexdigest()


@dataclass(frozen=True, slots=True)
class RegisteredExecutor:
    executor: str
    uid: int
    spki: str

    def __post_init__(self):
        if not _matches(_EXECUTOR, self.executor) or type(self.uid) is not int or self.uid < 0:
            raise ValueError("CAS_WITNESS_EXECUTOR")
        public_key(self.spki)

    @property
    def key_id(self):
        return hashlib.sha256(unbase64(self.spki)).hexdigest()


def witness_payload(binding, *, published_inode, published_at):
    """Build the signed payload from the broker's publication observations."""
    if not _physical(published_inode) or (
        type(published_at) is not int
        or not binding.issued_at <= published_at < binding.expires_at
    ):
        raise ValueError("CAS_WITNESS_PUBLICATION")
    return {
        "schema": SCHEMA,
        "witness_id": binding.witness_id,
        **asdict(binding),
        "stage": STAGE,
        "published_inode": published_inode,
        "published_at": published_at,
    }


def _check_directory(directory_fd, executor, reader_gid=None):
    info = os.fstat(directory_fd)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != executor.uid
            or (stat.S_IMODE(info.st_mode) != 0o700 if reader_gid is None
                else info.st_gid != reader_gid or stat.S_IMODE(info.st_mode) != 0o2750)):
        raise ValueError("CAS_WITNESS_DIRECTORY")


def _decode(raw):
    envelope = json.loads(raw)
    if (type(envelope) is not dict or set(envelope) != {"payload", "signature"}
            or type(envelope["payload"]) is not dict
            or canonical_json_bytes(envelope) != raw):
        raise ValueError("CAS_WITNESS_ENVELOPE")
    return envelope


def _verify(raw, binding, executor, *, published_inode):
    if (executor.executor, executor.key_id) != (binding.executor, binding.key_id):
        raise ValueError("CAS_WITNESS_EXECUTOR")
    envelope = _decode(raw)
    payload = envelope["payload"]
    expected = witness_payload(
        binding, published_inode=published_inode, published_at=payload.get("published_at")
    )
    if canonical_json_bytes(payload) != canonical_json_bytes(expected):
        raise ValueError("CAS_WITNESS_MISMATCH")
    try:
        public_key(executor.spki).verify(
            unbase64(envelope["signature"]), canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256())
        )
    except InvalidSignature:
        raise ValueError("CAS_WITNESS_SIGNATURE") from None


def persist_witness(directory_fd, binding, executor, *, signature, published_inode, published_at, reader_gid=None):
    """Persist a signed witness exclusively through a private directory descriptor."""
    _check_directory(directory_fd, executor, reader_gid)
    if os.geteuid() != executor.uid:
        raise ValueError("CAS_WITNESS_EXECUTOR")
    if type(signature) is not str or not 0 < len(signature) <= 1024:
        raise ValueError("CAS_WITNESS_SIGNATURE")
    payload = witness_payload(binding, published_inode=published_inode, published_at=published_at)
    raw = canonical_json_bytes({"payload": payload, "signature": signature})
    if len(raw) > MAX_WITNESS_BYTES:
        raise ValueError("CAS_WITNESS_SIZE")
    _verify(raw, binding, executor, published_inode=published_inode)
    if not LinuxSandboxBroker._git_publish_new(
        directory_fd, binding.witness_id, raw, cancel=None, reader_gid=reader_gid
    ):
        raise FileExistsError("CAS_WITNESS_EXISTS")


def verify_witness(
    directory_fd, binding, executor, *, repository, ref_directory, published_inode
):
    """Check exact signed evidence against independently observed ref custody.

    The caller supplies an enrollment from trusted configuration and an inode
    observed under the existing pinned ref-directory and repository checks.
    """
    if (not _physical(repository) or not _physical(ref_directory)
            or (repository, ref_directory) != (binding.repository, binding.ref_directory)):
        return False
    try:
        _check_directory(directory_fd, executor)
        fd = os.open(
            binding.witness_id, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
            dir_fd=directory_fd,
        )
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != executor.uid
                    or stat.S_IMODE(info.st_mode) != 0o400 or info.st_nlink != 1
                    or not 0 < info.st_size <= MAX_WITNESS_BYTES):
                return False
            raw = os.pread(fd, MAX_WITNESS_BYTES + 1, 0)
            if len(raw) != info.st_size:
                return False
            _verify(raw, binding, executor, published_inode=published_inode)
            # Cover a surviving link whose producer exited before directory sync.
            # Readback may establish the directory barrier before accepting it.
            os.fsync(directory_fd)
            current = os.stat(binding.witness_id, dir_fd=directory_fd, follow_symlinks=False)
            return (
                current.st_dev, current.st_ino, current.st_ctime_ns, current.st_nlink
            ) == (info.st_dev, info.st_ino, info.st_ctime_ns, info.st_nlink)
        finally:
            os.close(fd)
    except (OSError, ValueError, RecursionError):
        return False
