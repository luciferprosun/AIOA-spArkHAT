from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MockAwsAdapter,
    QueryResource,
)
from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    CloudFinding,
    CloudResourceType,
    PlanDisposition,
    RemediationOperation,
    RemediationPlan,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
    ResultStatus,
    Run,
    WorkflowState,
    WorkflowTransitionError,
    validate_workflow_transition,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
SECOND_PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3e")
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _run() -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="local/contracts/0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )


def _evidence() -> ResourceEvidence:
    result = QueryResource(MockAwsAdapter()).execute(
        ResourceQuery(
            resource_type=CloudResourceType.ELASTIC_IP,
            resource_id=MOCK_UNATTACHED_EIP_ID,
        ),
        run=_run(),
        observed_at=NOW,
    )
    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    return result.value


def _proposal(proposal_id: UUID, created_at: datetime) -> RemediationProposal:
    evidence = _evidence()
    return RemediationProposal.create(
        proposal_id=proposal_id,
        evidence=evidence,
        operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
        normalized_parameters={"allocation_id": MOCK_UNATTACHED_EIP_ID},
        authority_class=AuthorityGate.PLAN_AND_CONFIRM,
        risk_summary="Exact release requires human approval",
        created_at=created_at,
        expires_at=created_at + timedelta(hours=24),
    )


def test_resource_query_rejects_mismatched_identifier_and_unknown_enum() -> None:
    with pytest.raises(ValidationError, match="resource_id"):
        ResourceQuery(
            resource_type=CloudResourceType.ELASTIC_IP,
            resource_id="i-0123456789abcdef0",
        )
    with pytest.raises(ValidationError):
        ResourceQuery.model_validate(
            {"resource_type": "AWS::UNKNOWN", "resource_id": MOCK_UNATTACHED_EIP_ID}
        )


def test_resource_evidence_round_trips_and_rejects_tampered_hash() -> None:
    evidence = _evidence()

    assert ResourceEvidence.model_validate_json(evidence.model_dump_json()) == evidence
    payload = evidence.model_dump(mode="json")
    payload["evidence_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="evidence_hash"):
        ResourceEvidence.model_validate(payload)


def test_proposal_hash_is_stable_across_unique_ids_and_timestamps() -> None:
    first = _proposal(PROPOSAL_ID, NOW)
    second = _proposal(SECOND_PROPOSAL_ID, NOW + timedelta(minutes=5))

    assert first.proposal_id != second.proposal_id
    assert first.created_at != second.created_at
    assert first.proposal_hash == second.proposal_hash
    assert first.authorizes_execution is False


def test_proposal_rejects_model_claimed_auto_authority_and_tampering() -> None:
    proposal = _proposal(PROPOSAL_ID, NOW)
    payload = proposal.model_dump(mode="json")
    payload["authority_class"] = AuthorityGate.AUTO.value
    with pytest.raises(ValidationError, match="authority policy"):
        RemediationProposal.model_validate(payload)

    payload = proposal.model_dump(mode="json")
    payload["normalized_parameters"] = {"allocation_id": "eipalloc-0fedcba9876543210"}
    with pytest.raises(ValidationError, match="proposal_hash"):
        RemediationProposal.model_validate(payload)


def test_plan_discriminator_never_blurs_no_action_and_proposal() -> None:
    evidence = _evidence()
    proposal = _proposal(PROPOSAL_ID, NOW)
    with pytest.raises(ValidationError, match="NO_ACTION"):
        RemediationPlan(
            disposition=PlanDisposition.NO_ACTION,
            evidence_hash=evidence.evidence_hash,
            proposal=proposal,
            reason="invalid mixed result",
        )


def test_new_safe_terminal_states_are_terminal_and_pending_cannot_shortcut_success() -> None:
    assert (
        validate_workflow_transition(
            WorkflowState.EVIDENCE_READY,
            WorkflowState.NO_ACTION_REQUIRED,
        )
        is WorkflowState.NO_ACTION_REQUIRED
    )
    assert (
        validate_workflow_transition(
            WorkflowState.EVIDENCE_READY,
            WorkflowState.RECOMMENDATION_ONLY,
        )
        is WorkflowState.RECOMMENDATION_ONLY
    )
    for terminal in (WorkflowState.NO_ACTION_REQUIRED, WorkflowState.RECOMMENDATION_ONLY):
        with pytest.raises(WorkflowTransitionError):
            validate_workflow_transition(terminal, WorkflowState.INVESTIGATING)
    with pytest.raises(WorkflowTransitionError):
        validate_workflow_transition(
            WorkflowState.AWAITING_APPROVAL,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
        )


def test_evidence_has_explicit_finding_and_auto_authority() -> None:
    evidence = _evidence()

    assert evidence.findings == (CloudFinding.UNATTACHED_ELASTIC_IP,)
    assert evidence.authority is AuthorityGate.AUTO
    assert evidence.provenance.adapter == "mock-aws-adapter"
