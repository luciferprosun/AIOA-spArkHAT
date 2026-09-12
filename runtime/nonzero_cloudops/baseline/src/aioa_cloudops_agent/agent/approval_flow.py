"""Durable caller-facing request/resume control around native Strands HITL."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from strands.types.agent import Limits

from aioa_cloudops_agent.nz import (
    Approval,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    Checkpoint,
    ControlResult,
    FailureDetail,
    FailureKind,
    ProposalState,
    Run,
    Sha256Digest,
    Uuid7Identifier,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence import DurableTruthRepository
from aioa_cloudops_agent.safety.failures import workflow_state_for_failure

from .factory import PrimaryAgentRuntime
from .hitl import (
    ApprovalInterrupt,
    ApprovalResumeRequest,
    approval_request_hash,
    build_approval_payload,
)


class ApprovalResolution(BaseModel):
    """Durable decision result; approval is distinct from later execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    decision: ApprovalDecision
    final_state: Literal[WorkflowState.APPROVED, WorkflowState.DENIED_BY_HUMAN]
    request_hash: Sha256Digest
    native_resume_completed: bool
    reconciled: bool = False

    @model_validator(mode="after")
    def validate_decision_state(self) -> Self:
        expected = (
            WorkflowState.APPROVED
            if self.decision is ApprovalDecision.APPROVED
            else WorkflowState.DENIED_BY_HUMAN
        )
        if self.final_state is not expected:
            raise ValueError("approval decision and workflow state do not match")
        return self


ApprovalRequestResult = ControlResult[ApprovalInterrupt]
ApprovalResumeResult = ControlResult[ApprovalResolution]


