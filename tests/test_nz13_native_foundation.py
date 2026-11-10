"""Actual Native/Core integration with owned synthetic OS/TLS qualification only."""
import copy
import json
import os
import threading
import unittest
from unittest.mock import patch

import nz13_native_foundation_support as fx

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import (
    LocalCoreTransaction,
    RecordKind,
    TransactionContext,
)
from runtime.mission.governor import ReservationRequest


class NativeFoundationTests(unittest.TestCase):
    def setUp(self):
        self.host, self.data = fx.new_host(self)
        self.f = self.host.foundation

    def ready(self):
        fx.fixture_tls(self.host)
        fx.initialize(self.host)

    def inspect(self):
        return self.f.governor.inspect(self.host.core.local_operator(Capability.READ))

    def rows(self):
        principal = self.host.core.local_operator(Capability.READ)
        return self.host.runner.run(TransactionContext(principal, Capability.READ), lambda tx:
            canonical_json_bytes({kind.value: [(row.record_id, row.payload_digest) for row in tx.scan(kind, limit=1024)]
                                  for kind in (RecordKind.OPERATION, RecordKind.APPROVAL, RecordKind.AUDIT, RecordKind.OUTBOX)}))

    def test_opt_in_reuses_exact_authority_objects_without_starting_epoch_or_adapters(self):
        self.assertIs(self.f.core, self.host.core)
        self.assertIs(self.f.runner, self.host.runner)
        self.assertIs(self.f.ledger, self.host.ledger)
        self.assertIs(self.host.runtime._memory_patch_admission, self.f.core)
        self.assertIs(self.f.intent_journal.ledger, self.f.ledger)
        self.assertIs(self.f.intent_journal.governor, self.f.governor)
        self.assertEqual('CAPACITY_ADMIN', self.f.lifecycle.phase.value)
        self.assertEqual((0, 0), (self.inspect()['version'], self.inspect()['epoch']))
        self.assertIsNone(self.host.runtime.provider_manager)
        self.assertIsNone(self.host.runtime.executor)
        self.assertEqual(0, self.host.model_calls())

    def test_capture_before_tls_denies_and_initialize_cannot_take_over_history(self):
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        with self.assertRaises(AdmissionError):
            self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        self.ready()
        before = self.rows()
        with self.assertRaises(ValueError): fx.initialize(self.host)
        self.assertEqual(before, self.rows())

    def test_actual_domain_gates_precede_sql_claim_live_binding_and_github_preflight(self):
        self.ready()
        from runtime.meta_hackathon import agent_operations, github_write
        owner = self.host.core.local_operator(Capability.OWNER_APPROVAL)
        with patch.object(self.host.runner, 'run', side_effect=AssertionError('SQL_BEFORE_GATE')), \
             patch.object(github_write.github_remote, 'read_demo_base', side_effect=AssertionError('PREFLIGHT_BEFORE_GATE')):
            for action in (lambda: self.host.missions.run('meta-fake', 'a' * 64, owner),
                           lambda: self.host.missions.bind_live_request('meta-fake', None, None),
                           lambda: agent_operations.run(self.host.missions, 'agent-' + 'a' * 32, 'a' * 64, owner),
                           lambda: agent_operations.reconcile(self.host.missions, 'agent-' + 'a' * 32, owner),
                           lambda: github_write.propose(self.host, {}, {}),
                           lambda: github_write.dispatch(self.host, owner, {'op': 'github_write_approve'})):
                with self.subTest(action=action), self.assertRaises(AdmissionError): action()

    def test_original_call_capture_rejects_copy_cross_thread_close_and_generation_change(self):
        from runtime.meta_hackathon.native_authority import (
            NativeAccessUse,
            NativeAuthorityCapture,
        )
        self.ready()
        cap = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        self.addCleanup(cap.close)
        self.f.access.require_capture(cap, Capability.READ)
        for copier in (copy.copy, copy.deepcopy):
            with self.assertRaises((TypeError, AdmissionError)): copier(cap)
        with self.assertRaises((TypeError, AdmissionError)): NativeAuthorityCapture()
        errors = []
        def foreign_thread():
            try: self.f.access.require_capture(cap, Capability.READ)
            except AdmissionError: errors.append('DENIED')
        worker = threading.Thread(target=foreign_thread); worker.start(); worker.join(2)
        self.assertEqual(['DENIED'], errors)
        with self.assertRaises(AdmissionError): self.f.access.require_capture(cap, Capability.COMMIT)
        self.f.lifecycle.invalidate_admission()
        with self.assertRaises(AdmissionError): self.f.access.require_capture(cap, Capability.READ)
        cap.close()
        with self.assertRaises(AdmissionError): self.f.access.require_capture(cap, Capability.READ)

    def test_capture_callback_has_no_source_os_or_nested_runner(self):
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        self.ready()
        cap = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        self.addCleanup(cap.close)
        run = self.host.runner.run
        def body(tx):
            with patch.object(self.host, 'source_probe', side_effect=AssertionError('SOURCE_IN_SQL')), \
                 patch.object(self.host, '_require_qualified_operator', side_effect=AssertionError('AUTH_IO_IN_SQL')), \
                 patch.object(self.host.runner, 'run', side_effect=AssertionError('NESTED_RUNNER')):
                self.f.access.require_capture(cap, Capability.READ, tx=tx)
                self.f.access.require_capture(cap, Capability.READ, tx=tx)
        run(TransactionContext(cap.principal, Capability.READ), body)

    def populate(self):
        self.ready()
        gov = self.f.governor
        manage = self.host.core.local_operator(Capability.MANAGE)
        review = gov.money_policy_review(self.host.core.local_operator(Capability.READ),
            {'task_limit': 100000000, 'owner_provider_limit': 100000000, 'global_limit': 100000000}, request_id='legacy-money')
        gov.apply_money_policy(manage, review)
        epoch = self.inspect()['epoch']
        for i in range(3):
            principal = self.host.core.local_operator(Capability.COMMIT)
            request = ReservationRequest(f'prior-{i}', f'prior-task-{i}', 'sandbox-exec',
                                        'aioa/offline-host-worker-v1', 'a' * 64, 0, 1)
            gov.reserve(principal, request, epoch)
            gov.dispatch_commit(principal, request.request_id, epoch)
            gov.mark_unknown(principal, request.request_id, epoch, canonical_sha256(['unknown', i]))
            gov.settle(principal, request.request_id, epoch, canonical_sha256(['receipt', i]))
        self.assertEqual('OPEN', self.inspect()['circuits']['sandbox-exec']['state'])

    def test_capacity_transition_preserves_populated_committed_money_open_and_old_rows(self):
        self.populate()
        before = self.inspect(); old_rows = json.loads(self.rows())
        value = fx.review(self.host)
        fx.approve(self.host, value)
        result = fx.apply(self.host, value)
        self.assertEqual('APPLIED', result['status'])
        after = self.inspect(); new_rows = json.loads(self.rows())
        for kind, records in old_rows.items(): self.assertTrue(all(row in new_rows[kind] for row in records), kind)
        for field in ('reservations', 'exposure', 'money_policy', 'circuits', 'kill', 'policy_digest'):
            self.assertEqual(before[field], after[field], field)
        self.assertEqual((before['version'] + 1, before['epoch'] + 1), (after['version'], after['epoch']))
        self.assertEqual(80, after['execution_capacity']['capacity']['risk_limits']['global_limit'])
        again = fx.apply(self.host, value)
        self.assertEqual('READBACK_ONLY', again['status'])
        self.assertEqual(after, self.inspect())

    def test_retained_committed_exposure_cannot_be_hidden_by_smaller_capacity(self):
        self.populate(); before = self.rows()
        with self.assertRaises(ValueError): fx.review(self.host, proposed=fx.proposal(2))
        self.assertEqual(before, self.rows())

    def test_current_revocation_blocks_apply_and_later_revocation_preserves_history(self):
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value)
        warrant = self.f.controller._pending['1' * 32].warrant
        owner = self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.host.ledger.revoke(owner, warrant)
        before = self.rows()
        with self.assertRaises(ValueError): fx.apply(self.host, value)
        self.assertEqual(before, self.rows())
        self.host.operator_request(os.getuid(), {'op': 'execution_capacity_abort', 'request_id': '1' * 32})
        other = fx.review(self.host, '2' * 32); fx.approve(self.host, other); fx.apply(self.host, other)
        second = self.f.controller._pending['2' * 32].warrant
        self.host.ledger.revoke(owner, second)
        self.assertEqual('READBACK_ONLY', fx.apply(self.host, other)['status'])

    def test_rollback_after_consumption_leaves_no_warrant_use_or_transition(self):
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value); before = self.rows()
        from runtime.memory_patch.errors import MemoryPatchError
        with patch.object(self.f.governor, '_write', side_effect=ValueError('ROLLBACK_AFTER_CONSUME')), self.assertRaises(MemoryPatchError):
            fx.apply(self.host, value)
        self.assertEqual(before, self.rows())

    def test_lost_apply_ack_is_readback_only_with_one_epoch_and_one_consumption(self):
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value); before = self.inspect()
        real = LocalCoreTransaction.commit
        fired = []
        key = self.f.governor._key(before['version'] + 1)
        def unknown(tx):
            applied = tx.get(RecordKind.OPERATION, key)
            real(tx)
            if tx.context.purpose is Capability.COMMIT and applied is not None and not fired:
                fired.append('ACTUAL_TRANSITION_COMMIT')
                raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', unknown), self.assertRaises(CommitOutcomeUnknown):
            fx.apply(self.host, value)
        self.assertEqual(['ACTUAL_TRANSITION_COMMIT'], fired)
        result = fx.apply(self.host, value)
        self.assertEqual('READBACK_ONLY', result['status'])
        self.assertEqual(before['epoch'] + 1, self.inspect()['epoch'])

    def test_capacity_requests_remain_closed_private_and_never_http(self):
        self.ready()
        from runtime.webapp import WebRuntimeService
        service = WebRuntimeService(runtime=self.host.runtime, meta_missions=self.host.missions,
                                    meta_owner=self.host, mobile_gateway=self.host.mobile)
        service._mobile_console_uid = os.getuid()
        for value in ({'op': 'native_access_status', 'ready': True},
                      {'op': 'execution_capacity_review', 'request_id': '1' * 32, 'proposed': fx.proposal(), 'clock': 0}):
            with self.assertRaises(ValueError): self.host.operator_request(os.getuid(), value)
        with self.assertRaises(ValueError): self.host.operator_request(os.getuid() + 1, {'op': 'native_access_status'})
        with self.assertRaises(ValueError): service.mobile_operator_request({'op': 'execution_capacity_status', 'request_id': '1' * 32})

    def test_close_retains_live_admin_core_runner_and_lease_then_closes_once(self):
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        self.ready()
        cap = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        report = self.host.close()
        self.assertFalse(report['closed']); self.assertFalse(self.host._closed)
        self.assertTrue(self.host.core.configured); self.assertTrue(self.host.runner.configured)
        os.fstat(self.host._lease)
        cap.close()
        with patch.object(self.host.core, 'close', wraps=self.host.core.close) as core_close:
            self.assertTrue(self.host.close()['closed'])
            self.host.close()
            self.assertEqual(1, core_close.call_count)


class NativeBoundaryTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready
    inspect = NativeFoundationTests.inspect
    rows = NativeFoundationTests.rows

    def test_monotonic_regression_after_an_earlier_check_denies(self):
        from runtime.meta_hackathon import native_authority as native
        self.ready()
        cap = self.f.access.capture(Capability.READ, use=native.NativeAccessUse.READ)
        self.addCleanup(cap.close)
        with patch.object(native.time, 'monotonic', return_value=cap.monotonic_at + 10):
            self.f.access.require_capture(cap, Capability.READ)
        with patch.object(native.time, 'monotonic', return_value=cap.monotonic_at + 9), self.assertRaises(AdmissionError):
            self.f.access.require_capture(cap, Capability.READ)

    def test_observed_source_loss_invalidates_original_even_after_source_is_restored(self):
        from runtime.meta_hackathon import native_authority as native
        self.ready()
        cap = self.f.access.capture(Capability.READ, use=native.NativeAccessUse.READ)
        self.addCleanup(cap.close)
        with patch.object(self.host, 'source_probe', return_value=('c' * 40, 'b' * 64)), self.assertRaises(AdmissionError):
            self.host.operator_principal()
        with self.assertRaises(AdmissionError): self.f.access.require_capture(cap, Capability.READ)

    def test_direct_chat_claim_is_fenced_before_legacy_dispatch(self):
        self.ready()
        from runtime.meta_hackathon import chat
        with patch.object(chat, 'approve', side_effect=AssertionError('CHAT_DISPATCH_BEFORE_NATIVE_GATE')), self.assertRaises(AdmissionError):
            self.host.missions.chat_approve('1' * 32, 'a' * 64, self.host.core.local_operator(Capability.OWNER_APPROVAL))

    def test_foreign_same_core_governor_attachment_denies_capture(self):
        from runtime.meta_hackathon import native_authority as native
        from runtime.mission.governor import CoreDualGovernor
        self.ready()
        self.host.missions._chat_governor = CoreDualGovernor(self.f.core, self.f.runner, self.f.governor.policy)
        with self.assertRaises(AdmissionError):
            cap = self.f.access.capture(Capability.READ, use=native.NativeAccessUse.READ)
            cap.close()

    def test_malformed_legacy_history_cannot_disappear_from_quiescence(self):
        from runtime.memory_patch.persistence.ports import StoredRecord
        from runtime.meta_hackathon.mission_service import KIND
        self.ready()
        row = StoredRecord(RecordKind.OPERATION, 'meta-malformed', self.host.ledger.scope, 1,
                           {'schema': KIND, 'task_id': 'meta-malformed', 'state': 'UNSUPPORTED_STATE'})
        principal = self.host.core.local_operator(Capability.COMMIT)
        self.host.runner.run(TransactionContext(principal, Capability.COMMIT), lambda tx: tx.insert(row))
        from runtime.memory_patch.errors import MemoryPatchError
        with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)

    def test_unknown_legacy_work_denies_review_without_mutating_it(self):
        from runtime.memory_patch.persistence.ports import StoredRecord
        from runtime.meta_hackathon.mission_service import KIND
        self.ready()
        row = StoredRecord(RecordKind.OPERATION, 'meta-orphan', self.host.ledger.scope, 1,
                           {'schema': KIND, 'task_id': 'meta-orphan', 'state': 'UNKNOWN'})
        principal = self.host.core.local_operator(Capability.COMMIT)
        self.host.runner.run(TransactionContext(principal, Capability.COMMIT), lambda tx: tx.insert(row))
        before = self.rows()
        with self.assertRaises(ValueError): fx.review(self.host)
        self.assertEqual(before, self.rows())

    def test_delayed_source_capture_retains_core_runner_lease_until_call_returns(self):
        from runtime.meta_hackathon import native_authority as native
        self.ready()
        entered, release = threading.Event(), threading.Event()
        errors = []
        def probe():
            entered.set()
            if not release.wait(3): raise AssertionError('FIXTURE_RELEASE_TIMEOUT')
            return self.host.source
        def capture():
            try:
                value = self.f.access.capture(Capability.READ, use=native.NativeAccessUse.READ)
                value.close()
            except AdmissionError: errors.append('GENERATION_DENIED')
        with patch.object(self.host, 'source_probe', side_effect=probe):
            worker = threading.Thread(target=capture); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                result = self.host.close()
                self.assertFalse(result['closed'])
                self.assertTrue(self.host.runner.configured and self.host.core.configured)
                os.fstat(self.host._lease)
            finally: release.set(); worker.join(4)
        self.assertEqual(['GENERATION_DENIED'], errors)
        self.assertTrue(self.host.close()['closed'])

    def test_lost_approval_ack_is_inspection_only_without_reapproval(self):
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        self.ready(); value = fx.review(self.host)
        warrant = self.f.controller._pending['1' * 32].warrant
        key = self.host.ledger._key(warrant)
        real = LocalCoreTransaction.commit
        fired = []
        def unknown(tx):
            witness = tx.get(RecordKind.APPROVAL, key)
            real(tx)
            if tx.context.purpose is Capability.OWNER_APPROVAL and witness is not None and not fired:
                fired.append('OWNER_WITNESS_COMMIT'); raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', unknown), self.assertRaises(CommitOutcomeUnknown):
            fx.approve(self.host, value)
        self.assertEqual(['OWNER_WITNESS_COMMIT'], fired)
        before = self.rows()
        with self.assertRaises(ValueError): fx.approve(self.host, value)
        with self.assertRaises(ValueError): fx.apply(self.host, value)
        self.assertEqual(before, self.rows())

    def test_apply_at_one_microsecond_before_expiry_uses_precise_immutable_time(self):
        from datetime import UTC, datetime, timedelta

        from runtime.meta_hackathon import native_authority as native
        from runtime.mission import execution_capacity as codec
        now = [datetime.now(UTC)]
        class ControlledUTC:
            @staticmethod
            def now(_zone): return now[0]
        self.host.core._clock = lambda: now[0]
        self.host.ledger.clock = lambda: now[0]
        with patch.object(native, 'datetime', ControlledUTC):
            # fromtimestamp is needed for actual TLS expiry projection too.
            ControlledUTC.fromtimestamp = staticmethod(datetime.fromtimestamp)
            self.ready(); value = fx.review(self.host); fx.approve(self.host, value)
            now[0] = codec.utc(value['review']['expires_at']) - timedelta(microseconds=1)
            result = fx.apply(self.host, value)
            self.assertEqual('APPLIED', result['status'])
            self.assertEqual(int(now[0].timestamp()), self.inspect()['last_now'])

    def test_post_ack_expiry_fences_request_and_only_canonical_readback_remains(self):
        from datetime import UTC, datetime, timedelta

        from runtime.meta_hackathon import native_authority as native
        from runtime.mission import execution_capacity as codec
        now = [datetime.now(UTC)]
        class ControlledUTC:
            now = staticmethod(lambda _zone: now[0])
            fromtimestamp = staticmethod(datetime.fromtimestamp)
        self.host.core._clock = lambda: now[0]
        self.host.ledger.clock = lambda: now[0]
        real = LocalCoreTransaction.commit
        with patch.object(native, 'datetime', ControlledUTC):
            self.ready(); value = fx.review(self.host); fx.approve(self.host, value)
            before = self.inspect(); key = self.f.governor._key(before['version'] + 1)
            now[0] = codec.utc(value['review']['expires_at']) - timedelta(microseconds=1)
            def expire_after_ack(tx):
                row = tx.get(RecordKind.OPERATION, key)
                real(tx)
                if tx.context.purpose is Capability.COMMIT and row is not None:
                    now[0] += timedelta(microseconds=2)
            with patch.object(LocalCoreTransaction, 'commit', expire_after_ack):
                try: fx.apply(self.host, value)
                except ValueError: pass  # A late authority loss may report a closed denial.
            self.assertEqual('READBACK_ONLY', self.f.controller._pending['1' * 32].state)
            self.assertEqual('READBACK_ONLY', fx.apply(self.host, value)['status'])
            self.assertEqual(before['epoch'] + 1, self.inspect()['epoch'])

    def test_new_native_process_session_reads_old_consumed_transition_after_expiry(self):
        from datetime import timedelta

        from runtime.meta_hackathon import runtime_adapter
        from runtime.mission import execution_capacity as codec
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value); fx.apply(self.host, value)
        old_instance = self.host.instance_id
        self.assertTrue(self.host.close()['closed'])
        authentication = {'uid': os.getuid(), 'method': 'SECOND_SYNTHETIC_TEST_ONLY'}
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), authentication)):
            other = runtime_adapter.NativeMobileComposition(self.host.root, origin=self.host.origin,
                source_probe=lambda: self.host.source, host_composition=self.f.spec)
        self.addCleanup(other.close); fx.fixture_tls(other)
        other.ledger.clock = lambda: codec.utc(value['review']['expires_at']) + timedelta(days=1)
        self.assertNotEqual(old_instance, other.instance_id)
        self.assertEqual('READBACK_ONLY', fx.apply(other, value)['status'])
        self.assertFalse(other.foundation.controller._pending)


