"""Bounded verification and durable SUCCESS_WITH_EVIDENCE closure."""

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from aioa_cloudops_agent.cloudops import InvestigationIdentity
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.nz import (
    ActionOutcome,
    ActionProposal,
    ActionResult,
    AuditEvent,
    AuditEventType,
    ControlResult,
    ExecutionAcknowledgement,
    FailureDetail,
    FailureKind,
    IdempotencyStatus,
    ObservedInstanceState,
    ResultStatus,
    Run,
    VerificationDisposition,
    VerificationEvidence,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence import DurableTruthRepository, derive_idempotency_key
from aioa_cloudops_agent.safety.failures import workflow_state_for_failure

from .models import VerificationCompletion, VerificationObservation
from .service import VerifyInstanceStateService


class BoundedVerificationCoordinator:
    """Poll independent read-back within a fixed budget and persist proof before success."""

    def __init__(
        self,
        repository: DurableTruthRepository,
        service: VerifyInstanceStateService,
        *,
        settings: VerificationSettings,
        clock: Callable[[], datetime],
        sleeper: Callable[[int], None],
        event_id_factory: Callable[[], UUID],
        evidence_id_factory: Callable[[], UUID],
    ) -> None:
        if not isinstance(service, VerifyInstanceStateService):
            raise TypeError("service must be VerifyInstanceStateService")
        if not isinstance(settings, VerificationSettings):
            raise TypeError("settings must be VerificationSettings")
        if not all(callable(value) for value in (clock, sleeper, event_id_factory, evidence_id_factory)):
            raise TypeError("verification dependencies must be callable")
        self._repository = repository
        self._service = service
        self._settings = settings
        self._clock = clock
        self._sleeper = sleeper
        self._event_id_factory = event_id_factory
        self._evidence_id_factory = evidence_id_factory

    def verify(self, proposal_id: UUID) -> ControlResult[VerificationCompletion]:
        """Independently verify one acknowledged stop or reconcile prior verified truth."""

        try:
            proposal = self._repository.get_proposal(proposal_id)
            if proposal is None:
                return self._failed(
                    FailureKind.VALIDATION_FAILURE,
                    "VERIFICATION_PROPOSAL_NOT_FOUND",
                    "Durable proposal is required for verification",
                )
            run = self._repository.get_run(proposal.run_id)
            if run is None:
                return self._failed(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "VERIFICATION_RUN_NOT_FOUND",
                    "Durable run is required for verification",
                )
            idempotency = self._repository.get_idempotency(derive_idempotency_key(proposal))
        except StorageDependencyError:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "VERIFICATION_DURABILITY_UNAVAILABLE",
                "Durable verification prerequisites are unavailable",
                retryable=True,
            )
        if run.state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            return self._reconcile_success(run, proposal_id)
        if idempotency is None or idempotency.execution_acknowledgement is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "EXECUTION_ACKNOWLEDGEMENT_MISSING",
                "Independent verification requires a durable execution acknowledgement",
            )
        if run.state is not WorkflowState.VERIFYING:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "VERIFICATION_STATE_INVALID",
                "Run must be durably VERIFYING before provider read-back",
            )
        if idempotency.status is IdempotencyStatus.COMPLETED:
            return self._finalize_existing_evidence(run, proposal_id)
        if idempotency.status is not IdempotencyStatus.REGISTERED:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "VERIFICATION_IDEMPOTENCY_INVALID",
                "Idempotency state cannot safely enter verification",
            )
        acknowledgement = idempotency.execution_acknowledgement
        identity = InvestigationIdentity.from_run(run)
        try:
            self._append_event(
                run,
                AuditEventType.VERIFICATION_STARTED,
                acknowledgement.acknowledgement_hash,
                metadata={"proposal_id": str(proposal_id)},
            )
        except (StorageConflictError, StorageDependencyError):
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "VERIFICATION_AUDIT_UNAVAILABLE",
                "Verification start could not be persisted",
                retryable=True,
            )

        last_observation: VerificationObservation | None = None
        for attempt in range(1, self._settings.max_attempts + 1):
            observation_result = self._service.observe(
                proposal,
                identity,
                observed_at=self._clock(),
                attempt=attempt,
            )
            if observation_result.status is ResultStatus.FAILURE:
                assert observation_result.failure is not None
                return self._fail_verification(
                    run,
                    idempotency.idempotency_key,
                    observation_result.failure,
                )
            assert observation_result.value is not None
            last_observation = observation_result.value
            try:
                self._append_event(
                    run,
                    AuditEventType.VERIFICATION_OBSERVED,
                    last_observation.observation_hash,
                    metadata={
                        "attempt": str(attempt),
                        "disposition": last_observation.disposition.value,
                        "observed_state": last_observation.observed_state.value,
                        "proposal_id": str(proposal_id),
                    },
                )
            except (StorageConflictError, StorageDependencyError):
                self._mark_recovery_required(run)
                return self._failed(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "VERIFICATION_OBSERVATION_DURABILITY_FAILED",
                    "Independent provider observation could not be durably audited",
                )
            if last_observation.disposition is VerificationDisposition.VERIFIED:
                return self._persist_success(
                    run,
                    proposal,
                    acknowledgement,
                    last_observation,
                )
            if last_observation.disposition is VerificationDisposition.MISMATCH:
                return self._fail_verification(
                    run,
                    idempotency.idempotency_key,
                    FailureDetail(
                        kind=FailureKind.VERIFICATION_FAILURE,
                        code="VERIFICATION_STATE_MISMATCH",
                        message="Independent EC2 state does not match the expected stopped state",
                        retryable=False,
                    ),
                )
            if attempt < self._settings.max_attempts:
                self._sleeper(self._settings.interval_seconds)

        assert last_observation is not None
        return self._fail_verification(
            run,
            idempotency.idempotency_key,
            FailureDetail(
                kind=FailureKind.VERIFICATION_FAILURE,
                code="VERIFICATION_TIMEOUT",
                message="EC2 remained transitional beyond the bounded verification budget",
                retryable=True,
            ),
        )

    def for_tool(self, proposal_id: UUID) -> dict[str, object]:
        """Return strict JSON for the Strands read-only tool wrapper."""

        return self.verify(proposal_id).model_dump(mode="json")

    def _persist_success(
        self,
        run: Run,
        proposal: ActionProposal,
        acknowledgement: ExecutionAcknowledgement,
        observation: VerificationObservation,
    ) -> ControlResult[VerificationCompletion]:
        verified_at = self._clock()
        evidence = VerificationEvidence.create(
            evidence_id=self._evidence_id_factory(),
            proposal=proposal,
            run=run,
            verified_at=verified_at,
            acknowledgement=acknowledgement,
            observation_hash=observation.observation_hash,
        )
        try:
            evidence = self._repository.create_verification_evidence(evidence)
            self._repository.complete_idempotency(
                derive_idempotency_key(proposal),
                ActionResult(
                    outcome=ActionOutcome.SUCCEEDED,
                    observed_state=ObservedInstanceState.STOPPED,
                    evidence_hash=evidence.evidence_hash,
                ),
                completed_at=self._clock(),
            )
            self._append_event(
                run,
                AuditEventType.VERIFICATION_RECORDED,
                evidence.evidence_hash,
                metadata={
                    "proposal_id": str(proposal.proposal_id),
                    "transition_candidate": WorkflowState.SUCCESS_WITH_EVIDENCE.value,
                },
            )
            run = self._repository.transition_run(
                run.run_id,
                WorkflowState.SUCCESS_WITH_EVIDENCE,
                expected_state=WorkflowState.VERIFYING,
                expected_version=run.version,
                updated_at=self._clock(),
                verification_proposal_id=proposal.proposal_id,
            )
        except (StorageConflictError, StorageDependencyError):
            self._mark_recovery_required(run)
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "VERIFICATION_EVIDENCE_DURABILITY_FAILED",
                "Verified provider state could not be durably closed as success",
            )
        return ControlResult[VerificationCompletion].succeeded(
            VerificationCompletion(evidence=evidence, attempts=observation.attempt)
        )

    def _finalize_existing_evidence(
        self,
        run: Run,
        proposal_id: UUID,
    ) -> ControlResult[VerificationCompletion]:
        try:
            evidence = self._repository.get_verification_evidence(run.run_id, proposal_id)
            if evidence is None:
                return self._failed(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "COMPLETED_RESULT_MISSING_EVIDENCE",
                    "Completed idempotency record lacks durable verification evidence",
                )
            self._append_event(
                run,
                AuditEventType.VERIFICATION_RECORDED,
                evidence.evidence_hash,
                metadata={
                    "proposal_id": str(proposal_id),
                    "reconciled": "true",
                    "transition_candidate": WorkflowState.SUCCESS_WITH_EVIDENCE.value,
                },
            )
            run = self._repository.transition_run(
                run.run_id,
                WorkflowState.SUCCESS_WITH_EVIDENCE,
                expected_state=WorkflowState.VERIFYING,
                expected_version=run.version,
                updated_at=self._clock(),
                verification_proposal_id=proposal_id,
            )
        except (StorageConflictError, StorageDependencyError):
            self._mark_recovery_required(run)
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "SUCCESS_TRANSITION_RECONCILIATION_FAILED",
                "Durable success transition requires recovery",
            )
        return ControlResult[VerificationCompletion].succeeded(
            VerificationCompletion(evidence=evidence, attempts=0, reconciled=True)
        )

    def _reconcile_success(
        self,
        run: Run,
        proposal_id: UUID,
    ) -> ControlResult[VerificationCompletion]:
        try:
            evidence = self._repository.get_verification_evidence(run.run_id, proposal_id)
        except StorageDependencyError:
            return self._failed(
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "VERIFIED_EVIDENCE_LOOKUP_UNAVAILABLE",
                "Durable verified evidence lookup is unavailable",
                retryable=True,
            )
        if evidence is None:
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "SUCCESS_EVIDENCE_MISSING",
                "SUCCESS_WITH_EVIDENCE lacks its durable proof",
            )
        return ControlResult[VerificationCompletion].succeeded(
            VerificationCompletion(evidence=evidence, attempts=0, reconciled=True)
        )

    def _fail_verification(
        self,
        run: Run,
        idempotency_key: str,
        failure: FailureDetail,
    ) -> ControlResult[VerificationCompletion]:
        target_state = workflow_state_for_failure(failure)
        try:
            self._repository.complete_idempotency(
                idempotency_key,
                ActionResult(outcome=ActionOutcome.FAILED, failure=failure),
                completed_at=self._clock(),
            )
            self._repository.transition_run(
                run.run_id,
                target_state,
                expected_state=WorkflowState.VERIFYING,
                expected_version=run.version,
                updated_at=self._clock(),
            )
        except (StorageConflictError, StorageDependencyError):
            self._mark_recovery_required(run)
            return self._failed(
                FailureKind.RECOVERY_REQUIREMENT,
                "VERIFICATION_FAILURE_DURABILITY_FAILED",
                "Verification failure could not be durably reconciled",
            )
        return ControlResult[VerificationCompletion].failed(failure)

    def _mark_recovery_required(self, run: Run) -> None:
        try:
            current = self._repository.get_run(run.run_id)
            if current is not None and current.state is WorkflowState.VERIFYING:
                self._repository.transition_run(
                    current.run_id,
                    WorkflowState.RECOVERY_REQUIRED,
                    expected_state=WorkflowState.VERIFYING,
                    expected_version=current.version,
                    updated_at=self._clock(),
                )
        except (StorageConflictError, StorageDependencyError):
            return

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
                source="nz-verification",
                tool_name="verify_instance_state",
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
    ) -> ControlResult[VerificationCompletion]:
        return ControlResult[VerificationCompletion].failed(
            FailureDetail(
                kind=kind,
                code=code,
                message=message,
                retryable=retryable,
            )
        )
