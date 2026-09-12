from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

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
    ControlResult,
    ExpectedPrecondition,
    FailureDetail,
    FailureKind,
    IdempotencyRecord,
    IdempotencyStatus,
    ObservedInstanceState,
    ResultStatus,
    Run,
    WorkflowState,
    generate_event_id,
    generate_proposal_id,
    generate_run_id,
    generate_trace_id,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVENT_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64


def _run(**overrides: object) -> Run:
    values: dict[str, object] = {
        "run_id": RUN_ID,
        "trace_id": TRACE_ID,
        "correlation_id": CORRELATION_ID,
        "idempotency_key": "request:idle-ec2:0001",
        "state": WorkflowState.RECEIVED,
        "created_at": NOW,
        "updated_at": NOW,
        "budget": BudgetCounters(max_turns=8, max_tokens=8_192),
        "version": 1,
    }
    values.update(overrides)
    return Run.model_validate(values)


def _proposal(**overrides: object) -> ActionProposal:
    values: dict[str, object] = {
        "proposal_id": PROPOSAL_ID,
        "run_id": RUN_ID,
        "action": Capability.STOP_SANDBOX_INSTANCE,
        "target": ActionTarget(
            resource_id="i-0123456789abcdef0",
            sandbox_scope="hackathon-sandbox",
        ),
        "expected_precondition": ExpectedPrecondition(
            instance_state=ObservedInstanceState.RUNNING,
            observed_at=NOW,
            evidence_hash=DIGEST,
        ),
        "authority": AuthorityGate.PLAN_AND_CONFIRM,
        "evidence_hash": DIGEST,
        "created_at": NOW,
    }
    values.update(overrides)
    return ActionProposal.model_validate(values)


def test_valid_run_creation_uses_explicit_received_state() -> None:
    run = Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="request:idle-ec2:0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
    )

    assert run.state is WorkflowState.RECEIVED
    assert run.version == 1


def test_invalid_or_missing_workflow_state_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _run(state="MODEL_INVENTED_STATE")
    with pytest.raises(ValidationError):
        _run(state=None)


@pytest.mark.parametrize("field", ["run_id", "trace_id", "correlation_id"])
def test_identity_fields_reject_empty_or_non_uuid7_values(field: str) -> None:
    with pytest.raises(ValidationError):
        _run(**{field: ""})
    with pytest.raises(ValidationError):
        _run(**{field: uuid4()})


def test_generated_workflow_identifiers_are_uuid7() -> None:
    generated = (
        generate_run_id(),
        generate_trace_id(),
        generate_proposal_id(),
        generate_event_id(),
    )

    assert all(identifier.version == 7 for identifier in generated)


def test_action_proposal_is_typed_and_never_approval() -> None:
    proposal = _proposal()

    assert proposal.action is Capability.STOP_SANDBOX_INSTANCE
    assert proposal.authority is AuthorityGate.PLAN_AND_CONFIRM
    assert proposal.authorizes_execution is False


@pytest.mark.parametrize(
    "override",
    [
        {"action": "StopInstances"},
        {"action": Capability.INSPECT_INSTANCE},
        {"authority": AuthorityGate.AUTO},
        {"evidence_hash": "b" * 64},
        {
            "expected_precondition": ExpectedPrecondition(
                instance_state=ObservedInstanceState.STOPPED,
                observed_at=NOW,
                evidence_hash=DIGEST,
            )
        },
    ],
)
def test_malformed_action_proposal_is_rejected(override: dict[str, object]) -> None:
    with pytest.raises((ValidationError, ValueError)):
        _proposal(**override)


