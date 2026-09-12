"""Typed records persisted by the Non-Zero state layer."""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from uuid import UUID

from aioa_cloudops_agent.domain.enums import AuthorityGate, ExecutionState
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SENSITIVE_ATTRIBUTE_TERMS = ("credential", "password", "secret", "token")


def validate_utc_timestamp(name: str, value: object) -> datetime:
    """Return a timezone-aware UTC timestamp or fail explicitly."""

    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractValidationError(f"{name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{name} must use UTC")
    return value


def compute_evidence_digest(payload: object) -> str:
    """Return SHA-256 over deterministic JSON without accepting ambiguous values."""

    try:
        canonical_payload = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractValidationError("evidence payload must be canonical JSON data") from error
    return hashlib.sha256(canonical_payload).hexdigest()


def validate_evidence_digest(value: object) -> str:
    """Return a lowercase SHA-256 digest or fail explicitly."""

    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ContractValidationError("evidence_digest must be a lowercase SHA-256 digest")
    return value


def _validate_non_empty_text(name: str, value: object, *, maximum: int = 1_024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ContractValidationError(f"{name} must not contain surrounding whitespace")
    if len(value) > maximum:
        raise ContractValidationError(f"{name} must not exceed {maximum} characters")
    return value


class ProvenanceEventType(StrEnum):
    """Closed set of currently persisted provenance event types."""

    EXECUTION_CREATED = "EXECUTION_CREATED"
    EXECUTION_STATE_CHANGED = "EXECUTION_STATE_CHANGED"
    CLOUDOPS_INSTANCE_INSPECTED = "CLOUDOPS_INSTANCE_INSPECTED"
    APPROVAL_STATE_CHANGED = "APPROVAL_STATE_CHANGED"


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Versioned execution metadata with an explicit lifecycle state."""

    correlation_id: UUID
    idempotency_key: str
    execution_state: ExecutionState
    authority_gate: AuthorityGate
    created_at: datetime
    updated_at: datetime
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID):
            raise ContractValidationError("correlation_id must be a UUIDv7 value")
        validate_correlation_id(self.correlation_id)
        _validate_non_empty_text("idempotency_key", self.idempotency_key, maximum=256)
        if not isinstance(self.execution_state, ExecutionState):
            raise ContractValidationError("execution_state must be an ExecutionState")
        if not isinstance(self.authority_gate, AuthorityGate):
            raise ContractValidationError("authority_gate must be an AuthorityGate")
        validate_utc_timestamp("created_at", self.created_at)
        validate_utc_timestamp("updated_at", self.updated_at)
        if self.updated_at < self.created_at:
            raise ContractValidationError("updated_at must not precede created_at")
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version <= 0:
            raise ContractValidationError("version must be a positive integer")


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    """Create-only ownership of a client-provided execution key."""

    correlation_id: UUID
    idempotency_key: str
    claimed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID):
            raise ContractValidationError("correlation_id must be a UUIDv7 value")
        validate_correlation_id(self.correlation_id)
        _validate_non_empty_text("idempotency_key", self.idempotency_key, maximum=256)
        validate_utc_timestamp("claimed_at", self.claimed_at)


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    """Immutable, append-oriented evidence for one execution event."""

    correlation_id: UUID
    event_id: str
    event_type: ProvenanceEventType
    sequence: int
    timestamp: datetime
    actor: str
    summary: str
    evidence_digest: str | None = None
    attributes: Mapping[str, str] | tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID):
            raise ContractValidationError("correlation_id must be a UUIDv7 value")
        validate_correlation_id(self.correlation_id)
        _validate_non_empty_text("event_id", self.event_id, maximum=256)
        if not isinstance(self.event_type, ProvenanceEventType):
            raise ContractValidationError("event_type must be a ProvenanceEventType")
        if isinstance(self.sequence, bool) or not isinstance(self.sequence, int) or self.sequence <= 0:
            raise ContractValidationError("sequence must be a positive integer")
        validate_utc_timestamp("timestamp", self.timestamp)
        _validate_non_empty_text("actor", self.actor, maximum=256)
        _validate_non_empty_text("summary", self.summary, maximum=2_048)
        if self.evidence_digest is not None:
            validate_evidence_digest(self.evidence_digest)

        if isinstance(self.attributes, Mapping):
            attribute_items: tuple[object, ...] = tuple(self.attributes.items())
        elif isinstance(self.attributes, tuple):
            attribute_items = self.attributes
        else:
            raise ContractValidationError("attributes must be a mapping or tuple of string pairs")

        normalized_attributes: dict[str, str] = {}
        for item in attribute_items:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ContractValidationError("attributes must contain string key/value pairs")
            key, value = item
            valid_key = _validate_non_empty_text("attribute key", key, maximum=128)
            valid_value = _validate_non_empty_text("attribute value", value, maximum=2_048)
            lowered_key = valid_key.casefold()
            if any(term in lowered_key for term in _SENSITIVE_ATTRIBUTE_TERMS):
                raise ContractValidationError("sensitive provenance attribute keys are prohibited")
            if valid_key in normalized_attributes:
                raise ContractValidationError("provenance attribute keys must be unique")
            normalized_attributes[valid_key] = valid_value

        object.__setattr__(
            self,
            "attributes",
            MappingProxyType(dict(sorted(normalized_attributes.items()))),
        )
