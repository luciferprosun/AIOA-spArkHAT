from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from aioa_cloudops_agent.agent.hitl import (
    ApprovalInterrupt,
    approval_request_hash,
    build_approval_payload,
)
from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    InspectInstanceService,
    SandboxTarget,
)
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.domain import AuthorityGate
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
    ControlResult,
    ExecutionAcknowledgement,
    ExpectedPrecondition,
    FailureKind,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    ResultStatus,
    Run,
    VerificationEvidence,
    VerificationProofOrigin,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError
from aioa_cloudops_agent.persistence import (
    derive_idempotency_key,
    register_approved_action,
)
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.recovery import (
    RecoveryAction,
    RecoveryCoordinator,
    RecoveryRequest,
    RecoveryStatus,
)
from aioa_cloudops_agent.verification import (
    BoundedVerificationCoordinator,
    VerifyInstanceStateService,
)

INSTANCE_ID = "i-0123456789abcdef0"
OTHER_INSTANCE_ID = "i-0fedcba9876543210"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVIDENCE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9bdc")
NOW = datetime(2026, 8, 24, 8, 0, tzinfo=UTC)
DIGEST = "a" * 64
REQUEST_HASH = "b" * 64
ACK_HASH = "c" * 64


class UuidFactory:
    def __init__(self, start: int) -> None:
        self.value = start

    def __call__(self) -> UUID:
        result = UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{self.value:02x}")
        self.value += 1
        return result


class TickingClock:
    def __init__(self) -> None:
        self.value = NOW + timedelta(minutes=10)

    def __call__(self) -> datetime:
        current = self.value
        self.value += timedelta(seconds=1)
        return current


class RecordingRepository(InMemoryTestDurableTruthRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[AuditEvent] = []

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return super().append_audit_event(event)


class UnavailableRepository(RecordingRepository):
    def get_run(self, run_id: UUID) -> Run | None:
        del run_id
        raise StorageDependencyError("synthetic durable outage")


class SequencedEc2Client:
    def __init__(self, states: tuple[str | None, ...]) -> None:
        self.states = list(states)
        self.calls: list[list[str]] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        self.calls.append(InstanceIds)
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
                                {"Key": "AIOACloudOpsSandbox", "Value": "true"}
                            ],
                        }
                    ]
                }
            ]
        }


def _new_run(repository: RecordingRepository) -> Run:
    return repository.create_run(
        Run.new(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:0001",
            created_at=NOW,
            budget=BudgetCounters(max_turns=8, max_tokens=8_192),
        )
    )


def _transition(
    repository: RecordingRepository,
    run: Run,
    state: WorkflowState,
    offset: int,
    *,
    approval_proposal_id: UUID | None = None,
    verification_proposal_id: UUID | None = None,
) -> Run:
    return repository.transition_run(
        run.run_id,
        state,
        expected_state=run.state,
        expected_version=run.version,
        updated_at=NOW + timedelta(seconds=offset),
        approval_proposal_id=approval_proposal_id,
        verification_proposal_id=verification_proposal_id,
    )


def _proposal(*, state: ProposalState = ProposalState.PROPOSED) -> ActionProposal:
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
        state=state,
        evidence_hash=DIGEST,
        created_at=NOW,
    )


def _approval(
    proposal: ActionProposal,
    decision: ApprovalDecision = ApprovalDecision.APPROVED,
) -> Approval:
    return Approval(
        proposal_id=proposal.proposal_id,
        run_id=proposal.run_id,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-recovery",
        request_hash=REQUEST_HASH,
        decision=decision,
        decided_at=NOW + timedelta(seconds=6),
        actor_session_id="human-session-001",
        decision_nonce="decision-nonce-recovery-0001",
    )


