"""AIOA mobile-to-home bridge P0: transport-neutral READ admission.

This is an untrusted message envelope / local policy adapter, NOT an executor,
a human approval channel, a cloud service or an authentication mechanism.

Designed for both ChatGPT on Android and a future native/PWA AIOA client.
A future Nebius relay may pass these packets to a home worker over an
OUTBOUND-ONLY authenticated connection. Cloud packets grant NO authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import threading
from typing import Any, Mapping
import uuid

from .adapter import admit_commander_result, build_task
from .contracts import ContractError, RiskClass, TaskEnvelope, TaskResult, TaskState
from .policy import PolicyEffect, evaluate_task

PROTOCOL_VERSION = "aioa.mobile-nebius-bridge.v1"
MAX_PACKET_BYTES = 4096
MAX_TTL_SECONDS = 300
MAX_FUTURE_SKEW_SECONDS = 30
MAX_SEQUENCE = (1 << 63) - 1
# A very narrow first working slice; raw file/artifact/diff content cannot
# cross into a mobile relay until its own safe, typed projection is reviewed.
MOBILE_READ_ALLOWLIST = frozenset({"system.status", "git.status"})
ORIGINS = frozenset({"android-chatgpt", "aioa-android", "aioa-web"})
_REQUIRED_KEYS = frozenset({
    "version", "kind", "peer_id", "session_id", "message_id",
    "sequence", "created_at", "expires_at", "origin", "operation",
    "payload", "fingerprint",
})
_UUID_PATTERN = re.compile(r"^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$")
_PEER_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_HEX_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _utc(value: str, name: str) -> datetime:
    # Strict UTC on the wire: no timezone ambiguity, offsets, or local time.
    if type(value) is not str or not re.fullmatch(
        r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value
    ):
        raise ContractError(f"{name} must be UTC with second precision")
    try:
        result = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        return result.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ContractError(f"{name} is an invalid timestamp") from exc


def _uuid(value: Any, name: str) -> str:
    if type(value) is not str or _UUID_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{name} must be a canonical UUID")
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError()
    except ValueError as exc:
        raise ContractError(f"{name} is an invalid UUID") from exc
    return value


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("non-canonical packet") from exc


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, value in pairs:
        if name in data:
            raise ContractError("duplicate JSON key")
        data[name] = value
    return data


def _forbid_nonfinite(value: str) -> None:
    raise ContractError("non-finite number")


@dataclass(frozen=True)
class MobileReadRequest:
    """One READ proposal; fingerprint is integrity ONLY, not authentication.

    The trusted transport must separately authenticate the peer and bind the
    peer_id to that connection. The model cannot self-assert human authority.
    """

    peer_id: str
    session_id: str
    message_id: str
    sequence: int
    created_at: str
    expires_at: str
    origin: str
    operation: str
    payload: dict[str, Any]
    version: str = PROTOCOL_VERSION
    kind: str = "READ_REQUEST"

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION or self.kind != "READ_REQUEST":
            raise ContractError("unsupported remote bridge version/kind")
        if type(self.peer_id) is not str or not _PEER_PATTERN.fullmatch(self.peer_id):
            raise ContractError("invalid peer id")
        _uuid(self.session_id, "session_id")
        _uuid(self.message_id, "message_id")
        if type(self.sequence) is not int or not 1 <= self.sequence <= MAX_SEQUENCE:
            raise ContractError("invalid sequence")
        if self.origin not in ORIGINS:
            raise ContractError("unknown mobile origin")
        if self.operation not in MOBILE_READ_ALLOWLIST:
            raise ContractError("remote operation is not in READ allowlist")
        if type(self.payload) is not dict:
            raise ContractError("mobile payload must be an object")
        created, expires = _utc(self.created_at, "created_at"), _utc(self.expires_at, "expires_at")
        ttl = (expires - created).total_seconds()
        if not 0 < ttl <= MAX_TTL_SECONDS:
            raise ContractError("invalid request lifetime")
        # Reuse existing Commander payload and task contract; no new authority.
        build_task(self.operation, self.payload, source="aioa-mobile-bridge")

    def _unsigned(self) -> dict[str, Any]:
        return {
            "version": self.version, "kind": self.kind,
            "peer_id": self.peer_id, "session_id": self.session_id,
            "message_id": self.message_id, "sequence": self.sequence,
            "created_at": self.created_at, "expires_at": self.expires_at,
            "origin": self.origin, "operation": self.operation,
            "payload": self.payload,
        }

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(_canonical(self._unsigned())).hexdigest()

    def encode(self) -> bytes:
        wire = _canonical({**self._unsigned(), "fingerprint": self.fingerprint})
        if len(wire) > MAX_PACKET_BYTES:
            raise ContractError("bridge packet exceeds limit")
        return wire

    @classmethod
    def decode(cls, wire: bytes) -> "MobileReadRequest":
        if type(wire) is not bytes or len(wire) > MAX_PACKET_BYTES:
            raise ContractError("bridge packet exceeds limit or is not bytes")
        try:
            packet = json.loads(wire.decode("utf-8"), object_pairs_hook=_strict_pairs,
                                parse_constant=_forbid_nonfinite)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ContractError("invalid bridge JSON") from exc
        if type(packet) is not dict or set(packet) != _REQUIRED_KEYS:
            raise ContractError("bridge requires exact fields")
        provided = packet.pop("fingerprint")
        if type(provided) is not str or not _HEX_PATTERN.fullmatch(provided):
            raise ContractError("invalid packet fingerprint")
        try:
            request = cls(**packet)
        except TypeError as exc:
            raise ContractError("invalid bridge payload") from exc
        if provided != request.fingerprint:
            raise ContractError("bridge packet fingerprint mismatch")
        return request


class ReadOnlyMobileIngress:
    """Process-local replay guard only. Remote durable storage is NOT supplied.

    IMPORTANT: in production, the authenticated relay AND home worker must
    persist idempotency and replay state across restarts. Existing Core/PCAF
    remains the only authority if non-READ functions are added in the future.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_sequence: dict[tuple[str, str], int] = {}
        self._seen_messages: set[tuple[str, str]] = set()

    def admit(
        self,
        wire: bytes,
        *,
        authenticated_peer_id: str | None,
        now: datetime | None = None,
    ) -> TaskEnvelope:
        if authenticated_peer_id is None:
            raise ContractError("transport authentication required")
        request = MobileReadRequest.decode(wire)
        if request.peer_id != authenticated_peer_id:
            raise ContractError("transport peer mismatch")
        clock = now or datetime.now(timezone.utc)
        if clock.tzinfo is None:
            raise ContractError("trusted clock must be timezone-aware")
        clock = clock.astimezone(timezone.utc)
        if clock < _utc(request.created_at, "created_at") - timedelta(seconds=MAX_FUTURE_SKEW_SECONDS):
            raise ContractError("packet timestamp is in the future")
        if clock > _utc(request.expires_at, "expires_at"):
            raise ContractError("mobile request expired")
        task = build_task(
            request.operation, dict(request.payload),
            target_project="commander",
            task_id=request.message_id,
            idempotency_key=request.fingerprint,
            source="aioa-mobile-bridge",
        )
        if task.risk is not RiskClass.READ or evaluate_task(task).effect is not PolicyEffect.ALLOW:
            raise ContractError("existing Core READ policy denied request")

        key = (request.peer_id, request.session_id)
        message_key = (request.peer_id, request.message_id)
        with self._lock:
            if message_key in self._seen_messages:
                raise ContractError("duplicate mobile message")
            if request.sequence <= self._last_sequence.get(key, 0):
                raise ContractError("replayed mobile sequence")
            self._seen_messages.add(message_key)
            self._last_sequence[key] = request.sequence
        return task


def project_mobile_result(task: TaskEnvelope, result: TaskResult) -> dict[str, Any]:
    """Projection only. NEVER forward raw Commander output or approval records."""
    if task.task_id != result.task_id or task.risk is not RiskClass.READ:
        raise ContractError("result task binding mismatch")
    if task.operation not in MOBILE_READ_ALLOWLIST:
        raise ContractError("result operation not allowed")
    # State is from existing wire contract; summary, filenames, artifacts,
    # audit refs, metadata and any model text are deliberately discarded.
    observation = admit_commander_result(result)
    return {
        "version": PROTOCOL_VERSION,
        "message_id": task.task_id,
        "state": result.state.value,
        "advisory_authority": observation.authority,
        "can_authorize_effects": False,
        "requires_owner_attention": result.state is TaskState.WAITING_FOR_HUMAN,
        "detail": "Redacted at mobile bridge P0",
    }
