# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: domain/identifiers.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Generation and validation for canonical correlation identifiers."""

from uuid import RFC_4122, UUID

from uuid6 import uuid7

from .validation import ContractValidationError


def validate_correlation_id(value: object) -> UUID:
    """Return a UUIDv7 value or fail explicitly for another version or malformed input."""

    if isinstance(value, UUID):
        correlation_id = value
    elif isinstance(value, str):
        try:
            correlation_id = UUID(value)
        except (ValueError, AttributeError) as error:
            raise ContractValidationError(
                "correlation_id must be a valid UUIDv7"
            ) from error
    else:
        raise ContractValidationError(
            "correlation_id must be a UUIDv7 or UUIDv7 string"
        )

    if correlation_id.version != 7 or correlation_id.variant != RFC_4122:
        raise ContractValidationError("correlation_id must be an RFC-compatible UUIDv7")
    return correlation_id


def generate_correlation_id() -> UUID:
    """Generate a standards-compliant UUIDv7 correlation identifier."""

    return validate_correlation_id(uuid7())
