import asyncio
import importlib.metadata
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from strands import Agent, tool
from strands.hooks.events import BeforeToolCallEvent
from strands.interrupt import Interrupt, InterruptException
from strands.interventions import Deny, Proceed
from strands.models import BedrockModel, Model
from strands.vended_interventions.hitl import HumanInTheLoop

from aioa_cloudops_agent.agent import (
    CURRENT_REGISTERED_TOOL_COUNT,
    FINAL_TOOL_CAP,
    PRIMARY_AGENT_COUNT,
    SYSTEM_PROMPT,
    create_bedrock_model,
    create_primary_agent,
)
from aioa_cloudops_agent.cloudops import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.config import BedrockSettings
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
    generate_correlation_id,
)

ROOT = Path(__file__).parents[2]
INSTANCE_ID = "i-0123456789abcdef0"
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")


class FakeModel(Model):
    def __init__(self) -> None:
        self.config: dict[str, Any] = {}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self.config)

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        if False:
            yield {}

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        if False:
            yield {}


class NonCallingEc2Client:
    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        raise AssertionError(f"unexpected provider call: {InstanceIds!r}")


class NonCallingCloudWatchClient:
    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        raise AssertionError(f"unexpected provider call: {kwargs!r}")


class FakeBotoSession:
    region_name = "eu-central-1"

    def __init__(self) -> None:
        self.client_calls: list[dict[str, object]] = []

    def client(self, **kwargs: object) -> SimpleNamespace:
        self.client_calls.append(kwargs)
        return SimpleNamespace(meta=SimpleNamespace(region_name=kwargs["region_name"]))


def _context(correlation_id: object) -> ExecutionContext:
    return ExecutionContext(
        correlation_id=correlation_id,
        idempotency_key="agent-test",
        state=ExecutionState.INIT,
        authority_gate=AuthorityGate.AUTO,
        budget=ExecutionBudget(max_turns=2, max_tokens=1_024),
    )


def _runtime() -> object:
    identity = InvestigationIdentity(
        run_id=generate_correlation_id(),
        trace_id=generate_correlation_id(),
        correlation_id=generate_correlation_id(),
    )
    return create_primary_agent(
        context=_context(identity.correlation_id),
        identity=identity,
        target=SandboxTarget(instance_id=INSTANCE_ID),
        ec2_client=NonCallingEc2Client(),
        cloudwatch_client=NonCallingCloudWatchClient(),
        proposal_id=PROPOSAL_ID,
        clock=lambda: datetime(2026, 8, 23, 10, 0, tzinfo=UTC),
        model=FakeModel(),
    )


def test_exact_strands_version_is_installed_and_pinned_with_otel() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert importlib.metadata.version("strands-agents") == "1.53.0"
    assert '"strands-agents[otel]==1.53.0"' in metadata


def test_required_current_strands_apis_are_importable() -> None:
    assert Agent is not None
    assert tool is not None
    assert BedrockModel is not None
    assert HumanInTheLoop is not None
    assert Interrupt is not None
    assert InterruptException is not None


def test_bedrock_provider_uses_explicit_region_model_and_bounds() -> None:
    session = FakeBotoSession()
    settings = BedrockSettings(max_output_tokens=256)

    model = create_bedrock_model(settings, boto_session=session)
    config = model.get_config()

    assert isinstance(model, BedrockModel)
    assert config["model_id"] == "eu.amazon.nova-2-lite-v1:0"
    assert config["max_tokens"] == 256
    assert config["temperature"] == 0.00001
    assert config["streaming"] is True
    assert session.client_calls[0]["service_name"] == "bedrock-runtime"
    assert session.client_calls[0]["region_name"] == "eu-central-1"
    client_config = session.client_calls[0]["config"]
    assert client_config.retries == {"mode": "standard", "total_max_attempts": 1}
    assert client_config.connect_timeout == 3
    assert client_config.read_timeout == 45
    assert client_config.ignore_configured_endpoint_urls is True


