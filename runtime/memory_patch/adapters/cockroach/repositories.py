"""Scoped SQL repositories for the native canonical record contract."""

from __future__ import annotations

import json
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


class ScopedVectorRepository:
    """SQL search returns internal identities; Core separately admits evidence.

    The complete Core scope and approved HAT/model predicates precede ranking.
    Exact search uses the primary index and stable ties. ANN is an explicit
    separate operation whose quality must be certified independently.
    """

    def __init__(self, connection, context, check_active):
        self._connection, self._context, self._check_active = (
            connection,
            context,
            check_active,
        )

    def search(self, vector, *, hat_id, model_digest, limit=20, approximate=False):
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
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if approximate:
            # v26.2.5 rejects vector-index acceleration with this required
            # request-context RLS filter (SQLSTATE 42809). Keep this explicit
            # mode unverified; never weaken RLS or silently substitute a scan.
            raise MemoryPatchError(ErrorCode.UNVERIFIED)
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
