"""Fail-closed provider outcome classification and UNKNOWN quarantine.

The records in this module are evidence only.  They cannot grant an approval,
authorize transport, or execute a replay.  A manual replay request deliberately
creates a new immutable attempt record; the normal Core/live-call gates must
still authorize any later network operation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid


class ProviderFailureClass(str, Enum):
    AUTH_FAILURE = "AUTH_FAILURE"
    QUOTA_OR_RATE_LIMIT = "QUOTA_OR_RATE_LIMIT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    TRUNCATED_RESPONSE = "TRUNCATED_RESPONSE"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    MALFORMED_JSON = "MALFORMED_JSON"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    MODEL_OR_CAPABILITY_MISMATCH = "MODEL_OR_CAPABILITY_MISMATCH"
    UNKNOWN = "UNKNOWN"


_CODE_CLASS = {
    "MISSING_API_KEY": ProviderFailureClass.AUTH_FAILURE,
    "INVALID_API_KEY_CONFIGURATION": ProviderFailureClass.AUTH_FAILURE,
    "PROVIDER_AUTH_FAILED": ProviderFailureClass.AUTH_FAILURE,
    "RATE_LIMITED": ProviderFailureClass.QUOTA_OR_RATE_LIMIT,
    "PROVIDER_UNAVAILABLE": ProviderFailureClass.PROVIDER_UNAVAILABLE,
    "UPSTREAM_SERVER_ERROR": ProviderFailureClass.UPSTREAM_5XX,
    "PROVIDER_TIMEOUT": ProviderFailureClass.NETWORK_TIMEOUT,
    "CONNECTION_FAILURE": ProviderFailureClass.NETWORK_TIMEOUT,
    "TRUNCATED_RESPONSE": ProviderFailureClass.TRUNCATED_RESPONSE,
    "RESPONSE_TOO_LARGE": ProviderFailureClass.TRUNCATED_RESPONSE,
    "OUTPUT_TOKEN_LIMIT_EXCEEDED": ProviderFailureClass.TRUNCATED_RESPONSE,
    "INVALID_PROVIDER_RESPONSE": ProviderFailureClass.SCHEMA_INVALID,
    "MALFORMED_PROVIDER_JSON": ProviderFailureClass.MALFORMED_JSON,
    "EMPTY_PROVIDER_RESPONSE": ProviderFailureClass.EMPTY_RESPONSE,
    "MODEL_NOT_FOUND": ProviderFailureClass.MODEL_OR_CAPABILITY_MISMATCH,
    "MODEL_MISMATCH": ProviderFailureClass.MODEL_OR_CAPABILITY_MISMATCH,
    "MODEL_OR_REQUEST_REJECTED": ProviderFailureClass.MODEL_OR_CAPABILITY_MISMATCH,
}


def classify_provider_failure(code: str, http_status: int | None = None) -> ProviderFailureClass:
    """Map only evidence-supported conditions; ambiguity remains UNKNOWN."""
    if http_status in {401, 403}:
        return ProviderFailureClass.AUTH_FAILURE
    if http_status == 429:
        return ProviderFailureClass.QUOTA_OR_RATE_LIMIT
    if http_status is not None and 500 <= http_status <= 599:
        return ProviderFailureClass.UPSTREAM_5XX
    return _CODE_CLASS.get(code, ProviderFailureClass.UNKNOWN)


def sha256_bytes(value: bytes | None) -> str | None:
    return None if value is None else hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class SafeProviderMetadata:
    http_status: int | None = None
    provider_request_id: str | None = None
    model: str | None = None
    content_type: str | None = None
    response_byte_length: int | None = None
    finish_reason: str | None = None
    latency_ms: int | None = None
    retry_after: str | None = None
    rate_limit: dict | None = None
    request_hash: str | None = None
    response_hash: str | None = None

    def payload(self) -> dict:
        result = asdict(self)
        return {key: value for key, value in result.items() if value is not None}


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,191}\Z", re.ASCII)
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{40}\Z", re.ASCII)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SECRET_KEYS = re.compile(
    r"(?:authorization|api[-_]?key|cookie|secret|token|password)", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")


def redact_evidence(value):
    """Recursively remove credentials while retaining bounded diagnostic shape."""
    if isinstance(value, dict):
        return {
            str(key)[:128]: ("[REDACTED]" if _SECRET_KEYS.search(str(key)) else redact_evidence(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_evidence(item) for item in value[:128]]
    if isinstance(value, str):
        return _BEARER.sub("Bearer [REDACTED]", value)[:2048]
    if value is None or type(value) in {bool, int, float}:
        return value
    return "[REDACTED_TYPE]"


@dataclass(frozen=True, slots=True)
class UnknownEvent:
    test_or_operation_id: str
    provider: str
    model: str
    request_hash: str
    response_hash: str | None
    safe_http_metadata: dict
    parser_stage: str
    attempt_count: int
    human_readable_reason: str
    source_commit_sha: str
    redacted_artifact: dict


class UnknownQuarantine:
    """Owner-only append-only manifest and redacted artifacts."""

    def __init__(self, root: Path, *, clock=time.time):
        if not isinstance(root, Path) or not root.is_absolute() or root.is_symlink():
            raise ValueError("INVALID_QUARANTINE_ROOT")
        self.root = root
        self.clock = clock
        self.artifacts = root / "redacted"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.artifacts.mkdir(mode=0o700, exist_ok=True)
        os.chmod(root, 0o700)
        os.chmod(self.artifacts, 0o700)
        self.manifest = root / "unknown.jsonl"
        self.replays = root / "manual-replays.jsonl"

    @staticmethod
    def _validate_event(event: UnknownEvent) -> None:
        if type(event) is not UnknownEvent:
            raise ValueError("INVALID_UNKNOWN_EVENT")
        for value in (event.test_or_operation_id, event.provider, event.parser_stage):
            if type(value) is not str or _ID.fullmatch(value) is None:
                raise ValueError("INVALID_UNKNOWN_EVENT")
        if type(event.model) is not str or _MODEL.fullmatch(event.model) is None:
            raise ValueError("INVALID_UNKNOWN_EVENT")
        if _DIGEST.fullmatch(event.request_hash) is None:
            raise ValueError("INVALID_UNKNOWN_EVENT")
        if event.response_hash is not None and _DIGEST.fullmatch(event.response_hash) is None:
            raise ValueError("INVALID_UNKNOWN_EVENT")
        if _SHA.fullmatch(event.source_commit_sha) is None or not 1 <= event.attempt_count <= 1000:
            raise ValueError("INVALID_UNKNOWN_EVENT")
        if (type(event.human_readable_reason) is not str
                or not event.human_readable_reason
                or len(event.human_readable_reason) > 512):
            raise ValueError("INVALID_UNKNOWN_EVENT")

    @staticmethod
    def _append(path: Path, value: dict) -> None:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         sort_keys=True, separators=(",", ":")).encode() + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            current = os.fstat(descriptor)
            if not stat.S_ISREG(current.st_mode) or current.st_uid != os.getuid():
                raise ValueError("UNSAFE_QUARANTINE_MANIFEST")
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            os.write(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def record(self, event: UnknownEvent) -> str:
        self._validate_event(event)
        unknown_id = "unknown-" + uuid.uuid4().hex
        created = int(self.clock())
        artifact_name = unknown_id + ".json"
        artifact_path = self.artifacts / artifact_name
        artifact = json.dumps(redact_evidence(event.redacted_artifact), ensure_ascii=False,
                              allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        descriptor = os.open(
            artifact_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, artifact)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        record = {
            "unknown_id": unknown_id,
            "created_at_utc": created,
            "test_id_or_operation_id": event.test_or_operation_id,
            "provider": event.provider,
            "model": event.model,
            "request_hash": event.request_hash,
            "response_hash": event.response_hash,
            "safe_http_metadata": redact_evidence(event.safe_http_metadata),
            "parser_stage": event.parser_stage,
            "attempt_count": event.attempt_count,
            "reason_code": "UNKNOWN",
            "human_readable_reason": event.human_readable_reason,
            "redacted_artifact_path": "redacted/" + artifact_name,
            "source_commit_sha": event.source_commit_sha,
            "replay_status": "QUARANTINED_MANUAL_ONLY",
            "resolved_as": None,
            "resolved_at_utc": None,
        }
        self._append(self.manifest, record)
        return unknown_id

    def unresolved_ids(self) -> tuple[str, ...]:
        if not self.manifest.exists():
            return ()
        records = [json.loads(line) for line in self.manifest.read_text().splitlines() if line]
        return tuple(item["unknown_id"] for item in records if item["resolved_as"] is None)

    def request_manual_replay(self, unknown_id: str, new_operation_id: str,
                              *, confirmed: bool) -> str:
        if confirmed is not True or _ID.fullmatch(unknown_id or "") is None:
            raise ValueError("MANUAL_CONFIRMATION_REQUIRED")
        if _ID.fullmatch(new_operation_id or "") is None:
            raise ValueError("INVALID_NEW_OPERATION_ID")
        if unknown_id not in self.unresolved_ids():
            raise ValueError("UNKNOWN_ID_NOT_UNRESOLVED")
        attempt_id = "replay-attempt-" + uuid.uuid4().hex
        self._append(self.replays, {
            "attempt_id": attempt_id,
            "unknown_id": unknown_id,
            "new_operation_id": new_operation_id,
            "created_at_utc": int(self.clock()),
            "status": "REQUESTED_NOT_DISPATCHED",
            "automatic": False,
            "authority_granted": False,
        })
        return attempt_id
