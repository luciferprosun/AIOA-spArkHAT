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
                for foreign in (False, True):
                    scope = (
                        replace(
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
        cfg.save(
            "C5_RLS_MATRIX.json",
            {
                "STATUS": "PASS",
                "ordinary_reads": matrix,
                "ordinary_scope_role_combinations": 24,
                "scoped_tables": 17,
                "direct_INSERT_cross_owner_denied": 24,
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
