"""Deterministic permit gate for bounded provider transport calls.

The gate is authority metadata, never model output.  G07-B intentionally has
no live-permit issuer: only TEST permits can be issued by this module.  A later
operator phase may supply a separately issued, strictly parsed LIVE artifact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import threading
import weakref
from typing import Callable


SCHEMA_VERSION = 1
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z", re.ASCII)
_AUTHORITY_MARKER = object()
_ISSUED_AUTHORIZATIONS = weakref.WeakSet()
_IGNORED_SOURCE_DIRECTORIES = frozenset(
    {".git", "__pycache__", ".mypy_cache", ".pytest_cache", "build", "dist"}
)
_CANONICAL_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_GIT_BINARY = "/usr/bin/git"
_ACCEPTED_TEST_EVIDENCE = Path("aioa") / "accepted-test-evidence.json"


class LiveCallBlocked(RuntimeError):
    """A permit failed closed before provider transport."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__("LIVE_CALL_BLOCKED")


def _require_digest(value: object, *, sha: bool = False) -> str:
    pattern = _SHA if sha else _DIGEST
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError("INVALID_LIVE_CALL_PERMIT")
    return value


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def source_tree_digest(root: Path) -> str:
    """Hash regular source files and fail closed on protected-tree symlinks."""
    if (
        not isinstance(root, Path)
        or not root.is_absolute()
        or root.is_symlink()
        or not root.is_dir()
    ):
        raise ValueError("INVALID_SOURCE_STATE_ROOT")
    root = root.resolve()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root)
        if any(part in _IGNORED_SOURCE_DIRECTORIES for part in relative.parts):
            continue
        encoded_path = relative.as_posix().encode("utf-8")
        if path.is_symlink():
            raise ValueError("SOURCE_TREE_SYMLINK_REJECTED")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("INVALID_SOURCE_STATE_ENTRY")
        before = path.stat()
        content = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                content.update(chunk)
        after = path.stat()
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after:
            raise ValueError("SOURCE_STATE_CHANGED_DURING_DIGEST")
        digest.update(_canonical_bytes([
            "file", len(encoded_path), encoded_path.hex(), after.st_size, content.hexdigest()
        ]))
    return digest.hexdigest()


class RepositorySourceStateReader:
    """Production-owned LIVE reader with no injectable state callbacks."""

    __slots__ = ("root",)

    def __init__(self) -> None:
        root = _CANONICAL_REPOSITORY_ROOT
        if not isinstance(root, Path) or not root.is_absolute() or not root.is_dir():
            raise ValueError("INVALID_SOURCE_STATE_READER")
        self.root = root.resolve()

    @property
    def test_evidence_path(self) -> Path:
        return _authoritative_git_directory(self.root) / _ACCEPTED_TEST_EVIDENCE

    def __call__(self) -> tuple[str, str, str]:
        return _read_authoritative_source_state(self.root)


def transport_request_digest(payload: bytes, timeout: int, max_bytes: int) -> str:
    """Bind an authorization to the exact non-secret network request arguments."""
    if (
        type(payload) is not bytes
        or type(timeout) is not int
        or timeout <= 0
        or type(max_bytes) is not int
        or max_bytes <= 0
    ):
        raise LiveCallBlocked("TRANSPORT_REQUEST_INVALID")
    return hashlib.sha256(_canonical_bytes({
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "timeout": timeout,
        "max_bytes": max_bytes,
    })).hexdigest()


def _strict_object(raw: bytes | str) -> dict:
    if type(raw) is bytes:
        try:
            raw = raw.decode("utf-8")
        except UnicodeError:
            raise ValueError("INVALID_LIVE_CALL_PERMIT") from None
    if type(raw) is not str or len(raw.encode("utf-8")) > 16384:
        raise ValueError("INVALID_LIVE_CALL_PERMIT")

    def pairs(values):
        result = {}
        for key, value in values:
            if type(key) is not str or key in result:
                raise ValueError("INVALID_LIVE_CALL_PERMIT")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                ValueError("INVALID_LIVE_CALL_PERMIT")
            ),
        )
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError, UnicodeError):
        raise ValueError("INVALID_LIVE_CALL_PERMIT") from None
    if type(value) is not dict:
        raise ValueError("INVALID_LIVE_CALL_PERMIT")
    return value


