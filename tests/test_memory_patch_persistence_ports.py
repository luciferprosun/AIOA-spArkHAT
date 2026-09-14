"""Explicit deterministic fakes; production never imports or constructs these."""

from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.audit import (
    CoreLedgerPublication,
    append_domain_event,
    decode_audit,
    domain_chain,
    mark_published,
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
from runtime.memory_patch.persistence.retry import RetryPolicy, extract_sqlstate
from runtime.tools.provenance import AppendOnlyProvenanceStore, verify_provenance_chain

NOW = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)


def make_admission(
    *,
    owner="test-owner-a",
    tenant="test-tenant-a",
    capabilities=None,
    clock=lambda: NOW,
):
    scope = OwnerScope(tenant, owner, "test-space", "test-slot")
    assignment = LocalOwnerAssignment(
        scope,
        frozenset(Capability if capabilities is None else capabilities),
        frozenset({"test-hat"}),
        frozenset({"test-model"}),
        operator_approved=True,
    )
    return CoreAdmission(assignment, clock=clock)


class StructuredFailure(Exception):
    def __init__(self, sqlstate):
        self.sqlstate = sqlstate
        super().__init__("synthetic database fault")


class FakeFactory:
    """A locked copy-on-write transaction, never an implicit runtime backend."""

    def __init__(self, *, state=None, commit_faults=()):
        self.state = {} if state is None else state
        self.commit_faults = list(commit_faults)
        self.contexts = []
        self.attempts = []
        self.lock = threading.RLock()
        self.opens = self.closes = self.commits = self.rollbacks = 0
        self.closed = False

    def begin(self, context, *, attempt):
        self.lock.acquire()
        self.opens += 1
        self.contexts.append(context)
        self.attempts.append(attempt)
        return FakeTransaction(self, context)

    def close(self):
        self.closed = True


class FakeTransaction:
    def __init__(self, factory, context):
        self.factory = factory
        self.context = context
        self.snapshot = factory.state.copy()
        self.closed = False

    def _key(self, kind, identity):
        return self.context.scope.binding(), kind, identity

    def get(self, kind, record_id):
        return self.snapshot.get(self._key(kind, record_id))

    def scan(self, kind, *, limit, states):
        records = [
            record
            for (scope, record_kind, _), record in self.snapshot.items()
            if scope == self.context.scope.binding()
            and record_kind is kind
            and (not states or record.payload.get("state") in states)
        ]
        return tuple(sorted(records, key=lambda item: item.record_id)[:limit])

    def insert(self, record):
        key = self._key(record.kind, record.record_id)
        if key in self.snapshot:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.snapshot[key] = record

    def replace(self, record, *, expected_revision):
        key = self._key(record.kind, record.record_id)
        prior = self.snapshot.get(key)
        if prior is None or prior.revision != expected_revision:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        self.snapshot[key] = record

    def commit(self):
        fault = (
            self.factory.commit_faults.pop(0) if self.factory.commit_faults else None
        )
        if fault == "40001":
            raise StructuredFailure(fault)
        if fault not in (None, "unknown_after_commit"):
            raise StructuredFailure(fault)
        self.factory.state.clear()
        self.factory.state.update(self.snapshot)
        self.factory.commits += 1
        if fault == "unknown_after_commit":
            raise CommitOutcomeUnknown()

    def rollback(self):
        self.factory.rollbacks += 1

    def close(self):
        if not self.closed:
            self.closed = True
            self.factory.closes += 1
            self.factory.lock.release()


