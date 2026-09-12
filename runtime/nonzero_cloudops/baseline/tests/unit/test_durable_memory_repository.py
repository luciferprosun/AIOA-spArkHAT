from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from aioa_cloudops_agent.nz import (
    ActionOutcome,
    ActionProposal,
    ActionResult,
    ActionTarget,
    Approval,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    AuthorityGate,
    BudgetCounters,
    Capability,
    Checkpoint,
    ExpectedPrecondition,
    IdempotencyRecord,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    RecoveryDisposition,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import DurablePrerequisiteError, StorageConflictError
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.persistence.prerequisites import (
    load_execution_prerequisites,
    register_approved_action,
)
from aioa_cloudops_agent.persistence.recovery import classify_recovery
from aioa_cloudops_agent.persistence.semantic_idempotency import (
    build_idempotency_record,
    derive_action_fingerprint,
    derive_idempotency_key,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
OTHER_PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
OTHER_RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b40")
EVENT_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3f")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _run(*, state: WorkflowState = WorkflowState.RECEIVED, version: int = 1) -> Run:
    return Run(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="request:idle-ec2:0001",
        state=state,
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=max(0, version - 1)),
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
        version=version,
    )


def _proposal(*, state: ProposalState = ProposalState.PROPOSED) -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=Capability.STOP_SANDBOX_INSTANCE,
        target=ActionTarget(
            resource_id="i-0123456789abcdef0",
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


def _approval(decision: ApprovalDecision = ApprovalDecision.APPROVED) -> Approval:
    proposal = _proposal(state=ProposalState.AWAITING_APPROVAL)
    return Approval(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-1",
        request_hash="f" * 64,
        decision=decision,
        decided_at=NOW + timedelta(seconds=5),
        actor_session_id="human-session-001",
        decision_nonce="nonce-approved-0001",
    )


def _prepare_awaiting_repository(
    decision: ApprovalDecision | None = None,
) -> tuple[
    InMemoryTestDurableTruthRepository,
    Run,
    ActionProposal,
    Approval | None,
]:
    repository = InMemoryTestDurableTruthRepository()
    run = repository.create_run(_run())
    states = (
        WorkflowState.INVESTIGATING,
        WorkflowState.EVIDENCE_READY,
        WorkflowState.REMEDIATION_PROPOSED,
    )
    for offset, state in enumerate(states, start=1):
        run = repository.transition_run(
            RUN_ID,
            state,
            expected_state=run.state,
            expected_version=run.version,
            updated_at=NOW + timedelta(seconds=offset),
        )
    proposal = repository.create_proposal(_proposal())
    proposal = repository.transition_proposal(
        PROPOSAL_ID,
        ProposalState.AWAITING_APPROVAL,
        expected_state=ProposalState.PROPOSED,
    )
    run = repository.transition_run(
        RUN_ID,
        WorkflowState.AWAITING_APPROVAL,
        expected_state=WorkflowState.REMEDIATION_PROPOSED,
        expected_version=run.version,
        updated_at=NOW + timedelta(seconds=4),
    )
    approval = repository.create_approval(_approval(decision)) if decision is not None else None
    return repository, run, proposal, approval


def _prepare_approved_repository(
    *,
    checkpoint_evidence_hash: str | None = DIGEST,
) -> tuple[
    InMemoryTestDurableTruthRepository,
    Run,
    ActionProposal,
    Approval,
]:
    repository, run, proposal, approval = _prepare_awaiting_repository(
        ApprovalDecision.APPROVED
    )
    assert approval is not None
    run = repository.transition_run(
        RUN_ID,
        WorkflowState.APPROVED,
        expected_state=WorkflowState.AWAITING_APPROVAL,
        expected_version=run.version,
        updated_at=NOW + timedelta(seconds=6),
        approval_proposal_id=PROPOSAL_ID,
    )
    repository.save_checkpoint(
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.APPROVED,
            resume_metadata={"proposal_id": str(PROPOSAL_ID)},
            tool_result_hashes=(
                {"build_remediation_evidence": checkpoint_evidence_hash}
                if checkpoint_evidence_hash is not None
                else {}
            ),
            created_at=NOW + timedelta(seconds=6),
        ),
        expected_version=None,
    )
    return repository, run, proposal, approval


def test_run_save_load_and_conditional_transition() -> None:
    repository = InMemoryTestDurableTruthRepository()
    created = repository.create_run(_run())

    loaded = repository.get_run(RUN_ID)
    updated = repository.transition_run(
        RUN_ID,
        WorkflowState.INVESTIGATING,
        expected_state=WorkflowState.RECEIVED,
        expected_version=1,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert loaded == created
    assert updated.state is WorkflowState.INVESTIGATING
    assert updated.version == 2
    with pytest.raises(StorageConflictError, match="state or version"):
        repository.transition_run(
            RUN_ID,
            WorkflowState.EVIDENCE_READY,
            expected_state=WorkflowState.RECEIVED,
            expected_version=1,
            updated_at=NOW + timedelta(seconds=2),
        )


def test_new_run_and_proposal_must_start_at_canonical_initial_state() -> None:
    repository = InMemoryTestDurableTruthRepository()

    with pytest.raises(StorageConflictError, match="RECEIVED version 1"):
        repository.create_run(_run(state=WorkflowState.INVESTIGATING))
    with pytest.raises(StorageConflictError, match="start at PROPOSED"):
        repository.create_proposal(_proposal(state=ProposalState.AWAITING_APPROVAL))


def test_run_cannot_enter_approved_without_positive_durable_approval() -> None:
    repository, run, _, _ = _prepare_awaiting_repository()

    with pytest.raises(StorageConflictError, match="matching durable human decision"):
        repository.transition_run(
            RUN_ID,
            WorkflowState.APPROVED,
            expected_state=WorkflowState.AWAITING_APPROVAL,
            expected_version=run.version,
            updated_at=NOW + timedelta(seconds=6),
            approval_proposal_id=PROPOSAL_ID,
        )


def test_proposal_and_approval_are_separate_create_only_records() -> None:
    repository = InMemoryTestDurableTruthRepository()
    proposal = repository.create_proposal(_proposal())
    proposal = repository.transition_proposal(
        PROPOSAL_ID,
        ProposalState.AWAITING_APPROVAL,
        expected_state=ProposalState.PROPOSED,
    )

    assert repository.get_proposal(PROPOSAL_ID) == proposal
    assert repository.get_approval(PROPOSAL_ID) is None
    assert proposal.authorizes_execution is False
    approval = repository.create_approval(_approval())
    assert repository.get_approval(PROPOSAL_ID) == approval
    with pytest.raises(StorageConflictError, match="conflicting"):
        repository.create_approval(_approval(ApprovalDecision.DENIED))


@pytest.mark.parametrize(
    "binding_change",
    [
        {"proposal_id": OTHER_PROPOSAL_ID},
        {"run_id": OTHER_RUN_ID},
    ],
)
def test_approval_from_another_run_or_proposal_cannot_authorize_execution(
    binding_change: dict[str, UUID],
) -> None:
    repository, _, _, _ = _prepare_awaiting_repository()
    substituted = _approval().model_copy(update=binding_change)

    with pytest.raises(StorageConflictError):
        repository.create_approval(substituted)

    assert repository.get_approval(PROPOSAL_ID) is None


def test_proposal_transition_is_conditional_and_cannot_be_reversed() -> None:
    repository = InMemoryTestDurableTruthRepository()
    repository.create_proposal(_proposal())
    awaiting = repository.transition_proposal(
        PROPOSAL_ID,
        ProposalState.AWAITING_APPROVAL,
        expected_state=ProposalState.PROPOSED,
    )

    assert awaiting.state is ProposalState.AWAITING_APPROVAL
    with pytest.raises(StorageConflictError):
        repository.transition_proposal(
            PROPOSAL_ID,
            ProposalState.PROPOSED,
            expected_state=ProposalState.AWAITING_APPROVAL,
        )


def test_semantic_idempotency_is_stable_and_exact_duplicate_reconciles() -> None:
    repository, _, proposal, _ = _prepare_approved_repository()
    first = build_idempotency_record(
        proposal,
        registered_at=NOW + timedelta(seconds=7),
    )

    assert derive_idempotency_key(proposal) == first.idempotency_key
    assert derive_action_fingerprint(proposal) == first.action_fingerprint
    assert repository.register_idempotency(first) == first
    assert repository.register_idempotency(first) == first
    assert repository.get_idempotency(first.idempotency_key) == first


def test_conflicting_idempotency_payload_is_rejected() -> None:
    repository, _, proposal, _ = _prepare_approved_repository()
    first = build_idempotency_record(
        proposal,
        registered_at=NOW + timedelta(seconds=7),
    )
    repository.register_idempotency(first)
    conflict = IdempotencyRecord(
        idempotency_key=first.idempotency_key,
        proposal_id=OTHER_PROPOSAL_ID,
        action_fingerprint="b" * 64,
        registered_at=NOW + timedelta(seconds=7),
    )

    with pytest.raises(StorageConflictError, match="incompatible ownership"):
        repository.register_idempotency(conflict)


def test_direct_idempotency_registration_requires_durable_human_approval() -> None:
    repository, _, proposal, _ = _prepare_awaiting_repository()
    record = build_idempotency_record(
        proposal,
        registered_at=NOW + timedelta(seconds=7),
    )

    with pytest.raises(StorageConflictError, match="requires human approval"):
        repository.register_idempotency(record)


def test_idempotency_result_is_retrievable_without_aws_side_effect() -> None:
    repository, _, _, _ = _prepare_approved_repository()
    record = register_approved_action(
        repository,
        PROPOSAL_ID,
        registered_at=NOW + timedelta(seconds=7),
    )
    result = ActionResult(
        outcome=ActionOutcome.SUCCEEDED,
        observed_state=ObservedInstanceState.STOPPED,
        evidence_hash="b" * 64,
    )

    completed = repository.complete_idempotency(
        record.idempotency_key,
        result,
        completed_at=NOW + timedelta(seconds=8),
    )

    assert completed.status is IdempotencyStatus.COMPLETED
    assert completed.action_result == result
    assert repository.get_idempotency(record.idempotency_key) == completed
    with pytest.raises(StorageConflictError):
        repository.complete_idempotency(
            record.idempotency_key,
            result,
            completed_at=NOW + timedelta(seconds=9),
        )


def test_checkpoint_round_trip_and_stale_version_rejection() -> None:
    repository = InMemoryTestDurableTruthRepository()
    first = Checkpoint(
        run_id=RUN_ID,
        last_safe_state=WorkflowState.EVIDENCE_READY,
        resume_metadata={"evidence": "ready"},
        tool_result_hashes={"inspect_instance": DIGEST},
        created_at=NOW,
        version=1,
    )
    second = first.model_copy(
        update={
            "last_safe_state": WorkflowState.REMEDIATION_PROPOSED,
            "created_at": NOW + timedelta(seconds=1),
            "version": 2,
        }
    )

    repository.save_checkpoint(first, expected_version=None)
    assert repository.get_checkpoint(RUN_ID) == first
    repository.save_checkpoint(second, expected_version=1)
    assert repository.get_checkpoint(RUN_ID) == second
    with pytest.raises(StorageConflictError, match="version"):
        repository.save_checkpoint(second, expected_version=1)


def test_audit_event_is_append_only_and_round_trips() -> None:
    repository = InMemoryTestDurableTruthRepository()
    event = AuditEvent(
        event_id=EVENT_ID,
        run_id=RUN_ID,
        type=AuditEventType.PROPOSAL_CREATED,
        timestamp=NOW,
        source="nz-control-plane",
        redacted_payload_hash=DIGEST,
    )

    repository.append_audit_event(event)

    assert repository.get_audit_event(RUN_ID, EVENT_ID) == event
    with pytest.raises(StorageConflictError, match="already exists"):
        repository.append_audit_event(event)
    assert not hasattr(repository, "overwrite_audit_event")
    assert not hasattr(repository, "delete_audit_event")


def test_durable_prerequisites_require_separate_approval_and_checkpoint() -> None:
    repository, run, proposal, approval = _prepare_approved_repository()
    idempotency = register_approved_action(
        repository,
        PROPOSAL_ID,
        registered_at=NOW + timedelta(seconds=7),
    )

    proof = load_execution_prerequisites(repository, PROPOSAL_ID)

    assert proof.run == run
    assert proof.proposal == proposal
    assert proof.approval == approval
    assert proof.idempotency == idempotency
    assert proof.checkpoint.last_safe_state is WorkflowState.APPROVED
    assert not hasattr(proof, "execute")


@pytest.mark.parametrize("checkpoint_evidence_hash", [None, "b" * 64])
def test_missing_or_mismatched_checkpoint_evidence_blocks_execution(
    checkpoint_evidence_hash: str | None,
) -> None:
    repository, _, _, _ = _prepare_approved_repository(
        checkpoint_evidence_hash=checkpoint_evidence_hash
    )
    register_approved_action(
        repository,
        PROPOSAL_ID,
        registered_at=NOW + timedelta(seconds=7),
    )

    with pytest.raises(DurablePrerequisiteError, match="proposal evidence hash"):
        load_execution_prerequisites(repository, PROPOSAL_ID)


def test_proposal_alone_never_satisfies_approval_prerequisite() -> None:
    repository, _, _, _ = _prepare_awaiting_repository()

    assert repository.get_approval(PROPOSAL_ID) is None
    with pytest.raises(DurablePrerequisiteError, match="missing approval"):
        register_approved_action(
            repository,
            PROPOSAL_ID,
            registered_at=NOW + timedelta(seconds=7),
        )


def test_human_denial_never_satisfies_execution_prerequisite() -> None:
    repository, _, _, _ = _prepare_awaiting_repository(ApprovalDecision.DENIED)

    with pytest.raises(DurablePrerequisiteError, match="does not approve"):
        register_approved_action(
            repository,
            PROPOSAL_ID,
            registered_at=NOW + timedelta(seconds=7),
        )


@pytest.mark.parametrize(
    ("run", "checkpoint", "expected"),
    [
        (None, None, RecoveryDisposition.NEW_RUN),
        (
            _run(state=WorkflowState.AWAITING_APPROVAL, version=5),
            None,
            RecoveryDisposition.AWAITING_APPROVAL,
        ),
        (
            _run(state=WorkflowState.EXECUTING, version=8),
            None,
            RecoveryDisposition.RECONCILIATION_REQUIRED,
        ),
        (
            _run(state=WorkflowState.SUCCESS_WITH_EVIDENCE, version=10),
            None,
            RecoveryDisposition.TERMINAL_RUN,
        ),
    ],
)
def test_recovery_disposition_is_conservative(
    run: Run | None,
    checkpoint: Checkpoint | None,
    expected: RecoveryDisposition,
) -> None:
    assert classify_recovery(run, checkpoint) is expected


def test_safe_recovery_requires_matching_durable_checkpoint() -> None:
    run = _run(state=WorkflowState.EVIDENCE_READY, version=3)
    checkpoint = Checkpoint(
        run_id=RUN_ID,
        last_safe_state=WorkflowState.EVIDENCE_READY,
        created_at=NOW + timedelta(seconds=2),
    )

    assert classify_recovery(run, checkpoint) is RecoveryDisposition.SAFE_RESUMABLE


def test_repository_exposes_no_cloudops_mutation_capability() -> None:
    repository = InMemoryTestDurableTruthRepository()

    for operation in (
        "stop_instances",
        "terminate_instances",
        "execute_mutation",
        "delete_run",
        "scan",
    ):
        assert not hasattr(repository, operation)