def _git_value(root: Path, *arguments: str) -> str:
    """Read repository metadata through a fixed production-owned Git command."""
    try:
        completed = subprocess.run(
            (_GIT_BINARY, "-C", str(root), *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("AUTHORITATIVE_GIT_STATE_UNAVAILABLE") from None
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value or "\n" in value or "\r" in value:
        raise ValueError("AUTHORITATIVE_GIT_STATE_UNAVAILABLE")
    return value


def _authoritative_git_directory(root: Path) -> Path:
    value = _git_value(root, "rev-parse", "--absolute-git-dir")
    directory = Path(value)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("AUTHORITATIVE_GIT_STATE_UNAVAILABLE")
    return directory.resolve()


def _authoritative_head(root: Path) -> str:
    return _require_digest(_git_value(root, "rev-parse", "--verify", "HEAD"), sha=True)


def _read_stable_regular_file(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded regular file without following a final-component symlink."""
    if not path.is_absolute() or type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("INVALID_EVIDENCE_PATH")
    try:
        before = path.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ValueError("INVALID_EVIDENCE_FILE")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_size > max_bytes:
                raise ValueError("INVALID_EVIDENCE_FILE")
            chunks = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(8192, max_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("INVALID_EVIDENCE_FILE")
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, ValueError):
        raise ValueError("INVALID_EVIDENCE_FILE") from None
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_opened or identity_opened != identity_after:
        raise ValueError("EVIDENCE_CHANGED_DURING_READ")
    return b"".join(chunks)


def _authoritative_test_evidence_digest(
    root: Path, current_head: str, current_source_digest: str
) -> str:
    path = _authoritative_git_directory(root) / _ACCEPTED_TEST_EVIDENCE
    raw = _read_stable_regular_file(path, max_bytes=65536)
    evidence = _strict_object(raw)
    expected = {
        "schema_version",
        "status",
        "git_sha",
        "source_tree_digest",
        "tests_run",
        "failures",
        "errors",
        "skipped",
        "unexpected_skips",
        "completed_at",
    }
    if set(evidence) != expected:
        raise ValueError("INVALID_TEST_EVIDENCE")
    if (
        type(evidence["schema_version"]) is not int
        or evidence["schema_version"] != 1
        or evidence["status"] != "PASS"
        or type(evidence["tests_run"]) is not int
        or evidence["tests_run"] <= 0
        or type(evidence["failures"]) is not int
        or evidence["failures"] != 0
        or type(evidence["errors"]) is not int
        or evidence["errors"] != 0
        or type(evidence["skipped"]) is not int
        or evidence["skipped"] < 0
        or type(evidence["unexpected_skips"]) is not int
        or evidence["unexpected_skips"] != 0
        or type(evidence["completed_at"]) is not int
        or evidence["completed_at"] <= 0
    ):
        raise ValueError("INVALID_TEST_EVIDENCE")
    _require_digest(evidence["git_sha"], sha=True)
    _require_digest(evidence["source_tree_digest"])
    if evidence["git_sha"] != current_head:
        raise ValueError("STALE_TEST_EVIDENCE_HEAD")
    if evidence["source_tree_digest"] != current_source_digest:
        raise ValueError("STALE_TEST_EVIDENCE_SOURCE")
    return hashlib.sha256(raw).hexdigest()


def _read_authoritative_source_state(root: Path) -> tuple[str, str, str]:
    head_before = _authoritative_head(root)
    source_digest = source_tree_digest(root)
    evidence_digest = _authoritative_test_evidence_digest(
        root, head_before, source_digest
    )
    head_after = _authoritative_head(root)
    if head_after != head_before:
        raise ValueError("SOURCE_STATE_CHANGED_DURING_READ")
    return head_after, source_digest, evidence_digest


@dataclass(frozen=True, slots=True, repr=False)
class LocalGateResult:
    gate_status: str
    test_suite_digest: str

    def __post_init__(self) -> None:
        if self.gate_status not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("INVALID_LOCAL_GATE_RESULT")
        _require_digest(self.test_suite_digest)


@dataclass(frozen=True, slots=True, repr=False)
class LiveCallPermit:
    permit_id: str
    phase: str
    git_sha: str
    worktree_digest: str
    test_suite_digest: str
    gate_status: str
    issued_at: int
    expires_at: int
    max_live_calls: int
    provider_id: str
    model_id: str
    transport_scope: str
    schema_version: int = SCHEMA_VERSION
    permit_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if (
            type(self.permit_id) is not str
            or _ID.fullmatch(self.permit_id) is None
            or type(self.phase) is not str
            or _ID.fullmatch(self.phase) is None
        ):
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        _require_digest(self.git_sha, sha=True)
        _require_digest(self.worktree_digest)
        _require_digest(self.test_suite_digest)
        if self.gate_status not in {"PASS", "FAIL", "BLOCKED"}:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if (
            type(self.issued_at) is not int
            or type(self.expires_at) is not int
            or not 0 <= self.issued_at < self.expires_at <= 4102444800
            or type(self.max_live_calls) is not int
            or not 1 <= self.max_live_calls <= 100000
        ):
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if self.transport_scope not in {"TEST", "LIVE"}:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if self.transport_scope == "LIVE" and self.max_live_calls != 1:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if (
            type(self.provider_id) is not str
            or _ID.fullmatch(self.provider_id) is None
            or type(self.model_id) is not str
            or _MODEL.fullmatch(self.model_id) is None
        ):
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        object.__setattr__(
            self,
            "permit_digest",
            hashlib.sha256(_canonical_bytes(self._unsigned())).hexdigest(),
        )

    def _unsigned(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "permit_id": self.permit_id,
            "phase": self.phase,
            "git_sha": self.git_sha,
            "worktree_digest": self.worktree_digest,
            "test_suite_digest": self.test_suite_digest,
            "gate_status": self.gate_status,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_live_calls": self.max_live_calls,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "transport_scope": self.transport_scope,
        }

    def as_dict(self) -> dict:
        return {**self._unsigned(), "permit_digest": self.permit_digest}

    def to_json_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    @classmethod
    def from_json_bytes(cls, raw: bytes | str) -> "LiveCallPermit":
        value = _strict_object(raw)
        expected = {
            "schema_version",
            "permit_id",
            "phase",
            "git_sha",
            "worktree_digest",
            "test_suite_digest",
            "gate_status",
            "issued_at",
            "expires_at",
            "max_live_calls",
            "provider_id",
            "model_id",
            "transport_scope",
            "permit_digest",
        }
        if set(value) != expected:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        supplied_digest = value.pop("permit_digest")
        permit = cls(**value)
        if type(supplied_digest) is not str or supplied_digest != permit.permit_digest:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        return permit


@dataclass(frozen=True, slots=True, repr=False)
class LocalGateDecision:
    phase_status: str
    permit: LiveCallPermit | None
    reason: str | None

    def __post_init__(self) -> None:
        if self.phase_status not in {"PASS", "BLOCKED"}:
            raise ValueError("INVALID_LOCAL_GATE_DECISION")
        if self.phase_status == "PASS":
            if type(self.permit) is not LiveCallPermit or self.reason is not None:
                raise ValueError("INVALID_LOCAL_GATE_DECISION")
        elif self.permit is not None or self.reason != "LOCAL_GATE_NOT_PASS":
            raise ValueError("INVALID_LOCAL_GATE_DECISION")


def issue_test_permit(
    *,
    permit_id: str,
    phase: str,
    git_sha: str,
    worktree_digest: str,
    local_gate: LocalGateResult,
    issued_at: int,
    expires_at: int,
    max_live_calls: int,
    provider_id: str,
    model_id: str,
) -> LocalGateDecision:
    """Return the production phase decision and optional TEST-scope permit."""
    if type(local_gate) is not LocalGateResult:
        raise ValueError("INVALID_LOCAL_GATE_RESULT")
    if local_gate.gate_status != "PASS":
        return LocalGateDecision("BLOCKED", None, "LOCAL_GATE_NOT_PASS")
    return LocalGateDecision(
        "PASS",
        LiveCallPermit(
            permit_id,
            phase,
            git_sha,
            worktree_digest,
            local_gate.test_suite_digest,
            local_gate.gate_status,
            issued_at,
            expires_at,
            max_live_calls,
            provider_id,
            model_id,
            "TEST",
        ),
        None,
    )


class PermitUsageLedger:
    """Durably consume permit calls before transport, including across restarts."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("INVALID_PERMIT_LEDGER")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._open() as database:
            database.execute(
                "CREATE TABLE IF NOT EXISTS permit_usage("
                "permit_digest TEXT PRIMARY KEY, max_calls INTEGER NOT NULL, "
                "used_calls INTEGER NOT NULL CHECK(used_calls>=0 AND used_calls<=max_calls))"
            )

    def _open(self):
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    def used(self, permit: LiveCallPermit) -> int:
        with self._open() as database:
            row = database.execute(
                "SELECT max_calls,used_calls FROM permit_usage WHERE permit_digest=?",
                (permit.permit_digest,),
            ).fetchone()
        if row is None:
            return 0
        if row[0] != permit.max_live_calls:
            raise LiveCallBlocked("PERMIT_LEDGER_BINDING_MISMATCH")
        return int(row[1])

    def consume(self, permit: LiveCallPermit) -> int:
        database = self._open()
        try:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT max_calls,used_calls FROM permit_usage WHERE permit_digest=?",
                (permit.permit_digest,),
            ).fetchone()
            if row is None:
                used = 0
                database.execute(
                    "INSERT INTO permit_usage(permit_digest,max_calls,used_calls) VALUES(?,?,0)",
                    (permit.permit_digest, permit.max_live_calls),
                )
            else:
                if row[0] != permit.max_live_calls:
                    raise LiveCallBlocked("PERMIT_LEDGER_BINDING_MISMATCH")
                used = int(row[1])
            if used >= permit.max_live_calls:
                raise LiveCallBlocked("CALL_BUDGET_EXHAUSTED")
            used += 1
            database.execute(
                "UPDATE permit_usage SET used_calls=? WHERE permit_digest=?",
                (used, permit.permit_digest),
            )
            database.execute("COMMIT")
            return used
        except Exception:
            try:
                database.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            database.close()


class _TransportAuthorization:
    """Opaque, single-use capability consumed at the transport effect boundary."""

    __slots__ = (
        "permit_digest", "provider_id", "model_id", "transport_scope",
        "call_ordinal", "request_digest", "_transport", "_state_reader",
        "_expected_state", "_issued_at", "_expires_at", "_clock", "_marker",
        "_consumed", "_lock", "__weakref__",
    )

    def __init__(
        self,
        permit: LiveCallPermit,
        call_ordinal: int,
        request_digest: str,
        transport: object,
        state_reader: Callable[[], tuple[str, str, str]],
        clock: Callable[[], int],
        authority_marker: object = None,
    ) -> None:
        self.permit_digest = permit.permit_digest
        self.provider_id = permit.provider_id
        self.model_id = permit.model_id
        self.transport_scope = permit.transport_scope
        self.call_ordinal = call_ordinal
        self.request_digest = request_digest
        self._transport = transport
        self._state_reader = state_reader
        self._expected_state = (
            permit.git_sha, permit.worktree_digest, permit.test_suite_digest
        )
        self._issued_at = permit.issued_at
        self._expires_at = permit.expires_at
        self._clock = clock
        self._marker = authority_marker
        self._consumed = False
        self._lock = threading.Lock()

    def consume(
        self,
        expected_scope: str,
        *,
        transport: object,
        payload: bytes,
        timeout: int,
        max_bytes: int,
        provider_id: str,
        model_id: str,
    ) -> None:
        with self._lock:
            if self._consumed:
                raise LiveCallBlocked("TRANSPORT_AUTHORIZATION_REUSED")
            now = self._clock()
            if type(now) is not int or now < self._issued_at or now >= self._expires_at:
                raise LiveCallBlocked("PERMIT_EXPIRED_OR_NOT_YET_VALID")
            if transport is not self._transport:
                raise LiveCallBlocked("TRANSPORT_IDENTITY_MISMATCH")
            if self.transport_scope != expected_scope:
                raise LiveCallBlocked("TRANSPORT_SCOPE_MISMATCH")
            if provider_id != self.provider_id:
                raise LiveCallBlocked("PROVIDER_MISMATCH")
            if model_id != self.model_id:
                raise LiveCallBlocked("MODEL_MISMATCH")
            if transport_request_digest(payload, timeout, max_bytes) != self.request_digest:
                raise LiveCallBlocked("TRANSPORT_REQUEST_MISMATCH")
            _require_matching_state(self._state_reader(), self._expected_state)
            self._consumed = True


def require_transport_authorization(
    authorization: object,
    expected_scope: str,
    *,
    transport: object,
    payload: bytes,
    timeout: int,
    max_bytes: int,
    provider_id: str,
    model_id: str,
) -> None:
    if (
        type(authorization) is not _TransportAuthorization
        or getattr(authorization, "_marker", None) is not _AUTHORITY_MARKER
        or authorization not in _ISSUED_AUTHORIZATIONS
    ):
        raise LiveCallBlocked("TRANSPORT_AUTHORIZATION_MISSING_OR_INVALID")
    authorization.consume(
        expected_scope,
        transport=transport,
        payload=payload,
        timeout=timeout,
        max_bytes=max_bytes,
        provider_id=provider_id,
        model_id=model_id,
    )


def _require_matching_state(
    current: tuple[str, str, str], expected: tuple[str, str, str]
) -> None:
    if current[0] != expected[0]:
        raise LiveCallBlocked("GIT_SHA_MISMATCH")
    if current[1] != expected[1]:
        raise LiveCallBlocked("WORKTREE_DIGEST_MISMATCH")
    if current[2] != expected[2]:
        raise LiveCallBlocked("TEST_SUITE_DIGEST_MISMATCH")


class LiveCallGate:
    """Validate a permit against current local evidence and consume its budget."""

    def __init__(
        self,
        permit: LiveCallPermit | None,
        *,
        source_reader: Callable[[], tuple[str, str, str]],
        usage_ledger: PermitUsageLedger,
        clock: Callable[[], int],
    ) -> None:
        if permit is not None and type(permit) is not LiveCallPermit:
            raise ValueError("INVALID_LIVE_CALL_PERMIT")
        if (
            not callable(source_reader)
            or type(usage_ledger) is not PermitUsageLedger
            or not callable(clock)
        ):
            raise ValueError("INVALID_LIVE_CALL_GATE")
        if (
            permit is not None
            and permit.transport_scope == "LIVE"
            and type(source_reader) is not RepositorySourceStateReader
        ):
            raise ValueError("INVALID_LIVE_CALL_GATE")
        self.permit = permit
        self._source_reader = source_reader
        self.usage_ledger = usage_ledger
        self.clock = clock

    def _current_state(self) -> tuple[str, str, str]:
        try:
            state = self._source_reader()
            if type(state) is not tuple or len(state) != 3:
                raise ValueError("INVALID_SOURCE_STATE")
            git_sha, worktree_digest, test_suite_digest = state
            _require_digest(git_sha, sha=True)
            _require_digest(worktree_digest)
            _require_digest(test_suite_digest)
        except LiveCallBlocked:
            raise
        except Exception:
            raise LiveCallBlocked("SOURCE_STATE_UNAVAILABLE") from None
        return git_sha, worktree_digest, test_suite_digest

    def _validate(self, provider_id: str, model_id: str, transport_scope: str) -> LiveCallPermit:
        permit = self.permit
        if permit is None:
            raise LiveCallBlocked("PERMIT_MISSING")
        if permit.gate_status != "PASS":
            raise LiveCallBlocked("LOCAL_GATE_NOT_PASS")
        now = self.clock()
        if type(now) is not int or now < permit.issued_at or now >= permit.expires_at:
            raise LiveCallBlocked("PERMIT_EXPIRED_OR_NOT_YET_VALID")
        _require_matching_state(
            self._current_state(),
            (permit.git_sha, permit.worktree_digest, permit.test_suite_digest),
        )
        if permit.provider_id != provider_id:
            raise LiveCallBlocked("PROVIDER_MISMATCH")
        if permit.model_id != model_id:
            raise LiveCallBlocked("MODEL_MISMATCH")
        if permit.transport_scope != transport_scope:
            raise LiveCallBlocked("TRANSPORT_SCOPE_MISMATCH")
        if self.usage_ledger.used(permit) >= permit.max_live_calls:
            raise LiveCallBlocked("CALL_BUDGET_EXHAUSTED")
        return permit

    def require(self, provider_id: str, model_id: str, transport_scope: str) -> None:
        self._validate(provider_id, model_id, transport_scope)

    def authorize(
        self,
        provider_id: str,
        model_id: str,
        transport_scope: str,
        *,
        transport: object,
        payload: bytes,
        timeout: int,
        max_bytes: int,
    ) -> _TransportAuthorization:
        permit = self._validate(provider_id, model_id, transport_scope)
        ordinal = self.usage_ledger.consume(permit)
        authorization = _TransportAuthorization(
            permit,
            ordinal,
            transport_request_digest(payload, timeout, max_bytes),
            transport,
            self._current_state,
            self.clock,
            _AUTHORITY_MARKER,
        )
        _ISSUED_AUTHORIZATIONS.add(authorization)
        return authorization
