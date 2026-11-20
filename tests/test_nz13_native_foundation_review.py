"""Review regressions: owned SQLite/threads, synthetic OS/TLS, no real activation."""
import hashlib
import json
import os
import threading
import time
import unittest
from unittest.mock import patch

import nz13_native_foundation_support as fx

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.meta_hackathon import github_write


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.host, self.data = fx.new_host(self)
        self.f = self.host.foundation
        fx.fixture_tls(self.host)
        fx.initialize(self.host)

    def rows(self, host=None):
        host = host or self.host
        return host.runner.run(TransactionContext(host.core.local_operator(Capability.READ), Capability.READ),
            lambda tx: canonical_json_bytes({kind.value: [(row.record_id, row.payload_digest) for row in tx.scan(kind, limit=1024)]
                for kind in (RecordKind.OPERATION, RecordKind.APPROVAL, RecordKind.AUDIT, RecordKind.OUTBOX)}))

    def github_row(self, state, *, host=None, key=None, operation_id='a' * 32, schema='aioa.mobile.transport.v1'):
        host = host or self.host
        data = {'schema': schema, 'state': state, 'operation_id': operation_id,
            'source_chat_request_id': 'b' * 32, 'source_reply_sha256': 'c' * 64,
            'source_sha': host.source[0], 'capsule_digest': host.source[1], 'core_instance_id': host.instance_id,
            'created_at': int(time.time()), 'expires_at': int(time.time()) + 300,
            'stop_requested': False, 'warrant': None}
        row = StoredRecord(RecordKind.OPERATION, key or 'native-github-' + operation_id, host.ledger.scope, 1, data)
        host.runner.run(TransactionContext(host.core.local_operator(Capability.COMMIT), Capability.COMMIT), lambda tx: tx.insert(row))
        return row


class GitHubRetainedHistoryTests(ReviewFixture):
    def test_unsupported_github_state_blocks_review_without_any_mutation_or_preflight(self):
        self.github_row('GITHUB_UNSUPPORTED')
        before = self.rows()
        with patch.object(github_write.github_remote, 'read_demo_base', side_effect=AssertionError('PREFLIGHT_FORBIDDEN')), self.assertRaises((ValueError, MemoryPatchError)):
            fx.review(self.host)
        self.assertEqual(before, self.rows())

    def test_unsupported_github_state_inserted_after_approval_blocks_apply_without_consumption(self):
        review = fx.review(self.host)
        fx.approve(self.host, review)
        self.github_row('GITHUB_UNSUPPORTED')
        before = self.rows()
        with self.assertRaises((ValueError, MemoryPatchError)):
            fx.apply(self.host, review)
        self.assertEqual(before, self.rows())

    def test_malformed_github_schema_key_domain_and_operation_id_fail_closed(self):
        variants = ({'schema': 'foreign.domain.v1'}, {'key': 'native-github-' + 'd' * 32},
                    {'key': 'foreign-github-' + 'a' * 32}, {'operation_id': 'not-an-operation-id'})
        for variant in variants:
            with self.subTest(variant=variant):
                host, _ = fx.new_host(self)
                fx.fixture_tls(host); fx.initialize(host)
                self.github_row('GITHUB_PROPOSAL_FAILED', host=host, **variant)
                before = self.rows(host)
                with self.assertRaises((ValueError, MemoryPatchError)):
                    fx.review(host)
                self.assertEqual(before, self.rows(host))

    def test_github_unknown_remains_a_blocker(self):
        self.github_row('GITHUB_UNKNOWN')
        before = self.rows()
        with self.assertRaises((ValueError, MemoryPatchError)):
            fx.review(self.host)
        self.assertEqual(before, self.rows())

    def test_valid_terminal_and_source_binding_history_remain_readable(self):
        operation = self.github_row('GITHUB_PROPOSAL_FAILED')
        self.github_row('GITHUB_SOURCE_BINDING', key='native-github-source-' + 'b' * 32)
        principal = self.host.core.local_operator(Capability.READ)
        rows = self.host.runner.run(TransactionContext(principal, Capability.READ), github_write.retained_in_transaction)
        self.assertEqual([operation.record_id], [row.record_id for row in rows])
        before = self.rows()
        self.assertEqual('REVIEWED', fx.review(self.host)['status'])
        self.assertEqual(before, self.rows())

    def test_shared_remote_git_result_state_is_not_a_native_transport_domain(self):
        self.github_row('GITHUB_PROPOSAL_FAILED')
        self.github_row('GITHUB_VERIFIED', key='github-result-' + 'a' * 32, schema='aioa.github-result.v1')
        self.assertEqual('REVIEWED', fx.review(self.host)['status'])


class NativeConcurrentCloseTests(ReviewFixture):
    def test_two_close_calls_have_one_owner_and_never_close_reused_foreign_fd(self):
        entered, release = threading.Event(), threading.Event()
        original_drain = self.f.lifecycle.drain
        drain_calls = []
        def blocked_first_drain():
            value = original_drain()
            drain_calls.append(value)
            if len(drain_calls) == 1:
                entered.set()
                if not release.wait(3): raise AssertionError('CLOSE_BARRIER_TIMEOUT')
            return value
        original_close = os.close
        lease = self.host._lease
        foreign_source = os.open(self.host.root / 'owned-foreign-fd', os.O_CREAT | os.O_RDWR, 0o600)
        lease_calls, results, errors = [], [], []
        def close_fd(fd):
            original_close(fd)
            if fd == lease:
                lease_calls.append(fd)
                if len(lease_calls) == 1: os.dup2(foreign_source, lease)
        def close_host():
            try: results.append(self.host.close())
            except (OSError,RuntimeError,ValueError,AssertionError) as error: errors.append(type(error).__name__)
        try:
            with patch.object(self.f.lifecycle, 'drain', side_effect=blocked_first_drain), \
                 patch.object(self.host.runtime, 'close', wraps=self.host.runtime.close) as runtime_close, \
                 patch.object(self.host.runner, 'close', wraps=self.host.runner.close) as runner_close, \
                 patch.object(self.host.core, 'close', wraps=self.host.core.close) as core_close, \
                 patch('runtime.meta_hackathon.runtime_adapter.os.close', side_effect=close_fd):
                first = threading.Thread(target=close_host); first.start()
                self.assertTrue(entered.wait(2))
                second = threading.Thread(target=close_host); second.start(); second.join(1)
                release.set(); first.join(3); second.join(3)
                self.assertFalse(first.is_alive() or second.is_alive())
                self.assertEqual([], errors)
                self.assertEqual((1, 1, 1, 1), (runtime_close.call_count, runner_close.call_count, core_close.call_count, len(lease_calls)))
                os.fstat(lease)
                self.assertEqual('CLOSED', self.f.lifecycle.phase.value)
                self.assertTrue(self.host.close()['closed'])
                self.assertEqual(1, len(lease_calls))
        finally:
            release.set()
            original_close(foreign_source)
            try: original_close(lease)
            except OSError: pass

    def test_faulted_close_stage_is_quarantined_and_never_retried(self):
        with patch.object(self.host.runtime, 'close', wraps=self.host.runtime.close) as runtime_close, \
             patch.object(self.host.runner, 'close', wraps=self.host.runner.close) as runner_close, \
             patch.object(self.host.core, 'close', side_effect=RuntimeError('OWNED_CLOSE_BOUNDARY')) as core_close:
            with self.assertRaises(RuntimeError): self.host.close()
            self.assertEqual('QUARANTINED', self.host.close()['status'])
            self.assertEqual((1, 1, 1), (runtime_close.call_count, runner_close.call_count, core_close.call_count))
            self.assertFalse(self.host._closed)
            self.assertTrue(self.host.core.configured)
            os.fstat(self.host._lease)


