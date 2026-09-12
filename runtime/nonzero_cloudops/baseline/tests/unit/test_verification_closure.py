from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    InspectInstanceService,
    InvestigationIdentity,
    SandboxTarget,
)
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass
from aioa_cloudops_agent.nz import (
    ActionOutcome,
    ActionProposal,
    ActionResult,
    ActionTarget,
    Approval,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    BudgetCounters,
    Capability,
    Checkpoint,
    ExecutionAcknowledgement,
    ExpectedPrecondition,
    FailureKind,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    ResultStatus,
    Run,
    VerificationDisposition,
    VerificationEvidence,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence import derive_idempotency_key
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.remediation import (
    StopExecutionCommand,
    StopSandboxInstanceCoordinator,
)
from aioa_cloudops_agent.verification import (
    BoundedVerificationCoordinator,
    VerificationObservation,
    VerifyInstanceStateService,
    create_verify_instance_state_tool,
)

INSTANCE_ID = "i-0123456789abcdef0"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVIDENCE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9bdc")
NOW = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)
DIGEST = "a" * 64
REQUEST_HASH = "b" * 64


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )


class UuidFactory:
    def __init__(self, start: int) -> None:
        self.value = start

    def __call__(self) -> UUID:
        result = UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{self.value:02x}")
        self.value += 1
        return result


class SequencedEc2Client:
    def __init__(
        self,
        states: tuple[str | None, ...],
        *,
        repository: InMemoryTestDurableTruthRepository | None = None,
    ) -> None:
        self.states = list(states)
        self.repository = repository
        self.calls: list[list[str]] = []
        self.run_states_at_read: list[WorkflowState] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        self.calls.append(InstanceIds)
        if self.repository is not None:
            run = self.repository.get_run(RUN_ID)
            assert run is not None
            self.run_states_at_read.append(run.state)
        state = self.states.pop(0)
        if state is None:
            return {"Reservations": []}
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE_ID,
                            "State": {"Name": state},
                            "InstanceType": "t3.micro",
                            "LaunchTime": NOW - timedelta(hours=2),
                            "Monitoring": {"State": "disabled"},
                            "Placement": {"AvailabilityZone": "eu-central-1a"},
                            "Tags": [
                                {
                                    "Key": "AIOACloudOpsSandbox",
                                    "Value": "true",
                                }
                            ],
                        }
                    ]
                }
            ]
        }


class RecordingExecutor:
    def __init__(self) -> None:
        self.commands: list[StopExecutionCommand] = []

    def execute(self, command: StopExecutionCommand) -> ExecutionAcknowledgement:
        self.commands.append(command)
        return ExecutionAcknowledgement(
            proposal_id=command.proposal_id,
            run_id=command.run_id,
            target=command.target,
            current_state=ObservedInstanceState.STOPPING,
            request_reference="request-safe-001",
            acknowledged_at=NOW + timedelta(seconds=10),
            acknowledgement_hash="c" * 64,
        )


class RecordingRepository(InMemoryTestDurableTruthRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[AuditEvent] = []

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return super().append_audit_event(event)


class VerificationEvidenceFailingRepository(RecordingRepository):
    def create_verification_evidence(
        self,
        evidence: VerificationEvidence,
    ) -> VerificationEvidence:
        raise StorageDependencyError("synthetic final-evidence outage")


def _proposal() -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=Capability.STOP_SANDBOX_INSTANCE,
        target=ActionTarget(
            resource_id=INSTANCE_ID,
            sandbox_scope="hackathon-sandbox",
        ),
        expected_precondition=ExpectedPrecondition(
            instance_state=ObservedInstanceState.RUNNING,
            observed_at=NOW,
            evidence_hash=DIGEST,
        ),
        authority=AuthorityGate.PLAN_AND_CONFIRM,
        state=ProposalState.PROPOSED,
        evidence_hash=DIGEST,
        created_at=NOW,
    )