def _prepare_awaiting(
    repository: RecordingRepository | None = None,
) -> tuple[RecordingRepository, Run, ActionProposal]:
    actual = repository or RecordingRepository()
    run = _new_run(actual)
    for offset, state in enumerate(
        (
            WorkflowState.INVESTIGATING,
            WorkflowState.EVIDENCE_READY,
            WorkflowState.REMEDIATION_PROPOSED,
            WorkflowState.AWAITING_APPROVAL,
        ),
        start=1,
    ):
        run = _transition(actual, run, state, offset)
    proposal = actual.create_proposal(_proposal())
    proposal = actual.transition_proposal(
        PROPOSAL_ID,
        ProposalState.AWAITING_APPROVAL,
        expected_state=ProposalState.PROPOSED,
    )
    payload = build_approval_payload(proposal)
    actual.save_checkpoint(
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.AWAITING_APPROVAL,
            resume_metadata={
                "proposal_id": str(PROPOSAL_ID),
                "approval_interrupt_id": "v1:before_tool_call:stop-recovery",
                "approval_request_hash": approval_request_hash(payload),
            },
            tool_result_hashes={"build_remediation_evidence": DIGEST},
            created_at=NOW + timedelta(seconds=5),
            version=1,
        ),
        expected_version=None,
    )
    return actual, run, proposal


def _prepare_approved(
    repository: RecordingRepository | None = None,
) -> tuple[RecordingRepository, Run, ActionProposal]:
    actual, run, proposal = _prepare_awaiting(repository)
    actual.create_approval(_approval(proposal))
    run = _transition(
        actual,
        run,
        WorkflowState.APPROVED,
        7,
        approval_proposal_id=PROPOSAL_ID,
    )
    checkpoint = actual.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    actual.save_checkpoint(
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.APPROVED,
            resume_metadata={
                **checkpoint.resume_metadata,
                "approval_decision": ApprovalDecision.APPROVED.value,
            },
            tool_result_hashes=checkpoint.tool_result_hashes,
            created_at=NOW + timedelta(seconds=7),
            version=2,
        ),
        expected_version=1,
    )
    return actual, run, proposal


def _prepare_executing(
    *,
    state: WorkflowState = WorkflowState.EXECUTING,
    acknowledgement: bool = False,
) -> tuple[RecordingRepository, Run, ActionProposal]:
    repository, run, proposal = _prepare_approved()
    register_approved_action(
        repository,
        PROPOSAL_ID,
        registered_at=NOW + timedelta(seconds=8),
    )
    run = _transition(repository, run, WorkflowState.EXECUTING, 9)
    if acknowledgement:
        repository.record_execution_acknowledgement(
            derive_idempotency_key(proposal),
            ExecutionAcknowledgement(
                proposal_id=PROPOSAL_ID,
                run_id=RUN_ID,
                target=proposal.target,
                current_state=ObservedInstanceState.STOPPING,
                request_reference="request-recovery-001",
                acknowledged_at=NOW + timedelta(seconds=10),
                acknowledgement_hash=ACK_HASH,
            ),
        )
    if state is WorkflowState.VERIFYING:
        run = _transition(repository, run, WorkflowState.VERIFYING, 11)
    elif state is WorkflowState.RECOVERY_REQUIRED:
        run = _transition(repository, run, WorkflowState.RECOVERY_REQUIRED, 11)
    return repository, run, proposal


def _prepare_verified(
    *,
    final_state: WorkflowState = WorkflowState.SUCCESS_WITH_EVIDENCE,
) -> tuple[RecordingRepository, Run, ActionProposal, VerificationEvidence]:
    repository, run, proposal = _prepare_executing(
        state=WorkflowState.VERIFYING,
        acknowledgement=True,
    )
    idempotency = repository.get_idempotency(derive_idempotency_key(proposal))
    assert idempotency is not None and idempotency.execution_acknowledgement is not None
    evidence = VerificationEvidence.create(
        evidence_id=EVIDENCE_ID,
        proposal=proposal,
        run=run,
        verified_at=NOW + timedelta(seconds=12),
        acknowledgement=idempotency.execution_acknowledgement,
        observation_hash="d" * 64,
    )
    repository.create_verification_evidence(evidence)
    repository.complete_idempotency(
        idempotency.idempotency_key,
        ActionResult(
            outcome=ActionOutcome.SUCCEEDED,
            observed_state=ObservedInstanceState.STOPPED,
            evidence_hash=evidence.evidence_hash,
        ),
        completed_at=NOW + timedelta(seconds=13),
    )
    if final_state is WorkflowState.SUCCESS_WITH_EVIDENCE:
        run = _transition(
            repository,
            run,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            14,
            verification_proposal_id=PROPOSAL_ID,
        )
    elif final_state is WorkflowState.RECOVERY_REQUIRED:
        run = _transition(repository, run, WorkflowState.RECOVERY_REQUIRED, 14)
    return repository, run, proposal, evidence


