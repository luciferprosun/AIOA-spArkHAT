"""UUIDv7 and non-empty identifier contracts for the Non-Zero workflow."""

from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, StringConstraints

from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.domain.identifiers import (
    generate_correlation_id,
    validate_correlation_id,
)


def _validate_uuid7(value: UUID) -> UUID:
    try:
        return validate_correlation_id(value)
    except ContractValidationError as error:
        raise ValueError(error.message) from error


def _validate_bounded_text(value: str) -> str:
    if value != value.strip():
        raise ValueError("value must not contain surrounding whitespace")
    return value


Uuid7Identifier = Annotated[UUID, AfterValidator(_validate_uuid7)]
NonEmptyText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=512),
    AfterValidator(_validate_bounded_text),
]
ShortIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:#/-]*$"),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(min_length=16, max_length=256, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:#/-]*$"),
]
Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Ec2InstanceId = Annotated[
    str,
    StringConstraints(pattern=r"^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$"),
]


def generate_run_id() -> UUID:
    """Generate one UUIDv7 run identifier."""

    return generate_correlation_id()


def generate_trace_id() -> UUID:
    """Generate one UUIDv7 trace identifier."""

    return generate_correlation_id()


def generate_proposal_id() -> UUID:
    """Generate one UUIDv7 proposal identifier."""

    return generate_correlation_id()


def generate_event_id() -> UUID:
    """Generate one UUIDv7 audit-event identifier."""

    return generate_correlation_id()