class NativeConfigTests(unittest.TestCase):
    def setUp(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        temporary = TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = fx.config_data(self.root)

    def test_private_config_load_is_inert_and_rejects_duplicate_extra_link_and_world_access(self):
        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        path = self.root / 'native-config.json'
        path.write_text(json.dumps(self.data)); path.chmod(0o600)
        os.utime(path, ns=(0, path.stat().st_mtime_ns))  # Cold private data may update access time when read.
        with patch('runtime.mission.git_publish.GitSourceSnapshot.capture', side_effect=AssertionError('PARSE_READ_SOURCE')), \
             patch('runtime.mission.git_publish.GitSourceSnapshot.verify_export', side_effect=AssertionError('PARSE_READ_EXPORT')):
            loaded = NativeHostCompositionConfig.load(path)
            self.assertEqual(self.data, loaded.to_dict())
        path.chmod(0o644)
        with self.assertRaises(ValueError): NativeHostCompositionConfig.load(path)
        path.chmod(0o600)
        link = self.root / 'config-link'; link.symlink_to(path)
        with self.assertRaises((ValueError, OSError)): NativeHostCompositionConfig.load(link)
        path.write_text('{"schema":"first","schema":"second"}')
        with self.assertRaises(ValueError): NativeHostCompositionConfig.load(path)

    def test_config_deep_types_fieldsets_bounds_and_snapshot_encoding_are_closed(self):
        from runtime.meta_hackathon.native_authority import NativeHostCompositionConfig
        for change in (
            lambda d: d.update(extra=True),
            lambda d: d['limits_plan'].update(local_git_effects=True),
            lambda d: d['limits_plan'].update(local_git_effects=3),
            lambda d: d['limits_plan'].update(callback='arbitrary'),
            lambda d: d['portable'].update(extra=True),
            lambda d: d['portable']['binding'].update(extra=True),
            lambda d: d['portable']['resource_query'].update(extra=True),
            lambda d: d['recipe'].update(command=['sh', '-c', 'arbitrary']),
            lambda d: d['source_snapshot']['files'][0].__setitem__(1, d['source_snapshot']['files'][0][1] + '\n'),
            lambda d: d.update(candidate_root=d['base_root']),
            lambda d: d['sandbox_seed'].update(descriptor_path='/arbitrary/host-config.json'),
            lambda d: d.update(profile='LIVE_MODEL'),
        ):
            value = copy.deepcopy(self.data); change(value)
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                NativeHostCompositionConfig.from_dict(value)

    def test_legacy_none_does_not_construct_foundation_governor_or_target(self):
        from runtime.meta_hackathon import native_authority, runtime_adapter
        with patch.object(native_authority.NativeAuthorityFoundation, 'bind_owner', side_effect=AssertionError('OFF_ACTIVATION')), \
             patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), {'uid': os.getuid()})):
            owner = runtime_adapter.NativeMobileComposition(self.root / 'legacy-native', origin='https://fixture.example.org',
                                                           source_probe=lambda: ('a' * 40, 'b' * 64))
        self.addCleanup(owner.close)
        self.assertIsNone(owner.foundation)
        self.assertFalse(hasattr(owner, 'chat_governor'))
        self.assertIsNone(owner.runtime._coding_tasks)
        self.assertEqual(0, owner.model_calls())


class NativePublicationTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready

    def test_actual_mission_publishes_same_token_thread_before_durable_approval(self):
        from runtime.browser_agent.chrome_read_adapter import (
            ChromeReadAdapter,
            FixtureReadDriver,
        )
        from runtime.meta_hackathon.mission_service import MissionError
        from runtime.meta_hackathon.native_authority import NativePhase
        from runtime.providers.config import ProviderManager
        from runtime.providers.meta_model_api import MetaModelProvider
        self.ready()
        service = self.host.missions
        service.manager = ProviderManager(self.host.root, meta_only=True)
        def fixed_protocol(payload, _cancel, _timeout):
            value = json.loads(payload['messages'][-1]['content']); value.pop('instruction')
            body = {'id': 'owned-protocol-fixture', 'model': 'Llama-4-Maverick-17B-128E-Instruct-FP8',
                    'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                    'content': None, 'tool_calls': [{'id': 'call_' + value['task_id'], 'type': 'function',
                    'function': {'name': 'navigate_read', 'arguments': json.dumps(value, sort_keys=True)}}]}}],
                    'usage': {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}}
            from runtime.providers.meta_model_api import MODEL
            body['model'] = MODEL
            return 200, json.dumps(body).encode()
        service.manager.configure_meta(MetaModelProvider(mode='MOCK', transport=fixed_protocol))
        service.browser = ChromeReadAdapter(FixtureReadDriver())
        request = service.preview({'mode': 'OFFLINE_FIXTURE', 'instruction': 'Read the owned fixture.',
            'target_url': 'https://docs.example.org/offline-fixture'}, self.host.core.local_operator(Capability.READ))
        observed = []
        def approval(_owner, _warrant):
            handle = self.f.lifecycle._handles.get(request['task_id'])
            observed.append(handle is not None and service._workers.get(request['task_id']) is handle.thread
                            and service._cancels.get(request['task_id']) is handle.cancel
                            and handle.thread.ident is None and not handle.done.is_set())
            raise ValueError('OWNED_TEST_STOP_BEFORE_APPROVAL')
        # Controlled internal phase exercises the future publication hook only;
        # it is not a complete graph, real OS/TLS or execution qualification.
        self.f.lifecycle._phase = NativePhase.ACTIVE
        try:
            with patch.object(self.host.ledger, 'approve', side_effect=approval), self.assertRaises(MissionError):
                service.run(request['task_id'], request['preview_digest'],
                            self.host.core.local_operator(Capability.OWNER_APPROVAL))
        finally: self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual([True], observed)
        with self.assertRaises(ValueError): self.f.lifecycle.begin_capacity_review('9' * 32)
        self.assertFalse(self.host.close()['closed'])

    def test_delayed_renew_is_owned_before_os_auth_and_cannot_publish_after_close(self):
        from runtime.meta_hackathon import runtime_adapter
        self.ready()
        status = self.host.operator_auth_status()
        value = {'op': 'operator_renew', 'request_id': '6' * 32,
                 **{key: status[key] for key in ('source_sha', 'capsule_digest', 'core_instance_id', 'admission_revision')}}
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def authenticate():
            entered.set()
            if not release.wait(3): raise AssertionError('FIXTURE_RENEW_RELEASE_TIMEOUT')
            return os.getuid(), {'uid': os.getuid(), 'method': 'RENEW_SYNTHETIC_TEST_ONLY'}
        def renew():
            try: outcomes.append(self.host.operator_request(os.getuid(), value, invalidate_console=lambda: None))
            except ValueError: outcomes.append('FENCED')
        with patch.object(runtime_adapter, '_desktop_operator_uid', side_effect=authenticate):
            worker = threading.Thread(target=renew); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.host.close()['closed'])
                self.assertTrue(self.host.core.configured and self.host.runner.configured)
                os.fstat(self.host._lease)
            finally: release.set(); worker.join(4)
        self.assertEqual(['FENCED'], outcomes)
        self.assertTrue(self.host.close()['closed'])


class NativeRetainedCodecTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready
    inspect = NativeFoundationTests.inspect

    def committed(self):
        self.ready()
        reader = self.host.core.local_operator(Capability.READ)
        before = self.host.runner.run(TransactionContext(reader, Capability.READ), self.f.governor._load)
        value = fx.review(self.host); fx.approve(self.host, value); fx.apply(self.host, value)
        return before, self.inspect()['version']

    def validate_changed(self, before, version, change):
        reader = self.host.core.local_operator(Capability.READ)
        def read(tx):
            row = tx.get(RecordKind.OPERATION, self.f.governor._key(version))
            outcome = json.loads(canonical_json_bytes(row.payload['outcome']))
            change(outcome['execution_capacity_transition'])
            return self.f.governor._validate_capacity_transition(tx, before, outcome['state'],
                                                               outcome['execution_capacity_transition'])
        return self.host.runner.run(TransactionContext(reader, Capability.READ), read)

    def test_retained_consumption_boolean_flags_cannot_be_integer_zero(self):
        before, version = self.committed()
        with self.assertRaises(ValueError):
            self.validate_changed(before, version, lambda t: t['consumption'].update(effect_verified=0))

    def test_before_snapshot_cannot_substitute_boolean_epoch_for_integer_epoch(self):
        from runtime.memory_patch.persistence.ports import StoredRecord
        before, version = self.committed()
        def corrupt(transition):
            snap = transition['approval_at_apply']['warrant_state_before']
            snap['payload']['root']['lease_epoch'] = True
            snap['payload']['active']['lease_epoch'] = True
            rebuilt = StoredRecord(RecordKind.OPERATION, snap['record_id'], self.host.ledger.scope,
                                   snap['revision'], snap['payload'])
            snap['payload_digest'] = rebuilt.payload_digest
        with self.assertRaises(ValueError): self.validate_changed(before, version, corrupt)

    def test_foreign_native_row_schema_cannot_mint_a_current_capture(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.persistence.ports import StoredRecord
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        self.ready()
        principal = self.host.core.local_operator(Capability.COMMIT)
        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION, 'mobile-operator-' + self.host.instance_id)
            payload = json.loads(canonical_json_bytes(row.payload)); payload['schema'] = 'foreign-native-row'
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, payload),
                       expected_revision=row.revision)
        self.host.runner.run(TransactionContext(principal, Capability.COMMIT), corrupt)
        capture = None
        try:
            with self.assertRaises((ValueError, MemoryPatchError)):
                capture = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        finally:
            if capture is not None: capture.close()

    def test_retry_reuses_precise_apply_time_without_source_io_inside_transaction(self):
        from runtime.memory_patch.persistence import ports
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value)
        before = self.inspect(); key = self.f.governor._key(before['version'] + 1)
        actual_commit = LocalCoreTransaction.commit
        times = []
        class SerializationRetry(Exception):
            sqlstate = '40001'
        def retry_once(tx):
            row = tx.get(RecordKind.OPERATION, key)
            if tx.context.purpose is Capability.COMMIT and row is not None:
                times.append(row.payload['outcome']['execution_capacity_transition']['applied_at'])
                if len(times) == 1: raise SerializationRetry()
            return actual_commit(tx)
        def guarded_source():
            if ports._IN_TRANSACTION.get(): raise AssertionError('SOURCE_IO_DURING_RETRY')
            return self.host.source
        with patch.object(LocalCoreTransaction, 'commit', retry_once), \
             patch.object(self.host, 'source_probe', side_effect=guarded_source):
            self.assertEqual('APPLIED', fx.apply(self.host, value)['status'])
        self.assertEqual(2, len(times)); self.assertEqual(times[0], times[1])
        self.assertEqual(before['epoch'] + 1, self.inspect()['epoch'])


class NativeFinalLifetimeTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready

    def test_auth_status_call_retains_resources_until_source_probe_returns(self):
        self.ready()
        entered, release = threading.Event(), threading.Event()
        responses = []
        def probe():
            entered.set()
            if not release.wait(3): raise AssertionError('STATUS_RELEASE_TIMEOUT')
            return self.host.source
        def status():
            responses.append(self.host.operator_request(os.getuid(), {'op': 'operator_auth_status'}))
        with patch.object(self.host, 'source_probe', side_effect=probe):
            worker = threading.Thread(target=status); worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertFalse(self.host.close()['closed'])
                self.assertTrue(self.host.core.configured and self.host.runner.configured)
                os.fstat(self.host._lease)
            finally: release.set(); worker.join(4)
        self.assertEqual('AUTH_REQUIRED', responses[0]['state'])
        self.assertTrue(self.host.close()['closed'])

    def test_partial_foundation_construction_keeps_ownership_and_never_reports_absence(self):
        from pathlib import Path
        from tempfile import mkdtemp

        from runtime.meta_hackathon import native_authority, runtime_adapter
        root = Path(mkdtemp(prefix='owned-partial-native-'))
        fx.OWNED_ROOTS.append(str(root))
        owners = []
        def fail(owner, _spec):
            owners.append(owner)
            raise ValueError('OWNED_PARTIAL_BINDING_FAULT')
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), {'uid': os.getuid()})), \
             patch.object(native_authority.NativeAuthorityFoundation, 'bind_owner', side_effect=fail), \
             self.assertRaisesRegex(ValueError, 'OWNED_PARTIAL_BINDING_FAULT'):
            runtime_adapter.NativeMobileComposition(root / 'native', origin=self.host.origin,
                source_probe=lambda: self.host.source, host_composition=self.f.spec)
        self.assertEqual(1, len(owners)); owner = owners[0]
        self.assertFalse(owner.close()['closed'])
        self.assertFalse(owner._closed)
        self.assertTrue(owner.core.configured and owner.runner.configured)
        os.fstat(owner._lease)
        self.assertIsNone(owner.foundation)
        # Retained private fixtures end with this owned test process; there is
        # no false cleanup/absence certificate and no raw key/DB copy.


class NativeDuplicateReviewTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready

    def test_committed_request_cannot_remint_review_after_native_restart(self):
        from runtime.meta_hackathon import runtime_adapter
        self.ready(); value = fx.review(self.host); fx.approve(self.host, value); fx.apply(self.host, value)
        self.assertTrue(self.host.close()['closed'])
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), {'uid': os.getuid()})):
            other = runtime_adapter.NativeMobileComposition(self.host.root, origin=self.host.origin,
                source_probe=lambda: self.host.source, host_composition=self.f.spec)
        self.addCleanup(other.close); fx.fixture_tls(other)
        replay = fx.review(other)
        self.assertEqual('READBACK_ONLY', replay['status'])
        self.assertFalse(other.foundation.controller._pending)
        with self.assertRaises(ValueError): fx.review(other, proposed=fx.proposal(81))


class NativeIdentityJoinTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp
    ready = NativeFoundationTests.ready

    def test_runtime_alias_with_equal_core_fields_cannot_replace_actual_runtime(self):
        from types import SimpleNamespace

        from runtime.meta_hackathon.native_authority import NativeAccessUse
        self.ready(); original = self.host.runtime; capture = None
        try:
            self.host.runtime = SimpleNamespace(_memory_patch_admission=self.host.core,
                                               _owns_memory_patch_admission=False, _coding_tasks=None)
            with self.assertRaises(ValueError):
                capture = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        finally:
            if capture is not None: capture.close()
            self.host.runtime = original

    def test_uid_field_change_invalidates_existing_original_projection(self):
        from runtime.meta_hackathon.native_authority import NativeAccessUse
        self.ready(); original = self.host.uid
        capture = self.f.access.capture(Capability.READ, use=NativeAccessUse.READ)
        try:
            self.host.uid += 1
            with self.assertRaises(ValueError): self.f.access.require_capture(capture, Capability.READ)
        finally:
            self.host.uid = original; capture.close()


