"""Idempotency orchestration kept separate from provider-specific storage."""

from .models import IdempotencyClaim
from .repository import ExecutionRepository


def claim_once(
    repository: ExecutionRepository,
    claim: IdempotencyClaim,
) -> IdempotencyClaim:
    """Delegate one atomic claim without retries that could hide a conflict."""

    return repository.claim_idempotency(claim)
