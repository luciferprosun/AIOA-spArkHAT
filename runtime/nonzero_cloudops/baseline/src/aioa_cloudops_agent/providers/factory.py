"""Single explicit model-provider factory for the canonical Strands Agent."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from strands.models.model import Model

from aioa_cloudops_agent.config.agent import BedrockSettings
from aioa_cloudops_agent.config.runtime import (
    PORTABLE_MODEL_ID,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.config.settings import (
    DEFAULT_AWS_REGION,
    DEFAULT_MODEL_MAX_OUTPUT_TOKENS,
)
from aioa_cloudops_agent.domain.errors import ContractValidationError

from .model import (
    MockModelFailure,
    MockModelProvider,
    ModelProviderUnavailableError,
)

BedrockProviderFactory = Callable[..., Model]


@dataclass(frozen=True, slots=True)
class ModelProviderRuntime:
    """Resolved Strands model plus public-safe, non-secret runtime metadata."""

    settings: RuntimeSettings
    model: Model
    model_id: str
    region: str
    max_output_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.settings, RuntimeSettings):
            raise ContractValidationError("provider runtime requires RuntimeSettings")
        if not isinstance(self.model, Model):
            raise ContractValidationError("provider runtime requires a Strands Model")
        if not isinstance(self.model_id, str) or not self.model_id.strip():
            raise ContractValidationError("provider model_id must not be empty")
        if not isinstance(self.region, str) or not self.region.strip():
            raise ContractValidationError("provider region must not be empty")
        if (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ContractValidationError("provider token limit must be positive")

    @property
    def provider_name(self) -> ModelProviderName:
        return self.settings.model_provider

    @property
    def external_network_allowed(self) -> bool:
        return self.settings.mode is RuntimeMode.AWS

    @property
    def aws_calls_allowed(self) -> bool:
        return self.settings.aws_calls_allowed


def create_bedrock_model(
    settings: BedrockSettings,
    *,
    boto_session: Any | None = None,
) -> Model:
    """Create Bedrock lazily only after the AWS provider was explicitly selected."""

    if not isinstance(settings, BedrockSettings):
        raise ContractValidationError("settings must be BedrockSettings")
    from strands.models import BedrockModel

    from aioa_cloudops_agent.aws_clients import create_bedrock_runtime_config

    model_config = {
        "model_id": settings.model_id,
        "temperature": float(settings.temperature),
        "max_tokens": settings.max_output_tokens,
        "streaming": True,
    }
    if boto_session is not None:
        if getattr(boto_session, "region_name", None) != settings.region:
            raise ContractValidationError("boto_session region must match Bedrock settings")
        return BedrockModel(
            boto_session=boto_session,
            boto_client_config=create_bedrock_runtime_config(),
            **model_config,
        )
    return BedrockModel(
        region_name=settings.region,
        boto_client_config=create_bedrock_runtime_config(),
        **model_config,
    )


def _metadata(settings: RuntimeSettings, model: Model) -> ModelProviderRuntime:
    if settings.model_provider is ModelProviderName.MOCK:
        return ModelProviderRuntime(
            settings=settings,
            model=model,
            model_id=PORTABLE_MODEL_ID,
            region=DEFAULT_AWS_REGION,
            max_output_tokens=DEFAULT_MODEL_MAX_OUTPUT_TOKENS,
        )
    bedrock = settings.bedrock
    if not isinstance(bedrock, BedrockSettings):
        raise ContractValidationError("Bedrock provider settings are unavailable")
    return ModelProviderRuntime(
        settings=settings,
        model=model,
        model_id=bedrock.model_id,
        region=bedrock.region,
        max_output_tokens=bedrock.max_output_tokens,
    )


def create_model_provider(
    settings: RuntimeSettings | None = None,
    *,
    model_override: Model | None = None,
    mock_failure: MockModelFailure = MockModelFailure.NONE,
    boto_session: Any | None = None,
    bedrock_factory: BedrockProviderFactory | None = None,
) -> ModelProviderRuntime:
    """Resolve exactly one provider with no fallback and no ambient AWS discovery."""

    selected = settings or RuntimeSettings()
    if not isinstance(selected, RuntimeSettings):
        raise ContractValidationError("settings must be RuntimeSettings")
    if model_override is not None:
        if not isinstance(model_override, Model):
            raise ContractValidationError("model_override must be a Strands Model")
        return _metadata(selected, model_override)
    if selected.model_provider is ModelProviderName.MOCK:
        if boto_session is not None:
            raise ContractValidationError("portable provider does not accept an AWS session")
        return _metadata(selected, MockModelProvider(failure=mock_failure))
    bedrock = selected.bedrock
    if not isinstance(bedrock, BedrockSettings):
        raise ContractValidationError("Bedrock provider settings are unavailable")
    factory = bedrock_factory or create_bedrock_model
    try:
        model = factory(bedrock, boto_session=boto_session)
    except ContractValidationError:
        raise
    except (ImportError, ModuleNotFoundError) as error:
        raise ModelProviderUnavailableError(
            "selected model provider is unavailable"
        ) from error
    except Exception as error:
        raise ModelProviderUnavailableError(
            "selected model provider could not be initialized"
        ) from error
    if not isinstance(model, Model):
        raise ModelProviderUnavailableError(
            "selected model provider returned an invalid runtime"
        )
    return _metadata(selected, model)
