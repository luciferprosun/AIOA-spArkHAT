"""Fail-closed server-owned settings for the Day 15 judge surface."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from aioa_cloudops_agent.cloudops import SandboxTarget
from aioa_cloudops_agent.config import BedrockSettings, DynamoDbSettings, IdlePolicySettings
from aioa_cloudops_agent.config.settings import DEFAULT_AWS_REGION
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.nz import BudgetCounters

JUDGE_MAX_TURNS: Final = 8
JUDGE_MAX_TOKENS: Final = 8_192
JUDGE_MAX_ELAPSED_SECONDS: Final = 60
JUDGE_REQUEST_BODY_MAX_BYTES: Final = 4_096
JUDGE_TOKEN_MIN_LENGTH: Final = 32
JUDGE_TOKEN_MAX_LENGTH: Final = 512
JUDGE_TOKEN_MAX_LIFETIME_SECONDS: Final = 86_400

_LAMBDA_FUNCTION_NAME = re.compile(r"^[A-Za-z0-9-_]{1,64}$")
_SECRET_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9/_+=.@-]{1,512}$")


class JudgeInvestigationRequest(BaseModel):
    """The public caller can select one read-only intent and nothing else."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal["investigate_idle_sandbox"]


def new_judge_budget() -> BudgetCounters:
    """Return the one immutable server-owned run budget."""

    return BudgetCounters(
        max_turns=JUDGE_MAX_TURNS,
        max_tokens=JUDGE_MAX_TOKENS,
        max_elapsed_seconds=JUDGE_MAX_ELAPSED_SECONDS,
    )


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{name} is required")
    return value


def _utc_not_after(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ContractValidationError("JUDGE_TOKEN_NOT_AFTER must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ContractValidationError("JUDGE_TOKEN_NOT_AFTER must be UTC")
    return parsed


def _split_commercial_arn(value: str, *, name: str) -> tuple[str, str, str, str]:
    if not isinstance(value, str) or value != value.strip():
        raise ContractValidationError(f"{name} must be an exact ARN")
    parts = value.split(":", 5)
    if len(parts) != 6:
        raise ContractValidationError(f"{name} must be an exact ARN")
    arn, partition, service, region, account_id, resource = parts
    if (
        arn != "arn"
        or partition != "aws"
        or region != DEFAULT_AWS_REGION
        or len(account_id) != 12
        or not account_id.isascii()
        or not account_id.isdecimal()
        or not resource
    ):
        raise ContractValidationError(f"{name} must be an exact eu-central-1 ARN")
    return service, account_id, resource, partition


def _validate_runtime_arns(private_alias_arn: str, secret_arn: str) -> None:
    service, account_id, resource, partition = _split_commercial_arn(
        private_alias_arn,
        name="PRIVATE_REMEDIATION_FUNCTION_NAME",
    )
    lambda_resource = resource.split(":")
    if (
        service != "lambda"
        or len(lambda_resource) != 3
        or lambda_resource[0] != "function"
        or _LAMBDA_FUNCTION_NAME.fullmatch(lambda_resource[1]) is None
        or lambda_resource[2] != "live"
    ):
        raise ContractValidationError(
            "PRIVATE_REMEDIATION_FUNCTION_NAME must be an exact live alias ARN"
        )
    secret_service, secret_account, secret_resource, secret_partition = (
        _split_commercial_arn(secret_arn, name="JUDGE_TOKEN_SECRET_ARN")
    )
    secret_parts = secret_resource.split(":", 1)
    if (
        secret_service != "secretsmanager"
        or secret_partition != partition
        or secret_account != account_id
        or len(secret_parts) != 2
        or secret_parts[0] != "secret"
        or _SECRET_RESOURCE_NAME.fullmatch(secret_parts[1]) is None
    ):
        raise ContractValidationError(
            "JUDGE_TOKEN_SECRET_ARN must be an exact same-account secret ARN"
        )


@dataclass(frozen=True, slots=True)
class JudgeRuntimeSettings:
    """Validated non-secret composition settings for one orchestrator process."""

    stage: str
    state_table: DynamoDbSettings
    target: SandboxTarget
    bedrock: BedrockSettings
    idle_policy: IdlePolicySettings
    private_executor_alias_arn: str
    judge_token_secret_arn: str
    judge_token_not_after: datetime

    def __post_init__(self) -> None:
        if not self.stage or self.stage != self.stage.strip() or not self.stage.isascii():
            raise ContractValidationError("APP_STAGE must be a non-empty ASCII deployment stage")
        if self.target.region != DEFAULT_AWS_REGION or self.bedrock.region != DEFAULT_AWS_REGION:
            raise ContractValidationError(f"all runtime regions must be {DEFAULT_AWS_REGION}")
        _validate_runtime_arns(
            self.private_executor_alias_arn,
            self.judge_token_secret_arn,
        )
        if self.judge_token_not_after.tzinfo is None or self.judge_token_not_after.utcoffset() != UTC.utcoffset(
            self.judge_token_not_after
        ):
            raise ContractValidationError("judge token expiry must be UTC")

    @classmethod
    def from_environment(
        cls,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> JudgeRuntimeSettings:
        """Load the canonical target and fail instead of inventing a deployment value."""

        lambda_region = os.getenv("AWS_REGION")
        if lambda_region != DEFAULT_AWS_REGION:
            raise ContractValidationError(f"AWS_REGION must be {DEFAULT_AWS_REGION}")
        settings = cls(
            stage=_required_environment("APP_STAGE"),
            state_table=DynamoDbSettings.from_environment(),
            target=SandboxTarget.from_environment(),
            bedrock=BedrockSettings.from_environment(),
            idle_policy=IdlePolicySettings.from_environment(),
            private_executor_alias_arn=_required_environment(
                "PRIVATE_REMEDIATION_FUNCTION_NAME"
            ),
            judge_token_secret_arn=_required_environment("JUDGE_TOKEN_SECRET_ARN"),
            judge_token_not_after=_utc_not_after(
                _required_environment("JUDGE_TOKEN_NOT_AFTER")
            ),
        )
        now = (clock or (lambda: datetime.now(UTC)))()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise ContractValidationError("judge token validation clock must be UTC")
        if not now < settings.judge_token_not_after <= now + timedelta(
            seconds=JUDGE_TOKEN_MAX_LIFETIME_SECONDS
        ):
            raise ContractValidationError(
                "JUDGE_TOKEN_NOT_AFTER must be future UTC within the maximum lifetime"
            )
        return settings
