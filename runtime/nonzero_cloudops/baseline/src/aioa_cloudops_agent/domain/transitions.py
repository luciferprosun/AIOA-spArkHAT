"""Pure validation for execution-state transitions."""

from typing import Final

from .enums import ExecutionState
from .errors import ContractValidationError, IllegalStateTransitionError

_ALLOWED_TRANSITIONS: Final[dict[ExecutionState, frozenset[ExecutionState]]] = {
    ExecutionState.INIT: frozenset({ExecutionState.RUNNING}),
    ExecutionState.RUNNING: frozenset(
        {
            ExecutionState.PENDING,
            ExecutionState.SUCCESS,
            ExecutionState.FAIL,
        }
    ),
    ExecutionState.PENDING: frozenset(
        {
            ExecutionState.RUNNING,
            ExecutionState.FAIL,
        }
    ),
    ExecutionState.SUCCESS: frozenset(),
    ExecutionState.FAIL: frozenset(),
}


def validate_state_transition(
    current_state: ExecutionState,
    next_state: ExecutionState,
) -> ExecutionState:
    """Return the next state when allowed, otherwise raise an explicit domain error."""

    if not isinstance(current_state, ExecutionState):
        raise ContractValidationError("current_state must be an ExecutionState")
    if not isinstance(next_state, ExecutionState):
        raise ContractValidationError("next_state must be an ExecutionState")
    if next_state not in _ALLOWED_TRANSITIONS[current_state]:
        raise IllegalStateTransitionError(current_state, next_state)
    return next_state
