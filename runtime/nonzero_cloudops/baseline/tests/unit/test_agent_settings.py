import pytest

from aioa_cloudops_agent.config import (
    DETERMINISTIC_TEMPERATURE_POLICY,
    NOVA_2_LITE_MAX_TEMPERATURE,
    NOVA_2_LITE_MIN_TEMPERATURE,
    AwsSettings,
    BedrockSettings,
    get_bedrock_model_capabilities,
)
from aioa_cloudops_agent.domain import ContractValidationError


def test_bedrock_settings_use_explicit_nova_candidate_defaults() -> None:
    settings = BedrockSettings()

    assert settings.model_id == "eu.amazon.nova-2-lite-v1:0"
    assert settings.region == "eu-central-1"
    assert settings.max_output_tokens == 1_024
    assert settings.temperature == 0.00001
    assert DETERMINISTIC_TEMPERATURE_POLICY == "LOWEST_MODEL_SUPPORTED_TEMPERATURE"


def test_nova_2_lite_capabilities_are_model_specific() -> None:
    capabilities = get_bedrock_model_capabilities("eu.amazon.nova-2-lite-v1:0")

    assert capabilities.model_id == "eu.amazon.nova-2-lite-v1:0"
    assert capabilities.minimum_temperature == NOVA_2_LITE_MIN_TEMPERATURE
    assert capabilities.maximum_temperature == NOVA_2_LITE_MAX_TEMPERATURE


def test_nova_2_lite_accepts_lowest_supported_temperature() -> None:
    settings = BedrockSettings(temperature=0.00001)

    assert settings.temperature == 0.00001


@pytest.mark.parametrize("temperature", [0, -0.1, 0.000001, 1.00001, 2])
def test_nova_2_lite_rejects_temperature_outside_supported_range(
    temperature: float,
) -> None:
    with pytest.raises(ContractValidationError, match="supported range"):
        BedrockSettings(temperature=temperature)


def test_supported_but_noncanonical_temperature_is_rejected_by_policy() -> None:
    with pytest.raises(ContractValidationError, match="lowest model-supported"):
        BedrockSettings(temperature=0.1)


def test_unknown_model_does_not_inherit_nova_temperature_constraints() -> None:
    with pytest.raises(ContractValidationError, match="model_id is not supported"):
        BedrockSettings(model_id="another.provider-model-v1", temperature=0.00001)


def test_bedrock_settings_are_environment_configurable_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("BEDROCK_REGION", "eu-central-1")
    monkeypatch.setenv("MODEL_MAX_OUTPUT_TOKENS", "256")

    settings = BedrockSettings.from_environment()

    assert settings.model_id == "eu.amazon.nova-2-lite-v1:0"
    assert settings.max_output_tokens == 256


@pytest.mark.parametrize(
    "overrides",
    [
        {"model_id": ""},
        {"model_id": " anthropic.claude-3-haiku-20240307-v1:0"},
        {"region": "us-east-1"},
        {"max_output_tokens": 0},
        {"max_output_tokens": 1_025},
        {"max_output_tokens": True},
        {"temperature": True},
    ],
)
def test_invalid_bedrock_settings_fail_explicitly(overrides: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        BedrockSettings(**overrides)


def test_malformed_environment_token_cap_fails_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MODEL_MAX_OUTPUT_TOKENS", "not-an-integer")

    with pytest.raises(ContractValidationError, match="positive integer"):
        BedrockSettings.from_environment()


def test_no_claude_haiku_fallback_is_encoded() -> None:
    settings = BedrockSettings()

    assert "claude" not in settings.model_id.casefold()
    assert "haiku" not in settings.model_id.casefold()


def test_model_region_tokens_and_mutation_default_remain_frozen() -> None:
    bedrock = BedrockSettings()
    aws = AwsSettings()

    assert bedrock.model_id == "eu.amazon.nova-2-lite-v1:0"
    assert bedrock.region == "eu-central-1"
    assert bedrock.max_output_tokens <= 1_024
    assert aws.aws_mutations_enabled is False
