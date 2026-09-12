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
    ExecutionAcknowledgement,
    ExpectedPrecondition,
    FailureDetail,
    FailureKind,
    IdempotencyRecord,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    Run,
    VerificationEvidence,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError
from aioa_cloudops_agent.persistence.serialization import (
    deserialize_record,
    from_dynamo_attribute,
    serialize_record,
    to_dynamo_attribute,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVENT_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
EVIDENCE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3f")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _records() -> tuple[object, ...]:
    run = Run(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="request:idle-ec2:0001",
        state=WorkflowState.APPROVED,
        created_at=NOW,
        updated_at=NOW + timedelta(seconds=6),
        budget=BudgetCounters(
            max_turns=8,
            max_tokens=8_192,
            turns_used=3,
            tokens_used=900,
        ),
        version=7,
    )
    proposal = ActionProposal(
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
        state=ProposalState.AWAITING_APPROVAL,
        evidence_hash=DIGEST,
        created_at=NOW,
    )
    approval = Approval(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-1",
        request_hash="f" * 64,
        decision=ApprovalDecision.APPROVED,
        decided_at=NOW + timedelta(seconds=5),
        actor_session_id="human-session-001",
        decision_nonce="nonce-approved-0001",
    )
    failure = FailureDetail(
        kind=FailureKind.VERIFICATION_FAILURE,
        code="INSTANCE_STATE_UNVERIFIED",
        message="Instance state could not be proven",
        retryable=True,
    )
    idempotency = IdempotencyRecord(
        idempotency_key="action/" + "b" * 64,
        proposal_id=PROPOSAL_ID,
        action_fingerprint="b" * 64,
        status=IdempotencyStatus.FAILED,
        action_result=ActionResult(outcome=ActionOutcome.FAILED, failure=failure),
        registered_at=NOW + timedelta(seconds=7),
        completed_at=NOW + timedelta(seconds=8),
    )
    checkpoint = Checkpoint(
        run_id=RUN_ID,
        last_safe_state=WorkflowState.APPROVED,
        resume_metadata={
            "reason": "approved-before-execution",
            "attempt": 1,
            "confidence": 0.75,
        },
        tool_result_hashes={"inspect_instance": DIGEST},
        created_at=NOW + timedelta(seconds=6),
        version=2,
    )
    event = AuditEvent(
        event_id=EVENT_ID,
        run_id=RUN_ID,
        type=AuditEventType.APPROVAL_RECORDED,
        timestamp=NOW + timedelta(seconds=5),
        source="approval-service",
        tool_name="inspect_instance",
        model_id="eu.amazon.nova-2-lite-v1:0",
        redacted_payload_hash="c" * 64,
        metadata={"decision": "APPROVED"},
    )
    acknowledgement = ExecutionAcknowledgement(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        target=proposal.target,
        current_state=ObservedInstanceState.STOPPING,
        request_reference="request-safe-001",
        acknowledged_at=NOW + timedelta(seconds=8),
        acknowledgement_hash="d" * 64,
    )
    evidence = VerificationEvidence.create(
        evidence_id=EVIDENCE_ID,
        proposal=proposal,
        run=run,
        verified_at=NOW + timedelta(seconds=9),
        acknowledgement=acknowledgement,
        observation_hash="e" * 64,
    )
    return run, proposal, approval, idempotency, checkpoint, event, evidence


@pytest.mark.parametrize("record", _records(), ids=lambda record: type(record).__name__)
def test_nz_record_survives_dynamodb_round_trip(record: object) -> None:
    restored = deserialize_record(serialize_record(record), type(record))

    assert restored == record
    assert type(restored) is type(record)


def test_explicit_failure_enum_and_timestamp_survive_round_trip() -> None:
    idempotency = _records()[3]
    restored = deserialize_record(serialize_record(idempotency), IdempotencyRecord)

    assert restored.status is IdempotencyStatus.FAILED
    assert restored.action_result is not None
    assert restored.action_result.failure is not None
    assert restored.action_result.failure.kind is FailureKind.VERIFICATION_FAILURE
    assert restored.completed_at == NOW + timedelta(seconds=8)
    assert restored.completed_at is not None
    assert restored.completed_at.utcoffset() == timedelta(0)


def test_json_subset_serialization_is_deterministic() -> None:
    payload = {"z": [1, 0.75, True, None], "a": {"state": "APPROVED"}}

    first = to_dynamo_attribute(payload)
    second = to_dynamo_attribute(payload)

    assert first == second
    assert from_dynamo_attribute(first) == payload
    assert list(first["M"]) == ["a", "z"]


def test_malformed_or_lossy_dynamodb_attributes_fail_explicitly() -> None:
    with pytest.raises(StorageDependencyError):
        from_dynamo_attribute({"N": "NaN"})
    with pytest.raises(StorageDependencyError):
        deserialize_record({"S": "not-a-record-map"}, Run)
    with pytest.raises(TypeError):
        to_dynamo_attribute(float("inf"))
