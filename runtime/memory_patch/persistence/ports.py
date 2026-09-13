"""Driver-free scoped repositories and whole-transaction execution.

The callback is domain computation only: prepare timestamps, random identities,
provider output and storage input before entering it. Each retry creates a fresh
transaction and revalidates Core authority. No default repository is fabricated.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, TypeVar

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    freeze_json,
    require_non_empty,
)
from runtime.memory_patch.errors import (
    CommitOutcomeUnknown,
    ErrorCode,
    MemoryPatchError,
)
from runtime.memory_patch.persistence.retry import RetryPolicy, extract_sqlstate


class RecordKind(str, Enum):
    SPACE = "space"
    PATCH = "patch"
    CHALLENGE = "challenge"
    APPROVAL = "approval"
    RECEIPT = "receipt"
    REVIEW = "review"
    SOURCE = "source"
    INGESTION = "ingestion"
    SHARING = "sharing"
    AUDIT = "audit"
    OUTBOX = "outbox"
    OPERATION = "operation"


@dataclass(frozen=True, slots=True, repr=False)
class StoredRecord:
    kind: RecordKind
    record_id: str
    scope: OwnerScope
    revision: int
    payload: Mapping[str, Any]
    payload_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.kind) is not RecordKind or type(self.scope) is not OwnerScope:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        require_non_empty(self.record_id, "record identity")
        if (
            len(self.record_id) > 256
            or type(self.revision) is not int
            or self.revision < 1
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if not isinstance(self.payload, Mapping):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        object.__setattr__(self, "payload", freeze_json(self.payload))
        object.__setattr__(
            self,
            "payload_digest",
            canonical_sha256(self, exclude_fields=("payload_digest",)),
        )

    def verify(self) -> None:
        if (
            canonical_sha256(self, exclude_fields=("payload_digest",))
            != self.payload_digest
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)


@dataclass(frozen=True, slots=True, repr=False)
class TransactionContext:
    principal: CorePrincipal
    purpose: Capability

    @property
    def scope(self) -> OwnerScope:
        return self.principal.scope


class RepositoryTransaction(Protocol):
    """Adapter contract: all SQL is scoped before filtering, counting or LIMIT.

    insert rejects conflicting immutable identity. replace uses revision CAS.
    Both include the supplied context; no method accepts a new tenant or owner.
    commit/rollback/close must reset context and release or discard the handle.
    Errors report SQLSTATE structurally. A missing commit acknowledgment raises
    CommitOutcomeUnknown (or structured 40003), never a success receipt.
    """

    def get(self, kind: RecordKind, record_id: str) -> StoredRecord | None: ...
    def scan(
        self, kind: RecordKind, *, limit: int, states: tuple[str, ...]
    ) -> tuple[StoredRecord, ...]: ...
    def insert(self, record: StoredRecord) -> None: ...
    def replace(self, record: StoredRecord, *, expected_revision: int) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class TransactionFactory(Protocol):
    def begin(
        self, context: TransactionContext, *, attempt: int
    ) -> RepositoryTransaction: ...
    def close(self) -> None: ...


_AUDITED = frozenset({RecordKind.AUDIT, RecordKind.OUTBOX, RecordKind.OPERATION})
_WRITE_KINDS = {
    Capability.CANDIDATE: frozenset({RecordKind.PATCH}) | _AUDITED,
    Capability.PROPOSE: frozenset({RecordKind.PATCH}) | _AUDITED,
    Capability.VALIDATE: frozenset({RecordKind.PATCH}) | _AUDITED,
    Capability.OWNER_APPROVAL: frozenset(
        {RecordKind.PATCH, RecordKind.CHALLENGE, RecordKind.APPROVAL}
    )
    | _AUDITED,
    Capability.COMMIT: frozenset({RecordKind.PATCH, RecordKind.RECEIPT}) | _AUDITED,
    Capability.ACTIVATE: frozenset({RecordKind.PATCH, RecordKind.RECEIPT}) | _AUDITED,
    Capability.MANAGE: frozenset(
        {RecordKind.SPACE, RecordKind.PATCH, RecordKind.SHARING, RecordKind.REVIEW}
    )
    | _AUDITED,
    Capability.REVIEW: frozenset({RecordKind.REVIEW}) | _AUDITED,
    Capability.EVIDENCE_CAPTURE: frozenset({RecordKind.SOURCE, RecordKind.INGESTION})
    | _AUDITED,
}


class TransactionView:
    """Invalidate escaped handles and enforce the Core purpose before adapter calls."""

    def __init__(
        self, adapter: RepositoryTransaction, context: TransactionContext
    ) -> None:
        self._adapter = adapter
        self.context = context
        self._active = True

    def invalidate(self) -> None:
        self._active = False

    def _check(self, kind: RecordKind, *, write: bool = False) -> None:
        if not self._active or type(kind) is not RecordKind:
            raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
        if write and kind not in _WRITE_KINDS.get(self.context.purpose, frozenset()):
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)

    def _record(self, record: StoredRecord, kind: RecordKind) -> StoredRecord:
        if (
            type(record) is not StoredRecord
            or record.kind is not kind
            or record.scope != self.context.scope
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        record.verify()
        return record

    def get(self, kind: RecordKind, record_id: str) -> StoredRecord | None:
        self._check(kind)
        require_non_empty(record_id, "record identity")
        if len(record_id) > 256:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        record = self._adapter.get(kind, record_id)
        if record is None:
            return None
        self._record(record, kind)
        if record.record_id != record_id:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        return record

    def scan(
        self,
        kind: RecordKind,
        *,
        limit: int = 128,
        states: tuple[str, ...] = (),
    ) -> tuple[StoredRecord, ...]:
        self._check(kind)
        if (
            type(limit) is not int
            or not 1 <= limit <= 1024
            or type(states) is not tuple
            or len(states) > 32
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if any(type(state) is not str or not 1 <= len(state) <= 64 for state in states):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        records = self._adapter.scan(kind, limit=limit, states=states)
        if type(records) is not tuple or len(records) > limit:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        for record in records:
            self._record(record, kind)
            if states and record.payload.get("state") not in states:
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if len({record.record_id for record in records}) != len(records):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        return records

    def insert(self, record: StoredRecord) -> None:
        self._check(record.kind, write=True)
        self._adapter.insert(self._record(record, record.kind))

    def replace(self, record: StoredRecord, *, expected_revision: int) -> None:
        self._check(record.kind, write=True)
        if (
            type(expected_revision) is not int
            or record.revision != expected_revision + 1
        ):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self._adapter.replace(
            self._record(record, record.kind), expected_revision=expected_revision
        )


_IN_TRANSACTION = contextvars.ContextVar("memory_patch_in_transaction", default=False)
T = TypeVar("T")


class TransactionRunner:
    def __init__(
        self,
        admission: CoreAdmission,
        factory: TransactionFactory | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._admission = admission
        self._factory = factory
        self._sleep = sleep
        self._closed = False

    @property
    def configured(self) -> bool:
        return self._factory is not None and not self._closed

    def run(
        self, context: TransactionContext, callback: Callable[[TransactionView], T]
    ) -> T:
        if self._closed:
            raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
        if self._factory is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        if _IN_TRANSACTION.get():
            raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED)
        token = _IN_TRANSACTION.set(True)
        policy = RetryPolicy()
        try:
            for attempt in range(1, policy.max_attempts + 1):
                self._admission.require(
                    context.principal, context.purpose, scope=context.scope
                )
                adapter: RepositoryTransaction | None = None
                view: TransactionView | None = None
                retry = False
                committing = False
                try:
                    adapter = self._factory.begin(context, attempt=attempt)
                    view = TransactionView(adapter, context)
                    result = callback(view)
                    self._admission.require(
                        context.principal, context.purpose, scope=context.scope
                    )
                    committing = True
                    adapter.commit()
                except Exception as error:
                    sqlstate = extract_sqlstate(error)
                    if isinstance(error, CommitOutcomeUnknown) or sqlstate == "40003":
                        raise CommitOutcomeUnknown() from error
                    if sqlstate == "40001":
                        if attempt == policy.max_attempts:
                            raise MemoryPatchError(ErrorCode.RETRY_EXHAUSTED) from error
                        retry = True
                    elif committing:
                        # Unless the driver proves rollback, a lost acknowledgment
                        # is an unknown outcome even without a SQLSTATE.
                        raise CommitOutcomeUnknown() from error
                    elif isinstance(error, MemoryPatchError):
                        raise
                    else:
                        raise MemoryPatchError(ErrorCode.TRANSACTION_FAILED) from error
                finally:
                    if view is not None:
                        view.invalidate()
                    if adapter is not None:
                        try:
                            try:
                                adapter.rollback()
                            finally:
                                adapter.close()
                        except Exception as cleanup_error:
                            if committing:
                                raise CommitOutcomeUnknown() from cleanup_error
                            raise MemoryPatchError(
                                ErrorCode.TRANSACTION_FAILED
                            ) from cleanup_error
                if not retry:
                    return result
                self._sleep(policy.backoff_seconds(attempt))
        finally:
            _IN_TRANSACTION.reset(token)
        raise MemoryPatchError(ErrorCode.RETRY_EXHAUSTED)

    def close(self) -> None:
        self._closed = True
        if self._factory is not None:
            self._factory.close()