class DurableApprovalFlow:
    """Persist proposal-bound human decisions before native tool execution resumes."""

    def __init__(
        self,
        runtime: PrimaryAgentRuntime,
        repository: DurableTruthRepository,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID],
    ) -> None:
        if not isinstance(runtime, PrimaryAgentRuntime):
            raise TypeError("runtime must be PrimaryAgentRuntime")
        if not callable(clock) or not callable(event_id_factory):
            raise TypeError("clock and event_id_factory must be callable")
        self._runtime = runtime
        self._repository = repository
        self._clock = clock
        self._event_id_factory = event_id_factory

    def request(self, proposal_id: UUID) -> ApprovalRequestResult:
        """Move durable truth to AWAITING_APPROVAL and return one native interrupt."""

        try:
            proposal = self._repository.get_proposal(proposal_id)
            if proposal is None:
                return self._failed(
                    FailureKind.VALIDATION_FAILURE,
                    "PROPOSAL_NOT_FOUND",
                    "Durable proposal is required before approval",
                )
            run = self._repository.get_run(proposal.run_id)
            checkpoint = self._repository.get_checkpoint(proposal.run_id)
        except StorageDependencyError:
            return self._storage_failed("Durable approval request lookup is unavailable")
        if run is None or checkpoint is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_PREREQUISITES_MISSING",
                "Durable run and evidence checkpoint are required",
            )
        if run.state is WorkflowState.AWAITING_APPROVAL:
            return self._reconcile_interrupt(run, proposal, checkpoint)
        if (
            run.state is not WorkflowState.REMEDIATION_PROPOSED
            or proposal.state is not ProposalState.PROPOSED
            or proposal.run_id != run.run_id
        ):
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_STATE_INVALID",
                "Approval can start only from the durable proposed state",
            )

        try:
            proposal = self._repository.transition_proposal(
                proposal.proposal_id,
                ProposalState.AWAITING_APPROVAL,
                expected_state=ProposalState.PROPOSED,
            )
            run = self._repository.transition_run(
                run.run_id,
                WorkflowState.AWAITING_APPROVAL,
                expected_state=WorkflowState.REMEDIATION_PROPOSED,
                expected_version=run.version,
                updated_at=self._clock(),
            )
        except StorageConflictError:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_TRANSITION_CONFLICT",
                "Durable approval transition could not be reconciled",
            )
        except StorageDependencyError:
            return self._storage_failed("Durable approval transition is unavailable")

        remaining_turns = run.budget.max_turns - run.budget.turns_used
        remaining_tokens = run.budget.max_tokens - run.budget.tokens_used
        remaining_milliseconds = (
            run.budget.max_elapsed_seconds * 1_000
            - run.budget.elapsed_milliseconds_used
        )
        if min(remaining_turns, remaining_tokens, remaining_milliseconds) <= 0:
            failure = FailureDetail(
                kind=FailureKind.BUDGET_EXHAUSTION,
                code="APPROVAL_BUDGET_ALREADY_EXHAUSTED",
                message="Durable budget was exhausted before approval interrupt generation",
                retryable=False,
            )
            try:
                self._append_event(
                    run,
                    AuditEventType.BUDGET_EXHAUSTED,
                    proposal.evidence_hash,
                    metadata={"failure_code": failure.code},
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failed("Approval budget audit is unavailable")
            return self._persist_request_failure(run, failure)
        limits: Limits = {
            "turns": remaining_turns,
            "output_tokens": min(
                remaining_tokens,
                self._runtime.model_settings.max_output_tokens,
            ),
            "total_tokens": remaining_tokens,
        }
        try:
            result = self._runtime.agent(
                "Request stop_sandbox_instance exactly once using only proposal_id "
                f"{proposal.proposal_id}. Do not add target or AWS parameters.",
                limits=limits,
            )
        except Exception:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "STRANDS_APPROVAL_INTERRUPT_FAILED",
                "Strands could not create the approval interrupt",
                retryable=True,
            )
        intervention_failure = getattr(
            self._runtime.human_in_the_loop,
            "last_failure",
            None,
        )
        if isinstance(intervention_failure, FailureDetail):
            return self._persist_request_failure(run, intervention_failure)
        if str(result.stop_reason).startswith("limit_"):
            failure = FailureDetail(
                kind=FailureKind.BUDGET_EXHAUSTION,
                code="APPROVAL_AGENT_BUDGET_EXHAUSTED",
                message="Bounded approval interrupt generation exhausted its model budget",
                retryable=False,
            )
            try:
                self._append_event(
                    run,
                    AuditEventType.BUDGET_EXHAUSTED,
                    proposal.evidence_hash,
                    metadata={"failure_code": failure.code},
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failed("Approval budget audit is unavailable")
            return self._persist_request_failure(run, failure)
        interrupts = tuple(result.interrupts or ())
        if result.stop_reason != "interrupt" or len(interrupts) != 1:
            failure = FailureDetail(
                kind=FailureKind.VALIDATION_FAILURE,
                code="APPROVAL_INTERRUPT_MISSING",
                message="Strands did not produce exactly one native approval interrupt",
                retryable=False,
            )
            try:
                self._append_event(
                    run,
                    AuditEventType.MODEL_OUTPUT_REJECTED,
                    proposal.evidence_hash,
                    metadata={"failure_code": failure.code},
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failed("Approval model-output audit is unavailable")
            return self._persist_request_failure(run, failure)
        interrupt = interrupts[0]
        payload = build_approval_payload(proposal)
        request_hash = approval_request_hash(payload)
        try:
            next_checkpoint = Checkpoint(
                run_id=run.run_id,
                last_safe_state=WorkflowState.AWAITING_APPROVAL,
                resume_metadata={
                    **checkpoint.resume_metadata,
                    "approval_interrupt_id": interrupt.id,
                    "approval_request_hash": request_hash,
                    "proposal_id": str(proposal.proposal_id),
                },
                tool_result_hashes=checkpoint.tool_result_hashes,
                created_at=self._clock(),
                version=checkpoint.version + 1,
            )
            self._repository.save_checkpoint(
                next_checkpoint,
                expected_version=checkpoint.version,
            )
            self._append_event(
                run,
                AuditEventType.APPROVAL_REQUESTED,
                request_hash,
                metadata={"proposal_id": str(proposal.proposal_id)},
            )
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failed("Approval interrupt checkpoint persistence failed")
        return ApprovalRequestResult.succeeded(
            ApprovalInterrupt(
                interrupt_id=interrupt.id,
                payload=payload,
                request_hash=request_hash,
                trace_id=run.trace_id,
                correlation_id=run.correlation_id,
            )
        )

    def resume(self, response: ApprovalResumeRequest) -> ApprovalResumeResult:
        """Persist the exact decision, transition, then resume the native Strands call."""

        if not isinstance(response, ApprovalResumeRequest):
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "APPROVAL_RESPONSE_INVALID",
                "Approval response must use the typed resume contract",
            )
        try:
            proposal = self._repository.get_proposal(response.proposal_id)
            run = self._repository.get_run(response.run_id)
            checkpoint = self._repository.get_checkpoint(response.run_id)
        except StorageDependencyError:
            return self._storage_failed("Durable approval resume lookup is unavailable")
        if proposal is None or run is None or checkpoint is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_RESUME_MISSING_STATE",
                "Approval resume requires durable run, proposal, and checkpoint",
            )
        payload = build_approval_payload(proposal)
        expected_hash = approval_request_hash(payload)
        if (
            response.run_id != proposal.run_id
            or response.action is not proposal.action
            or response.target != proposal.target
            or response.evidence_hash != proposal.evidence_hash
            or response.request_hash != expected_hash
            or checkpoint.resume_metadata.get("approval_interrupt_id")
            != response.interrupt_id
            or checkpoint.resume_metadata.get("approval_request_hash") != expected_hash
        ):
            try:
                self._append_event(
                    run,
                    AuditEventType.POLICY_DENIED,
                    expected_hash,
                    metadata={
                        "policy_code": "APPROVAL_BINDING_MISMATCH",
                        "proposal_id": str(proposal.proposal_id),
                    },
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failed("Approval denial audit is unavailable")
            return self._failed(
                FailureKind.POLICY_DENIAL,
                "APPROVAL_BINDING_MISMATCH",
                "Approval response does not match the durable interrupt and proposal",
            )
        approval = Approval(
            proposal_id=proposal.proposal_id,
            run_id=proposal.run_id,
            action=proposal.action,
            target=proposal.target,
            evidence_hash=proposal.evidence_hash,
            interrupt_id=response.interrupt_id,
            request_hash=response.request_hash,
            decision=response.decision,
            decided_at=self._clock(),
            actor_session_id=response.actor_session_id,
            decision_nonce=response.decision_nonce,
        )
        target_state = (
            WorkflowState.APPROVED
            if response.decision is ApprovalDecision.APPROVED
            else WorkflowState.DENIED_BY_HUMAN
        )
        try:
            existing = self._repository.get_approval(proposal.proposal_id)
            if existing is not None:
                semantically_identical = approval.model_copy(
                    update={"decided_at": existing.decided_at}
                )
                if existing != semantically_identical:
                    raise StorageConflictError("conflicting durable decision already exists")
                approval = existing
            else:
                self._repository.create_approval(approval)
            if run.state is target_state:
                return ApprovalResumeResult.succeeded(
                    self._resolution(run, response.decision, expected_hash, reconciled=True)
                )
            if run.state is not WorkflowState.AWAITING_APPROVAL:
                raise StorageConflictError("run is not awaiting this human decision")
            run = self._repository.transition_run(
                run.run_id,
                target_state,
                expected_state=WorkflowState.AWAITING_APPROVAL,
                expected_version=run.version,
                updated_at=self._clock(),
                approval_proposal_id=proposal.proposal_id,
            )
            self._repository.save_checkpoint(
                Checkpoint(
                    run_id=run.run_id,
                    last_safe_state=target_state,
                    resume_metadata={
                        **checkpoint.resume_metadata,
                        "approval_decision": response.decision.value,
                    },
                    tool_result_hashes=checkpoint.tool_result_hashes,
                    created_at=self._clock(),
                    version=checkpoint.version + 1,
                ),
                expected_version=checkpoint.version,
            )
            self._append_event(
                run,
                AuditEventType.APPROVAL_RECORDED,
                response.request_hash,
                metadata={
                    "proposal_id": str(proposal.proposal_id),
                    "decision": response.decision.value,
                },
            )
        except StorageConflictError:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_DECISION_CONFLICT",
                "Durable human decision conflicts with existing state",
            )
        except StorageDependencyError:
            return self._storage_failed("Durable human decision persistence failed")

        try:
            native_result = self._runtime.agent(
                [
                    {
                        "interruptResponse": {
                            "interruptId": response.interrupt_id,
                            "response": response.decision is ApprovalDecision.APPROVED,
                        }
                    }
                ]
            )
        except Exception:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "STRANDS_APPROVAL_RESUME_FAILED",
                "Durable decision exists but native Strands resume requires recovery",
            )
        if native_result.stop_reason == "interrupt":
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "STRANDS_APPROVAL_REINTERRUPTED",
                "Native Strands resume produced an unexpected additional interrupt",
            )
        return ApprovalResumeResult.succeeded(
            self._resolution(run, response.decision, expected_hash, reconciled=False)
        )

    def _reconcile_interrupt(
        self,
        run: Run,
        proposal: object,
        checkpoint: Checkpoint,
    ) -> ApprovalRequestResult:
        from aioa_cloudops_agent.nz import ActionProposal

        if not isinstance(proposal, ActionProposal) or proposal.state is not ProposalState.AWAITING_APPROVAL:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_RECONCILIATION_INVALID",
                "Awaiting run and proposal state are inconsistent",
            )
        interrupt_id = checkpoint.resume_metadata.get("approval_interrupt_id")
        payload = build_approval_payload(proposal)
        request_hash = approval_request_hash(payload)
        if (
            not isinstance(interrupt_id, str)
            or checkpoint.resume_metadata.get("approval_request_hash") != request_hash
        ):
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "APPROVAL_INTERRUPT_STATE_MISSING",
                "Durable interrupt metadata requires recovery",
            )
        return ApprovalRequestResult.succeeded(
            ApprovalInterrupt(
                interrupt_id=interrupt_id,
                payload=payload,
                request_hash=request_hash,
                trace_id=run.trace_id,
                correlation_id=run.correlation_id,
                reconciled=True,
            )
        )

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
                source="strands-hitl",
                tool_name="stop_sandbox_instance",
                redacted_payload_hash=payload_hash,
                metadata={
                    **metadata,
                    "trace_id": str(run.trace_id),
                    "correlation_id": str(run.correlation_id),
                },
            )
        )

    def _persist_request_failure(
        self,
        run: Run,
        failure: FailureDetail,
    ) -> ControlResult:
        try:
            self._repository.transition_run(
                run.run_id,
                workflow_state_for_failure(failure),
                expected_state=run.state,
                expected_version=run.version,
                updated_at=self._clock(),
            )
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failed("Approval failure state could not be persisted")
        return ControlResult.failed(failure)

    def _resolution(
        self,
        run: Run,
        decision: ApprovalDecision,
        request_hash: str,
        *,
        reconciled: bool,
    ) -> ApprovalResolution:
        return ApprovalResolution(
            run_id=run.run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            proposal_id=self._runtime.proposal_id,
            decision=decision,
            final_state=run.state,
            request_hash=request_hash,
            native_resume_completed=not reconciled,
            reconciled=reconciled,
        )

    @staticmethod
    def _failed(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> ControlResult:
        return ControlResult.failed(
            FailureDetail(
                kind=kind,
                code=code,
                message=message,
                retryable=retryable,
            )
        )

    @classmethod
    def _storage_failed(cls, message: str) -> ControlResult:
        return cls._failed(
            FailureKind.DEPENDENCY_UNAVAILABLE,
            "DURABLE_APPROVAL_UNAVAILABLE",
            message,
            retryable=True,
        )
