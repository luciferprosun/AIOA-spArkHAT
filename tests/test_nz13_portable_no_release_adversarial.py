"""Live proof isolation, real SQLite retries and retained-history corruption."""
import copy
import json
import os
import pickle
import threading
import unittest
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch

import test_nz13_portable_no_release as support
from nonzero_cloudops.adapters import portable
from nonzero_cloudops.state import files

from runtime.core_admission import Capability
from runtime.memory_patch.adapters.cockroach.repositories import canonical_record
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
)
from runtime.mission.target_projection import CoreTargetProjection
from runtime.mission.target_settlement import (
    FencedNoReleaseCertificate,
    VerifiedNoReleaseSettlement,
    VerifiedTargetSettlement,
)


class PortableNoReleaseAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.reference = support.PortableNoReleaseTests('runTest')
        self.reference.setUp()
        self.addCleanup(self.reference.doCleanups)
        self.f = self.reference.f

    @contextmanager
    def live(self):
        self.reference.start_lost()
        with self.f.adapter.target_guard():
            yield self.f.adapter.verify(self.f.operation, self.f.warrant)

    def apply(self, verified, epoch=1):
        return self.f.base.run_tx(lambda tx: self.f.port.apply_resolution_in_transaction(
            tx, self.f.warrant, epoch, verified))

    def snapshot(self):
        return self.f.base.run_tx(lambda tx: canonical_json_bytes({kind.value:
            [canonical_record(row) for row in tx.scan(kind, limit=1024)] for kind in RecordKind}), Capability.READ)

    def rewrite_private_record(self, row, payload, revision=None):
        # Deliberate damage only to this test's own SQLite; preserve container digest.
        item = StoredRecord(row.kind, row.record_id, row.scope,
                            row.revision if revision is None else revision, payload)
        cursor = self.f.base.factory.db.execute('UPDATE core_records_v1 SET record_json=?,record_digest=?,revision=? '
            'WHERE scope_key=? AND kind=? AND record_id=? AND revision=?',
            (canonical_record(item), item.payload_digest, item.revision,
             canonical_json_bytes(row.scope.binding()).decode(), row.kind.value, row.record_id, row.revision))
        self.assertEqual(1, cursor.rowcount)

    def test_serialized_facts_or_boolean_witness_cannot_settle(self):
        with self.live() as verified:
            facts = FencedNoReleaseCertificate.parse(verified.certificate.to_dict())
            self.assertEqual(facts, verified.certificate)
            self.assertIsNot(facts, verified.certificate)
            for fake in (None, True, {'live': True}, lambda: True, verified._witness):
                with self.subTest(kind=type(fake).__name__), self.assertRaises(ValueError):
                    VerifiedNoReleaseSettlement(verified.resolution, verified.target, facts, fake)
        self.f.unknown()

    def test_live_envelope_cannot_be_copied_deepcopied_or_pickled(self):
        with self.live() as verified:
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                    operation(verified)
        self.f.unknown()

    def test_expired_envelope_cannot_commit_under_another_genuine_guard(self):
        with self.live() as verified:
            pass
        before = self.snapshot()
        with self.f.adapter.target_guard(), \
                self.assertRaisesRegex(ValueError, '^NO_RELEASE_CURRENT_CAPTURE_REQUIRED$') as caught:
            self.apply(verified)
        self.assertEqual(ErrorCode.INTEGRITY_FAILED, caught.exception.code)
        self.assertEqual(before, self.snapshot())
        self.f.unknown()

    def test_another_thread_cannot_borrow_a_live_no_release_envelope(self):
        outcomes = []
        with self.live() as verified:
            def attempt():
                try:
                    verified.require_live(self.f.port, self.f.warrant)
                except (ValueError, portable.PortablePolicyError):
                    outcomes.append('DENIED')
                else:
                    outcomes.append('ACCEPTED')
            thread = threading.Thread(target=attempt)
            thread.start()
            thread.join(timeout=10)
            self.assertFalse(thread.is_alive())
        self.assertEqual(['DENIED'], outcomes)
        self.f.unknown()

    def test_forked_process_cannot_use_a_live_no_release_envelope(self):
        with self.live() as verified:
            child = os.fork()
            if child == 0:
                code = 2
                try:
                    verified.require_live(self.f.port, self.f.warrant)
                except (ValueError, portable.PortablePolicyError):
                    code = 0
                else:
                    code = 1
                finally:
                    os._exit(code)
            _pid, status = os.waitpid(child, 0)
            self.assertEqual(0, status)
        self.f.unknown()

    def test_nested_store_entry_cannot_borrow_the_outer_capture(self):
        with self.live(), self.f.store.target_guard(), self.assertRaises((ValueError, portable.PortablePolicyError)):
            self.f.adapter.verify(self.f.operation, self.f.warrant)
        self.f.unknown()

    def test_any_current_write_port_blocks_no_release_proof(self):
        with self.live():
            self.f.store._held_lock.write_release = object()
            try:
                with self.assertRaises(ValueError):
                    self.f.adapter.verify(self.f.operation, self.f.warrant)
            finally:
                del self.f.store._held_lock.write_release
        self.f.unknown()

    def test_old_applied_envelope_cannot_carry_a_no_release_resolution(self):
        with self.live() as verified:
            old = VerifiedTargetSettlement(verified.resolution, verified.target)
            with self.assertRaisesRegex(ValueError, '^TARGET_OWNED_APPLIED_CERTIFICATE_REQUIRED$'):
                self.apply(old)
        self.f.unknown()

    def test_extra_valid_receipt_in_complete_inventory_denies_no_release(self):
        import test_nz13_portable_domain_input as facts
        reference = facts.PortableDomainInputTests('runTest')
        reference.setUp()
        self.addCleanup(reference.doCleanups)
        extra = reference.historical_receipt()
        self.reference.start_lost()
        with self.f.store.target_guard():
            resources, receipts = self.f.store._load()
            receipts[extra.idempotency_key] = extra
            files.atomic_write_private_json(self.f.path, files.seal_local_payload(
                self.f.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
        with self.assertRaises(ValueError):
            self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.f.unknown()
        self.assertEqual(0, self.f.head()[1]['generation'])
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_serialization_retry_reuses_one_observation_and_has_no_physical_effect(self):
        self.reference.start_lost()
        commit = LocalCoreTransaction.commit
        retried, observations = [], []
        observe = self.f.store.observe_guarded_inventory
        class SerializationFailure(Exception):
            sqlstate = '40001'
        def conflict(tx):
            row = tx.get(RecordKind.OPERATION, self.f.port.head_key)
            if row is not None and row.payload['generation'] == 1 and not retried:
                retried.append(True)
                raise SerializationFailure()
            return commit(tx)
        def readback():
            observed = observe()
            observations.append(observed.state_root)
            return observed
        with patch.object(LocalCoreTransaction, 'commit', new=conflict), \
                patch.object(self.f.store, 'observe_guarded_inventory', side_effect=readback):
            self.reference.settle()
        self.assertEqual([True], retried)
        self.assertEqual(1, len(observations))
        self.assertEqual(3, self.f.head()[0].revision)
        self.assertEqual(1, self.f.head()[1]['generation'])
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_failure_after_history_insert_rolls_back_all_core_records_without_settlement(self):
        self.reference.start_lost()
        before = self.snapshot()
        save = CoreTargetProjection._save_head
        class InjectedCallbackFailure(Exception):
            pass
        def refuse(projection, tx, row, state):
            if projection is self.f.port and state['generation'] == 1:
                raise InjectedCallbackFailure()
            return save(projection, tx, row, state)
        with patch.object(CoreTargetProjection, '_save_head', new=refuse), self.assertRaises(MemoryPatchError) as caught:
            self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.assertEqual(ErrorCode.TRANSACTION_FAILED, caught.exception.code)
        self.assertIsInstance(caught.exception.__cause__, InjectedCallbackFailure)
        self.assertEqual(before, self.snapshot())
        self.f.unknown()
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_missing_settled_history_blocks_every_retained_call(self):
        self.reference.start_lost()
        self.reference.settle()
        self.f.base.delete(self.f.port.history_key(self.f.warrant))
        for operation in (lambda: self.f.route.inspect(self.f.p(Capability.READ), self.f.warrant),
                          lambda: self.f.route.reconcile(self.f.p(), self.f.warrant, 1), self.f.dispatch):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, '^TARGET_HISTORY_INTEGRITY$'):
                operation()
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_changed_certificate_is_denied_even_with_recomputed_outer_history_digest(self):
        self.reference.start_lost()
        self.reference.settle()
        row = self.f.base.run_tx(lambda tx: tx.get(RecordKind.OPERATION,
            self.f.port.history_key(self.f.warrant)), Capability.READ)
        history = json.loads(canonical_json_bytes(row.payload))
        history['no_release_certificate']['intent_digest'] = 'e' * 64
        self.rewrite_private_record(row, history)
        head_row, head = self.f.base.run_tx(lambda tx: (tx.get(RecordKind.OPERATION,
            self.f.port.head_key), None), Capability.READ)
        head = json.loads(canonical_json_bytes(head_row.payload))
        head['history_digest'] = canonical_sha256(history)
        self.rewrite_private_record(head_row, head)
        with self.assertRaisesRegex(ValueError, '^NO_RELEASE_RESOLUTION_BINDING$'):
            self.f.route.inspect(self.f.p(Capability.READ), self.f.warrant)
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_partial_head_rewind_cannot_hide_retained_no_release_history(self):
        original_row, original = self.f.head()
        self.reference.start_lost()
        self.reference.settle()
        current, _head = self.f.head()
        self.rewrite_private_record(current, original, revision=original_row.revision)
        for operation in (lambda: self.f.route.inspect(self.f.p(Capability.READ), self.f.warrant), self.f.dispatch):
            with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, '^TARGET_HISTORY_INTEGRITY$'):
                operation()
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_old_epoch_cannot_commit_an_otherwise_live_no_release_proof(self):
        with self.live() as verified:
            self.f.base.gov.start_epoch(self.f.p(Capability.MANAGE))
            before = self.snapshot()
            with self.assertRaises(MemoryPatchError):
                self.apply(verified)
            self.assertEqual(before, self.snapshot())
        self.f.unknown()

    def test_certificate_parser_rejects_live_flags_and_boolean_revision_slots(self):
        with self.live() as verified:
            value = verified.certificate.to_dict()
            for field in ('expected_head_revision', 'generation', 'intent_revision'):
                changed = {**value, field: True}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    FencedNoReleaseCertificate.parse(changed)
            with self.assertRaises(ValueError):
                FencedNoReleaseCertificate.parse({**value, 'live': True})
            for field in ('workspace', 'generation', 'receipt_digest', 'readback_digest'):
                changed = replace(verified.target, **{field: 99 if field == 'generation' else
                    ('another-workspace' if field == 'workspace' else 'f' * 64)})
                with self.subTest(field=field), self.assertRaises(ValueError):
                    envelope = VerifiedNoReleaseSettlement(verified.resolution, changed,
                        verified.certificate, verified._witness)
                    self.apply(envelope)
        self.f.unknown()

    def test_stopped_governor_allows_truth_reconciliation_without_a_new_effect(self):
        self.reference.start_lost()
        self.f.base.gov.set_kill(self.f.p(Capability.MANAGE), True)
        self.reference.settle()
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())
