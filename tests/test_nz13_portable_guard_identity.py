"""A held target guard cannot silently switch its lock or parent directory."""
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nonzero_cloudops.adapters.portable import PortableStateStore
from nonzero_cloudops.adapters.resources import CloudAdapterUnavailableError


class PortableGuardIdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.parent = self.root / 'inventory'
        self.parent.mkdir(mode=0o700)
        self.store = PortableStateStore(self.parent / 'state.json')
        self.lock = self.parent / 'state.json.lock'

    def test_unchanged_guard_remains_reentrant_and_never_initializes_inventory(self):
        with self.store.target_guard(), self.store.target_guard():
            self.store.assert_ready()
            self.assertIsNone(self.store.get_receipt('INERT_MISSING_RECEIPT'))
        self.assertFalse(self.store.path.exists())
        with self.store.target_guard():
            self.store.assert_ready()

    def test_replaced_lock_is_denied_before_any_inventory_load(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                self.lock.rename(self.parent / 'old.lock')
                self.lock.write_bytes(b'')
                self.lock.chmod(0o600)
                self.store.assert_ready()
            self.assertEqual(0, load.call_count)

    def test_hardlinked_lock_is_denied_before_any_inventory_load(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                os.link(self.lock, self.parent / 'alias.lock')
                self.store.assert_ready()
            self.assertEqual(0, load.call_count)

    def test_changed_lock_permissions_are_denied_before_inventory_load(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                self.lock.chmod(0o644)
                self.store.assert_ready()
            self.assertEqual(0, load.call_count)

    def test_replaced_parent_is_denied_before_inventory_load(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                self.parent.rename(self.root / 'old-inventory')
                self.parent.mkdir(mode=0o700)
                self.store.assert_ready()
            self.assertEqual(0, load.call_count)

    def test_parent_symlink_to_same_original_directory_is_denied(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                old = self.root / 'old-inventory'
                self.parent.rename(old)
                self.parent.symlink_to(old, target_is_directory=True)
                self.store.assert_ready()
            self.assertEqual(0, load.call_count)

    def test_detected_substitution_cannot_be_repaired_inside_the_same_guard(self):
        with patch.object(self.store, '_load', wraps=self.store._load) as load:
            with self.assertRaises(CloudAdapterUnavailableError), self.store.target_guard():
                old = self.parent / 'old.lock'
                self.lock.rename(old)
                self.lock.write_bytes(b'')
                self.lock.chmod(0o600)
                with self.assertRaises(CloudAdapterUnavailableError):
                    self.store.assert_ready()
                self.lock.unlink()
                old.rename(self.lock)
                with self.assertRaises(CloudAdapterUnavailableError):
                    self.store.assert_ready()
            self.assertEqual(0, load.call_count)
