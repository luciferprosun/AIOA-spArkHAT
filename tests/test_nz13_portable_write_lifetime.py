"""The existing write port must bind the same physical process/guard lifetime."""
import os
import unittest
from unittest.mock import patch

import test_nz13_portable_core_route as support
from nonzero_cloudops.adapters import portable

from runtime.core_admission import AdmissionError


class PortableWriteLifetimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = support.PortableCoreRouteTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def capture(self, action=None):
        captured = []
        seal = portable.seal_local_payload
        def boundary(*args, **kwargs):
            value = seal(*args, **kwargs)
            port = self.fixture.store._held_lock.write_release
            captured.append(port)
            if action is not None and callable(getattr(port, 'require_live_binding', None)):
                action(port)
            return value
        with patch.object(portable, 'seal_local_payload', new=boundary):
            self.fixture.dispatch()
        self.assertEqual(1, len(captured))
        self.assertTrue(callable(getattr(captured[0], 'require_live_binding', None)),
                        'PURE_PID_AND_PHYSICAL_LIFETIME_PORT_BINDING_NOT_IMPLEMENTED')
        self.assertEqual((1, 1, 0), self.fixture.executor.counters())
        return captured[0]

    def test_current_write_port_checks_live_binding_without_filesystem_work(self):
        completed = []
        def check(port):
            with patch.object(self.fixture.store, '_check_target_guard', side_effect=AssertionError('NO_FS')), \
                    patch.object(self.fixture.store, '_target_guard_identity', side_effect=AssertionError('NO_FS')), \
                    patch.object(self.fixture.store, '_require_managed_ready', side_effect=AssertionError('NO_FS')):
                port.require_live_binding(self.fixture.store)
            completed.append(True)
        self.capture(check)
        self.assertEqual([True], completed)

    def test_forked_process_cannot_use_the_same_live_port(self):
        completed = []
        def check(port):
            child = os.fork()
            if child == 0:
                try:
                    port.require_live_binding(self.fixture.store)
                except (AdmissionError, ValueError, portable.PortablePolicyError):
                    os._exit(0)
                except (AttributeError, TypeError, RuntimeError, OSError):
                    os._exit(2)
                os._exit(1)
            _child, status = os.waitpid(child, 0)
            completed.append(status)
        self.capture(check)
        self.assertEqual([0], completed)

    def test_old_port_does_not_revive_under_a_new_guard(self):
        port = self.capture()
        with self.assertRaises((AdmissionError, ValueError, portable.PortablePolicyError)):
            port.require_live_binding(self.fixture.store)
        with self.fixture.store.target_guard(), \
                self.assertRaises((AdmissionError, ValueError, portable.PortablePolicyError)):
            port.require_live_binding(self.fixture.store)

    def test_poisoned_guard_denies_pure_port_check_and_keeps_target_unchanged(self):
        seal = portable.seal_local_payload
        checks = []
        def boundary(*args, **kwargs):
            value = seal(*args, **kwargs)
            port = self.fixture.store._held_lock.write_release
            self.assertTrue(callable(getattr(port, 'require_live_binding', None)),
                            'PURE_WRITE_PORT_BINDING_NOT_IMPLEMENTED')
            self.fixture.store._held_lock.target_binding['failed'] = True
            with self.assertRaises((AdmissionError, ValueError, portable.PortablePolicyError)):
                port.require_live_binding(self.fixture.store)
            checks.append(True)
            return value
        with patch.object(portable, 'seal_local_payload', new=boundary), \
                self.assertRaises(portable.CloudAdapterUnavailableError):
            self.fixture.dispatch()
        self.assertEqual([True], checks)
        self.assertEqual(self.fixture.before_bytes, self.fixture.path.read_bytes())
        self.assertEqual((1, 0, 0), self.fixture.executor.counters())
        self.fixture.unknown()
