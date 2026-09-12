import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from strands.models import Model

from aioa_cloudops_agent.agent import BoundedInvestigationFlow, create_primary_agent
from aioa_cloudops_agent.cloudops import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    ActionProposal,
    AuditEvent,
    AuditEventType,
    BudgetCounters,
    Capability,
    FailureKind,
    ResultStatus,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository

INSTANCE_ID = "i-0123456789abcdef0"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVENT_IDS = tuple(UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{value:02x}") for value in range(64, 96))
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
CANONICAL_PLAN = (
    ("inspect_instance", {"instance_id": INSTANCE_ID}),
    ("read_utilization_metrics", {"instance_id": INSTANCE_ID}),
    ("build_remediation_evidence", {"instance_id": INSTANCE_ID}),
)


class ScriptedInvestigationModel(Model):
    """Deterministic model that still exercises the native Strands tool loop."""

    def __init__(
        self,
        plan: tuple[tuple[str, dict[str, object]], ...] = CANONICAL_PLAN,
    ) -> None:
        self.plan = plan
        self.calls = 0
        self.tool_specs_seen: list[tuple[str, ...]] = []
        self.config: dict[str, object] = {}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        if False:
            yield {}

    async def stream(
        self,
        messages: object,
        tool_specs: list[dict[str, object]] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        self.calls += 1
        names = tuple(spec["name"] for spec in (tool_specs or []))
        self.tool_specs_seen.append(names)
        yield {"messageStart": {"role": "assistant"}}
        if self.calls <= len(self.plan):
            name, tool_input = self.plan[self.calls - 1]
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": f"tool-{self.calls}",
                            "name": name,
                        }
                    },
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": json.dumps(tool_input)}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            final_text = (
                f"run_id={RUN_ID} trace_id={TRACE_ID} correlation_id={CORRELATION_ID} "
                f"proposal_id={PROPOSAL_ID}; no approval or mutation."
            )
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"text": final_text},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                "metrics": {"latencyMs": 1},
            }
        }


class FakeEc2Client:
    def __init__(self, *, sandbox_tag_value: str = "true") -> None:
        self.sandbox_tag_value = sandbox_tag_value
        self.calls: list[list[str]] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        self.calls.append(InstanceIds)
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE_ID,
                            "State": {"Name": "running"},
                            "InstanceType": "t3.micro",
                            "LaunchTime": NOW - timedelta(hours=2),
                            "Monitoring": {"State": "disabled"},
                            "Placement": {"AvailabilityZone": "eu-central-1a"},
                            "Tags": [
                                {
                                    "Key": "AIOACloudOpsSandbox",
                                    "Value": self.sandbox_tag_value,
                                }
                            ],
                        }
                    ]
                }
            ]
        }


class FakeCloudWatchClient:
    def __init__(
        self,
        values: tuple[float, ...],
        response: dict[str, object] | None = None,
    ) -> None:
        self.values = values
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        if self.response is not None:
            return self.response
        return {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5 * (index + 1)),
                    "Average": value,
                    "Unit": "Percent",
                }
                for index, value in enumerate(self.values)
            ]
        }


class RecordingRepository(InMemoryTestDurableTruthRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[AuditEvent] = []
        self.proposal_creates = 0
        self.operations: list[str] = []

    def transition_run(
        self,
        run_id: UUID,
        next_state: WorkflowState,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        updated_at: datetime,
        approval_proposal_id: UUID | None = None,
        verification_proposal_id: UUID | None = None,
    ) -> Run:
        self.operations.append(f"transition:{next_state.value}")
        return super().transition_run(
            run_id,
            next_state,
            expected_state=expected_state,
            expected_version=expected_version,
            updated_at=updated_at,
            approval_proposal_id=approval_proposal_id,
            verification_proposal_id=verification_proposal_id,
        )

    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        self.proposal_creates += 1
        self.operations.append("create_proposal")
        return super().create_proposal(proposal)

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return super().append_audit_event(event)


class ProposalFailingRepository(RecordingRepository):
    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        self.proposal_creates += 1
        self.operations.append("create_proposal")
        raise StorageDependencyError("synthetic DynamoDB outage")


class EventIdFactory:
    def __init__(self) -> None:
        self.index = 0

    def __call__(self) -> UUID:
        value = EVENT_IDS[self.index]
        self.index += 1
        return value


def _run(
    *,
    max_turns: int = 8,
    max_tokens: int = 8_192,
    max_elapsed_seconds: int = 60,
) -> Run:
    return Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key="request:idle-ec2:0001",
        created_at=NOW,
        budget=BudgetCounters(
            max_turns=max_turns,
            max_tokens=max_tokens,
            max_elapsed_seconds=max_elapsed_seconds,
        ),
    )


