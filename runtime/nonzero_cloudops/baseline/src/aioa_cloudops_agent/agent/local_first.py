"""Canonical Local-First Phase 1 flow ending at the durable approval boundary."""

from collections.abc import Callable
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from aioa_cloudops_agent.cloudops import PlanRemediation, QueryResource
from aioa_cloudops_agent.domain import ApprovalStatus, ExecutionState
from aioa_cloudops_agent.nz import (
    AuditEvent,
    AuditEventType,
    Checkpoint,
    ControlResult,
    FailureDetail,
    FailureKind,
    PlanDisposition,
    ProposalState,
    RemediationPlan,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
    ResultStatus,
    Run,
    Uuid7Identifier,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence import DurableTruthRepository, compute_evidence_digest
from aioa_cloudops_agent.providers import (
    ModelProvider,
    ModelProviderError,
    ModelProviderNonRetryableError,
    ModelProviderRetryableError,
    ModelProviderTimeoutError,
)
from aioa_cloudops_agent.safety import workflow_state_for_failure


class LocalFirstCompletion(BaseModel):
    """Explicit local result; protected proposals stop before any cloud write."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    evidence: ResourceEvidence
    plan: RemediationPlan
    final_state: Literal[
        WorkflowState.AWAITING_APPROVAL,
        WorkflowState.NO_ACTION_REQUIRED,
        WorkflowState.RECOMMENDATION_ONLY,
    ]
    public_state: ExecutionState
    approval_status: ApprovalStatus
    reconciled: bool = False

    @model_validator(mode="after")
    def validate_state_projection(self) -> Self:
        if (
            self.evidence.run_id != self.run_id
            or self.evidence.trace_id != self.trace_id
            or self.evidence.correlation_id != self.correlation_id
            or self.plan.evidence_hash != self.evidence.evidence_hash
        ):
            raise ValueError("local completion identities and evidence must match")
        if self.final_state is WorkflowState.AWAITING_APPROVAL:
            if (
                self.public_state is not ExecutionState.PENDING
                or self.approval_status is not ApprovalStatus.PENDING_APPROVAL
                or self.plan.disposition is not PlanDisposition.PROPOSAL
                or self.plan.proposal is None
                or self.plan.proposal.status is not ProposalState.AWAITING_APPROVAL
                or self.plan.proposal.authorizes_execution
            ):
                raise ValueError("approval-bound completion is inconsistent")
        elif (
            self.public_state is not ExecutionState.SUCCESS
            or self.approval_status is not ApprovalStatus.NOT_REQUIRED
        ):
            raise ValueError("safe terminal local completion is inconsistent")
        return self


LocalFirstResult = ControlResult[LocalFirstCompletion]


class LocalFirstPhaseOneFlow:
    """Use canonical NZ state, adapters, tools, and durability with no mutation API."""

    def __init__(
        self,
        *,
        query_resource: QueryResource,
        plan_remediation: PlanRemediation,
        model_provider: ModelProvider,
        repository: DurableTruthRepository,
        clock: Callable[[], datetime],
        proposal_id_factory: Callable[[], UUID],
        event_id_factory: Callable[[], UUID],
    ) -> None:
        if not isinstance(query_resource, QueryResource):
            raise TypeError("query_resource must be QueryResource")
        if not isinstance(plan_remediation, PlanRemediation):
            raise TypeError("plan_remediation must be PlanRemediation")
        if not callable(getattr(model_provider, "create_plan", None)):
            raise TypeError("model_provider must implement create_plan")
        if not all(callable(value) for value in (clock, proposal_id_factory, event_id_factory)):
            raise TypeError("clock and identifier factories must be callable")
        self._query = query_resource
        self._planner = plan_remediation
        self._model = model_provider
        self._repository = repository
        self._clock = clock
        self._proposal_id_factory = proposal_id_factory
        self._event_id_factory = event_id_factory

    def execute(self, run: Run, query: ResourceQuery | object) -> LocalFirstResult:
        """Execute read and planning through PENDING_APPROVAL, never beyond it."""

        if not isinstance(run, Run):
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "LOCAL_RUN_INVALID",
                "Local flow requires a typed run",
            )
        try:
            current = self._repository.get_run(run.run_id)
        except StorageDependencyError:
            return self._storage_failed("Local run lookup is unavailable")
        if current is not None and current != run:
            return self._reconcile(current)
        if current is None:
            try:
                current = self._repository.create_run(run)
                self._append_event(
                    current,
                    AuditEventType.RUN_CREATED,
                    compute_evidence_digest(run.model_dump(mode="json")),
                    source="local-nz-control",
                )
            except StorageConflictError:
                try:
                    raced = self._repository.get_run(run.run_id)
                except StorageDependencyError:
                    return self._storage_failed("Local run reconciliation is unavailable")
                if raced is None:
                    return self._storage_failed("Local run creation conflicted")
                return self._reconcile(raced)
            except StorageDependencyError:
                return self._storage_failed("Local run creation is unavailable")
        if current.state is not WorkflowState.RECEIVED:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_RUN_STATE_INVALID",
                "Local flow can start only from RECEIVED",
            )
        try:
            current = self._transition(current, WorkflowState.INVESTIGATING)
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failed("Durable INVESTIGATING transition failed")

        observed_at = self._clock()
        query_result = self._query.execute(query, run=current, observed_at=observed_at)
        if query_result.status is ResultStatus.FAILURE:
            if query_result.failure is None:
                return self._storage_failed("QueryResource returned an ambiguous failure")
            return self._persist_failure(current, query_result.failure)
        evidence = query_result.value
        if evidence is None:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.TOOL_ADAPTER_FAILURE,
                    code="QUERY_EVIDENCE_MISSING",
                    message="QueryResource did not return typed evidence",
                    retryable=False,
                ),
            )
        try:
            self._append_event(
                current,
                AuditEventType.RESOURCE_QUERIED,
                evidence.evidence_hash,
                source="query-resource",
                metadata={
                    "resource_id": evidence.resource.resource_id,
                    "resource_type": evidence.resource.resource_type.value,
                },
            )
            current = self._transition(current, WorkflowState.EVIDENCE_READY)
            self._repository.save_checkpoint(
                Checkpoint(
                    run_id=current.run_id,
                    last_safe_state=WorkflowState.EVIDENCE_READY,
                    resume_metadata={"phase": "LOCAL_1"},
                    tool_result_hashes={"query_resource": evidence.evidence_hash},
                    resource_evidence=evidence,
                    created_at=self._clock(),
                    version=1,
                ),
                expected_version=None,
            )
        except (StorageConflictError, StorageDependencyError):
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.STORAGE_FAILURE,
                    code="EVIDENCE_PERSISTENCE_FAILED",
                    message="Resource evidence could not be persisted",
                    retryable=True,
                ),
            )

        try:
            raw_plan = self._model.create_plan(evidence)
        except ModelProviderTimeoutError:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.PROVIDER_FAILURE,
                    code="MODEL_PROVIDER_TIMEOUT",
                    message="Model provider exhausted its bounded response time",
                    retryable=False,
                ),
            )
        except ModelProviderNonRetryableError:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.PROVIDER_FAILURE,
                    code="MODEL_PROVIDER_NON_RETRYABLE_FAILURE",
                    message="Model provider returned a permanent failure",
                    retryable=False,
                ),
            )
        except ModelProviderRetryableError:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.PROVIDER_FAILURE,
                    code="MODEL_PROVIDER_RETRYABLE_FAILURE",
                    message="Model provider returned a retryable failure",
                    retryable=True,
                ),
            )
        except ModelProviderError:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.PROVIDER_FAILURE,
                    code="MODEL_PROVIDER_FAILED",
                    message="Model provider is unavailable",
                    retryable=True,
                ),
            )
        except Exception:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.PROVIDER_FAILURE,
                    code="MODEL_PROVIDER_INVALID_FAILURE",
                    message="Model provider failed outside its typed contract",
                    retryable=False,
                ),
            )
        plan_result = self._planner.execute(
            evidence,
            model_output=raw_plan,
            proposal_id=self._proposal_id_factory(),
            created_at=self._clock(),
        )
        if plan_result.status is ResultStatus.FAILURE:
            failure = plan_result.failure
            if failure is None:
                return self._storage_failed("PlanRemediation returned an ambiguous failure")
            try:
                self._append_event(
                    current,
                    AuditEventType.MODEL_OUTPUT_REJECTED,
                    evidence.evidence_hash,
                    source="local-plan-policy",
                    metadata={"failure_code": failure.code},
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failed("Rejected model plan audit is unavailable")
            return self._persist_failure(current, failure)
        plan = plan_result.value
        if plan is None:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.VALIDATION_FAILURE,
                    code="PLAN_RESULT_MISSING",
                    message="PlanRemediation did not return a typed outcome",
                    retryable=False,
                ),
            )
        if plan.disposition is PlanDisposition.NO_ACTION:
            return self._complete_safe_terminal(
                current,
                evidence,
                plan,
                WorkflowState.NO_ACTION_REQUIRED,
                AuditEventType.NO_ACTION_RECORDED,
            )
        if plan.disposition is PlanDisposition.NON_EXECUTABLE_RECOMMENDATION:
            return self._complete_safe_terminal(
                current,
                evidence,
                plan,
                WorkflowState.RECOMMENDATION_ONLY,
                AuditEventType.RECOMMENDATION_RECORDED,
            )
        proposal = plan.proposal
        if proposal is None or proposal.authorizes_execution:
            return self._persist_failure(
                current,
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="PROTECTED_PROPOSAL_INVALID",
                    message="Protected plan did not produce inert proposal data",
                    retryable=False,
                ),
            )
        try:
            current = self._transition(current, WorkflowState.REMEDIATION_PROPOSED)
            awaiting_proposal = RemediationProposal.model_validate(
                {
                    **proposal.model_dump(mode="json"),
                    "status": ProposalState.AWAITING_APPROVAL,
                    "version": proposal.version + 1,
                }
            )
            self._repository.save_checkpoint(
                Checkpoint(
                    run_id=current.run_id,
                    last_safe_state=WorkflowState.AWAITING_APPROVAL,
                    resume_metadata={
                        "phase": "LOCAL_1",
                        "proposal_hash": awaiting_proposal.proposal_hash,
                        "proposal_id": str(awaiting_proposal.proposal_id),
                    },
                    tool_result_hashes={
                        "plan_remediation": awaiting_proposal.proposal_hash,
                        "query_resource": evidence.evidence_hash,
                    },
                    resource_evidence=evidence,
                    remediation_proposal=awaiting_proposal,
                    created_at=self._clock(),
                    version=2,
                ),
                expected_version=1,
            )
            current = self._transition(current, WorkflowState.AWAITING_APPROVAL)
            self._append_event(
                current,
                AuditEventType.REMEDIATION_PLANNED,
                awaiting_proposal.proposal_hash,
                source="plan-remediation",
                metadata={
                    "proposal_id": str(awaiting_proposal.proposal_id),
                    "authority": awaiting_proposal.authority_class.value,
                },
            )
            self._append_event(
                current,
                AuditEventType.APPROVAL_REQUESTED,
                awaiting_proposal.proposal_hash,
                source="local-approval-boundary",
                metadata={"proposal_id": str(awaiting_proposal.proposal_id)},
            )
        except (StorageConflictError, StorageDependencyError, ValueError):
            return self._storage_failed("Protected proposal persistence or transition failed")
        protected_plan = plan.model_copy(update={"proposal": awaiting_proposal})
        return LocalFirstResult.succeeded(
            self._completion(current, evidence, protected_plan, reconciled=False)
        )

    def _complete_safe_terminal(
        self,
        run: Run,
        evidence: ResourceEvidence,
        plan: RemediationPlan,
        target_state: Literal[
            WorkflowState.NO_ACTION_REQUIRED,
            WorkflowState.RECOMMENDATION_ONLY,
        ],
        event_type: AuditEventType,
    ) -> LocalFirstResult:
        try:
            current = self._transition(run, target_state)
            self._repository.save_checkpoint(
                Checkpoint(
                    run_id=current.run_id,
                    last_safe_state=target_state,
                    resume_metadata={
                        "phase": "LOCAL_1",
                        "plan_disposition": plan.disposition.value,
                        "reason": plan.reason,
                    },
                    tool_result_hashes={
                        "plan_remediation": (
                            evidence.evidence_hash
                            if plan.proposal is None
                            else plan.proposal.proposal_hash
                        ),
                        "query_resource": evidence.evidence_hash,
                    },
                    resource_evidence=evidence,
                    remediation_proposal=plan.proposal,
                    created_at=self._clock(),
                    version=2,
                ),
                expected_version=1,
            )
            self._append_event(
                current,
                event_type,
                evidence.evidence_hash if plan.proposal is None else plan.proposal.proposal_hash,
                source="plan-remediation",
            )
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failed("Safe terminal plan persistence failed")
        return LocalFirstResult.succeeded(
            self._completion(current, evidence, plan, reconciled=False)
        )

    def _reconcile(self, run: Run) -> LocalFirstResult:
        if run.state not in {
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.NO_ACTION_REQUIRED,
            WorkflowState.RECOMMENDATION_ONLY,
        }:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_RUN_ALREADY_ACTIVE",
                "Existing local run requires explicit recovery",
            )
        try:
            checkpoint = self._repository.get_checkpoint(run.run_id)
        except StorageDependencyError:
            return self._storage_failed("Local completion checkpoint is unavailable")
        if checkpoint is None or checkpoint.resource_evidence is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_CHECKPOINT_MISSING",
                "Terminal local run has no complete checkpoint",
            )
        evidence = checkpoint.resource_evidence
        proposal = checkpoint.remediation_proposal
        if run.state is WorkflowState.NO_ACTION_REQUIRED:
            plan = RemediationPlan(
                disposition=PlanDisposition.NO_ACTION,
                evidence_hash=evidence.evidence_hash,
                reason=str(checkpoint.resume_metadata.get("reason", "No action required")),
            )
        elif proposal is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_PROPOSAL_MISSING",
                "Terminal local run has no durable proposal",
            )
        else:
            disposition = (
                PlanDisposition.PROPOSAL
                if run.state is WorkflowState.AWAITING_APPROVAL
                else PlanDisposition.NON_EXECUTABLE_RECOMMENDATION
            )
            plan = RemediationPlan(
                disposition=disposition,
                evidence_hash=evidence.evidence_hash,
                proposal=proposal,
                reason=proposal.risk_summary,
            )
        try:
            return LocalFirstResult.succeeded(
                self._completion(run, evidence, plan, reconciled=True)
            )
        except ValueError:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "LOCAL_CHECKPOINT_INVALID",
                "Terminal local checkpoint is internally inconsistent",
            )

    def _completion(
        self,
        run: Run,
        evidence: ResourceEvidence,
        plan: RemediationPlan,
        *,
        reconciled: bool,
    ) -> LocalFirstCompletion:
        pending = run.state is WorkflowState.AWAITING_APPROVAL
        return LocalFirstCompletion(
            run_id=run.run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            evidence=evidence,
            plan=plan,
            final_state=run.state,
            public_state=ExecutionState.PENDING if pending else ExecutionState.SUCCESS,
            approval_status=(
                ApprovalStatus.PENDING_APPROVAL if pending else ApprovalStatus.NOT_REQUIRED
            ),
            reconciled=reconciled,
        )

    def _transition(self, run: Run, next_state: WorkflowState) -> Run:
        return self._repository.transition_run(
            run.run_id,
            next_state,
            expected_state=run.state,
            expected_version=run.version,
            updated_at=self._clock(),
        )

    def _append_event(
        self,
        run: Run,
        event_type: AuditEventType,
        payload_hash: str,
        *,
        source: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._repository.append_audit_event(
            AuditEvent(
                event_id=self._event_id_factory(),
                run_id=run.run_id,
                type=event_type,
                timestamp=self._clock(),
                source=source,
                redacted_payload_hash=payload_hash,
                metadata={
                    "trace_id": str(run.trace_id),
                    "correlation_id": str(run.correlation_id),
                    **(metadata or {}),
                },
            )
        )

    def _persist_failure(self, run: Run, failure: FailureDetail) -> LocalFirstResult:
        try:
            self._transition(run, workflow_state_for_failure(failure))
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failed("Typed local failure could not be persisted")
        return LocalFirstResult.failed(failure)

    @staticmethod
    def _failed(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> LocalFirstResult:
        return LocalFirstResult.failed(
            FailureDetail(kind=kind, code=code, message=message, retryable=retryable)
        )

    @classmethod
    def _storage_failed(cls, message: str) -> LocalFirstResult:
        return cls._failed(
            FailureKind.STORAGE_FAILURE,
            "LOCAL_STATE_STORE_UNAVAILABLE",
            message,
            retryable=True,
        )
