import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from strands import Agent
from strands.models import Model

from aioa_cloudops_agent.agent import create_primary_agent
from aioa_cloudops_agent.cloudops import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.config import (
    BedrockSettings,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.config.runtime import PORTABLE_MODEL_ID
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ContractValidationError,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.providers import (
    MockModelProvider,
    ModelProviderUnavailableError,
    create_model_provider,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
NOW = datetime(2026, 9, 1, 1, 0, tzinfo=UTC)
ROOT = Path(__file__).parents[2]


class InjectedModel(Model):
    def __init__(self) -> None:
        self.config: dict[str, object] = {}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    async def stream(self, *_args: Any, **_kwargs: Any) -> Any:
        if False:
            yield {}

    async def structured_output(self, *_args: Any, **_kwargs: Any) -> Any:
        if False:
            yield {}


class NonCallingEc2Client:
    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        raise AssertionError(f"unexpected provider call: {InstanceIds!r}")


class NonCallingCloudWatchClient:
    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        raise AssertionError(f"unexpected provider call: {kwargs!r}")


def _aws_settings() -> RuntimeSettings:
    return RuntimeSettings(
        mode=RuntimeMode.AWS,
        model_provider=ModelProviderName.BEDROCK,
        aws_integration_enabled=True,
        bedrock=BedrockSettings(),
    )


def test_factory_defaults_to_deterministic_non_network_strands_model() -> None:
    runtime = create_model_provider()

    assert isinstance(runtime.model, MockModelProvider)
    assert isinstance(runtime.model, Model)
    assert runtime.provider_name is ModelProviderName.MOCK
    assert runtime.model_id == PORTABLE_MODEL_ID
    assert runtime.external_network_allowed is False
    assert runtime.aws_calls_allowed is False


def test_portable_provider_never_loads_unavailable_bedrock_factory() -> None:
    calls = 0

    def unavailable(*_args: object, **_kwargs: object) -> Model:
        nonlocal calls
        calls += 1
        raise AssertionError("AWS provider factory must not be reached")

    runtime = create_model_provider(bedrock_factory=unavailable)

    assert runtime.provider_name is ModelProviderName.MOCK
    assert calls == 0


def test_explicit_aws_provider_failure_is_typed_and_redacted() -> None:
    private_detail = "private-provider-token-value"

    def unavailable(*_args: object, **_kwargs: object) -> Model:
        raise RuntimeError(private_detail)

    with pytest.raises(ModelProviderUnavailableError) as captured:
        create_model_provider(_aws_settings(), bedrock_factory=unavailable)

    assert str(captured.value) == "selected model provider could not be initialized"
    assert private_detail not in str(captured.value)


def test_aws_provider_requires_valid_strands_model_result() -> None:
    def invalid(*_args: object, **_kwargs: object) -> object:
        return object()

    with pytest.raises(ModelProviderUnavailableError, match="invalid runtime"):
        create_model_provider(_aws_settings(), bedrock_factory=invalid)  # type: ignore[arg-type]


def test_model_override_is_bound_to_explicit_selection_without_factory_call() -> None:
    model = InjectedModel()
    runtime = create_model_provider(_aws_settings(), model_override=model)

    assert runtime.model is model
    assert runtime.provider_name is ModelProviderName.BEDROCK
    assert runtime.model_id == BedrockSettings().model_id
    assert runtime.external_network_allowed is True
    assert runtime.aws_calls_allowed is True


def test_canonical_agent_defaults_to_portable_strands_provider_without_aws() -> None:
    identity = InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key="portable/provider/default",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=2_048),
        ),
        identity=identity,
        target=SandboxTarget(instance_id="i-0123456789abcdef0"),
        ec2_client=NonCallingEc2Client(),
        cloudwatch_client=NonCallingCloudWatchClient(),
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
    )

    assert isinstance(runtime.agent, Agent)
    assert runtime.model_settings.provider_name is ModelProviderName.MOCK
    assert runtime.model_settings.model_id == PORTABLE_MODEL_ID
    assert isinstance(runtime.model_settings.model, MockModelProvider)
    assert runtime.model_settings.aws_calls_allowed is False
    assert runtime.registered_tool_names == (
        "inspect_instance",
        "read_utilization_metrics",
        "build_remediation_evidence",
        "stop_sandbox_instance",
        "verify_instance_state",
    )


def test_factory_rejects_ambiguous_override_and_session_types() -> None:
    with pytest.raises(ContractValidationError, match="model_override"):
        create_model_provider(model_override=object())  # type: ignore[arg-type]
    with pytest.raises(ContractValidationError, match="does not accept an AWS session"):
        create_model_provider(boto_session=object())


def test_invalid_provider_name_is_rejected_without_echoing_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_value = "private-provider-selection-value"
    monkeypatch.setenv("AIOA_RUNTIME_MODE", "portable")
    monkeypatch.setenv("AIOA_MODEL_PROVIDER", private_value)
    monkeypatch.setenv("AIOA_AWS_INTEGRATION_ENABLED", "false")

    with pytest.raises(ContractValidationError) as captured:
        RuntimeSettings.from_environment()

    assert str(captured.value) == "AIOA_MODEL_PROVIDER must be mock or bedrock"
    assert private_value not in str(captured.value)


def test_portable_agent_modules_have_no_top_level_aws_client_construction_import() -> None:
    forbidden_modules = {
        "aioa_cloudops_agent.aws_clients",
        "boto3",
        "botocore",
        "botocore.config",
    }
    for relative in (
        "src/aioa_cloudops_agent/agent/factory.py",
        "src/aioa_cloudops_agent/providers/factory.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        top_level_modules = {
            node.module
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        top_level_modules.update(
            alias.name
            for node in tree.body
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert top_level_modules.isdisjoint(forbidden_modules)
