"""The existing portable target can share one lifecycle lock with Core.

These are inert temporary-file tests of storage serialization, not approval,
canonical CloudOps integration, cancellation or physical sandbox evidence.
"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from nonzero_cloudops.adapters import portable
from nonzero_cloudops.adapters.resources import CloudAdapterUnavailableError
from nonzero_cloudops.models import ResourceQuery


class PortableTargetGuardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'inventory.json'
        self.store = portable.PortableStateStore(self.path)
        initial = self.store._initial_resources[0]
        self.query = ResourceQuery(resource_type=initial.resource_type,
                                   resource_id=initial.resource_id, region=initial.region)

    def guard(self):
        method = getattr(self.store, 'target_guard', None)
        self.assertTrue(callable(method), 'Missing shared target lifecycle port')
        return method()

    def test_guard_reuses_one_lock_for_nested_public_readers(self):
        guard = self.guard()
        actual = portable.locked_private_file
        with patch.object(portable, 'locked_private_file', wraps=actual) as acquire, guard:
            self.store.assert_ready()
            self.assertEqual(self.query.resource_id,
                             self.store.get_resource(self.query).resource_id)
            with self.guard():
                self.store.assert_ready()
        self.assertEqual(1, acquire.call_count)
        self.assertFalse(self.path.exists(), 'A lifecycle lock must not initialize inventory')

    def test_existing_atomic_writer_can_run_inside_the_same_target_guard(self):
        with self.guard():
            resources, receipts = self.store._load()
            self.store._write(resources, receipts)
            self.store.assert_ready()
        self.assertEqual(0o600, self.path.stat().st_mode & 0o777)
        self.assertEqual(self.query.resource_id,
                         self.store.get_resource(self.query).resource_id)

    def test_shared_lock_cannot_be_silently_promoted_to_exclusive(self):
        self.guard()
        with self.store._lock(exclusive=False), self.assertRaises(CloudAdapterUnavailableError), self.guard():
            self.fail('Shared lock was promoted without a new lifetime')
        with self.guard():
            self.store.assert_ready()

    def test_other_thread_cannot_read_while_the_target_lifetime_is_held(self):
        started, finished = threading.Event(), threading.Event()
        failures = []

        def read():
            started.set()
            try:
                self.store.get_resource(self.query)
            except (ValueError, RuntimeError, OSError) as error:
                failures.append(type(error).__name__)
            finally:
                finished.set()

        guard = self.guard()
        with guard:
            worker = threading.Thread(target=read, daemon=True)
            worker.start()
            self.assertTrue(started.wait(5))
            self.assertFalse(finished.wait(.05), 'A foreign thread bypassed the target guard')
        self.assertTrue(finished.wait(5))
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual([], failures)

    def test_exception_releases_the_existing_file_lock_and_reentrant_state(self):
        with self.assertRaisesRegex(ValueError, 'FIXTURE_STOP'), self.guard(), self.guard():
            raise ValueError('FIXTURE_STOP')
        other = portable.PortableStateStore(self.path)
        other.assert_ready()
        with self.guard():
            self.store.assert_ready()
        self.assertFalse(self.path.exists())
