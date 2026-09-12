import pytest

from aioa_cloudops_agent.domain import (
    ContractValidationError,
    ErrorCode,
    ExecutionState,
    IllegalStateTransitionError,
    validate_state_transition,
)


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (ExecutionState.INIT, ExecutionState.RUNNING),
        (ExecutionState.RUNNING, ExecutionState.PENDING),
        (ExecutionState.RUNNING, ExecutionState.SUCCESS),
        (ExecutionState.RUNNING, ExecutionState.FAIL),
        (ExecutionState.PENDING, ExecutionState.RUNNING),
        (ExecutionState.PENDING, ExecutionState.FAIL),
    ],
)
def test_valid_state_transitions_return_explicit_next_state(
    current_state: ExecutionState,
    next_state: ExecutionState,
) -> None:
    result = validate_state_transition(current_state, next_state)

    assert result is next_state
    assert result is not None


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (ExecutionState.INIT, ExecutionState.SUCCESS),
        (ExecutionState.INIT, ExecutionState.FAIL),
        (ExecutionState.RUNNING, ExecutionState.INIT),
        (ExecutionState.PENDING, ExecutionState.PENDING),
        (ExecutionState.PENDING, ExecutionState.SUCCESS),
    ],
)
def test_illegal_state_transitions_raise_typed_error(
    current_state: ExecutionState,
    next_state: ExecutionState,
) -> None:
    with pytest.raises(IllegalStateTransitionError) as captured:
        validate_state_transition(current_state, next_state)

    assert captured.value.code is ErrorCode.ILLEGAL_STATE_TRANSITION
    assert captured.value.current_state is current_state
    assert captured.value.next_state is next_state
    assert captured.value.retryable is False


@pytest.mark.parametrize("terminal_state", [ExecutionState.SUCCESS, ExecutionState.FAIL])
@pytest.mark.parametrize("next_state", list(ExecutionState))
def test_terminal_states_are_protected(
    terminal_state: ExecutionState,
    next_state: ExecutionState,
) -> None:
    with pytest.raises(IllegalStateTransitionError):
        validate_state_transition(terminal_state, next_state)


@pytest.mark.parametrize(
    ("current_state", "next_state"),
    [
        (None, ExecutionState.RUNNING),
        (ExecutionState.RUNNING, None),
        ("RUNNING", ExecutionState.SUCCESS),
        (ExecutionState.RUNNING, "SUCCESS"),
    ],
)
def test_transition_validation_rejects_missing_or_untyped_states(
    current_state: object,
    next_state: object,
) -> None:
    with pytest.raises(ContractValidationError):
        validate_state_transition(current_state, next_state)
