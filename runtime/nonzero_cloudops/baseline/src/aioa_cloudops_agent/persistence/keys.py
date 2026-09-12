"""Deterministic DynamoDB keys for Non-Zero records."""

from dataclasses import dataclass
from uuid import UUID

from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id

MAX_KEY_COMPONENT_LENGTH = 512


def _validate_key_component(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ContractValidationError(f"{name} must not contain surrounding whitespace")
    if len(value) > MAX_KEY_COMPONENT_LENGTH:
        raise ContractValidationError(
            f"{name} must not exceed {MAX_KEY_COMPONENT_LENGTH} characters"
        )
    if any(character in value for character in ("\n", "\r", "\x00")):
        raise ContractValidationError(f"{name} contains an invalid control character")
    return value


def _validate_typed_correlation_id(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ContractValidationError("correlation_id must be a UUIDv7 value")
    return validate_correlation_id(value)


@dataclass(frozen=True, slots=True)
class DynamoKey:
    """Composite key accepted by the project state table."""

    partition_key: str
    sort_key: str

    def __post_init__(self) -> None:
        _validate_key_component("partition_key", self.partition_key)
        _validate_key_component("sort_key", self.sort_key)

    def as_item(self) -> dict[str, dict[str, str]]:
        """Serialize the key for the low-level DynamoDB API."""

        return {
            "PK": {"S": self.partition_key},
            "SK": {"S": self.sort_key},
        }


def execution_key(correlation_id: UUID) -> DynamoKey:
    """Return the metadata key for one execution."""

    valid_id = _validate_typed_correlation_id(correlation_id)
    return DynamoKey(f"EXEC#{valid_id}", "META")


def provenance_key(correlation_id: UUID, sequence: int, event_id: str) -> DynamoKey:
    """Return an ordered, append-only key for one provenance event."""

    valid_id = _validate_typed_correlation_id(correlation_id)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence <= 0:
        raise ContractValidationError("sequence must be a positive integer")
    valid_event_id = _validate_key_component("event_id", event_id)
    return DynamoKey(f"EXEC#{valid_id}", f"EVT#{sequence:020d}#{valid_event_id}")


def approval_key(correlation_id: UUID, proposal_id: str) -> DynamoKey:
    """Return the key for one proposal approval record."""

    valid_id = _validate_typed_correlation_id(correlation_id)
    valid_proposal_id = _validate_key_component("proposal_id", proposal_id)
    return DynamoKey(f"EXEC#{valid_id}", f"APPROVAL#{valid_proposal_id}")


def idempotency_key(value: str) -> DynamoKey:
    """Return the atomic lock key for an idempotency claim."""

    valid_value = _validate_key_component("idempotency_key", value)
    return DynamoKey(f"IDEMP#{valid_value}", "LOCK")