def _flow(
    *,
    values: tuple[float, ...] = (1, 2, 3, 4, 5, 6),
    model: ScriptedInvestigationModel | None = None,
    ec2_client: FakeEc2Client | None = None,
    repository: RecordingRepository | None = None,
    monotonic: Callable[[], float] | None = None,
    cloudwatch_response: dict[str, object] | None = None,
) -> tuple[
    BoundedInvestigationFlow,
    object,
    ScriptedInvestigationModel,
    FakeEc2Client,
    FakeCloudWatchClient,
    RecordingRepository,
]:
    actual_model = model or ScriptedInvestigationModel()
    actual_ec2 = ec2_client or FakeEc2Client()
    cloudwatch = FakeCloudWatchClient(values, cloudwatch_response)
    actual_repository = repository or RecordingRepository()
    identity = InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:0001",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=identity,
        target=SandboxTarget(instance_id=INSTANCE_ID),
        ec2_client=actual_ec2,
        cloudwatch_client=cloudwatch,
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
        model=actual_model,
        durable_repository=actual_repository,
    )
    flow_kwargs: dict[str, object] = {
        "clock": lambda: NOW,
        "event_id_factory": EventIdFactory(),
    }
    if monotonic is not None:
        flow_kwargs["monotonic"] = monotonic
    flow = BoundedInvestigationFlow(runtime, actual_repository, **flow_kwargs)
    return flow, runtime, actual_model, actual_ec2, cloudwatch, actual_repository


def test_strands_happy_path_persists_evidence_backed_non_authorizing_proposal() -> None:
    flow, runtime, model, ec2, cloudwatch, repository = _flow()

    result = flow.execute(_run())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.REMEDIATION_PROPOSED
    assert result.value.proposal.action is Capability.STOP_SANDBOX_INSTANCE
    assert result.value.proposal.authority is AuthorityGate.PLAN_AND_CONFIRM
    assert result.value.proposal.authorizes_execution is False
    assert repository.get_run(RUN_ID).state is WorkflowState.REMEDIATION_PROPOSED
    assert repository.get_proposal(PROPOSAL_ID) == result.value.proposal
    assert repository.get_approval(PROPOSAL_ID) is None
    assert repository.get_checkpoint(RUN_ID).last_safe_state is (WorkflowState.REMEDIATION_PROPOSED)
    assert repository.proposal_creates == 1
    assert repository.operations.index("create_proposal") < repository.operations.index(
        "transition:REMEDIATION_PROPOSED"
    )
    assert model.calls == 4
    assert runtime.tool_context.tool_calls == list(CANONICAL_PLAN_NAMES)
    assert all(names == runtime.registered_tool_names for names in model.tool_specs_seen)
    assert ec2.calls == [[INSTANCE_ID]]
    assert len(cloudwatch.calls) == 1
    assert cloudwatch.calls[0]["Dimensions"] == [{"Name": "InstanceId", "Value": INSTANCE_ID}]
    assert "proposal_id=" in result.value.agent_summary
    assert "human approval is still absent" in result.value.agent_summary
    assert "proposal_id=" in runtime.agent.messages[-1]["content"][0]["text"]


def test_busy_instance_ends_denied_by_policy_without_proposal() -> None:
    flow, _, _, _, _, repository = _flow(values=(20, 21, 22, 23, 24, 25))

    result = flow.execute(_run())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.POLICY_DENIAL
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_POLICY
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert repository.proposal_creates == 0


