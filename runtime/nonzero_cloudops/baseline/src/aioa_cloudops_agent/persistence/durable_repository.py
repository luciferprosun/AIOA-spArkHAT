"""Provider-independent durable truth operations for the canonical NZ workflow."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionResult,
    Approval,
    AuditEvent,
    BudgetCounters,
    Checkpoint,
    ExecutionAcknowledgement,
    IdempotencyRecord,
    IdempotencyStatus,
    ProposalState,
    Run,
    VerificationEvidence,
    WorkflowState,
)


class DurableTruthRepository(Protocol):
    """Narrow authoritative state boundary; no scan, delete, or mutation tool API."""

    def create_run(self, run: Run) -> Run:
        """Create a new version-one run without overwriting another run."""

    def get_run(self, run_id: UUID) -> Run | None:
        """Read one run; absence is distinct from dependency failure."""

    def transition_run(
        self,
        run_id: UUID,
        next_state: WorkflowState,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        updated_at: datetime,
        approval_proposal_id: UUID | None = None,
        verification_proposal_id: UUID | None = None,
    ) -> Run:
        """Conditionally apply one legal application-owned state transition."""

    def update_run_budget(
        self,
        run_id: UUID,
        budget: BudgetCounters,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> Run:
        """Conditionally persist monotonic turn, token, and elapsed-time counters."""

    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        """Create one immutable mutation proposal without treating it as approval."""

    def get_proposal(self, proposal_id: UUID) -> ActionProposal | None:
        """Read one proposal."""

    def transition_proposal(
        self,
        proposal_id: UUID,
        next_state: ProposalState,
        *,
        expected_state: ProposalState,
    ) -> ActionProposal:
        """Conditionally move proposal metadata to its next durable state."""

    def create_approval(self, approval: Approval) -> Approval:
        """Create one human decision without overwriting a prior decision."""

    def get_approval(self, proposal_id: UUID) -> Approval | None:
        """Read a decision; no record means no approval."""

    def register_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        """Atomically own or reconcile one semantic action key."""

    def get_idempotency(self, idempotency_key: str) -> IdempotencyRecord | None:
        """Read one semantic action registration."""

    def complete_idempotency(
        self,
        idempotency_key: str,
        result: ActionResult,
        *,
        completed_at: datetime,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        """Conditionally attach one explicit side-effect result."""

    def record_execution_acknowledgement(
        self,
        idempotency_key: str,
        acknowledgement: ExecutionAcknowledgement,
        *,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        """Conditionally persist one provider receipt without claiming completion."""

    def save_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        expected_version: int | None,
    ) -> Checkpoint:
        """Create or conditionally advance the last safe checkpoint."""

    def get_checkpoint(self, run_id: UUID) -> Checkpoint | None:
        """Read the latest safe checkpoint."""

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        """Append one immutable audit event."""

    def get_audit_event(self, run_id: UUID, event_id: UUID) -> AuditEvent | None:
        """Read one immutable event by identity."""

    def create_verification_evidence(
        self,
        evidence: VerificationEvidence,
    ) -> VerificationEvidence:
        """Create or reconcile one immutable independent verification proof."""

    def get_verification_evidence(
        self,
        run_id: UUID,
        proposal_id: UUID,
    ) -> VerificationEvidence | None:
        """Read one final verification proof; absence is not success."""
