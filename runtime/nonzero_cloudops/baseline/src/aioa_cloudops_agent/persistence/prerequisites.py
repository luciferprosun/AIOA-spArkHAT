"""Durable proof required before a future mutation executor may proceed."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from aioa_cloudops_agent.nz import (
    ActionProposal,
    Approval,
    ApprovalDecision,
    Checkpoint,
    IdempotencyRecord,
    IdempotencyStatus,
    ProposalState,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import DurablePrerequisiteError

from .durable_repository import DurableTruthRepository
from .semantic_idempotency import build_idempotency_record, derive_action_fingerprint


@dataclass(frozen=True, slots=True)
class ApprovedActionPrerequisites:
    """Proof bundle only; possession does not itself invoke an AWS mutation."""

    run: Run
    proposal: ActionProposal
    approval: Approval
    idempotency: IdempotencyRecord
    checkpoint: Checkpoint


def _require_approved_records(
    repository: DurableTruthRepository,
    proposal_id: UUID,
) -> tuple[Run, ActionProposal, Approval]:
    proposal = repository.get_proposal(proposal_id)
    if proposal is None:
        raise DurablePrerequisiteError("durable proposal is required")
    if proposal.state is not ProposalState.AWAITING_APPROVAL:
        raise DurablePrerequisiteError("proposal is not durably awaiting approval")
    approval = repository.get_approval(proposal.proposal_id)
    if approval is None:
        raise DurablePrerequisiteError("missing approval must not authorize execution")
    if approval.decision is not ApprovalDecision.APPROVED:
        raise DurablePrerequisiteError("human decision does not approve execution")
    run = repository.get_run(proposal.run_id)
    if run is None or run.state is not WorkflowState.APPROVED:
        raise DurablePrerequisiteError("durable run state must be APPROVED")
    return run, proposal, approval


def register_approved_action(
    repository: DurableTruthRepository,
    proposal_id: UUID,
    *,
    registered_at: datetime,
) -> IdempotencyRecord:
    """Register semantic ownership only after durable run and approval checks."""

    _, proposal, _ = _require_approved_records(repository, proposal_id)
    return repository.register_idempotency(
        build_idempotency_record(proposal, registered_at=registered_at)
    )


def load_execution_prerequisites(
    repository: DurableTruthRepository,
    proposal_id: UUID,
) -> ApprovedActionPrerequisites:
    """Load the full durable proof a future executor must require."""

    run, proposal, approval = _require_approved_records(repository, proposal_id)
    idempotency_key = f"action/{derive_action_fingerprint(proposal)}"
    idempotency = repository.get_idempotency(idempotency_key)
    if idempotency is None:
        raise DurablePrerequisiteError("durable idempotency registration is required")
    if (
        idempotency.proposal_id != proposal.proposal_id
        or idempotency.status is not IdempotencyStatus.REGISTERED
    ):
        raise DurablePrerequisiteError("idempotency ownership is inconsistent")
    checkpoint = repository.get_checkpoint(run.run_id)
    if checkpoint is None or checkpoint.last_safe_state is not WorkflowState.APPROVED:
        raise DurablePrerequisiteError("approved safe checkpoint is required")
    if (
        checkpoint.tool_result_hashes.get("build_remediation_evidence")
        != proposal.evidence_hash
    ):
        raise DurablePrerequisiteError(
            "approved safe checkpoint must retain the proposal evidence hash"
        )
    return ApprovedActionPrerequisites(
        run=run,
        proposal=proposal,
        approval=approval,
        idempotency=idempotency,
        checkpoint=checkpoint,
    )
