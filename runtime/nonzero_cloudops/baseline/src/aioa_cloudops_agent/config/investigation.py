"""Configurable demo defaults for read-only idle-instance investigation."""

import os
from dataclasses import dataclass
from typing import Final

from aioa_cloudops_agent.domain.errors import ContractValidationError

DEMO_OBSERVATION_WINDOW_MINUTES: Final = 60
DEMO_METRIC_PERIOD_SECONDS: Final = 300
DEMO_MINIMUM_DATAPOINTS: Final = 6
DEMO_CPU_IDLE_THRESHOLD_PERCENT: Final = 10.0


def _integer_from_environment(name: str, default: int) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ContractValidationError(f"{name} must be an integer") from error
    return parsed


def _float_from_environment(name: str, default: float) -> float:
    value = os.getenv(name, str(default))
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise ContractValidationError(f"{name} must be numeric") from error
    return parsed


@dataclass(frozen=True, slots=True)
class IdlePolicySettings:
    """Deterministic, overrideable demo policy—not an AWS recommendation."""

    observation_window_minutes: int = DEMO_OBSERVATION_WINDOW_MINUTES
    period_seconds: int = DEMO_METRIC_PERIOD_SECONDS
    minimum_datapoints: int = DEMO_MINIMUM_DATAPOINTS
    cpu_idle_threshold_percent: float = DEMO_CPU_IDLE_THRESHOLD_PERCENT

    def __post_init__(self) -> None:
        for name, value in (
            ("observation_window_minutes", self.observation_window_minutes),
            ("period_seconds", self.period_seconds),
            ("minimum_datapoints", self.minimum_datapoints),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ContractValidationError(f"{name} must be a positive integer")
        if self.observation_window_minutes > 24 * 60:
            raise ContractValidationError("observation_window_minutes must not exceed one day")
        if self.period_seconds < 60 or self.period_seconds > 3_600:
            raise ContractValidationError("period_seconds must be between 60 and 3600")
        window_seconds = self.observation_window_minutes * 60
        if window_seconds % self.period_seconds != 0:
            raise ContractValidationError("observation window must be divisible by period_seconds")
        maximum_datapoints = window_seconds // self.period_seconds
        if self.minimum_datapoints > maximum_datapoints:
            raise ContractValidationError("minimum_datapoints exceeds the configured window")
        threshold = self.cpu_idle_threshold_percent
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, (int, float))
            or not 0 <= float(threshold) <= 100
        ):
            raise ContractValidationError("cpu_idle_threshold_percent must be between 0 and 100")

    @classmethod
    def from_environment(cls) -> "IdlePolicySettings":
        """Load non-secret policy overrides with explicit validation."""

        return cls(
            observation_window_minutes=_integer_from_environment(
                "IDLE_OBSERVATION_WINDOW_MINUTES",
                DEMO_OBSERVATION_WINDOW_MINUTES,
            ),
            period_seconds=_integer_from_environment(
                "IDLE_METRIC_PERIOD_SECONDS",
                DEMO_METRIC_PERIOD_SECONDS,
            ),
            minimum_datapoints=_integer_from_environment(
                "IDLE_MINIMUM_DATAPOINTS",
                DEMO_MINIMUM_DATAPOINTS,
            ),
            cpu_idle_threshold_percent=_float_from_environment(
                "IDLE_CPU_THRESHOLD_PERCENT",
                DEMO_CPU_IDLE_THRESHOLD_PERCENT,
            ),
        )
