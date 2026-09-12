from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from aioa_cloudops_agent.domain import AuthorityGate, ContractValidationError, ExecutionState
from aioa_cloudops_agent.persistence import (
    ExecutionRecord,
    ProvenanceEventType,
    ProvenanceRecord,
    approval_key,
    compute_evidence_digest,
    execution_key,
    idempotency_key,
    provenance_key,
)

UUID7 = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def _execution_record(**overrides: object) -> ExecutionRecord:
    values: dict[str, object] = {
        "correlation_id": UUID7,
        "idempotency_key": "request-001",
        "execution_state": ExecutionState.INIT,
        "authority_gate": AuthorityGate.AUTO,
        "created_at": NOW,
        "updated_at": NOW,
        "version": 1,
    }
    values.update(overrides)
    return ExecutionRecord(**values)


def test_execution_record_contains_explicit_versioned_lifecycle() -> None:
    record = _execution_record()

    assert record.execution_state is ExecutionState.INIT
    assert record.version == 1
    assert record.created_at.tzinfo is UTC


def test_execution_record_requires_typed_uuid7() -> None:
    with pytest.raises(ContractValidationError, match="UUIDv7"):
        _execution_record(correlation_id=str(UUID7))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_state", None),
        ("execution_state", "INIT"),
        ("version", 0),
        ("version", True),
        ("idempotency_key", ""),
        ("created_at", datetime(2026, 8, 23, 10, 0)),
        ("updated_at", datetime(2026, 8, 23, 9, 59, tzinfo=UTC)),
    ],
)
def test_execution_record_rejects_ambiguous_or_invalid_values(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ContractValidationError):
        _execution_record(**{field: value})


def test_dynamodb_keys_are_deterministic_and_ordered() -> None:
    assert execution_key(UUID7).as_item() == {
        "PK": {"S": f"EXEC#{UUID7}"},
        "SK": {"S": "META"},
    }
    assert provenance_key(UUID7, 42, "event-42").sort_key == (
        "EVT#00000000000000000042#event-42"
    )
    assert approval_key(UUID7, "proposal-1").sort_key == "APPROVAL#proposal-1"
    assert idempotency_key("request-001").as_item() == {
        "PK": {"S": "IDEMP#request-001"},
        "SK": {"S": "LOCK"},
    }
    with pytest.raises(ContractValidationError, match="UUIDv7"):
        execution_key(str(UUID7))


def test_evidence_digest_is_deterministic_for_canonical_json() -> None:
    first = compute_evidence_digest({"region": "eu-central-1", "count": 2})
    second = compute_evidence_digest({"count": 2, "region": "eu-central-1"})

    assert first == second
    assert len(first) == 64


def test_non_json_or_non_finite_evidence_is_rejected() -> None:
    with pytest.raises(ContractValidationError, match="canonical JSON"):
        compute_evidence_digest({"value": object()})
    with pytest.raises(ContractValidationError, match="canonical JSON"):
        compute_evidence_digest({"value": float("nan")})


def test_provenance_record_is_immutable_and_rejects_secret_fields() -> None:
    record = ProvenanceRecord(
        correlation_id=UUID7,
        event_id="event-001",
        event_type=ProvenanceEventType.EXECUTION_CREATED,
        sequence=1,
        timestamp=NOW,
        actor="execution-service",
        summary="Execution metadata created",
        evidence_digest=compute_evidence_digest({"state": "INIT"}),
        attributes={"state": "INIT"},
    )

    assert dict(record.attributes) == {"state": "INIT"}
    with pytest.raises(TypeError):
        record.attributes["state"] = "SUCCESS"
    with pytest.raises(FrozenInstanceError):
        record.sequence = 2

    with pytest.raises(ContractValidationError, match="sensitive"):
        ProvenanceRecord(
            correlation_id=UUID7,
            event_id="event-002",
            event_type=ProvenanceEventType.EXECUTION_CREATED,
            sequence=2,
            timestamp=NOW,
            actor="execution-service",
            summary="Unsafe event",
            attributes={"session_token": "prohibited"},
        )


def test_provenance_timestamp_must_be_utc() -> None:
    with pytest.raises(ContractValidationError, match="must use UTC"):
        ProvenanceRecord(
            correlation_id=UUID7,
            event_id="event-003",
            event_type=ProvenanceEventType.EXECUTION_CREATED,
            sequence=3,
            timestamp=NOW.astimezone(timezone(timedelta(hours=1))),
            actor="execution-service",
            summary="Invalid timestamp",
        )


def test_malformed_provenance_attribute_pair_fails_explicitly() -> None:
    with pytest.raises(ContractValidationError, match="key/value pairs"):
        ProvenanceRecord(
            correlation_id=UUID7,
            event_id="event-004",
            event_type=ProvenanceEventType.EXECUTION_CREATED,
            sequence=4,
            timestamp=NOW,
            actor="execution-service",
            summary="Malformed attributes",
            attributes=(("state", "INIT", "unexpected"),),
        )
