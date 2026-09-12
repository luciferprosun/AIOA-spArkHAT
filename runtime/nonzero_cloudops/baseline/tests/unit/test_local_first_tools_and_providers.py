from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from aioa_cloudops_agent.agent import create_local_first_runtime
from aioa_cloudops_agent.cloudops import (
    MOCK_CLEAN_INSTANCE_ID,
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
    MOCK_UNTAGGED_INSTANCE_ID,
    MockAwsAdapter,
    PlanRemediation,
    QueryResource,
)
from aioa_cloudops_agent.config import LocalFirstMode, LocalFirstSettings
from aioa_cloudops_agent.domain import AuthorityGate, ContractValidationError
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    CloudFinding,
    CloudResourceType,
    FailureKind,
    PlanDisposition,
    ResourceEvidence,
    ResourceQuery,
    ResultStatus,
    Run,
)
from aioa_cloudops_agent.providers import (
    MockModelFailure,
    MockModelProvider,
    ModelProviderError,
    ModelProviderNonRetryableError,
    ModelProviderRetryableError,
    ModelProviderTimeoutError,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_IDS = tuple(
    UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{value:02x}") for value in range(80, 96)
)
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def _run() -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="local/tools/0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )


def _query(
    resource_type: CloudResourceType,
    resource_id: str,
    *,
    adapter: MockAwsAdapter | None = None,
) -> tuple[MockAwsAdapter, object]:
    selected = adapter or MockAwsAdapter()
    result = QueryResource(selected).execute(
        ResourceQuery(resource_type=resource_type, resource_id=resource_id),
        run=_run(),
        observed_at=NOW,
    )
    return selected, result


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "finding"),
    [
        (
            CloudResourceType.ELASTIC_IP,
            MOCK_UNATTACHED_EIP_ID,
            CloudFinding.UNATTACHED_ELASTIC_IP,
        ),
        (
            CloudResourceType.SECURITY_GROUP,
            MOCK_UNSAFE_SECURITY_GROUP_ID,
            CloudFinding.OVERLY_PERMISSIVE_INGRESS,
        ),
        (
            CloudResourceType.EC2_INSTANCE,
            MOCK_UNTAGGED_INSTANCE_ID,
            CloudFinding.REQUIRED_TAGS_MISSING,
        ),
        (
            CloudResourceType.EC2_INSTANCE,
            MOCK_CLEAN_INSTANCE_ID,
            CloudFinding.CLEAN,
        ),
    ],
)
def test_query_resource_covers_deterministic_scenarios_a_to_d(
    resource_type: CloudResourceType,
    resource_id: str,
    finding: CloudFinding,
) -> None:
    adapter, result = _query(resource_type, resource_id)

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.findings == (finding,)
    assert result.value.resource.resource_id == resource_id
    assert len(adapter.read_calls) == 1
    assert adapter.mutation_calls == adapter.network_calls == 0


def test_query_resource_distinguishes_not_found_invalid_input_and_adapter_failure() -> None:
    _, missing = _query(
        CloudResourceType.ELASTIC_IP,
        "eipalloc-0fedcba9876543210",
    )
    assert missing.status is ResultStatus.FAILURE
    assert missing.failure is not None
    assert missing.failure.kind is FailureKind.NOT_FOUND

    invalid = QueryResource(MockAwsAdapter()).execute(
        {"resource_type": CloudResourceType.ELASTIC_IP.value, "resource_id": "bad"},
        run=_run(),
        observed_at=NOW,
    )
    assert invalid.failure is not None
    assert invalid.failure.kind is FailureKind.VALIDATION_FAILURE

    _, failed = _query(
        CloudResourceType.ELASTIC_IP,
        MOCK_UNATTACHED_EIP_ID,
        adapter=MockAwsAdapter(fail_operations=frozenset({"get_resource"})),
    )
    assert failed.failure is not None
    assert failed.failure.kind is FailureKind.TOOL_ADAPTER_FAILURE
    assert failed.failure.retryable is True


def _evidence(resource_type: CloudResourceType, resource_id: str) -> ResourceEvidence:
    _, result = _query(resource_type, resource_id)
    assert result.value is not None
    return result.value


@pytest.mark.parametrize(
    ("resource_type", "resource_id", "disposition", "authority"),
    [
        (
            CloudResourceType.ELASTIC_IP,
            MOCK_UNATTACHED_EIP_ID,
            PlanDisposition.PROPOSAL,
            AuthorityGate.PLAN_AND_CONFIRM,
        ),
        (
            CloudResourceType.SECURITY_GROUP,
            MOCK_UNSAFE_SECURITY_GROUP_ID,
            PlanDisposition.PROPOSAL,
            AuthorityGate.PLAN_AND_CONFIRM,
        ),
        (
            CloudResourceType.EC2_INSTANCE,
            MOCK_UNTAGGED_INSTANCE_ID,
            PlanDisposition.NON_EXECUTABLE_RECOMMENDATION,
            AuthorityGate.NEVER_AUTONOMOUS,
        ),
    ],
)
def test_plan_remediation_enforces_local_authority(
    resource_type: CloudResourceType,
    resource_id: str,
    disposition: PlanDisposition,
    authority: AuthorityGate,
) -> None:
    evidence = _evidence(resource_type, resource_id)
    model = MockModelProvider()
    result = PlanRemediation().execute(
        evidence,
        model_output=model.create_plan(evidence),
        proposal_id=PROPOSAL_IDS[0],
        created_at=NOW,
    )

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.disposition is disposition
    assert result.value.proposal is not None
    assert result.value.proposal.authority_class is authority
    assert result.value.proposal.authorizes_execution is False