def test_missing_metrics_end_ambiguous_without_proposal() -> None:
    flow, _, _, _, _, repository = _flow(values=())

    result = flow.execute(_run())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
    assert repository.get_run(RUN_ID).state is WorkflowState.AMBIGUOUS_RESULT
    assert repository.get_proposal(PROPOSAL_ID) is None


@pytest.mark.parametrize(
    "response",
    [
        {"Datapoints": []},
        {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5),
                    "Unit": "Percent",
                }
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(hours=2),
                    "Average": 0.0,
                    "Unit": "Percent",
                }
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5),
                    "Average": 0.0,
                    "Unit": "Percent",
                },
                {
                    "Timestamp": NOW - timedelta(minutes=10),
                    "Average": 0.0,
                    "Unit": "Bytes",
                },
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5),
                    "Average": 0.0,
                    "Unit": "Percent",
                },
                {
                    "Timestamp": NOW - timedelta(minutes=5),
                    "Average": 99.0,
                    "Unit": "Percent",
                },
            ]
        },
    ],
    ids=("empty", "missing-average", "stale", "mixed-units", "contradictory"),
)
def test_ambiguous_cloudwatch_evidence_never_creates_idle_proposal(
    response: dict[str, object],
) -> None:
    flow, runtime, _, _, _, repository = _flow(cloudwatch_response=response)

    result = flow.execute(_run())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
    assert result.failure.code in {"EVIDENCE_AMBIGUOUS", "METRIC_EVIDENCE_INVALID"}
    assert any(
        reason in result.failure.message.casefold()
        for reason in (
            "ambiguous",
            "duplicate",
            "malformed",
            "missing",
            "outside",
            "unit",
        )
    )
    assert repository.get_run(RUN_ID).state is WorkflowState.AMBIGUOUS_RESULT
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert repository.proposal_creates == 0
    utilization = runtime.tool_context.utilization()
    if utilization is not None:
        assert utilization.classification.value == "AMBIGUOUS"
        assert utilization.average_cpu_percent is None


def test_sandbox_tag_failure_stops_cloudwatch_and_denies_policy() -> None:
    flow, _, _, _, cloudwatch, repository = _flow(
        ec2_client=FakeEc2Client(sandbox_tag_value="false")
    )

    result = flow.execute(_run())

    assert result.failure is not None
    assert result.failure.kind is FailureKind.POLICY_DENIAL
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_POLICY
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert cloudwatch.calls == []


def test_durable_proposal_failure_fails_closed_without_claiming_completion() -> None:
    repository = ProposalFailingRepository()
    flow, runtime, _, _, _, _ = _flow(repository=repository)

    result = flow.execute(_run())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert repository.get_run(RUN_ID).state is WorkflowState.DEPENDENCY_UNAVAILABLE
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert repository.get_approval(PROPOSAL_ID) is None
    assert runtime.tool_context.evidence().proposal.authorizes_execution is False


@pytest.mark.parametrize(
    ("plan", "expected_kind", "expected_state"),
    [
        (
            (("inspect_instance", {"instance_id": INSTANCE_ID, "region": "us-east-1"}),),
            FailureKind.POLICY_DENIAL,
            WorkflowState.DENIED_BY_POLICY,
        ),
        (
            (("stop_sandbox_instance", {"instance_id": INSTANCE_ID}),),
            FailureKind.VALIDATION_FAILURE,
            WorkflowState.MODEL_OUTPUT_INVALID,
        ),
        (
            (("terminate_instances", {"instance_id": INSTANCE_ID}),),
            FailureKind.POLICY_DENIAL,
            WorkflowState.DENIED_BY_POLICY,
        ),
    ],
)
def test_malformed_or_mutating_model_requests_cannot_create_proposal(
    plan: tuple[tuple[str, dict[str, object]], ...],
    expected_kind: FailureKind,
    expected_state: WorkflowState,
) -> None:
    flow, runtime, _, _, _, repository = _flow(model=ScriptedInvestigationModel(plan=plan))

    result = flow.execute(_run())

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is expected_kind
    assert repository.get_run(RUN_ID).state is expected_state
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert "stop_sandbox_instance" in runtime.registered_tool_names
    assert "terminate_instances" not in runtime.registered_tool_names


