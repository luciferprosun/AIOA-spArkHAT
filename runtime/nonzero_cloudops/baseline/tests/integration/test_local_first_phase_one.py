from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from aioa_cloudops_agent.agent import LocalFirstPhaseOneFlow
from aioa_cloudops_agent.cloudops import (
    MOCK_CLEAN_INSTANCE_ID,
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNTAGGED_INSTANCE_ID,
    MockAwsAdapter,
    PlanRemediation,
    QueryResource,
)
from aioa_cloudops_agent.domain import ApprovalStatus, ExecutionState
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    CloudResourceType,
    FailureKind,
    PlanDisposition,
    ResourceQuery,
    ResultStatus,
    Run,
    StorageConflictError,
    WorkflowState,
    WorkflowTransitionError,
    generate_event_id,
)
from aioa_cloudops_agent.persistence import LocalFileDurableTruthRepository
from aioa_cloudops_agent.providers import MockModelFailure, MockModelProvider

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_IDS = tuple(
    UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{value:02x}") for value in range(80, 96)
)
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


class ProposalIdFactory:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> UUID:
        value = PROPOSAL_IDS[self.index]
        self.index += 1
        return value


def _run() -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="local/integration/0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )


def _flow(
    path: Path,
    *,
    adapter: MockAwsAdapter | None = None,
    model: MockModelProvider | None = None,
) -> tuple[LocalFirstPhaseOneFlow, LocalFileDurableTruthRepository, MockAwsAdapter]:
    selected_adapter = adapter or MockAwsAdapter()
    store = LocalFileDurableTruthRepository(path)
    return (
        LocalFirstPhaseOneFlow(
            query_resource=QueryResource(selected_adapter),
            plan_remediation=PlanRemediation(),
            model_provider=model or MockModelProvider(),
            repository=store,
            clock=lambda: NOW,
            proposal_id_factory=ProposalIdFactory(),
            event_id_factory=generate_event_id,
        ),
        store,
        selected_adapter,
    )


def _query(resource_type: CloudResourceType, resource_id: str) -> ResourceQuery:
    return ResourceQuery(resource_type=resource_type, resource_id=resource_id)


def test_mandatory_flow_reaches_durable_pending_approval_without_aws_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    path = tmp_path / "state.json"
    flow, store, adapter = _flow(path)

    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.AWAITING_APPROVAL
    assert result.value.public_state is ExecutionState.PENDING
    assert result.value.approval_status is ApprovalStatus.PENDING_APPROVAL
    assert result.value.plan.proposal is not None
    assert result.value.plan.proposal.authorizes_execution is False
    proposal_hash = result.value.plan.proposal.proposal_hash

    reopened = LocalFileDurableTruthRepository(path)
    durable_run = reopened.get_run(RUN_ID)
    checkpoint = reopened.get_checkpoint(RUN_ID)
    assert durable_run is not None
    assert durable_run.state is WorkflowState.AWAITING_APPROVAL
    assert checkpoint is not None and checkpoint.remediation_proposal is not None
    assert checkpoint.remediation_proposal.proposal_hash == proposal_hash
    assert checkpoint.resource_evidence == result.value.evidence
    assert adapter.mutation_calls == adapter.network_calls == 0
    assert not hasattr(flow, "execute_remediation")
    assert store.get_run(RUN_ID) == durable_run


def test_reopened_flow_reconciles_same_pending_proposal(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    first_flow, _, _ = _flow(path)
    first = first_flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )
    second_flow, _, _ = _flow(path)

    second = second_flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )

    assert first.value is not None and first.value.plan.proposal is not None
    assert second.value is not None and second.value.plan.proposal is not None
    assert second.value.reconciled is True
    assert second.value.plan.proposal.proposal_hash == first.value.plan.proposal.proposal_hash


@pytest.mark.parametrize(
    ("failure", "failure_kind", "terminal_state", "failure_code", "retryable"),
    [
        (
            MockModelFailure.MALFORMED,
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            None,
            False,
        ),
        (
            MockModelFailure.EMPTY,
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            None,
            False,
        ),
        (
            MockModelFailure.TRUNCATED,
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            None,
            False,
        ),
        (
            MockModelFailure.INVALID_STRUCTURED,
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            None,
            False,
        ),
        (
            MockModelFailure.POLICY_INVALID,
            FailureKind.POLICY_DENIAL,
            WorkflowState.DENIED_BY_POLICY,
            None,
            False,
        ),
        (
            MockModelFailure.DENIED_ACTION,
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
            None,
            False,
        ),
        (
            MockModelFailure.PROVIDER_ERROR,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_FAILED",
            True,
        ),
        (
            MockModelFailure.TIMEOUT,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_TIMEOUT",
            False,
        ),
        (
            MockModelFailure.RETRYABLE_ERROR,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_RETRYABLE_FAILURE",
            True,
        ),
        (
            MockModelFailure.CONNECTION_FAILURE,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_RETRYABLE_FAILURE",
            True,
        ),
        (
            MockModelFailure.RATE_LIMIT,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_RETRYABLE_FAILURE",
            True,
        ),
        (
            MockModelFailure.NON_RETRYABLE_ERROR,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_NON_RETRYABLE_FAILURE",
            False,
        ),
        (
            MockModelFailure.MODEL_UNAVAILABLE,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_NON_RETRYABLE_FAILURE",
            False,
        ),
        (
            MockModelFailure.CONFIGURATION_ERROR,
            FailureKind.PROVIDER_FAILURE,
            WorkflowState.DEPENDENCY_UNAVAILABLE,
            "MODEL_PROVIDER_NON_RETRYABLE_FAILURE",
            False,
        ),
    ],
)
def test_model_failures_are_typed_terminal_and_create_no_proposal(
    tmp_path: Path,
    failure: MockModelFailure,
    failure_kind: FailureKind,
    terminal_state: WorkflowState,
    failure_code: str | None,
    retryable: bool,
) -> None:
    model = MockModelProvider(failure=failure)
    flow, store, adapter = _flow(
        tmp_path / "state.json",
        model=model,
    )

    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is failure_kind
    assert result.failure.retryable is retryable
    if failure_code is not None:
        assert result.failure.code == failure_code
    assert store.get_run(RUN_ID).state is terminal_state
    checkpoint = store.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    assert checkpoint.remediation_proposal is None
    assert adapter.mutation_calls == adapter.network_calls == 0
    assert model.plan_calls == 1


