import pytest

from aioa_cloudops_agent.config import AwsSettings, CostGuardrails, DynamoDbBillingMode
from aioa_cloudops_agent.domain import ContractValidationError


def test_aws_settings_use_canonical_safe_defaults() -> None:
    settings = AwsSettings()

    assert settings.region == "eu-central-1"
    assert settings.stage == "hackathon"
    assert settings.model_max_output_tokens == 1_024
    assert settings.cloudwatch_retention_days == 3
    assert settings.dynamodb_billing_mode is DynamoDbBillingMode.PAY_PER_REQUEST
    assert settings.aws_mutations_enabled is False


@pytest.mark.parametrize("region", [None, "", "us-east-1", "eu-west-1"])
def test_unsupported_region_is_rejected(region: object) -> None:
    with pytest.raises(ContractValidationError, match="region must be eu-central-1"):
        AwsSettings(region=region)


@pytest.mark.parametrize("stage", [None, "", "Hackathon", "hackathon_dev", "a" * 33])
def test_malformed_stage_is_rejected(stage: object) -> None:
    with pytest.raises(ContractValidationError, match="stage"):
        AwsSettings(stage=stage)


@pytest.mark.parametrize("token_cap", [None, True, 0, -1, 1_025])
def test_invalid_model_token_cap_is_rejected(token_cap: object) -> None:
    with pytest.raises(ContractValidationError, match="model_max_output_tokens"):
        AwsSettings(model_max_output_tokens=token_cap)


def test_canonical_model_token_cap_is_accepted() -> None:
    assert AwsSettings(model_max_output_tokens=1_024).model_max_output_tokens == 1_024


@pytest.mark.parametrize("retention_days", [None, True, 0, 1, 7])
def test_invalid_log_retention_is_rejected(retention_days: object) -> None:
    with pytest.raises(ContractValidationError, match="cloudwatch_retention_days"):
        AwsSettings(cloudwatch_retention_days=retention_days)


def test_dynamodb_pay_per_request_is_accepted() -> None:
    settings = AwsSettings(dynamodb_billing_mode=DynamoDbBillingMode.PAY_PER_REQUEST)

    assert settings.dynamodb_billing_mode is DynamoDbBillingMode.PAY_PER_REQUEST


@pytest.mark.parametrize("billing_mode", [None, "PAY_PER_REQUEST", "PROVISIONED"])
def test_untyped_or_unsupported_billing_mode_is_rejected(billing_mode: object) -> None:
    with pytest.raises(ContractValidationError, match="dynamodb_billing_mode"):
        AwsSettings(dynamodb_billing_mode=billing_mode)


def test_cost_guardrails_use_canonical_values() -> None:
    guardrails = CostGuardrails()

    assert guardrails.budget_warning_usd == 10
    assert guardrails.budget_elevated_usd == 25
    assert guardrails.budget_critical_usd == 40
    assert guardrails.model_output_token_cap == 1_024
    assert guardrails.dynamodb_billing_mode is DynamoDbBillingMode.PAY_PER_REQUEST
    assert guardrails.cloudwatch_retention_days == 3


@pytest.mark.parametrize(
    ("warning", "elevated", "critical"),
    [
        (10, 10, 40),
        (25, 10, 40),
        (10, 40, 25),
        (0, 25, 40),
        (10.0, 25, 40),
    ],
)
def test_incorrect_budget_threshold_ordering_is_rejected(
    warning: object,
    elevated: object,
    critical: object,
) -> None:
    with pytest.raises(ContractValidationError):
        CostGuardrails(
            budget_warning_usd=warning,
            budget_elevated_usd=elevated,
            budget_critical_usd=critical,
        )
