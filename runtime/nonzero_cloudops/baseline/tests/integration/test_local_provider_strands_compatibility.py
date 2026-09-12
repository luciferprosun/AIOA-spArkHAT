from datetime import UTC, datetime
from uuid import UUID

from aioa_cloudops_agent.agent import BoundedInvestigationFlow, create_primary_agent
from aioa_cloudops_agent.cloudops import (
    MOCK_CLEAN_INSTANCE_ID,
    InvestigationIdentity,
    MockAwsAdapter,
    SandboxTarget,
)
from aioa_cloudops_agent.config import ModelProviderName
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    ResultStatus,
    Run,
    WorkflowState,
    generate_event_id,
)
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.providers import MockModelProvider, MockToolCall

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
NOW = datetime(2026, 8, 26, 10, 0, tzinfo=UTC)


def test_local_providers_drive_existing_canonical_strands_path() -> None:
    run = Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="local/strands/0001",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
    )
    adapter = MockAwsAdapter()
    model = MockModelProvider(
        tool_plan=(
            MockToolCall("inspect_instance", {"instance_id": MOCK_CLEAN_INSTANCE_ID}),
            MockToolCall(
                "read_utilization_metrics",
                {"instance_id": MOCK_CLEAN_INSTANCE_ID},
            ),
            MockToolCall(
                "build_remediation_evidence",
                {"instance_id": MOCK_CLEAN_INSTANCE_ID},
            ),
        )
    )
    repository = InMemoryTestDurableTruthRepository()
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key="local/strands/0001",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=InvestigationIdentity.from_run(run),
        target=SandboxTarget(instance_id=MOCK_CLEAN_INSTANCE_ID),
        ec2_client=adapter,
        cloudwatch_client=adapter,
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
        model=model,
        durable_repository=repository,
    )

    result = BoundedInvestigationFlow(
        runtime,
        repository,
        clock=lambda: NOW,
        event_id_factory=generate_event_id,
    ).execute(run)

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.REMEDIATION_PROPOSED
    assert result.value.proposal.authorizes_execution is False
    assert runtime.model_settings.provider_name is ModelProviderName.MOCK
    assert runtime.model_settings.model is model
    assert runtime.model_settings.aws_calls_allowed is False
    assert model.calls == 4
    assert adapter.sdk_compatible_calls == [
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
    ]
    assert adapter.network_calls == adapter.mutation_calls == 0