def test_duplicate_request_reconciles_one_compatible_durable_proposal() -> None:
    flow, _, model, _, _, repository = _flow()
    run = _run()

    first = flow.execute(run)
    duplicate = flow.execute(run)

    assert first.status is ResultStatus.SUCCESS
    assert duplicate.status is ResultStatus.SUCCESS
    assert duplicate.value is not None
    assert duplicate.value.reconciled is True
    assert duplicate.value.proposal == first.value.proposal
    assert repository.proposal_creates == 1
    assert model.calls == 4


def test_trace_identity_and_evidence_hash_propagate_through_audit_and_checkpoint() -> None:
    flow, _, _, _, _, repository = _flow()

    result = flow.execute(_run())

    assert result.value is not None
    assert result.value.evidence is not None
    assert result.value.run_id == RUN_ID
    assert result.value.trace_id == TRACE_ID
    assert result.value.correlation_id == CORRELATION_ID
    assert result.value.proposal.evidence_hash == result.value.evidence.evidence_hash
    assert all(event.run_id == RUN_ID for event in repository.events)
    assert all(event.metadata["trace_id"] == str(TRACE_ID) for event in repository.events)
    assert all(
        event.metadata["correlation_id"] == str(CORRELATION_ID) for event in repository.events
    )
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint.tool_result_hashes["build_remediation_evidence"] == (
        result.value.evidence.evidence_hash
    )


def test_agent_turn_budget_exhaustion_persists_failure_and_no_proposal() -> None:
    flow, runtime, model, _, cloudwatch, repository = _flow()

    result = flow.execute(_run(max_turns=1))

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.BUDGET_EXHAUSTION
    assert repository.get_run(RUN_ID).state is WorkflowState.BUDGET_EXHAUSTED
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert runtime.tool_context.tool_calls == ["inspect_instance"]
    assert model.calls == 1
    assert cloudwatch.calls == []


def test_agent_token_budget_exhaustion_persists_failure_and_no_proposal() -> None:
    flow, runtime, model, _, cloudwatch, repository = _flow()

    result = flow.execute(_run(max_tokens=10))

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.BUDGET_EXHAUSTION
    assert repository.get_run(RUN_ID).state is WorkflowState.BUDGET_EXHAUSTED
    assert repository.get_run(RUN_ID).budget.tokens_used == 10
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert runtime.tool_context.tool_calls == ["inspect_instance"]
    assert model.calls == 1
    assert cloudwatch.calls == []


def test_flow_exposes_canonical_tools_without_mutation_clients() -> None:
    _, runtime, _, ec2, cloudwatch, _ = _flow()

    assert runtime.registered_tool_names == (
        *CANONICAL_PLAN_NAMES,
        "stop_sandbox_instance",
        "verify_instance_state",
    )
    for name in (
        "terminate_instances",
        "shell",
    ):
        assert name not in runtime.registered_tool_names
    for client in (ec2, cloudwatch):
        assert not hasattr(client, "stop_instances")
        assert not hasattr(client, "terminate_instances")
        assert not hasattr(client, "put_metric_data")


def test_denied_injection_is_linked_and_redacted_before_dispatch() -> None:
    malicious_value = "sensitive-session-redaction-marker"
    plan = (("terminate_instances", {"payload": malicious_value}),)
    flow, runtime, _, ec2, cloudwatch, repository = _flow(
        model=ScriptedInvestigationModel(plan=plan)
    )

    result = flow.execute(_run())

    assert result.failure is not None
    assert result.failure.kind is FailureKind.POLICY_DENIAL
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_POLICY
    assert repository.get_approval(PROPOSAL_ID) is None
    assert runtime.human_in_the_loop.denial_count == 1
    denial = next(
        event for event in repository.events if event.type is AuditEventType.POLICY_DENIED
    )
    assert denial.run_id == RUN_ID
    assert denial.metadata["trace_id"] == str(TRACE_ID)
    assert denial.metadata["correlation_id"] == str(CORRELATION_ID)
    assert denial.metadata["policy_code"] == "NEVER_AUTONOMOUS_DENIED"
    assert denial.tool_name == Capability.TERMINATE_INSTANCES.value
    assert malicious_value not in json.dumps(denial.model_dump(mode="json"))
    assert ec2.calls == []
    assert cloudwatch.calls == []