def test_factory_creates_exactly_one_primary_agent_and_five_canonical_tools() -> None:
    runtime = _runtime()

    assert isinstance(runtime.agent, Agent)
    assert PRIMARY_AGENT_COUNT == 1
    assert CURRENT_REGISTERED_TOOL_COUNT == 5
    assert FINAL_TOOL_CAP == 5
    assert runtime.registered_tool_names == (
        "inspect_instance",
        "read_utilization_metrics",
        "build_remediation_evidence",
        "stop_sandbox_instance",
        "verify_instance_state",
    )
    assert runtime.agent.tool_names == list(runtime.registered_tool_names)
    assert len(runtime.agent._intervention_registry.handlers) == 1
    assert runtime.agent._intervention_registry.handlers[0] is runtime.human_in_the_loop


def test_inspect_instance_tool_schema_is_nova_compatible_and_minimal() -> None:
    runtime = _runtime()
    schema = runtime.inspect_instance_tool.tool_spec["inputSchema"]["json"]

    assert schema == {
        "properties": {
            "instance_id": {
                "description": "Parameter instance_id",
                "type": "string",
            }
        },
        "required": ["instance_id"],
        "type": "object",
    }
    assert runtime.registered_tool_names == (
        "inspect_instance",
        "read_utilization_metrics",
        "build_remediation_evidence",
        "stop_sandbox_instance",
        "verify_instance_state",
    )


def test_bedrock_specific_tool_choice_formats_exact_registered_tool() -> None:
    session = FakeBotoSession()
    model = create_bedrock_model(BedrockSettings(max_output_tokens=256), boto_session=session)
    runtime = _runtime()

    request = model.format_request(
        messages=[{"role": "user", "content": [{"text": "Inspect the sandbox."}]}],
        tool_specs=[runtime.inspect_instance_tool.tool_spec],
        tool_choice={"tool": {"name": "inspect_instance"}},
    )

    assert request["toolConfig"]["toolChoice"] == {"tool": {"name": "inspect_instance"}}
    assert request["toolConfig"]["tools"] == [{"toolSpec": runtime.inspect_instance_tool.tool_spec}]


def test_phase_1_tag_remains_at_frozen_commit() -> None:
    result = subprocess.run(
        ["git", "rev-list", "-n", "1", "phase1-foundation-green"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "ced6e2a180dd50a1f43d4037bb8db5f4dc792657"


def test_native_hitl_allows_inspection_and_denies_malformed_mutation() -> None:
    runtime = _runtime()
    inspection_event = BeforeToolCallEvent(
        agent=runtime.agent,
        selected_tool=runtime.inspect_instance_tool,
        tool_use={
            "toolUseId": "inspect-1",
            "name": "inspect_instance",
            "input": {"instance_id": INSTANCE_ID},
        },
        invocation_state={},
    )
    mutation_event = BeforeToolCallEvent(
        agent=runtime.agent,
        selected_tool=None,
        tool_use={
            "toolUseId": "stop-1",
            "name": "stop_sandbox_instance",
            "input": {"instance_id": INSTANCE_ID},
        },
        invocation_state={},
    )

    inspection_action = asyncio.run(runtime.human_in_the_loop.before_tool_call(inspection_event))
    mutation_action = asyncio.run(runtime.human_in_the_loop.before_tool_call(mutation_event))

    assert isinstance(inspection_action, Proceed)
    assert isinstance(mutation_action, Deny)
    assert "schema rejected" in mutation_action.reason.casefold()


def test_hitl_does_not_use_wildcard_or_session_trust() -> None:
    runtime = _runtime()

    assert runtime.human_in_the_loop._allowed_tools == {
        "inspect_instance",
        "read_utilization_metrics",
        "build_remediation_evidence",
        "verify_instance_state",
    }
    assert "*" not in runtime.human_in_the_loop._allowed_tools
    assert runtime.human_in_the_loop._enable_trust is False
    assert runtime.human_in_the_loop._ask is None


def test_system_prompt_keeps_model_subordinate_to_tools_and_authority() -> None:
    normalized = SYSTEM_PROMPT.casefold()

    assert "model output is not execution authority" in normalized
    assert "registered tools" in normalized
    assert "do not guess" in normalized
    assert "never claim a mutation completed" in normalized
    assert "native human confirmation" in normalized
    assert "never model text" in normalized
