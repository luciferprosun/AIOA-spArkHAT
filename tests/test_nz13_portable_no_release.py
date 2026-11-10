"""Real private Core/Portable reconciliation; no product INIT or remote effects."""
import unittest
from unittest.mock import patch

import test_nz13_portable_core_route as support
from nonzero_cloudops.adapters import portable
from nonzero_cloudops.state import files

from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind


class PortableNoReleaseTests(unittest.TestCase):
    def setUp(self):
        self.f = support.PortableCoreRouteTests('runTest')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def start_lost(self):
        manager, lost = self.f.lose_ack(phase='STARTED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.f.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual('STARTED', self.f.head()[1]['in_flight']['phase'])
        self.f.unknown()

    def settle(self):
        try:
            result = self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        except ValueError as error:
            self.fail('FENCED_NO_RELEASE_NOT_IMPLEMENTED: ' + str(error))
        self.assertEqual('NotApplied', result['outcome']['contract_type'])
        self.assertIs(result['grants_replay'], False)
        self.assertEqual('NONE', result['authority'])
        return result

    def test_fresh_guard_settles_started_ack_loss_and_advances_only_core_history(self):
        self.start_lost()
        before_row, before = self.f.head()
        self.settle()
        row, head = self.f.head()
        self.assertEqual(before_row.revision + 1, row.revision)
        self.assertEqual(before['generation'] + 1, head['generation'])
        self.assertNotEqual(before['target_revision'], head['target_revision'])
        self.assertIsNone(head['in_flight'])
        for key in ('state_root', 'resources_root', 'receipts_root'):
            self.assertEqual(before[key], head[key])
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        history = self.f.base.run_tx(lambda tx: tx.get(RecordKind.OPERATION,
            self.f.port.history_key(self.f.warrant)), Capability.READ)
        self.assertEqual('aioa-core-target-history-portable-no-release.v1', history.payload['schema'])
        self.assertNotIn('write_observation', history.payload)
        self.assertEqual('no-effect-certificate', history.payload['resolution']['receipt']['kind'])
        self.assertEqual('CLOSED', self.f.base.liability.inspect(self.f.p(Capability.READ), self.f.task_id)[0].status.value)

    def test_retained_no_release_reconcile_and_dispatch_never_replay_executor(self):
        self.start_lost()
        result = self.settle()
        after = self.f.head()[0].revision
        retained = self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.assertEqual(result['outcome'], retained['outcome'])
        self.assertIs(retained['grants_replay'], False)
        self.assertEqual('NotApplied', self.f.dispatch()['outcome']['contract_type'])
        self.assertEqual(after, self.f.head()[0].revision)
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())

    def test_new_host_store_and_adapter_can_settle_same_checked_persistent_core(self):
        self.start_lost()
        old = self.f.executor
        self.f.store = portable.PortableStateStore(self.f.path)
        self.f.executor = portable.PortableExecutor(self.f.store, clock=lambda: self.f.base.now)
        self.f.adapter = self.f.target.CorePortableTarget(self.f.port, self.f.store, executor=self.f.executor,
            read_principal=self.f.p(Capability.READ), clock=lambda: self.f.base.now)
        self.f.route = self.f.make_route()
        self.settle()
        self.assertEqual((0, 0, 0), old.counters())
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_revoked_session_does_not_require_a_new_effect_permit_to_reconcile_truth(self):
        self.start_lost()
        self.f.route.revoke_session(self.f.p(Capability.MANAGE), self.f.session_id)
        self.settle()
        self.assertEqual((0, 0, 0), self.f.executor.counters())
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())

    def test_same_original_outer_guard_cannot_certify_its_later_started_record(self):
        with self.f.adapter.target_guard():
            self.start_lost()
            with self.assertRaises(ValueError):
                self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.f.unknown()
        self.assertEqual(0, self.f.head()[1]['generation'])
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())

    def test_released_ack_loss_with_missing_receipt_remains_unknown(self):
        manager, lost = self.f.lose_ack(phase='RELEASED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.f.dispatch()
        self.assertEqual([True], lost)
        with self.assertRaises(ValueError):
            self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.f.unknown()
        self.assertEqual('RELEASED', self.f.head()[1]['in_flight']['phase'])
        self.assertEqual(self.f.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 0, 0), self.f.executor.counters())

    def test_complete_resource_root_drift_cannot_be_called_no_release(self):
        self.start_lost()
        with self.f.store.target_guard():
            resources, receipts = self.f.store._load()
            key = next(iter(resources))
            resources[key] = resources[key].model_copy(update={'tags': {'controlled': 'no-release-drift'}})
            files.atomic_write_private_json(self.f.path, files.seal_local_payload(
                self.f.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
        with self.assertRaises(ValueError):
            self.f.route.reconcile(self.f.p(), self.f.warrant, 1)
        self.f.unknown()
        self.assertEqual(0, self.f.head()[1]['generation'])
        self.assertEqual((0, 0, 0), self.f.executor.counters())

    def test_no_store_or_filesystem_work_occurs_inside_any_core_callback(self):
        run = self.f.base.runner.run
        def checked(context, callback):
            def sql(tx):
                with (patch.object(self.f.store, 'observe_guarded_inventory', side_effect=AssertionError('STORE_READ_IN_SQL')),
                      patch.object(self.f.store, '_write', side_effect=AssertionError('STORE_WRITE_IN_SQL')),
                      patch.object(self.f.store, '_target_guard_identity', side_effect=AssertionError('GUARD_READ_IN_SQL')),
                      patch.object(portable, 'read_private_json', side_effect=AssertionError('FILE_READ_IN_SQL')),
                      patch.object(portable, 'atomic_write_private_json', side_effect=AssertionError('FILE_WRITE_IN_SQL'))):
                    return callback(tx)
            return run(context, sql)
        with patch.object(self.f.base.runner, 'run', side_effect=checked):
            self.start_lost()
            self.settle()
        self.assertEqual((0, 0, 0), self.f.executor.counters())
