"""C5-05..08: real SQL authority, transactions and durable domain outcomes."""

from __future__ import annotations

import hashlib
import secrets
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone

from support.certification_manifest import inputs, make_core, memory_fixture

from runtime.core_admission import Capability
from runtime.memory_patch.adapters.cockroach.migration_controller import (
    catalog,
    load_assets,
)
from runtime.memory_patch.adapters.cockroach.pool import (
    CoreDatabaseHandle,
    DatabasePurpose,
)
from runtime.memory_patch.adapters.cockroach.repositories import (
    TABLES,
    canonical_record,
)
from runtime.memory_patch.errors import (
    CommitOutcomeUnknown,
    ErrorCode,
    MemoryPatchError,
)
from runtime.memory_patch.persistence.idempotency import (
    OperationBinding,
    execute_once,
    reconcile,
)
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
    TransactionRunner,
)


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.cfg = inputs()
        self.core = make_core()
        self.factory = self.cfg.factory(self.core)
        self.addCleanup(self.factory.close)

    def context(self, cap=Capability.MANAGE):
        return TransactionContext(self.core.local_operator(cap), cap)

    def begin(self, cap=Capability.MANAGE):
        tx = self.factory.begin(self.context(cap), attempt=1)
        self.addCleanup(tx.close)
        return tx

    def deny_sql(self, connection, statement, args=(), *, states=("42501",)):
        try:
            connection.execute(statement, args)
        except Exception as error:
            self.assertIn(getattr(error, "sqlstate", None), states)
            return getattr(error, "sqlstate", None)
        self.fail("Required direct SQL denial did not occur")

    def test_05_full_role_scope_matrix_and_force_catalog(self):
        cfg = self.cfg
        shared = "roles-" + secrets.token_hex(8)
        cores = [
            make_core(tenant=t, owner=o, space=shared)
            for t in ("tenant-a", "tenant-b")
            for o in ("owner-a", "owner-b")
        ]
        payloads = {kind: {"fixture": True} for kind in RecordKind}
        payloads.update(
            {
                RecordKind.SPACE: {"state": "EMPTY"},
                RecordKind.PATCH: {
                    "state": "DETECTED",
                    "candidate": {"hat_id": "test-hat"},
                    "candidate_digest": "1" * 64,
                    "logically_deleted": False,
                    "proposal": {
                        "content_hash": "1" * 64,
                        "lifecycle_state": "DETECTED",
                    },
                },
                RecordKind.CHALLENGE: {"state": "OPEN"},
                RecordKind.APPROVAL: {"state": "APPROVED"},
                RecordKind.RECEIPT: {"state": "COMMITTED"},
                RecordKind.AUDIT: {"sequence_number": 0},
                RecordKind.OUTBOX: {"state": "PENDING"},
                RecordKind.REVIEW: {
                    "state": "OPEN",
                    "patch_id": "fixture-patch",
                    "approval_authority": False,
                    "publication_authority": False,
                },
            }
        )
        with cfg.connect("root") as admin:
            for core in cores:
                scope = core.local_operator(Capability.READ).scope
                for kind, payload in payloads.items():
                    if kind in {RecordKind.PATCH, RecordKind.REVIEW}:
                        continue
                    record = StoredRecord(
                        kind, "fixture-" + kind.value, scope, 1, payload
                    )
                    admin.execute(
                        "INSERT INTO aioa_memory_patch."
                        + TABLES[kind]
                        + "(tenant_id,owner_id,space_id,slot_id,record_id,revision,record_json,record_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (
                            *scope.binding(),
                            record.record_id,
                            1,
                            canonical_record(record),
                            record.payload_digest,
                        ),
                    )
                b = scope.binding()
                admin.execute(
                    "INSERT INTO aioa_memory_patch.source_lineage VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*b, "matrix-source", "v1", "1" * 64, "{}"),
                )
                admin.execute(
                    "INSERT INTO aioa_memory_patch.source_publications VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        *b,
                        "matrix-source",
                        "v1",
                        "1" * 64,
                        "PUBLISHED",
                        True,
                        "core-fixture-proof",
                        datetime(2020, 1, 1, tzinfo=timezone.utc),
                        None,
                        datetime(2026, 1, 1, tzinfo=timezone.utc),
                        [],
                        None,
                    ),
                )
                admin.execute(
                    "INSERT INTO aioa_memory_patch.parsed_chunks VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        *b,
                        "matrix-chunk",
                        "matrix-source",
                        "v1",
                        "1" * 64,
                        "a",
                        hashlib.sha256(b"a").hexdigest(),
                    ),
                )
                admin.execute(
                    "INSERT INTO aioa_memory_patch.source_hat_links VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (*b, "matrix-source", "v1", "test-hat", "2" * 64),
                )
                vector = "[1," + ",".join(["0"] * 383) + "]"
                from runtime.memory_patch.retrieval.embeddings import (
                    load_approved_model_spec,
                    normalize_embedding_vector,
                )

                spec = load_approved_model_spec()
                embedding = normalize_embedding_vector([1] + [0] * 383)
                admin.execute(
                    "INSERT INTO aioa_memory_patch.chunk_vectors VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::VECTOR(384))",
                    (
                        *b,
                        "matrix-chunk",
                        "matrix-source",
                        "v1",
                        "test-hat",
                        spec.model_id,
                        spec.model_revision,
                        spec.model_digest,
                        embedding.bytes_sha256,
                        vector,
                    ),
                )
        for core in cores:
            factory = cfg.factory(core)
            for kind, cap in (
                (RecordKind.PATCH, Capability.CANDIDATE),
                (RecordKind.REVIEW, Capability.MANAGE),
            ):
                principal = core.local_operator(cap)
                record = StoredRecord(
                    kind, "fixture-" + kind.value, principal.scope, 1, payloads[kind]
                )
                TransactionRunner(core, factory, owns_factory=False).run(
                    TransactionContext(principal, cap), lambda tx: tx.insert(record)
                )
            factory.close()
        ordinary = {
            "app": set(TABLES.values())
            | {
                "source_lineage",
                "source_publications",
                "parsed_chunks",
                "source_hat_links",
                "chunk_vectors",
            },
            "commit": {
                "spaces",
                "patches",
                "challenges",
                "approvals",
                "receipts",
                "audit_events",
                "outbox",
                "operations",
            },
            "reviewer": {"reviews", "patches", "audit_events", "outbox", "operations"},
            "publication": {
                "source_records",
                "ingestions",
                "operations",
                "audit_events",
                "outbox",
                "source_lineage",
                "source_publications",
                "parsed_chunks",
                "source_hat_links",
                "chunk_vectors",
            },
            "ingestion": {
                "source_records",
                "ingestions",
                "operations",
                "audit_events",
                "outbox",
                "source_lineage",
                "source_publications",
                "parsed_chunks",
                "source_hat_links",
                "chunk_vectors",
            },
            "audit": {"audit_events", "outbox", "operations"},
        }
        manifest = load_assets()[0]
        matrix = []
        for core in cores:
            for role, readable in ordinary.items():
                cap = {
                    "app": Capability.MANAGE,
                    "commit": Capability.COMMIT,
                    "reviewer": Capability.REVIEW,
                    "publication": Capability.EVIDENCE_CAPTURE,
                    "ingestion": Capability.EVIDENCE_CAPTURE,
                    "audit": Capability.READ,
                }[role]
                factory = cfg.factory(
                    core,
                    evidence_role=role
                    if role in {"publication", "ingestion"}
                    else "publication",
                    read_role="audit" if role == "audit" else "app",
                )
                context = TransactionContext(core.local_operator(cap), cap)
                for table in manifest["scoped_tables"]:
                    tx = factory.begin(context, attempt=1)
                    c = tx._lease.connection
                    try:
                        if table in readable:
                            rows = c.execute(
                                "SELECT tenant_id,owner_id,space_id,slot_id FROM aioa_memory_patch."
                                + table
                                + " WHERE space_id=%s",
                                (shared,),
                            ).fetchall()
                            self.assertEqual(rows, [context.scope.binding()])
                        else:
                            self.deny_sql(
                                c, "SELECT tenant_id FROM aioa_memory_patch." + table
                            )
                        matrix.append(
                            {
                                "role": role,
                                "table": table,
                                "tenant_case": context.scope.tenant_id[-1],
                                "owner_case": context.scope.owner_id[-1],
                                "SELECT": "SCOPED_ONE"
                                if table in readable
                                else "DENIED",
                            }
                        )
                    finally:
                        tx.rollback()
                        tx.close()
                # Every role is checked against all four CRUD operations on the
                # shared domain-operation table, with schema-valid canonical data.
                for foreign in (None, "owner", "tenant"):
                    scope = (
                        replace(
                            context.scope,
                            tenant_id="tenant-b"
                            if context.scope.tenant_id == "tenant-a"
                            else "tenant-a",
                        )
                        if foreign == "tenant"
                        else replace(
                            context.scope,
                            owner_id="owner-b"
                            if context.scope.owner_id == "owner-a"
                            else "owner-a",
                        )
                        if foreign
                        else context.scope
                    )
                    record = StoredRecord(
                        RecordKind.OPERATION,
                        "write-" + secrets.token_hex(6),
                        scope,
                        1,
                        {"fixture": True},
                    )
                    tx = factory.begin(context, attempt=1)
                    c = tx._lease.connection
                    try:
                        sql = "INSERT INTO aioa_memory_patch.operations(tenant_id,owner_id,space_id,slot_id,record_id,revision,record_json,record_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)"
                        args = (
                            *scope.binding(),
                            record.record_id,
                            1,
                            canonical_record(record),
                            record.payload_digest,
                        )
                        if foreign or role == "audit":
                            self.deny_sql(c, sql, args)
                        else:
                            self.assertEqual(c.execute(sql, args).rowcount, 1)
                    finally:
                        tx.rollback()
                        tx.close()
                for verb in ("UPDATE", "DELETE"):
                    tx = factory.begin(context, attempt=1)
                    try:
                        sql = (
                            "UPDATE aioa_memory_patch.operations SET revision=revision"
                            if verb == "UPDATE"
                            else "DELETE FROM aioa_memory_patch.operations"
                        ) + " WHERE space_id=%s"
                        self.deny_sql(tx._lease.connection, sql, (shared,))
                    finally:
                        tx.rollback()
                        tx.close()
                factory.close()
        with cfg.connect(cfg.target.migrator_role) as migrator:
            state = catalog(migrator, cfg.prefix)
            self.assertTrue(
                all(
                    row[1] and row[2]
                    for row in state["tables"]
                    if row[0] in manifest["scoped_tables"]
                )
            )
            for role in ("migrator", "schema_owner"):
                if role == "schema_owner":
                    migrator.execute("SET ROLE " + cfg.prefix + "_schema_owner")
                for table in manifest["scoped_tables"]:
                    self.assertEqual(
                        migrator.execute(
                            "SELECT count(*) FROM aioa_memory_patch."
                            + table
                            + " WHERE space_id=%s",
                            (shared,),
                        ).fetchone(),
                        (0,),
                    )
                    self.assertEqual(
                        migrator.execute(
                            "UPDATE aioa_memory_patch."
                            + table
                            + " SET owner_id=owner_id WHERE space_id=%s",
                            (shared,),
                        ).rowcount,
                        0,
                    )
                    self.assertEqual(
                        migrator.execute(
                            "DELETE FROM aioa_memory_patch."
                            + table
                            + " WHERE space_id=%s",
                            (shared,),
                        ).rowcount,
                        0,
                    )
                denied_record = StoredRecord(
                    RecordKind.SPACE,
                    "owner-insert-denied",
                    cores[0].local_operator(Capability.READ).scope,
                    1,
                    {"state": "EMPTY"},
                )
                self.deny_sql(
                    migrator,
                    "INSERT INTO aioa_memory_patch.spaces(tenant_id,owner_id,space_id,slot_id,record_id,revision,record_json,record_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        *denied_record.scope.binding(),
                        denied_record.record_id,
                        1,
                        canonical_record(denied_record),
                        denied_record.payload_digest,
                    ),
                )
                migrator.execute("RESET ROLE")
        with cfg.connect("root") as admin:
            for table in manifest["scoped_tables"]:
                self.assertEqual(
                    admin.execute(
                        "SELECT count(*) FROM aioa_memory_patch."
                        + table
                        + " WHERE space_id=%s",
                        (shared,),
                    ).fetchone(),
                    (4,),
                )
            admin.execute("BEGIN")
            try:
                control = StoredRecord(
                    RecordKind.SPACE,
                    "admin-control",
                    cores[0].local_operator(Capability.READ).scope,
                    1,
                    {"state": "EMPTY"},
                )
                admin.execute(
                    "INSERT INTO aioa_memory_patch.spaces(tenant_id,owner_id,space_id,slot_id,record_id,revision,record_json,record_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        *control.scope.binding(),
                        control.record_id,
                        1,
                        canonical_record(control),
                        control.payload_digest,
                    ),
                )
                self.assertEqual(
                    admin.execute(
                        "UPDATE aioa_memory_patch.spaces SET revision=revision WHERE record_id='admin-control' AND space_id=%s",
                        (shared,),
                    ).rowcount,
                    1,
                )
                self.assertEqual(
                    admin.execute(
                        "DELETE FROM aioa_memory_patch.spaces WHERE record_id='admin-control' AND space_id=%s",
                        (shared,),
                    ).rowcount,
                    1,
                )
            finally:
                admin.rollback()
        cfg.save(
            "C5_RLS_MATRIX.json",
            {
                "STATUS": "PASS",
                "ordinary_reads": matrix,
                "ordinary_scope_role_combinations": 24,
                "scoped_tables": 17,
                "direct_INSERT_cross_owner_denied": 24,
                "direct_INSERT_cross_tenant_denied": 24,
                "migrator_table_owner_INSERT_denied": 2,
                "admin_DML_bypass_control_rolled_back": True,
                "direct_UPDATE_DELETE_immutable_denied": 48,
                "migrator_table_owner_FORCE_rows": 0,
                "admin_bypass_rows_per_table": 4,
                "admin_forbidden_as_application_handle": True,
            },
        )

    def test_05_native_scope_and_repository_roundtrip(self):
        shared = "matrix-" + secrets.token_hex(8)
        cores = [
            make_core(tenant=t, owner=o, space=shared)
            for t in ("tenant-a", "tenant-b")
            for o in ("owner-a", "owner-b")
        ]
        for core in cores:
            factory = self.cfg.factory(core)
            runner = TransactionRunner(core, factory)
            principal = core.local_operator(Capability.MANAGE)
            record = StoredRecord(
                RecordKind.SPACE, "matrix-slot", principal.scope, 1, {"state": "EMPTY"}
            )
            runner.run(
                TransactionContext(principal, Capability.MANAGE),
                lambda tx: tx.insert(record),
            )
            principal = core.local_operator(Capability.READ)
            rows = runner.run(
                TransactionContext(principal, Capability.READ),
                lambda tx: tx.scan(RecordKind.SPACE, limit=100),
            )
            self.assertEqual(rows, (record,))
            tx = factory.begin(
                TransactionContext(principal, Capability.READ), attempt=1
            )
            self.assertEqual(
                tx._lease.connection.execute(
                    "SELECT tenant_id,owner_id FROM aioa_memory_patch.spaces WHERE space_id=%s",
                    (shared,),
                ).fetchall(),
                [record.scope.binding()[:2]],
            )
            tx.rollback()
            tx.close()
            factory.close()
        # Identical space/slot and row ID: each tenant/owner pair sees only itself.
        self.cfg.save(
            "C5_TENANT_OWNER_ROUNDTRIP.json",
            {
                "STATUS": "PASS",
                "tenant_owner_combinations": 4,
                "same_space_slot_record_id": True,
                "native_repository_and_direct_SQL": True,
            },
        )

    def test_05_application_cannot_migrate_or_gain_roles(self):
        statements = (
            "SET ROLE " + self.cfg.target.migrator_role,
            "SET ROLE " + self.cfg.prefix + "_schema_owner",
            "SET ROLE admin",
            "CREATE ROLE forbidden_c5_role",
            "ALTER ROLE " + self.cfg.target.application_role + " CREATELOGIN",
            "ALTER TABLE aioa_memory_patch.spaces DISABLE ROW LEVEL SECURITY",
            "ALTER TABLE aioa_memory_patch.spaces NO FORCE ROW LEVEL SECURITY",
            "CREATE TABLE aioa_memory_patch.forbidden_c5_table(id INT)",
            "CREATE TABLE public.forbidden_c5_table(id INT)",
            "UPDATE aioa_memory_patch.schema_certificate SET state='READY'",
            "INSERT INTO aioa_memory_patch.request_contexts DEFAULT VALUES",
            "SELECT aioa_memory_patch.mint_context_ticket('"
            + "0" * 64
            + "','x',1,'t','o','s','l','manage','owner_human','x',ARRAY['h'],ARRAY['m'],now()+INTERVAL '1 minute')",
        )
        results = []
        for sql in statements:
            with self.cfg.connect(self.cfg.target.application_role) as c:
                results.append(self.deny_sql(c, sql))
        for name in ("root", "admin", "node", "public"):
            with self.assertRaises(MemoryPatchError):
                CoreDatabaseHandle(name, DatabasePurpose.APPLICATION, lambda *_: None)
        self.cfg.save(
            "C5_ROLE_SEPARATION.json",
            {
                "STATUS": "PASS",
                "negative_operations": len(results),
                "all_SQLSTATE": sorted(set(results)),
                "admin_application_handles_denied": 4,
            },
        )

    def test_06_missing_forged_context_and_pool_reset(self):
        record = StoredRecord(
            RecordKind.SPACE, "reset-slot", self.context().scope, 1, {"state": "EMPTY"}
        )
        tx = self.begin()
        tx.insert(record)
        tx.commit()
        tx.close()
        tx = self.begin(Capability.READ)
        connection = tx._lease.connection
        self.assertIsNotNone(tx.get(RecordKind.SPACE, record.record_id))
        tx.commit()
        tx.close()
        # Pool release erases the SQL request context even on the same socket.
        self.assertEqual(
            connection.execute(
                "SELECT count(*) FROM aioa_memory_patch.spaces"
            ).fetchone(),
            (0,),
        )
        connection.execute("BEGIN")
        self.assertEqual(
            connection.execute(
                "SELECT count(*) FROM aioa_memory_patch.spaces"
            ).fetchone(),
            (0,),
        )
        connection.rollback()
        with self.cfg.connect(self.cfg.target.application_role) as c:
            self.assertEqual(
                c.execute("SELECT count(*) FROM aioa_memory_patch.spaces").fetchone(),
                (0,),
            )
            self.deny_sql(
                c,
                "SELECT aioa_memory_patch.set_request_context(%s)",
                ("invented-ticket",),
            )

    def test_06_force_rls_negative_control_copy(self):
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.migration_contract import (
            MigrationAdmission,
            MigrationPlan,
            MigrationUnit,
        )

        cfg = self.cfg
        core = make_core()
        principal = core.local_operator(Capability.MIGRATE)
        controller = cfg.controller(core)
        before = controller.inspect(
            principal, cfg.target, disposable_ownership_confirmed=True
        )
        scratch = "aioa_c5_control_" + secrets.token_hex(6)
        table = scratch + ".scoped_copy"
        statements = (
            "CREATE SCHEMA " + scratch,
            "GRANT USAGE,CREATE ON SCHEMA "
            + scratch
            + " TO "
            + cfg.prefix
            + "_schema_owner",
            "CREATE TABLE "
            + table
            + "(tenant_id STRING,owner_id STRING,space_id STRING,slot_id STRING,id INT PRIMARY KEY)",
            "INSERT INTO "
            + table
            + " VALUES('a','a','control','control',1),('b','b','control','control',2)",
            "ALTER TABLE " + table + " OWNER TO " + cfg.prefix + "_schema_owner",
            "ALTER TABLE " + table + " ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE " + table + " FORCE ROW LEVEL SECURITY",
            "CREATE POLICY scoped_copy_read ON "
            + table
            + " FOR SELECT TO "
            + cfg.prefix
            + "_schema_owner USING(aioa_memory_patch.scope_allows(tenant_id,owner_id,space_id,slot_id,NULL))",
            "REVOKE CREATE ON SCHEMA "
            + scratch
            + " FROM "
            + cfg.prefix
            + "_schema_owner",
            "ALTER TABLE " + table + " NO FORCE ROW LEVEL SECURITY",
            "ALTER TABLE " + table + " FORCE ROW LEVEL SECURITY",
            "DROP SCHEMA " + scratch + " CASCADE",
        )
        digest = canonical_sha256(statements)
        plan = MigrationPlan(
            "plan_" + secrets.token_hex(16),
            cfg.target,
            "Disposable FORCE negative control",
            before.catalog_fingerprint,
            digest,
            (MigrationUnit(1, "0001_force_control.sql", digest),),
        )
        admission = MigrationAdmission(core, cfg.allowlist, cfg.denylist)
        authorization = admission.admit(
            principal, plan, disposable_ownership_confirmed=True
        )
        admission.consume(
            principal,
            plan,
            authorization,
            observed_schema_fingerprint=before.catalog_fingerprint,
        )
        created = False
        try:
            with cfg.connect("root") as admin:
                for statement in statements[:9]:
                    admin.execute(statement)
                    created = True
                with cfg.connect(cfg.target.migrator_role) as owner:
                    owner.execute("SET ROLE " + cfg.prefix + "_schema_owner")
                    self.assertEqual(
                        owner.execute("SELECT count(*) FROM " + table).fetchone(), (0,)
                    )
                    admin.execute(statements[9])
                    self.assertEqual(
                        owner.execute("SELECT count(*) FROM " + table).fetchone(), (2,)
                    )
                    admin.execute(statements[10])
                    self.assertEqual(
                        owner.execute("SELECT count(*) FROM " + table).fetchone(), (0,)
                    )
        finally:
            if created:
                with cfg.connect("root") as admin:
                    admin.execute(statements[11])
        after = controller.inspect(
            core.local_operator(Capability.MIGRATE),
            cfg.target,
            disposable_ownership_confirmed=True,
        )
        self.assertEqual(before.catalog_fingerprint, after.catalog_fingerprint)
        cfg.save(
            "C5_FORCE_RLS_CONTROL.json",
            {
                "STATUS": "PASS",
                "plan_fingerprint": plan.fingerprint,
                "scope": "separate owned disposable copy of the scoped policy; production schema preserved",
                "FORCE_rows": 0,
                "NO_FORCE_rows": 2,
                "restored_FORCE_rows": 0,
                "native_catalog_restored": True,
                "negative_control_detected": True,
                "fixture_copy_disposed": True,
            },
        )

    def test_06_expired_sql_ticket_and_unready_pool(self):
        from runtime.memory_patch.adapters.cockroach.pool import CorePurposePool

        cfg = self.cfg
        context = self.context()
        lease = self.factory.pool.acquire(context)
        try:
            ticket = self.factory.broker.issue(context, lease)
            digest = hashlib.sha256(ticket.encode()).hexdigest()
            with cfg.connect("root") as admin:
                self.assertEqual(
                    admin.execute(
                        "UPDATE aioa_memory_patch.context_grants SET expires_at=now()-INTERVAL '1 minute' WHERE ticket_hash=%s",
                        (digest,),
                    ).rowcount,
                    1,
                )
            self.deny_sql(
                lease.connection,
                "SELECT aioa_memory_patch.set_request_context(%s)",
                (ticket,),
            )
        finally:
            self.factory.pool.release(lease, discard=True)
        before = len(cfg.calls)
        with self.assertRaises(MemoryPatchError):
            CorePurposePool(
                self.core,
                cfg.target,
                cfg.allowlist,
                cfg.denylist,
                tuple(self.factory.pool._handles.items()),
                approved_manifest_digest="0" * 64,
            )
        self.assertEqual(len(cfg.calls), before)
        with cfg.connect("root") as admin:
            original = admin.execute(
                "SELECT manifest_digest,state FROM aioa_memory_patch.schema_certificate WHERE singleton=true"
            ).fetchone()
            try:
                admin.execute(
                    "UPDATE aioa_memory_patch.schema_certificate SET state='MIGRATING' WHERE singleton=true"
                )
                with self.assertRaises(MemoryPatchError):
                    self.factory.begin(context, attempt=1)
                admin.execute(
                    "UPDATE aioa_memory_patch.schema_certificate SET state='READY',manifest_digest=%s WHERE singleton=true",
                    ("0" * 64,),
                )
                with self.assertRaises(MemoryPatchError):
                    self.factory.begin(context, attempt=1)
            finally:
                admin.execute(
                    "UPDATE aioa_memory_patch.schema_certificate SET manifest_digest=%s,state=%s WHERE singleton=true",
                    original,
                )

    def test_06_ticket_bound_to_role_socket_transaction_and_one_use(self):
        context = self.context()
        lease = self.factory.pool.acquire(context)
        self.addCleanup(
            lambda: (
                self.factory.pool.release(lease, discard=True)
                if not lease.released
                else None
            )
        )
        ticket = self.factory.broker.issue(context, lease)
        with self.cfg.connect(self.cfg.target.application_role) as foreign:
            self.deny_sql(
                foreign, "SELECT aioa_memory_patch.set_request_context(%s)", (ticket,)
            )
        c = lease.connection
        c.execute("BEGIN")
        self.assertEqual(
            c.execute(
                "SELECT aioa_memory_patch.set_request_context(%s)", (ticket,)
            ).fetchone(),
            (True,),
        )
        c.commit()
        c.execute("BEGIN")
        self.assertEqual(
            c.execute("SELECT count(*) FROM aioa_memory_patch.spaces").fetchone(), (0,)
        )
        self.deny_sql(c, "SELECT aioa_memory_patch.set_request_context(%s)", (ticket,))
        c.rollback()

    def test_07_real_40001_before_mid_commit_and_exhaustion(self):
        result_rows = []
        for phase, failures in (
            ("before", 2),
            ("mid", 2),
            ("commit", 2),
            ("exhaust", 10),
        ):
            context = self.context()
            binding = OperationBinding.bind(
                "retry-" + phase, "fixture", {"phase": phase}
            )
            factory = self.cfg.factory(self.core)
            attempts = []
            callbacks = []
            sleeps = []
            last = []
            original = factory.begin

            def begin(ctx, *, attempt):
                tx = original(ctx, attempt=attempt)
                attempts.append(attempt)
                last[:] = [tx]
                if phase == "before" and attempt <= failures:
                    try:
                        tx._lease.connection.execute(
                            "SET inject_retry_errors_enabled = on"
                        )
                        tx._lease.connection.execute("SELECT 1")
                    except BaseException:
                        tx.rollback()
                        tx.close()
                        raise
                if phase in {"commit", "exhaust"} and attempt <= failures:
                    tx._lease.connection.execute(
                        "SET inject_retry_errors_on_commit_enabled = on"
                    )
                return tx

            factory.begin = begin
            runner = TransactionRunner(self.core, factory, sleep=sleeps.append)

            def callback(tx):
                callbacks.append(attempts[-1])
                result = execute_once(tx, binding, lambda: {"durable": "one"})
                if phase == "mid" and attempts[-1] <= failures:
                    c = last[0]._lease.connection
                    c.execute("SET inject_retry_errors_enabled = on")
                    c.execute("SELECT 1")
                return result

            if phase == "exhaust":
                with self.assertRaises(MemoryPatchError) as denied:
                    runner.run(context, callback)
                self.assertIs(denied.exception.code, ErrorCode.RETRY_EXHAUSTED)
                expected_attempts = 10
            else:
                result = runner.run(context, callback)
                self.assertFalse(result.replayed)
                expected_attempts = 3
                self.assertTrue(
                    TransactionRunner(self.core, self.factory, owns_factory=False)
                    .run(context, lambda tx: reconcile(tx, binding))
                    .replayed
                )
            # The reconciliation call itself is a separate read transaction.
            self.assertEqual(
                attempts[:expected_attempts], list(range(1, expected_attempts + 1))
            )
            self.assertEqual(len(sleeps), expected_attempts - 1)
            self.assertTrue(all(0 < delay <= 1 for delay in sleeps))
            read = self.factory.begin(self.context(Capability.READ), attempt=1)
            self.assertEqual(
                read.get(RecordKind.OPERATION, binding.idempotency_key) is None,
                phase == "exhaust",
            )
            read.rollback()
            read.close()
            result_rows.append(
                {
                    "phase": phase,
                    "real_server_retry_injection": True,
                    "attempts": expected_attempts,
                    "callback_attempts": callbacks,
                    "backoff": sleeps,
                    "durable_rows": 0 if phase == "exhaust" else 1,
                    "STATUS": "PASS",
                }
            )
            runner.close()
            self.assertFalse(factory.pool._leases)
            self.assertFalse(factory.pool._idle)
        self.cfg.save(
            "C5_SQLSTATE_40001.json",
            {
                "STATUS": "PASS",
                "cases": result_rows,
                "provider_calls": 0,
                "reference": "https://docs.cockroachlabs.com/docs/v26.2/session-variables",
            },
        )

    def test_07_nonretry_and_unknown_acknowledgement(self):
        context = self.context()
        factory = self.cfg.factory(self.core)
        runner = TransactionRunner(
            self.core, factory, sleep=lambda _: self.fail("nonretry error retried")
        )
        calls = []
        original = factory.begin
        active = []

        def begin(ctx, *, attempt):
            calls.append(attempt)
            tx = original(ctx, attempt=attempt)
            active[:] = [tx]
            return tx

        factory.begin = begin

        def invalid(tx):
            active[0]._lease.connection.execute("SELECT 1/0")

        with self.assertRaises(MemoryPatchError):
            runner.run(context, invalid)
        self.assertEqual(calls, [1])
        calls.clear()
        binding = OperationBinding.bind("unknown-ack", "fixture", {})

        def unknown_begin(ctx, *, attempt):
            tx = begin(ctx, attempt=attempt)
            commit = tx.commit

            def unknown():
                commit()
                raise CommitOutcomeUnknown()

            tx.commit = unknown
            return tx

        factory.begin = unknown_begin
        with self.assertRaises(CommitOutcomeUnknown):
            runner.run(
                context,
                lambda tx: execute_once(tx, binding, lambda: {"durable": "one"}),
            )
        self.assertEqual(calls, [1])
        factory.begin = begin
        self.assertTrue(runner.run(context, lambda tx: reconcile(tx, binding)).replayed)
        runner.close()

    def test_08_concurrent_same_key_and_changed_payload(self):
        context = self.context()
        binding = OperationBinding.bind("concurrent", "fixture", {"value": 1})
        barrier = threading.Barrier(2)
        results = []

        def worker():
            factory = self.cfg.factory(self.core)
            runner = TransactionRunner(self.core, factory, sleep=lambda _: None)
            try:
                barrier.wait(timeout=15)
                return runner.run(
                    context,
                    lambda tx: execute_once(tx, binding, lambda: {"durable": "one"}),
                )
            finally:
                runner.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: worker(), range(2)))
        self.assertEqual(sum(not result.replayed for result in results), 1)
        runner = TransactionRunner(self.core, self.factory)
        with self.assertRaises(MemoryPatchError) as conflict:
            runner.run(
                context,
                lambda tx: execute_once(
                    tx,
                    OperationBinding.bind("concurrent", "fixture", {"value": 2}),
                    lambda: {},
                ),
            )
        self.assertIs(conflict.exception.code, ErrorCode.IDEMPOTENCY_CONFLICT)

    def test_08_native_approval_commit_activation_and_outbox(self):
        fixture = memory_fixture()
        self.addCleanup(fixture.close)
        patch_id = fixture.prepare()
        fixture.approve(patch_id)
        self.assertEqual(fixture.read(patch_id).payload["state"], "APPROVED")
        fixture.publish()
        fixture.publish()
        committed = fixture.commit.commit(
            fixture.p(Capability.COMMIT),
            patch_id,
            expected_revision=6,
            operation_key="commit",
        )
        self.assertEqual(committed.outcome["state"], "COMMITTED")
        fixture.publish()
        activated = fixture.commit.activate(
            fixture.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key="activate",
        )
        replay = fixture.commit.activate(
            fixture.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key="activate",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(activated.outcome, replay.outcome)
        fixture.publish()
        fixture.publish()
        self.assertEqual(len(fixture.rows(RecordKind.RECEIPT)), 2)
        events = fixture.rows(RecordKind.AUDIT)
        outbox = fixture.rows(RecordKind.OUTBOX)
        self.assertEqual(len(events), len(outbox))
        self.assertEqual(len({row.payload["event_id"] for row in outbox}), len(outbox))
        self.assertTrue(all(row.payload["state"] == "PUBLISHED" for row in outbox))
        self.assertEqual(fixture.read(patch_id).payload["state"], "ACTIVE")
        self.cfg.save(
            "C5_IDEMPOTENCY_OUTBOX.json",
            {
                "STATUS": "PASS",
                "commit_receipts": 1,
                "activation_receipts": 1,
                "audit_rows": len(events),
                "outbox_rows": len(outbox),
                "duplicate_events": 0,
                "Core_publication_idempotent": True,
                "approval_does_not_execute": True,
            },
        )

    def test_08_domain_retry_and_interrupted_core_publication(self):
        fixture = memory_fixture()
        self.addCleanup(fixture.close)
        patch_id = fixture.prepare()
        fixture.approve(patch_id)
        fixture.publish()
        fixture.commit.commit(
            fixture.p(Capability.COMMIT),
            patch_id,
            expected_revision=6,
            operation_key="atomic-commit",
        )
        fixture.publish()
        before = {
            kind: len(fixture.rows(kind))
            for kind in (RecordKind.RECEIPT, RecordKind.AUDIT, RecordKind.OUTBOX)
        }
        attempts = []
        original_begin = fixture.factory.begin

        def begin(context, *, attempt):
            tx = original_begin(context, attempt=attempt)
            if context.purpose is Capability.ACTIVATE:
                attempts.append(attempt)
                if len(attempts) == 1:
                    tx._lease.connection.execute(
                        "SET inject_retry_errors_on_commit_enabled=on"
                    )
            return tx

        fixture.factory.begin = begin
        try:
            fixture.commit.activate(
                fixture.p(Capability.ACTIVATE),
                patch_id,
                expected_revision=7,
                operation_key="atomic-activation",
            )
        finally:
            fixture.factory.begin = original_begin
        self.assertEqual(attempts, [1, 2])
        self.assertEqual(fixture.read(patch_id).payload["state"], "ACTIVE")
        for kind, count in before.items():
            # One activation receipt and one patch transition each have their
            # own audit/outbox entry, as required by NativeCommit.activate.
            self.assertEqual(
                len(fixture.rows(kind)),
                count + (1 if kind is RecordKind.RECEIPT else 2),
            )
        durable = {kind: fixture.rows(kind) for kind in before}
        original_publish = fixture.publisher.publish
        interruptions = []

        def lost_sink_ack(principal, outbox, event):
            receipt = original_publish(principal, outbox, event)
            if outbox.payload["state"] == "PENDING" and not interruptions:
                interruptions.append(True)
                raise OSError("Controlled C5 sink acknowledgement interruption")
            return receipt

        fixture.publisher.publish = lost_sink_ack
        with self.assertRaises(OSError):
            fixture.publish()
        fixture.publisher.publish = original_publish
        self.assertEqual(interruptions, [True])
        self.assertTrue(
            any(
                row.payload["state"] == "PENDING"
                for row in fixture.rows(RecordKind.OUTBOX)
            )
        )
        self.assertEqual(fixture.read(patch_id).revision, 8)
        fixture.publish()
        fixture.publish()
        self.assertEqual(fixture.rows(RecordKind.RECEIPT), durable[RecordKind.RECEIPT])
        self.assertEqual(fixture.rows(RecordKind.AUDIT), durable[RecordKind.AUDIT])
        outbox = fixture.rows(RecordKind.OUTBOX)
        self.assertEqual(len(outbox), len(durable[RecordKind.OUTBOX]))
        self.assertTrue(all(row.payload["state"] == "PUBLISHED" for row in outbox))
        import json

        entries = [
            json.loads(line) for line in fixture.store.log_path.read_text().splitlines()
        ]
        proofs = [
            row["payload"]["proof_id"]
            for row in entries
            if row.get("payload", {}).get("module") == "memory-patch"
        ]
        self.assertEqual(len(proofs), len(outbox))
        self.assertEqual(len(set(proofs)), len(proofs))
        self.assertFalse(fixture.factory.pool._leases)
        self.cfg.save(
            "C5_DOMAIN_ATOMICITY_AND_SINK_RETRY.json",
            {
                "STATUS": "PASS",
                "actual_40001_at_activation_commit": True,
                "activation_attempts": attempts,
                "durable_activation_receipts": 1,
                "audit_outbox_domain_same_SQL_transaction": True,
                "Core_sink_ack_interruption_then_deduplicated_retry": True,
                "Core_proofs": len(proofs),
                "external_effects_inside_retry_callback": 0,
                "process_crash_or_backup_campaign": False,
            },
        )

    def test_08_native_concurrent_commit_and_activation_race(self):
        fixture = memory_fixture()
        self.addCleanup(fixture.close)
        patch_id = fixture.prepare()
        fixture.approve(patch_id)
        fixture.publish()
        races = []
        for name, capability, revision in (
            ("commit", Capability.COMMIT, 6),
            ("activate", Capability.ACTIVATE, 7),
        ):
            barrier = threading.Barrier(2)
            principal = fixture.p(capability)
            action = getattr(fixture.commit, name)

            def worker(_):
                barrier.wait(timeout=15)
                return action(
                    principal,
                    patch_id,
                    expected_revision=revision,
                    operation_key="race-" + name,
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(worker, range(2)))
            self.assertEqual(sum(not result.replayed for result in results), 1)
            self.assertEqual(results[0].outcome, results[1].outcome)
            self.assertEqual(fixture.read(patch_id).revision, revision + 1)
            fixture.publish()
            races.append(
                {"action": name, "callers": 2, "logical_mutations": 1, "replays": 1}
            )
        self.assertEqual(len(fixture.rows(RecordKind.RECEIPT)), 2)
        self.assertFalse(fixture.factory.pool._leases)
        self.cfg.save(
            "C5_COMMIT_ACTIVATION_RACE.json",
            {
                "STATUS": "PASS",
                "races": races,
                "durable_commit_receipts": 1,
                "durable_activation_receipts": 1,
            },
        )

    def test_05_reviewer_case_scope_and_direct_state_authority(self):
        from runtime.memory_patch.review import NativeReview, ReviewDecision

        fixture = memory_fixture()
        self.addCleanup(fixture.close)
        assigned = fixture.detect(key="review-assigned")
        unassigned = fixture.detect(
            fixture.draft(title="Separate unassigned candidate"), key="review-private"
        )
        self.assertNotEqual(assigned, unassigned)
        review = NativeReview(fixture.lifecycle, fixture.rf.evidence)

        def read_as_reviewer():
            return fixture.runner.run(
                TransactionContext(fixture.p(Capability.REVIEW), Capability.REVIEW),
                lambda tx: (
                    tx.get(RecordKind.PATCH, assigned),
                    tx.get(RecordKind.PATCH, unassigned),
                ),
            )

        self.assertEqual(read_as_reviewer(), (None, None))
        case = review.open_case(
            fixture.p(Capability.MANAGE),
            assigned,
            expected_revision=1,
            operation_key="review-open",
        ).outcome["case_id"]
        visible, private = read_as_reviewer()
        self.assertEqual(visible.record_id, assigned)
        self.assertIsNone(private)
        self.assertEqual(len(review.queue(fixture.p(Capability.REVIEW))), 1)
        principal = fixture.p(Capability.REVIEW)
        review.claim(principal, case, expected_revision=1, operation_key="review-claim")
        review.decide(
            principal,
            case,
            expected_revision=2,
            decision=ReviewDecision.ACCEPT_ADVISORY,
            operation_key="review-decide",
        )
        self.assertEqual(fixture.read(assigned).payload["state"], "DETECTED")
        self.assertFalse(fixture.rows(RecordKind.APPROVAL))
        self.assertFalse(fixture.rows(RecordKind.RECEIPT))
        original = fixture.read(assigned)
        for change in (
            {"state": "APPROVED"},
            {"candidate_digest": "0" * 64},
            {"candidate": {**original.payload["candidate"], "hat_id": "forged-hat"}},
        ):
            record = StoredRecord(
                original.kind,
                original.record_id,
                original.scope,
                2,
                {**original.payload, **change},
            )
            tx = fixture.factory.begin(
                TransactionContext(fixture.p(Capability.MANAGE), Capability.MANAGE),
                attempt=1,
            )
            try:
                self.deny_sql(
                    tx._lease.connection,
                    "UPDATE aioa_memory_patch.patches SET revision=%s,record_json=%s,record_digest=%s WHERE tenant_id=%s AND owner_id=%s AND space_id=%s AND slot_id=%s AND record_id=%s",
                    (
                        2,
                        canonical_record(record),
                        record.payload_digest,
                        *record.scope.binding(),
                        record.record_id,
                    ),
                    states=("42501", "23514"),
                )
            finally:
                tx.rollback()
                tx.close()
        for table in ("approvals", "receipts", "audit_events"):
            tx = fixture.factory.begin(
                TransactionContext(fixture.p(Capability.MANAGE), Capability.MANAGE),
                attempt=1,
            )
            try:
                self.deny_sql(
                    tx._lease.connection,
                    "UPDATE aioa_memory_patch." + table + " SET revision=revision",
                )
            finally:
                tx.rollback()
                tx.close()
        tx = fixture.factory.begin(
            TransactionContext(fixture.p(Capability.REVIEW), Capability.REVIEW),
            attempt=1,
        )
        try:
            record = StoredRecord(
                RecordKind.REVIEW,
                "forged-case",
                principal.scope,
                1,
                {
                    "state": "OPEN",
                    "patch_id": unassigned,
                    "approval_authority": False,
                    "publication_authority": False,
                },
            )
            self.deny_sql(
                tx._lease.connection,
                "INSERT INTO aioa_memory_patch.reviews(tenant_id,owner_id,space_id,slot_id,record_id,revision,record_json,record_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    *record.scope.binding(),
                    record.record_id,
                    1,
                    canonical_record(record),
                    record.payload_digest,
                ),
                states=("42501", "23514"),
            )
        finally:
            tx.rollback()
            tx.close()
        self.cfg.save(
            "C5_REVIEW_AND_STATE_AUTHORITY.json",
            {
                "STATUS": "PASS",
                "uncased_patch_visibility": 0,
                "owner_assigned_case_visibility": 1,
                "review_decision_approval_or_execution": False,
                "direct_immutable_or_skipped_state_updates_denied": 6,
                "reviewer_self_assignment_denied": True,
            },
        )