def _approval(proposal: ActionProposal) -> Approval:
    return Approval(
        proposal_id=proposal.proposal_id,
        run_id=proposal.run_id,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-1",
        request_hash=REQUEST_HASH,
        decision=ApprovalDecision.APPROVED,
        decided_at=NOW + timedelta(seconds=5),
        actor_session_id="human-session-001",
        decision_nonce="decision-nonce-0001",
    )


def _prepare_verifying_repository(
    repository: RecordingRepository | None = None,
) -> tuple[RecordingRepository, ActionProposal, RecordingExecutor]:
    actual = repository or RecordingRepository()
    run = actual.create_run(
        Run.new(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:0001",
            created_at=NOW,
            budget=BudgetCounters(max_turns=8, max_tokens=8_192),
        )
    )
    for offset, state in enumerate(
        (
            WorkflowState.INVESTIGATING,
            WorkflowState.EVIDENCE_READY,
            WorkflowState.REMEDIATION_PROPOSED,
            WorkflowState.AWAITING_APPROVAL,
        ),
        start=1,
    ):
        run = actual.transition_run(
            RUN_ID,
            state,
            expected_state=run.state,
            expected_version=run.version,
            updated_at=NOW + timedelta(seconds=offset),
        )
    proposal = actual.create_proposal(_proposal())
    proposal = actual.transition_proposal(
        PROPOSAL_ID,
        ProposalState.AWAITING_APPROVAL,
        expected_state=ProposalState.PROPOSED,
    )
    actual.create_approval(_approval(proposal))
    run = actual.transition_run(
        RUN_ID,
        WorkflowState.APPROVED,
        expected_state=WorkflowState.AWAITING_APPROVAL,
        expected_version=run.version,
        updated_at=NOW + timedelta(seconds=6),
        approval_proposal_id=PROPOSAL_ID,
    )
    actual.save_checkpoint(
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.APPROVED,
            resume_metadata={"proposal_id": str(PROPOSAL_ID)},
            tool_result_hashes={"build_remediation_evidence": DIGEST},
            created_at=NOW + timedelta(seconds=6),
            version=1,
        ),
        expected_version=None,
    )
    executor = RecordingExecutor()
    execution = StopSandboxInstanceCoordinator(
        actual,
        executor,
        clock=lambda: NOW + timedelta(seconds=10),
        event_id_factory=UuidFactory(160),
    ).execute(PROPOSAL_ID)
    assert execution.status is ResultStatus.SUCCESS
    assert actual.get_run(RUN_ID).state is WorkflowState.VERIFYING
    return actual, proposal, executor


def _coordinator(
    repository: RecordingRepository,
    client: SequencedEc2Client,
    *,
    max_attempts: int = 3,
    sleeps: list[int] | None = None,
) -> BoundedVerificationCoordinator:
    target = SandboxTarget(instance_id=INSTANCE_ID)
    service = VerifyInstanceStateService(
        InspectInstanceService(client, target),
        target,
    )
    recorded_sleeps = sleeps if sleeps is not None else []
    return BoundedVerificationCoordinator(
        repository,
        service,
        settings=VerificationSettings(
            max_attempts=max_attempts,
            interval_seconds=0,
        ),
        clock=lambda: NOW + timedelta(seconds=20),
        sleeper=recorded_sleeps.append,
        event_id_factory=UuidFactory(180),
        evidence_id_factory=lambda: EVIDENCE_ID,
    )


def test_verify_tool_is_auto_read_only_and_accepts_only_proposal_reference() -> None:
    calls: list[UUID] = []

    def handler(proposal_id: UUID) -> dict[str, object]:
        calls.append(proposal_id)
        return {"status": "SUCCESS", "value": "verified", "failure": None}

    verify_tool = create_verify_instance_state_tool(handler, _identity())
    schema = verify_tool.tool_spec["inputSchema"]["json"]

    assert verify_tool.tool_name == "verify_instance_state"
    assert schema["required"] == ["proposal_id"]
    assert set(schema["properties"]) == {"proposal_id"}
    verify_tool(proposal_id=str(PROPOSAL_ID))
    assert calls == [PROPOSAL_ID]
    assert not any(
        token in str(schema)
        for token in ("StopInstances", "Force", "InstanceIds", "TerminateInstances")
    )


