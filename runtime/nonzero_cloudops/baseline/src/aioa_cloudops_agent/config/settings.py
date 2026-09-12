"""Typed AWS settings and cost guardrails with fail-closed defaults."""

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from aioa_cloudops_agent.domain.errors import ContractValidationError

DEFAULT_AWS_REGION: Final = "eu-central-1"
DEFAULT_DEPLOYMENT_STAGE: Final = "hackathon"
DEFAULT_MODEL_MAX_OUTPUT_TOKENS: Final = 1_024
DEFAULT_CLOUDWATCH_RETENTION_DAYS: Final = 3
DEFAULT_BUDGET_WARNING_USD: Final = 10
DEFAULT_BUDGET_ELEVATED_USD: Final = 25
DEFAULT_BUDGET_CRITICAL_USD: Final = 40

_STAGE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class DynamoDbBillingMode(StrEnum):
    """Supported DynamoDB billing mode for this project."""

    PAY_PER_REQUEST = "PAY_PER_REQUEST"


def _validate_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{name} must be an integer")
    if value <= 0:
        raise ContractValidationError(f"{name} must be positive")


def _validate_model_token_cap(value: object) -> None:
    _validate_positive_integer("model_max_output_tokens", value)
    if value > DEFAULT_MODEL_MAX_OUTPUT_TOKENS:
        raise ContractValidationError(
            f"model_max_output_tokens must not exceed {DEFAULT_MODEL_MAX_OUTPUT_TOKENS}"
        )


def _validate_log_retention(value: object) -> None:
    _validate_positive_integer("cloudwatch_retention_days", value)
    if value != DEFAULT_CLOUDWATCH_RETENTION_DAYS:
        raise ContractValidationError(
            f"cloudwatch_retention_days must be {DEFAULT_CLOUDWATCH_RETENTION_DAYS}"
        )


def _validate_billing_mode(value: object) -> None:
    if not isinstance(value, DynamoDbBillingMode):
        raise ContractValidationError("dynamodb_billing_mode must be PAY_PER_REQUEST")


@dataclass(frozen=True, slots=True)
class AwsSettings:
    """Portable AWS execution settings with mutation capability disabled by default."""

    region: str = DEFAULT_AWS_REGION
    stage: str = DEFAULT_DEPLOYMENT_STAGE
    model_max_output_tokens: int = DEFAULT_MODEL_MAX_OUTPUT_TOKENS
    cloudwatch_retention_days: int = DEFAULT_CLOUDWATCH_RETENTION_DAYS
    dynamodb_billing_mode: DynamoDbBillingMode = DynamoDbBillingMode.PAY_PER_REQUEST
    aws_mutations_enabled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.region, str) or self.region != DEFAULT_AWS_REGION:
            raise ContractValidationError(f"region must be {DEFAULT_AWS_REGION}")
        if not isinstance(self.stage, str) or not _STAGE_PATTERN.fullmatch(self.stage):
            raise ContractValidationError("stage must be a lowercase deployment slug")
        _validate_model_token_cap(self.model_max_output_tokens)
        _validate_log_retention(self.cloudwatch_retention_days)
        _validate_billing_mode(self.dynamodb_billing_mode)
        if not isinstance(self.aws_mutations_enabled, bool):
            raise ContractValidationError("aws_mutations_enabled must be a boolean")


@dataclass(frozen=True, slots=True)
class CostGuardrails:
    """Machine-readable cost thresholds and service consumption limits."""

    budget_warning_usd: int = DEFAULT_BUDGET_WARNING_USD
    budget_elevated_usd: int = DEFAULT_BUDGET_ELEVATED_USD
    budget_critical_usd: int = DEFAULT_BUDGET_CRITICAL_USD
    model_output_token_cap: int = DEFAULT_MODEL_MAX_OUTPUT_TOKENS
    dynamodb_billing_mode: DynamoDbBillingMode = DynamoDbBillingMode.PAY_PER_REQUEST
    cloudwatch_retention_days: int = DEFAULT_CLOUDWATCH_RETENTION_DAYS

    def __post_init__(self) -> None:
        _validate_positive_integer("budget_warning_usd", self.budget_warning_usd)
        _validate_positive_integer("budget_elevated_usd", self.budget_elevated_usd)
        _validate_positive_integer("budget_critical_usd", self.budget_critical_usd)
        if not (
            self.budget_warning_usd
            < self.budget_elevated_usd
            < self.budget_critical_usd
        ):
            raise ContractValidationError(
                "budget thresholds must satisfy warning < elevated < critical"
            )
        _validate_model_token_cap(self.model_output_token_cap)
        _validate_billing_mode(self.dynamodb_billing_mode)
        _validate_log_retention(self.cloudwatch_retention_days)
