"""Bounded post-action verification settings."""

from dataclasses import dataclass

from aioa_cloudops_agent.domain.errors import ContractValidationError


@dataclass(frozen=True, slots=True)
class VerificationSettings:
    """Small deterministic polling budget; no model-controlled retry loop."""

    max_attempts: int = 3
    interval_seconds: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 10
        ):
            raise ContractValidationError("max_attempts must be between 1 and 10")
        if (
            isinstance(self.interval_seconds, bool)
            or not isinstance(self.interval_seconds, int)
            or not 0 <= self.interval_seconds <= 30
        ):
            raise ContractValidationError("interval_seconds must be between 0 and 30")
