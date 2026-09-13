# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: persistence/durable_logic.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Provider-neutral transformations for durable NZ records."""

from ..models import (
    ActionOutcome,
    ActionProposal,
    ActionResult,
    Approval,
    IdempotencyStatus,
    ProposalState,
)
from ..models.errors import StorageConflictError


def validate_approval_binding(proposal: ActionProposal, approval: Approval) -> None:
    """Require one decision to bind the exact immutable proposal contents."""

    if (
        approval.proposal_id != proposal.proposal_id
        or approval.run_id != proposal.run_id
        or approval.action is not proposal.action
        or approval.target != proposal.target
        or approval.evidence_hash != proposal.evidence_hash
    ):
        raise StorageConflictError("human decision does not match the durable proposal")


def completed_idempotency_status(result: ActionResult) -> IdempotencyStatus:
    """Map an explicit action outcome to its durable idempotency status."""

    if result.outcome is ActionOutcome.SUCCEEDED:
        return IdempotencyStatus.COMPLETED
    if result.outcome is ActionOutcome.FAILED:
        return IdempotencyStatus.FAILED
    return IdempotencyStatus.RECONCILIATION_REQUIRED


def transitioned_proposal(
    proposal: ActionProposal,
    next_state: ProposalState,
) -> ActionProposal:
    """Apply the small application-owned proposal-state policy."""

    allowed = {
        ProposalState.PROPOSED: {
            ProposalState.AWAITING_APPROVAL,
            ProposalState.SUPERSEDED,
        },
        ProposalState.AWAITING_APPROVAL: {ProposalState.SUPERSEDED},
        ProposalState.SUPERSEDED: set(),
    }
    if next_state not in allowed[proposal.state]:
        raise StorageConflictError(
            f"illegal proposal transition: {proposal.state.value} -> {next_state.value}"
        )
    values = proposal.model_dump()
    values["state"] = next_state
    return ActionProposal.model_validate(values)