def _readback_service(client: SequencedEc2Client) -> VerifyInstanceStateService:
    target = SandboxTarget(instance_id=INSTANCE_ID)
    return VerifyInstanceStateService(InspectInstanceService(client, target), target)


def _approval_reconstructor(proposal: ActionProposal):
    payload = build_approval_payload(proposal)

    def reconstruct(proposal_id: UUID) -> ControlResult[ApprovalInterrupt]:
        assert proposal_id == proposal.proposal_id
        return ControlResult[ApprovalInterrupt].succeeded(
            ApprovalInterrupt(
                interrupt_id="v1:before_tool_call:stop-recovery",
                payload=payload,
                request_hash=approval_request_hash(payload),
                trace_id=TRACE_ID,
                correlation_id=CORRELATION_ID,
                reconciled=True,
            )
        )

    return reconstruct


def _coordinator(
    repository: RecordingRepository,
    *,
    readback: VerifyInstanceStateService | None = None,
    verification_reconciler=None,
    approval_reconstructor=None,
    settings: VerificationSettings | None = None,
    clock: TickingClock | None = None,
    sleeps: list[int] | None = None,
) -> RecoveryCoordinator:
    actual_sleeps = sleeps if sleeps is not None else []
    return RecoveryCoordinator(
        repository,
        clock=clock or TickingClock(),
        sleeper=actual_sleeps.append,
        event_id_factory=UuidFactory(128),
        recovery_id_factory=UuidFactory(176),
        evidence_id_factory=lambda: EVIDENCE_ID,
        approval_reconstructor=approval_reconstructor,
        verification_reconciler=verification_reconciler,
        readback_service=readback,
        verification_settings=settings or VerificationSettings(max_attempts=3, interval_seconds=0),
    )


def _request() -> RecoveryRequest:
    return RecoveryRequest(run_id=RUN_ID, proposal_id=PROPOSAL_ID)


def test_restart_at_awaiting_approval_reconstructs_exact_interrupt_without_execution() -> None:
    repository, _, proposal = _prepare_awaiting()

    result = _coordinator(
        repository,
        approval_reconstructor=_approval_reconstructor(proposal),
    ).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.action is RecoveryAction.RECONSTRUCT_APPROVAL
    assert result.value.final_state is WorkflowState.AWAITING_APPROVAL
    assert result.value.approval_interrupt is not None
    assert result.value.approval_interrupt.payload.proposal_id == PROPOSAL_ID
    assert result.value.executor_calls == 0
    assert repository.get_approval(PROPOSAL_ID) is None


def test_restart_at_approved_without_execution_claim_is_ready_but_does_not_execute() -> None:
    repository, _, _ = _prepare_approved()

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.status is RecoveryStatus.READY
    assert result.value.ready_for_execution is True
    assert repository.get_idempotency(f"action/{DIGEST}") is None
    assert repository.get_run(RUN_ID).state is WorkflowState.APPROVED


