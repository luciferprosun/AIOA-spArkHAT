"""Fail-closed configuration for the single private sandbox stop path."""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aioa_cloudops_agent.domain.errors import ContractValidationError

from .settings import DEFAULT_AWS_REGION

if TYPE_CHECKING:
    from aioa_cloudops_agent.cloudops.models import SandboxTarget


def _strict_boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ContractValidationError(f"{name} must be exactly true or false")


@dataclass(frozen=True, slots=True)
class SandboxRemediationSettings:
    """Non-secret scope and two independent live-mutation opt-in switches."""

    instance_id: str
    required_tag_key: str = "AIOACloudOpsSandbox"
    required_tag_value: str = "true"
    region: str = DEFAULT_AWS_REGION
    aws_mutations_enabled: bool = False
    allow_live_sandbox_stop: bool = False

    def __post_init__(self) -> None:
        from aioa_cloudops_agent.cloudops.models import SandboxTarget

        SandboxTarget(
            instance_id=self.instance_id,
            region=self.region,
            required_tag_key=self.required_tag_key,
            required_tag_value=self.required_tag_value,
        )
        if self.region != DEFAULT_AWS_REGION:
            raise ContractValidationError(f"region must be {DEFAULT_AWS_REGION}")
        if not isinstance(self.aws_mutations_enabled, bool):
            raise ContractValidationError("aws_mutations_enabled must be a boolean")
        if not isinstance(self.allow_live_sandbox_stop, bool):
            raise ContractValidationError("allow_live_sandbox_stop must be a boolean")

    @property
    def live_execution_enabled(self) -> bool:
        """Require both global and action-specific configuration; neither is approval."""

        return self.aws_mutations_enabled and self.allow_live_sandbox_stop

    @property
    def target(self) -> "SandboxTarget":
        """Construct the already-validated domain scope without a config import cycle."""

        from aioa_cloudops_agent.cloudops.models import SandboxTarget

        return SandboxTarget(
            instance_id=self.instance_id,
            region=self.region,
            required_tag_key=self.required_tag_key,
            required_tag_value=self.required_tag_value,
        )

    @classmethod
    def from_environment(cls) -> "SandboxRemediationSettings":
        """Load one explicit target and fail when production scope is absent."""

        instance_id = os.getenv("SANDBOX_INSTANCE_ID")
        if instance_id is None:
            raise ContractValidationError("SANDBOX_INSTANCE_ID is required")
        return cls(
            instance_id=instance_id,
            required_tag_key=os.getenv("SANDBOX_TAG_KEY", "AIOACloudOpsSandbox"),
            required_tag_value=os.getenv("SANDBOX_TAG_VALUE", "true"),
            region=os.getenv("SANDBOX_REGION", DEFAULT_AWS_REGION),
            aws_mutations_enabled=_strict_boolean("AWS_MUTATIONS_ENABLED"),
            allow_live_sandbox_stop=_strict_boolean("AIOA_ALLOW_LIVE_SANDBOX_STOP"),
        )
