"""Non-Zero orchestrator for one approval-bound private sandbox stop."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from aioa_cloudops_agent.nz import (
    ActionOutcome,
    ActionResult,
    AuditEvent,
    AuditEventType,
    ControlResult,
    FailureDetail,
    FailureKind,
    IdempotencyStatus,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import (
    DurablePrerequisiteError,
    StorageConflictError,
    StorageDependencyError,
)
from aioa_cloudops_agent.persistence import (
    DurableTruthRepository,
    compute_evidence_digest,
    derive_idempotency_key,
    load_execution_prerequisites,
    register_approved_action,
)
from aioa_cloudops_agent.safety.failures import workflow_state_for_failure

from .command import build_stop_execution_command
from .emergency import EXECUTOR_EMERGENCY_DISABLED
from .errors import (
    RemediationAmbiguousError,
    RemediationDependencyError,
    RemediationDisabledError,
    RemediationEmergencyDisabledError,
    RemediationExecutionError,
    RemediationScopeError,
)
from .executor import PrivateRemediationExecutor


class StopSandboxInstanceCoordinator:
    """Own state/idempotency while delegating EC2 authority to a private executor."""

    def __init__(
        self,
        repository: DurableTruthRepository,
        executor: PrivateRemediationExecutor,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID],
    ) -> None:
        if not callable(clock) or not callable(event_id_factory):
            raise TypeError("clock and event_id_factory must be callable")
        self._repository = repository
        self._executor = executor
        self._clock = clock
        self._event_id_factory = event_id_factory

    def execute(self, proposal_id: UUID) -> ControlResult:
        """Execute once only after durable approval; never infer authority from input."""

        try:
            proposal = self._repository.get_proposal(proposal_id)
        except StorageDependencyError:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "PROPOSAL_LOOKUP_UNAVAILABLE",
                "Durable proposal lookup is unavailable",
                retryable=True,
            )
        if proposal is None:
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "PROPOSAL_NOT_FOUND",
                "Durable proposal is required",
            )
        idempotency_key = derive_idempotency_key(proposal)
        try:
            existing = self._repository.get_idempotency(idempotency_key)
        except StorageDependencyError:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "IDEMPOTENCY_LOOKUP_UNAVAILABLE",
                "Durable idempotency lookup is unavailable",
                retryable=True,
            )
        if existing is not None:
            if (
                existing.proposal_id != proposal.proposal_id
                or existing.idempotency_key != idempotency_key
            ):
                return self._failed(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "IDEMPOTENCY_OWNERSHIP_CONFLICT",
                    "Durable idempotency ownership is inconsistent",
                )
            if existing.execution_acknowledgement is not None:
                try:
                    existing_run = self._repository.get_run(proposal.run_id)
                except StorageDependencyError:
                    return self._failed(
                        FailureKind.DEPENDENCY_UNAVAILABLE,
                        "RUN_RECONCILIATION_UNAVAILABLE",
                        "Durable run reconciliation is unavailable",
                        retryable=True,
                    )
                if existing_run is not None and existing_run.state in {
                    WorkflowState.VERIFYING,
                    WorkflowState.SUCCESS_WITH_EVIDENCE,
                }:
                    return ControlResult.succeeded(existing.execution_acknowledgement)
                return self._mark_recovery_required(
                    proposal.run_id,
                    "ACKNOWLEDGEMENT_STATE_UNRECONCILED",
                    "Execution acknowledgement exists without a safe verifying state",
                )
            if existing.status is IdempotencyStatus.REGISTERED:
                return self._mark_recovery_required(
                    proposal.run_id,
                    "IDEMPOTENCY_IN_PROGRESS",
                    "Unresolved in-progress mutation must not be blindly replayed",
                )
            if existing.action_result is not None and existing.action_result.failure is not None:
                return ControlResult.failed(existing.action_result.failure)
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "IDEMPOTENCY_RESULT_UNRECONCILED",
                "Existing action result requires reconciliation",
            )

        try:
            idempotency = register_approved_action(
                self._repository,
                proposal_id,
                registered_at=self._clock(),
            )
            prerequisites = load_execution_prerequisites(self._repository, proposal_id)
            run = prerequisites.run
            run = self._repository.transition_run(
                run.run_id,
                WorkflowState.EXECUTING,
                expected_state=WorkflowState.APPROVED,
                expected_version=run.version,
                updated_at=self._clock(),
            )
            command = build_stop_execution_command(
                prerequisites,
                issued_at=self._clock(),
            )
            self._append_event(
                run,
                AuditEventType.EXECUTION_REQUESTED,
                idempotency.action_fingerprint,
                metadata={"proposal_id": str(proposal.proposal_id)},
            )
        except DurablePrerequisiteError as error:
            return self._failed(
                FailureKind.POLICY_DENIAL,
                "EXECUTION_PREREQUISITES_DENIED",
                str(error),
            )
        except StorageConflictError:
            return self._mark_recovery_required(
                proposal.run_id,
                "EXECUTION_OWNERSHIP_CONFLICT",
                "Durable execution ownership could not be established safely",
            )
        except StorageDependencyError:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "EXECUTION_DURABILITY_UNAVAILABLE",
                "Durable write-before-execute state is unavailable",
                retryable=True,
            )

        try:
            acknowledgement = self._executor.execute(command)
        except RemediationEmergencyDisabledError:
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code=EXECUTOR_EMERGENCY_DISABLED,
                    message="Independent executor emergency control denied the mutation",
                    retryable=False,
                ),
                ActionOutcome.FAILED,
            )
        except (RemediationDisabledError, RemediationScopeError):
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="SANDBOX_EXECUTION_DENIED",
                    message="Private executor rejected configuration, scope, or precondition",
                    retryable=False,
                ),
                ActionOutcome.FAILED,
            )
        except RemediationDependencyError:
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                    code="STOP_DEPENDENCY_UNAVAILABLE",
                    message="Private executor dependency is unavailable before safe acknowledgement",
                    retryable=True,
                ),
                ActionOutcome.FAILED,
            )
        except RemediationExecutionError:
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.EXECUTION_FAILURE,
                    code="STOP_EXECUTION_FAILED",
                    message="StopInstances returned an explicit unsuccessful outcome",
                    retryable=False,
                ),
                ActionOutcome.FAILED,
            )
        except RemediationAmbiguousError:
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.RECOVERY_REQUIREMENT,
                    code="STOP_ACKNOWLEDGEMENT_AMBIGUOUS",
                    message="Mutation acknowledgement is unknown and requires reconciliation",
                    retryable=False,
                ),
                ActionOutcome.AMBIGUOUS,
            )
        except Exception:
            return self._persist_execution_failure(
                run,
                idempotency.idempotency_key,
                FailureDetail(
                    kind=FailureKind.RECOVERY_REQUIREMENT,
                    code="STOP_EXECUTOR_UNEXPECTED_FAILURE",
                    message="Private executor failed without a safe acknowledgement",
                    retryable=False,
                ),
                ActionOutcome.AMBIGUOUS,
            )

        try:
            self._repository.record_execution_acknowledgement(
                idempotency.idempotency_key,
                acknowledgement,
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
                acknowledgement.acknowledgement_hash,
                metadata={"proposal_id": str(proposal.proposal_id)},
            )
        except (StorageConflictError, StorageDependencyError):
            return self._mark_recovery_required(
                run.run_id,
                "EXECUTION_ACK_DURABILITY_FAILED",
                "Executor acknowledgement could not be durably reconciled",
            )
        return ControlResult.succeeded(acknowledgement)

    def for_tool(self, proposal_id: UUID) -> dict[str, object]:
        """Return the strict JSON result consumed by the Strands tool wrapper."""

        return self.execute(proposal_id).model_dump(mode="json")

    def _persist_execution_failure(
        self,
        run: Run,
        idempotency_key: str,
        failure: FailureDetail,
        outcome: ActionOutcome,
    ) -> ControlResult:
        target_state = workflow_state_for_failure(failure)
        try:
            if failure.kind is FailureKind.POLICY_DENIAL:
                self._append_event(
                    run,
                    AuditEventType.POLICY_DENIED,
                    compute_evidence_digest({"code": failure.code, "kind": failure.kind.value}),
                    metadata={"policy_code": failure.code},
                )
            self._repository.complete_idempotency(
                idempotency_key,
                ActionResult(outcome=outcome, failure=failure),
                completed_at=self._clock(),
            )
            self._repository.transition_run(
                run.run_id,
                target_state,
                expected_state=WorkflowState.EXECUTING,
                expected_version=run.version,
                updated_at=self._clock(),
            )
        except (StorageConflictError, StorageDependencyError):
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "EXECUTION_FAILURE_DURABILITY_FAILED",
                "Execution failure could not be durably reconciled",
            )
        return ControlResult.failed(failure)

    def _mark_recovery_required(
        self,
        run_id: UUID,
        code: str,
        message: str,
    ) -> ControlResult:
        failure = FailureDetail(
            kind=FailureKind.RECOVERY_REQUIREMENT,
            code=code,
            message=message,
            retryable=False,
        )
        try:
            run = self._repository.get_run(run_id)
            if run is not None and run.state in {
                WorkflowState.APPROVED,
                WorkflowState.EXECUTING,
            }:
                self._repository.transition_run(
                    run.run_id,
                    WorkflowState.RECOVERY_REQUIRED,
                    expected_state=run.state,
                    expected_version=run.version,
                    updated_at=self._clock(),
                )
        except (StorageConflictError, StorageDependencyError):
            pass
        return ControlResult.failed(failure)

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
                source="nz-remediation-orchestrator",
                tool_name="stop_sandbox_instance",
                redacted_payload_hash=payload_hash,
                metadata={
                    **metadata,
                    "trace_id": str(run.trace_id),
                    "correlation_id": str(run.correlation_id),
                },
            )
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
