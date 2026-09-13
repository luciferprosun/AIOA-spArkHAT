"""Owner-partitioned domain audit and separately acknowledged Core publication.

The supplied Core store owns the global envelope and hash chain. Native domain
state, audit and outbox are one repository transaction; Core JSONL publication
is an independent, leased, deduplicated step. It is never a SQL atomicity claim.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from tools.provenance import AppendOnlyProvenanceStore as ExistingCoreProvenanceStore

from runtime.core_admission import Capability, CoreActor, CoreAdmission, CorePrincipal
from runtime.memory_patch.contracts.enums import ActorType
from runtime.memory_patch.contracts.records import (
    AuditEvent,
    build_audit_event,
    verify_audit_chain,
    verify_audit_event_hash,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    to_canonical_data,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionView,
)
from runtime.nonzero_cloudops.state.files import (
    atomic_write_private_json,
    locked_private_file,
    open_local_payload,
    read_private_json,
    seal_local_payload,
    validate_local_path,
)
from runtime.tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain

_EVENT_KEYS = frozenset(
    {
        "schema_version",
        "audit_event_id",
        "tenant_id",
        "user_id",
        "kernel_run_id",
        "event_type",
        "sequence_number",
        "previous_event_hash",
        "resource_type",
        "resource_id",
        "state_before",
        "state_after",
        "actor_type",
        "actor_id",
        "content_hashes",
        "created_at",
        "personal_memory_space_id",
        "protected_payload_reference",
        "event_hash",
    }
)
_OUTBOX_KEYS = frozenset(
    {
        "state",
        "event_id",
        "event_digest",
        "operation_digest",
        "proof_id",
        "core_entry_hash",
    }
)
_HEAD_TYPE = "CORE_MEMORY_PATCH_PUBLICATION_HEAD"
_CORE_EVENT = "MEMORY_PATCH_DOMAIN_EVENT"


def decode_audit(record: StoredRecord) -> AuditEvent:
    if record.kind is not RecordKind.AUDIT or set(record.payload) != _EVENT_KEYS:
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
    record.verify()
    payload = dict(record.payload)
    digest = payload.pop("event_hash")
    try:
        payload["created_at"] = datetime.fromisoformat(payload["created_at"])
        payload["actor_type"] = ActorType(payload["actor_type"])
        event = AuditEvent(**payload)
    except (TypeError, ValueError) as error:
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT) from error
    if (
        event.event_hash != digest
        or record.record_id != event.audit_event_id
        or (event.tenant_id, event.user_id, event.personal_memory_space_id)
        != (record.scope.tenant_id, record.scope.owner_id, record.scope.space_id)
    ):
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
    return event


def domain_chain(transaction: TransactionView) -> tuple[AuditEvent, ...]:
    records = transaction.scan(RecordKind.AUDIT, limit=1024)
    if len(records) >= 1024:
        # No silently truncated head; a paginated adapter contract is required
        # before increasing this explicitly bounded local domain quota.
        raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
    events = tuple(
        sorted(
            (decode_audit(record) for record in records),
            key=lambda event: event.sequence_number,
        )
    )
    try:
        verify_audit_chain(events)
    except ValueError as error:
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT) from error
    return events


def append_domain_event(
    transaction: TransactionView,
    operation: OperationBinding,
    *,
    event_id: str,
    proof_id: str,
    resource_id: str,
    before: str | None,
    after: str,
    content_digest: str,
    at: datetime,
) -> StoredRecord:
    events = domain_chain(transaction)
    principal = transaction.context.principal
    actor = {
        CoreActor.OWNER_HUMAN: ActorType.USER,
        CoreActor.HUMAN_REVIEWER: ActorType.HUMAN_REVIEWER,
        CoreActor.COMMIT_SERVICE: ActorType.COMMIT_SERVICE,
        CoreActor.CRITIC: ActorType.CRITIC_PROMPT_LOOP,
    }[principal.actor]
    event = build_audit_event(
        audit_event_id=event_id,
        tenant_id=principal.scope.tenant_id,
        user_id=principal.scope.owner_id,
        kernel_run_id=None,
        event_type=operation.operation_kind,
        sequence_number=len(events),
        previous_event=events[-1] if events else None,
        resource_type="memory_patch_domain",
        resource_id=resource_id,
        state_before=before,
        state_after=after,
        actor_type=actor,
        actor_id=principal.actor_session_id,
        content_hashes={
            "content": content_digest,
            "operation": operation.payload_digest,
        },
        created_at=at,
        personal_memory_space_id=principal.scope.space_id,
    )
    transaction.insert(
        StoredRecord(
            RecordKind.AUDIT, event_id, principal.scope, 1, to_canonical_data(event)
        )
    )
    outbox = StoredRecord(
        RecordKind.OUTBOX,
        proof_id,
        principal.scope,
        1,
        {
            "state": "PENDING",
            "event_id": event_id,
            "event_digest": event.event_hash,
            "operation_digest": canonical_sha256(
                {"scope": principal.scope.binding(), "operation": operation}
            ),
            "proof_id": proof_id,
            "core_entry_hash": None,
        },
    )
    transaction.insert(outbox)
    return outbox


def require_record_audit(
    transaction: TransactionView, record: StoredRecord
) -> AuditEvent:
    """A recomputed row digest alone cannot replace its append-only history."""
    record.verify()
    events = [
        event
        for event in domain_chain(transaction)
        if event.resource_id == record.record_id
    ]
    if not events or events[-1].content_hashes.get("content") != record.payload_digest:
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
    return events[-1]


@dataclass(frozen=True, slots=True, repr=False)
class CorePublicationReceipt:
    proof_id: str
    event_digest: str
    operation_digest: str
    core_entry_hash: str


def _publication_payload(outbox: StoredRecord, event: AuditEvent) -> dict:
    outbox.verify()
    verify_audit_event_hash(event)
    if (
        outbox.kind is not RecordKind.OUTBOX
        or set(outbox.payload) != _OUTBOX_KEYS
        or outbox.payload["state"] not in {"PENDING", "PUBLISHED"}
        or outbox.record_id != outbox.payload["proof_id"]
        or outbox.payload["event_id"] != event.audit_event_id
        or outbox.payload["event_digest"] != event.event_hash
        or (event.tenant_id, event.user_id, event.personal_memory_space_id)
        != (outbox.scope.tenant_id, outbox.scope.owner_id, outbox.scope.space_id)
    ):
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
    return {
        "module": "memory-patch",
        "contract_version": "memory-patch-native-v1",
        "proof_id": outbox.payload["proof_id"],
        "operation_digest": outbox.payload["operation_digest"],
        "domain_event_digest": event.event_hash,
        "authority": "DOMAIN_AUDIT_ONLY",
    }


def mark_published(
    transaction: TransactionView, outbox: StoredRecord, receipt: CorePublicationReceipt
) -> StoredRecord:
    if (
        receipt.proof_id != outbox.record_id
        or receipt.event_digest != outbox.payload["event_digest"]
        or receipt.operation_digest != outbox.payload["operation_digest"]
    ):
        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
    if outbox.payload["state"] == "PUBLISHED":
        if outbox.payload["core_entry_hash"] != receipt.core_entry_hash:
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
        return outbox
    updated = StoredRecord(
        outbox.kind,
        outbox.record_id,
        outbox.scope,
        outbox.revision + 1,
        {
            **outbox.payload,
            "state": "PUBLISHED",
            "core_entry_hash": receipt.core_entry_hash,
        },
    )
    transaction.replace(updated, expected_revision=outbox.revision)
    return updated


class CoreLedgerPublication:
    """An adapter over an explicitly supplied Core store, with no implicit store.

    The Core composition supplies a dedicated writer lease for this store and
    must route its writers through that lease. Constructor and import are inert.
    Existing unanchored logs are never silently adopted.
    """

    def __init__(
        self,
        core: CoreAdmission,
        store: AppendOnlyProvenanceStore,
        *,
        max_bytes: int = 8 * 1024 * 1024,
        after_log_fsync: Callable[[], None] | None = None,
    ) -> None:
        if (
            not isinstance(
                store, (AppendOnlyProvenanceStore, ExistingCoreProvenanceStore)
            )
            or type(max_bytes) is not int
            or not 4096 <= max_bytes <= 64 * 1024 * 1024
        ):
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
        self._core = core
        self._store = store
        self._max_bytes = max_bytes
        self._head = store.provenance_dir / "memory-patch-publication-head.json"
        self._lock = store.provenance_dir / "core-writer.lock"
        self._after_log_fsync = after_log_fsync

    def _check_paths(self) -> None:
        directory = self._store.provenance_dir
        for path in (self._store.log_path, self._head, self._lock):
            validate_local_path(path)
        info = directory.stat()
        if (
            info.st_uid != os.getuid()
            or not stat.S_ISDIR(info.st_mode)
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)

    def _log_fd(self, *, create: bool = False) -> int:
        descriptor = os.open(
            self._store.log_path,
            os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else 0),
            0o600,
        )
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077
            or info.st_size > self._max_bytes
        ):
            os.close(descriptor)
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
        return descriptor

    @staticmethod
    def _checkpoint(entries: list[dict]) -> dict:
        verified = verify_provenance_chain(entries)
        if not verified.ok:
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
        return {
            "entry_count": verified.entry_count,
            "terminal_hash": verified.terminal_hash,
        }

    def _write_head(self, entries: list[dict]) -> None:
        atomic_write_private_json(
            self._head,
            seal_local_payload(self._checkpoint(entries), payload_type=_HEAD_TYPE),
        )

    def initialize(self, principal: CorePrincipal) -> None:
        self._core.require(principal, Capability.MANAGE)
        try:
            self._check_paths()
            with locked_private_file(self._lock, exclusive=True):
                if self._store.log_path.exists() or self._head.exists():
                    raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                descriptor = self._log_fd(create=True)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                self._write_head([])
        except (OSError, ValueError, TypeError) as error:
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT) from error

    def _read(self, *, require_head: bool = True) -> list[dict]:
        os.close(self._log_fd())
        entries = self._store.read_all()
        observed = self._checkpoint(entries)
        if require_head:
            head, _ = open_local_payload(
                read_private_json(self._head), payload_type=_HEAD_TYPE
            )
            if head != observed:
                raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
        return entries

    @staticmethod
    def _receipt(payload: dict, entry: dict) -> CorePublicationReceipt:
        return CorePublicationReceipt(
            payload["proof_id"],
            payload["domain_event_digest"],
            payload["operation_digest"],
            entry["entry_hash"],
        )

    def publish(
        self, principal: CorePrincipal, outbox: StoredRecord, event: AuditEvent
    ) -> CorePublicationReceipt:
        self._core.require(principal, principal.capability, scope=outbox.scope)
        if principal.capability is Capability.READ:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        payload = _publication_payload(outbox, event)
        try:
            self._check_paths()
            with locked_private_file(self._lock, exclusive=True):
                entries = self._read()
                matches = [
                    entry
                    for entry in entries
                    if entry["event_type"] == _CORE_EVENT
                    and entry["payload"].get("proof_id") == payload["proof_id"]
                ]
                if matches:
                    if len(matches) != 1 or matches[0]["payload"] != payload:
                        raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                    return self._receipt(payload, matches[0])
                if self._store.log_path.stat().st_size + 2048 > self._max_bytes:
                    raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
                record = self._store.append_event(_CORE_EVENT, payload)
                descriptor = self._log_fd()
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                if self._after_log_fsync is not None:
                    self._after_log_fsync()
                self._write_head([*entries, record])
                return self._receipt(payload, record)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise MemoryPatchError(ErrorCode.PROVENANCE_PENDING) from error

    def verify(
        self, principal: CorePrincipal, outbox: StoredRecord, event: AuditEvent
    ) -> CorePublicationReceipt:
        self._core.require(principal, principal.capability, scope=outbox.scope)
        payload = _publication_payload(outbox, event)
        try:
            self._check_paths()
            with locked_private_file(self._lock, exclusive=False):
                matches = [
                    entry
                    for entry in self._read()
                    if entry["event_type"] == _CORE_EVENT
                    and entry["payload"].get("proof_id") == payload["proof_id"]
                ]
                if len(matches) != 1 or matches[0]["payload"] != payload:
                    raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                receipt = self._receipt(payload, matches[0])
                if (
                    outbox.payload["state"] != "PUBLISHED"
                    or outbox.payload["core_entry_hash"] != receipt.core_entry_hash
                ):
                    raise MemoryPatchError(ErrorCode.PROVENANCE_PENDING)
                return receipt
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT) from error

    def reconcile_checkpoint(
        self, principal: CorePrincipal, outbox: StoredRecord, event: AuditEvent
    ) -> CorePublicationReceipt:
        """Explicit operator repair of exactly one bound, fsynced publication.

        Does not change domain state, approve a patch, activate, or run a retry.
        A missing log, truncated prefix or unrelated extra entry still denies.
        """
        self._core.require(principal, Capability.MANAGE, scope=outbox.scope)
        payload = _publication_payload(outbox, event)
        try:
            self._check_paths()
            with locked_private_file(self._lock, exclusive=True):
                entries = self._read(require_head=False)
                head, _ = open_local_payload(
                    read_private_json(self._head), payload_type=_HEAD_TYPE
                )
                count = head.get("entry_count")
                if (
                    type(count) is not int
                    or count < 0
                    or len(entries) != count + 1
                    or self._checkpoint(entries[:count]) != head
                ):
                    raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                record = entries[-1]
                if record["event_type"] != _CORE_EVENT or record["payload"] != payload:
                    raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT)
                self._write_head(entries)
                return self._receipt(payload, record)
        except (OSError, ValueError, TypeError, KeyError) as error:
            raise MemoryPatchError(ErrorCode.PROVENANCE_CORRUPT) from error
