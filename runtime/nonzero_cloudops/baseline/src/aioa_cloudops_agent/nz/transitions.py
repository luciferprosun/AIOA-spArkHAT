"""Application-owned legal transition table for the canonical workflow."""

from typing import Final

from .enums import TERMINAL_WORKFLOW_STATES, WorkflowState
from .errors import WorkflowTransitionError

_COMMON_INVESTIGATION_FAILURES: Final[frozenset[WorkflowState]] = frozenset(
    {
        WorkflowState.DENIED_BY_POLICY,
        WorkflowState.MODEL_OUTPUT_INVALID,
        WorkflowState.AMBIGUOUS_RESULT,
        WorkflowState.DEPENDENCY_UNAVAILABLE,
        WorkflowState.BUDGET_EXHAUSTED,
        WorkflowState.RECOVERY_REQUIRED,
    }
)

ALLOWED_WORKFLOW_TRANSITIONS: Final[dict[WorkflowState, frozenset[WorkflowState]]] = {
    WorkflowState.RECEIVED: frozenset(
        {
            WorkflowState.INVESTIGATING,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.MODEL_OUTPUT_INVALID,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.BUDGET_EXHAUSTED,
        }
    ),
    WorkflowState.INVESTIGATING: frozenset(
        {WorkflowState.EVIDENCE_READY, *_COMMON_INVESTIGATION_FAILURES}
    ),
    WorkflowState.EVIDENCE_READY: frozenset(
        {
            WorkflowState.REMEDIATION_PROPOSED,
            WorkflowState.NO_ACTION_REQUIRED,
            WorkflowState.RECOMMENDATION_ONLY,
            WorkflowState.DENIED_BY_POLICY,
            *_COMMON_INVESTIGATION_FAILURES,
        }
    ),
    WorkflowState.REMEDIATION_PROPOSED: frozenset(
        {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.RECOVERY_REQUIRED,
        }
    ),
    WorkflowState.AWAITING_APPROVAL: frozenset(
        {
            WorkflowState.APPROVED,
            WorkflowState.DENIED_BY_HUMAN,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.MODEL_OUTPUT_INVALID,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.BUDGET_EXHAUSTED,
            WorkflowState.RECOVERY_REQUIRED,
        }
    ),
    WorkflowState.APPROVED: frozenset(
        {
            WorkflowState.EXECUTING,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.RECOVERY_REQUIRED,
        }
    ),
    WorkflowState.EXECUTING: frozenset(
        {
            WorkflowState.VERIFYING,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.EXECUTION_FAILED,
            WorkflowState.AMBIGUOUS_RESULT,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.BUDGET_EXHAUSTED,
            WorkflowState.RECOVERY_REQUIRED,
        }
    ),
    WorkflowState.VERIFYING: frozenset(
        {
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.MODEL_OUTPUT_INVALID,
            WorkflowState.VERIFICATION_FAILED,
            WorkflowState.AMBIGUOUS_RESULT,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.BUDGET_EXHAUSTED,
            WorkflowState.RECOVERY_REQUIRED,
        }
    ),
    WorkflowState.RECOVERY_REQUIRED: frozenset(
        {
            WorkflowState.VERIFYING,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.VERIFICATION_FAILED,
        }
    ),
    **{state: frozenset() for state in TERMINAL_WORKFLOW_STATES},
}


def validate_workflow_transition(
    current_state: WorkflowState,
    next_state: WorkflowState,
) -> WorkflowState:
    """Return the next state only when the closed transition table allows it."""

    if not isinstance(current_state, WorkflowState) or not isinstance(
        next_state, WorkflowState
    ):
        raise WorkflowTransitionError("unknown workflow state is denied")
    if next_state not in ALLOWED_WORKFLOW_TRANSITIONS[current_state]:
        raise WorkflowTransitionError(
            f"illegal workflow transition: {current_state.value} -> {next_state.value}"
        )
    return next_state
