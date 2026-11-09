"""Full guarded storage facts, not Core registration or owned-effect proof."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from nonzero_cloudops.adapters import portable
from nonzero_cloudops.models import (
    ElasticIpResource,
    LocalExecutionReceipt,
    RemediationOperation,
    generate_proposal_id,
    generate_run_id,
)
from nonzero_cloudops.models.digest import compute_evidence_digest
from nonzero_cloudops.state.files import atomic_write_private_json, seal_local_payload


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode()


class PortableInventorySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'target/inventory.json'
        self.store = portable.PortableStateStore(self.path)

    def api(self, store=None):
        method = getattr(store or self.store, 'observe_guarded_inventory', None)
        self.assertTrue(callable(method), 'STRICT_GUARDED_INVENTORY_API_NOT_IMPLEMENTED')
        return method

    def prepare(self, *, resources=None, receipts=None):
        # Explicit administrator fixture preparation; no product INIT claim.
        with self.store._lock(exclusive=True):
            defaults, _ = self.store._initial_snapshot()
            self.store._write(defaults if resources is None else resources,
                              {} if receipts is None else receipts)

    def observe(self, store=None):
        selected = store or self.store
        method = self.api(selected)
        with selected.target_guard():
            return method()

    def receipt(self, number):
        resources, _ = self.store._initial_snapshot()
        before = next(value for value in resources.values()
                      if isinstance(value, ElasticIpResource) and value.association_id is None)
        run_id = generate_run_id()
        digest = hashlib.sha256(('synthetic-receipt-' + str(number)).encode()).hexdigest()
        values = {
            'run_id': run_id, 'proposal_id': generate_proposal_id(),
            'proposal_hash': digest, 'evidence_hash': digest, 'decision_hash': digest,
            'intent_hash': digest, 'idempotency_key': 'local-exec:' + str(run_id) + ':' + digest,
            'operation_type': RemediationOperation.RELEASE_ELASTIC_IP,
            'target_resource_type': before.resource_type, 'target_resource_id': before.resource_id,
            'before_resource': before, 'after_resource': None,
            'executed_at': datetime(2026, 11, 9, 0, 0, number, tzinfo=UTC),
        }
        provisional = LocalExecutionReceipt.model_construct(**values, receipt_hash='0' * 64)
        return LocalExecutionReceipt(**values,
            receipt_hash=compute_evidence_digest(provisional.receipt_payload()))

    def test_requires_this_thread_exclusive_guard_before_lock_or_read(self):
        method = self.api()
        self.prepare()
        self.store._lock_path.unlink()
        before = self.path.read_bytes()
        with (
            patch.object(portable, 'read_private_json', side_effect=AssertionError('unguarded read')),
            self.assertRaises(portable.PortablePolicyError),
        ):
            method()
        self.assertFalse(self.store._lock_path.exists())
        self.assertEqual(before, self.path.read_bytes())

    def test_another_store_guard_does_not_authorize_this_store(self):
        self.api()
        other = portable.PortableStateStore(Path(self.temp.name) / 'other/inventory.json')
        method = self.api(other)
        with self.store.target_guard(), self.assertRaises(portable.PortablePolicyError):
            method()
        self.assertFalse(other._lock_path.exists())

    def test_guard_in_another_thread_is_not_borrowed(self):
        method = self.api()
        self.prepare()
        outcomes = []

        def observe():
            try:
                method()
            except portable.PortablePolicyError:
                outcomes.append('DENIED')
        with self.store.target_guard():
            worker = threading.Thread(target=observe, daemon=True)
            worker.start()
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), 'unguarded thread blocked on another thread guard')
        worker.join(timeout=5)
        self.assertEqual(['DENIED'], outcomes)

    def test_missing_inventory_never_becomes_a_virtual_baseline(self):
        method = self.api()
        self.store.assert_ready()  # The documented legacy default stays intact.
        self.assertFalse(self.path.exists())
        with self.store.target_guard(), self.assertRaises(portable.CloudAdapterUnavailableError):
            method()
        self.assertFalse(self.path.exists())

    def test_explicit_empty_inventory_is_a_real_snapshot(self):
        self.api()
        self.prepare(resources={})
        observed = self.observe()
        self.assertEqual({'format_version': 1, 'resources': [], 'receipts': []},
                         json.loads(observed.canonical_state))

    def test_complete_canonical_state_and_collection_roots_are_derived(self):
        self.api()
        self.prepare()
        observed = self.observe()
        state = json.loads(observed.canonical_state)
        self.assertEqual(canonical(state), observed.canonical_state)
        self.assertEqual(hashlib.sha256(observed.canonical_state).hexdigest(), observed.state_root)
        self.assertEqual(hashlib.sha256(canonical(state['resources'])).hexdigest(), observed.resources_root)
        self.assertEqual(hashlib.sha256(canonical(state['receipts'])).hexdigest(), observed.receipts_root)
        self.assertEqual(64, len(observed.guard_fingerprint))
        self.assertEqual('NONE', observed.authority)

    def test_snapshot_is_deeply_immutable_and_per_call(self):
        self.api()
        self.prepare()
        with self.store.target_guard():
            first, second = self.api()(), self.api()()
        self.assertIsNot(first, second)
        self.assertEqual(first.canonical_state, second.canonical_state)
        with self.assertRaises(AttributeError):
            first.canonical_state += b'changed'
        with self.assertRaises(AttributeError):
            first.state_root = '0' * 64

    def test_untouched_resource_changes_the_complete_root(self):
        self.api()
        self.prepare()
        before = self.observe()
        with self.store._lock(exclusive=True):
            resources, receipts = self.store._load()
            key = max(resources, key=lambda item: (str(item[0]), item[1], item[2]))
            resources[key] = resources[key].model_copy(update={'tags': {'snapshot': 'changed'}})
            self.store._write(resources, receipts)
        after = self.observe()
        self.assertNotEqual(before.state_root, after.state_root)
        self.assertNotEqual(before.resources_root, after.resources_root)
        self.assertEqual(before.receipts_root, after.receipts_root)

    def test_removing_older_receipt_changes_root_while_newest_is_unchanged(self):
        self.api()
        older, newer = self.receipt(1), self.receipt(2)
        self.prepare(receipts={older.idempotency_key: older, newer.idempotency_key: newer})
        before = self.observe()
        with self.store._lock(exclusive=True):
            resources, receipts = self.store._load()
            del receipts[older.idempotency_key]
            self.store._write(resources, receipts)
        after = self.observe()
        self.assertEqual(before.resources_root, after.resources_root)
        self.assertNotEqual(before.receipts_root, after.receipts_root)
        self.assertNotEqual(before.state_root, after.state_root)

    def test_receipt_contents_are_not_reduced_to_count(self):
        self.api()
        first, second = self.receipt(1), self.receipt(2)
        self.prepare(receipts={first.idempotency_key: first})
        before = self.observe()
        self.prepare(receipts={second.idempotency_key: second})
        after = self.observe()
        self.assertNotEqual(before.receipts_root, after.receipts_root)
        self.assertEqual(before.resources_root, after.resources_root)

    def test_collection_order_does_not_change_canonical_roots(self):
        self.api()
        self.prepare()
        before = self.observe()
        payload = json.loads(before.canonical_state)
        payload['resources'].reverse()
        atomic_write_private_json(self.path, seal_local_payload(payload, payload_type='AIOA_SANDBOX_INVENTORY'))
        after = self.observe()
        self.assertEqual(before.canonical_state, after.canonical_state)

    def test_inventory_atomic_replace_keeps_guard_identity(self):
        self.api()
        self.prepare()
        before, inode = self.observe(), self.path.stat().st_ino
        self.prepare()
        after = self.observe()
        self.assertNotEqual(inode, self.path.stat().st_ino)
        self.assertEqual(before.guard_fingerprint, after.guard_fingerprint)
        self.assertEqual(before.canonical_state, after.canonical_state)

    def test_separate_instances_share_facts_in_sequential_guards(self):
        self.api()
        self.prepare()
        first = self.observe()
        other = portable.PortableStateStore(self.path)
        second = self.observe(other)
        self.assertEqual(first.canonical_state, second.canonical_state)
        self.assertEqual(first.guard_fingerprint, second.guard_fingerprint)

    def test_inventory_deletion_does_not_restore_initial_resources(self):
        self.api()
        self.prepare()
        self.path.unlink()
        with self.store.target_guard(), self.assertRaises(portable.CloudAdapterUnavailableError):
            self.api()()
        self.assertFalse(self.path.exists())

    def test_hardlinked_inventory_is_denied_without_rewrite(self):
        self.api()
        self.prepare()
        before = self.path.read_bytes()
        alias = self.path.with_name('alias.json')
        os.link(self.path, alias)
        with self.store.target_guard(), self.assertRaises(portable.CloudAdapterUnavailableError):
            self.api()()
        self.assertEqual(before, alias.read_bytes())
        self.assertEqual(before, self.path.read_bytes())

    def test_legacy_load_rejects_boolean_payload_version(self):
        self.prepare()
        payload = {'format_version': True, 'resources': [], 'receipts': []}
        atomic_write_private_json(self.path, seal_local_payload(payload, payload_type='AIOA_SANDBOX_INVENTORY'))
        with self.store._lock(exclusive=False), self.assertRaises(portable.CloudAdapterUnavailableError):
            self.store._load()

    def test_boolean_payload_version_is_denied(self):
        self.api()
        self.prepare()
        payload = {'format_version': True, 'resources': [], 'receipts': []}
        atomic_write_private_json(self.path, seal_local_payload(payload, payload_type='AIOA_SANDBOX_INVENTORY'))
        with self.store.target_guard(), self.assertRaises(portable.CloudAdapterUnavailableError):
            self.api()()

    def test_guard_substitution_poison_is_checked_before_snapshot(self):
        self.api()
        self.prepare()
        with self.assertRaises(portable.CloudAdapterUnavailableError), self.store.target_guard():
            saved = self.store._lock_path.with_name('saved.lock')
            self.store._lock_path.rename(saved)
            self.store._lock_path.write_bytes(b'')
            self.store._lock_path.chmod(0o600)
            with self.assertRaises(portable.CloudAdapterUnavailableError):
                self.api()()
            self.store._lock_path.unlink()
            saved.rename(self.store._lock_path)
            with self.assertRaises(portable.CloudAdapterUnavailableError):
                self.api()()

    def test_inventory_symlink_is_denied_without_touching_target(self):
        self.api()
        self.prepare()
        target = self.path.with_name('preserved.json')
        target.write_bytes(self.path.read_bytes())
        target.chmod(0o600)
        self.path.unlink()
        self.path.symlink_to(target)
        before = target.read_bytes()
        with self.store.target_guard(), self.assertRaises(portable.CloudAdapterUnavailableError):
            self.api()()
        self.assertEqual(before, target.read_bytes())

    def test_changed_store_path_cannot_borrow_old_named_guard(self):
        self.api()
        self.prepare()
        with self.store.target_guard():
            original = self.store._path
            self.store._path = original.with_name('other.json')
            try:
                with self.assertRaises(portable.PortablePolicyError):
                    self.api()()
            finally:
                self.store._path = original


if __name__ == '__main__':
    unittest.main()
