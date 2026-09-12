"""Typed contracts for bounded, traceable execution."""

from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from .enums import AuthorityGate, ExecutionState
from .errors import ContractValidationError
from .identifiers import validate_correlation_id


def _validate_positive_bounded_integer(name: str, value: object, upper_bound: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContractValidationError(f"{name} must be an integer")
    if value <= 0:
        raise ContractValidationError(f"{name} must be positive")
    if value > upper_bound:
        raise ContractValidationError(f"{name} must not exceed {upper_bound}")


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    """Hard limits applied to one execution."""

    MAX_TURNS: ClassVar[int] = 1_000
    MAX_TOKENS: ClassVar[int] = 10_000_000

    max_turns: int
    max_tokens: int

    def __post_init__(self) -> None:
        _validate_positive_bounded_integer("max_turns", self.max_turns, self.MAX_TURNS)
        _validate_positive_bounded_integer("max_tokens", self.max_tokens, self.MAX_TOKENS)


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Required identity, authority, lifecycle, and budget for an execution."""

    MAX_IDEMPOTENCY_KEY_LENGTH: ClassVar[int] = 256

    correlation_id: UUID
    idempotency_key: str
    state: ExecutionState
    authority_gate: AuthorityGate
    budget: ExecutionBudget

    def __post_init__(self) -> None:
        if not isinstance(self.correlation_id, UUID):
            raise ContractValidationError("correlation_id must be a UUID")
        validate_correlation_id(self.correlation_id)
        if not isinstance(self.idempotency_key, str):
            raise ContractValidationError("idempotency_key must be a string")
        if not self.idempotency_key.strip():
            raise ContractValidationError("idempotency_key must not be empty")
        if len(self.idempotency_key) > self.MAX_IDEMPOTENCY_KEY_LENGTH:
            raise ContractValidationError(
                f"idempotency_key must not exceed {self.MAX_IDEMPOTENCY_KEY_LENGTH} characters"
            )
        if not isinstance(self.state, ExecutionState):
            raise ContractValidationError("state must be an ExecutionState")
        if not isinstance(self.authority_gate, AuthorityGate):
            raise ContractValidationError("authority_gate must be an AuthorityGate")
        if not isinstance(self.budget, ExecutionBudget):
            raise ContractValidationError("budget must be an ExecutionBudget")
