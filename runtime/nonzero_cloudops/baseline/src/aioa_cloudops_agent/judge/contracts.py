"""Public, redacted contracts for the bounded Day 15 judge surface."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from aioa_cloudops_agent.nz import Sha256Digest, WorkflowState
from aioa_cloudops_agent.nz.identifiers import Uuid7Identifier


class JudgeErrorCode(StrEnum):
    """Stable public taxonomy; provider and exception text never crosses HTTP."""

    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    UNAUTHORIZED = "UNAUTHORIZED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    NOT_READY = "NOT_READY"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    INVESTIGATION_DENIED = "INVESTIGATION_DENIED"
    INVESTIGATION_INVALID = "INVESTIGATION_INVALID"
    EVIDENCE_AMBIGUOUS = "EVIDENCE_AMBIGUOUS"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class JudgeOutcomeClass(StrEnum):
    """Bounded truth classes returned by one investigation request."""

    REMEDIATION_PROPOSED = "remediation_proposed"
    CLOSED_NON_SUCCESS = "closed_non_success"
    EVIDENCE_AMBIGUOUS = "evidence_ambiguous"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    RECOVERY_REQUIRED = "recovery_required"


class JudgeInvestigationOutcome(BaseModel):
    """Sanitized result with no target, prompt, tool arguments, or provider body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    succeeded: bool
    state: WorkflowState | None = None
    outcome_class: JudgeOutcomeClass
    proposal_id: Uuid7Identifier | None = None
    evidence_hash: Sha256Digest | None = None
    error_code: JudgeErrorCode | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def validate_result_shape(self) -> Self:
        if self.succeeded:
            if (
                self.state is not WorkflowState.REMEDIATION_PROPOSED
                or self.outcome_class is not JudgeOutcomeClass.REMEDIATION_PROPOSED
                or self.proposal_id is None
                or self.evidence_hash is None
                or self.error_code is not None
                or self.retryable
            ):
                raise ValueError("successful investigation result is incomplete")
        elif (
            self.proposal_id is not None
            or self.evidence_hash is not None
            or self.error_code is None
        ):
            raise ValueError("failed investigation result exposes inconsistent evidence")
        return self


class JudgeErrorResponse(BaseModel):
    """Minimal caller-visible error without exception or configuration detail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error: JudgeErrorCode
    run_id: UUID | None = None
    retryable: bool = False


class JudgeReadinessResponse(BaseModel):
    """Identifier-free readiness response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"]
