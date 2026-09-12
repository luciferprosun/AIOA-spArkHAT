"""Provider-independent repository contract for Non-Zero state."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from aioa_cloudops_agent.domain.approval import ApprovalRecord, ApprovalStatus
from aioa_cloudops_agent.domain.enums import ExecutionState

from .models import ExecutionRecord, IdempotencyClaim, ProvenanceRecord


class ExecutionRepository(Protocol):
    """Operations required by execution, idempotency, provenance, and approval flows."""

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        """Create execution metadata without overwriting existing state."""

    def get_execution(self, correlation_id: UUID) -> ExecutionRecord | None:
        """Read execution metadata by its UUIDv7 correlation identifier."""

    def claim_idempotency(self, claim: IdempotencyClaim) -> IdempotencyClaim:
        """Atomically claim an idempotency key exactly once."""

    def update_execution_state(
        self,
        correlation_id: UUID,
        next_state: ExecutionState,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        """Update state only when the stored version equals the expected version."""

    def append_provenance(self, record: ProvenanceRecord) -> ProvenanceRecord:
        """Append an immutable event without exposing overwrite or delete operations."""

    def save_approval(
        self,
        record: ApprovalRecord,
        *,
        expected_status: ApprovalStatus | None = None,
    ) -> ApprovalRecord:
        """Create or conditionally replace one proposal approval record."""

    def get_approval(self, correlation_id: UUID, proposal_id: str) -> ApprovalRecord | None:
        """Read one proposal approval record."""
