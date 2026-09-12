from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from aioa_cloudops_agent.domain import (
    ApprovalRecord,
    ApprovalStatus,
    ContractValidationError,
    ExecutionState,
    generate_correlation_id,
    validate_correlation_id,
    validate_pending_approval_mapping,
)

UUID7 = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def test_generated_correlation_identifier_is_real_uuid7() -> None:
    correlation_id = generate_correlation_id()

    assert isinstance(correlation_id, UUID)
    assert correlation_id.version == 7
    assert validate_correlation_id(correlation_id) is correlation_id


def test_uuid7_string_is_validated_without_version_substitution() -> None:
    assert validate_correlation_id(str(UUID7)) == UUID7


@pytest.mark.parametrize("invalid_value", [uuid4(), "not-a-uuid", None, 7])
def test_non_uuid7_correlation_identifiers_fail_explicitly(invalid_value: object) -> None:
    with pytest.raises(ContractValidationError, match="UUIDv7"):
        validate_correlation_id(invalid_value)


def test_approval_status_values_are_separate_and_canonical() -> None:
    assert [status.value for status in ApprovalStatus] == [
        "NOT_REQUIRED",
        "PENDING_APPROVAL",
        "APPROVED",
        "REJECTED",
    ]


def test_pending_approval_requires_pending_execution_state() -> None:
    validate_pending_approval_mapping(ExecutionState.PENDING, ApprovalStatus.PENDING_APPROVAL)

    with pytest.raises(ContractValidationError, match="execution_state PENDING"):
        validate_pending_approval_mapping(
            ExecutionState.RUNNING,
            ApprovalStatus.PENDING_APPROVAL,
        )


def test_pending_approval_record_is_typed_and_immutable() -> None:
    record = ApprovalRecord(
        correlation_id=UUID7,
        proposal_id="proposal-001",
        status=ApprovalStatus.PENDING_APPROVAL,
        requested_at=NOW,
    )

    assert record.resolved_at is None
    with pytest.raises(FrozenInstanceError):
        record.status = ApprovalStatus.APPROVED


def test_resolved_approval_requires_valid_utc_resolution_time() -> None:
    with pytest.raises(ContractValidationError, match="resolved_at"):
        ApprovalRecord(
            correlation_id=UUID7,
            proposal_id="proposal-001",
            status=ApprovalStatus.APPROVED,
            requested_at=NOW,
        )

    with pytest.raises(ContractValidationError, match="must use UTC"):
        ApprovalRecord(
            correlation_id=UUID7,
            proposal_id="proposal-001",
            status=ApprovalStatus.REJECTED,
            requested_at=NOW,
            resolved_at=NOW.astimezone(timezone(timedelta(hours=2))),
        )
