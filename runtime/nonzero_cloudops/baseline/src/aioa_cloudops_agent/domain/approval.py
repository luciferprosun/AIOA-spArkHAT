"""Approval state kept separate from the execution lifecycle."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from .enums import ExecutionState
from .errors import ContractValidationError
from .identifiers import validate_correlation_id


class ApprovalStatus(StrEnum):
    """Explicit state of a human-approval record."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


def _validate_utc_timestamp(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractValidationError(f"{name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{name} must use UTC")


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Immutable approval state for a proposal within one execution."""

    correlation_id: UUID
    proposal_id: str
    status: ApprovalStatus
    requested_at: datetime
    resolved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID):
            raise ContractValidationError("approval correlation_id must be a UUID")
        validate_correlation_id(self.correlation_id)
        if not isinstance(self.proposal_id, str) or not self.proposal_id.strip():
            raise ContractValidationError("proposal_id must not be empty")
        if not isinstance(self.status, ApprovalStatus):
            raise ContractValidationError("status must be an ApprovalStatus")
        _validate_utc_timestamp("requested_at", self.requested_at)

        resolved_statuses = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED}
        if self.status in resolved_statuses:
            _validate_utc_timestamp("resolved_at", self.resolved_at)
            if self.resolved_at < self.requested_at:
                raise ContractValidationError("resolved_at must not precede requested_at")
        elif self.resolved_at is not None:
            raise ContractValidationError("unresolved approval status must not have resolved_at")


def validate_pending_approval_mapping(
    execution_state: ExecutionState,
    approval_status: ApprovalStatus,
) -> None:
    """Require PENDING execution state whenever approval is pending."""

    if not isinstance(execution_state, ExecutionState):
        raise ContractValidationError("execution_state must be an ExecutionState")
    if not isinstance(approval_status, ApprovalStatus):
        raise ContractValidationError("approval_status must be an ApprovalStatus")
    if (
        approval_status is ApprovalStatus.PENDING_APPROVAL
        and execution_state is not ExecutionState.PENDING
    ):
        raise ContractValidationError(
            "PENDING_APPROVAL requires execution_state PENDING"
        )