class NativePartialBindingTests(unittest.TestCase):
    setUp = NativeFoundationTests.setUp

    def test_fault_after_foundation_ownership_publication_keeps_incomplete_graph_fenced(self):
        from pathlib import Path
        from tempfile import mkdtemp

        from runtime.meta_hackathon import native_authority, runtime_adapter
        root = Path(mkdtemp(prefix='owned-bound-partial-native-'))
        fx.OWNED_ROOTS.append(str(root)); owners = []
        def fail(_spec, owner):
            owners.append(owner)
            raise ValueError('OWNED_ROOT_OBSERVATION_FAULT')
        with patch.object(runtime_adapter, '_desktop_operator_uid', return_value=(os.getuid(), {'uid': os.getuid()})), \
             patch.object(native_authority.NativeHostCompositionConfig, 'observe', autospec=True, side_effect=fail), \
             self.assertRaisesRegex(ValueError, 'OWNED_ROOT_OBSERVATION_FAULT'):
            runtime_adapter.NativeMobileComposition(root / 'native', origin=self.host.origin,
                source_probe=lambda: self.host.source, host_composition=self.f.spec)
        self.assertEqual(1, len(owners)); owner = owners[0]
        self.assertFalse(owner.close()['closed'])
        self.assertFalse(owner._closed)
        self.assertTrue(owner.core.configured and owner.runner.configured)
        os.fstat(owner._lease)
        self.assertEqual('QUARANTINED', owner.foundation.lifecycle.phase.value)
        self.assertFalse(owner.foundation.lifecycle._roles)
