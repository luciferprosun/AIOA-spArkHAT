"""Canonical failure-to-workflow mapping and redacted boundary failures."""

from enum import StrEnum
from typing import Final

from aioa_cloudops_agent.nz import FailureDetail, FailureKind, WorkflowState

FAILURE_WORKFLOW_STATE: Final[dict[FailureKind, WorkflowState]] = {
    FailureKind.VALIDATION_FAILURE: WorkflowState.MODEL_OUTPUT_INVALID,
    FailureKind.POLICY_DENIAL: WorkflowState.DENIED_BY_POLICY,
    FailureKind.AMBIGUOUS_RESULT: WorkflowState.AMBIGUOUS_RESULT,
    FailureKind.DEPENDENCY_UNAVAILABLE: WorkflowState.DEPENDENCY_UNAVAILABLE,
    FailureKind.BUDGET_EXHAUSTION: WorkflowState.BUDGET_EXHAUSTED,
    FailureKind.EXECUTION_FAILURE: WorkflowState.EXECUTION_FAILED,
    FailureKind.VERIFICATION_FAILURE: WorkflowState.VERIFICATION_FAILED,
    FailureKind.RECOVERY_REQUIREMENT: WorkflowState.RECOVERY_REQUIRED,
    FailureKind.ILLEGAL_STATE_TRANSITION: WorkflowState.RECOVERY_REQUIRED,
    FailureKind.PROVIDER_FAILURE: WorkflowState.DEPENDENCY_UNAVAILABLE,
    FailureKind.TOOL_ADAPTER_FAILURE: WorkflowState.DEPENDENCY_UNAVAILABLE,
    FailureKind.STORAGE_FAILURE: WorkflowState.DEPENDENCY_UNAVAILABLE,
    FailureKind.IDEMPOTENCY_CONFLICT: WorkflowState.RECOVERY_REQUIRED,
    FailureKind.NOT_FOUND: WorkflowState.AMBIGUOUS_RESULT,
    FailureKind.CONFIGURATION_ERROR: WorkflowState.DENIED_BY_POLICY,
}


class BoundaryRisk(StrEnum):
    """How an unknown exception must fail at a control boundary."""

    READ_ONLY = "READ_ONLY"
    DURABLE_CONTROL = "DURABLE_CONTROL"
    MUTATION_OUTCOME_UNKNOWN = "MUTATION_OUTCOME_UNKNOWN"


def workflow_state_for_failure(failure: FailureDetail | FailureKind) -> WorkflowState:
    """Return the one durable state assigned to a typed failure category."""

    kind = failure.kind if isinstance(failure, FailureDetail) else failure
    if not isinstance(kind, FailureKind):
        raise TypeError("failure must be FailureDetail or FailureKind")
    return FAILURE_WORKFLOW_STATE[kind]


def redacted_unknown_failure(
    boundary: BoundaryRisk,
    error: Exception | None = None,
) -> FailureDetail:
    """Translate an unexpected exception without retaining its message or secrets."""

    if not isinstance(boundary, BoundaryRisk):
        raise TypeError("boundary must be BoundaryRisk")
    if error is not None and not isinstance(error, Exception):
        raise TypeError("error must be an Exception when provided")
    if boundary is BoundaryRisk.MUTATION_OUTCOME_UNKNOWN:
        return FailureDetail(
            kind=FailureKind.RECOVERY_REQUIREMENT,
            code="MUTATION_OUTCOME_UNKNOWN",
            message="Mutation outcome is unknown and requires durable reconciliation",
            retryable=False,
        )
    if boundary is BoundaryRisk.DURABLE_CONTROL:
        return FailureDetail(
            kind=FailureKind.DEPENDENCY_UNAVAILABLE,
            code="DURABLE_CONTROL_UNAVAILABLE",
            message="Durable control dependency is unavailable",
            retryable=True,
        )
    return FailureDetail(
        kind=FailureKind.DEPENDENCY_UNAVAILABLE,
        code="READ_DEPENDENCY_UNAVAILABLE",
        message="Read-only dependency is unavailable",
        retryable=True,
    )
