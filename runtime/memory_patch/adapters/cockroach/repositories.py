"""Scoped SQL repositories for the native canonical record contract."""

from __future__ import annotations

import json
from types import MappingProxyType

from runtime.core_admission import OwnerScope
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
