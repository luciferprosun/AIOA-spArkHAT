"""Top-level runtime selection with an explicit portable default."""

import os
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from aioa_cloudops_agent.domain.errors import ContractValidationError

from .agent import BedrockSettings

PORTABLE_MODEL_ID: Final = "aioa.mock.deterministic-v1"


class RuntimeMode(StrEnum):
    """Closed application runtime modes; cloud use is never inferred."""

    PORTABLE = "portable"
    AWS = "aws"


class ModelProviderName(StrEnum):
    """Providers supported by the current single Strands-agent runtime."""

    MOCK = "mock"
    BEDROCK = "bedrock"


def _parse_aws_opt_in(value: str) -> bool:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ContractValidationError(
        "AIOA_AWS_INTEGRATION_ENABLED must be exactly true or false"
    )


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Non-secret provider selection shared by CLI, tests, and composition."""

    mode: RuntimeMode = RuntimeMode.PORTABLE
    model_provider: ModelProviderName = ModelProviderName.MOCK
    aws_integration_enabled: bool = False
    bedrock: BedrockSettings | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, RuntimeMode):
            raise ContractValidationError("runtime mode must be portable or aws")
        if not isinstance(self.model_provider, ModelProviderName):
            raise ContractValidationError("model provider must be mock or bedrock")
        if not isinstance(self.aws_integration_enabled, bool):
            raise ContractValidationError("AWS integration opt-in must be a boolean")
        if self.mode is RuntimeMode.PORTABLE:
            if self.model_provider is not ModelProviderName.MOCK:
                raise ContractValidationError(
                    "portable runtime supports only the deterministic mock provider"
                )
            if self.aws_integration_enabled or self.bedrock is not None:
                raise ContractValidationError(
                    "portable runtime forbids AWS integration configuration"
                )
            return
        if self.model_provider is not ModelProviderName.BEDROCK:
            raise ContractValidationError("AWS runtime requires the explicit bedrock provider")
        if not self.aws_integration_enabled:
            raise ContractValidationError(
                "AWS runtime requires AIOA_AWS_INTEGRATION_ENABLED=true"
            )
        if not isinstance(self.bedrock, BedrockSettings):
            raise ContractValidationError(
                "AWS runtime requires explicit Bedrock model and region configuration"
            )

    @property
    def aws_calls_allowed(self) -> bool:
        """Return the explicit AWS provider boundary, never credential availability."""

        return self.mode is RuntimeMode.AWS and self.aws_integration_enabled

    @classmethod
    def from_environment(cls) -> "RuntimeSettings":
        """Load non-secret selection without discovering credentials or creating clients."""

        raw_mode = os.getenv("AIOA_RUNTIME_MODE", RuntimeMode.PORTABLE.value)
        raw_provider = os.getenv("AIOA_MODEL_PROVIDER", ModelProviderName.MOCK.value)
        try:
            mode = RuntimeMode(raw_mode)
        except ValueError as error:
            raise ContractValidationError(
                "AIOA_RUNTIME_MODE must be portable or aws"
            ) from error
        try:
            provider = ModelProviderName(raw_provider)
        except ValueError as error:
            raise ContractValidationError(
                "AIOA_MODEL_PROVIDER must be mock or bedrock"
            ) from error
        aws_enabled = _parse_aws_opt_in(
            os.getenv("AIOA_AWS_INTEGRATION_ENABLED", "false")
        )
        bedrock: BedrockSettings | None = None
        if mode is RuntimeMode.AWS and provider is ModelProviderName.BEDROCK and aws_enabled:
            if "BEDROCK_MODEL_ID" not in os.environ or "BEDROCK_REGION" not in os.environ:
                raise ContractValidationError(
                    "AWS runtime requires explicit Bedrock model and region configuration"
                )
            bedrock = BedrockSettings.from_environment()
        return cls(
            mode=mode,
            model_provider=provider,
            aws_integration_enabled=aws_enabled,
            bedrock=bedrock,
        )
