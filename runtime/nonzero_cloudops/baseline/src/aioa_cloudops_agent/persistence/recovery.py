"""Conservative restart classification built only from durable state."""

from aioa_cloudops_agent.nz import (
    TERMINAL_WORKFLOW_STATES,
    Checkpoint,
    RecoveryDisposition,
    Run,
    WorkflowState,
)


def classify_recovery(run: Run | None, checkpoint: Checkpoint | None) -> RecoveryDisposition:
    """Classify state without pretending that full reconciliation is implemented."""

    if run is None:
        return RecoveryDisposition.NEW_RUN
    if run.state in TERMINAL_WORKFLOW_STATES:
        return RecoveryDisposition.TERMINAL_RUN
    if run.state is WorkflowState.AWAITING_APPROVAL:
        return RecoveryDisposition.AWAITING_APPROVAL
    if run.state in {WorkflowState.EXECUTING, WorkflowState.VERIFYING}:
        return RecoveryDisposition.RECONCILIATION_REQUIRED
    if checkpoint is None or checkpoint.run_id != run.run_id:
        return RecoveryDisposition.RECONCILIATION_REQUIRED
    if checkpoint.last_safe_state is not run.state:
        return RecoveryDisposition.RECONCILIATION_REQUIRED
    return RecoveryDisposition.SAFE_RESUMABLE
