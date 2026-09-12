"""Explicit bounded retry rules for read-only dependencies only."""

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Final, TypeVar

from .circuit import (
    CircuitDependency,
    CircuitPermit,
    DependencyCircuitBreaker,
)


class RetryOperationClass(StrEnum):
    """Closed operation classes used by the automatic retry matrix."""

    MODEL_SCHEMA_CORRECTION = "MODEL_SCHEMA_CORRECTION"
    READ_ONLY_DEPENDENCY = "READ_ONLY_DEPENDENCY"
    READ_ONLY_VALIDATION = "READ_ONLY_VALIDATION"
    DURABLE_CONDITIONAL_CONFLICT = "DURABLE_CONDITIONAL_CONFLICT"
    MUTATION_BEFORE_SEND = "MUTATION_BEFORE_SEND"
    MUTATION_ACK_AMBIGUOUS = "MUTATION_ACK_AMBIGUOUS"
    VERIFICATION_POLL = "VERIFICATION_POLL"


AUTOMATIC_RETRY_ALLOWED: Final[dict[RetryOperationClass, bool]] = {
    RetryOperationClass.MODEL_SCHEMA_CORRECTION: True,
    RetryOperationClass.READ_ONLY_DEPENDENCY: True,
    RetryOperationClass.READ_ONLY_VALIDATION: False,
    RetryOperationClass.DURABLE_CONDITIONAL_CONFLICT: False,
    RetryOperationClass.MUTATION_BEFORE_SEND: False,
    RetryOperationClass.MUTATION_ACK_AMBIGUOUS: False,
    RetryOperationClass.VERIFICATION_POLL: True,
}

_TRANSIENT_CODES: Final[frozenset[str]] = frozenset(
    {
        "InternalError",
        "InternalFailure",
        "RequestTimeout",
        "RequestTimeoutException",
        "ServiceUnavailable",
        "ServiceUnavailableException",
        "Throttling",
        "ThrottlingException",
        "TooManyRequestsException",
    }
)
_TRANSIENT_HTTP_STATUSES: Final[frozenset[int]] = frozenset({429, 500, 502, 503, 504})
_PERMANENT_CODES: Final[frozenset[str]] = frozenset(
    {
        "AccessDenied",
        "AccessDeniedException",
        "InvalidClientTokenId",
        "InvalidParameter",
        "InvalidParameterValue",
        "ResourceNotFoundException",
        "UnauthorizedOperation",
        "UnrecognizedClientException",
        "ValidationError",
        "ValidationException",
    }
)
_TRANSIENT_TRANSPORT_ERRORS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("botocore.exceptions", "ConnectTimeoutError"),
        ("botocore.exceptions", "ConnectionClosedError"),
        ("botocore.exceptions", "EndpointConnectionError"),
        ("botocore.exceptions", "ReadTimeoutError"),
    }
)


def is_known_transient_read_error(error: Exception) -> bool:
    """Recognize only allow-listed transient read failures; AccessDenied is permanent."""

    if isinstance(error, (TimeoutError, ConnectionError)):
        return True
    error_type = type(error)
    if (error_type.__module__, error_type.__name__) in _TRANSIENT_TRANSPORT_ERRORS:
        return True
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    details = response.get("Error")
    code = details.get("Code") if isinstance(details, Mapping) else None
    metadata = response.get("ResponseMetadata")
    status = metadata.get("HTTPStatusCode") if isinstance(metadata, Mapping) else None
    if code in _PERMANENT_CODES:
        return False
    return code in _TRANSIENT_CODES or status in _TRANSIENT_HTTP_STATUSES


ResultValue = TypeVar("ResultValue")


class ReadRetryStateUnavailableError(RuntimeError):
    """Audit-safe failure when the bounded retry guard cannot continue."""

    reason_code: Final = "READ_RETRY_STATE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("Bounded read retry state is unavailable")


class BoundedReadRetry:
    """Retry a read only for known transient failures and a fixed attempt cap."""

    def __init__(
        self,
        *,
        max_attempts: int = 2,
        sleeper: Callable[[int], None] | None = None,
        circuit_breaker: DependencyCircuitBreaker | None = None,
        dependency: CircuitDependency | None = None,
    ) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise TypeError("max_attempts must be an integer")
        if not 1 <= max_attempts <= 3:
            raise ValueError("read retry max_attempts must be between 1 and 3")
        if sleeper is not None and not callable(sleeper):
            raise TypeError("sleeper must be callable")
        if (circuit_breaker is None) != (dependency is None):
            raise ValueError("circuit_breaker and dependency must be configured together")
        if circuit_breaker is not None and not isinstance(
            circuit_breaker, DependencyCircuitBreaker
        ):
            raise TypeError("circuit_breaker must be DependencyCircuitBreaker")
        if dependency is not None and not isinstance(dependency, CircuitDependency):
            raise TypeError("dependency must be CircuitDependency")
        self._max_attempts = max_attempts
        self._sleeper = sleeper or (lambda _: None)
        self._circuit_breaker = circuit_breaker
        self._dependency = dependency

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    def run(
        self,
        operation: Callable[[], ResultValue],
        *,
        operation_class: RetryOperationClass = RetryOperationClass.READ_ONLY_DEPENDENCY,
    ) -> ResultValue:
        """Run a read; mutation and validation classes can never enter this retry loop."""

        if not callable(operation):
            raise TypeError("operation must be callable")
        if operation_class not in {
            RetryOperationClass.READ_ONLY_DEPENDENCY,
            RetryOperationClass.VERIFICATION_POLL,
        }:
            raise ValueError("automatic retry is restricted to read-only operations")
        permit: CircuitPermit | None = None
        if self._circuit_breaker is not None and self._dependency is not None:
            permit = self._circuit_breaker.acquire(self._dependency)
        attempt_cap = 1 if permit is not None and permit.half_open else self._max_attempts
        for attempt in range(1, attempt_cap + 1):
            try:
                result = operation()
            except Exception as error:
                transient = is_known_transient_read_error(error)
                if attempt < attempt_cap and transient:
                    try:
                        self._sleeper(attempt)
                    except Exception as sleeper_error:
                        if permit is not None and self._circuit_breaker is not None:
                            self._circuit_breaker.record_transient_failure(permit)
                        raise ReadRetryStateUnavailableError() from sleeper_error
                    continue
                if permit is not None and self._circuit_breaker is not None:
                    if transient:
                        self._circuit_breaker.record_transient_failure(permit)
                    else:
                        self._circuit_breaker.record_permanent_outcome(permit)
                    raise
                raise
            if permit is not None and self._circuit_breaker is not None:
                self._circuit_breaker.record_success(permit)
            return result
        raise AssertionError("bounded retry loop returned no result")
