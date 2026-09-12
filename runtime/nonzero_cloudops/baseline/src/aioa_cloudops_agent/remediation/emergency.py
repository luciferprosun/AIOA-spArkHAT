"""Independent, executor-local emergency veto for the sole mutation boundary."""

import os
from collections.abc import Callable, Mapping
from typing import Final, Protocol, runtime_checkable

from .errors import RemediationEmergencyDisabledError

EMERGENCY_EXECUTION_DISABLED_ENV: Final = "AIOA_EMERGENCY_EXECUTION_DISABLED"
EMERGENCY_DENIAL_STATUS: Final = "DENIED_BY_POLICY"
EXECUTOR_EMERGENCY_DISABLED: Final = "EXECUTOR_EMERGENCY_DISABLED"


@runtime_checkable
class EmergencyExecutionControl(Protocol):
    """Negative control checked afresh immediately at each mutation boundary."""

    def assert_writes_enabled(self) -> None:
        """Raise the typed denial unless the independent veto is explicitly down."""


class EnvironmentEmergencyExecutionControl:
    """Strict environment-backed veto: only exact ``false`` permits a boundary call."""

    def __init__(self, reader: Callable[[str], object] | None = None) -> None:
        if reader is not None and not callable(reader):
            raise TypeError("reader must be callable")
        self._reader = os.environ.get if reader is None else reader

    def assert_writes_enabled(self) -> None:
        """Re-read the control and fail closed without retaining the raw value."""

        try:
            value = self._reader(EMERGENCY_EXECUTION_DISABLED_ENV)
        except Exception:
            raise RemediationEmergencyDisabledError(
                "emergency executor disable is active or unavailable"
            ) from None
        if value != "false":
            raise RemediationEmergencyDisabledError(
                "emergency executor disable is active or unavailable"
            )


def emergency_denial_payload() -> dict[str, str]:
    """Return the only safe denial envelope emitted by the private Lambda."""

    return {
        "status": EMERGENCY_DENIAL_STATUS,
        "code": EXECUTOR_EMERGENCY_DISABLED,
    }


def is_emergency_denial_payload(payload: object) -> bool:
    """Recognize only the exact closed denial envelope; reject extensions."""

    return isinstance(payload, Mapping) and dict(payload) == emergency_denial_payload()
