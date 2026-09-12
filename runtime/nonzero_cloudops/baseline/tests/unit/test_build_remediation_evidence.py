from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from aioa_cloudops_agent.cloudops import (
    BuildRemediationEvidenceService,
    Ec2InstanceState,
    Ec2MonitoringState,
    EvidenceBuildOutcome,
    EvidenceDecision,
    InstanceInspection,
    InvestigationIdentity,
    MetricDatapoint,
    RemediationEvidenceBundle,
    SandboxTarget,
    UtilizationEvidence,
    create_build_remediation_evidence_tool,
)
from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass
from aioa_cloudops_agent.nz import Capability, FailureKind, ProposalState, ResultStatus

INSTANCE_ID = "i-0123456789abcdef0"
OTHER_INSTANCE_ID = "i-0fedcba9876543210"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )


def _inspection(*, state: Ec2InstanceState = Ec2InstanceState.RUNNING) -> InstanceInspection:
    return InstanceInspection.create(
        identity=_identity(),
        instance_id=INSTANCE_ID,
        region="eu-central-1",
        state=state,
        instance_type="t3.micro",
        launch_time=NOW - timedelta(hours=2),
        monitoring_state=Ec2MonitoringState.DISABLED,
        availability_zone="eu-central-1a",
        sandbox_tag_key="AIOACloudOpsSandbox",
        sandbox_tag_value="true",
    )


def _utilization(*values: float) -> UtilizationEvidence:
    return UtilizationEvidence.create(
        identity=_identity(),
        instance_id=INSTANCE_ID,
        window_start=NOW - timedelta(hours=1),
        window_end=NOW,
        period_seconds=300,
        minimum_datapoints=6,
        idle_threshold_percent=10.0,
        datapoints=tuple(
            MetricDatapoint(
                timestamp=NOW - timedelta(minutes=5 * (index + 1)),
                value_percent=value,
            )
            for index, value in enumerate(values)
        ),
        collected_at=NOW,
    )


def _service() -> BuildRemediationEvidenceService:
    return BuildRemediationEvidenceService(SandboxTarget(instance_id=INSTANCE_ID))


def test_candidate_evidence_builds_fixed_non_authorizing_proposal() -> None:
    outcome = _service().build(
        inspection=_inspection(),
        utilization=_utilization(1, 2, 3, 4, 5, 6),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )

    assert outcome.decision is EvidenceDecision.PROPOSAL_READY
    assert outcome.proposal is not None
    assert outcome.proposal.proposal_id == PROPOSAL_ID
    assert outcome.proposal.run_id == RUN_ID
    assert outcome.proposal.action is Capability.STOP_SANDBOX_INSTANCE
    assert outcome.proposal.target.resource_id == INSTANCE_ID
    assert outcome.proposal.authority is AuthorityGate.PLAN_AND_CONFIRM
    assert outcome.proposal.state is ProposalState.PROPOSED
    assert outcome.proposal.authorizes_execution is False
    assert outcome.proposal.evidence_hash == outcome.evidence.evidence_hash
    assert outcome.evidence.authority_gate is AuthorityGate.AUTO
    assert outcome.evidence.operation_class is AwsOperationClass.READ_ONLY


@pytest.mark.parametrize(
    ("inspection", "utilization"),
    [
        (_inspection(), _utilization(20, 21, 22, 23, 24, 25)),
        (_inspection(state=Ec2InstanceState.STOPPED), _utilization(1, 2, 3, 4, 5, 6)),
    ],
)
def test_busy_or_nonrunning_instance_produces_explicit_nonproposal(
    inspection: InstanceInspection,
    utilization: UtilizationEvidence,
) -> None:
    outcome = _service().build(
        inspection=inspection,
        utilization=utilization,
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )

    assert outcome.decision is EvidenceDecision.NOT_ELIGIBLE
    assert outcome.proposal is None


def test_ambiguous_utilization_cannot_form_evidence_or_proposal() -> None:
    result = _service().build_result(
        inspection=_inspection(),
        utilization=_utilization(),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
    assert result.value is None


def test_evidence_hash_is_stable_and_changes_with_decision_evidence() -> None:
    service = _service()
    first = service.build(
        inspection=_inspection(),
        utilization=_utilization(1, 2, 3, 4, 5, 6),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )
    repeated = service.build(
        inspection=_inspection(),
        utilization=_utilization(1, 2, 3, 4, 5, 6),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )
    changed = service.build(
        inspection=_inspection(),
        utilization=_utilization(2, 3, 4, 5, 6, 7),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )

    assert first.evidence.evidence_hash == repeated.evidence.evidence_hash
    assert first.proposal == repeated.proposal
    assert first.evidence.evidence_hash != changed.evidence.evidence_hash
    assert first.proposal != changed.proposal


def test_evidence_and_proposal_round_trip_preserve_typed_boundaries() -> None:
    outcome = _service().build(
        inspection=_inspection(),
        utilization=_utilization(1, 2, 3, 4, 5, 6),
        identity=_identity(),
        proposal_id=PROPOSAL_ID,
        built_at=NOW,
    )

    restored = EvidenceBuildOutcome.model_validate_json(outcome.model_dump_json())
    evidence = RemediationEvidenceBundle.model_validate_json(
        outcome.evidence.model_dump_json()
    )

    assert restored == outcome
    assert evidence == outcome.evidence
    assert restored.proposal is not None
    assert restored.proposal.authority is AuthorityGate.PLAN_AND_CONFIRM
    assert restored.proposal.authorizes_execution is False


def test_build_tool_accepts_only_target_id_and_uses_bound_typed_evidence() -> None:
    tool = create_build_remediation_evidence_tool(
        _service(),
        _inspection,
        lambda: _utilization(1, 2, 3, 4, 5, 6),
        _identity(),
        SandboxTarget(instance_id=INSTANCE_ID),
        PROPOSAL_ID,
        clock=lambda: NOW,
    )

    result = tool(instance_id=INSTANCE_ID)
    schema = tool.tool_spec["inputSchema"]["json"]

    assert tool.tool_name == "build_remediation_evidence"
    assert set(schema["properties"]) == {"instance_id"}
    assert schema["required"] == ["instance_id"]
    assert result["status"] == "SUCCESS"
    assert result["value"]["proposal"]["action"] == "stop_sandbox_instance"
    assert result["value"]["proposal"]["authority"] == "PLAN_AND_CONFIRM"
    with pytest.raises(TypeError):
        tool(
            instance_id=INSTANCE_ID,
            action="TerminateInstances",
            target=OTHER_INSTANCE_ID,
        )


def test_build_tool_fails_closed_without_prior_typed_evidence() -> None:
    tool = create_build_remediation_evidence_tool(
        _service(),
        lambda: None,
        lambda: None,
        _identity(),
        SandboxTarget(instance_id=INSTANCE_ID),
        PROPOSAL_ID,
        clock=lambda: NOW,
    )

    result = tool(instance_id=INSTANCE_ID)

    assert result["status"] == "FAILURE"
    assert result["failure"]["kind"] == FailureKind.VALIDATION_FAILURE.value