def test_unexpected_provider_exception_is_redacted_and_never_retried(tmp_path: Path) -> None:
    class UnexpectedProvider:
        def __init__(self) -> None:
            self.calls = 0

        def create_plan(self, _evidence: object) -> str:
            self.calls += 1
            raise RuntimeError("private-provider-exception-detail")

    provider = UnexpectedProvider()
    adapter = MockAwsAdapter()
    store = LocalFileDurableTruthRepository(tmp_path / "state.json")
    flow = LocalFirstPhaseOneFlow(
        query_resource=QueryResource(adapter),
        plan_remediation=PlanRemediation(),
        model_provider=provider,
        repository=store,
        clock=lambda: NOW,
        proposal_id_factory=ProposalIdFactory(),
        event_id_factory=generate_event_id,
    )

    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )

    assert result.failure is not None
    assert result.failure.code == "MODEL_PROVIDER_INVALID_FAILURE"
    assert result.failure.message == "Model provider failed outside its typed contract"
    assert "private-provider" not in result.failure.message
    assert provider.calls == 1
    assert adapter.mutation_calls == adapter.network_calls == 0


def test_missing_resource_never_becomes_empty_success(tmp_path: Path) -> None:
    flow, store, _ = _flow(tmp_path / "state.json")

    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, "eipalloc-0fedcba9876543210"),
    )

    assert result.status is ResultStatus.FAILURE
    assert result.value is None
    assert result.failure is not None
    assert result.failure.kind is FailureKind.NOT_FOUND
    assert store.get_run(RUN_ID).state is WorkflowState.AMBIGUOUS_RESULT
    assert store.get_checkpoint(RUN_ID) is None


def test_adapter_exception_becomes_typed_failure_without_mutation(tmp_path: Path) -> None:
    adapter = MockAwsAdapter(fail_operations=frozenset({"get_resource"}))
    flow, store, _ = _flow(tmp_path / "state.json", adapter=adapter)

    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )

    assert result.failure is not None
    assert result.failure.kind is FailureKind.TOOL_ADAPTER_FAILURE
    assert store.get_run(RUN_ID).state is WorkflowState.DEPENDENCY_UNAVAILABLE
    assert adapter.mutation_calls == adapter.network_calls == 0


def test_pending_approval_cannot_shortcut_to_success(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    flow, store, _ = _flow(path)
    result = flow.execute(
        _run(),
        _query(CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID),
    )
    assert result.value is not None
    pending = store.get_run(RUN_ID)
    assert pending is not None

    with pytest.raises((WorkflowTransitionError, StorageConflictError)):
        store.transition_run(
            pending.run_id,
            WorkflowState.SUCCESS_WITH_EVIDENCE,
            expected_state=WorkflowState.AWAITING_APPROVAL,
            expected_version=pending.version,
            updated_at=NOW,
        )
    assert LocalFileDurableTruthRepository(path).get_run(RUN_ID) == pending


def test_clean_and_recommendation_paths_finish_explicitly(tmp_path: Path) -> None:
    clean_flow, clean_store, clean_adapter = _flow(tmp_path / "clean.json")
    clean = clean_flow.execute(
        _run(),
        _query(CloudResourceType.EC2_INSTANCE, MOCK_CLEAN_INSTANCE_ID),
    )
    assert clean.value is not None
    assert clean.value.final_state is WorkflowState.NO_ACTION_REQUIRED
    assert clean.value.plan.disposition is PlanDisposition.NO_ACTION
    assert clean_store.get_run(RUN_ID).state is WorkflowState.NO_ACTION_REQUIRED

    recommendation_flow, recommendation_store, recommendation_adapter = _flow(
        tmp_path / "recommendation.json"
    )
    recommendation = recommendation_flow.execute(
        _run(),
        _query(CloudResourceType.EC2_INSTANCE, MOCK_UNTAGGED_INSTANCE_ID),
    )
    assert recommendation.value is not None
    assert recommendation.value.final_state is WorkflowState.RECOMMENDATION_ONLY
    assert (
        recommendation.value.plan.disposition
        is PlanDisposition.NON_EXECUTABLE_RECOMMENDATION
    )
    assert recommendation_store.get_run(RUN_ID).state is WorkflowState.RECOMMENDATION_ONLY
    assert clean_adapter.mutation_calls == recommendation_adapter.mutation_calls == 0