def test_stopped_target_persists_proof_then_reaches_success_with_evidence() -> None:
    repository, proposal, executor = _prepare_verifying_repository()
    client = SequencedEc2Client(("stopped",), repository=repository)

    result = _coordinator(repository, client).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert result.value.evidence.proposal_id == proposal.proposal_id
    assert result.value.evidence.observed_state is ObservedInstanceState.STOPPED
    assert repository.get_verification_evidence(RUN_ID, PROPOSAL_ID) == result.value.evidence
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    idempotency = repository.get_idempotency(derive_idempotency_key(proposal))
    assert idempotency is not None and idempotency.status is IdempotencyStatus.COMPLETED
    assert idempotency.action_result is not None
    assert idempotency.action_result.evidence_hash == result.value.evidence.evidence_hash
    assert client.calls == [[INSTANCE_ID]]
    assert client.run_states_at_read == [WorkflowState.VERIFYING]
    assert len(executor.commands) == 1
    assert [event.type for event in repository.events[-3:]] == [
        AuditEventType.VERIFICATION_STARTED,
        AuditEventType.VERIFICATION_OBSERVED,
        AuditEventType.VERIFICATION_RECORDED,
    ]


def test_stopping_state_is_polled_within_budget_and_never_prematurely_succeeds() -> None:
    repository, _, _ = _prepare_verifying_repository()
    client = SequencedEc2Client(("stopping", "stopped"), repository=repository)
    sleeps: list[int] = []

    result = _coordinator(repository, client, sleeps=sleeps).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None and result.value.attempts == 2
    assert client.run_states_at_read == [WorkflowState.VERIFYING, WorkflowState.VERIFYING]
    assert sleeps == [0]
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE


def test_running_state_after_stop_is_mismatch_and_never_success() -> None:
    repository, _, _ = _prepare_verifying_repository()
    client = SequencedEc2Client(("running",), repository=repository)

    result = _coordinator(repository, client).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.VERIFICATION_FAILURE
    assert repository.get_run(RUN_ID).state is WorkflowState.VERIFICATION_FAILED
    assert repository.get_verification_evidence(RUN_ID, PROPOSAL_ID) is None


def test_empty_provider_response_is_explicit_failure_not_stopped() -> None:
    repository, _, _ = _prepare_verifying_repository()
    client = SequencedEc2Client((None,), repository=repository)

    result = _coordinator(repository, client).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
    assert repository.get_run(RUN_ID).state is WorkflowState.AMBIGUOUS_RESULT
    assert repository.get_verification_evidence(RUN_ID, PROPOSAL_ID) is None


def test_transitional_state_timeout_is_explicit_verification_failure() -> None:
    repository, _, _ = _prepare_verifying_repository()
    client = SequencedEc2Client(("stopping", "stopping", "stopping"))
    sleeps: list[int] = []

    result = _coordinator(repository, client, sleeps=sleeps).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None and result.failure.code == "VERIFICATION_TIMEOUT"
    assert repository.get_run(RUN_ID).state is WorkflowState.VERIFICATION_FAILED
    assert len(client.calls) == 3
    assert sleeps == [0, 0]


