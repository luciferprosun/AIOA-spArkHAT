"""Non-Zero persistence contracts and DynamoDB adapter."""

from .durable_repository import DurableTruthRepository
from .dynamodb import DynamoDbClient, DynamoDbExecutionRepository
from .errors import (
    IdempotencyConflictError,
    OptimisticConcurrencyError,
    PersistenceConflictError,
    PersistenceOperationError,
)
from .idempotency import claim_once
from .keys import (
    DynamoKey,
    approval_key,
    execution_key,
    idempotency_key,
    provenance_key,
)
from .local import LocalFileDurableTruthRepository
from .models import (
    ExecutionRecord,
    IdempotencyClaim,
    ProvenanceEventType,
    ProvenanceRecord,
    compute_evidence_digest,
    validate_evidence_digest,
    validate_utc_timestamp,
)
from .nz_dynamodb import DynamoDbDurableTruthRepository
from .prerequisites import (
    ApprovedActionPrerequisites,
    load_execution_prerequisites,
    register_approved_action,
)
from .recovery import classify_recovery
from .repository import ExecutionRepository
from .semantic_idempotency import (
    build_idempotency_record,
    derive_action_fingerprint,
    derive_idempotency_key,
)

__all__ = [
    "ApprovedActionPrerequisites",
    "DurableTruthRepository",
    "DynamoDbClient",
    "DynamoDbDurableTruthRepository",
    "DynamoDbExecutionRepository",
    "DynamoKey",
    "ExecutionRecord",
    "ExecutionRepository",
    "IdempotencyClaim",
    "IdempotencyConflictError",
    "LocalFileDurableTruthRepository",
    "OptimisticConcurrencyError",
    "PersistenceConflictError",
    "PersistenceOperationError",
    "ProvenanceEventType",
    "ProvenanceRecord",
    "approval_key",
    "build_idempotency_record",
    "claim_once",
    "classify_recovery",
    "compute_evidence_digest",
    "derive_action_fingerprint",
    "derive_idempotency_key",
    "execution_key",
    "idempotency_key",
    "load_execution_prerequisites",
    "provenance_key",
    "register_approved_action",
    "validate_evidence_digest",
    "validate_utc_timestamp",
]
