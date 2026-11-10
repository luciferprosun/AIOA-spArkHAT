"""A real managed flock lifetime is data, never effect or approval authority."""
import copy
import fcntl
import os
import pickle
import threading
import unittest
from unittest.mock import patch

import test_nz13_portable_core_route as core_support
from nonzero_cloudops.adapters import portable


class PortableGuardLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = core_support.PortableCoreRouteTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def entry(self):
        method = getattr(self.store, '_current_guard_entry', None)
        self.assertTrue(callable(method), 'PRIVATE_PHYSICAL_GUARD_LIFETIME_NOT_IMPLEMENTED')
        return method()

    def test_outside_guard_has_no_live_entry(self):
        method = getattr(self.store, '_current_guard_entry', None)
        self.assertTrue(callable(method), 'PRIVATE_PHYSICAL_GUARD_LIFETIME_NOT_IMPLEMENTED')
        with self.assertRaises(portable.PortablePolicyError):
            method()

    def test_genuine_outer_acquisition_expires_before_another_call_can_use_it(self):
        with self.store.target_guard():
            entry = self.entry()
            self.assertIs(True, entry.owns_outer_lock)
            self.assertEqual('NONE', entry.authority)
            entry.require_live(self.store)
            entry.require_outer_owner(self.store)
        with self.assertRaises(portable.PortablePolicyError):
            entry.require_live(self.store)

    def test_nested_target_guard_has_a_distinct_nonowning_entry_and_restores_outer(self):
        with self.store.target_guard():
            outer = self.entry()
            with self.store.target_guard():
                inner = self.entry()
                self.assertIsNot(outer, inner)
                self.assertIs(False, inner.owns_outer_lock)
                inner.require_live(self.store)
                with self.assertRaises(portable.PortablePolicyError):
                    inner.require_outer_owner(self.store)
                with self.assertRaises(portable.PortablePolicyError):
                    outer.require_live(self.store)
            self.assertIs(outer, self.entry())
            outer.require_outer_owner(self.store)
            with self.assertRaises(portable.PortablePolicyError):
                inner.require_live(self.store)

    def test_first_target_entry_nested_under_legacy_lock_cannot_claim_outer_acquisition(self):
        with self.store._lock(exclusive=True), self.store.target_guard():
            entry = self.entry()
            self.assertIs(False, entry.owns_outer_lock)
            entry.require_live(self.store)
            with self.assertRaises(portable.PortablePolicyError):
                entry.require_outer_owner(self.store)

    def test_new_acquisition_does_not_revive_old_entry(self):
        with self.store.target_guard():
            old = self.entry()
        with self.store.target_guard():
            new = self.entry()
            self.assertIsNot(old, new)
            new.require_outer_owner(self.store)
            with self.assertRaises(portable.PortablePolicyError):
                old.require_live(self.store)

    def test_copy_deepcopy_and_serialization_cannot_transfer_a_live_entry(self):
        with self.store.target_guard():
            entry = self.entry()
            for operation in (copy.copy, copy.deepcopy, pickle.dumps):
                with self.subTest(operation=operation.__name__), self.assertRaises(TypeError):
                    operation(entry)
            entry.require_outer_owner(self.store)

    def test_another_store_instance_cannot_borrow_the_same_path_witness(self):
        other = portable.PortableStateStore(self.store.path)
        with self.store.target_guard():
            entry = self.entry()
            with self.assertRaises(portable.PortablePolicyError):
                entry.require_live(other)
            entry.require_live(self.store)

    def test_another_thread_cannot_borrow_the_entry(self):
        outcomes = []
        with self.store.target_guard():
            entry = self.entry()
            def check():
                try:
                    entry.require_live(self.store)
                except portable.PortablePolicyError:
                    outcomes.append('DENIED')
                else:
                    outcomes.append('UNEXPECTEDLY_ALLOWED')
            thread = threading.Thread(target=check)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(['DENIED'], outcomes)
            entry.require_live(self.store)

    def test_fork_cannot_inherit_a_live_entry_even_with_the_same_thread_identifier(self):
        with self.store.target_guard():
            entry = self.entry()
            pid = os.fork()
            if pid == 0:
                try:
                    entry.require_live(self.store)
                except portable.PortablePolicyError:
                    os._exit(0)
                except (AttributeError, TypeError, ValueError, RuntimeError, OSError):
                    os._exit(2)
                os._exit(1)
            _pid, status = os.waitpid(pid, 0)
            self.assertEqual(0, status)
            entry.require_live(self.store)

    def test_live_identity_checks_do_no_filesystem_work(self):
        with self.store.target_guard():
            entry = self.entry()
            with patch.object(self.store, '_check_target_guard', side_effect=AssertionError('NO_FS_IN_PURE_CHECK')), \
                    patch.object(self.store, '_target_guard_identity', side_effect=AssertionError('NO_FS_IN_PURE_CHECK')), \
                    patch.object(self.store, '_require_managed_ready', side_effect=AssertionError('NO_FS_IN_PURE_CHECK')), \
                    patch.object(portable.os, 'fstat', side_effect=AssertionError('NO_FS_IN_PURE_CHECK')):
                entry.require_live(self.store)
                entry.require_outer_owner(self.store)

    def test_changed_configuration_cannot_reuse_a_live_entry(self):
        with self.store.target_guard():
            entry = self.entry()
            original = self.store._path
            try:
                self.store._path = original.with_name('different.json')
                with self.assertRaises(portable.PortablePolicyError):
                    entry.require_live(self.store)
            finally:
                self.store._path = original
            entry.require_live(self.store)

    def test_reused_descriptor_number_does_not_revive_an_expired_entry(self):
        with self.store.target_guard():
            entry = self.entry()
            old_descriptor = self.store._held_lock.descriptor
        with self.assertRaises(OSError):
            os.fstat(old_descriptor)
        actual = os.open(self.fixture.base.path / 'owned-fd-reuse.bin',
                         os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if actual != old_descriptor:
                os.dup2(actual, old_descriptor)
            with self.assertRaises(portable.PortablePolicyError):
                entry.require_live(self.store)
        finally:
            os.close(old_descriptor)
            if actual != old_descriptor:
                os.close(actual)

    def test_fork_cleanup_cannot_unlock_the_still_live_parent_flock(self):
        manager = self.store.target_guard()
        manager.__enter__()
        try:
            child = os.fork()
            if child == 0:
                try:
                    manager.__exit__(None, None, None)
                except (AttributeError, TypeError, ValueError, RuntimeError, OSError):
                    os._exit(2)
                os._exit(0)
            _child, status = os.waitpid(child, 0)
            self.assertEqual(0, status)
            probe = os.fork()
            if probe == 0:
                descriptor = os.open(self.store._lock_path, os.O_RDWR | os.O_CLOEXEC)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os._exit(0)
                except OSError:
                    os._exit(2)
                os._exit(1)
            _probe, status = os.waitpid(probe, 0)
            self.assertEqual(0, status, 'CHILD_CLEANUP_RELEASED_PARENT_FLOCK')
        finally:
            manager.__exit__(None, None, None)
