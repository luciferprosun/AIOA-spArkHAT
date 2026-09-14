"Bounded SQLSTATE 40001-only retry classification and backoff."

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from runtime.memory_patch.errors import PersistenceConfigurationError

SERIALIZATION_SQLSTATE = "40001"
_SQLSTATE = re.compile("^[0-9A-Z]{5}$")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 10
    base_backoff_seconds: float = 0.01
    max_backoff_seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.max_attempts != 10:
            raise PersistenceConfigurationError(
                "retry policy must use exactly ten attempts",
                sanitized_code="INVALID_RETRY_POLICY",
            )
        if (
            self.base_backoff_seconds < 0
            or self.max_backoff_seconds <= 0
            or self.max_backoff_seconds > 1.0
            or (self.base_backoff_seconds > self.max_backoff_seconds)
        ):
            raise PersistenceConfigurationError(
                "retry backoff must be bounded to one second",
                sanitized_code="INVALID_RETRY_POLICY",
            )

    def backoff_seconds(self, attempt: int) -> float:
        if attempt < 1 or attempt >= self.max_attempts:
            raise PersistenceConfigurationError(
                "retry attempt is outside the backoff range",
                sanitized_code="INVALID_RETRY_ATTEMPT",
            )
        return min(
            self.max_backoff_seconds, self.base_backoff_seconds * 2 ** (attempt - 1)
        )


def extract_sqlstate(error: BaseException) -> str | None:
    """Read a structured SQLSTATE without classifying exception text."""
    candidates = (
        getattr(error, "sqlstate", None),
        getattr(error, "pgcode", None),
        getattr(getattr(error, "diag", None), "sqlstate", None),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and _SQLSTATE.fullmatch(candidate):
            return candidate
    return None


def is_retryable_sqlstate(sqlstate: str | None) -> bool:
    return sqlstate == SERIALIZATION_SQLSTATE


BackoffFunction = Callable[[int], float]
