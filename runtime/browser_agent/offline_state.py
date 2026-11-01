"""META-P1-03 deterministic OFFLINE state machine (stdlib only).

Synthetic navigation READ missions only. No browser, no network, no effects.
Every dispatch_allowed is ALWAYS False.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class OfflineState(str, Enum):
    NEW = "NEW"
    PREVIEWED = "PREVIEWED"
    OBSERVED = "OBSERVED"
    STOPPED = "STOPPED"
    TIMED_OUT = "TIMED_OUT"
    CANCELLED = "CANCELLED"
    DENIED = "DENIED"


TERMINAL = frozenset({
    OfflineState.OBSERVED, OfflineState.STOPPED, OfflineState.TIMED_OUT,
    OfflineState.CANCELLED, OfflineState.DENIED,
})

_ALLOWED: dict[OfflineState, frozenset[OfflineState]] = {
    OfflineState.NEW: frozenset({
        OfflineState.PREVIEWED, OfflineState.STOPPED,
        OfflineState.TIMED_OUT, OfflineState.CANCELLED, OfflineState.DENIED,
    }),
    OfflineState.PREVIEWED: frozenset({
        OfflineState.OBSERVED, OfflineState.STOPPED,
        OfflineState.TIMED_OUT, OfflineState.CANCELLED, OfflineState.DENIED,
    }),
    OfflineState.OBSERVED: frozenset(),
    OfflineState.STOPPED: frozenset(),
    OfflineState.TIMED_OUT: frozenset(),
    OfflineState.CANCELLED: frozenset(),
    OfflineState.DENIED: frozenset(),
}


class OfflineStateDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("META_OFFLINE_STATE_DENIED")


class OfflineStateTransitionDenied(ValueError):
    def __init__(self) -> None:
        super().__init__("META_OFFLINE_STATE_TRANSITION_DENIED")


def _deny() -> OfflineStateDenied:
    return OfflineStateDenied()


@dataclass(frozen=True, slots=True)
class OfflineClockBounds:
    initial_utc: datetime
    deadline_utc: datetime
    timeout_ms: int


class OfflineTaskState:
    """Per-task isolated state machine. No class-level mutable state."""

    def __init__(
        self,
        *,
        task_digest: str,
        allowed_origins: tuple[str, ...],
        core_owner_scope_digest: str,
        core_source_sha: str,
        task_owner_scope_digest: str,
        task_source_sha: str,
        initial_utc: datetime,
        deadline_utc: datetime,
        timeout_ms: int,
    ) -> None:
        from runtime.meta_hackathon.contracts import _hash

        for value in (task_digest, core_owner_scope_digest, task_owner_scope_digest):
            _hash(value)
        for value in (core_source_sha, task_source_sha):
            _hash(value, sha40=True)
        if type(allowed_origins) is not tuple or not allowed_origins:
            raise _deny()
        for origin in allowed_origins:
            if type(origin) is not str or not origin:
                raise _deny()
        for moment in (initial_utc, deadline_utc):
            if not isinstance(moment, datetime) or moment.tzinfo is None:
                raise _deny()
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 15000:
            raise _deny()
        if deadline_utc <= initial_utc:
            raise _deny()
        self._task_digest = task_digest
        self._allowed_origins = allowed_origins
        self._core_owner_scope_digest = core_owner_scope_digest
        self._core_source_sha = core_source_sha
        self._task_owner_scope_digest = task_owner_scope_digest
        self._task_source_sha = task_source_sha
        self._bounds = OfflineClockBounds(
            initial_utc=initial_utc.astimezone(timezone.utc),
            deadline_utc=deadline_utc.astimezone(timezone.utc),
            timeout_ms=timeout_ms,
        )
        self._state = OfflineState.NEW
        self._observed_url: str | None = None

    @property
    def dispatch_allowed(self) -> bool:
        return False

    @property
    def environment(self) -> str:
        return "OFFLINE_FIXTURE"

    @property
    def state(self) -> OfflineState:
        return self._state

    @property
    def task_digest(self) -> str:
        return self._task_digest

    def _move(self, target: OfflineState) -> None:
        if target not in _ALLOWED[self._state]:
            raise OfflineStateTransitionDenied()
        self._state = target

    def _expired(self, now: datetime) -> bool:
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise _deny()
        moment = now.astimezone(timezone.utc)
        elapsed_ms = (moment - self._bounds.initial_utc).total_seconds() * 1000.0
        return moment >= self._bounds.deadline_utc or elapsed_ms >= self._bounds.timeout_ms

    def preview(self, *, stopped: bool, now: datetime) -> OfflineState:
        if type(stopped) is not bool:
            raise _deny()
        if self._state is not OfflineState.NEW:
            raise OfflineStateTransitionDenied()
        if stopped:
            self._move(OfflineState.STOPPED)
            return self._state
        if self._task_owner_scope_digest != self._core_owner_scope_digest:
            self._move(OfflineState.DENIED)
            return self._state
        if self._task_source_sha != self._core_source_sha:
            self._move(OfflineState.DENIED)
            return self._state
        if self._expired(now):
            self._move(OfflineState.TIMED_OUT)
            return self._state
        self._move(OfflineState.PREVIEWED)
        return self._state

    def observe(
        self,
        *,
        task_digest: str,
        observed_url: object,
        captured_at_utc: object,
        stopped: bool,
        now: datetime,
    ) -> OfflineState:
        from runtime.meta_hackathon.contracts import (
            MetaContractError,
            utc_timestamp,
            valid_page_url,
        )

        if type(stopped) is not bool:
            raise _deny()
        if self._state is not OfflineState.PREVIEWED:
            raise OfflineStateTransitionDenied()
        if stopped:
            self._move(OfflineState.STOPPED)
            return self._state
        if type(task_digest) is not str or task_digest != self._task_digest:
            self._move(OfflineState.DENIED)
            return self._state
        try:
            valid_page_url(observed_url, self._allowed_origins)
            captured = utc_timestamp(captured_at_utc)
        except MetaContractError:
            self._move(OfflineState.DENIED)
            return self._state
        if captured > self._bounds.deadline_utc or self._expired(now):
            self._move(OfflineState.TIMED_OUT)
            return self._state
        if captured < self._bounds.initial_utc:
            self._move(OfflineState.DENIED)
            return self._state
        if captured > now.astimezone(timezone.utc):
            self._move(OfflineState.DENIED)
            return self._state
        self._observed_url = observed_url  # type: ignore[assignment]
        self._move(OfflineState.OBSERVED)
        return self._state

    def follow_redirect(self, *, redirect_url: object) -> OfflineState:
        from runtime.meta_hackathon.contracts import MetaContractError, valid_page_url

        if self._state is not OfflineState.PREVIEWED:
            raise OfflineStateTransitionDenied()
        try:
            valid_page_url(redirect_url, self._allowed_origins)
        except MetaContractError:
            self._move(OfflineState.DENIED)
            return self._state
        return self._state

    def stop(self) -> OfflineState:
        if self._state in TERMINAL:
            raise OfflineStateTransitionDenied()
        self._move(OfflineState.STOPPED)
        return self._state

    def cancel(self) -> OfflineState:
        if self._state in TERMINAL:
            raise OfflineStateTransitionDenied()
        self._move(OfflineState.CANCELLED)
        return self._state

    def check_timeout(self, now: datetime) -> OfflineState:
        if self._state in TERMINAL:
            raise OfflineStateTransitionDenied()
        if self._expired(now):
            self._move(OfflineState.TIMED_OUT)
        return self._state
