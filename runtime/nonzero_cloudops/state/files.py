# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: persistence/local_integrity.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Shared fail-closed integrity and filesystem primitives for local JSON state."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Final

LOCAL_INTEGRITY_VERSION: Final = 1
LOCAL_STATE_MAX_BYTES: Final = 8 * 1024 * 1024
_DIGEST_LENGTH: Final = 64
_ENVELOPE_KEYS: Final = frozenset(
    {"integrity_version", "payload", "payload_sha256", "payload_type"}
)


class StateIntegrityError(ValueError):
    """A local file failed structural, digest, or private-file validation."""


def _canonical_bytes(value: object) -> bytes:
    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise StateIntegrityError(
            "local integrity payload is not canonical JSON"
        ) from error
    return rendered.encode("utf-8")


def seal_local_payload(
    payload: Mapping[str, object],
    *,
    payload_type: str,
) -> dict[str, object]:
    """Bind one typed payload to its exact type and canonical SHA-256 digest."""

    if not isinstance(payload, Mapping):
        raise StateIntegrityError("local integrity payload must be a mapping")
    if (
        not isinstance(payload_type, str)
        or not payload_type
        or payload_type != payload_type.strip()
        or len(payload_type) > 64
    ):
        raise StateIntegrityError("local integrity payload type is invalid")
    material: dict[str, object] = {
        "integrity_version": LOCAL_INTEGRITY_VERSION,
        "payload": dict(payload),
        "payload_type": payload_type,
    }
    return {
        **material,
        "payload_sha256": hashlib.sha256(_canonical_bytes(material)).hexdigest(),
    }


def open_local_payload(
    envelope: object,
    *,
    payload_type: str,
) -> tuple[Mapping[str, object], str]:
    """Verify an exact local envelope and return its payload plus trusted digest."""

    if not isinstance(envelope, Mapping) or set(envelope) != _ENVELOPE_KEYS:
        raise StateIntegrityError("local integrity envelope shape is invalid")
    if (type(envelope.get("integrity_version")) is not int
            or envelope.get("integrity_version") != LOCAL_INTEGRITY_VERSION):
        raise StateIntegrityError("local integrity envelope version is unsupported")
    if envelope.get("payload_type") != payload_type:
        raise StateIntegrityError("local integrity payload type does not match")
    payload = envelope.get("payload")
    digest = envelope.get("payload_sha256")
    if not isinstance(payload, Mapping):
        raise StateIntegrityError("local integrity payload shape is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise StateIntegrityError("local integrity digest shape is invalid")
    material = {
        "integrity_version": LOCAL_INTEGRITY_VERSION,
        "payload": dict(payload),
        "payload_type": payload_type,
    }
    expected = hashlib.sha256(_canonical_bytes(material)).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise StateIntegrityError("local integrity digest does not match")
    return payload, digest


def _strict_json(raw: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise StateIntegrityError("local JSON contains a duplicate key")
            result[name] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                StateIntegrityError("local JSON contains a non-finite value")
            ),
        )
    except (json.JSONDecodeError, RecursionError) as error:
        raise StateIntegrityError("local JSON is malformed") from error


def validate_local_path(path: Path) -> None:
    """Reject traversal, symlink, directory, and overlong local state targets."""

    if not isinstance(path, Path) or not str(path).strip() or ".." in path.parts:
        raise StateIntegrityError("local state path is invalid")
    if len(os.fsencode(path)) > 4_096:
        raise StateIntegrityError("local state path is too long")
    if any(parent.is_symlink() for parent in path.parents if parent.exists()):
        raise StateIntegrityError("local state path must not traverse a symlink")
    if path.is_symlink():
        raise StateIntegrityError("local state path must not be a symlink")
    if path.exists() and not path.is_file():
        raise StateIntegrityError("local state path must be a regular file")


def read_private_json(
    path: Path,
    *,
    max_bytes: int = LOCAL_STATE_MAX_BYTES,
) -> object:
    """Read one stable owner-only single-link file without following symlinks.

    Callers retain their existing lock. Replacement between separate reads is
    supported; replacement or mutation during one read is a typed denial. This
    detects observed FD/name changes, not hostile joint rollback by an OS owner.
    """

    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 1 <= max_bytes <= LOCAL_STATE_MAX_BYTES
    ):
        raise StateIntegrityError("local state size limit is invalid")
    if not isinstance(path, (str, Path)):
        raise StateIntegrityError("local state path is invalid")
    path = Path(path)
    validate_local_path(path)
    required_flags = ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC")
    if not all(hasattr(os, name) for name in required_flags):
        raise StateIntegrityError("local state safe open is unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    descriptor = os.open(path, flags)

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
                info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1):
            raise StateIntegrityError("local state file ownership or type is invalid")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise StateIntegrityError("local state file must be owner-only")
        if not 0 <= metadata.st_size <= max_bytes:
            raise StateIntegrityError("local state file exceeds its bounded size")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw_bytes = handle.read(max_bytes + 1)
            observed = os.fstat(handle.fileno())
            named = path.lstat()
            if (len(raw_bytes) != metadata.st_size
                    or identity(metadata) != identity(observed)
                    or identity(metadata) != identity(named)):
                raise StateIntegrityError("local state file changed during read")
        raw = raw_bytes.decode("utf-8", errors="strict")
        return _strict_json(raw)
    except UnicodeError as error:
        raise StateIntegrityError("local state file is not valid UTF-8") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def locked_private_file(path: Path, *, exclusive: bool, create: bool = True) -> Iterator[int]:
    """Hold one owner-only regular lock file without following symlinks."""

    if type(create) is not bool:
        raise StateIntegrityError('local state lock creation flag is invalid')
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise StateIntegrityError("local state lock ownership or type is invalid")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise StateIntegrityError("local state lock must be owner-only")
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        acquiring_pid = os.getpid()
        try:
            # Borrowed only for identity checks while this same lock is held.
            # The existing context manager remains the sole descriptor owner.
            yield descriptor
        finally:
            # fork shares the open file description. A child closes its copy;
            # only the process that acquired flock may explicitly unlock it.
            if os.getpid() == acquiring_pid:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def atomic_write_private_json(path: Path, value: object) -> None:
    """Atomically replace one regular target with owner-only canonical JSON."""

    validate_local_path(path)
    rendered = (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    if len(rendered.encode("utf-8")) > LOCAL_STATE_MAX_BYTES:
        raise StateIntegrityError("local state write exceeds its bounded size")
    descriptor = -1
    temporary_name = ""
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
        temporary_name = ""
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_name:
            with suppress(OSError):
                Path(temporary_name).unlink(missing_ok=True)
