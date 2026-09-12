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


class LocalIntegrityError(ValueError):
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
        raise LocalIntegrityError("local integrity payload is not canonical JSON") from error
    return rendered.encode("utf-8")


def seal_local_payload(
    payload: Mapping[str, object],
    *,
    payload_type: str,
) -> dict[str, object]:
    """Bind one typed payload to its exact type and canonical SHA-256 digest."""

    if not isinstance(payload, Mapping):
        raise LocalIntegrityError("local integrity payload must be a mapping")
    if (
        not isinstance(payload_type, str)
        or not payload_type
        or payload_type != payload_type.strip()
        or len(payload_type) > 64
    ):
        raise LocalIntegrityError("local integrity payload type is invalid")
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
        raise LocalIntegrityError("local integrity envelope shape is invalid")
    if envelope.get("integrity_version") != LOCAL_INTEGRITY_VERSION:
        raise LocalIntegrityError("local integrity envelope version is unsupported")
    if envelope.get("payload_type") != payload_type:
        raise LocalIntegrityError("local integrity payload type does not match")
    payload = envelope.get("payload")
    digest = envelope.get("payload_sha256")
    if not isinstance(payload, Mapping):
        raise LocalIntegrityError("local integrity payload shape is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise LocalIntegrityError("local integrity digest shape is invalid")
    material = {
        "integrity_version": LOCAL_INTEGRITY_VERSION,
        "payload": dict(payload),
        "payload_type": payload_type,
    }
    expected = hashlib.sha256(_canonical_bytes(material)).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise LocalIntegrityError("local integrity digest does not match")
    return payload, digest


def _strict_json(raw: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise LocalIntegrityError("local JSON contains a duplicate key")
            result[name] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                LocalIntegrityError("local JSON contains a non-finite value")
            ),
        )
    except json.JSONDecodeError as error:
        raise LocalIntegrityError("local JSON is malformed") from error


def validate_local_path(path: Path) -> None:
    """Reject traversal, symlink, directory, and overlong local state targets."""

    if not isinstance(path, Path) or not str(path).strip() or ".." in path.parts:
        raise LocalIntegrityError("local state path is invalid")
    if len(os.fsencode(path)) > 4_096:
        raise LocalIntegrityError("local state path is too long")
    if any(parent.is_symlink() for parent in path.parents if parent.exists()):
        raise LocalIntegrityError("local state path must not traverse a symlink")
    if path.is_symlink():
        raise LocalIntegrityError("local state path must not be a symlink")
    if path.exists() and not path.is_file():
        raise LocalIntegrityError("local state path must be a regular file")


def read_private_json(
    path: Path,
    *,
    max_bytes: int = LOCAL_STATE_MAX_BYTES,
) -> object:
    """Read one owner-only regular file without following symlinks."""

    if (
        isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or not 1 <= max_bytes <= LOCAL_STATE_MAX_BYTES
    ):
        raise LocalIntegrityError("local state size limit is invalid")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise LocalIntegrityError("local state file ownership or type is invalid")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise LocalIntegrityError("local state file must be owner-only")
        if metadata.st_size > max_bytes:
            raise LocalIntegrityError("local state file exceeds its bounded size")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            raw_bytes = handle.read(max_bytes + 1)
        if len(raw_bytes) > max_bytes:
            raise LocalIntegrityError("local state file exceeds its bounded size")
        raw = raw_bytes.decode("utf-8", errors="strict")
        return _strict_json(raw)
    except UnicodeError as error:
        raise LocalIntegrityError("local state file is not valid UTF-8") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def locked_private_file(path: Path, *, exclusive: bool) -> Iterator[None]:
    """Hold one owner-only regular lock file without following symlinks."""

    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise LocalIntegrityError("local state lock ownership or type is invalid")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise LocalIntegrityError("local state lock must be owner-only")
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def atomic_write_private_json(path: Path, value: object) -> None:
    """Atomically replace one regular target with owner-only canonical JSON."""

    validate_local_path(path)
    rendered = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    ) + "\n"
    if len(rendered.encode("utf-8")) > LOCAL_STATE_MAX_BYTES:
        raise LocalIntegrityError("local state write exceeds its bounded size")
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