def test_verification_evidence_hash_is_stable_and_decision_sensitive() -> None:
    repository, proposal, _ = _prepare_verifying_repository()
    run = repository.get_run(RUN_ID)
    record = repository.get_idempotency(derive_idempotency_key(proposal))
    assert run is not None and record is not None
    acknowledgement = record.execution_acknowledgement
    assert acknowledgement is not None

    first = VerificationEvidence.create(
        evidence_id=EVIDENCE_ID,
        proposal=proposal,
        run=run,
        verified_at=NOW + timedelta(seconds=20),
        acknowledgement=acknowledgement,
        observation_hash="d" * 64,
    )
    same = VerificationEvidence.create(
        evidence_id=EVIDENCE_ID,
        proposal=proposal,
        run=run,
        verified_at=NOW + timedelta(seconds=20),
        acknowledgement=acknowledgement,
        observation_hash="d" * 64,
    )
    changed = VerificationEvidence.create(
        evidence_id=EVIDENCE_ID,
        proposal=proposal,
        run=run,
        verified_at=NOW + timedelta(seconds=20),
        acknowledgement=acknowledgement,
        observation_hash="e" * 64,
    )

    assert first.evidence_hash == same.evidence_hash
    assert first.evidence_hash != changed.evidence_hash
    with pytest.raises(ValidationError, match="canonical evidence"):
        VerificationEvidence.model_validate(
            {**first.model_dump(), "evidence_hash": "f" * 64}
        )


def test_success_transition_without_durable_verification_evidence_is_rejected() -> None:
    repository, proposal, _ = _prepare_verifying_repository()
    run = repository.get_run(RUN_ID)
    assert run is not None
    repository.complete_idempotency(
        derive_idempotency_key(proposal),
        ActionResult(
            outcome=ActionOutcome.SUCCEEDED,
            observed_state=ObservedInstanceState.STOPPED,
            evidence_hash="d" * 64,
        ),
        completed_at=NOW + timedelta(seconds=20),
    )

    with pytest.raises(StorageConflictError, match="proof is incomplete"):
        repository.transition_run(
            RUN_ID,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            expected_state=WorkflowState.VERIFYING,
            expected_version=run.version,
            updated_at=NOW + timedelta(seconds=21),
            verification_proposal_id=PROPOSAL_ID,
        )


def test_final_evidence_storage_failure_never_claims_success() -> None:
    repository, _, _ = _prepare_verifying_repository(
        VerificationEvidenceFailingRepository()
    )
    client = SequencedEc2Client(("stopped",), repository=repository)

    result = _coordinator(repository, client).verify(PROPOSAL_ID)

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.RECOVERY_REQUIREMENT
    assert repository.get_run(RUN_ID).state is WorkflowState.RECOVERY_REQUIRED
    assert repository.get_verification_evidence(RUN_ID, PROPOSAL_ID) is None


def test_duplicate_verified_request_reconciles_without_second_read_or_stop() -> None:
    repository, _, executor = _prepare_verifying_repository()
    client = SequencedEc2Client(("stopped",), repository=repository)
    coordinator = _coordinator(repository, client)

    first = coordinator.verify(PROPOSAL_ID)
    duplicate = coordinator.verify(PROPOSAL_ID)

    assert first.status is ResultStatus.SUCCESS
    assert duplicate.status is ResultStatus.SUCCESS
    assert duplicate.value is not None and duplicate.value.reconciled is True
    assert duplicate.value.evidence == first.value.evidence
    assert client.calls == [[INSTANCE_ID]]
    assert len(executor.commands) == 1


def test_verification_observation_contract_is_explicitly_auto_and_read_only() -> None:
    _, proposal, _ = _prepare_verifying_repository()
    identity = InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )
    service = VerifyInstanceStateService(
        InspectInstanceService(
            SequencedEc2Client(("stopped",)),
            SandboxTarget(instance_id=INSTANCE_ID),
        ),
        SandboxTarget(instance_id=INSTANCE_ID),
    )

    result = service.observe(proposal, identity, observed_at=NOW, attempt=1)

    assert result.value is not None
    assert result.value.disposition is VerificationDisposition.VERIFIED
    assert result.value.observed_state is Ec2InstanceState.STOPPED
    assert result.value.authority_gate is AuthorityGate.AUTO
    assert result.value.operation_class is AwsOperationClass.READ_ONLY
    assert not hasattr(service, "stop_instances")
    with pytest.raises(ValidationError):
        VerificationObservation.model_validate(
            {
                **result.value.model_dump(),
                "disposition": VerificationDisposition.MISMATCH,
            }
        )
