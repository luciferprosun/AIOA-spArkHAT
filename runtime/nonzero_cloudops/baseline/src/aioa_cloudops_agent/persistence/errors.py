"""Typed persistence failures with explicit retry semantics."""

from aioa_cloudops_agent.domain.errors import DomainError, ErrorCode


class PersistenceConflictError(DomainError):
    """Raised when a create-only persistence operation finds existing state."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code=ErrorCode.PERSISTENCE_CONFLICT,
            message=message,
            retryable=False,
        )


class IdempotencyConflictError(DomainError):
    """Raised when an idempotency key was already claimed."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            code=ErrorCode.IDEMPOTENCY_CONFLICT,
            message=f"Idempotency key is already claimed: {idempotency_key}",
            retryable=False,
        )


class OptimisticConcurrencyError(DomainError):
    """Raised when a writer uses a stale execution version."""

    def __init__(self, expected_version: int) -> None:
        super().__init__(
            code=ErrorCode.OPTIMISTIC_CONCURRENCY_CONFLICT,
            message=f"Execution version no longer matches expected version {expected_version}",
            retryable=True,
        )


class PersistenceOperationError(DomainError):
    """Raised when persistence fails without exposing provider response details."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code=ErrorCode.PERSISTENCE_FAILURE,
            message=message,
            retryable=True,
        )
