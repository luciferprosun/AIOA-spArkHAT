"""Typed restart and reconciliation decisions derived only from durable truth."""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from aioa_cloudops_agent.agent.hitl import ApprovalInterrupt
from aioa_cloudops_agent.cloudops import Ec2InstanceState
from aioa_cloudops_agent.nz import (
    FailureDetail,
    NonEmptyText,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
    WorkflowState,
)
from aioa_cloudops_agent.verification import VerificationCompletion


class RecoveryAction(StrEnum):
    """Closed internal actions; none authorizes a new workload mutation."""

    RESUME_SAFE_STATE = "RESUME_SAFE_STATE"
    RESUME_PROPOSAL = "RESUME_PROPOSAL"
    RECONSTRUCT_APPROVAL = "RECONSTRUCT_APPROVAL"
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    RECONCILE_LOST_ACK = "RECONCILE_LOST_ACK"
    RESUME_VERIFICATION = "RESUME_VERIFICATION"
    RETURN_VERIFIED_RESULT = "RETURN_VERIFIED_RESULT"
    PRESERVE_TERMINAL = "PRESERVE_TERMINAL"
    OPERATOR_REVIEW = "OPERATOR_REVIEW"


class RecoveryStatus(StrEnum):
    """Caller-visible classification of the deterministic recovery decision."""

    RESUMABLE = "RESUMABLE"
    READY = "READY"
    RECONCILED = "RECONCILED"
    TERMINAL = "TERMINAL"
    OPERATOR_REQUIRED = "OPERATOR_REQUIRED"


class RecoveryRequest(BaseModel):
    """Opaque durable references only; conversational text is not accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier | None = None


class RecoveryOutcome(BaseModel):
    """Audited, typed result of one deterministic restart decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    proposal_id: Uuid7Identifier | None
    initial_state: WorkflowState
    final_state: WorkflowState
    status: RecoveryStatus
    action: RecoveryAction
    reason_code: ShortIdentifier
    reason: NonEmptyText
    audit_event_id: Uuid7Identifier
    approval_interrupt: ApprovalInterrupt | None = None
    verification: VerificationCompletion | None = None
    observed_state: Ec2InstanceState | None = None
    evidence_hash: Sha256Digest | None = None
    failure: FailureDetail | None = None
    ready_for_execution: bool = False
    reconciled: bool = False
    mutation_replayed: Literal[False] = False
    executor_calls: Literal[0] = 0

    @model_validator(mode="after")
    def validate_action_payload(self) -> Self:
        if (
            self.action is RecoveryAction.RECONSTRUCT_APPROVAL
            and self.approval_interrupt is None
        ):
            raise ValueError("approval reconstruction requires the durable interrupt")
        if self.action is RecoveryAction.RETURN_VERIFIED_RESULT and (
            self.evidence_hash is None
            or self.final_state is not WorkflowState.SUCCESS_WITH_EVIDENCE
        ):
            raise ValueError("verified recovery requires durable success evidence")
        if self.ready_for_execution != (self.action is RecoveryAction.READY_FOR_EXECUTION):
            raise ValueError("ready_for_execution must match the recovery action")
        if self.status is RecoveryStatus.OPERATOR_REQUIRED and self.failure is None:
            raise ValueError("operator-required recovery needs an explicit failure")
        return self
