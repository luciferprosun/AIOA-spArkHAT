from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from aioa_cloudops_agent.nz import (
    TERMINAL_WORKFLOW_STATES,
    BudgetCounters,
    Run,
    WorkflowState,
    WorkflowTransitionError,
    transition_run,
    validate_workflow_transition,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _run() -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="request:idle-ec2:0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
    )


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (WorkflowState.RECEIVED, WorkflowState.INVESTIGATING),
        (WorkflowState.INVESTIGATING, WorkflowState.EVIDENCE_READY),
        (WorkflowState.EVIDENCE_READY, WorkflowState.REMEDIATION_PROPOSED),
        (WorkflowState.REMEDIATION_PROPOSED, WorkflowState.AWAITING_APPROVAL),
        (WorkflowState.AWAITING_APPROVAL, WorkflowState.APPROVED),
        (WorkflowState.APPROVED, WorkflowState.EXECUTING),
        (WorkflowState.EXECUTING, WorkflowState.VERIFYING),
        (WorkflowState.VERIFYING, WorkflowState.SUCCESS_WITH_EVIDENCE),
    ],
)
def test_canonical_progression_is_explicitly_legal(
    current: WorkflowState,
    next_state: WorkflowState,
) -> None:
    assert validate_workflow_transition(current, next_state) is next_state


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (WorkflowState.RECEIVED, WorkflowState.EXECUTING),
        (WorkflowState.REMEDIATION_PROPOSED, WorkflowState.APPROVED),
        (WorkflowState.REMEDIATION_PROPOSED, WorkflowState.EXECUTING),
        (WorkflowState.AWAITING_APPROVAL, WorkflowState.EXECUTING),
        (WorkflowState.EXECUTING, WorkflowState.SUCCESS_WITH_EVIDENCE),
        (WorkflowState.VERIFYING, WorkflowState.APPROVED),
    ],
)
def test_approval_and_verification_cannot_be_skipped(
    current: WorkflowState,
    next_state: WorkflowState,
) -> None:
    with pytest.raises(WorkflowTransitionError):
        validate_workflow_transition(current, next_state)


@pytest.mark.parametrize("terminal_state", sorted(TERMINAL_WORKFLOW_STATES, key=str))
def test_terminal_states_cannot_reenter_active_execution(
    terminal_state: WorkflowState,
) -> None:
    with pytest.raises(WorkflowTransitionError):
        validate_workflow_transition(terminal_state, WorkflowState.INVESTIGATING)


@pytest.mark.parametrize(
    ("current", "next_state"),
    [
        (WorkflowState.DENIED_BY_HUMAN, WorkflowState.EXECUTING),
        (WorkflowState.EXECUTION_FAILED, WorkflowState.SUCCESS_WITH_EVIDENCE),
        (WorkflowState.VERIFICATION_FAILED, WorkflowState.SUCCESS_WITH_EVIDENCE),
        (WorkflowState.SUCCESS_WITH_EVIDENCE, WorkflowState.EXECUTING),
    ],
)
def test_b4_illegal_terminal_reentry_matrix_fails_closed(
    current: WorkflowState,
    next_state: WorkflowState,
) -> None:
    with pytest.raises(WorkflowTransitionError):
        validate_workflow_transition(current, next_state)


def test_unknown_state_fails_closed() -> None:
    with pytest.raises(WorkflowTransitionError, match="unknown workflow state"):
        validate_workflow_transition("RECEIVED", WorkflowState.INVESTIGATING)


def test_run_advances_as_new_immutable_versions() -> None:
    original = _run()
    investigating = transition_run(
        original,
        WorkflowState.INVESTIGATING,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert original.state is WorkflowState.RECEIVED
    assert original.version == 1
    assert investigating.state is WorkflowState.INVESTIGATING
    assert investigating.version == 2


def test_success_with_evidence_requires_the_complete_legal_path() -> None:
    run = _run()
    path = (
        WorkflowState.INVESTIGATING,
        WorkflowState.EVIDENCE_READY,
        WorkflowState.REMEDIATION_PROPOSED,
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.APPROVED,
        WorkflowState.EXECUTING,
        WorkflowState.VERIFYING,
        WorkflowState.SUCCESS_WITH_EVIDENCE,
    )
    for index, state in enumerate(path, start=1):
        run = transition_run(run, state, updated_at=NOW + timedelta(seconds=index))

    assert run.state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert run.version == 9


def test_success_with_evidence_cannot_be_created_by_invalid_transition() -> None:
    run = transition_run(
        _run(),
        WorkflowState.INVESTIGATING,
        updated_at=NOW + timedelta(seconds=1),
    )

    with pytest.raises(WorkflowTransitionError):
        transition_run(
            run,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            updated_at=NOW + timedelta(seconds=2),
        )
