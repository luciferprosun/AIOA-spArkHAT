"Fail-closed exceptions raised by Knowledge Kernel contracts."

from __future__ import annotations

from enum import Enum


class KernelContractError(ValueError):
    """Base class for contract validation failures."""


class ContractValidationError(KernelContractError):
    """A record violates a structural or semantic contract invariant."""


class AuthorityViolation(KernelContractError):
    """An actor attempted an operation outside its declared authority."""


class OwnershipViolation(KernelContractError):
    """A tenant or user attempted to cross an ownership boundary."""


class InvalidTransition(KernelContractError):
    """A lifecycle transition is not present in the explicit state graph."""


class QuotaExceeded(KernelContractError):
    """A Personal Memory HAT pool operation would exceed its policy."""


class IntegrityError(KernelContractError):
    """A deterministic hash or immutable binding does not verify."""


class PersistenceError(RuntimeError):
    """Base failure that exposes only bounded, non-secret metadata."""

    def __init__(
        self,
        message: str = "persistence operation failed",
        *,
        sqlstate: str | None = None,
        attempt: int | None = None,
        operation_kind: str | None = None,
        sanitized_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate
        self.attempt = attempt
        self.operation_kind = operation_kind
        self.sanitized_code = sanitized_code


class PersistenceConfigurationError(PersistenceError):
    """The connection factory or persistence configuration is unsafe."""


class PersistenceTransactionError(PersistenceError):
    """A transaction failed and was not automatically retried."""


class RetryableSerializationError(PersistenceTransactionError):
    """A typed SQLSTATE 40001 signal used by deterministic integrations."""

    def __init__(
        self, *, attempt: int | None = None, operation_kind: str | None = None
    ) -> None:
        super().__init__(
            "serializable transaction requires a complete retry",
            sqlstate="40001",
            attempt=attempt,
            operation_kind=operation_kind,
            sanitized_code="SERIALIZATION_RETRY",
        )


class RetryExhaustedError(PersistenceTransactionError):
    """Ten complete serializable transaction attempts did not commit."""


class IdempotencyConflictError(PersistenceError):
    """An idempotency identity was reused with a different binding."""


class OperationStateConflictError(PersistenceError):
    """A compare-and-set lifecycle transition observed stale state."""


class ImmutableRecordConflictError(PersistenceError):
    """An immutable database identity was reused with different facts."""


class TransactionBoundaryViolation(PersistenceError):
    """Code crossed or retained the bounded persistence transaction boundary."""


# Native operation errors are separate from retained private source exceptions.
# Public views map legacy exception *types*, and never serialize their messages.


class ErrorCode(str, Enum):
    INVALID_REQUEST = "INVALID_REQUEST"
    ADMISSION_DENIED = "ADMISSION_DENIED"
    OWNER_DENIED = "OWNER_DENIED"
    BACKEND_UNCONFIGURED = "BACKEND_UNCONFIGURED"
    MODULE_CLOSED = "MODULE_CLOSED"
    NOT_FOUND = "NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"
    EVIDENCE_DENIED = "EVIDENCE_DENIED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    CHALLENGE_DENIED = "CHALLENGE_DENIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MIGRATION_DENIED = "MIGRATION_DENIED"
    TARGET_DENIED = "TARGET_DENIED"
    TRANSACTION_FAILED = "TRANSACTION_FAILED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    PROVENANCE_PENDING = "PROVENANCE_PENDING"
    PROVENANCE_CORRUPT = "PROVENANCE_CORRUPT"
    PROVIDER_DENIED = "PROVIDER_DENIED"
    UNVERIFIED = "UNVERIFIED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class MemoryPatchError(RuntimeError):
    """A closed native error code; no arbitrary message or diagnostic payload."""

    def __init__(self, code: ErrorCode) -> None:
        if type(code) is not ErrorCode:
            raise TypeError("native error requires a closed code")
        self.code = code
        super().__init__(code.value)


class CommitOutcomeUnknown(MemoryPatchError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.RECOVERY_REQUIRED)