def test_clean_resource_returns_explicit_no_action() -> None:
    evidence = _evidence(CloudResourceType.EC2_INSTANCE, MOCK_CLEAN_INSTANCE_ID)
    model = MockModelProvider()

    result = PlanRemediation().execute(
        evidence,
        model_output=model.create_plan(evidence),
        proposal_id=PROPOSAL_IDS[0],
        created_at=NOW,
    )

    assert result.value is not None
    assert result.value.disposition is PlanDisposition.NO_ACTION
    assert result.value.proposal is None


def test_repeated_planning_keeps_action_hash_stable() -> None:
    evidence = _evidence(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID)
    model = MockModelProvider()
    planner = PlanRemediation()
    output = model.create_plan(evidence)

    first = planner.execute(
        evidence,
        model_output=output,
        proposal_id=PROPOSAL_IDS[0],
        created_at=NOW,
    )
    second = planner.execute(
        evidence,
        model_output=output,
        proposal_id=PROPOSAL_IDS[1],
        created_at=NOW + timedelta(minutes=10),
    )

    assert first.value is not None and first.value.proposal is not None
    assert second.value is not None and second.value.proposal is not None
    assert first.value.proposal.proposal_hash == second.value.proposal.proposal_hash


@pytest.mark.parametrize(
    ("failure", "expected_kind"),
    [
        (MockModelFailure.MALFORMED, FailureKind.VALIDATION_FAILURE),
        (MockModelFailure.POLICY_INVALID, FailureKind.POLICY_DENIAL),
    ],
)
def test_untrusted_model_output_cannot_create_proposal(
    failure: MockModelFailure,
    expected_kind: FailureKind,
) -> None:
    evidence = _evidence(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID)
    output = MockModelProvider(failure=failure).create_plan(evidence)

    result = PlanRemediation().execute(
        evidence,
        model_output=output,
        proposal_id=PROPOSAL_IDS[0],
        created_at=NOW,
    )

    assert result.status is ResultStatus.FAILURE
    assert result.value is None
    assert result.failure is not None
    assert result.failure.kind is expected_kind


def test_mock_model_provider_supports_explicit_error_and_timeout() -> None:
    evidence = _evidence(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID)

    with pytest.raises(ModelProviderError):
        MockModelProvider(failure=MockModelFailure.PROVIDER_ERROR).create_plan(evidence)
    with pytest.raises(ModelProviderTimeoutError):
        MockModelProvider(failure=MockModelFailure.TIMEOUT).create_plan(evidence)
    with pytest.raises(ModelProviderRetryableError):
        MockModelProvider(failure=MockModelFailure.RETRYABLE_ERROR).create_plan(evidence)
    with pytest.raises(ModelProviderNonRetryableError):
        MockModelProvider(failure=MockModelFailure.NON_RETRYABLE_ERROR).create_plan(evidence)


def test_mock_provider_has_explicit_approval_required_and_empty_scenarios() -> None:
    evidence = _evidence(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID)

    approval = MockModelProvider(failure=MockModelFailure.APPROVAL_REQUIRED)
    empty = MockModelProvider(failure=MockModelFailure.EMPTY)

    approval_result = PlanRemediation().execute(
        evidence,
        model_output=approval.create_plan(evidence),
        proposal_id=PROPOSAL_IDS[0],
        created_at=NOW,
    )
    empty_result = PlanRemediation().execute(
        evidence,
        model_output=empty.create_plan(evidence),
        proposal_id=PROPOSAL_IDS[1],
        created_at=NOW,
    )

    assert approval_result.value is not None
    assert approval_result.value.disposition is PlanDisposition.PROPOSAL
    assert approval_result.value.proposal is not None
    assert approval_result.value.proposal.authority_class is AuthorityGate.PLAN_AND_CONFIRM
    assert approval_result.value.proposal.authorizes_execution is False
    assert empty_result.status is ResultStatus.FAILURE
    assert empty_result.failure is not None
    assert empty_result.failure.kind is FailureKind.VALIDATION_FAILURE


def test_local_composition_defaults_to_mock_and_never_falls_back_from_live(
    tmp_path: Path,
) -> None:
    runtime = create_local_first_runtime(
        LocalFirstSettings(state_path=tmp_path / "state.json")
    )
    assert runtime.cloud_provider.adapter_name == "mock-aws-adapter"
    assert runtime.cloud_provider.network_calls == 0
    assert runtime.model_provider.network_calls == 0

    with pytest.raises(ContractValidationError, match="no mock fallback"):
        create_local_first_runtime(
            LocalFirstSettings(
                mode=LocalFirstMode.LIVE,
                state_path=tmp_path / "live.json",
            )
        )