def test_model_like_free_form_arguments_cannot_become_executable_action() -> None:
    payload = _proposal().model_dump(mode="json")
    payload["arguments"] = {
        "InstanceIds": ["i-0123456789abcdef0"],
        "shell": "aws ec2 stop-instances",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ActionProposal.model_validate(payload)


def test_approval_is_explicit_positive_or_negative_data() -> None:
    proposal = _proposal()
    approved = Approval(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-1",
        request_hash="f" * 64,
        decision=ApprovalDecision.APPROVED,
        decided_at=NOW,
        actor_session_id="human-session-001",
        decision_nonce="nonce-approved-0001",
    )
    denied = approved.model_copy(update={"decision": ApprovalDecision.DENIED})

    assert approved.decision is ApprovalDecision.APPROVED
    assert denied.decision is ApprovalDecision.DENIED


def test_missing_or_ambiguous_approval_is_never_approval() -> None:
    with pytest.raises(ValidationError):
        Approval.model_validate(
            {
                "proposal_id": str(PROPOSAL_ID),
                "decided_at": NOW.isoformat(),
                "actor_session_id": "human-session-001",
                "decision_nonce": "nonce-approved-0001",
            }
        )
    with pytest.raises(ValidationError):
        Approval.model_validate(
            {
                "proposal_id": str(PROPOSAL_ID),
                "decision": True,
                "decided_at": NOW.isoformat(),
                "actor_session_id": "human-session-001",
                "decision_nonce": "nonce-approved-0001",
            }
        )


def test_explicit_failure_survives_serialization_round_trip() -> None:
    failure = FailureDetail(
        kind=FailureKind.DEPENDENCY_UNAVAILABLE,
        code="DYNAMODB_UNAVAILABLE",
        message="Durable source of truth is unavailable",
        retryable=True,
    )
    result = ControlResult[str].failed(failure)

    restored = ControlResult[str].model_validate_json(result.model_dump_json())

    assert restored.status is ResultStatus.FAILURE
    assert restored.value is None
    assert restored.failure == failure


def test_control_result_rejects_ambiguous_none() -> None:
    with pytest.raises(ValidationError):
        ControlResult[str](status=ResultStatus.SUCCESS, value=None)
    with pytest.raises(ValidationError):
        ControlResult[str](status=ResultStatus.FAILURE, failure=None)


def test_budget_counters_are_bounded() -> None:
    with pytest.raises(ValidationError, match="turns_used"):
        BudgetCounters(max_turns=2, max_tokens=100, turns_used=3)
    with pytest.raises(ValidationError, match="tokens_used"):
        BudgetCounters(max_turns=2, max_tokens=100, tokens_used=101)


def test_core_pydantic_contracts_round_trip_with_typed_values() -> None:
    proposal = _proposal()
    approval = Approval(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=proposal.action,
        target=proposal.target,
        evidence_hash=proposal.evidence_hash,
        interrupt_id="v1:before_tool_call:stop-1",
        request_hash="f" * 64,
        decision=ApprovalDecision.APPROVED,
        decided_at=NOW,
        actor_session_id="human-session-001",
        decision_nonce="nonce-approved-0001",
    )
    action_result = ActionResult(
        outcome=ActionOutcome.SUCCEEDED,
        observed_state=ObservedInstanceState.STOPPED,
        evidence_hash="b" * 64,
    )
    idempotency = IdempotencyRecord(
        idempotency_key="idem:logical-action:0001",
        proposal_id=PROPOSAL_ID,
        action_fingerprint="c" * 64,
        status=IdempotencyStatus.COMPLETED,
        action_result=action_result,
        registered_at=NOW,
        completed_at=NOW + timedelta(seconds=10),
    )
    checkpoint = Checkpoint(
        run_id=RUN_ID,
        last_safe_state=WorkflowState.APPROVED,
        resume_metadata={"reason": "approved-before-execution"},
        tool_result_hashes={"inspect_instance": DIGEST},
        created_at=NOW,
    )
    event = AuditEvent(
        event_id=EVENT_ID,
        run_id=RUN_ID,
        type=AuditEventType.APPROVAL_RECORDED,
        timestamp=NOW,
        source="approval-service",
        redacted_payload_hash="d" * 64,
        metadata={"decision": "APPROVED"},
    )

    records = (approval, idempotency, checkpoint, event)
    restored = tuple(
        type(record).model_validate_json(record.model_dump_json()) for record in records
    )

    assert restored == records


def test_active_side_effect_state_cannot_be_marked_as_safe_checkpoint() -> None:
    with pytest.raises(ValidationError, match="cannot label"):
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.EXECUTING,
            created_at=NOW,
        )


def test_audit_event_rejects_sensitive_metadata_key() -> None:
    with pytest.raises(ValidationError, match="sensitive"):
        AuditEvent(
            event_id=EVENT_ID,
            run_id=RUN_ID,
            type=AuditEventType.MODEL_OBSERVED,
            timestamp=NOW,
            source="strands-agent",
            redacted_payload_hash=DIGEST,
            metadata={"session_token": "prohibited"},
        )