def test_lost_executor_ack_observed_stopped_closes_only_from_read_only_proof() -> None:
    repository, _, proposal = _prepare_executing()
    client = SequencedEc2Client(("stopped",))

    result = _coordinator(
        repository,
        readback=_readback_service(client),
    ).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert result.value.mutation_replayed is False
    assert result.value.executor_calls == 0
    assert client.calls == [[INSTANCE_ID]]
    evidence = repository.get_verification_evidence(RUN_ID, PROPOSAL_ID)
    assert evidence is not None
    assert evidence.proof_origin is VerificationProofOrigin.RECOVERY_READ_BACK
    assert evidence.execution_acknowledgement_hash is None
    idempotency = repository.get_idempotency(derive_idempotency_key(proposal))
    assert idempotency is not None and idempotency.status is IdempotencyStatus.COMPLETED


def test_lost_executor_ack_observed_stopping_uses_bounded_reads_without_replay() -> None:
    repository, _, _ = _prepare_executing()
    client = SequencedEc2Client(("stopping", "stopping"))
    sleeps: list[int] = []

    result = _coordinator(
        repository,
        readback=_readback_service(client),
        settings=VerificationSettings(max_attempts=2, interval_seconds=0),
        sleeps=sleeps,
    ).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.status is RecoveryStatus.OPERATOR_REQUIRED
    assert result.value.observed_state is Ec2InstanceState.STOPPING
    assert result.value.mutation_replayed is False
    assert client.calls == [[INSTANCE_ID], [INSTANCE_ID]]
    assert sleeps == [0]
    assert repository.get_run(RUN_ID).state is WorkflowState.RECOVERY_REQUIRED


def test_lost_executor_ack_observed_running_requires_operator_and_never_replays() -> None:
    repository, _, _ = _prepare_executing()
    client = SequencedEc2Client(("running",))

    result = _coordinator(
        repository,
        readback=_readback_service(client),
    ).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.reason_code == "LOST_ACK_TARGET_STILL_RUNNING"
    assert result.value.executor_calls == 0
    assert repository.get_run(RUN_ID).state is WorkflowState.RECOVERY_REQUIRED


def test_lost_executor_ack_empty_provider_response_is_explicit_failure() -> None:
    repository, _, _ = _prepare_executing()
    client = SequencedEc2Client((None,))

    result = _coordinator(
        repository,
        readback=_readback_service(client),
    ).recover(_request())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
    assert repository.get_run(RUN_ID).state is WorkflowState.RECOVERY_REQUIRED


def test_restart_at_verifying_resumes_bounded_read_only_verification() -> None:
    repository, _, proposal = _prepare_executing(
        state=WorkflowState.VERIFYING,
        acknowledgement=True,
    )
    client = SequencedEc2Client(("stopped",))
    service = _readback_service(client)
    verification = BoundedVerificationCoordinator(
        repository,
        service,
        settings=VerificationSettings(max_attempts=2, interval_seconds=0),
        clock=TickingClock(),
        sleeper=lambda _: None,
        event_id_factory=UuidFactory(200),
        evidence_id_factory=lambda: EVIDENCE_ID,
    )

    result = _coordinator(
        repository,
        verification_reconciler=verification.verify,
    ).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert client.calls == [[proposal.target.resource_id]]


def test_existing_completed_success_returns_idempotently_without_provider_read() -> None:
    repository, _, _, evidence = _prepare_verified()

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None and result.value.reconciled is True
    assert result.value.evidence_hash == evidence.evidence_hash
    assert result.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert result.value.executor_calls == 0


def test_recovery_required_with_completed_evidence_reconciles_to_success() -> None:
    repository, _, _, evidence = _prepare_verified(
        final_state=WorkflowState.RECOVERY_REQUIRED
    )

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.evidence_hash == evidence.evidence_hash
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE


def test_active_recovery_lease_prevents_two_concurrent_drivers() -> None:
    repository, _, _ = _prepare_executing()
    coordinator = _coordinator(repository)

    first = coordinator.recover(_request())
    second = coordinator.recover(_request())

    assert first.status is ResultStatus.SUCCESS
    assert first.value is not None and first.value.status is RecoveryStatus.OPERATOR_REQUIRED
    assert second.status is ResultStatus.FAILURE
    assert second.failure is not None
    assert second.failure.code == "RECOVERY_ALREADY_CLAIMED"


