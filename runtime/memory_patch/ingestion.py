"""Explicit idempotent ingestion milestones; no scheduler or ambient worker."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.evidence_admission import CoreEvidenceAdmission, InputOrigin
from runtime.memory_patch.acquisition import AcquisitionManifest
from runtime.memory_patch.audit import append_domain_event, require_record_audit
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    normalize_utc_timestamp,
    require_non_empty,
    require_sha256_hex,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.idempotency import (
    OperationBinding,
    OperationResult,
    execute_once,
)
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
    TransactionRunner,
)
from runtime.memory_patch.source_lineage import SourceLicenseStatus


class SagaMilestone(str, Enum):
    REGISTERED = "REGISTERED"
    ACQUIRED_LOCAL = "ACQUIRED_LOCAL"
    HASH_VERIFIED = "HASH_VERIFIED"
    SNAPSHOT_UPLOAD_PENDING = "SNAPSHOT_UPLOAD_PENDING"
    SNAPSHOT_UPLOADED = "SNAPSHOT_UPLOADED"
    SNAPSHOT_LOCK_VERIFIED = "SNAPSHOT_LOCK_VERIFIED"
    PARSED = "PARSED"
    VALIDATED = "VALIDATED"
    PUBLISHED = "PUBLISHED"


MILESTONE_ORDER = tuple(SagaMilestone)


@dataclass(frozen=True, slots=True, repr=False)
class MilestoneReceipt:
    scope: OwnerScope
    saga_id: str
    milestone: SagaMilestone
    snapshot_digest: str
    source_fingerprint: str
    proof_digest: str
    external_reference: str

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not OwnerScope
            or type(self.milestone) is not SagaMilestone
            or self.milestone is SagaMilestone.REGISTERED
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for value in (self.saga_id, self.external_reference):
            require_non_empty(value, "ingestion receipt identity")
            if len(value) > 256 or "://" in value or value.startswith(("/", "\\")):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for value in (self.snapshot_digest, self.source_fingerprint, self.proof_digest):
            require_sha256_hex(value, "ingestion receipt fingerprint")

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256(self)


class IngestionEffectAuthority(Protocol):
    """Core-owned receipt verifier, supplied explicitly with the storage/parser port.

    Constructing MilestoneReceipt does not confer authority. This verifier must
    establish its exact immutable effect/purpose/snapshot binding. Providers and
    request bodies never supply a verifier. It performs no effect or retry.
    """

    def require_receipt(
        self, principal: CorePrincipal, receipt: MilestoneReceipt
    ) -> None: ...


class NativeIngestion:
    def __init__(
        self,
        core: CoreAdmission,
        transactions: TransactionRunner,
        *,
        effects: IngestionEffectAuthority | None = None,
        evidence: CoreEvidenceAdmission | None = None,
    ) -> None:
        self._core = core
        self._transactions = transactions
        self._effects = effects
        self._evidence = evidence

    def register(
        self,
        principal: CorePrincipal,
        manifest: AcquisitionManifest,
        *,
        operation_key: str,
        at: datetime,
    ) -> OperationResult:
        if type(manifest) is not AcquisitionManifest:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        scope = self._core.require(
            principal, Capability.EVIDENCE_CAPTURE, scope=manifest.snapshot.scope
        )
        snapshot = manifest.snapshot
        if (
            snapshot.hat_id not in principal.hat_ids
            or snapshot.origin is not InputOrigin.SOURCE_BYTES
            or manifest.quarantined is not False
            or manifest.license_status
            in {SourceLicenseStatus.UNKNOWN, SourceLicenseStatus.PROHIBITED}
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        operation = OperationBinding.bind(
            operation_key, "ingestion_register", {"manifest": manifest.manifest_digest}
        )
        saga_id = "ingsaga_" + manifest.manifest_digest
        event_id, proof_id = (
            "event_" + secrets.token_hex(16),
            "proof_" + secrets.token_hex(16),
        )
        stamp = normalize_utc_timestamp(at)

        def apply(tx):
            def mutate():
                record = StoredRecord(
                    RecordKind.INGESTION,
                    saga_id,
                    scope,
                    1,
                    {
                        "state": SagaMilestone.REGISTERED.value,
                        "snapshot_digest": snapshot.binding_digest,
                        "source_id": snapshot.source_id,
                        "source_version_id": snapshot.knowledge_version_id,
                        "source_fingerprint": snapshot.content_sha256,
                        "manifest_digest": manifest.manifest_digest,
                        "receipt_digests": (),
                        "created_at": stamp,
                        "updated_at": stamp,
                        "quarantined": False,
                        "disposition": "READY",
                    },
                )
                tx.insert(record)
                append_domain_event(
                    tx,
                    operation,
                    event_id=event_id,
                    proof_id=proof_id,
                    resource_id=saga_id,
                    before=None,
                    after=record.payload["state"],
                    content_digest=record.payload_digest,
                    at=at,
                )
                return {
                    "saga_id": saga_id,
                    "revision": 1,
                    "state": record.payload["state"],
                    "proof_id": proof_id,
                }

            return execute_once(tx, operation, mutate)

        return self._transactions.run(
            TransactionContext(principal, Capability.EVIDENCE_CAPTURE), apply
        )

    def advance(
        self,
        principal: CorePrincipal,
        receipt: MilestoneReceipt,
        *,
        expected_revision: int,
        operation_key: str,
        at: datetime,
    ) -> OperationResult:
        if type(receipt) is not MilestoneReceipt:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self._core.require(principal, Capability.EVIDENCE_CAPTURE, scope=receipt.scope)
        if self._effects is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        self._effects.require_receipt(principal, receipt)
        captured = None
        if receipt.milestone is SagaMilestone.PUBLISHED:
            if self._evidence is None:
                raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
            captured = self._evidence.require_evidence(
                principal, receipt.external_reference
            )
            if captured.source.source_fingerprint != receipt.source_fingerprint:
                raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        operation = OperationBinding.bind(
            operation_key,
            "ingestion_advance",
            {"receipt_digest": receipt.receipt_digest, "revision": expected_revision},
        )
        event_id, proof_id = (
            "event_" + secrets.token_hex(16),
            "proof_" + secrets.token_hex(16),
        )
        stamp = normalize_utc_timestamp(at)

        def apply(tx):
            def mutate():
                record = tx.get(RecordKind.INGESTION, receipt.saga_id)
                if record is None:
                    raise MemoryPatchError(ErrorCode.NOT_FOUND)
                require_record_audit(tx, record)
                current = SagaMilestone(record.payload["state"])
                index = MILESTONE_ORDER.index(current)
                if (
                    record.revision != expected_revision
                    or record.payload["quarantined"] is not False
                    or index + 1 >= len(MILESTONE_ORDER)
                    or MILESTONE_ORDER[index + 1] is not receipt.milestone
                    or record.payload["snapshot_digest"] != receipt.snapshot_digest
                    or record.payload["source_fingerprint"]
                    != receipt.source_fingerprint
                    or (
                        captured is not None
                        and (
                            captured.source.source_id != record.payload["source_id"]
                            or captured.source.source_version_id
                            != record.payload["source_version_id"]
                        )
                    )
                    or stamp < record.payload["updated_at"]
                ):
                    raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
                updated = StoredRecord(
                    record.kind,
                    record.record_id,
                    record.scope,
                    record.revision + 1,
                    {
                        **record.payload,
                        "state": receipt.milestone.value,
                        "updated_at": stamp,
                        "disposition": "COMPLETED"
                        if receipt.milestone is SagaMilestone.PUBLISHED
                        else "READY",
                        "receipt_digests": (
                            *record.payload["receipt_digests"],
                            receipt.receipt_digest,
                        ),
                    },
                )
                tx.replace(updated, expected_revision=record.revision)
                append_domain_event(
                    tx,
                    operation,
                    event_id=event_id,
                    proof_id=proof_id,
                    resource_id=record.record_id,
                    before=current.value,
                    after=updated.payload["state"],
                    content_digest=updated.payload_digest,
                    at=at,
                )
                return {
                    "saga_id": record.record_id,
                    "revision": updated.revision,
                    "state": updated.payload["state"],
                    "proof_id": proof_id,
                }

            return execute_once(tx, operation, mutate)

        return self._transactions.run(
            TransactionContext(principal, Capability.EVIDENCE_CAPTURE), apply
        )

    def quarantine(
        self,
        principal: CorePrincipal,
        saga_id: str,
        *,
        expected_revision: int,
        operation_key: str,
        reason: str,
        at: datetime,
    ) -> OperationResult:
        self._core.require(principal, Capability.EVIDENCE_CAPTURE)
        if reason not in {"PARSING_REJECTED", "SOURCE_CHANGED", "RECEIPT_UNVERIFIED"}:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        operation = OperationBinding.bind(
            operation_key,
            "ingestion_quarantine",
            {"saga_id": saga_id, "revision": expected_revision, "reason": reason},
        )
        event_id, proof_id = (
            "event_" + secrets.token_hex(16),
            "proof_" + secrets.token_hex(16),
        )
        stamp = normalize_utc_timestamp(at)

        def apply(tx):
            def mutate():
                record = tx.get(RecordKind.INGESTION, saga_id)
                if record is None:
                    raise MemoryPatchError(ErrorCode.NOT_FOUND)
                require_record_audit(tx, record)
                if (
                    record.revision != expected_revision
                    or record.payload["quarantined"]
                    or stamp < record.payload["updated_at"]
                ):
                    raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
                updated = StoredRecord(
                    record.kind,
                    record.record_id,
                    record.scope,
                    record.revision + 1,
                    {
                        **record.payload,
                        "quarantined": True,
                        "disposition": "QUARANTINED",
                        "updated_at": stamp,
                    },
                )
                tx.replace(updated, expected_revision=record.revision)
                append_domain_event(
                    tx,
                    operation,
                    event_id=event_id,
                    proof_id=proof_id,
                    resource_id=saga_id,
                    before=record.payload["state"],
                    after="QUARANTINED",
                    content_digest=updated.payload_digest,
                    at=at,
                )
                return {
                    "saga_id": saga_id,
                    "revision": updated.revision,
                    "state": "QUARANTINED",
                    "proof_id": proof_id,
                }

            return execute_once(tx, operation, mutate)

        return self._transactions.run(
            TransactionContext(principal, Capability.EVIDENCE_CAPTURE), apply
        )

    def inspect(self, principal: CorePrincipal, saga_id: str) -> StoredRecord:
        """Restart inspection is read-only and never resumes work automatically."""
        self._core.require(principal, Capability.READ)

        def read(tx):
            record = tx.get(RecordKind.INGESTION, saga_id)
            if record is None:
                raise MemoryPatchError(ErrorCode.NOT_FOUND)
            require_record_audit(tx, record)
            return record

        return self._transactions.run(
            TransactionContext(principal, Capability.READ), read
        )
