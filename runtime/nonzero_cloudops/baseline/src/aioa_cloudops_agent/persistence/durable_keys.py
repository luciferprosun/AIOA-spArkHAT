"""Deterministic one-table keys for canonical Non-Zero durable records."""

from uuid import UUID

from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.nz.identifiers import IdempotencyKey

from .keys import DynamoKey


def _uuid7(value: UUID) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("durable record identifier must be a UUIDv7")
    return validate_correlation_id(value)


def run_key(run_id: UUID) -> DynamoKey:
    """Address one workflow run."""

    return DynamoKey(f"RUN#{_uuid7(run_id)}", "META")


def proposal_key(proposal_id: UUID) -> DynamoKey:
    """Address one write-before-execute proposal."""

    return DynamoKey(f"PROPOSAL#{_uuid7(proposal_id)}", "META")


def approval_decision_key(proposal_id: UUID) -> DynamoKey:
    """Address the separate human decision for one proposal."""

    return DynamoKey(f"PROPOSAL#{_uuid7(proposal_id)}", "APPROVAL")


def semantic_idempotency_key(value: IdempotencyKey) -> DynamoKey:
    """Address one stable semantic action registration."""

    return DynamoKey(f"IDEMP#{value}", "LOCK")


def checkpoint_key(run_id: UUID) -> DynamoKey:
    """Address the latest versioned safe checkpoint for one run."""

    return DynamoKey(f"RUN#{_uuid7(run_id)}", "CHECKPOINT")


def audit_event_key(run_id: UUID, event_id: UUID) -> DynamoKey:
    """Address one append event using its time-ordered UUIDv7 identity."""

    return DynamoKey(f"RUN#{_uuid7(run_id)}", f"AUDIT#{_uuid7(event_id)}")


def verification_evidence_key(run_id: UUID, proposal_id: UUID) -> DynamoKey:
    """Address one immutable final verification proof for a run/proposal pair."""

    return DynamoKey(
        f"RUN#{_uuid7(run_id)}",
        f"VERIFY#{_uuid7(proposal_id)}",
    )