def test_corrupt_checkpoint_fails_closed_and_is_audited() -> None:
    repository, _, _ = _prepare_executing()
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    repository._checkpoints[RUN_ID] = checkpoint.model_copy(
        update={
            "resume_metadata": {
                **checkpoint.resume_metadata,
                "proposal_id": str(UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")),
            }
        }
    )

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.code == "RECOVERY_CHECKPOINT_PROPOSAL_MISMATCH"
    assert repository.events[-1].type is AuditEventType.RECOVERY_DEFERRED


def test_durable_store_outage_never_falls_back_to_in_memory_authority() -> None:
    result = _coordinator(UnavailableRepository()).recover(_request())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE


@pytest.mark.parametrize(
    "state",
    [WorkflowState.DENIED_BY_HUMAN, WorkflowState.DENIED_BY_POLICY],
)
def test_denied_terminal_state_remains_terminal_after_restart(state: WorkflowState) -> None:
    repository, run, proposal = _prepare_awaiting()
    if state is WorkflowState.DENIED_BY_HUMAN:
        repository.create_approval(_approval(proposal, ApprovalDecision.DENIED))
        run = _transition(
            repository,
            run,
            state,
            7,
            approval_proposal_id=PROPOSAL_ID,
        )
    else:
        run = _transition(repository, run, state, 7)

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.action is RecoveryAction.PRESERVE_TERMINAL
    assert result.value.final_state is state
    assert repository.get_run(RUN_ID).state is state


def test_checkpoint_json_roundtrip_preserves_recovery_identity_state_and_hashes() -> None:
    checkpoint = Checkpoint(
        run_id=RUN_ID,
        last_safe_state=WorkflowState.APPROVED,
        resume_metadata={
            "proposal_id": str(PROPOSAL_ID),
            "recovery_claim_id": str(
                UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b80")
            ),
            "recovery_claim_state": WorkflowState.EXECUTING.value,
        },
        tool_result_hashes={"build_remediation_evidence": DIGEST},
        created_at=NOW,
        version=3,
    )

    restored = Checkpoint.model_validate_json(checkpoint.model_dump_json())

    assert restored == checkpoint
    assert restored.resume_metadata["recovery_claim_state"] == "EXECUTING"
    assert restored.tool_result_hashes["build_remediation_evidence"] == DIGEST


def test_recovery_audit_event_links_run_trace_correlation_and_proposal() -> None:
    repository, _, _ = _prepare_approved()

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.SUCCESS
    event = repository.events[-1]
    assert event.run_id == RUN_ID
    assert event.metadata["trace_id"] == str(TRACE_ID)
    assert event.metadata["correlation_id"] == str(CORRELATION_ID)
    assert event.metadata["proposal_id"] == str(PROPOSAL_ID)


def test_recovery_package_contains_no_executor_or_ec2_write_call() -> None:
    recovery_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("src/aioa_cloudops_agent/recovery").glob("*.py")
    )

    assert "stop_instances(" not in recovery_source
    assert "terminate_instances(" not in recovery_source
    assert "start_instances(" not in recovery_source
    assert "PrivateRemediationExecutor" not in recovery_source


def test_cross_run_proposal_reference_is_rejected_before_reconciliation() -> None:
    repository, _, proposal = _prepare_executing()
    other_run_id = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
    repository._proposals[PROPOSAL_ID] = proposal.model_copy(
        update={"run_id": other_run_id}
    )

    result = _coordinator(repository).recover(_request())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.POLICY_DENIAL


def test_recovery_required_is_reconcilable_only_through_verification() -> None:
    from aioa_cloudops_agent.nz import validate_workflow_transition

    assert (
        validate_workflow_transition(
            WorkflowState.RECOVERY_REQUIRED,
            WorkflowState.VERIFYING,
        )
        is WorkflowState.VERIFYING
    )
