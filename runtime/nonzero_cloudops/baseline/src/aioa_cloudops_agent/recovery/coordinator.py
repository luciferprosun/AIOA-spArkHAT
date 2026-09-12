"""Restart-safe Non-Zero reconciliation with no mutation replay capability."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from aioa_cloudops_agent.agent.hitl import ApprovalInterrupt
from aioa_cloudops_agent.cloudops import Ec2InstanceState, InvestigationIdentity
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.nz import (
    TERMINAL_WORKFLOW_STATES,
    ActionOutcome,
    ActionProposal,
    ActionResult,
    Approval,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    Checkpoint,
    ControlResult,
    FailureDetail,
    FailureKind,
    IdempotencyRecord,
    IdempotencyStatus,
    ProposalState,
    ResultStatus,
    Run,
    VerificationEvidence,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence.durable_repository import DurableTruthRepository
from aioa_cloudops_agent.persistence.models import compute_evidence_digest
from aioa_cloudops_agent.persistence.semantic_idempotency import derive_idempotency_key
from aioa_cloudops_agent.verification import (
    VerificationCompletion,
    VerificationObservation,
    VerifyInstanceStateService,
)

from .models import RecoveryAction, RecoveryOutcome, RecoveryRequest, RecoveryStatus

ApprovalReconstructor = Callable[[UUID], ControlResult[ApprovalInterrupt]]
VerificationReconciler = Callable[[UUID], ControlResult[VerificationCompletion]]


@dataclass(frozen=True, slots=True)
class _Snapshot:
    run: Run
    proposal: ActionProposal | None
    approval: Approval | None
    idempotency: IdempotencyRecord | None
    checkpoint: Checkpoint | None
    evidence: VerificationEvidence | None


class RecoveryCoordinator:
    """Classify and reconcile durable work without owning an executor or write API."""

    def __init__(
        self,
        repository: DurableTruthRepository,
        *,
        clock: Callable[[], datetime],
        sleeper: Callable[[int], None],
        event_id_factory: Callable[[], UUID],
        recovery_id_factory: Callable[[], UUID],
        evidence_id_factory: Callable[[], UUID],
        approval_reconstructor: ApprovalReconstructor | None = None,
        verification_reconciler: VerificationReconciler | None = None,
        readback_service: VerifyInstanceStateService | None = None,
        verification_settings: VerificationSettings | None = None,
        lease_seconds: int = 30,
    ) -> None:
        dependencies = (
            clock,
            sleeper,
            event_id_factory,
            recovery_id_factory,
            evidence_id_factory,
        )
        if not all(callable(value) for value in dependencies):
            raise TypeError("recovery dependencies must be callable")
        if not 1 <= lease_seconds <= 300:
            raise ValueError("lease_seconds must be between 1 and 300")
        self._repository = repository
        self._clock = clock
        self._sleeper = sleeper
        self._event_id_factory = event_id_factory
        self._recovery_id_factory = recovery_id_factory
        self._evidence_id_factory = evidence_id_factory
        self._approval_reconstructor = approval_reconstructor
        self._verification_reconciler = verification_reconciler
        self._readback_service = readback_service
        self._verification_settings = verification_settings or VerificationSettings()
        self._lease_seconds = lease_seconds

    def recover(self, request: RecoveryRequest) -> ControlResult[RecoveryOutcome]:
        """Recover one durable reference; never infer state or approval from prose."""

        if not isinstance(request, RecoveryRequest):
            return self._plain_failure(
                FailureKind.VALIDATION_FAILURE,
                "RECOVERY_REQUEST_INVALID",
                "Recovery requires the typed durable-reference contract",
            )
        snapshot_result = self._load_snapshot(request)
        if isinstance(snapshot_result, FailureDetail):
            return ControlResult[RecoveryOutcome].failed(snapshot_result)
        snapshot = snapshot_result
        run = snapshot.run
        proposal = snapshot.proposal

        consistency_failure = self._validate_snapshot(request, snapshot)
        if consistency_failure is not None:
            return self._audited_failure(run, proposal, consistency_failure)

        if run.state is WorkflowState.REMEDIATION_PROPOSED:
            return self._outcome(
                run,
                proposal,
                RecoveryStatus.RESUMABLE,
                RecoveryAction.RESUME_PROPOSAL,
                "PROPOSAL_RECONSTRUCTED",
                "Durable proposal remains unapproved and resumable",
            )
        if run.state is WorkflowState.AWAITING_APPROVAL:
            return self._recover_awaiting_approval(snapshot)
        if run.state is WorkflowState.APPROVED:
            return self._recover_approved(snapshot)
        if run.state in {WorkflowState.EXECUTING, WorkflowState.RECOVERY_REQUIRED}:
            return self._recover_execution(snapshot)
        if run.state is WorkflowState.VERIFYING:
            return self._recover_verification(snapshot)
        if run.state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            return self._return_verified(snapshot)
        if run.state in TERMINAL_WORKFLOW_STATES:
            return self._outcome(
                run,
                proposal,
                RecoveryStatus.TERMINAL,
                RecoveryAction.PRESERVE_TERMINAL,
                "TERMINAL_STATE_PRESERVED",
                "Durable terminal state remains closed after restart",
            )
        return self._outcome(
            run,
            proposal,
            RecoveryStatus.RESUMABLE,
            RecoveryAction.RESUME_SAFE_STATE,
            "SAFE_STATE_RESUMABLE",
            "Durable state and checkpoint permit normal non-mutation continuation",
        )

    def _load_snapshot(self, request: RecoveryRequest) -> _Snapshot | FailureDetail:
        try:
            run = self._repository.get_run(request.run_id)
            if run is None:
                return FailureDetail(
                    kind=FailureKind.VALIDATION_FAILURE,
                    code="RECOVERY_RUN_NOT_FOUND",
                    message="Durable run is required for recovery",
                    retryable=False,
                )
            proposal = (
                self._repository.get_proposal(request.proposal_id)
                if request.proposal_id is not None
                else None
            )
            checkpoint = self._repository.get_checkpoint(run.run_id)
            approval = (
                self._repository.get_approval(proposal.proposal_id)
                if proposal is not None
                else None
            )
            idempotency = (
                self._repository.get_idempotency(derive_idempotency_key(proposal))
                if proposal is not None
                else None
            )
            evidence = (
                self._repository.get_verification_evidence(run.run_id, proposal.proposal_id)
                if proposal is not None
                else None
            )
        except StorageDependencyError:
            return FailureDetail(
                kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                code="RECOVERY_DURABLE_TRUTH_UNAVAILABLE",
                message="Authoritative durable truth is unavailable during recovery",
                retryable=True,
            )
        return _Snapshot(run, proposal, approval, idempotency, checkpoint, evidence)

    def _validate_snapshot(
        self,
        request: RecoveryRequest,
        snapshot: _Snapshot,
    ) -> FailureDetail | None:
        run = snapshot.run
        proposal = snapshot.proposal
        proposal_required = run.state not in {
            WorkflowState.RECEIVED,
            WorkflowState.INVESTIGATING,
            WorkflowState.EVIDENCE_READY,
        }
        if proposal_required and proposal is None:
            return self._failure(
                "RECOVERY_PROPOSAL_REQUIRED",
                "This durable workflow state requires an exact proposal reference",
            )
        if proposal is not None and (
            proposal.run_id != run.run_id or proposal.proposal_id != request.proposal_id
        ):
            return self._policy_failure(
                "RECOVERY_PROPOSAL_RUN_MISMATCH",
                "Proposal and run references do not share one durable identity",
            )
        checkpoint = snapshot.checkpoint
        checkpoint_required = run.state not in {
            WorkflowState.RECEIVED,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            WorkflowState.DENIED_BY_HUMAN,
            WorkflowState.DENIED_BY_POLICY,
            WorkflowState.EXECUTION_FAILED,
            WorkflowState.VERIFICATION_FAILED,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            WorkflowState.AMBIGUOUS_RESULT,
            WorkflowState.BUDGET_EXHAUSTED,
        }
        if checkpoint_required and checkpoint is None:
            return self._failure(
                "RECOVERY_CHECKPOINT_REQUIRED",
                "Active durable work requires a versioned checkpoint",
            )
        if checkpoint is not None:
            if checkpoint.run_id != run.run_id:
                return self._failure(
                    "RECOVERY_CHECKPOINT_RUN_MISMATCH",
                    "Checkpoint belongs to another durable run",
                )
            metadata_proposal = checkpoint.resume_metadata.get("proposal_id")
            if proposal is not None and metadata_proposal not in {
                None,
                str(proposal.proposal_id),
            }:
                return self._failure(
                    "RECOVERY_CHECKPOINT_PROPOSAL_MISMATCH",
                    "Checkpoint proposal metadata is inconsistent",
                )
            if run.state is WorkflowState.AWAITING_APPROVAL and (
                checkpoint.last_safe_state is not WorkflowState.AWAITING_APPROVAL
            ):
                return self._failure(
                    "RECOVERY_APPROVAL_CHECKPOINT_INVALID",
                    "Awaiting approval is missing its exact safe checkpoint",
                )
        return None

    def _recover_awaiting_approval(
        self,
        snapshot: _Snapshot,
    ) -> ControlResult[RecoveryOutcome]:
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        if snapshot.approval is not None:
            return self._audited_failure(
                run,
                proposal,
                self._failure(
                    "AWAITING_APPROVAL_HAS_DECISION",
                    "Awaiting run conflicts with an existing durable decision",
                ),
            )
        if proposal.state is not ProposalState.AWAITING_APPROVAL:
            return self._audited_failure(
                run,
                proposal,
                self._failure(
                    "AWAITING_APPROVAL_PROPOSAL_INVALID",
                    "Awaiting run and proposal state are inconsistent",
                ),
            )
        if self._approval_reconstructor is None:
            return self._operator_required(
                run,
                proposal,
                "APPROVAL_RECONSTRUCTOR_UNAVAILABLE",
                "Durable approval boundary exists but its caller adapter is unavailable",
            )
        reconstructed = self._approval_reconstructor(proposal.proposal_id)
        if reconstructed.status is ResultStatus.FAILURE:
            assert reconstructed.failure is not None
            return self._audited_failure(run, proposal, reconstructed.failure)
        assert reconstructed.value is not None
        return self._outcome(
            run,
            proposal,
            RecoveryStatus.RESUMABLE,
            RecoveryAction.RECONSTRUCT_APPROVAL,
            "APPROVAL_INTERRUPT_RECONSTRUCTED",
            "Exact proposal-bound human approval boundary was reconstructed",
            approval_interrupt=reconstructed.value,
            reconciled=True,
        )

    def _recover_approved(self, snapshot: _Snapshot) -> ControlResult[RecoveryOutcome]:
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        if not self._positive_approval_matches(snapshot):
            return self._audited_failure(
                run,
                proposal,
                self._policy_failure(
                    "APPROVED_STATE_BINDING_INVALID",
                    "Approved state lacks its exact positive durable decision",
                ),
            )
        if snapshot.idempotency is None:
            return self._outcome(
                run,
                proposal,
                RecoveryStatus.READY,
                RecoveryAction.READY_FOR_EXECUTION,
                "APPROVAL_READY_NO_EXECUTION_CLAIM",
                "Durable approval is valid and no execution ownership was claimed",
                ready_for_execution=True,
                reconciled=True,
            )
        return self._operator_required(
            run,
            proposal,
            "APPROVED_WITH_UNRESOLVED_CLAIM",
            "Execution ownership exists but durable state does not prove an API request",
        )

    def _recover_execution(self, snapshot: _Snapshot) -> ControlResult[RecoveryOutcome]:
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        if not self._positive_approval_matches(snapshot):
            return self._audited_failure(
                run,
                proposal,
                self._policy_failure(
                    "RECOVERY_APPROVAL_BINDING_INVALID",
                    "Lost-ACK recovery requires the exact positive durable approval",
                ),
            )
        idempotency = snapshot.idempotency
        if idempotency is None:
            return self._operator_required(
                run,
                proposal,
                "RECOVERY_IDEMPOTENCY_MISSING",
                "Executing state lacks durable semantic execution ownership",
            )
        if idempotency.status is IdempotencyStatus.COMPLETED:
            return self._return_verified(snapshot)
        if idempotency.status is not IdempotencyStatus.REGISTERED:
            return self._operator_required(
                run,
                proposal,
                "RECOVERY_IDEMPOTENCY_UNRESOLVED",
                "Durable action result requires explicit operator reconciliation",
            )
        claim = self._claim_active_recovery(snapshot)
        if isinstance(claim, FailureDetail):
            return self._audited_failure(
                run,
                proposal,
                claim,
                event_type=AuditEventType.RECOVERY_DEFERRED,
            )
        if idempotency.execution_acknowledgement is not None:
            return self._resume_from_durable_ack(snapshot, claim)
        return self._reconcile_missing_ack(snapshot, claim)

    def _recover_verification(self, snapshot: _Snapshot) -> ControlResult[RecoveryOutcome]:
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        if snapshot.idempotency is None:
            return self._operator_required(
                run,
                proposal,
                "VERIFYING_IDEMPOTENCY_MISSING",
                "Verification restart lacks durable execution ownership",
            )
        if snapshot.idempotency.status is IdempotencyStatus.COMPLETED:
            return self._return_verified(snapshot)
        claim = self._claim_active_recovery(snapshot)
        if isinstance(claim, FailureDetail):
            return self._audited_failure(
                run,
                proposal,
                claim,
                event_type=AuditEventType.RECOVERY_DEFERRED,
            )
        if self._verification_reconciler is None:
            return self._operator_required(
                run,
                proposal,
                "VERIFICATION_RECONCILER_UNAVAILABLE",
                "Read-only verification continuation is not configured",
            )
        result = self._verification_reconciler(proposal.proposal_id)
        if result.status is ResultStatus.FAILURE:
            assert result.failure is not None
            return self._audited_failure(run, proposal, result.failure)
        assert result.value is not None
        return self._outcome(
            snapshot.run,
            proposal,
            RecoveryStatus.RECONCILED,
            RecoveryAction.RETURN_VERIFIED_RESULT,
            "VERIFYING_RESTART_COMPLETED",
            "Bounded read-only verification persisted final proof after restart",
            final_state=WorkflowState.SUCCESS_WITH_EVIDENCE,
            verification=result.value,
            evidence_hash=result.value.evidence.evidence_hash,
            reconciled=True,
            event_type=AuditEventType.RECOVERY_COMPLETED,
        )

    def _resume_from_durable_ack(
        self,
        snapshot: _Snapshot,
        claim: Checkpoint,
    ) -> ControlResult[RecoveryOutcome]:
        del claim
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        try:
            if run.state is WorkflowState.RECOVERY_REQUIRED:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.RECOVERY_REQUIRED,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
            elif run.state is WorkflowState.EXECUTING:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.EXECUTING,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
        except (StorageConflictError, StorageDependencyError):
            return self._audited_failure(
                snapshot.run,
                proposal,
                self._failure(
                    "RECOVERY_VERIFYING_TRANSITION_CONFLICT",
                    "Durable acknowledgement could not safely resume verification",
                ),
            )
        if self._verification_reconciler is None:
            return self._operator_required(
                run,
                proposal,
                "VERIFICATION_RECONCILER_UNAVAILABLE",
                "Durable acknowledgement is safe, but read-only verification is not configured",
            )
        result = self._verification_reconciler(proposal.proposal_id)
        if result.status is ResultStatus.FAILURE:
            assert result.failure is not None
            return self._audited_failure(run, proposal, result.failure)
        assert result.value is not None
        return self._outcome(
            snapshot.run,
            proposal,
            RecoveryStatus.RECONCILED,
            RecoveryAction.RETURN_VERIFIED_RESULT,
            "DURABLE_ACK_VERIFICATION_COMPLETED",
            "Durable acknowledgement resumed bounded read-only verification",
            final_state=WorkflowState.SUCCESS_WITH_EVIDENCE,
            verification=result.value,
            evidence_hash=result.value.evidence.evidence_hash,
            reconciled=True,
            event_type=AuditEventType.RECOVERY_COMPLETED,
        )

    def _reconcile_missing_ack(
        self,
        snapshot: _Snapshot,
        claim: Checkpoint,
    ) -> ControlResult[RecoveryOutcome]:
        del claim
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        if self._readback_service is None:
            return self._operator_required(
                run,
                proposal,
                "LIVE_RECONCILIATION_NOT_CONFIGURED",
                "Lost acknowledgement remains safe and requires read-only reconciliation",
            )
        identity = InvestigationIdentity.from_run(run)
        last: VerificationObservation | None = None
        for attempt in range(1, self._verification_settings.max_attempts + 1):
            observation = self._readback_service.observe(
                proposal,
                identity,
                observed_at=self._clock(),
                attempt=attempt,
            )
            if observation.status is ResultStatus.FAILURE:
                assert observation.failure is not None
                self._mark_recovery_required(run)
                return self._audited_failure(run, proposal, observation.failure)
            assert observation.value is not None
            last = observation.value
            audit_failure = self._append_observation_event(run, proposal, last)
            if audit_failure is not None:
                self._mark_recovery_required(run)
                return ControlResult[RecoveryOutcome].failed(audit_failure)
            if last.observed_state is Ec2InstanceState.STOPPED:
                return self._complete_from_recovery_observation(snapshot, last)
            if last.observed_state is Ec2InstanceState.RUNNING:
                self._mark_recovery_required(run)
                return self._operator_required(
                    run,
                    proposal,
                    "LOST_ACK_TARGET_STILL_RUNNING",
                    "Running state after ambiguous acknowledgement forbids blind replay",
                    observed_state=last.observed_state,
                )
            if last.observed_state is not Ec2InstanceState.STOPPING:
                self._mark_recovery_required(run)
                return self._operator_required(
                    run,
                    proposal,
                    "LOST_ACK_STATE_AMBIGUOUS",
                    "Read-only recovery observed an unsafe or ambiguous EC2 state",
                    observed_state=last.observed_state,
                )
            if attempt < self._verification_settings.max_attempts:
                self._sleeper(self._verification_settings.interval_seconds)
        assert last is not None
        self._mark_recovery_required(run)
        return self._operator_required(
            run,
            proposal,
            "LOST_ACK_STILL_TRANSITIONING",
            "Bounded read-only reconciliation ended without a final state",
            observed_state=last.observed_state,
        )

    def _complete_from_recovery_observation(
        self,
        snapshot: _Snapshot,
        observation: VerificationObservation,
    ) -> ControlResult[RecoveryOutcome]:
        run, proposal = snapshot.run, snapshot.proposal
        assert proposal is not None
        try:
            if run.state is WorkflowState.EXECUTING:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.EXECUTING,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
            elif run.state is WorkflowState.RECOVERY_REQUIRED:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.RECOVERY_REQUIRED,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
            evidence = VerificationEvidence.create_from_recovery(
                evidence_id=self._evidence_id_factory(),
                proposal=proposal,
                run=run,
                verified_at=self._clock(),
                observation_hash=observation.observation_hash,
            )
            evidence = self._repository.create_verification_evidence(evidence)
            self._repository.complete_idempotency(
                derive_idempotency_key(proposal),
                ActionResult(
                    outcome=ActionOutcome.SUCCEEDED,
                    observed_state=observation.observed_state.value,
                    evidence_hash=evidence.evidence_hash,
                ),
                completed_at=self._clock(),
            )
            self._append_event(
                run,
                proposal,
                AuditEventType.RECOVERY_COMPLETED,
                "LOST_ACK_STOPPED_VERIFIED",
                evidence.evidence_hash,
            )
            run = self._repository.transition_run(
                run.run_id,
                WorkflowState.SUCCESS_WITH_EVIDENCE,
                expected_state=WorkflowState.VERIFYING,
                expected_version=run.version,
                updated_at=self._clock(),
                verification_proposal_id=proposal.proposal_id,
            )
        except (StorageConflictError, StorageDependencyError, ValueError):
            self._mark_recovery_required(run)
            return self._audited_failure(
                snapshot.run,
                proposal,
                self._failure(
                    "RECOVERY_EVIDENCE_DURABILITY_FAILED",
                    "Stopped read-back could not satisfy every durable success invariant",
                ),
            )
        return self._outcome(
            snapshot.run,
            proposal,
            RecoveryStatus.RECONCILED,
            RecoveryAction.RETURN_VERIFIED_RESULT,
            "LOST_ACK_RECONCILED_FROM_READ_BACK",
            "Independent stopped-state proof closed the approved lost-ACK action",
            final_state=run.state,
            observed_state=observation.observed_state,
            evidence_hash=evidence.evidence_hash,
            reconciled=True,
            event_type=AuditEventType.RECOVERY_COMPLETED,
        )

    def _return_verified(self, snapshot: _Snapshot) -> ControlResult[RecoveryOutcome]:
        run, proposal, evidence = snapshot.run, snapshot.proposal, snapshot.evidence
        if proposal is None or evidence is None or snapshot.idempotency is None:
            return self._audited_failure(
                run,
                proposal,
                self._failure(
                    "RECOVERY_VERIFIED_EVIDENCE_MISSING",
                    "Completed durable work is missing its independent proof",
                ),
            )
        if (
            snapshot.idempotency.status is not IdempotencyStatus.COMPLETED
            or snapshot.idempotency.action_result is None
            or snapshot.idempotency.action_result.evidence_hash != evidence.evidence_hash
        ):
            return self._audited_failure(
                run,
                proposal,
                self._failure(
                    "RECOVERY_VERIFIED_RESULT_INCONSISTENT",
                    "Idempotency result and verification evidence do not match",
                ),
            )
        try:
            if run.state is WorkflowState.RECOVERY_REQUIRED:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.RECOVERY_REQUIRED,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
            if run.state is WorkflowState.VERIFYING:
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.SUCCESS_WITH_EVIDENCE,
                    expected_state=WorkflowState.VERIFYING,
                    expected_version=run.version,
                    updated_at=self._clock(),
                    verification_proposal_id=proposal.proposal_id,
                )
        except (StorageConflictError, StorageDependencyError):
            return self._audited_failure(
                snapshot.run,
                proposal,
                self._failure(
                    "RECOVERY_SUCCESS_RECONCILIATION_CONFLICT",
                    "Existing verified proof could not reconcile the durable run state",
                ),
            )
        if run.state is not WorkflowState.SUCCESS_WITH_EVIDENCE:
            return self._operator_required(
                run,
                proposal,
                "RECOVERY_SUCCESS_STATE_INVALID",
                "Verified result exists in a state that cannot be safely closed",
            )
        return self._outcome(
            snapshot.run,
            proposal,
            RecoveryStatus.RECONCILED,
            RecoveryAction.RETURN_VERIFIED_RESULT,
            "VERIFIED_RESULT_RETURNED_IDEMPOTENTLY",
            "Existing durable verification proof was returned without new provider work",
            final_state=run.state,
            evidence_hash=evidence.evidence_hash,
            reconciled=True,
            event_type=AuditEventType.RECOVERY_COMPLETED,
        )

    def _positive_approval_matches(self, snapshot: _Snapshot) -> bool:
        proposal, approval = snapshot.proposal, snapshot.approval
        return bool(
            proposal is not None
            and approval is not None
            and approval.decision is ApprovalDecision.APPROVED
            and approval.proposal_id == proposal.proposal_id
            and approval.run_id == snapshot.run.run_id
            and approval.action is proposal.action
            and approval.target == proposal.target
            and approval.evidence_hash == proposal.evidence_hash
        )

    def _claim_active_recovery(self, snapshot: _Snapshot) -> Checkpoint | FailureDetail:
        checkpoint = snapshot.checkpoint
        proposal = snapshot.proposal
        if checkpoint is None or proposal is None:
            return self._failure(
                "RECOVERY_CLAIM_CHECKPOINT_MISSING",
                "Active reconciliation requires a durable checkpoint",
            )
        now = self._clock()
        lease_raw = checkpoint.resume_metadata.get("recovery_lease_expires_at")
        if isinstance(lease_raw, str):
            try:
                lease_expiry = datetime.fromisoformat(lease_raw)
            except ValueError:
                return self._failure(
                    "RECOVERY_LEASE_CORRUPT",
                    "Recovery checkpoint contains an invalid lease timestamp",
                )
            if lease_expiry > now:
                return self._failure(
                    "RECOVERY_ALREADY_CLAIMED",
                    "Another bounded recovery attempt currently owns this checkpoint",
                )
        claim_id = self._recovery_id_factory()
        claimed = Checkpoint(
            run_id=checkpoint.run_id,
            last_safe_state=checkpoint.last_safe_state,
            resume_metadata={
                **checkpoint.resume_metadata,
                "recovery_claim_id": str(claim_id),
                "recovery_claim_state": snapshot.run.state.value,
                "recovery_lease_expires_at": (
                    now + timedelta(seconds=self._lease_seconds)
                ).isoformat(),
                "recovery_proposal_id": str(proposal.proposal_id),
            },
            tool_result_hashes=checkpoint.tool_result_hashes,
            created_at=now,
            version=checkpoint.version + 1,
        )
        try:
            return self._repository.save_checkpoint(
                claimed,
                expected_version=checkpoint.version,
            )
        except StorageConflictError:
            return self._failure(
                "RECOVERY_CONCURRENT_CLAIM_CONFLICT",
                "Concurrent recovery attempt won the optimistic checkpoint claim",
            )
        except StorageDependencyError:
            return FailureDetail(
                kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                code="RECOVERY_CLAIM_STORAGE_UNAVAILABLE",
                message="Recovery checkpoint claim could not reach durable truth",
                retryable=True,
            )

    def _mark_recovery_required(self, run: Run) -> None:
        if run.state is WorkflowState.RECOVERY_REQUIRED:
            return
        try:
            current = self._repository.get_run(run.run_id)
            if current is not None and current.state in {
                WorkflowState.EXECUTING,
                WorkflowState.VERIFYING,
            }:
                self._repository.transition_run(
                    current.run_id,
                    WorkflowState.RECOVERY_REQUIRED,
                    expected_state=current.state,
                    expected_version=current.version,
                    updated_at=self._clock(),
                )
        except (StorageConflictError, StorageDependencyError):
            return

    def _append_observation_event(
        self,
        run: Run,
        proposal: ActionProposal,
        observation: VerificationObservation,
    ) -> FailureDetail | None:
        try:
            self._append_event(
                run,
                proposal,
                AuditEventType.RECOVERY_OBSERVED,
                f"LOST_ACK_{observation.observed_state.value.upper().replace('-', '_')}",
                observation.observation_hash,
            )
        except (StorageConflictError, StorageDependencyError):
            return FailureDetail(
                kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                code="RECOVERY_OBSERVATION_AUDIT_UNAVAILABLE",
                message="Read-only recovery observation could not be durably audited",
                retryable=True,
            )
        return None

    def _outcome(
        self,
        run: Run,
        proposal: ActionProposal | None,
        status: RecoveryStatus,
        action: RecoveryAction,
        reason_code: str,
        reason: str,
        *,
        final_state: WorkflowState | None = None,
        approval_interrupt: ApprovalInterrupt | None = None,
        verification: VerificationCompletion | None = None,
        observed_state: Ec2InstanceState | None = None,
        evidence_hash: str | None = None,
        failure: FailureDetail | None = None,
        ready_for_execution: bool = False,
        reconciled: bool = False,
        event_type: AuditEventType = AuditEventType.RECOVERY_CLASSIFIED,
    ) -> ControlResult[RecoveryOutcome]:
        event_id = self._event_id_factory()
        payload_hash = compute_evidence_digest(
            {
                "action": action.value,
                "final_state": (final_state or run.state).value,
                "initial_state": run.state.value,
                "proposal_id": str(proposal.proposal_id) if proposal else None,
                "reason_code": reason_code,
                "run_id": str(run.run_id),
            }
        )
        try:
            self._repository.append_audit_event(
                AuditEvent(
                    event_id=event_id,
                    run_id=run.run_id,
                    type=event_type,
                    timestamp=self._clock(),
                    source="nz-recovery",
                    redacted_payload_hash=payload_hash,
                    metadata={
                        "action": action.value,
                        "correlation_id": str(run.correlation_id),
                        "initial_state": run.state.value,
                        "proposal_id": str(proposal.proposal_id) if proposal else "none",
                        "reason_code": reason_code,
                        "trace_id": str(run.trace_id),
                    },
                )
            )
        except (StorageConflictError, StorageDependencyError):
            return self._plain_failure(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "RECOVERY_AUDIT_UNAVAILABLE",
                "Recovery decision could not be durably audited",
                retryable=True,
            )
        return ControlResult[RecoveryOutcome].succeeded(
            RecoveryOutcome(
                run_id=run.run_id,
                trace_id=run.trace_id,
                correlation_id=run.correlation_id,
                proposal_id=proposal.proposal_id if proposal else None,
                initial_state=run.state,
                final_state=final_state or run.state,
                status=status,
                action=action,
                reason_code=reason_code,
                reason=reason,
                audit_event_id=event_id,
                approval_interrupt=approval_interrupt,
                verification=verification,
                observed_state=observed_state,
                evidence_hash=evidence_hash,
                failure=failure,
                ready_for_execution=ready_for_execution,
                reconciled=reconciled,
            )
        )

    def _operator_required(
        self,
        run: Run,
        proposal: ActionProposal | None,
        code: str,
        message: str,
        *,
        observed_state: Ec2InstanceState | None = None,
    ) -> ControlResult[RecoveryOutcome]:
        failure = self._failure(code, message)
        return self._outcome(
            run,
            proposal,
            RecoveryStatus.OPERATOR_REQUIRED,
            RecoveryAction.OPERATOR_REVIEW,
            code,
            message,
            observed_state=observed_state,
            failure=failure,
            reconciled=True,
            event_type=AuditEventType.RECOVERY_DEFERRED,
        )

    def _audited_failure(
        self,
        run: Run,
        proposal: ActionProposal | None,
        failure: FailureDetail,
        *,
        event_type: AuditEventType = AuditEventType.RECOVERY_DEFERRED,
    ) -> ControlResult[RecoveryOutcome]:
        payload_hash = compute_evidence_digest(
            {
                "failure_code": failure.code,
                "failure_kind": failure.kind.value,
                "proposal_id": str(proposal.proposal_id) if proposal else None,
                "run_id": str(run.run_id),
                "state": run.state.value,
            }
        )
        try:
            self._append_event(run, proposal, event_type, failure.code, payload_hash)
        except (StorageConflictError, StorageDependencyError):
            return self._plain_failure(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "RECOVERY_FAILURE_AUDIT_UNAVAILABLE",
                "Recovery failure could not be durably audited",
                retryable=True,
            )
        return ControlResult[RecoveryOutcome].failed(failure)

    def _append_event(
        self,
        run: Run,
        proposal: ActionProposal | None,
        event_type: AuditEventType,
        reason_code: str,
        payload_hash: str,
    ) -> None:
        self._repository.append_audit_event(
            AuditEvent(
                event_id=self._event_id_factory(),
                run_id=run.run_id,
                type=event_type,
                timestamp=self._clock(),
                source="nz-recovery",
                redacted_payload_hash=payload_hash,
                metadata={
                    "correlation_id": str(run.correlation_id),
                    "proposal_id": str(proposal.proposal_id) if proposal else "none",
                    "reason_code": reason_code,
                    "trace_id": str(run.trace_id),
                },
            )
        )

    @staticmethod
    def _failure(code: str, message: str) -> FailureDetail:
        return FailureDetail(
            kind=FailureKind.RECOVERY_REQUIREMENT,
            code=code,
            message=message,
            retryable=False,
        )

    @staticmethod
    def _policy_failure(code: str, message: str) -> FailureDetail:
        return FailureDetail(
            kind=FailureKind.POLICY_DENIAL,
            code=code,
            message=message,
            retryable=False,
        )

    @staticmethod
    def _plain_failure(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> ControlResult[RecoveryOutcome]:
        return ControlResult[RecoveryOutcome].failed(
            FailureDetail(
                kind=kind,
                code=code,
                message=message,
                retryable=retryable,
            )
        )
