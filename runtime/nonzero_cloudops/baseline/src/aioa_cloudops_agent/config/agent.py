"""Fail-closed configuration for the single Strands and Bedrock runtime."""

import os
from dataclasses import dataclass
from typing import Final

from aioa_cloudops_agent.domain.errors import ContractValidationError

from .settings import DEFAULT_AWS_REGION, DEFAULT_MODEL_MAX_OUTPUT_TOKENS

DEFAULT_BEDROCK_MODEL_ID: Final = "eu.amazon.nova-2-lite-v1:0"
DEFAULT_BEDROCK_REGION: Final = DEFAULT_AWS_REGION
NOVA_2_LITE_MIN_TEMPERATURE: Final = 0.00001
NOVA_2_LITE_MAX_TEMPERATURE: Final = 1.0
DEFAULT_MODEL_TEMPERATURE: Final = NOVA_2_LITE_MIN_TEMPERATURE
DETERMINISTIC_TEMPERATURE_POLICY: Final = "LOWEST_MODEL_SUPPORTED_TEMPERATURE"


@dataclass(frozen=True, slots=True)
class BedrockModelCapabilities:
    """Model-specific inference constraints used by the Bedrock settings contract."""

    model_id: str
    minimum_temperature: float
    maximum_temperature: float

    def validate_temperature(self, value: object) -> float:
        """Validate one temperature against this model's documented range."""

        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ContractValidationError("Bedrock temperature must be numeric")
        temperature = float(value)
        if not self.minimum_temperature <= temperature <= self.maximum_temperature:
            raise ContractValidationError(
                "Bedrock temperature must be within the configured model's supported range"
            )
        return temperature


_MODEL_CAPABILITIES: Final[dict[str, BedrockModelCapabilities]] = {
    DEFAULT_BEDROCK_MODEL_ID: BedrockModelCapabilities(
        model_id=DEFAULT_BEDROCK_MODEL_ID,
        minimum_temperature=NOVA_2_LITE_MIN_TEMPERATURE,
        maximum_temperature=NOVA_2_LITE_MAX_TEMPERATURE,
    )
}


def get_bedrock_model_capabilities(model_id: str) -> BedrockModelCapabilities:
    """Return explicit capabilities without assuming constraints across models."""

    try:
        return _MODEL_CAPABILITIES[model_id]
    except (KeyError, TypeError) as error:
        raise ContractValidationError("Bedrock model_id is not supported by this runtime") from error


def _read_positive_integer(name: str, value: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ContractValidationError(f"{name} must be a positive integer") from error
    if parsed <= 0:
        raise ContractValidationError(f"{name} must be a positive integer")
    return parsed


@dataclass(frozen=True, slots=True)
class BedrockSettings:
    """Explicit Bedrock provider settings without a fallback model."""

    model_id: str = DEFAULT_BEDROCK_MODEL_ID
    region: str = DEFAULT_BEDROCK_REGION
    max_output_tokens: int = DEFAULT_MODEL_MAX_OUTPUT_TOKENS
    temperature: float = DEFAULT_MODEL_TEMPERATURE

    def __post_init__(self) -> None:
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ContractValidationError("Bedrock model_id must be a non-empty string")
        if self.model_id != self.model_id.strip():
            raise ContractValidationError("Bedrock model_id must not contain surrounding whitespace")
        capabilities = get_bedrock_model_capabilities(self.model_id)
        if not isinstance(self.region, str) or self.region != DEFAULT_BEDROCK_REGION:
            raise ContractValidationError(f"Bedrock region must be {DEFAULT_BEDROCK_REGION}")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
            or self.max_output_tokens > DEFAULT_MODEL_MAX_OUTPUT_TOKENS
        ):
            raise ContractValidationError(
                f"Bedrock max_output_tokens must be between 1 and {DEFAULT_MODEL_MAX_OUTPUT_TOKENS}"
            )
        temperature = capabilities.validate_temperature(self.temperature)
        if temperature != capabilities.minimum_temperature:
            raise ContractValidationError(
                "Bedrock temperature must use the lowest model-supported temperature"
            )

    @classmethod
    def from_environment(cls) -> "BedrockSettings":
        """Load non-secret provider settings with explicit validation."""

        return cls(
            model_id=os.getenv("BEDROCK_MODEL_ID", DEFAULT_BEDROCK_MODEL_ID),
            region=os.getenv("BEDROCK_REGION", DEFAULT_BEDROCK_REGION),
            max_output_tokens=_read_positive_integer(
                "MODEL_MAX_OUTPUT_TOKENS",
                os.getenv(
                    "MODEL_MAX_OUTPUT_TOKENS",
                    str(DEFAULT_MODEL_MAX_OUTPUT_TOKENS),
                ),
            ),
            temperature=DEFAULT_MODEL_TEMPERATURE,
        )
