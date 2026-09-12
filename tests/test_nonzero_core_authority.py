"""Phase 4: every scenario enters through the public, authenticated Core API.

Private references are used only to inject deterministic faults or observe
mutation counters. They never start/approve/resume a workflow. No oracle reads.
"""
import http.client
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID

from nonzero_cloudops import module_descriptor
from webapp import WebRuntimeService, make_server

AVAILABLE = module_descriptor()['available']
TARGET = {'resource_type': 'AWS::EC2::EIP', 'resource_id': 'eipalloc-0123456789abcdef0'}
GROUP = {'resource_type': 'AWS::EC2::SecurityGroup', 'resource_id': 'sg-0123456789abcdef0'}
if AVAILABLE:
    from nonzero_cloudops.adapters.portable import PortableConflictError
    from nonzero_cloudops.models.errors import StorageDependencyError


@unittest.skipUnless(AVAILABLE, 'NonZero optional extra is not installed')
class CoreNativeAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.environment = patch.dict('os.environ', {'AOIA_HOME': self.temporary.name})
        self.environment.start()
        self.now = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
        self.clock_patch = patch('nonzero_cloudops.service.datetime')
        self.clock_patch.start().now.side_effect = lambda _zone: self.now
        self.start_core()

    def start_core(self):
        self.app = WebRuntimeService(cpl_fixture=True)
        self.server = make_server('127.0.0.1', 0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.token = self.api('GET', '/api/session', authenticated=False)['token']

    def stop_core(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.app.close()
        self.assertFalse(self.thread.is_alive())

    def restart_core(self):
        self.stop_core()
        self.start_core()

    def tearDown(self):
        self.stop_core()
        self.clock_patch.stop()
        self.environment.stop()
        self.temporary.cleanup()

    def api(self, method, path, payload=None, *, expected=200, authenticated=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        headers = {'Content-Type': 'application/json', 'X-AIOA-Intent': 'nonzero-operator-v1'}
        if authenticated:
            headers['X-AIOA-Session-Token'] = self.token
        connection.request(method, path, None if payload is None else json.dumps(payload), headers)
        response = connection.getresponse()
        status, body = response.status, json.loads(response.read())
        connection.close()
        self.assertEqual(status, expected, f'{method} {path}: HTTP {status}')
        return body.get('result', body)

    def start_run(self, target=None):
        result = self.api('POST', '/api/nonzero/runs', target or TARGET, expected=201)
        self.assertEqual(result['final_state'], 'AWAITING_APPROVAL')
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)
        return '/api/nonzero/runs/'+result['run_id']

    def challenge(self, path):
        challenge = self.api('POST', path+'/approval-request', {})
        request = challenge['request']
        fields = ('request_id', 'run_id', 'proposal_id', 'request_hash', 'proposal_hash',
                  'evidence_hash', 'proposal_version')
        return {**{field: request[field] for field in fields},
                'decision': 'APPROVED', 'decision_nonce': challenge['decision_nonce']}

    def approve(self, path, choice='APPROVED'):
        body = {**self.challenge(path), 'decision': choice}
        self.api('POST', path+'/decision', body)
        return body

    def resume(self, path, expected=200):
        return self.api('POST', path+'/resume', {'confirm_execution': True}, expected=expected)

    def test_core_approve_one_runtime_verified_receipt_and_trace(self):
        status = self.api('GET', '/api/status')
        for module in ('critical_loop', 'evidence_review', 'nonzero_cloudops'):
            self.assertIn(module, status)
        self.assertTrue(self.api('GET', '/api/nonzero/status')['available'])
        path = self.start_run()
        self.resume(path, expected=403)  # No implicit approval at the Core boundary.
        body = self.approve(path)
        done = self.resume(path)
        self.assertEqual(done['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(done['verification']['receipt_hash'], done['receipt']['receipt_hash'])
        self.assertTrue(done['verification']['observed_absent'])
        self.assertNotIn('observed_resource', done['verification'])
        self.assertNotIn('after_resource', done['receipt'])
        self.assertEqual(done['verification']['target_resource_id'], TARGET['resource_id'])
        self.assertEqual(done['receipt']['operation_type'], 'RELEASE_ELASTIC_IP')
        trace = self.api('GET', '/api/nonzero/trace')
        self.assertTrue(trace['ok'])
        rendered = json.dumps(trace)
        self.assertIn(done['receipt']['receipt_hash'], rendered)
        self.assertNotIn(body['decision_nonce'], rendered)
        view = self.api('GET', path)
        self.assertEqual(view['run_sandbox_mutations'], 1)
        self.assertEqual(view['evidence_integrity'], 'VERIFIED')
        self.assertEqual(view['runtime']['process_external_network_calls'], 0)
        self.assertFalse(view['runtime']['real_cloud_mutations_enabled'])
        runtime = self.app.runtime
        cli = runtime.command_registry.execute('/nonzero trace', runtime)
        self.assertEqual(cli.exit_code, 0)
        self.assertIs(runtime.nonzero_cloudops, runtime._nonzero_service)
        self.assertEqual(runtime._owned_cpl_fixture.requests, [])

    def test_core_deny_is_durable_and_never_mutates(self):
        path = self.start_run()
        self.approve(path, 'DENIED')
        self.restart_core()
        done = self.resume(path)
        self.assertEqual(done['final_state'], 'DENIED_BY_HUMAN')
        self.assertNotIn('receipt', done)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 0)
        self.assertTrue(self.api('GET', '/api/nonzero/trace')['ok'])

    def test_core_proposal_swap_cannot_authorize_another_action(self):
        first = self.start_run()
        body = self.challenge(first)
        second = self.start_run(GROUP)
        self.challenge(second)
        self.api('POST', second+'/decision', body, expected=400)
        self.api('POST', second+'/decision', {**body, 'run_id': second.rsplit('/', 1)[1]}, expected=403)
        self.resume(second, expected=403)
        self.assertEqual(self.api('GET', second)['run_sandbox_mutations'], 0)

    def test_core_stale_and_expired_challenges_fail_closed(self):
        path = self.start_run()
        stale = self.challenge(path)
        fresh = self.challenge(path)
        self.api('POST', path+'/decision', stale, expected=403)
        self.now += timedelta(seconds=601)
        self.api('POST', path+'/decision', fresh, expected=403)
        self.resume(path, expected=403)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 0)

    def test_core_replay_and_concurrent_resume_execute_once(self):
        path = self.start_run()
        body = self.approve(path)
        self.assertTrue(self.api('POST', path+'/decision', body)['reconciled'])
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.resume(path), range(4)))
        self.assertEqual(len({item['receipt']['receipt_hash'] for item in results}), 1)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 1)
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 1)

    def test_core_restart_requires_operator_resume(self):
        path = self.start_run()
        self.approve(path)
        self.restart_core()
        self.assertIsNone(self.app.runtime._nonzero_service)
        view = self.api('GET', path)
        self.assertEqual(view['run']['state'], 'APPROVED')
        self.assertEqual(view['run_sandbox_mutations'], 0)
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)
        self.api('POST', path+'/resume', {'confirm_execution': False}, expected=400)
        self.assertEqual(self.resume(path)['final_state'], 'SUCCESS_WITH_EVIDENCE')

    def test_core_post_mutation_checkpoint_failure_reconciles_once(self):
        path = self.start_run()
        self.approve(path)
        repository = self.app.runtime.nonzero_cloudops.components.repository
        save = repository.save_checkpoint

        def lose_checkpoint(checkpoint, **kwargs):
            if checkpoint.local_execution_receipt is not None:
                raise StorageDependencyError('synthetic checkpoint interruption')
            return save(checkpoint, **kwargs)

        with patch.object(repository, 'save_checkpoint', side_effect=lose_checkpoint):
            result = self.resume(path, expected=409)
        self.assertEqual(result['failure_code'], 'LOCAL_RECEIPT_DURABILITY_FAILED')
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 1)
        self.restart_core()
        self.assertEqual(self.resume(path)['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 1)

    def test_core_uncertain_execution_never_blindly_retries(self):
        path = self.start_run()
        self.approve(path)
        executor = self.app.runtime.nonzero_cloudops.components.executor
        with patch.object(executor, 'execute', side_effect=PortableConflictError) as execute:
            self.resume(path, expected=409)
            execute.assert_called_once()
        self.restart_core()
        self.api('GET', path)
        with patch.object(self.app.runtime.nonzero_cloudops.components.executor, 'execute') as retry:
            self.resume(path, expected=409)
            retry.assert_not_called()
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 0)

    def test_core_tampered_provenance_cannot_report_success(self):
        path = self.start_run()
        self.approve(path)
        self.app.runtime.nonzero_cloudops.provenance.append_event('tampered_source', {'source_sha': '0'*40})
        self.resume(path, expected=409)
        self.api('GET', '/api/nonzero/trace', expected=409)
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 0)

    def test_core_wrong_independent_verification_identity_is_not_success(self):
        path = self.start_run()
        self.approve(path)
        executor = self.app.runtime.nonzero_cloudops.components.executor
        verify = executor.verify

        def mismatched(receipt):
            return verify(receipt).model_copy(update={'proposal_id': UUID('00000000-0000-7000-8000-000000000099')})

        with patch.object(executor, 'verify', side_effect=mismatched):
            result = self.resume(path, expected=503)
        self.assertNotIn('receipt', result)
        self.assertNotEqual(self.api('GET', path)['run']['state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(executor.mutation_calls, 1)

    def test_core_disabled_module_preserves_core_health(self):
        self.app.runtime.nonzero_config = {'enabled': False}
        status = self.api('GET', '/api/nonzero/status')
        self.assertEqual(status['availability_code'], 'NONZERO_DISABLED')
        self.api('GET', '/api/nonzero/ready', expected=503)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertIn('critical_loop', self.api('GET', '/api/status'))

    def test_core_explicit_aws_selection_is_unavailable(self):
        for enabled, code in [(False, 'NONZERO_AWS_EXPLICIT_ENABLEMENT_REQUIRED'),
                              (True, 'NONZERO_AWS_BACKEND_NOT_CERTIFIED')]:
            with self.subTest(aws_enabled=enabled):
                self.app.runtime.nonzero_config = {'backend': 'aws', 'aws_enabled': enabled}
                status = self.api('GET', '/api/nonzero/status')
                self.assertEqual(status['availability_code'], code)
                self.assertFalse(status['live_aws_enabled'])
                self.api('POST', '/api/nonzero/runs', TARGET, expected=503)
                self.assertIsNone(self.app.runtime._nonzero_service)
                self.assertIn('evidence_review', self.api('GET', '/api/status'))

    def test_core_malformed_config_is_typed_without_state_initialization(self):
        self.app.runtime.nonzero_config = {'enabled': 'yes'}
        status = self.api('GET', '/api/nonzero/status')
        self.assertEqual(status['availability_code'], 'NONZERO_CONFIG_INVALID')
        self.api('POST', '/api/nonzero/runs', TARGET, expected=400)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertIn('critical_loop', self.api('GET', '/api/status'))
