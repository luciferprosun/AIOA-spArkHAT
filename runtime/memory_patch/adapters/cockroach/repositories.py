"""Scoped SQL repositories for the native canonical record contract."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord

TABLES = MappingProxyType(
    {
        RecordKind.SOURCE: "source_records",
        RecordKind.INGESTION: "ingestions",
        RecordKind.OPERATION: "operations",
        RecordKind.SPACE: "spaces",
        RecordKind.PATCH: "patches",
        RecordKind.SHARING: "sharing_proposals",
        RecordKind.CHALLENGE: "challenges",
        RecordKind.APPROVAL: "approvals",
        RecordKind.RECEIPT: "receipts",
        RecordKind.AUDIT: "audit_events",
        RecordKind.OUTBOX: "outbox",
        RecordKind.REVIEW: "reviews",
        RecordKind.LEARNING: "learning_records",
    }
)


def canonical_record(record: StoredRecord) -> str:
    record.verify()
    return canonical_json_bytes(record, exclude_fields=("payload_digest",)).decode(
        "utf-8"
    )


def restore_record(raw: str, digest: str, *, kind: RecordKind, scope: OwnerScope):
    try:
        data = json.loads(raw)
        if set(data) != {"kind", "record_id", "scope", "revision", "payload"}:
            raise ValueError("record fields")
        record = StoredRecord(
            RecordKind(data["kind"]),
            data["record_id"],
            OwnerScope(**data["scope"]),
            data["revision"],
            data["payload"],
        )
        if (
            record.kind is not kind
            or record.scope != scope
            or record.payload_digest != digest
            or canonical_record(record) != raw
        ):
            raise ValueError("record identity")
        return record
    except (TypeError, ValueError, KeyError) as error:
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED) from error


class ScopedSQLRepository:
    """No method accepts a replacement owner, tenant, table name or SQL string."""

    def __init__(self, connection, context, check_active):
        self._connection = connection
        self._context = context
        self._check_active = check_active

    def _table(self, kind):
        self._check_active()
        if type(kind) is not RecordKind:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        return "aioa_memory_patch." + TABLES[kind]

    @property
    def _scope(self):
        return self._context.scope.binding()

    def get(self, kind, record_id):
        table = self._table(kind)
        if type(record_id) is not str or not 1 <= len(record_id) <= 256:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT record_json, record_digest FROM "
                + table
                + " WHERE tenant_id=%s AND owner_id=%s AND space_id=%s "
                "AND slot_id=%s AND record_id=%s",
                (*self._scope, record_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        record = restore_record(*row, kind=kind, scope=self._context.scope)
        if record.record_id != record_id:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        return record

    def scan(self, kind, *, limit, states):
        table = self._table(kind)
        if (
            type(limit) is not int
            or not 1 <= limit <= 1024
            or type(states) is not tuple
            or len(states) > 32
            or any(type(s) is not str or not 1 <= len(s) <= 64 for s in states)
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        query = (
            "SELECT record_json, record_digest FROM "
            + table
            + " WHERE tenant_id=%s AND owner_id=%s AND space_id=%s AND slot_id=%s"
        )
        args = list(self._scope)
        if states:
            query += " AND payload->>'state' = ANY(%s::STRING[])"
            args.append(list(states))
        query += " ORDER BY record_id LIMIT %s"
        args.append(limit)
        with self._connection.cursor() as cursor:
            cursor.execute(query, args)
            rows = cursor.fetchall()
        return tuple(
            restore_record(*row, kind=kind, scope=self._context.scope) for row in rows
        )

    def _record(self, record):
        if type(record) is not StoredRecord or record.scope != self._context.scope:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        record.verify()
        return canonical_record(record)

    def insert(self, record):
        table = self._table(record.kind)
        raw = self._record(record)
        with self._connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO "
                + table
                + " (tenant_id,owner_id,space_id,slot_id,record_id,revision,"
                "record_json,record_digest) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    *self._scope,
                    record.record_id,
                    record.revision,
                    raw,
                    record.payload_digest,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)

    def replace(self, record, *, expected_revision):
        table = self._table(record.kind)
        raw = self._record(record)
        if (
            type(expected_revision) is not int
            or expected_revision < 1
            or record.revision != expected_revision + 1
        ):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        with self._connection.cursor() as cursor:
            cursor.execute(
                "UPDATE " + table + " SET revision=%s,record_json=%s,record_digest=%s "
                "WHERE tenant_id=%s AND owner_id=%s AND space_id=%s AND slot_id=%s "
                "AND record_id=%s AND revision=%s",
                (
                    record.revision,
                    raw,
                    record.payload_digest,
                    *self._scope,
                    record.record_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)


class AnnCapability(str, Enum):
    VERIFIED_SECURE = "VERIFIED_SECURE"
    UNAVAILABLE_SECURELY_ON_CRDB_26_2_5 = "UNAVAILABLE_SECURELY_ON_CRDB_26_2_5"


@dataclass(frozen=True, slots=True)
class VectorSearchCapabilities:
    """Certified adapter profile; obtaining it never probes or changes SQL."""

    certified_engine_version: str = field(default="v26.2.5", init=False)
    default_mode: str = field(default="EXACT", init=False)
    exact: bool = field(default=True, init=False)
    ann: AnnCapability = field(
        default=AnnCapability.UNAVAILABLE_SECURELY_ON_CRDB_26_2_5, init=False
    )

    def descriptor(self):
        return {
            "certified_engine_version": self.certified_engine_version,
            "default_mode": self.default_mode,
            "exact": self.exact,
            "ann": self.ann.value,
            "ann_required_failure_code": ErrorCode.ANN_UNAVAILABLE.value,
        }


@dataclass(frozen=True, slots=True, repr=False)
class VectorSearchResult:
    """Private SQL hits with explicit mode; metadata contains no row identities."""

    hits: tuple
    mode: str = field(default="EXACT", init=False)
    ann_capability: AnnCapability = field(
        default=AnnCapability.UNAVAILABLE_SECURELY_ON_CRDB_26_2_5, init=False
    )

    def metadata(self):
        return {"mode": self.mode, "ann_capability": self.ann_capability.value}


class ScopedVectorRepository:
    """SQL search returns internal identities; Core separately admits evidence.

    The complete Core scope and approved HAT/model predicates precede ranking.
    Exact search uses the primary index and stable ties. This certified profile
    has no safe ANN path. Required ANN is rejected before a search query; a
    future profile must be separately certified before enabling acceleration.
    """

    def __init__(self, connection, context, check_active):
        self._connection, self._context, self._check_active = (
            connection,
            context,
            check_active,
        )

    def capabilities(self):
        self._check_active()
        if self._context.purpose is not Capability.READ:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        return VectorSearchCapabilities()

    def search_with_status(
        self,
        vector,
        *,
        hat_id,
        model_digest,
        limit=20,
        ann_required=False,
        approximate=False,
    ):
        """Return exact hits and truthful mode, or reject required ANN."""
        return VectorSearchResult(
            self.search(
                vector,
                hat_id=hat_id,
                model_digest=model_digest,
                limit=limit,
                ann_required=ann_required,
                approximate=approximate,
            )
        )

    def search(
        self,
        vector,
        *,
        hat_id,
        model_digest,
        limit=20,
        approximate=False,
        ann_required=False,
    ):
        """Compatibility API returning exact hits only; never silently use ANN."""
        from runtime.memory_patch.retrieval.embeddings import (
            EmbeddingVector,
            load_approved_model_spec,
            vector_from_float32_bytes,
        )

        self._check_active()
        if (
            self._context.purpose is not Capability.READ
            or hat_id not in self._context.principal.hat_ids
            or model_digest != load_approved_model_spec().model_digest
            or type(vector) is not EmbeddingVector
            or type(limit) is not int
            or not 1 <= limit <= 100
            or type(approximate) is not bool
            or type(ann_required) is not bool
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if approximate or ann_required:
            # Both the legacy opt-in and the required-capability request deny
            # before SQL. Exact retrieval is never mislabeled as ANN.
            raise MemoryPatchError(ErrorCode.ANN_UNAVAILABLE)
        checked = vector_from_float32_bytes(vector.float32_bytes)
        if (
            checked.values != vector.values
            or checked.bytes_sha256 != vector.bytes_sha256
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        literal = "[" + ",".join(repr(value) for value in checked.values) + "]"
        index = "@chunk_vectors_pkey"
        query = (
            "SELECT v.chunk_id,v.source_id,v.version_id,v.embedding_bytes_digest,"
            "v.embedding <-> %s::VECTOR(384) AS distance,v.embedding::STRING "
            "FROM aioa_memory_patch.chunk_vectors" + index + " v "
            "WHERE v.tenant_id=%s AND v.owner_id=%s AND v.space_id=%s AND v.slot_id=%s "
            "AND v.hat_id=%s AND v.embedding_model_digest=%s "
            "AND EXISTS(SELECT 1 FROM aioa_memory_patch.source_publications p "
            "WHERE (p.tenant_id,p.owner_id,p.space_id,p.slot_id,p.source_id,p.version_id)="
            "(v.tenant_id,v.owner_id,v.space_id,v.slot_id,v.source_id,v.version_id) "
            "AND p.source_status='PUBLISHED' AND p.reviewed_license AND p.publication_proof_id IS NOT NULL) "
            "ORDER BY distance,v.chunk_id LIMIT %s"
        )
        with self._connection.cursor() as cursor:
            cursor.execute(
                query,
                (literal, *self._context.scope.binding(), hat_id, model_digest, limit),
            )
            rows = cursor.fetchall()
        result = []
        for row in rows:
            try:
                stored = EmbeddingVector(tuple(json.loads(row[5])))
                if stored.bytes_sha256 != row[3]:
                    raise ValueError("vector byte identity")
            except (ValueError, TypeError) as error:
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED) from error
            result.append(tuple(row[:5]))
        return tuple(result)
