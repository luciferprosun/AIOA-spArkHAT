"""Local-2 human authorization, replay protection, execution, and verification."""

import hashlib
import hmac
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aioa_cloudops_agent.cloudops import (
    CloudAdapterUnavailableError,
    LocalMockConflictError,
    LocalMockMutationError,
    LocalMockPolicyError,
    LocalMockRemediationExecutor,
)
from aioa_cloudops_agent.nz import (
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    Checkpoint,
    ControlResult,
    FailureDetail,
    FailureKind,
    LocalApprovalDecisionRecord,
    LocalApprovalRequestRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    NonEmptyText,
    RemediationProposal,
    ResourceEvidence,
    Run,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence import DurableTruthRepository


class LocalOperatorPrincipal(BaseModel):
    """Authenticated local operator identity supplied by the API boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_session_id: ShortIdentifier


class LocalApprovalChallenge(BaseModel):
    """Human-visible exact proposal plus one ephemeral decision challenge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: LocalApprovalRequestRecord
    proposal: RemediationProposal
    evidence: ResourceEvidence
    decision_nonce: NonEmptyText = Field(min_length=16, max_length=256)

    @model_validator(mode="after")
    def validate_challenge_binding(self) -> Self:
        if (
            self.request.proposal_id != self.proposal.proposal_id
            or self.request.run_id != self.proposal.run_id
            or self.request.proposal_hash != self.proposal.proposal_hash
            or self.request.evidence_hash != self.evidence.evidence_hash
            or self.proposal.evidence_hash != self.evidence.evidence_hash
            or self.request.decision_nonce_hash
            != hashlib.sha256(self.decision_nonce.encode("utf-8")).hexdigest()
        ):
            raise ValueError("local approval challenge is not exactly proposal-bound")
        return self


class LocalDecisionRequest(BaseModel):
    """Strict API input echoing every decision-critical durable binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: Uuid7Identifier
    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    request_hash: Sha256Digest
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    proposal_version: int = Field(gt=0)
    decision: ApprovalDecision
    decision_nonce: NonEmptyText = Field(min_length=16, max_length=256)


class LocalApprovalResolution(BaseModel):
    """Durable decision state; approval remains distinct from execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    request_id: Uuid7Identifier
    request_hash: Sha256Digest
    decision_hash: Sha256Digest
    decision: ApprovalDecision
    final_state: Literal[WorkflowState.APPROVED, WorkflowState.DENIED_BY_HUMAN]
    reconciled: bool = False

    @model_validator(mode="after")
    def validate_resolution_state(self) -> Self:
        expected = (
            WorkflowState.APPROVED
            if self.decision is ApprovalDecision.APPROVED
            else WorkflowState.DENIED_BY_HUMAN
        )
        if self.final_state is not expected:
            raise ValueError("local decision and final state do not match")
        return self


class LocalExecutionCompletion(BaseModel):
    """Explicit Local-2 terminal result with independent verification when executed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    decision: ApprovalDecision
    final_state: Literal[
        WorkflowState.DENIED_BY_HUMAN,
        WorkflowState.SUCCESS_WITH_EVIDENCE,
    ]
    approval: LocalApprovalDecisionRecord
    receipt: LocalExecutionReceipt | None = None
    verification: LocalVerificationEvidence | None = None
    reconciled: bool = False

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.decision is ApprovalDecision.DENIED:
            if (
                self.final_state is not WorkflowState.DENIED_BY_HUMAN
                or self.receipt is not None
                or self.verification is not None
            ):
                raise ValueError("denied local completion cannot contain execution proof")
        elif (
            self.final_state is not WorkflowState.SUCCESS_WITH_EVIDENCE
            or self.receipt is None
            or self.verification is None
            or self.receipt.run_id != self.run_id
            or self.receipt.proposal_id != self.proposal_id
            or self.verification.receipt_hash != self.receipt.receipt_hash
        ):
            raise ValueError("approved local completion requires linked verification")
        return self


LocalApprovalChallengeResult = ControlResult[LocalApprovalChallenge]
LocalApprovalResolutionResult = ControlResult[LocalApprovalResolution]
LocalExecutionResult = ControlResult[LocalExecutionCompletion]

_APPROVED_DECISION_DOWNSTREAM_STATES = frozenset(
    {
        WorkflowState.EXECUTING,
        WorkflowState.VERIFYING,
        WorkflowState.SUCCESS_WITH_EVIDENCE,
        WorkflowState.DENIED_BY_POLICY,
        WorkflowState.MODEL_OUTPUT_INVALID,
        WorkflowState.AMBIGUOUS_RESULT,
        WorkflowState.DEPENDENCY_UNAVAILABLE,
        WorkflowState.BUDGET_EXHAUSTED,
        WorkflowState.EXECUTION_FAILED,
        WorkflowState.VERIFICATION_FAILED,
        WorkflowState.RECOVERY_REQUIRED,
    }
)


class LocalHitlExecutionFlow:
    """Connect Local-1 proposals to exact human authority and protected mock execution."""

    def __init__(
        self,
        repository: DurableTruthRepository,
        executor: LocalMockRemediationExecutor,
        *,
        clock: Callable[[], datetime],
        request_id_factory: Callable[[], UUID],
        event_id_factory: Callable[[], UUID],
        nonce_factory: Callable[[], str],
        request_ttl_seconds: int = 600,
    ) -> None:
        if not isinstance(executor, LocalMockRemediationExecutor):
            raise TypeError("executor must be LocalMockRemediationExecutor")
        if not all(
            callable(value)
            for value in (clock, request_id_factory, event_id_factory, nonce_factory)
        ):
            raise TypeError("clock and factories must be callable")
        if (
            isinstance(request_ttl_seconds, bool)
            or not isinstance(request_ttl_seconds, int)
            or not 60 <= request_ttl_seconds <= 3_600
        ):
            raise ValueError("request_ttl_seconds must be between 60 and 3600")
        self._repository = repository
        self._executor = executor
        self._clock = clock
        self._request_id_factory = request_id_factory
        self._event_id_factory = event_id_factory
        self._nonce_factory = nonce_factory
        self._request_ttl_seconds = request_ttl_seconds

    def request_approval(
        self,
        run_id: UUID,
        principal: LocalOperatorPrincipal,
    ) -> LocalApprovalChallengeResult:
        """Issue a fresh one-time challenge without persisting its raw nonce."""

        if not isinstance(principal, LocalOperatorPrincipal):
            return self._challenge_failed(
                FailureKind.VALIDATION_FAILURE,
                "LOCAL_OPERATOR_INVALID",
                "Local approval requires an authenticated operator principal",
            )
        loaded = self._load(run_id)
        if isinstance(loaded, FailureDetail):
            return LocalApprovalChallengeResult.failed(loaded)
        run, checkpoint, evidence, proposal = loaded
        if run.state is not WorkflowState.AWAITING_APPROVAL:
            return self._challenge_failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_APPROVAL_STATE_INVALID",
                "Local approval can be requested only from AWAITING_APPROVAL",
            )
        if checkpoint.local_approval is not None:
            return self._challenge_failed(
                FailureKind.IDEMPOTENCY_CONFLICT,
                "LOCAL_DECISION_ALREADY_RECORDED",
                "A durable human decision already exists for this proposal",
            )
        now = self._clock()
        if now >= proposal.expires_at:
            return self._challenge_failed(
                FailureKind.POLICY_DENIAL,
                "LOCAL_PROPOSAL_EXPIRED",
                "The local remediation proposal has expired",
            )
        nonce = self._nonce_factory()
        if (
            not isinstance(nonce, str)
            or nonce != nonce.strip()
            or not 16 <= len(nonce) <= 256
        ):
            return self._challenge_failed(
                FailureKind.CONFIGURATION_ERROR,
                "LOCAL_NONCE_FACTORY_INVALID",
                "The local approval nonce factory returned an invalid challenge",
            )
        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        expires_at = min(
            proposal.expires_at,
            now + timedelta(seconds=self._request_ttl_seconds),
        )
        try:
            request = LocalApprovalRequestRecord.create(
                request_id=self._request_id_factory(),
                proposal=proposal,
                actor_session_id=principal.actor_session_id,
                decision_nonce_hash=nonce_hash,
                requested_at=now,
                expires_at=expires_at,
            )
            next_checkpoint = self._next_checkpoint(
                checkpoint,
                last_safe_state=WorkflowState.AWAITING_APPROVAL,
                local_approval_request=request,
                local_approval=None,
                local_execution_intent=None,
                local_execution_receipt=None,
                local_verification=None,
                metadata={
                    "phase": "LOCAL_2",
                    "local_approval_request_hash": request.request_hash,
                },
            )
            self._repository.save_checkpoint(
                next_checkpoint,
                expected_version=checkpoint.version,
            )
            self._append_event(
                run,
                AuditEventType.APPROVAL_REQUESTED,
                request.request_hash,
                metadata={
                    "proposal_id": str(proposal.proposal_id),
                    "request_id": str(request.request_id),
                    "actor_session_id": principal.actor_session_id,
                },
            )
        except (StorageConflictError, StorageDependencyError, TypeError, ValueError):
            return self._challenge_storage_failed(
                "Local approval challenge could not be persisted"
            )
        return LocalApprovalChallengeResult.succeeded(
            LocalApprovalChallenge(
                request=request,
                proposal=proposal,
                evidence=evidence,
                decision_nonce=nonce,
            )
        )

    def decide(
        self,
        decision: LocalDecisionRequest,
        principal: LocalOperatorPrincipal,
    ) -> LocalApprovalResolutionResult:
        """Persist an exact bound decision before changing workflow authority."""

        if not isinstance(decision, LocalDecisionRequest) or not isinstance(
            principal, LocalOperatorPrincipal
        ):
            return self._resolution_failed(
                FailureKind.VALIDATION_FAILURE,
                "LOCAL_DECISION_INVALID",
                "Local decision and authenticated principal are required",
            )
        loaded = self._load(decision.run_id)
        if isinstance(loaded, FailureDetail):
            return LocalApprovalResolutionResult.failed(loaded)
        run, checkpoint, _, proposal = loaded
        request = checkpoint.local_approval_request
        if request is None:
            return self._resolution_failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_APPROVAL_REQUEST_MISSING",
                "No durable local approval challenge exists",
            )
        if not self._decision_matches_request(decision, principal, request):
            self._audit_policy_denial(run, proposal, "LOCAL_APPROVAL_BINDING_MISMATCH")
            return self._resolution_failed(
                FailureKind.POLICY_DENIAL,
                "LOCAL_APPROVAL_BINDING_MISMATCH",
                "Local decision does not match the durable proposal challenge",
            )
        existing = checkpoint.local_approval
        if existing is not None:
            expected_nonce_hash = hashlib.sha256(
                decision.decision_nonce.encode("utf-8")
            ).hexdigest()
            if (
                existing.request_id != decision.request_id
                or existing.request_hash != decision.request_hash
                or existing.decision is not decision.decision
                or not hmac.compare_digest(
                    existing.decision_nonce_hash,
                    expected_nonce_hash,
                )
            ):
                return self._resolution_failed(
                    FailureKind.IDEMPOTENCY_CONFLICT,
                    "LOCAL_APPROVAL_REPLAY_CONFLICT",
                    "A conflicting decision already owns this approval challenge",
                )
            reconciled = self._apply_decision_state(run, checkpoint, existing)
            if isinstance(reconciled, FailureDetail):
                return LocalApprovalResolutionResult.failed(reconciled)
            final_run, _ = reconciled
            return LocalApprovalResolutionResult.succeeded(
                self._resolution(final_run, existing, reconciled=True)
            )
        now = self._clock()
        if now > request.expires_at or now > proposal.expires_at:
            self._audit_policy_denial(run, proposal, "LOCAL_APPROVAL_EXPIRED")
            return self._resolution_failed(
                FailureKind.POLICY_DENIAL,
                "LOCAL_APPROVAL_EXPIRED",
                "Local approval challenge or proposal has expired",
            )
        approval = LocalApprovalDecisionRecord.create(
            request,
            decision=decision.decision,
            decided_at=now,
        )
        try:
            decision_checkpoint = self._next_checkpoint(
                checkpoint,
                last_safe_state=WorkflowState.AWAITING_APPROVAL,
                local_approval=approval,
                metadata={
                    "phase": "LOCAL_2",
                    "local_decision_hash": approval.decision_hash,
                },
            )
            decision_checkpoint = self._repository.save_checkpoint(
                decision_checkpoint,
                expected_version=checkpoint.version,
            )
        except (StorageConflictError, StorageDependencyError, ValueError):
            return self._resolution_storage_failed(
                "Local human decision could not be durably recorded"
            )
        applied = self._apply_decision_state(run, decision_checkpoint, approval)
        if isinstance(applied, FailureDetail):
            return LocalApprovalResolutionResult.failed(applied)
        final_run, final_checkpoint = applied
        try:
            self._append_event(
                final_run,
                AuditEventType.APPROVAL_RECORDED,
                approval.decision_hash,
                metadata={
                    "proposal_id": str(proposal.proposal_id),
                    "request_id": str(request.request_id),
                    "decision": approval.decision.value,
                    "actor_session_id": principal.actor_session_id,
                },
            )
        except (StorageConflictError, StorageDependencyError):
            return self._resolution_storage_failed(
                "Local decision audit could not be durably recorded"
            )
        return LocalApprovalResolutionResult.succeeded(
            self._resolution(final_run, final_checkpoint.local_approval, reconciled=False)
        )

    def resume(
        self,
        run_id: UUID,
        principal: LocalOperatorPrincipal,
    ) -> LocalExecutionResult:
        """Resume, execute once, independently verify, and reconcile after restart."""

        if not isinstance(principal, LocalOperatorPrincipal):
            return self._execution_failed(
                FailureKind.VALIDATION_FAILURE,
                "LOCAL_OPERATOR_INVALID",
                "Local resume requires an authenticated operator principal",
            )
        loaded = self._load(run_id)
        if isinstance(loaded, FailureDetail):
            return LocalExecutionResult.failed(loaded)
        run, checkpoint, evidence, proposal = loaded
        approval = checkpoint.local_approval
        if approval is None:
            return self._execution_failed(
                FailureKind.POLICY_DENIAL,
                "LOCAL_APPROVAL_REQUIRED",
                "Protected local execution requires a durable human decision",
            )
        if approval.actor_session_id != principal.actor_session_id:
            self._audit_policy_denial(run, proposal, "LOCAL_OPERATOR_SESSION_MISMATCH")
            return self._execution_failed(
                FailureKind.POLICY_DENIAL,
                "LOCAL_OPERATOR_SESSION_MISMATCH",
                "Only the authenticated deciding session may resume execution",
            )
        if approval.decision is ApprovalDecision.DENIED:
            applied = self._apply_decision_state(run, checkpoint, approval)
            if isinstance(applied, FailureDetail):
                return LocalExecutionResult.failed(applied)
            final_run, _ = applied
            return LocalExecutionResult.succeeded(
                LocalExecutionCompletion(
                    run_id=run.run_id,
                    proposal_id=proposal.proposal_id,
                    decision=approval.decision,
                    final_state=final_run.state,
                    approval=approval,
                    reconciled=run.state is WorkflowState.DENIED_BY_HUMAN,
                )
            )
        if run.state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            if checkpoint.last_safe_state is not WorkflowState.SUCCESS_WITH_EVIDENCE:
                try:
                    checkpoint = self._repository.save_checkpoint(
                        self._next_checkpoint(
                            checkpoint,
                            last_safe_state=WorkflowState.SUCCESS_WITH_EVIDENCE,
                            metadata={"phase": "LOCAL_2", "local_outcome": "verified"},
                        ),
                        expected_version=checkpoint.version,
                    )
                except (StorageConflictError, StorageDependencyError, ValueError):
                    return self._execution_storage_failed(
                        "Local success checkpoint could not be reconciled"
                    )
            return self._completed_from_checkpoint(run, checkpoint, reconciled=True)
        if run.state is WorkflowState.AWAITING_APPROVAL:
            applied = self._apply_decision_state(run, checkpoint, approval)
            if isinstance(applied, FailureDetail):
                return LocalExecutionResult.failed(applied)
            run, checkpoint = applied
        if self._clock() > proposal.expires_at:
            return self._mark_recovery_required(
                run,
                "LOCAL_APPROVAL_EXPIRED_BEFORE_EXECUTION",
                "Approved proposal expired before protected execution",
            )
        if run.state is WorkflowState.APPROVED:
            intent = checkpoint.local_execution_intent
            try:
                if intent is None:
                    intent = LocalExecutionIntent.create(
                        proposal,
                        approval,
                        registered_at=self._clock(),
                    )
                    checkpoint = self._repository.save_checkpoint(
                        self._next_checkpoint(
                            checkpoint,
                            last_safe_state=WorkflowState.APPROVED,
                            local_execution_intent=intent,
                            metadata={
                                "phase": "LOCAL_2",
                                "local_execution_intent_hash": intent.intent_hash,
                            },
                        ),
                        expected_version=checkpoint.version,
                    )
                    self._append_event(
                        run,
                        AuditEventType.IDEMPOTENCY_REGISTERED,
                        intent.intent_hash,
                        metadata={"proposal_id": str(proposal.proposal_id)},
                    )
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.EXECUTING,
                    expected_state=WorkflowState.APPROVED,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
                self._append_event(
                    run,
                    AuditEventType.EXECUTION_REQUESTED,
                    intent.intent_hash,
                    metadata={"proposal_id": str(proposal.proposal_id)},
                )
            except (StorageConflictError, StorageDependencyError, ValueError):
                return self._execution_storage_failed(
                    "Local execution ownership could not be established"
                )
        if run.state is WorkflowState.EXECUTING:
            intent = checkpoint.local_execution_intent
            if intent is None:
                return self._mark_recovery_required(
                    run,
                    "LOCAL_EXECUTION_INTENT_MISSING",
                    "Executing local run has no durable idempotency ownership",
                )
            receipt = checkpoint.local_execution_receipt
            try:
                if receipt is None:
                    receipt = self._executor.get_receipt(intent.idempotency_key)
                if receipt is None:
                    receipt = self._executor.execute(
                        proposal=proposal,
                        evidence=evidence,
                        approval=approval,
                        intent=intent,
                    )
                if checkpoint.local_execution_receipt is None:
                    checkpoint = self._repository.save_checkpoint(
                        self._next_checkpoint(
                            checkpoint,
                            last_safe_state=WorkflowState.APPROVED,
                            local_execution_receipt=receipt,
                            metadata={
                                "phase": "LOCAL_2",
                                "local_execution_receipt_hash": receipt.receipt_hash,
                            },
                        ),
                        expected_version=checkpoint.version,
                    )
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.VERIFYING,
                    expected_state=WorkflowState.EXECUTING,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
                self._append_event(
                    run,
                    AuditEventType.EXECUTION_ACKNOWLEDGED,
                    receipt.receipt_hash,
                    metadata={"proposal_id": str(proposal.proposal_id)},
                )
            except LocalMockPolicyError:
                return self._persist_execution_failure(
                    run,
                    WorkflowState.DENIED_BY_POLICY,
                    FailureKind.POLICY_DENIAL,
                    "LOCAL_EXECUTION_POLICY_DENIED",
                    "Protected local executor denied the exact action",
                )
            except LocalMockConflictError:
                return self._mark_recovery_required(
                    run,
                    "LOCAL_EXECUTION_CONFLICT",
                    "Local mock state conflicts with approved evidence",
                )
            except LocalMockMutationError:
                return self._persist_execution_failure(
                    run,
                    WorkflowState.DEPENDENCY_UNAVAILABLE,
                    FailureKind.DEPENDENCY_UNAVAILABLE,
                    "LOCAL_EXECUTOR_UNAVAILABLE",
                    "Protected local executor is unavailable",
                )
            except CloudAdapterUnavailableError:
                return self._persist_execution_failure(
                    run,
                    WorkflowState.DEPENDENCY_UNAVAILABLE,
                    FailureKind.DEPENDENCY_UNAVAILABLE,
                    "LOCAL_MOCK_STATE_UNAVAILABLE",
                    "Local mock inventory is unavailable",
                )
            except (StorageConflictError, StorageDependencyError, ValueError):
                return self._execution_failed(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "LOCAL_RECEIPT_DURABILITY_FAILED",
                    "Local execution receipt requires deterministic retry reconciliation",
                )
        if run.state is WorkflowState.VERIFYING:
            receipt = checkpoint.local_execution_receipt
            if receipt is None:
                return self._mark_verification_failed(
                    run,
                    "LOCAL_RECEIPT_MISSING",
                    "Verification cannot proceed without a durable execution receipt",
                )
            verification = checkpoint.local_verification
            try:
                if verification is None:
                    verification = self._executor.verify(receipt)
                    checkpoint = self._repository.save_checkpoint(
                        self._next_checkpoint(
                            checkpoint,
                            last_safe_state=WorkflowState.APPROVED,
                            local_verification=verification,
                            metadata={
                                "phase": "LOCAL_2",
                                "local_verification_hash": verification.verification_hash,
                            },
                        ),
                        expected_version=checkpoint.version,
                    )
                run = self._repository.transition_run(
                    run.run_id,
                    WorkflowState.SUCCESS_WITH_EVIDENCE,
                    expected_state=WorkflowState.VERIFYING,
                    expected_version=run.version,
                    updated_at=self._clock(),
                    verification_proposal_id=proposal.proposal_id,
                )
                checkpoint = self._repository.save_checkpoint(
                    self._next_checkpoint(
                        checkpoint,
                        last_safe_state=WorkflowState.SUCCESS_WITH_EVIDENCE,
                        metadata={"phase": "LOCAL_2", "local_outcome": "verified"},
                    ),
                    expected_version=checkpoint.version,
                )
                self._append_event(
                    run,
                    AuditEventType.VERIFICATION_RECORDED,
                    verification.verification_hash,
                    metadata={"proposal_id": str(proposal.proposal_id)},
                )
            except LocalMockMutationError:
                return self._mark_verification_failed(
                    run,
                    "LOCAL_VERIFICATION_MISMATCH",
                    "Independent local read-back did not prove the approved result",
                )
            except CloudAdapterUnavailableError:
                return self._persist_execution_failure(
                    run,
                    WorkflowState.DEPENDENCY_UNAVAILABLE,
                    FailureKind.DEPENDENCY_UNAVAILABLE,
                    "LOCAL_MOCK_STATE_UNAVAILABLE",
                    "Local mock inventory is unavailable during verification",
                )
            except (StorageConflictError, StorageDependencyError, ValueError):
                return self._execution_storage_failed(
                    "Local verification proof could not be durably closed"
                )
        return self._completed_from_checkpoint(run, checkpoint, reconciled=False)

    def _load(
        self,
        run_id: UUID,
    ) -> tuple[Run, Checkpoint, ResourceEvidence, RemediationProposal] | FailureDetail:
        try:
            run = self._repository.get_run(run_id)
            checkpoint = self._repository.get_checkpoint(run_id)
        except (StorageDependencyError, TypeError):
            return self._failure(
                FailureKind.STORAGE_FAILURE,
                "LOCAL_STATE_STORE_UNAVAILABLE",
                "Local durable state lookup is unavailable",
                retryable=True,
            )
        if run is None or checkpoint is None:
            return self._failure(
                FailureKind.NOT_FOUND,
                "LOCAL_RUN_NOT_FOUND",
                "Local run and checkpoint are required",
            )
        evidence = checkpoint.resource_evidence
        proposal = checkpoint.remediation_proposal
        if (
            evidence is None
            or proposal is None
            or evidence.run_id != run.run_id
            or evidence.trace_id != run.trace_id
            or evidence.correlation_id != run.correlation_id
            or proposal.run_id != run.run_id
            or proposal.correlation_id != run.correlation_id
            or proposal.evidence_hash != evidence.evidence_hash
        ):
            return self._failure(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_HITL_PREREQUISITES_INVALID",
                "Local run lacks exact durable evidence and proposal bindings",
            )
        return run, checkpoint, evidence, proposal

    def _apply_decision_state(
        self,
        run: Run,
        checkpoint: Checkpoint,
        approval: LocalApprovalDecisionRecord,
    ) -> tuple[Run, Checkpoint] | FailureDetail:
        target_state = (
            WorkflowState.APPROVED
            if approval.decision is ApprovalDecision.APPROVED
            else WorkflowState.DENIED_BY_HUMAN
        )
        try:
            downstream_approval = (
                approval.decision is ApprovalDecision.APPROVED
                and run.state in _APPROVED_DECISION_DOWNSTREAM_STATES
            )
            if run.state is not target_state and not downstream_approval:
                if run.state is not WorkflowState.AWAITING_APPROVAL:
                    raise StorageConflictError(
                        "run is not awaiting the durable local decision"
                    )
                run = self._repository.transition_run(
                    run.run_id,
                    target_state,
                    expected_state=WorkflowState.AWAITING_APPROVAL,
                    expected_version=run.version,
                    updated_at=self._clock(),
                    approval_proposal_id=approval.proposal_id,
                )
            if not downstream_approval and checkpoint.last_safe_state is not target_state:
                checkpoint = self._repository.save_checkpoint(
                    self._next_checkpoint(
                        checkpoint,
                        last_safe_state=target_state,
                        metadata={
                            "phase": "LOCAL_2",
                            "local_decision": approval.decision.value,
                        },
                    ),
                    expected_version=checkpoint.version,
                )
        except StorageConflictError:
            return self._failure(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_DECISION_STATE_CONFLICT",
                "Durable local decision conflicts with workflow state",
            )
        except StorageDependencyError:
            return self._failure(
                FailureKind.STORAGE_FAILURE,
                "LOCAL_STATE_STORE_UNAVAILABLE",
                "Local decision state persistence is unavailable",
                retryable=True,
            )
        return run, checkpoint

    @staticmethod
    def _decision_matches_request(
        decision: LocalDecisionRequest,
        principal: LocalOperatorPrincipal,
        request: LocalApprovalRequestRecord,
    ) -> bool:
        nonce_hash = hashlib.sha256(decision.decision_nonce.encode("utf-8")).hexdigest()
        return (
            decision.request_id == request.request_id
            and decision.run_id == request.run_id
            and decision.proposal_id == request.proposal_id
            and decision.request_hash == request.request_hash
            and decision.proposal_hash == request.proposal_hash
            and decision.evidence_hash == request.evidence_hash
            and decision.proposal_version == request.proposal_version
            and principal.actor_session_id == request.actor_session_id
            and hmac.compare_digest(nonce_hash, request.decision_nonce_hash)
        )

    def _next_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        last_safe_state: WorkflowState,
        metadata: dict[str, str],
        **updates: object,
    ) -> Checkpoint:
        payload = checkpoint.model_dump(mode="json")
        payload.update(updates)
        payload.update(
            {
                "created_at": self._clock(),
                "last_safe_state": last_safe_state,
                "resume_metadata": {
                    **checkpoint.resume_metadata,
                    **metadata,
                },
                "version": checkpoint.version + 1,
            }
        )
        return Checkpoint.model_validate(payload)

    def _append_event(
        self,
        run: Run,
        event_type: AuditEventType,
        payload_hash: str,
        *,
        metadata: dict[str, str],
    ) -> None:
        self._repository.append_audit_event(
            AuditEvent(
                event_id=self._event_id_factory(),
                run_id=run.run_id,
                type=event_type,
                timestamp=self._clock(),
                source="local-hitl",
                redacted_payload_hash=payload_hash,
                metadata={
                    **metadata,
                    "trace_id": str(run.trace_id),
                    "correlation_id": str(run.correlation_id),
                },
            )
        )

    def _audit_policy_denial(
        self,
        run: Run,
        proposal: RemediationProposal,
        code: str,
    ) -> None:
        with suppress(StorageConflictError, StorageDependencyError):
            self._append_event(
                run,
                AuditEventType.POLICY_DENIED,
                proposal.proposal_hash,
                metadata={"proposal_id": str(proposal.proposal_id), "policy_code": code},
            )

    def _completed_from_checkpoint(
        self,
        run: Run,
        checkpoint: Checkpoint,
        *,
        reconciled: bool,
    ) -> LocalExecutionResult:
        approval = checkpoint.local_approval
        proposal = checkpoint.remediation_proposal
        if (
            run.state is not WorkflowState.SUCCESS_WITH_EVIDENCE
            or approval is None
            or proposal is None
            or checkpoint.local_execution_receipt is None
            or checkpoint.local_verification is None
        ):
            return self._execution_failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_COMPLETION_PROOF_MISSING",
                "Local success requires durable receipt and verification proof",
            )
        return LocalExecutionResult.succeeded(
            LocalExecutionCompletion(
                run_id=run.run_id,
                proposal_id=proposal.proposal_id,
                decision=approval.decision,
                final_state=run.state,
                approval=approval,
                receipt=checkpoint.local_execution_receipt,
                verification=checkpoint.local_verification,
                reconciled=reconciled,
            )
        )

    def _mark_recovery_required(
        self,
        run: Run,
        code: str,
        message: str,
    ) -> LocalExecutionResult:
        return self._persist_execution_failure(
            run,
            WorkflowState.RECOVERY_REQUIRED,
            FailureKind.RECOVERY_REQUIREMENT,
            code,
            message,
        )

    def _mark_verification_failed(
        self,
        run: Run,
        code: str,
        message: str,
    ) -> LocalExecutionResult:
        return self._persist_execution_failure(
            run,
            WorkflowState.VERIFICATION_FAILED,
            FailureKind.VERIFICATION_FAILURE,
            code,
            message,
        )

    def _persist_execution_failure(
        self,
        run: Run,
        target_state: WorkflowState,
        kind: FailureKind,
        code: str,
        message: str,
    ) -> LocalExecutionResult:
        failure = self._failure(kind, code, message)
        try:
            if run.state is not target_state:
                self._repository.transition_run(
                    run.run_id,
                    target_state,
                    expected_state=run.state,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
        except (StorageConflictError, StorageDependencyError):
            return self._execution_storage_failed(
                "Local failure state could not be durably persisted"
            )
        return LocalExecutionResult.failed(failure)

    @staticmethod
    def _resolution(
        run: Run,
        approval: LocalApprovalDecisionRecord | None,
        *,
        reconciled: bool,
    ) -> LocalApprovalResolution:
        if approval is None:
            raise ValueError("resolution requires local approval")
        return LocalApprovalResolution(
            run_id=run.run_id,
            proposal_id=approval.proposal_id,
            request_id=approval.request_id,
            request_hash=approval.request_hash,
            decision_hash=approval.decision_hash,
            decision=approval.decision,
            final_state=(
                WorkflowState.APPROVED
                if approval.decision is ApprovalDecision.APPROVED
                else WorkflowState.DENIED_BY_HUMAN
            ),
            reconciled=reconciled,
        )

    @staticmethod
    def _failure(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> FailureDetail:
        return FailureDetail(kind=kind, code=code, message=message, retryable=retryable)

    @classmethod
    def _challenge_failed(
        cls,
        kind: FailureKind,
        code: str,
        message: str,
    ) -> LocalApprovalChallengeResult:
        return LocalApprovalChallengeResult.failed(cls._failure(kind, code, message))

    @classmethod
    def _resolution_failed(
        cls,
        kind: FailureKind,
        code: str,
        message: str,
    ) -> LocalApprovalResolutionResult:
        return LocalApprovalResolutionResult.failed(cls._failure(kind, code, message))

    @classmethod
    def _execution_failed(
        cls,
        kind: FailureKind,
        code: str,
        message: str,
    ) -> LocalExecutionResult:
        return LocalExecutionResult.failed(cls._failure(kind, code, message))

    @classmethod
    def _challenge_storage_failed(cls, message: str) -> LocalApprovalChallengeResult:
        return LocalApprovalChallengeResult.failed(
            cls._failure(
                FailureKind.STORAGE_FAILURE,
                "LOCAL_STATE_STORE_UNAVAILABLE",
                message,
                retryable=True,
            )
        )

    @classmethod
    def _resolution_storage_failed(cls, message: str) -> LocalApprovalResolutionResult:
        return LocalApprovalResolutionResult.failed(
            cls._failure(
                FailureKind.STORAGE_FAILURE,
                "LOCAL_STATE_STORE_UNAVAILABLE",
                message,
                retryable=True,
            )
        )

    @classmethod
    def _execution_storage_failed(cls, message: str) -> LocalExecutionResult:
        return LocalExecutionResult.failed(
            cls._failure(
                FailureKind.STORAGE_FAILURE,
                "LOCAL_STATE_STORE_UNAVAILABLE",
                message,
                retryable=True,
            )
        )
