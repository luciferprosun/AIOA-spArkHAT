"""Explicit Non-Zero failures and fail-closed control results."""

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from .enums import FailureKind, ResultStatus
from .identifiers import NonEmptyText, ShortIdentifier


class FailureDetail(BaseModel):
    """Serializable failure information with stable category and retry semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: FailureKind
    code: ShortIdentifier
    message: NonEmptyText
    retryable: bool


class ControlResult[ResultValue](BaseModel):
    """Discriminated result that cannot blur failure into missing data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ResultStatus
    value: ResultValue | None = None
    failure: FailureDetail | None = None

    @model_validator(mode="after")
    def validate_discriminated_result(self) -> Self:
        if self.status is ResultStatus.SUCCESS:
            if self.value is None or self.failure is not None:
                raise ValueError("successful result requires value and forbids failure")
        elif self.value is not None or self.failure is None:
            raise ValueError("failed result requires failure and forbids value")
        return self

    @classmethod
    def succeeded(cls, value: ResultValue) -> "ControlResult[ResultValue]":
        return cls(status=ResultStatus.SUCCESS, value=value)

    @classmethod
    def failed(cls, failure: FailureDetail) -> "ControlResult[ResultValue]":
        return cls(status=ResultStatus.FAILURE, failure=failure)


class NonZeroContractError(ValueError):
    """Base deterministic rejection from the Non-Zero control plane."""


class WorkflowTransitionError(NonZeroContractError):
    """Raised when a workflow transition is not application-authorized."""


class CapabilityDeniedError(NonZeroContractError):
    """Raised when a capability or authority claim is absent or disallowed."""


class DurablePrerequisiteError(NonZeroContractError):
    """Raised when durable truth cannot prove future execution prerequisites."""


class StorageDependencyError(NonZeroContractError):
    """Raised when authoritative storage is unavailable or malformed."""

    retryable = True


class StorageConflictError(NonZeroContractError):
    """Raised when a conditional durable write detects incompatible state."""