def test_policy_denial_closes_the_invocation_before_later_safe_looking_tools() -> None:
    plan = (
        ("terminate_instances", {"instance_id": INSTANCE_ID}),
        *CANONICAL_PLAN,
    )
    flow, runtime, _, ec2, cloudwatch, repository = _flow(
        model=ScriptedInvestigationModel(plan=plan)
    )

    result = flow.execute(_run())

    assert result.failure is not None
    assert result.failure.kind is FailureKind.POLICY_DENIAL
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_POLICY
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert runtime.tool_context.tool_calls == []
    assert runtime.human_in_the_loop.denial_count == 4
    assert ec2.calls == []
    assert cloudwatch.calls == []


def test_repeated_malformed_tool_payload_exhausts_schema_correction_budget() -> None:
    plan = (
        ("stop_sandbox_instance", {"instance_id": INSTANCE_ID}),
        ("stop_sandbox_instance", {"instance_id": INSTANCE_ID}),
    )
    flow, runtime, _, ec2, cloudwatch, repository = _flow(
        model=ScriptedInvestigationModel(plan=plan)
    )

    result = flow.execute(_run())

    assert result.failure is not None
    assert result.failure.kind is FailureKind.VALIDATION_FAILURE
    assert result.failure.code == "MODEL_OUTPUT_INVALID"
    assert result.failure.retryable is False
    assert repository.get_run(RUN_ID).state is WorkflowState.MODEL_OUTPUT_INVALID
    assert runtime.human_in_the_loop.denial_count == 2
    assert (
        sum(event.type is AuditEventType.MODEL_OUTPUT_REJECTED for event in repository.events) == 2
    )
    assert ec2.calls == []
    assert cloudwatch.calls == []


def test_one_schema_correction_can_recover_only_to_the_exact_safe_tool_sequence() -> None:
    plan = (
        ("stop_sandbox_instance", {"instance_id": INSTANCE_ID}),
        *CANONICAL_PLAN,
    )
    flow, runtime, _, ec2, cloudwatch, repository = _flow(
        model=ScriptedInvestigationModel(plan=plan)
    )

    result = flow.execute(_run())

    assert result.status is ResultStatus.SUCCESS
    assert repository.get_run(RUN_ID).state is WorkflowState.REMEDIATION_PROPOSED
    assert runtime.tool_context.tool_calls == list(CANONICAL_PLAN_NAMES)
    assert runtime.human_in_the_loop.denial_count == 1
    assert ec2.calls == [[INSTANCE_ID]]
    assert len(cloudwatch.calls) == 1


class MonotonicSequence:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def test_elapsed_time_budget_is_persisted_and_audited_before_any_proposal() -> None:
    flow, runtime, _, _, _, repository = _flow(monotonic=MonotonicSequence(0.0, 2.0))

    result = flow.execute(_run(max_elapsed_seconds=1))

    assert result.failure is not None
    assert result.failure.kind is FailureKind.BUDGET_EXHAUSTION
    durable_run = repository.get_run(RUN_ID)
    assert durable_run is not None
    assert durable_run.state is WorkflowState.BUDGET_EXHAUSTED
    assert durable_run.budget.elapsed_milliseconds_used == 1_000
    assert repository.get_proposal(PROPOSAL_ID) is None
    assert repository.get_approval(PROPOSAL_ID) is None
    assert AuditEventType.BUDGET_UPDATED in {event.type for event in repository.events}
    assert AuditEventType.BUDGET_EXHAUSTED in {event.type for event in repository.events}
    assert runtime.registered_tool_names == (
        *CANONICAL_PLAN_NAMES,
        "stop_sandbox_instance",
        "verify_instance_state",
    )


CANONICAL_PLAN_NAMES = tuple(name for name, _ in CANONICAL_PLAN)
