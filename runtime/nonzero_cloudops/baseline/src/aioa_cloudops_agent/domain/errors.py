"""Typed domain errors for explicit failure handling."""

from enum import StrEnum

from .enums import ExecutionState


class ErrorCode(StrEnum):
    """Stable machine-readable domain error codes."""

    INVALID_CONTRACT = "INVALID_CONTRACT"
    ILLEGAL_STATE_TRANSITION = "ILLEGAL_STATE_TRANSITION"
    AWS_BOUNDARY_VIOLATION = "AWS_BOUNDARY_VIOLATION"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    OPTIMISTIC_CONCURRENCY_CONFLICT = "OPTIMISTIC_CONCURRENCY_CONFLICT"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    CLOUDOPS_INSPECTION_REJECTED = "CLOUDOPS_INSPECTION_REJECTED"
    CLOUDOPS_RESPONSE_INVALID = "CLOUDOPS_RESPONSE_INVALID"


class DomainError(Exception):
    """Base exception carrying an explicit typed error contract."""

    code: ErrorCode
    message: str
    retryable: bool

    def __init__(self, *, code: ErrorCode, message: str, retryable: bool) -> None:
        if not isinstance(code, ErrorCode):
            raise TypeError("code must be an ErrorCode")
        if not isinstance(message, str):
            raise TypeError("message must be a string")
        if not message.strip():
            raise ValueError("message must not be empty")
        if not isinstance(retryable, bool):
            raise TypeError("retryable must be a boolean")

        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ContractValidationError(DomainError):
    """Raised when a typed domain contract is missing or invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code=ErrorCode.INVALID_CONTRACT,
            message=message,
            retryable=False,
        )


class IllegalStateTransitionError(DomainError):
    """Raised when an execution attempts an unauthorized lifecycle transition."""

    current_state: ExecutionState
    next_state: ExecutionState

    def __init__(self, current_state: ExecutionState, next_state: ExecutionState) -> None:
        self.current_state = current_state
        self.next_state = next_state
        super().__init__(
            code=ErrorCode.ILLEGAL_STATE_TRANSITION,
            message=f"Illegal execution-state transition: {current_state.value} -> {next_state.value}",
            retryable=False,
        )
