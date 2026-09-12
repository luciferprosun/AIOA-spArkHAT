"""Process-local, dependency-specific circuit state for bounded read operations."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from threading import Lock
from time import monotonic
from typing import Final


class CircuitState(StrEnum):
    """Closed vocabulary for dependency circuit lifecycle."""

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitDependency(StrEnum):
    """Read dependencies currently protected by the application circuit."""

    BEDROCK_MODEL = "BEDROCK_MODEL"
    EC2_READ = "EC2_READ"
    CLOUDWATCH_READ = "CLOUDWATCH_READ"
    VERIFICATION_READ = "VERIFICATION_READ"


@dataclass(frozen=True, slots=True)
class CircuitBreakerSettings:
    """Finite breaker limits owned by application configuration, never model input."""

    failure_threshold: int = 2
    cooldown_seconds: float = 30.0
    max_half_open_probes: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.failure_threshold, bool)
            or not isinstance(self.failure_threshold, int)
            or not 1 <= self.failure_threshold <= 10
        ):
            raise ValueError("failure_threshold must be between 1 and 10")
        cooldown = self.cooldown_seconds
        if (
            isinstance(cooldown, bool)
            or not isinstance(cooldown, (int, float))
            or not isfinite(float(cooldown))
            or not 0 < float(cooldown) <= 300
        ):
            raise ValueError("cooldown_seconds must be finite and between 0 and 300")
        if (
            isinstance(self.max_half_open_probes, bool)
            or not isinstance(self.max_half_open_probes, int)
            or self.max_half_open_probes != 1
        ):
            raise ValueError("max_half_open_probes must be exactly 1")


class CircuitOpenError(RuntimeError):
    """Typed, audit-safe signal that a dependency call was suppressed."""

    reason_code: Final = "DEPENDENCY_CIRCUIT_OPEN"

    def __init__(self, dependency: CircuitDependency) -> None:
        self.dependency = dependency
        super().__init__(f"{dependency.value} dependency circuit is open")


class CircuitStateUnavailableError(RuntimeError):
    """Typed fail-closed signal for unavailable or invalid circuit state."""

    reason_code: Final = "DEPENDENCY_CIRCUIT_UNAVAILABLE"

    def __init__(self, dependency: CircuitDependency) -> None:
        self.dependency = dependency
        super().__init__(f"{dependency.value} dependency circuit state is unavailable")


@dataclass(frozen=True, slots=True)
class CircuitPermit:
    """Generation-bound permission for one bounded read operation."""

    dependency: CircuitDependency
    generation: int
    half_open: bool


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    """Safe read-only circuit diagnostics without provider exception details."""

    dependency: CircuitDependency
    state: CircuitState
    consecutive_transient_failures: int
    half_open_probe_active: bool


@dataclass(slots=True)
class _DependencyState:
    state: CircuitState = CircuitState.CLOSED
    consecutive_transient_failures: int = 0
    retry_at: float | None = None
    generation: int = 0
    half_open_probe_active: bool = False


class DependencyCircuitBreaker:
    """Thread-safe state machine shared by read services in one runtime process."""

    def __init__(
        self,
        settings: CircuitBreakerSettings | None = None,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        active_settings = settings if settings is not None else CircuitBreakerSettings()
        if not isinstance(active_settings, CircuitBreakerSettings):
            raise TypeError("settings must be CircuitBreakerSettings")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._settings = active_settings
        self._clock = clock
        self._lock = Lock()
        self._states: dict[CircuitDependency, _DependencyState] = {}

    @property
    def settings(self) -> CircuitBreakerSettings:
        return self._settings

    def acquire(self, dependency: CircuitDependency) -> CircuitPermit:
        """Acquire a read permit, suppressing OPEN or competing HALF_OPEN calls."""

        dependency = self._validate_dependency(dependency)
        now = self._safe_now(dependency)
        try:
            with self._lock:
                state = self._state(dependency)
                if state.state is CircuitState.CLOSED:
                    return CircuitPermit(dependency, state.generation, half_open=False)
                if state.state is CircuitState.OPEN:
                    if state.retry_at is None:
                        raise CircuitStateUnavailableError(dependency)
                    if now < state.retry_at:
                        raise CircuitOpenError(dependency)
                    state.state = CircuitState.HALF_OPEN
                    state.half_open_probe_active = True
                    state.generation += 1
                    return CircuitPermit(dependency, state.generation, half_open=True)
                if state.state is CircuitState.HALF_OPEN:
                    raise CircuitOpenError(dependency)
                raise CircuitStateUnavailableError(dependency)
        except (CircuitOpenError, CircuitStateUnavailableError):
            raise
        except Exception as error:
            raise CircuitStateUnavailableError(dependency) from error

    def record_success(self, permit: CircuitPermit) -> None:
        """Close/reset only when this permit still belongs to the active generation."""

        self._record_non_transient(permit)

    def record_permanent_outcome(self, permit: CircuitPermit) -> None:
        """Treat a permanent provider response as reachability, without counting it."""

        self._record_non_transient(permit)

    def record_transient_failure(self, permit: CircuitPermit) -> None:
        """Count one terminal transient operation failure and open at the threshold."""

        permit = self._validate_permit(permit)
        now = self._safe_now(permit.dependency)
        try:
            with self._lock:
                state = self._state(permit.dependency)
                if permit.generation != state.generation:
                    return
                if permit.half_open:
                    if (
                        state.state is not CircuitState.HALF_OPEN
                        or not state.half_open_probe_active
                    ):
                        raise CircuitStateUnavailableError(permit.dependency)
                    self._open(state, now)
                    return
                if state.state is not CircuitState.CLOSED:
                    return
                state.consecutive_transient_failures += 1
                if (
                    state.consecutive_transient_failures
                    >= self._settings.failure_threshold
                ):
                    self._open(state, now)
        except CircuitStateUnavailableError:
            raise
        except Exception as error:
            raise CircuitStateUnavailableError(permit.dependency) from error

    def snapshot(self, dependency: CircuitDependency) -> CircuitSnapshot:
        """Return safe state for tests and operational diagnostics."""

        dependency = self._validate_dependency(dependency)
        try:
            with self._lock:
                state = self._state(dependency)
                return CircuitSnapshot(
                    dependency=dependency,
                    state=state.state,
                    consecutive_transient_failures=(
                        state.consecutive_transient_failures
                    ),
                    half_open_probe_active=state.half_open_probe_active,
                )
        except CircuitStateUnavailableError:
            raise
        except Exception as error:
            raise CircuitStateUnavailableError(dependency) from error

    def _record_non_transient(self, permit: CircuitPermit) -> None:
        permit = self._validate_permit(permit)
        try:
            with self._lock:
                state = self._state(permit.dependency)
                if permit.generation != state.generation:
                    return
                if permit.half_open and (
                    state.state is not CircuitState.HALF_OPEN
                    or not state.half_open_probe_active
                ):
                    raise CircuitStateUnavailableError(permit.dependency)
                if not permit.half_open and state.state is not CircuitState.CLOSED:
                    return
                state.state = CircuitState.CLOSED
                state.consecutive_transient_failures = 0
                state.retry_at = None
                state.half_open_probe_active = False
                if permit.half_open:
                    state.generation += 1
        except CircuitStateUnavailableError:
            raise
        except Exception as error:
            raise CircuitStateUnavailableError(permit.dependency) from error

    def _open(self, state: _DependencyState, now: float) -> None:
        state.state = CircuitState.OPEN
        state.retry_at = now + float(self._settings.cooldown_seconds)
        state.half_open_probe_active = False
        state.generation += 1

    def _safe_now(self, dependency: CircuitDependency) -> float:
        try:
            value = self._clock()
        except Exception as error:
            raise CircuitStateUnavailableError(dependency) from error
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not isfinite(float(value))
        ):
            raise CircuitStateUnavailableError(dependency)
        return float(value)

    def _state(self, dependency: CircuitDependency) -> _DependencyState:
        state = self._states.setdefault(dependency, _DependencyState())
        retry_at_valid = state.retry_at is None or (
            not isinstance(state.retry_at, bool)
            and isinstance(state.retry_at, (int, float))
            and isfinite(float(state.retry_at))
        )
        if (
            not isinstance(state, _DependencyState)
            or not isinstance(state.state, CircuitState)
            or isinstance(state.generation, bool)
            or not isinstance(state.generation, int)
            or state.generation < 0
            or isinstance(state.consecutive_transient_failures, bool)
            or not isinstance(state.consecutive_transient_failures, int)
            or state.consecutive_transient_failures < 0
            or not isinstance(state.half_open_probe_active, bool)
            or not retry_at_valid
            or (
                state.state is CircuitState.CLOSED
                and (state.retry_at is not None or state.half_open_probe_active)
            )
            or (
                state.state is CircuitState.OPEN
                and (state.retry_at is None or state.half_open_probe_active)
            )
            or (
                state.state is CircuitState.HALF_OPEN
                and (state.retry_at is None or not state.half_open_probe_active)
            )
        ):
            raise CircuitStateUnavailableError(dependency)
        return state

    @staticmethod
    def _validate_dependency(dependency: CircuitDependency) -> CircuitDependency:
        if not isinstance(dependency, CircuitDependency):
            raise TypeError("dependency must be CircuitDependency")
        return dependency

    @staticmethod
    def _validate_permit(permit: CircuitPermit) -> CircuitPermit:
        if not isinstance(permit, CircuitPermit):
            raise TypeError("permit must be CircuitPermit")
        if (
            not isinstance(permit.dependency, CircuitDependency)
            or isinstance(permit.generation, bool)
            or not isinstance(permit.generation, int)
            or permit.generation < 0
            or not isinstance(permit.half_open, bool)
        ):
            raise TypeError("permit fields are invalid")
        return permit