class PersistencePortTests(unittest.TestCase):
    def setUp(self):
        self.admission = make_admission()
        self.principal = self.admission.local_operator(Capability.CANDIDATE)
        self.context = TransactionContext(self.principal, Capability.CANDIDATE)
        self.factory = FakeFactory()
        self.sleeps = []
        self.runner = TransactionRunner(
            self.admission, self.factory, sleep=self.sleeps.append
        )
        self.binding = OperationBinding.bind(
            "test-operation", "candidate", {"text": "approved test input"}
        )

    def mutation(self, tx):
        tx.insert(
            StoredRecord(
                RecordKind.PATCH,
                "patch_one",
                self.principal.scope,
                1,
                {"state": "DETECTED"},
            )
        )
        return {"patch_id": "patch_one"}

    def perform(self):
        return self.runner.run(
            self.context,
            lambda tx: execute_once(tx, self.binding, lambda: self.mutation(tx)),
        )

    def test_unconfigured_denies_without_constructing_a_fake(self):
        with self.assertRaises(MemoryPatchError) as raised:
            TransactionRunner(self.admission).run(
                self.context, lambda tx: self.fail("callback ran")
            )
        self.assertEqual(ErrorCode.BACKEND_UNCONFIGURED, raised.exception.code)
        self.assertEqual(0, self.factory.opens)

    def test_structured_sqlstate_only(self):
        self.assertIsNone(extract_sqlstate(Exception("40001")))
        self.assertEqual("40001", extract_sqlstate(StructuredFailure("40001")))
        self.assertEqual("40001", extract_sqlstate(SimpleNamespace(pgcode="40001")))
        self.assertEqual(
            "40001",
            extract_sqlstate(SimpleNamespace(diag=SimpleNamespace(sqlstate="40001"))),
        )
        self.assertIsNone(
            extract_sqlstate(SimpleNamespace(sqlstate="40001 untrusted text"))
        )

    def test_source_retry_policy_exact_sequence(self):
        policy = RetryPolicy()
        self.assertEqual(10, policy.max_attempts)
        self.assertEqual(
            [0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.0, 1.0],
            [policy.backoff_seconds(i) for i in range(1, 10)],
        )

    def test_full_transaction_repeats_and_commits_once(self):
        self.factory.commit_faults = ["40001", "40001"]
        result = self.perform()
        self.assertFalse(result.replayed)
        self.assertEqual([1, 2, 3], self.factory.attempts)
        self.assertEqual([0.01, 0.02], self.sleeps)
        self.assertEqual(
            (3, 3, 1), (self.factory.opens, self.factory.closes, self.factory.commits)
        )
        self.assertEqual(2, len(self.factory.state))

    def test_ten_attempt_limit_and_no_partial_mutation(self):
        self.factory.commit_faults = ["40001"] * 10
        with self.assertRaises(MemoryPatchError) as raised:
            self.perform()
        self.assertEqual(ErrorCode.RETRY_EXHAUSTED, raised.exception.code)
        self.assertEqual((10, 10), (self.factory.opens, self.factory.closes))
        self.assertEqual({}, self.factory.state)

    def test_nonretryable_callback_rolls_back(self):
        def operation(tx):
            self.mutation(tx)
            raise StructuredFailure("23505")

        with self.assertRaises(MemoryPatchError):
            self.runner.run(self.context, operation)
        self.assertEqual(
            (1, 1, 0), (self.factory.opens, self.factory.closes, self.factory.commits)
        )
        self.assertEqual({}, self.factory.state)

    def test_exact_replay_is_one_logical_mutation(self):
        first = self.perform()
        second = self.perform()
        self.assertEqual(first.outcome, second.outcome)
        self.assertTrue(second.replayed)
        self.assertEqual(2, len(self.factory.state))

    def test_conflicting_replay_does_not_change_state(self):
        self.perform()
        before = self.factory.state.copy()
        self.binding = OperationBinding.bind(
            "test-operation", "candidate", {"text": "different input"}
        )
        with self.assertRaises(MemoryPatchError) as raised:
            self.perform()
        self.assertEqual(ErrorCode.IDEMPOTENCY_CONFLICT, raised.exception.code)
        self.assertEqual(before, self.factory.state)

    def test_unknown_commit_requires_read_only_reconciliation(self):
        self.factory.commit_faults = ["unknown_after_commit"]
        with self.assertRaises(CommitOutcomeUnknown):
            self.perform()
        self.assertEqual(1, self.factory.opens)
        reader = self.admission.local_operator(Capability.READ)
        result = self.runner.run(
            TransactionContext(reader, Capability.READ),
            lambda tx: reconcile(tx, self.binding),
        )
        self.assertEqual({"patch_id": "patch_one"}, dict(result.outcome))
        self.assertTrue(result.replayed)
        self.assertEqual(2, len(self.factory.state))

    def test_missing_reconciliation_does_not_execute(self):
        with self.assertRaises(MemoryPatchError) as raised:
            self.runner.run(self.context, lambda tx: reconcile(tx, self.binding))
        self.assertEqual(ErrorCode.RECOVERY_REQUIRED, raised.exception.code)
        self.assertEqual({}, self.factory.state)

    def test_concurrent_exact_replay(self):
        results, errors = [], []

        def run():
            try:
                results.append(self.perform())
            except Exception as error:
                errors.append(type(error).__name__)

        threads = [threading.Thread(target=run) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertFalse(errors)
        self.assertEqual(8, len(results))
        self.assertEqual(1, sum(not result.replayed for result in results))
        self.assertEqual(2, len(self.factory.state))

    def test_escaped_handle_is_invalidated(self):
        escaped = []
        self.runner.run(self.context, lambda tx: escaped.append(tx))
        with self.assertRaises(MemoryPatchError):
            escaped[0].get(RecordKind.PATCH, "patch_one")

    def test_nested_transaction_is_denied(self):
        with self.assertRaises(MemoryPatchError):
            self.runner.run(
                self.context,
                lambda tx: self.runner.run(self.context, lambda nested: None),
            )
        self.assertEqual(1, self.factory.opens)

    def test_read_purpose_cannot_write(self):
        reader = self.admission.local_operator(Capability.READ)
        with self.assertRaises(MemoryPatchError) as raised:
            self.runner.run(TransactionContext(reader, Capability.READ), self.mutation)
        self.assertEqual(ErrorCode.ADMISSION_DENIED, raised.exception.code)
        self.assertFalse(self.factory.state)

    def test_forged_or_mismatched_context_denied_before_begin(self):
        forged = replace(
            self.principal,
            scope=OwnerScope(
                "another-tenant", "another-owner", "test-space", "test-slot"
            ),
        )
        with self.assertRaises(ValueError):
            self.runner.run(
                TransactionContext(forged, Capability.CANDIDATE), self.mutation
            )
        self.assertEqual(0, self.factory.opens)

    def test_scoped_read_cannot_count_other_owner(self):
        self.perform()
        other = make_admission(owner="test-owner-b")
        reader = other.local_operator(Capability.READ)
        runner = TransactionRunner(other, self.factory)
        result = runner.run(
            TransactionContext(reader, Capability.READ),
            lambda tx: tx.scan(RecordKind.PATCH),
        )
        self.assertEqual((), result)

    def test_mutable_or_tampered_payload_is_rejected(self):
        record = StoredRecord(
            RecordKind.PATCH,
            "patch_one",
            self.principal.scope,
            1,
            {"nested": {"value": 1}},
        )
        with self.assertRaises(TypeError):
            record.payload["nested"]["value"] = 2
        object.__setattr__(record, "payload_digest", "0" * 64)
        with self.assertRaises(MemoryPatchError):
            self.runner.run(self.context, lambda tx: tx.insert(record))

    def test_close_does_not_resume_any_operation(self):
        self.runner.close()
        self.assertTrue(self.factory.closed)
        with self.assertRaises(MemoryPatchError):
            self.perform()
        self.assertEqual(0, self.factory.opens)


class CoreProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        (root / "provenance").mkdir(mode=0o700)
        self.store = AppendOnlyProvenanceStore(root, clock=lambda: NOW)
        self.core = make_admission()
        self.operator = self.core.local_operator(Capability.MANAGE)
        self.principal = self.core.local_operator(Capability.CANDIDATE)
        self.context = TransactionContext(self.principal, Capability.CANDIDATE)
        self.factory = FakeFactory()
        self.runner = TransactionRunner(self.core, self.factory)
        self.publisher = CoreLedgerPublication(self.core, self.store)
        self.publisher.initialize(self.operator)
        self.operation = OperationBinding.bind(
            "audit-operation", "candidate", {"input": "fixture"}
        )

    def prepare(self):
        def mutation(tx):
            patch = StoredRecord(
                RecordKind.PATCH,
                "patch_one",
                self.principal.scope,
                1,
                {"state": "DETECTED"},
            )
            tx.insert(patch)
            return append_domain_event(
                tx,
                self.operation,
                event_id="event_one",
                proof_id="proof_one",
                resource_id="patch_one",
                before=None,
                after="DETECTED",
                content_digest=patch.payload_digest,
                at=NOW,
            )

        return self.runner.run(self.context, mutation)

    def event(self, outbox):
        return self.runner.run(
            self.context,
            lambda tx: decode_audit(
                tx.get(RecordKind.AUDIT, outbox.payload["event_id"])
            ),
        )

    def test_domain_mutation_audit_outbox_are_atomic(self):
        def fail(tx):
            tx.insert(
                StoredRecord(
                    RecordKind.PATCH,
                    "patch_one",
                    self.principal.scope,
                    1,
                    {"state": "DETECTED"},
                )
            )
            append_domain_event(
                tx,
                self.operation,
                event_id="event_one",
                proof_id="proof_one",
                resource_id="patch_one",
                before=None,
                after="DETECTED",
                content_digest="1" * 64,
                at=NOW,
            )
            raise OSError("synthetic interruption before commit")

        with self.assertRaises(MemoryPatchError):
            self.runner.run(self.context, fail)
        self.assertEqual({}, self.factory.state)
        self.assertEqual([], self.store.read_all())

    def test_publication_is_a_separate_deduplicated_core_step(self):
        outbox = self.prepare()
        event = self.event(outbox)
        self.assertEqual("PENDING", outbox.payload["state"])
        self.assertEqual([], self.store.read_all())
        receipt = self.publisher.publish(self.principal, outbox, event)
        self.assertEqual(receipt, self.publisher.publish(self.principal, outbox, event))
        self.assertEqual(1, len(self.store.read_all()))
        published = self.runner.run(
            self.context, lambda tx: mark_published(tx, outbox, receipt)
        )
        self.assertEqual(
            receipt, self.publisher.verify(self.principal, published, event)
        )
        self.assertTrue(verify_provenance_chain(self.store.read_all()).ok)
        self.assertEqual(
            "DOMAIN_AUDIT_ONLY", self.store.read_all()[0]["payload"]["authority"]
        )

    def test_pending_sql_ack_after_core_publication_replays_without_duplicate(self):
        outbox = self.prepare()
        event = self.event(outbox)
        receipt = self.publisher.publish(self.principal, outbox, event)
        with self.assertRaises(MemoryPatchError):
            self.publisher.verify(self.principal, outbox, event)
        restarted = CoreLedgerPublication(self.core, self.store)
        self.assertEqual(receipt, restarted.publish(self.principal, outbox, event))
        self.assertEqual(1, len(self.store.read_all()))

    def test_core_append_checkpoint_interruption_requires_explicit_reconciliation(self):
        outbox = self.prepare()
        event = self.event(outbox)

        def interrupt():
            raise OSError("synthetic checkpoint interruption")

        broken = CoreLedgerPublication(self.core, self.store, after_log_fsync=interrupt)
        with self.assertRaises(MemoryPatchError):
            broken.publish(self.principal, outbox, event)
        with self.assertRaises(MemoryPatchError):
            self.publisher.publish(self.principal, outbox, event)
        receipt = self.publisher.reconcile_checkpoint(self.operator, outbox, event)
        self.assertEqual(receipt, self.publisher.publish(self.principal, outbox, event))
        self.assertEqual(1, len(self.store.read_all()))
        self.assertEqual(
            "DETECTED",
            self.runner.run(
                self.context, lambda tx: tx.get(RecordKind.PATCH, "patch_one")
            ).payload["state"],
        )

    def test_missing_or_truncated_core_chain_is_not_adopted(self):
        outbox = self.prepare()
        event = self.event(outbox)
        self.publisher.publish(self.principal, outbox, event)
        self.store.log_path.write_text("")
        with self.assertRaises(MemoryPatchError):
            self.publisher.publish(self.principal, outbox, event)
        with self.assertRaises(MemoryPatchError):
            self.publisher.reconcile_checkpoint(self.operator, outbox, event)

    def test_tampered_owner_partitioned_domain_chain_denies(self):
        outbox = self.prepare()
        record = next(
            record
            for record in self.factory.state.values()
            if record.kind is RecordKind.AUDIT
        )
        changed = StoredRecord(
            record.kind,
            record.record_id,
            record.scope,
            record.revision,
            {**record.payload, "event_hash": "0" * 64},
        )
        self.factory.state[(record.scope.binding(), record.kind, record.record_id)] = (
            changed
        )
        with self.assertRaises(MemoryPatchError):
            self.runner.run(self.context, domain_chain)
        self.assertEqual("PENDING", outbox.payload["state"])

    def test_wrong_owner_cannot_publish_or_read_core_receipt(self):
        outbox = self.prepare()
        other = make_admission(owner="other-owner")
        with self.assertRaises(ValueError):
            self.publisher.publish(
                other.local_operator(Capability.CANDIDATE), outbox, self.event(outbox)
            )
        self.assertEqual([], self.store.read_all())

    def test_concurrent_core_publication_is_serialized_and_deduplicated(self):
        outbox = self.prepare()
        event = self.event(outbox)
        results, errors = [], []

        def publish():
            try:
                results.append(self.publisher.publish(self.principal, outbox, event))
            except Exception as error:
                errors.append(type(error).__name__)

        threads = [threading.Thread(target=publish) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        self.assertEqual([], errors)
        self.assertEqual(6, len(results))
        self.assertEqual(1, len(set(results)))
        self.assertEqual(1, len(self.store.read_all()))
