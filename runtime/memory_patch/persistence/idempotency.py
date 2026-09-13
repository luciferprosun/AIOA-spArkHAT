"""Exact operation replay is a durable read; a different binding is a conflict."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..contracts.serialization import (
    canonical_sha256,
    freeze_json,
    require_non_empty,
    require_sha256_hex,
)
from ..errors import ErrorCode, MemoryPatchError
from .ports import RecordKind, StoredRecord, TransactionView


@dataclass(frozen=True, slots=True, repr=False)
class OperationBinding:
    idempotency_key: str
    operation_kind: str
    payload_digest: str

    def __post_init__(self) -> None:
        for value in (self.idempotency_key, self.operation_kind):
            require_non_empty(value, "operation binding")
            if len(value) > 128:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        require_sha256_hex(self.payload_digest, "operation payload digest")

    @classmethod
    def bind(
        cls, key: str, operation: str, payload: Mapping[str, Any]
    ) -> OperationBinding:
        return cls(key, operation, canonical_sha256(payload))


@dataclass(frozen=True, slots=True, repr=False)
class OperationResult:
    outcome: Mapping[str, Any]
    replayed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", freeze_json(self.outcome))


def _read(record: StoredRecord, binding: OperationBinding) -> OperationResult:
    if (
        set(record.payload) != {"operation_kind", "payload_digest", "outcome"}
        or record.payload["operation_kind"] != binding.operation_kind
        or record.payload["payload_digest"] != binding.payload_digest
        or not isinstance(record.payload["outcome"], Mapping)
    ):
        raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
    return OperationResult(record.payload["outcome"], True)


def execute_once(
    transaction: TransactionView,
    binding: OperationBinding,
    mutation: Callable[[], Mapping[str, Any]],
) -> OperationResult:
    existing = transaction.get(RecordKind.OPERATION, binding.idempotency_key)
    if existing is not None:
        return _read(existing, binding)
    outcome = freeze_json(mutation())
    if not isinstance(outcome, Mapping):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    transaction.insert(
        StoredRecord(
            RecordKind.OPERATION,
            binding.idempotency_key,
            transaction.context.scope,
            1,
            {
                "operation_kind": binding.operation_kind,
                "payload_digest": binding.payload_digest,
                "outcome": outcome,
            },
        )
    )
    return OperationResult(outcome, False)


def reconcile(
    transaction: TransactionView, binding: OperationBinding
) -> OperationResult:
    """Never execute on restart or on an absent/unknown durable operation."""
    existing = transaction.get(RecordKind.OPERATION, binding.idempotency_key)
    if existing is None:
        raise MemoryPatchError(ErrorCode.RECOVERY_REQUIRED)
    return _read(existing, binding)
