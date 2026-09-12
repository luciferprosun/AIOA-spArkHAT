"""Clearly test-only in-memory implementation of the durable repository contract."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionResult,
    Approval,
    ApprovalDecision,
    AuditEvent,
    BudgetCounters,
    Checkpoint,
    ExecutionAcknowledgement,
    IdempotencyRecord,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    Run,
    VerificationEvidence,
    VerificationProofOrigin,
    WorkflowState,
    transition_run,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError

from .durable_logic import (
    completed_idempotency_status,
    transitioned_proposal,
    validate_approval_binding,
)
from .semantic_idempotency import derive_action_fingerprint, derive_idempotency_key

MAX_DURABLE_RUNS = 2_048
MAX_AUDIT_EVENTS_PER_RUN = 1_024
_MAX_SNAPSHOT_RECORDS = 65_536


class InMemoryTestDurableTruthRepository:
    """Deterministic test fake; never a production durability fallback."""

    def __init__(self) -> None:
        self._runs: dict[UUID, Run] = {}
        self._proposals: dict[UUID, ActionProposal] = {}
        self._approvals: dict[UUID, Approval] = {}
        self._idempotency: dict[str, IdempotencyRecord] = {}
        self._checkpoints: dict[UUID, Checkpoint] = {}
        self._audit_events: dict[tuple[UUID, UUID], AuditEvent] = {}
        self._verification_evidence: dict[tuple[UUID, UUID], VerificationEvidence] = {}

    def create_run(self, run: Run) -> Run:
        if run.version != 1 or run.state is not WorkflowState.RECEIVED:
            raise StorageConflictError("new durable run must start at RECEIVED version 1")
        if run.run_id in self._runs:
            raise StorageConflictError("durable run already exists")
        if len(self._runs) >= MAX_DURABLE_RUNS:
            raise StorageConflictError("durable run capacity is exhausted")
        self._runs[run.run_id] = run
        return run

    def get_run(self, run_id: UUID) -> Run | None:
        return self._runs.get(run_id)

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
        current = self._runs.get(run_id)
        if current is None:
            raise StorageConflictError("durable run does not exist")
        if current.state is not expected_state or current.version != expected_version:
            raise StorageConflictError("durable run state or version no longer matches")
        if next_state in {WorkflowState.APPROVED, WorkflowState.DENIED_BY_HUMAN}:
            if approval_proposal_id is None:
                raise StorageConflictError(
                    "decision transition requires a durable proposal decision"
                )
            proposal = self._proposals.get(approval_proposal_id)
            approval = self._approvals.get(approval_proposal_id)
            checkpoint = self._checkpoints.get(run_id)
            expected_decision = (
                ApprovalDecision.APPROVED
                if next_state is WorkflowState.APPROVED
                else ApprovalDecision.DENIED
            )
            legacy_decision_valid = (
                proposal is not None
                and proposal.run_id == run_id
                and proposal.state is ProposalState.AWAITING_APPROVAL
                and approval is not None
                and approval.decision is expected_decision
            )
            local_proposal = (
                checkpoint.remediation_proposal if checkpoint is not None else None
            )
            local_approval = checkpoint.local_approval if checkpoint is not None else None
            local_decision_valid = (
                checkpoint is not None
                and local_proposal is not None
                and local_proposal.proposal_id == approval_proposal_id
                and local_proposal.run_id == run_id
                and local_proposal.status is ProposalState.AWAITING_APPROVAL
                and local_approval is not None
                and local_approval.proposal_id == approval_proposal_id
                and local_approval.run_id == run_id
                and local_approval.decision is expected_decision
            )
            if not legacy_decision_valid and not local_decision_valid:
                raise StorageConflictError(
                    "decision transition requires matching durable human decision"
                )
        if next_state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            if verification_proposal_id is None:
                raise StorageConflictError("SUCCESS_WITH_EVIDENCE requires durable verification")
            proposal = self._proposals.get(verification_proposal_id)
            evidence = self._verification_evidence.get((run_id, verification_proposal_id))
            idempotency = (
                self._idempotency.get(derive_idempotency_key(proposal))
                if proposal is not None
                else None
            )
            legacy_proof_valid = (
                proposal is not None
                and evidence is not None
                and evidence.run_id == run_id
                and evidence.observed_state is ObservedInstanceState.STOPPED
                and idempotency is not None
                and idempotency.status is IdempotencyStatus.COMPLETED
                and idempotency.action_result is not None
                and idempotency.action_result.evidence_hash == evidence.evidence_hash
            )
            checkpoint = self._checkpoints.get(run_id)
            local_proposal = (
                checkpoint.remediation_proposal if checkpoint is not None else None
            )
            local_receipt = (
                checkpoint.local_execution_receipt if checkpoint is not None else None
            )
            local_verification = (
                checkpoint.local_verification if checkpoint is not None else None
            )
            local_proof_valid = (
                checkpoint is not None
                and local_proposal is not None
                and local_proposal.proposal_id == verification_proposal_id
                and local_proposal.run_id == run_id
                and local_receipt is not None
                and local_receipt.proposal_id == verification_proposal_id
                and local_receipt.run_id == run_id
                and local_verification is not None
                and local_verification.proposal_id == verification_proposal_id
                and local_verification.run_id == run_id
                and local_verification.receipt_hash == local_receipt.receipt_hash
            )
            if not legacy_proof_valid and not local_proof_valid:
                raise StorageConflictError("SUCCESS_WITH_EVIDENCE proof is incomplete")
        updated = transition_run(current, next_state, updated_at=updated_at)
        self._runs[run_id] = updated
        return updated

    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        if proposal.state is not ProposalState.PROPOSED:
            raise StorageConflictError("new durable proposal must start at PROPOSED")
        if proposal.proposal_id in self._proposals:
            raise StorageConflictError("durable proposal already exists")
        self._proposals[proposal.proposal_id] = proposal
        return proposal

    def update_run_budget(
        self,
        run_id: UUID,
        budget: BudgetCounters,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> Run:
        if not isinstance(budget, BudgetCounters):
            raise TypeError("budget must be BudgetCounters")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version <= 0
        ):
            raise TypeError("expected_version must be a positive integer")
        if not isinstance(updated_at, datetime):
            raise TypeError("updated_at must be datetime")
        current = self._runs.get(run_id)
        if current is None or current.version != expected_version:
            raise StorageConflictError("durable run budget version no longer matches")
        if (
            budget.max_turns != current.budget.max_turns
            or budget.max_tokens != current.budget.max_tokens
            or budget.max_elapsed_seconds != current.budget.max_elapsed_seconds
            or budget.turns_used < current.budget.turns_used
            or budget.tokens_used < current.budget.tokens_used
            or budget.elapsed_milliseconds_used < current.budget.elapsed_milliseconds_used
            or updated_at < current.updated_at
        ):
            raise StorageConflictError("durable run budget update is not monotonic")
        values = current.model_dump()
        values.update(
            {
                "budget": budget,
                "updated_at": updated_at,
                "version": current.version + 1,
            }
        )
        updated = Run.model_validate(values)
        self._runs[run_id] = updated
        return updated

    def get_proposal(self, proposal_id: UUID) -> ActionProposal | None:
        return self._proposals.get(proposal_id)

    def transition_proposal(
        self,
        proposal_id: UUID,
        next_state: ProposalState,
        *,
        expected_state: ProposalState,
    ) -> ActionProposal:
        current = self._proposals.get(proposal_id)
        if current is None or current.state is not expected_state:
            raise StorageConflictError("durable proposal state no longer matches")
        updated = transitioned_proposal(current, next_state)
        self._proposals[proposal_id] = updated
        return updated

    def create_approval(self, approval: Approval) -> Approval:
        proposal = self._proposals.get(approval.proposal_id)
        if proposal is None or proposal.state is not ProposalState.AWAITING_APPROVAL:
            raise StorageConflictError("human decision requires an awaiting durable proposal")
        validate_approval_binding(proposal, approval)
        existing = self._approvals.get(approval.proposal_id)
        if existing is not None:
            if existing == approval:
                return existing
            raise StorageConflictError("conflicting human decision already exists")
        self._approvals[approval.proposal_id] = approval
        return approval

    def get_approval(self, proposal_id: UUID) -> Approval | None:
        return self._approvals.get(proposal_id)

    def register_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        existing = self._idempotency.get(record.idempotency_key)
        if existing is not None:
            if (
                existing.proposal_id != record.proposal_id
                or existing.action_fingerprint != record.action_fingerprint
            ):
                raise StorageConflictError("idempotency key has incompatible ownership")
            return existing
        proposal = self._proposals.get(record.proposal_id)
        if (
            proposal is None
            or proposal.state is not ProposalState.AWAITING_APPROVAL
            or record.action_fingerprint != derive_action_fingerprint(proposal)
            or record.idempotency_key != derive_idempotency_key(proposal)
        ):
            raise StorageConflictError("idempotency registration lacks a matching proposal")
        approval = self._approvals.get(record.proposal_id)
        run = self._runs.get(proposal.run_id)
        if approval is None or approval.decision is not ApprovalDecision.APPROVED:
            raise StorageConflictError("idempotency registration requires human approval")
        if run is None or run.state is not WorkflowState.APPROVED:
            raise StorageConflictError("idempotency registration requires an approved run")
        self._idempotency[record.idempotency_key] = record
        return record

    def get_idempotency(self, idempotency_key: str) -> IdempotencyRecord | None:
        return self._idempotency.get(idempotency_key)

    def complete_idempotency(
        self,
        idempotency_key: str,
        result: ActionResult,
        *,
        completed_at: datetime,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        current = self._idempotency.get(idempotency_key)
        if current is None or current.status is not expected_status:
            raise StorageConflictError("idempotency status no longer matches")
        values = current.model_dump()
        values.update(
            {
                "status": completed_idempotency_status(result),
                "action_result": result,
                "completed_at": completed_at,
            }
        )
        updated = IdempotencyRecord.model_validate(values)
        self._idempotency[idempotency_key] = updated
        return updated

    def record_execution_acknowledgement(
        self,
        idempotency_key: str,
        acknowledgement: ExecutionAcknowledgement,
        *,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        current = self._idempotency.get(idempotency_key)
        if current is None or current.status is not expected_status:
            raise StorageConflictError("idempotency status no longer matches")
        if current.execution_acknowledgement is not None:
            if current.execution_acknowledgement == acknowledgement:
                return current
            raise StorageConflictError("conflicting execution acknowledgement exists")
        if acknowledgement.proposal_id != current.proposal_id:
            raise StorageConflictError("execution acknowledgement ownership is invalid")
        updated = current.model_copy(update={"execution_acknowledgement": acknowledgement})
        self._idempotency[idempotency_key] = updated
        return updated

    def save_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        expected_version: int | None,
    ) -> Checkpoint:
        current = self._checkpoints.get(checkpoint.run_id)
        if current is None:
            if expected_version is not None or checkpoint.version != 1:
                raise StorageConflictError("new checkpoint must start at version 1")
        elif expected_version != current.version or checkpoint.version != current.version + 1:
            raise StorageConflictError("checkpoint version no longer matches")
        self._checkpoints[checkpoint.run_id] = checkpoint
        return checkpoint

    def get_checkpoint(self, run_id: UUID) -> Checkpoint | None:
        return self._checkpoints.get(run_id)

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        key = (event.run_id, event.event_id)
        if key in self._audit_events:
            raise StorageConflictError("audit event already exists")
        if self.count_audit_events(event.run_id) >= MAX_AUDIT_EVENTS_PER_RUN:
            raise StorageConflictError("audit event capacity is exhausted for this run")
        self._audit_events[key] = event
        return event

    def get_audit_event(self, run_id: UUID, event_id: UUID) -> AuditEvent | None:
        return self._audit_events.get((run_id, event_id))

    def list_audit_events(self, run_id: UUID, *, limit: int = 128) -> tuple[AuditEvent, ...]:
        """Return one run's bounded, deterministic append-only audit timeline."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 256:
            raise ValueError("audit event limit must be between 1 and 256")
        events = (
            event for (event_run_id, _), event in self._audit_events.items()
            if event_run_id == run_id
        )
        return tuple(
            sorted(events, key=lambda event: (event.timestamp, str(event.event_id)))[:limit]
        )

    def count_audit_events(self, run_id: UUID) -> int:
        """Return one run's bounded event count without exposing a scan API."""

        return sum(event_run_id == run_id for event_run_id, _ in self._audit_events)

    def create_verification_evidence(
        self,
        evidence: VerificationEvidence,
    ) -> VerificationEvidence:
        key = (evidence.run_id, evidence.proposal_id)
        existing = self._verification_evidence.get(key)
        if existing is not None:
            if existing == evidence:
                return existing
            raise StorageConflictError("conflicting verification evidence already exists")
        proposal = self._proposals.get(evidence.proposal_id)
        run = self._runs.get(evidence.run_id)
        idempotency = (
            self._idempotency.get(derive_idempotency_key(proposal))
            if proposal is not None
            else None
        )
        approval = self._approvals.get(evidence.proposal_id)
        acknowledgement_matches = (
            evidence.proof_origin is VerificationProofOrigin.EXECUTION_ACKNOWLEDGEMENT
            and idempotency is not None
            and idempotency.execution_acknowledgement is not None
            and idempotency.execution_acknowledgement.acknowledgement_hash
            == evidence.execution_acknowledgement_hash
        )
        recovery_matches = (
            evidence.proof_origin is VerificationProofOrigin.RECOVERY_READ_BACK
            and idempotency is not None
            and idempotency.status is IdempotencyStatus.REGISTERED
            and idempotency.execution_acknowledgement is None
            and approval is not None
            and approval.decision is ApprovalDecision.APPROVED
            and approval.run_id == evidence.run_id
            and approval.target == evidence.target
        )
        if (
            proposal is None
            or run is None
            or run.state is not WorkflowState.VERIFYING
            or proposal.run_id != evidence.run_id
            or proposal.target != evidence.target
            or run.trace_id != evidence.trace_id
            or run.correlation_id != evidence.correlation_id
            or idempotency is None
            or not (acknowledgement_matches or recovery_matches)
        ):
            raise StorageConflictError("verification evidence does not match the proposal")
        self._verification_evidence[key] = evidence
        return evidence

    def get_verification_evidence(
        self,
        run_id: UUID,
        proposal_id: UUID,
    ) -> VerificationEvidence | None:
        return self._verification_evidence.get((run_id, proposal_id))

    def export_snapshot(self) -> dict[str, object]:
        """Return a complete, deterministic JSON-safe snapshot for a local adapter."""

        return {
            "format_version": 1,
            "runs": [
                self._runs[key].model_dump(mode="json")
                for key in sorted(self._runs, key=str)
            ],
            "proposals": [
                self._proposals[key].model_dump(mode="json")
                for key in sorted(self._proposals, key=str)
            ],
            "approvals": [
                self._approvals[key].model_dump(mode="json")
                for key in sorted(self._approvals, key=str)
            ],
            "idempotency": [
                self._idempotency[key].model_dump(mode="json")
                for key in sorted(self._idempotency)
            ],
            "checkpoints": [
                self._checkpoints[key].model_dump(mode="json")
                for key in sorted(self._checkpoints, key=str)
            ],
            "audit_events": [
                self._audit_events[key].model_dump(mode="json")
                for key in sorted(self._audit_events, key=lambda item: (str(item[0]), str(item[1])))
            ],
            "verification_evidence": [
                self._verification_evidence[key].model_dump(mode="json")
                for key in sorted(
                    self._verification_evidence,
                    key=lambda item: (str(item[0]), str(item[1])),
                )
            ],
        }

    @classmethod
    def from_snapshot(cls, payload: object) -> "InMemoryTestDurableTruthRepository":
        """Rebuild validated durable truth or fail closed on corrupt local state."""

        expected_keys = {
            "format_version",
            "runs",
            "proposals",
            "approvals",
            "idempotency",
            "checkpoints",
            "audit_events",
            "verification_evidence",
        }
        if not isinstance(payload, Mapping) or set(payload) != expected_keys:
            raise StorageDependencyError("local durable snapshot shape is invalid")
        if payload.get("format_version") != 1:
            raise StorageDependencyError("local durable snapshot version is unsupported")

        def records(name: str, model: Any) -> list[Any]:
            values = payload.get(name)
            if not isinstance(values, list) or len(values) > _MAX_SNAPSHOT_RECORDS:
                raise StorageDependencyError(f"local durable snapshot {name} is invalid")
            try:
                return [model.model_validate(value) for value in values]
            except (TypeError, ValueError, ValidationError) as error:
                raise StorageDependencyError(
                    f"local durable snapshot {name} violates typed contracts"
                ) from error

        repository = cls()
        runs = records("runs", Run)
        proposals = records("proposals", ActionProposal)
        approvals = records("approvals", Approval)
        idempotency = records("idempotency", IdempotencyRecord)
        checkpoints = records("checkpoints", Checkpoint)
        audit_events = records("audit_events", AuditEvent)
        verification_evidence = records("verification_evidence", VerificationEvidence)

        repository._runs = {record.run_id: record for record in runs}
        repository._proposals = {record.proposal_id: record for record in proposals}
        repository._approvals = {record.proposal_id: record for record in approvals}
        repository._idempotency = {record.idempotency_key: record for record in idempotency}
        repository._checkpoints = {record.run_id: record for record in checkpoints}
        repository._audit_events = {
            (record.run_id, record.event_id): record for record in audit_events
        }
        repository._verification_evidence = {
            (record.run_id, record.proposal_id): record for record in verification_evidence
        }
        counts = (
            (len(runs), len(repository._runs)),
            (len(proposals), len(repository._proposals)),
            (len(approvals), len(repository._approvals)),
            (len(idempotency), len(repository._idempotency)),
            (len(checkpoints), len(repository._checkpoints)),
            (len(audit_events), len(repository._audit_events)),
            (len(verification_evidence), len(repository._verification_evidence)),
        )
        if any(source != restored for source, restored in counts):
            raise StorageDependencyError("local durable snapshot contains duplicate identities")
        if any(proposal.run_id not in repository._runs for proposal in proposals):
            raise StorageDependencyError("local proposal references a missing run")
        if any(approval.proposal_id not in repository._proposals for approval in approvals):
            raise StorageDependencyError("local approval references a missing proposal")
        if any(checkpoint.run_id not in repository._runs for checkpoint in checkpoints):
            raise StorageDependencyError("local checkpoint references a missing run")
        if any(event.run_id not in repository._runs for event in audit_events):
            raise StorageDependencyError("local audit event references a missing run")
        if len(runs) > MAX_DURABLE_RUNS:
            raise StorageDependencyError("local durable snapshot exceeds run capacity")
        event_counts: dict[UUID, int] = {}
        for event in audit_events:
            event_counts[event.run_id] = event_counts.get(event.run_id, 0) + 1
        if any(count > MAX_AUDIT_EVENTS_PER_RUN for count in event_counts.values()):
            raise StorageDependencyError("local durable snapshot exceeds audit capacity")
        return repository
