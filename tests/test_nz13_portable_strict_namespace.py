"""Reserved managed namespaces restrict every Store instance before physical release exists.

Administrator fixture preparation is explicit; no product INIT or Core-bound
mutation is certified here. Legacy mutation remains covered outside the reserved
namespace. All tested filesystem changes belong to private temporary fixtures.
"""
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from nonzero_cloudops.adapters import portable
from nonzero_cloudops.state import files


class PortableStrictNamespaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / '.aioa-core-managed-v1' / ('a' * 64) / ('b' * 64) / 'inventory.json'
        self.lock = self.path.with_name('inventory.json.lock')
        values = portable.default_mock_resources()
        self.resources = {(item.resource_type, item.resource_id, item.region): item for item in values}

    def tree(self):
        return sorted(str(path.relative_to(self.root)) for path in self.root.rglob('*'))

    def prepare(self, *, inventory=True, lock=True):
        # Explicit administrator fixture preparation; constructor does not do it.
        for path in (self.path.parents[2], self.path.parents[1], self.path.parent):
            path.mkdir(mode=0o700)
        if inventory:
            payload = portable.PortableStateStore._payload(self.resources, {})
            envelope = files.seal_local_payload(payload, payload_type=portable._INVENTORY_PAYLOAD_TYPE)
            files.atomic_write_private_json(self.path, envelope)
        if lock:
            self.lock.write_bytes(b'')
            self.lock.chmod(0o600)

    def denied(self, action):
        try:
            action()
        except (portable.CloudAdapterUnavailableError, portable.PortablePolicyError,
                files.StateIntegrityError, FileNotFoundError):
            return True
        return False

    def construct_and_read(self):
        portable.PortableStateStore(self.path).assert_ready()

    def test_missing_entire_namespace_creates_no_directories_or_files(self):
        before = self.tree()
        refused = self.denied(self.construct_and_read)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_missing_inventory_never_creates_a_lock_or_virtual_initial_state(self):
        self.prepare(inventory=False, lock=False)
        before = self.tree()
        refused = self.denied(self.construct_and_read)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_missing_lock_is_not_implicitly_created(self):
        self.prepare(lock=False)
        before = self.tree()
        refused = self.denied(self.construct_and_read)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_inventory_loss_after_construction_has_no_virtual_fallback(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        self.path.unlink()
        before = self.tree()
        refused = self.denied(store.assert_ready)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_lock_loss_after_construction_does_not_recreate_it(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        self.lock.unlink()
        before = self.tree()
        refused = self.denied(store.assert_ready)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_malformed_and_unknown_reserved_layout_never_falls_back_to_legacy(self):
        variants = [
            self.root / '.aioa-core-managed-v2' / ('a' * 64) / ('b' * 64) / 'inventory.json',
            self.root / '.aioa-core-managed' / ('a' * 64) / ('b' * 64) / 'inventory.json',
            self.root / '.aioa-core-managed-v1' / 'short' / ('b' * 64) / 'inventory.json',
            self.root / '.aioa-core-managed-v1' / ('A' * 64) / ('b' * 64) / 'inventory.json',
            self.root / '.aioa-core-managed-v1' / ('a' * 64) / ('b' * 64) / 'other.json',
            self.root / '.aioa-core-managed-v1' / ('a' * 64) / 'inventory.json',
            self.root / '.aioa-core-managed-v1' / '..' / 'outside' / 'inventory.json',
        ]
        for path in variants:
            with self.subTest(path=str(path.relative_to(self.root))):
                before = self.tree()
                refused = self.denied(lambda path=path: portable.PortableStateStore(path))
                self.assertEqual(before, self.tree())
                self.assertTrue(refused)

    def test_relative_reserved_path_is_not_a_legacy_alias(self):
        before = self.tree()
        cwd = Path.cwd()
        try:
            os.chdir(self.root)
            refused = self.denied(lambda: portable.PortableStateStore(self.path.relative_to(self.root)))
        finally:
            os.chdir(cwd)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_managed_parent_symlink_is_denied_without_replacement(self):
        self.prepare()
        real = self.path.parent.with_name('real-target')
        self.path.parent.rename(real)
        self.path.parent.symlink_to(real, target_is_directory=True)
        before = self.tree()
        self.assertTrue(self.denied(self.construct_and_read))
        self.assertEqual(before, self.tree())
        self.assertTrue(self.path.parent.is_symlink())

    def test_hardlinked_inventory_is_denied_before_any_write(self):
        self.prepare()
        os.link(self.path, self.root / 'inventory-alias')
        before = self.path.read_bytes()
        self.assertTrue(self.denied(self.construct_and_read))
        self.assertEqual(before, self.path.read_bytes())

    def test_hardlinked_guard_is_denied_without_replacement(self):
        self.prepare()
        os.link(self.lock, self.root / 'guard-alias')
        before = self.lock.stat().st_ino
        self.assertTrue(self.denied(self.construct_and_read))
        self.assertEqual(before, self.lock.stat().st_ino)

    def test_new_unbound_instance_cannot_call_the_shared_write_sink(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        before = self.path.read_bytes()
        calls = []
        write = portable.atomic_write_private_json
        def counted(*args, **kwargs):
            calls.append(True)
            return write(*args, **kwargs)
        with patch.object(portable, 'atomic_write_private_json', counted):
            refused = self.denied(lambda: store._write(self.resources, {}))
        self.assertEqual([], calls)
        self.assertTrue(refused)
        self.assertEqual(before, self.path.read_bytes())

    def test_held_storage_guard_does_not_grant_core_write_permission(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        before = self.path.read_bytes()
        with store.target_guard():
            self.assertTrue(self.denied(lambda: store._write(self.resources, {})))
        self.assertEqual(before, self.path.read_bytes())

    def test_complete_existing_managed_state_can_be_observed_without_mutation(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        before = self.path.read_bytes()
        with store.target_guard():
            observed = store.observe_guarded_inventory()
        self.assertEqual(64, len(observed.state_root))
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(b'', self.lock.read_bytes())

    def test_unregistered_legacy_outside_reserved_namespace_keeps_existing_behavior(self):
        path = self.root / 'legacy/inventory.json'
        store = portable.PortableStateStore(path)
        with store._lock(exclusive=True):
            store._write(self.resources, {})
        other = portable.PortableStateStore(path)
        with other._lock(exclusive=False):
            resources, receipts = other._load()
        self.assertEqual(self.resources, resources)
        self.assertEqual({}, receipts)

    def test_shared_lock_can_refuse_creation_without_changing_legacy_default(self):
        self.assertIn('create', inspect.signature(files.locked_private_file).parameters)
        self.assertIs(True, inspect.signature(files.locked_private_file).parameters['create'].default)
        path = self.root / 'absent.lock'
        with self.assertRaises(FileNotFoundError), files.locked_private_file(path, exclusive=True, create=False):
            self.fail('Missing lock was created')
        self.assertFalse(path.exists())

    def test_existing_noncreating_lock_is_borrowed_and_closed(self):
        self.assertIn('create', inspect.signature(files.locked_private_file).parameters)
        path = self.root / 'existing.lock'
        path.write_bytes(b'')
        path.chmod(0o600)
        inode = path.stat().st_ino
        with files.locked_private_file(path, exclusive=True, create=False) as descriptor:
            self.assertEqual(inode, os.fstat(descriptor).st_ino)
        with self.assertRaises(OSError):
            os.fstat(descriptor)
        self.assertEqual(inode, path.stat().st_ino)

    def test_managed_instance_cannot_be_rebound_to_a_legacy_path_for_writing(self):
        self.prepare()
        store = portable.PortableStateStore(self.path)
        outside = self.root / 'other/inventory.json'
        outside.parent.mkdir(mode=0o700)
        store._path = outside
        self.assertTrue(self.denied(lambda: store._write(self.resources, {})))
        self.assertFalse(outside.exists())

    def test_managed_directory_must_remain_owner_private(self):
        self.prepare()
        self.path.parent.chmod(0o755)
        before = self.path.read_bytes()
        self.assertTrue(self.denied(self.construct_and_read))
        self.assertEqual(before, self.path.read_bytes())

    def test_relative_basename_inside_managed_cwd_cannot_write(self):
        self.prepare()
        before = self.path.stat().st_ino
        cwd = Path.cwd()
        try:
            os.chdir(self.path.parent)
            refused = self.denied(lambda: portable.PortableStateStore(Path('inventory.json'))._write(self.resources, {}))
        finally:
            os.chdir(cwd)
        self.assertEqual(before, self.path.stat().st_ino)
        self.assertTrue(refused)

    def test_relative_child_inside_reserved_ancestor_cannot_create_state(self):
        self.prepare(inventory=False, lock=False)
        before = self.tree()
        cwd = Path.cwd()
        try:
            os.chdir(self.path.parents[2])
            relative = Path('a' * 64) / ('b' * 64) / 'inventory.json'
            refused = self.denied(lambda: portable.PortableStateStore(relative).assert_ready())
        finally:
            os.chdir(cwd)
        self.assertEqual(before, self.tree())
        self.assertTrue(refused)

    def test_relative_legacy_store_reclassified_after_cwd_change(self):
        self.prepare()
        legacy = self.root / 'legacy-cwd'
        legacy.mkdir(mode=0o700)
        before = self.path.stat().st_ino
        cwd = Path.cwd()
        try:
            os.chdir(legacy)
            store = portable.PortableStateStore(Path('inventory.json'))
            os.chdir(self.path.parent)
            refused = self.denied(lambda: store._write(self.resources, {}))
        finally:
            os.chdir(cwd)
        self.assertEqual(before, self.path.stat().st_ino)
        self.assertTrue(refused)
        self.assertFalse((legacy / 'inventory.json').exists())

    def test_interleaved_cwd_change_cannot_retarget_the_atomic_writer(self):
        self.prepare()
        legacy = self.root / 'interleaved-legacy'
        legacy.mkdir(mode=0o700)
        before = self.path.stat().st_ino
        cwd = Path.cwd()
        seal = portable.seal_local_payload
        def interleave(*args, **kwargs):
            value = seal(*args, **kwargs)
            os.chdir(self.path.parent)
            return value
        try:
            os.chdir(legacy)
            store = portable.PortableStateStore(Path('inventory.json'))
            with patch.object(portable, 'seal_local_payload', interleave):
                store._write(self.resources, {})
        finally:
            os.chdir(cwd)
        self.assertEqual(before, self.path.stat().st_ino)
        self.assertTrue((legacy / 'inventory.json').exists())
        self.assertEqual(legacy / 'inventory.json', store.path)
        self.assertTrue(store.path.is_absolute())