def mission_preview(host):
    from runtime.browser_agent.chrome_read_adapter import (
        ChromeReadAdapter,
        FixtureReadDriver,
    )
    from runtime.providers.config import ProviderManager
    from runtime.providers.meta_model_api import MODEL, MetaModelProvider
    service = host.missions
    service.manager = ProviderManager(host.root, meta_only=True)
    def fixed_protocol(payload, _cancel, _timeout):
        value = json.loads(payload['messages'][-1]['content']); value.pop('instruction')
        body = {'id': 'owned-review-protocol', 'model': MODEL,
            'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
            'content': None, 'tool_calls': [{'id': 'call_' + value['task_id'], 'type': 'function',
            'function': {'name': 'navigate_read', 'arguments': json.dumps(value, sort_keys=True)}}]}}],
            'usage': {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80}}
        return 200, json.dumps(body).encode()
    service.manager.configure_meta(MetaModelProvider(mode='MOCK', transport=fixed_protocol))
    service.browser = ChromeReadAdapter(FixtureReadDriver())
    return service.preview({'mode': 'OFFLINE_FIXTURE', 'instruction': 'Read the owned fixture.',
        'target_url': 'https://docs.example.org/offline-fixture'}, host.core.local_operator(Capability.READ))


class NativeMissionRetirementTests(ReviewFixture):
    def start_mission(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        request = mission_preview(self.host)
        self.f.lifecycle._phase = NativePhase.ACTIVE  # Controlled hook only, never graph qualification.
        self.host.missions.run(request['task_id'], request['preview_digest'],
                               self.host.core.local_operator(Capability.OWNER_APPROVAL))
        handle = self.f.lifecycle._handles[request['task_id']]
        return request, handle

    def test_completed_actual_mission_retires_only_after_source_owned_join_and_cleanup(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        request, handle = self.start_mission()
        original_thread, original_cancel = handle.thread, handle.cancel
        handle.thread.join(3)
        self.assertFalse(handle.thread.is_alive())
        self.assertEqual('OFFLINE_FIXTURE', self.host.missions._get(request['task_id']).payload['state'])
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual('REVIEWED', fx.review(self.host)['status'])
        self.assertIs(original_thread, handle.thread); self.assertIs(original_cancel, handle.cancel)
        self.assertIsNotNone(handle.cleanup)
        self.assertNotIn(handle.task_id, self.f.lifecycle._handles)
        self.assertNotIn(handle.task_id, self.host.missions._workers)
        self.assertTrue(self.host.close()['closed'])

    def test_done_thread_without_terminal_record_is_not_cleanup_evidence(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        with patch.object(self.host.missions, '_execute', return_value=None):
            _, handle = self.start_mission(); handle.thread.join(3)
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertTrue(handle.done.is_set())
        with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
        self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
        self.assertIsNone(handle.cleanup)
        self.assertFalse(self.host.close()['closed'])

    def test_unknown_actual_worker_preserves_original_handle_and_live_core(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        with patch('runtime.meta_hackathon.mission_service.run_read_once', side_effect=ValueError('OWNED_UNKNOWN')):
            request, handle = self.start_mission(); handle.thread.join(3)
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual('UNKNOWN', self.host.missions._get(request['task_id']).payload['state'])
        with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
        self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
        self.assertFalse(self.host.close()['closed'])
        self.assertTrue(self.host.core.configured); self.assertTrue(self.host.runner.configured)
        os.fstat(self.host._lease)

    def test_terminal_row_cannot_retire_worker_before_actual_return_and_join(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        terminal, release = threading.Event(), threading.Event()
        change = self.host.missions._change
        def hold_terminal(*args, **kwargs):
            result = change(*args, **kwargs)
            if args[2] == 'OFFLINE_FIXTURE':
                terminal.set()
                if not release.wait(4): raise AssertionError('OWNED_TERMINAL_BARRIER_TIMEOUT')
            return result
        try:
            with patch.object(self.host.missions, '_change', side_effect=hold_terminal):
                _, handle = self.start_mission()
                self.assertTrue(terminal.wait(3))
                self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
                with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
                self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
                self.assertFalse(handle.done.is_set())
                release.set(); handle.thread.join(3)
            self.assertEqual('REVIEWED', fx.review(self.host)['status'])
            self.assertIsNotNone(handle.cleanup)
        finally: release.set()


def agent_port(case, host):
    """Real same-Core journal/warrant/artifact I/O; synthetic sandbox adapter only."""
    from types import SimpleNamespace

    from lab.archaioa.evidence import EvidenceRef
    from lab.archaioa.outcome import Applied
    from runtime.memory_patch.contracts.serialization import canonical_sha256
    from runtime.meta_hackathon import agent_operations as agent
    from runtime.mission.liability import Reconciliation
    from runtime.mission.sandbox_contracts import SandboxRecipe, SandboxRegistry
    from runtime.mission.sandbox_linux import LinuxSandboxBroker, TrustedSandboxConfig
    from runtime.mission.tools import LocalSessionGrant
    service, foundation = host.missions, host.foundation
    case.enterContext(patch.object(agent, 'MODEL', 'aioa/offline-host-worker-v1'))
    task = 'agent-' + 'a' * 32; now = int(time.time()); digest = canonical_sha256(['owned-review', task])
    recipe = SandboxRecipe('tiny-python-v1', 'root-1', canonical_sha256({}), 'b' * 64, 'c' * 64)
    registry = SandboxRegistry('fixture-workspace', (recipe,))
    artifact = canonical_json_bytes({'tests_passed': 5})
    config_root = host.root / 'owned-agent-port'; config_root.mkdir(mode=0o700)
    config = TrustedSandboxConfig(config_root, b'{}', canonical_sha256({}), registry,
        canonical_json_bytes({recipe.recipe_id: {'expected': {'result.json': {'bytes': len(artifact), 'sha256': hashlib.sha256(artifact).hexdigest()}}}}), b'{}')
    broker = LinuxSandboxBroker(config)
    grant = LocalSessionGrant('owned-agent-session', service.scope, registry.workspace, 1,
        ('PROJECT_WRITE', 'SANDBOX_EXEC'), digest, now, now + 300, 1, 0, 4, 5, 4096)
    inner = {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': 'sha256:' + 'd' * 64,
        'expected_target_revision': 'target-v1', 'payload': recipe.payload(registry.workspace, task, 'effect')}
    operation = {'operation_class': 'SANDBOX_EXEC', 'target_fingerprint': inner['target_fingerprint'],
        'expected_target_revision': inner['expected_target_revision'], 'payload': {'schema': 'aioa.local-operation.v2',
        'principal_session_id': host.instance_id, 'policy_epoch': 1, 'sandbox_operation': inner,
        'session_id': grant.session_id, 'session_grant_digest': grant.digest, 'task_digest': digest, 'manifest': {}}}
    approval = {'operation': operation, 'session_grant': grant.to_dict(), 'files': {}, 'summary': 'Owned fixed-port hook test'}
    data = {'schema': agent.KIND, 'task_id': task, 'state': 'AGENT_PENDING', 'task_digest': digest,
        'source_sha': host.source[0], 'capsule_digest': host.source[1], 'expires_at': now + 300,
        'approval_payload': approval, 'preview_digest': canonical_sha256(approval), 'config_ref': 'owned-review',
        'stop_requested': False, 'warrant': None, 'provider_id': 'offline-host', 'model_id': 'aioa/offline-host-worker-v1'}
    class Port:
        unknown = False
        on_session = None
        sessions = 0
        dispatches = 0
        def create_session(self, _owner, actual):
            case.assertEqual(grant, actual); self.sessions += 1
            if self.on_session is not None: self.on_session()
        def verify(self, actual_operation, warrant):
            case.assertEqual(operation, actual_operation)
            request = agent.dispatch_request(operation, warrant)
            raw = (config.root / ('run-' + request.digest) / 'artifact-result.json').read_bytes()
            case.assertEqual(artifact, raw)
            return Reconciliation(warrant.operation_hash, Applied('owned-agent-result'),
                EvidenceRef('owned-agent-result', 'receipt', 'sha256:' + hashlib.sha256(raw).hexdigest(), 'v1'),
                EvidenceRef('owned-agent-readback', 'independent-readback', 'sha256:' + canonical_sha256(['closed-owned-artifact', request.digest]), 'v1'))
        def dispatch_registered_local(self, principal, warrant, actual_operation, reservation, *, check, cancel):
            check(); case.assertFalse(cancel.cancelled); self.dispatches += 1
            journal = foundation.intent_journal
            journal._run(principal, Capability.COMMIT, lambda tx:
                journal._start_in_transaction(tx, warrant, actual_operation, reservation, local_zero=True))
            request = agent.dispatch_request(operation, warrant)
            run = config.root / ('run-' + request.digest); run.mkdir(mode=0o700)
            with (run / 'artifact-result.json').open('xb') as stream:
                stream.write(artifact); stream.flush(); os.fsync(stream.fileno())
            if self.unknown: raise ValueError('OWNED_AGENT_ACK_UNKNOWN')
            resolution = self.verify(operation, warrant)
            return journal._run(principal, Capability.COMMIT, lambda tx:
                journal.apply_resolution_in_transaction(tx, warrant, warrant.lease_epoch, resolution))
    port = Port(); port.errors = []; broker.verify = port.verify
    dispatch = port.dispatch_registered_local
    complete = agent._complete
    def diagnostic(call, *args, **kwargs):
        try: return call(*args, **kwargs)
        except ValueError as error:
            code = str(error)
            port.errors.append(code if __import__('re').fullmatch('[A-Z][A-Z0-9_]{0,99}', code) else type(error).__name__)
            raise
    port.dispatch_registered_local = lambda *args, **kwargs: diagnostic(dispatch, *args, **kwargs)
    case.enterContext(patch.object(agent, '_complete', side_effect=lambda *args, **kwargs: diagnostic(complete, *args, **kwargs)))
    case.enterContext(patch.object(service, 'agent_journal', foundation.intent_journal, create=True))
    route = agent._make_route(service, config, broker, foundation.liability)
    case.enterContext(patch.object(route, 'create_session', side_effect=port.create_session))
    case.enterContext(patch.object(route, 'dispatch_registered_local', side_effect=port.dispatch_registered_local))
    port.route = route
    attributes = {'agent_route': route, 'agent_epoch': 1, 'agent_governor': foundation.governor,
        'agent_journal': foundation.intent_journal, 'agent_broker': broker, 'agent_config': config,
        '_agent_routes': {'owned-review': route}, '_agent_configs': {'owned-review': config},
        '_agent_brokers': {'owned-review': broker}, '_agent_effect_lock': threading.RLock(), 'cpl_veto_reader': lambda: False}
    for name, value in attributes.items(): case.enterContext(patch.object(service, name, value, create=True))
    service._run(Capability.COMMIT, lambda tx: agent._save(service, tx, data))
    return SimpleNamespace(port=port, data=data, broker=broker, task=task)


class NativeAgentReviewTests(ReviewFixture):
    def start_agent(self, port):
        from runtime.meta_hackathon.native_authority import NativePhase
        self.f.lifecycle._phase = NativePhase.ACTIVE  # Controlled future hook, not a production builder.
        self.host.missions.run_agent(port.task, port.data['preview_digest'], self.host.core.local_operator(Capability.OWNER_APPROVAL))
        return self.f.lifecycle._handles[port.task]

    def test_agent_handle_first_precedes_session_and_completed_worker_retires(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        # The future graph coverage projection is controlled solely to isolate publication.
        coverage = self.f.lifecycle._coverage()
        port = agent_port(self, self.host); observed = []
        def before_session():
            handle = self.f.lifecycle._handles[port.task]; observed.append(handle)
            self.assertIs(handle.thread, self.host.missions._workers[port.task])
            self.assertIs(handle.cancel, self.host.missions._cancels[port.task])
            self.assertIsNone(handle.thread.ident)
            self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
            try:
                with patch.object(self.f.lifecycle, '_coverage', return_value=coverage), self.assertRaises(ValueError):
                    self.f.lifecycle.begin_capacity_review('7' * 32)
            finally: self.f.lifecycle._phase = NativePhase.ACTIVE
        port.port.on_session = before_session
        handle = self.start_agent(port); handle.thread.join(3)
        self.assertEqual([handle], observed)
        self.assertEqual('AGENT_COMPLETED', self.host.missions.agent_view(port.task, self.host.core.local_operator(Capability.READ))['state'], str(port.port.errors))
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertTrue(self.host.close()['closed'])
        self.assertIs(handle.broker, port.broker); self.assertIsNotNone(handle.cleanup)
        self.assertEqual((1, 1), (port.port.sessions, port.port.dispatches))

    def test_agent_fence_first_blocks_session_approval_claim_start_and_thread(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        self.f.lifecycle.begin_capacity_review('7' * 32)
        port = agent_port(self, self.host); before = self.rows()
        self.f.lifecycle._phase = NativePhase.ACTIVE
        try:
            with patch.object(self.host.ledger, 'approve', side_effect=AssertionError('NO_APPROVAL')), \
                 patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_WORKER')), self.assertRaises(ValueError):
                self.host.missions.run_agent(port.task, port.data['preview_digest'], self.host.core.local_operator(Capability.OWNER_APPROVAL))
        finally: self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual((0, 0), (port.port.sessions, port.port.dispatches)); self.assertEqual(before, self.rows())

    def test_agent_owned_settlement_reuses_parent_thread_token_without_new_start(self):
        from runtime.meta_hackathon.native_authority import NativeAccessUse, NativePhase
        port = agent_port(self, self.host); port.port.unknown = True
        handle = self.start_agent(port); handle.thread.join(3)
        original_thread, original_cancel = handle.thread, handle.cancel
        self.assertEqual('AGENT_UNKNOWN', self.host.missions.agent_view(port.task, self.host.core.local_operator(Capability.READ))['state'], str(port.port.errors))
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        with patch.object(port.port.route, 'create_session', side_effect=AssertionError('NO_SESSION')), \
             patch.object(port.port.route, 'dispatch_registered_local', side_effect=AssertionError('NO_DISPATCH')), \
             patch.object(self.host.ledger, 'approve', side_effect=AssertionError('NO_REAPPROVAL')), \
             patch.object(self.host.ledger, 'consume_in_transaction', side_effect=AssertionError('NO_CONSUME')), \
             patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_REPLACEMENT')), \
             patch.object(self.f.access, 'capture', wraps=self.f.access.capture) as capture:
            result = self.host.missions.reconcile_agent(port.task, self.host.core.local_operator(Capability.READ))
        self.assertEqual('AGENT_COMPLETED', result['state'], str(port.port.errors))
        self.assertIs(handle.thread, original_thread); self.assertIs(handle.cancel, original_cancel)
        self.assertIsNotNone(handle.cleanup); self.assertNotIn(port.task, self.f.lifecycle._handles)
        self.assertEqual(1, port.port.dispatches)
        self.assertTrue(capture.call_args_list)
        self.assertTrue(all(call.kwargs['use'] is NativeAccessUse.SETTLEMENT for call in capture.call_args_list))

    def test_agent_unproven_broker_cleanup_keeps_completed_handle(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        port = agent_port(self, self.host); handle = self.start_agent(port); handle.thread.join(3)
        port.broker._quarantined = True  # Negative injection into the actual broker cleanup state.
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertFalse(self.host.close()['closed'])
        self.assertIs(handle, self.f.lifecycle._handles[port.task]); self.assertIsNone(handle.cleanup)

    def test_admin_settlement_capture_keeps_exact_parent_role_and_execution_boundaries(self):
        from runtime.core_admission import AdmissionError
        from runtime.meta_hackathon.native_authority import NativeAccessUse, NativePhase

        port = agent_port(self, self.host)
        port.port.unknown = True
        parent = self.start_agent(port)
        parent.thread.join(3)
        self.assertFalse(parent.thread.is_alive())
        original_thread, original_cancel = parent.thread, parent.cancel
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        with self.host.missions._native_synchronous(port.task, 'AGENT_SETTLEMENT') as child:
            self.assertIs(child.parent, parent)
            self.assertIs(child.cancel, original_cancel)
            for purpose in (Capability.READ, Capability.COMMIT):
                capture = self.f.access.capture(purpose, use=NativeAccessUse.SETTLEMENT)
                try:
                    self.f.access.require_capture(capture, purpose)
                    self.assertIs(capture.work_handle, child)
                    self.assertIs(capture.core, self.host.core)
                finally:
                    capture.close()
            before = self.rows()
            original = (child.parent, child.kind, child.role, child.producer)
            invalid = (
                ('unparented', None, child.kind, child.role, child.producer),
                ('wrong-kind', parent, 'GITHUB_SETTLEMENT', child.role, child.producer),
                ('coding-worker', parent, child.kind, 'CODING_WORKER', child.producer),
                ('coding-http-effect', parent, child.kind, 'CODING_HTTP_EFFECT', child.producer),
                ('portable-effect', parent, child.kind, 'PORTABLE_EFFECT', child.producer),
                ('foreign-producer', parent, child.kind, child.role, object()),
            )
            for label, wrong_parent, wrong_kind, wrong_role, wrong_producer in invalid:
                try:
                    with self.f.lifecycle.lock:
                        child.parent, child.kind = wrong_parent, wrong_kind
                        child.role, child.producer = wrong_role, wrong_producer
                    with self.subTest(boundary=label), \
                         patch.object(self.host, '_require_qualified_operator',
                                      side_effect=AssertionError('ADMIN_DENIAL_MUST_PRECEDE_AUTH_SOURCE_SQL')):
                        for purpose in (Capability.READ, Capability.COMMIT):
                            with self.assertRaises(AdmissionError):
                                self.f.access.capture(purpose, use=NativeAccessUse.SETTLEMENT)
                finally:
                    with self.f.lifecycle.lock:
                        child.parent, child.kind, child.role, child.producer = original
            with patch.object(self.host, '_require_qualified_operator',
                              side_effect=AssertionError('ADMIN_EXECUTION_DENIAL_MUST_PRECEDE_AUTH_SOURCE_SQL')), \
                 self.assertRaises(AdmissionError):
                self.f.access.capture(Capability.COMMIT, use=NativeAccessUse.EXECUTION)
            self.assertEqual(before, self.rows())
        with self.assertRaises(AdmissionError):
            self.f.access.capture(Capability.READ, use=NativeAccessUse.SETTLEMENT)
        result = self.host.missions.reconcile_agent(port.task,
            self.host.core.local_operator(Capability.READ))
        self.assertEqual('AGENT_COMPLETED', result['state'], str(port.port.errors))
        self.assertIs(parent.thread, original_thread)
        self.assertIs(parent.cancel, original_cancel)
        self.assertEqual((1, 1), (port.port.sessions, port.port.dispatches))


def github_port(case, host):
    """Actual existing route/worker with fixed offline HTTP transport, no model/API."""
    from types import SimpleNamespace

    import test_github_remote_execution as protocol

    from runtime.mcp_bridge.github_remote import InstallationCredential
    from runtime.meta_hackathon.native_authority import NativePhase
    from runtime.mission.git_publish import DEMO_REPOSITORY, GitTreeSnapshot, git_object
    from runtime.mobile_gateway import wire
    service = host.missions
    # A fixed admitted offline identity; no provider/model call or extra assignment.
    case.enterContext(patch('runtime.providers.meta_model_api.MODEL', 'aioa/offline-host-worker-v1'))
    case.enterContext(patch.object(service, '_chat_governor', host.foundation.governor, create=True))
    case.enterContext(patch.object(github_write.github_remote.GitHubAppCredentialSource, 'configuration', return_value=({'installation_id': 73}, None)))
    base = GitTreeSnapshot(git_object('tree', b''), {})
    context = {'request_id': '9' * 32, 'receipt_sha256': '9' * 64, 'data_sha256': '8' * 64,
        'observed_at': int(time.time()), 'expires_at': int(time.time()) + 300,
        'data': {'repository': DEMO_REPOSITORY, 'repository_id': 1445911975, 'commit_sha': 'c' * 40,
                 'tree_sha': base.sha, 'read_source': 'OWNED_OFFLINE_FIXED_TRANSPORT'}}
    case.enterContext(patch('runtime.meta_hackathon.native_tools.chat_read_context', return_value=context))
    case.enterContext(patch.object(github_write, '_proposal_read_context', return_value=context))
    raw = json.dumps({'schema': 'aioa.muse.github-change.v1', 'operation': 'code.commit_draft_pr', 'target_repo': DEMO_REPOSITORY,
        'title': 'Owned reviewed change', 'body': 'Fixed offline hook fixture; no model.', 'files': {'agent-demo/review.py': 'VALUE = 1\n'}})
    message = {'reply': raw, 'receipt': {'response_sha256': wire.digest(raw.encode())}}
    port = protocol.RemoteExecutionTests(); port.setUp()
    port.credential = InstallationCredential('ghs_OWNED_FIX1_ONLY', 73, int(time.time()) + 3600, 'a' * 64, 'LIVE')
    case.enterContext(patch.object(github_write.github_remote.GitHubAppCredentialSource, 'mint', return_value=port.credential))
    case.enterContext(patch.object(github_write.github_remote, '_https_once', side_effect=port.transport))
    def propose():
        with patch.object(github_write.github_remote, 'read_demo_base', return_value=('c' * 40, base)):
            return github_write.propose(host, {'request_id': 'd' * 32, 'chat_request_id': 'a' * 32}, message)
    host.foundation.lifecycle._phase = NativePhase.ACTIVE
    review = propose()
    data = github_write.plain(host.mobile._get('native-github-' + 'd' * 32).payload)
    port.plan, port.base = github_write._decode(data)
    port.tree = port.base.add_files(port.plan.files); port.commit = port.plan.commit_sha_for_tree(port.tree.sha)
    port.marker_assertion = lambda: case.assertIsNotNone(host.mobile._get('github-step-' + 'd' * 32 + '-tree'))
    return SimpleNamespace(port=port, review=review, context=context, base=base, message=message,
        operation_id='d' * 32, task='github-' + 'd' * 32, request={'request_id': 'd' * 32, 'chat_request_id': 'a' * 32})


class NativeGitHubReviewTests(ReviewFixture):
    def approve_github(self, port, *, lose_terminal=False):
        original = github_write._save
        def save(host, operation_id, data, **kwargs):
            if lose_terminal and data['state'] == 'GITHUB_VERIFIED': raise ValueError('OWNED_TERMINAL_ACK_UNKNOWN')
            return original(host, operation_id, data, **kwargs)
        with patch.object(github_write, '_save', side_effect=save):
            github_write.dispatch(self.host, self.host.core.local_operator(Capability.OWNER_APPROVAL),
                {'op': 'github_write_approve', 'operation_id': port.operation_id, 'review_digest': port.review['review_digest']})
            handle = self.f.lifecycle._handles[port.task]; handle.thread.join(4)
        return handle

    def test_github_preflight_handle_first_blocks_review_with_same_token(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        port = github_port(self, self.host)
        observed = []
        request = {'request_id': 'e' * 32, 'chat_request_id': 'f' * 32}
        def preflight(*, check, cancel):
            handle = self.f.lifecycle._handles['sync-github_preflight-' + request['request_id']]
            observed.append(handle); self.assertIs(handle.thread, threading.current_thread()); self.assertIs(handle.cancel, cancel)
            self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
            try:
                with self.assertRaises(ValueError): self.f.lifecycle.begin_capacity_review('7' * 32)
            finally: self.f.lifecycle._phase = NativePhase.ACTIVE
            return 'c' * 40, port.base
        with patch.object(github_write.github_remote, 'read_demo_base', side_effect=preflight):
            result = github_write.propose(self.host, request, port.message)
        self.assertEqual('GITHUB_PROPOSED', result['status']); self.assertEqual(1, len(observed))
        self.assertIsNotNone(observed[0].cleanup); self.assertNotIn(observed[0].task_id, self.f.lifecycle._handles)

    def test_github_fence_first_blocks_preflight_claim_approval_and_worker(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        self.f.lifecycle.begin_capacity_review('7' * 32); before = self.rows()
        self.f.lifecycle._phase = NativePhase.ACTIVE
        try:
            with patch.object(github_write.github_remote, 'read_demo_base', side_effect=AssertionError('NO_PREFLIGHT')), \
                 patch.object(self.host.mobile, '_run', side_effect=AssertionError('NO_CLAIM')), \
                 patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_WORKER')):
                with self.assertRaises(ValueError): github_write.propose(self.host, {'request_id': 'd' * 32}, {})
                with self.assertRaises(ValueError): github_write.dispatch(self.host, self.host.core.local_operator(Capability.OWNER_APPROVAL), {'op': 'github_write_approve'})
        finally: self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual(before, self.rows())

    def test_github_worker_publishes_before_approval_and_terminal_owned_cleanup_retires(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        port = github_port(self, self.host); original = self.host.ledger.approve; observed = []
        def approve(owner, warrant):
            handle = self.f.lifecycle._handles[port.task]; observed.append(handle)
            self.assertIs(handle.thread, self.host.missions._workers[port.task]); self.assertIsNone(handle.thread.ident)
            self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
            try:
                with self.assertRaises(ValueError): self.f.lifecycle.begin_capacity_review('7' * 32)
            finally: self.f.lifecycle._phase = NativePhase.ACTIVE
            return original(owner, warrant)
        with patch.object(self.host.ledger, 'approve', side_effect=approve): handle = self.approve_github(port)
        self.assertEqual([handle], observed)
        self.assertEqual('GITHUB_VERIFIED', self.host.mobile._get('native-github-' + port.operation_id).payload['state'], str(self.host.mobile._get('native-github-' + port.operation_id).payload.get('error')))
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        self.assertEqual('REVIEWED', fx.review(self.host)['status'])
        self.assertIsNotNone(handle.cleanup); self.assertNotIn(port.task, self.f.lifecycle._handles)

    def _assert_private_github_settlement(self, phase):
        from types import SimpleNamespace

        from runtime.meta_hackathon.native_authority import NativeAccessUse
        port = github_port(self, self.host); handle = self.approve_github(port, lose_terminal=True)
        self.assertEqual('GITHUB_UNKNOWN', self.host.mobile._get('native-github-' + port.operation_id).payload['state'])
        original_thread, original_cancel = handle.thread, handle.cancel
        self.f.lifecycle._phase = phase
        start_calls = len(port.port.calls)
        # This is only the fixed server fixture's expected bearer, never a product credential.
        port.port.credential = SimpleNamespace(bearer=None)
        run = self.host.runner.run
        def pure_retry(context, callback):
            def invoke(tx):
                with patch.object(self.host, 'source_probe', side_effect=AssertionError('SOURCE_IO_IN_SETTLEMENT_TX')), \
                     patch.object(self.host, '_require_qualified_operator', side_effect=AssertionError('AUTH_IO_IN_SETTLEMENT_TX')):
                    return callback(tx)
            return run(context, invoke)
        with patch.object(self.host.runner, 'run', side_effect=pure_retry), \
             patch.object(github_write.github_remote.GitHubAppCredentialSource, 'mint', side_effect=AssertionError('NO_MINT')), \
             patch.object(self.host.ledger, 'approve', side_effect=AssertionError('NO_REAPPROVAL')), \
             patch.object(self.host.ledger, 'consume_in_transaction', side_effect=AssertionError('NO_CONSUME')), \
             patch.object(self.f.intent_journal, '_start_in_transaction', side_effect=AssertionError('NO_START')), \
             patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_REPLACEMENT')), \
             patch.object(self.f.access, 'capture', wraps=self.f.access.capture) as capture:
            result = self.host.operator_request(os.getuid(), {'op': 'github_write_reconcile', 'operation_id': port.operation_id})
        self.assertEqual('GITHUB_VERIFIED', result['status'])
        self.assertTrue(all(method == 'GET' for method, _, _ in port.port.calls[start_calls:]))
        self.assertIs(handle.thread, original_thread); self.assertIs(handle.cancel, original_cancel)
        self.assertIsNotNone(handle.cleanup); self.assertNotIn(port.task, self.f.lifecycle._handles)
        self.assertTrue(capture.call_args_list)
        self.assertTrue(all(call.kwargs['use'] is NativeAccessUse.SETTLEMENT for call in capture.call_args_list))

    def test_private_github_settlement_keeps_original_thread_token_and_has_no_new_start(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        self._assert_private_github_settlement(NativePhase.CAPACITY_ADMIN)

    def test_private_github_settlement_active_uses_only_fresh_settlement_captures(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        self._assert_private_github_settlement(NativePhase.ACTIVE)

    def _unknown_parent(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        port = github_port(self, self.host); handle = self.approve_github(port, lose_terminal=True)
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
        return port, handle

    def _assert_private_parent_denied(self, port, handle):
        before = self.rows()
        with patch.object(github_write.github_remote, '_https_once', side_effect=AssertionError('NO_UNPROVEN_GET')) as network, \
             patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_REPLACEMENT')):
            with self.assertRaises((ValueError, MemoryPatchError)):
                self.host.operator_request(os.getuid(), {'op': 'github_write_reconcile', 'operation_id': port.operation_id})
            network.assert_not_called()
        self.assertEqual(before, self.rows()); self.assertIs(handle, self.f.lifecycle._handles[port.task])
        self.assertIsNone(handle.cleanup); self.assertFalse(self.host.close()['closed'])

    def test_private_github_settlement_foreign_canonical_parent_denies_before_get(self):
        port, handle = self._unknown_parent()
        data = github_write.plain(self.host.mobile._get('native-github-' + port.operation_id).payload); data.pop('schema')
        data['core_instance_id'] = 'f' * 64
        github_write._save(self.host, port.operation_id, data)
        self._assert_private_parent_denied(port, handle)

    def test_private_github_settlement_missing_warrant_denies_before_get(self):
        port, handle = self._unknown_parent()
        data = github_write.plain(self.host.mobile._get('native-github-' + port.operation_id).payload); data.pop('schema')
        data['warrant'] = None
        github_write._save(self.host, port.operation_id, data)
        self._assert_private_parent_denied(port, handle)

    def test_private_github_settlement_cancelled_original_token_is_never_reset(self):
        port, handle = self._unknown_parent(); token = handle.cancel; token.cancel()
        self._assert_private_parent_denied(port, handle)
        self.assertIs(token, handle.cancel); self.assertTrue(token.cancelled)

    def test_private_github_settlement_expired_current_native_denies_before_get(self):
        port, handle = self._unknown_parent()
        self.host._tls_expires = time.time() - 1
        self._assert_private_parent_denied(port, handle)

    def test_private_github_settlement_orphan_denies_before_get_or_new_work(self):
        self.github_row('GITHUB_UNKNOWN')
        before = self.rows()
        with patch.object(github_write.github_remote, '_https_once', side_effect=AssertionError('NO_ORPHAN_GET')), \
             patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_ORPHAN_WORKER')), self.assertRaises((ValueError, MemoryPatchError)):
            self.host.operator_request(os.getuid(), {'op': 'github_write_reconcile', 'operation_id': 'a' * 32})
        self.assertEqual(before, self.rows())


class NativeFixBoundaryTests(ReviewFixture):
    def test_http_console_cannot_forward_native_private_settlement(self):
        from runtime.mobile_gateway import wire
        from runtime.webapp import WebRuntimeService
        service = WebRuntimeService(runtime=self.host.runtime, meta_missions=self.host.missions,
                                    meta_owner=self.host, mobile_gateway=self.host.mobile)
        service.mobile_only = True; service._mobile_console_uid = os.getuid()
        with patch.object(self.host, 'operator_request', side_effect=AssertionError('HTTP_OWNER_FORWARD_FORBIDDEN')) as owner:
            with self.assertRaises(wire.MobileError):
                service.mobile_operator_request({'op': 'github_write_reconcile', 'operation_id': 'a' * 32})
            owner.assert_not_called()

    def test_close_failure_after_real_core_close_retains_lease_and_never_recloses_core(self):
        original = self.host.core.close
        def closed_then_unknown():
            original()
            raise RuntimeError('OWNED_CORE_CLOSE_ACK_UNKNOWN')
        with patch.object(self.host.core, 'close', side_effect=closed_then_unknown) as close:
            with self.assertRaises(RuntimeError): self.host.close()
            self.assertEqual('QUARANTINED', self.host.close()['status'])
            self.assertEqual(1, close.call_count)
        self.assertFalse(self.host.core.configured); os.fstat(self.host._lease)
        self.assertEqual('UNKNOWN', self.host._native_close_steps['CORE'])
        self.assertNotIn('LEASE', self.host._native_close_steps)


class FixedLiveMissionPort:
    """Internal LIVE code kind, owned offline identity; no HTTP, key or model.

    Only the external provider is fixed. MetaLiveBinding checks, canonical
    MetaCallRecords ACKs, warrant consumption and governor history stay real.
    Protocol receipt labels are synthetic test data, never LIVE certification.
    """
    mode = 'LIVE'
    receipt_view = None

    def __init__(self, service):
        self.service = service
        self.calls = 0
        self.request = None
        self._active_attempt_id = None
        self.fail = False
        self.stop = False

    def generate_meta_plan(self, request, cancel, *, live_binding):
        from decimal import Decimal

        from runtime.providers.meta_model_api import ProviderPlan
        from runtime.providers.meta_receipts import MetaCallRecords
        from runtime.providers.tool_calling import ToolCall
        self.calls += 1
        self.request = request
        live_binding.check(request)
        records = MetaCallRecords(live_binding)
        self._active_attempt_id = records.admit(request)
        try:
            live_binding.release_once(request)
            records.change(request, 'IN_FLIGHT')
            if self.fail:
                records.change(request, 'UNKNOWN', error_code='META_NETWORK_UNKNOWN')
                if self.stop: cancel.cancel()
                raise ValueError('OWNED_FIXED_PROVIDER_UNKNOWN')
            plan = ProviderPlan(ToolCall('owned-fixed-plan', 'navigate_read', json.dumps(request.plan_fields())),
                request.digest, {'prompt_tokens': 50, 'completion_tokens': 30, 'total_tokens': 80},
                'META_API_LIVE_VERIFIED', str((Decimal(50) * Decimal('1.25') + Decimal(30) * Decimal('4.25')) / 1000000),
                model_id='aioa/offline-host-worker-v1', live_verified=True, binding=request.public_binding())
            records.change(request, 'COMPLETED', result=plan, http_status=200)
            if self.stop: cancel.cancel()
            return plan
        finally:
            self._active_attempt_id = None

    def receipt(self):
        row = self.service._run(Capability.READ,
            lambda tx: tx.get(RecordKind.RECEIPT, 'meta-api-' + self.request.digest))
        if row is None: return None
        row.verify()
        return json.loads(canonical_json_bytes(row.payload))

    def diagnostics(self):
        return {'last_live_receipt': self.receipt()}


def live_mission_port(case, host):
    from dataclasses import replace
    from datetime import timedelta
    from decimal import Decimal
    from types import SimpleNamespace

    from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
    from lab.archaioa.decision_root import DecisionDependencyRoot
    from lab.archaioa.evidence import EvidenceRef
    from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
    from runtime.memory_patch.contracts.serialization import canonical_sha256
    from runtime.meta_hackathon import mission_service
    from runtime.meta_hackathon.contracts import BrowserTaskV1
    from runtime.mission.governor import ReservationRequest
    from runtime.mission.warrant import approval_digest
    from runtime.providers import meta_model_api as api
    # Keep the actual Native assignment, fixed offline model and every budget.
    # MetaReceiptView's Muse-only validator is not patched or used as a proof.
    case.enterContext(patch.object(api, 'MODEL', 'aioa/offline-host-worker-v1'))
    case.enterContext(patch.object(mission_service, 'MODEL', 'aioa/offline-host-worker-v1'))
    service = host.missions
    port = FixedLiveMissionPort(service)
    service.manager = SimpleNamespace(_meta_provider=port, generate_meta_plan=port.generate_meta_plan)
    instruction = 'Read the owned fixture without dispatch.'
    preview = service.preview({'mode': 'LIVE', 'instruction': instruction,
        'target_url': 'https://docs.example.org/offline-fixture'}, host.core.local_operator(Capability.READ))
    request = api.MetaPlanRequest(BrowserTaskV1.parse(preview['task']), instruction,
        preview['correlation_id'], '.05', capsule_digest=preview['capsule_digest'])
    operation = api.spend_operation(request.digest, request.public_binding())
    now = host.ledger.clock()
    epoch = host.foundation.governor.inspect(host.core.local_operator(Capability.READ))['epoch']
    reservation = ReservationRequest('owned-live-spend', request.task.task_id, api.PROVIDER, api.MODEL,
        canonical_sha256(operation), 50000000, 1)
    commit = host.core.local_operator(Capability.COMMIT)
    host.foundation.governor.reserve(commit, reservation, epoch)
    authority = AuthorityScope(operation_classes=(api.SPEND_OPERATION,), target_scope=operation['target_fingerprint'],
        risk_ceiling=RiskLevel.MODERATE, monetary_ceiling=Money(Decimal('.05'), 'USD'), not_before=now,
        expires_at=now + timedelta(seconds=60), owner_scope=request.task.owner_scope_digest, task_scope=request.task.task_id)
    warrant = EffectWarrant(warrant_id='owned-live-warrant', task_id=request.task.task_id,
        owner_scope=request.task.owner_scope_digest, operation_class=api.SPEND_OPERATION,
        operation_hash='sha256:' + canonical_sha256(operation), target_fingerprint=operation['target_fingerprint'],
        expected_target_revision=request.task.source_sha, revision_policy=RevisionPolicy.REQUIRE,
        decision_dependency_root=DecisionDependencyRoot((EvidenceRef('owned-live-task', 'task',
            'sha256:' + request.task.digest, 'v1'),)), lease_epoch=epoch, authority_scope=authority,
        approval_digest='sha256:' + '0' * 64, money_reservation_id=reservation.request_id,
        risk_reservation_id=reservation.request_id, nonce='owned-live-nonce', issued_at=now, expires_at=now + timedelta(seconds=60))
    warrant = replace(warrant, approval_digest=approval_digest(warrant))
    host.ledger.approve(host.core.local_operator(Capability.OWNER_APPROVAL), warrant)
    binding = api.MetaLiveBinding(host.ledger, host.foundation.governor, commit, warrant, reservation,
        True, True, source_reader=host.source_probe)
    from runtime.meta_hackathon.native_authority import NativePhase
    host.foundation.lifecycle._phase = NativePhase.ACTIVE
    bound = service.bind_live_request(preview['task_id'], request, binding)
    return SimpleNamespace(port=port, bound=bound, request=request, binding=binding)


class NativeLiveMissionRetirementTests(ReviewFixture):
    def start_live(self, *, fail=False, stop=False):
        port = live_mission_port(self, self.host)
        port.port.fail, port.port.stop = fail, stop
        self.host.missions.run(port.bound['task_id'], port.bound['preview_digest'],
            self.host.core.local_operator(Capability.OWNER_APPROVAL))
        handle = self.f.lifecycle._handles[port.bound['task_id']]
        return port, handle

    def joined(self, handle):
        from runtime.meta_hackathon.native_authority import NativePhase
        handle.thread.join(3)
        self.assertFalse(handle.thread.is_alive())
        self.assertTrue(handle.done.is_set())
        self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN

    def settle(self, port):
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        receipt = port.port.receipt()
        self.assertIsNotNone(receipt)
        self.f.governor.settle(port.binding.principal, port.binding.reservation.request_id,
            port.binding.warrant.lease_epoch, canonical_sha256(receipt))

    def retained(self, handle):
        before = self.rows()
        with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
        self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
        self.assertIs(handle.thread, self.host.missions._workers[handle.task_id])
        self.assertIs(handle.cancel, self.host.missions._cancels[handle.task_id])
        self.assertIsNone(handle.cleanup)
        self.assertEqual(before, self.rows())
        self.assertFalse(self.host.close()['closed'])
        self.assertTrue(self.host.core.configured and self.host.runner.configured)
        os.fstat(self.host._lease)

    def positive(self, *, stop=False):
        port, handle = self.start_live(stop=stop)
        self.joined(handle)
        value = self.host.missions._get(handle.task_id).payload
        self.assertEqual(('STOPPED' if stop else 'BLOCKED', 'CONSUMED'),
            (value['state'], value['native_spend_binding']))
        self.assertEqual(1, port.port.calls)
        original_thread, original_cancel = handle.thread, handle.cancel
        self.settle(port)
        run = self.host.runner.run
        def pure(context, callback):
            def invoke(tx):
                with patch.object(self.host, 'source_probe', side_effect=AssertionError('SOURCE_IO_IN_RETIRE_TX')), \
                     patch.object(self.host.missions, 'source_probe', side_effect=AssertionError('MISSION_SOURCE_IO_IN_RETIRE_TX')), \
                     patch.object(self.host, '_require_qualified_operator', side_effect=AssertionError('AUTH_IO_IN_RETIRE_TX')):
                    return callback(tx)
            return run(context, invoke)
        with patch.object(self.host.runner, 'run', side_effect=pure), \
             patch.object(self.host.ledger, 'consume_in_transaction', side_effect=AssertionError('NO_RECONSUME')), \
             patch.object(self.f.intent_journal, '_start_in_transaction', side_effect=AssertionError('NO_START')), \
             patch.object(self.host.missions, '_prepare_native_worker', side_effect=AssertionError('NO_REPLACEMENT')):
            self.assertEqual('REVIEWED', fx.review(self.host)['status'])
        self.assertIs(handle.thread, original_thread)
        self.assertIs(handle.cancel, original_cancel)
        self.assertIsNotNone(handle.cleanup)
        self.assertNotIn(handle.task_id, self.f.lifecycle._handles)
        self.assertNotIn(handle.task_id, self.host.missions._workers)
        self.assertNotIn(handle.task_id, self.host.missions._cancels)
        self.assertEqual(1, port.port.calls)
        self.assertTrue(self.host.close()['closed'])

    def test_live_blocked_consumed_canonical_settlement_retires_original_and_closes(self):
        self.positive()

    def test_live_stopped_with_positive_receipt_settlement_retires_original_and_closes(self):
        self.positive(stop=True)

    def test_live_unknown_and_not_reusable_keep_original_ownership(self):
        port, handle = self.start_live(fail=True)
        self.joined(handle)
        value = self.host.missions._get(handle.task_id).payload
        self.assertEqual(('UNKNOWN', 'NOT_REUSABLE'), (value['state'], value['native_spend_binding']))
        self.assertIsNone(port.port.receipt())
        self.retained(handle)

    def test_live_stopped_without_positive_receipt_keeps_original_ownership(self):
        _, handle = self.start_live(fail=True, stop=True)
        self.joined(handle)
        value = self.host.missions._get(handle.task_id).payload
        self.assertEqual(('STOPPED', 'NOT_REUSABLE'), (value['state'], value['native_spend_binding']))
        self.retained(handle)

    def test_live_completed_receipt_without_financial_settlement_is_retained(self):
        port, handle = self.start_live()
        self.joined(handle)
        state = self.f.governor.inspect(self.host.core.local_operator(Capability.READ))
        self.assertEqual('UNKNOWN', state['reservations'][port.binding.reservation.request_id]['state'])
        self.assertIsNotNone(port.port.receipt())
        self.retained(handle)

    def test_live_missing_canonical_receipt_cannot_be_replaced_by_mission_copy(self):
        from runtime.memory_patch.persistence.ports import TransactionView
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        get = TransactionView.get
        def missing(tx, kind, identity):
            if kind is RecordKind.RECEIPT and identity == 'meta-api-' + port.request.digest: return None
            return get(tx, kind, identity)
        with patch.object(TransactionView, 'get', missing): self.retained(handle)

    def test_live_corrupt_or_foreign_canonical_receipt_is_retained(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        def corrupt(tx):
            row = tx.get(RecordKind.RECEIPT, 'meta-api-' + port.request.digest)
            value = json.loads(canonical_json_bytes(row.payload))
            value['warrant_digest'] = 'sha256:' + 'f' * 64
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, value), expected_revision=row.revision)
        self.host.runner.run(TransactionContext(port.binding.principal, Capability.COMMIT), corrupt)
        self.retained(handle)

    def test_live_settlement_with_foreign_evidence_digest_is_retained(self):
        port, handle = self.start_live()
        self.joined(handle)
        self.f.governor.settle(port.binding.principal, port.binding.reservation.request_id,
            port.binding.warrant.lease_epoch, 'f' * 64)
        self.retained(handle)

    def test_live_revoked_warrant_is_retained_after_receipt_and_settlement(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        self.host.ledger.revoke(self.host.core.local_operator(Capability.OWNER_APPROVAL), port.binding.warrant)
        self.retained(handle)

    def test_live_unproven_transport_cleanup_is_retained(self):
        from types import SimpleNamespace
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        handle.cancel.attach(SimpleNamespace(sock=None, close=lambda: None))
        self.retained(handle)

    def test_live_terminal_before_return_and_join_blocks_until_original_returns(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        entered, release = threading.Event(), threading.Event()
        change = self.host.missions._change
        def hold(*args, **kwargs):
            result = change(*args, **kwargs)
            if args[2] == 'BLOCKED':
                entered.set()
                if not release.wait(4): raise AssertionError('OWNED_LIVE_RETURN_BARRIER_TIMEOUT')
            return result
        try:
            with patch.object(self.host.missions, '_change', side_effect=hold):
                port, handle = self.start_live()
                self.assertTrue(entered.wait(3))
                self.settle(port)
                self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
                with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
                self.assertIsNone(handle.returned)
                self.assertFalse(handle.done.is_set())
                self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
                release.set(); handle.thread.join(3)
            self.assertEqual('REVIEWED', fx.review(self.host)['status'])
            self.assertIsNotNone(handle.cleanup)
        finally: release.set()

    def test_live_quarantined_exception_after_terminal_is_retained(self):
        execute = self.host.missions._execute_live
        def failed_after_terminal(*args):
            execute(*args)
            raise ValueError('OWNED_LIVE_RETURN_UNPROVEN')
        with patch.object(self.host.missions, '_execute_live', side_effect=failed_after_terminal):
            port, handle = self.start_live()
            self.joined(handle)
        self.settle(port)
        self.assertTrue(handle.quarantined)
        self.retained(handle)

    def test_live_expired_current_native_keeps_original_ownership(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        self.host._tls_expires = time.time() - 1
        self.retained(handle)


    def test_live_canonical_worker_can_drain_and_close_without_prior_review(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        self.assertTrue(self.f.lifecycle.drain())
        self.assertIsNotNone(handle.cleanup)
        self.assertNotIn(handle.task_id, self.f.lifecycle._handles)
        self.assertNotIn(handle.task_id, self.host.missions._workers)
        self.assertTrue(self.host.close()['closed'])

    def test_live_copied_context_cannot_retire_the_original_worker(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        handle.context = tuple(iter(handle.context))
        self.retained(handle)

    def test_live_missing_canonical_attempt_ack_is_retained(self):
        from runtime.memory_patch.persistence.ports import TransactionView
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        get = TransactionView.get
        def missing(tx, kind, identity):
            if kind is RecordKind.OPERATION and identity == 'meta-api-attempt-' + port.request.digest: return None
            return get(tx, kind, identity)
        with patch.object(TransactionView, 'get', missing): self.retained(handle)

    def test_live_missing_canonical_consumption_is_retained(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        def remove_consumption(tx):
            row = tx.get(RecordKind.OPERATION, self.host.ledger._key(port.binding.warrant))
            value = json.loads(canonical_json_bytes(row.payload)); value['consumption'] = None
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, value), expected_revision=row.revision)
        self.host.runner.run(TransactionContext(port.binding.principal, Capability.COMMIT), remove_consumption)
        self.retained(handle)

    def test_live_current_source_drift_keeps_original_ownership(self):
        port, handle = self.start_live()
        self.joined(handle); self.settle(port)
        self.host.source_probe = lambda: ('f' * 40, 'f' * 64)
        self.retained(handle)

    def test_live_returned_done_worker_still_requires_actual_thread_join(self):
        from runtime.meta_hackathon.native_authority import NativePhase
        entered, finish_worker = threading.Event(), threading.Event()
        done_called, exit_thread = threading.Event(), threading.Event()
        execute = self.host.missions._execute_live
        def hold_execute(*args):
            execute(*args)
            entered.set()
            if not finish_worker.wait(4): raise AssertionError('OWNED_LIVE_FINISH_TIMEOUT')
        try:
            with patch.object(self.host.missions, '_execute_live', side_effect=hold_execute):
                port, handle = self.start_live()
                self.assertTrue(entered.wait(3)); self.settle(port)
                original_set = handle.done.set
                def hold_done():
                    original_set(); done_called.set()
                    if not exit_thread.wait(4): raise AssertionError('OWNED_LIVE_JOIN_TIMEOUT')
                with patch.object(handle.done, 'set', side_effect=hold_done):
                    finish_worker.set(); self.assertTrue(done_called.wait(3))
                    self.f.lifecycle._phase = NativePhase.CAPACITY_ADMIN
                    self.assertTrue(handle.done.is_set() and handle.thread.is_alive())
                    self.assertIsNotNone(handle.returned)
                    with self.assertRaises((ValueError, MemoryPatchError)): fx.review(self.host)
                    self.assertIs(handle, self.f.lifecycle._handles[handle.task_id])
                    self.assertIsNone(handle.cleanup)
                    exit_thread.set(); handle.thread.join(3)
            self.assertEqual('REVIEWED', fx.review(self.host)['status'])
            self.assertIsNotNone(handle.cleanup)
        finally:
            finish_worker.set(); exit_thread.set()
