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
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from main import create_runtime
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

    def start_core(self, config=None):
        self.app = WebRuntimeService(runtime=create_runtime(cpl_fixture=True, nonzero_config=config))
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

    def restart_core(self, config=None):
        self.stop_core()
        self.start_core(config)

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
        self.restart_core({'enabled': False})
        status = self.api('GET', '/api/nonzero/status')
        self.assertEqual(status['availability_code'], 'NONZERO_DISABLED')
        self.api('GET', '/api/nonzero/ready', expected=503)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertIn('critical_loop', self.api('GET', '/api/status'))

    def test_core_explicit_aws_selection_is_unavailable(self):
        for enabled, code in [(False, 'NONZERO_AWS_EXPLICIT_ENABLEMENT_REQUIRED'),
                              (True, 'NONZERO_AWS_BACKEND_NOT_CERTIFIED')]:
            with self.subTest(aws_enabled=enabled):
                self.restart_core({'backend': 'aws', 'aws_enabled': enabled})
                status = self.api('GET', '/api/nonzero/status')
                self.assertEqual(status['availability_code'], code)
                self.assertFalse(status['live_aws_enabled'])
                self.api('POST', '/api/nonzero/runs', TARGET, expected=503)
                self.assertIsNone(self.app.runtime._nonzero_service)
                self.assertEqual(list(Path(self.temporary.name).rglob('native-v1')), [])
                self.assertIn('evidence_review', self.api('GET', '/api/status'))

    def test_core_malformed_config_is_typed_without_state_initialization(self):
        self.restart_core({'enabled': 'yes'})
        status = self.api('GET', '/api/nonzero/status')
        self.assertEqual(status['availability_code'], 'NONZERO_CONFIG_INVALID')
        self.api('POST', '/api/nonzero/runs', TARGET, expected=400)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertIn('critical_loop', self.api('GET', '/api/status'))

    def test_phase6_config_assignment_cannot_diverge_from_active_service(self):
        self.api('GET', '/api/nonzero/ready')
        runtime = self.app.runtime
        service = runtime.nonzero_cloudops
        for replacement in ({'enabled': False}, {'backend': 'aws'}, {'enabled': 'yes'}):
            with self.subTest(config=replacement):
                with self.assertRaises(AttributeError):
                    runtime.nonzero_config = replacement
                with self.assertRaises(AttributeError):
                    service.config = replacement
                status = self.api('GET', '/api/nonzero/status')
                self.assertTrue(status['available'])
                self.assertTrue(status['initialized'])
                self.assertEqual(status['mode'], 'portable')
                self.assertIs(runtime.nonzero_cloudops, service)
        with self.assertRaises(FrozenInstanceError):
            runtime.nonzero_config.enabled = False
        self.assertEqual(self.api('GET', '/api/nonzero/ready')['status'], 'ready')

    def test_phase6_startup_snapshot_does_not_retain_input_dictionary(self):
        config = {'enabled': False}
        self.restart_core(config)
        config['enabled'] = True
        status = self.api('GET', '/api/nonzero/status')
        self.assertEqual(status['availability_code'], 'NONZERO_DISABLED')
        self.assertFalse(status['initialized'])
        self.api('POST', '/api/nonzero/runs', TARGET, expected=503)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertEqual(list(Path(self.temporary.name).rglob('native-v1')), [])
        self.restart_core(config)
        self.assertFalse(self.api('GET', '/api/nonzero/status')['initialized'])
        self.assertEqual(self.api('GET', '/api/nonzero/ready')['status'], 'ready')
        self.assertTrue(self.api('GET', '/api/nonzero/status')['initialized'])

    def test_phase6_malformed_snapshot_cannot_be_repaired_by_input_mutation(self):
        config = {'enabled': 'yes'}
        self.restart_core(config)
        config['enabled'] = True
        self.assertEqual(self.api('GET', '/api/nonzero/status')['availability_code'],
                         'NONZERO_CONFIG_INVALID')
        self.api('POST', '/api/nonzero/runs', TARGET, expected=400)
        self.assertIsNone(self.app.runtime._nonzero_service)
        self.assertEqual(list(Path(self.temporary.name).rglob('native-v1')), [])

    def test_phase6_close_cannot_reinitialize_or_keep_cached_service_available(self):
        from nonzero_cloudops import NonZeroError
        runtime = self.app.runtime
        self.api('GET', '/api/nonzero/ready')
        service = runtime.nonzero_cloudops
        runtime.close()
        self.assertFalse(runtime.nonzero_status()['available'])
        self.assertFalse(service.status()['available'])
        with self.assertRaises(NonZeroError) as failure:
            _ = runtime.nonzero_cloudops
        self.assertEqual(failure.exception.code, 'NONZERO_SERVICE_CLOSED')
        with self.assertRaises(NonZeroError):
            service.ready(operator=True)
        self.assertEqual(service.components.executor.mutation_calls, 0)

    def test_phase6_request_append_failure_prevents_protected_dispatch(self):
        path = self.start_run()
        self.approve(path)
        service = self.app.runtime.nonzero_cloudops
        checkpoint = service.components.repository.get_checkpoint(UUID(path.rsplit('/', 1)[1]))
        with patch.object(service.provenance, 'append_event', side_effect=OSError('injected disk failure')):
            failed = self.resume(path, expected=503)
        self.assertEqual(failed['error'], 'NONZERO_PROVENANCE_WRITE_FAILED')
        self.assertEqual(service.components.executor.execute_calls, 0)
        self.assertEqual(service.components.repository.get_checkpoint(checkpoint.run_id), checkpoint)
        self.assertEqual(self.resume(path)['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(service.components.executor.mutation_calls, 1)

    def test_phase6_post_decision_evidence_failure_reconciles_exact_decision(self):
        path = self.start_run()
        body = self.challenge(path)
        service = self.app.runtime.nonzero_cloudops
        append = service.provenance.append_event

        def fail_result(kind, payload):
            if kind == 'nonzero_operator_result':
                raise OSError('injected result write failure')
            return append(kind, payload)

        with patch.object(service.provenance, 'append_event', side_effect=fail_result):
            self.api('POST', path+'/decision', body, expected=503)
        run_id = UUID(body['run_id'])
        saved = service.components.repository.get_checkpoint(run_id).local_approval
        self.assertIsNotNone(saved)
        self.assertEqual(service.components.executor.mutation_calls, 0)
        self.restart_core()
        retried = self.api('POST', path+'/decision', body)
        self.assertTrue(retried['reconciled'])
        self.assertEqual(retried['decision_hash'], saved.decision_hash)
        service = self.app.runtime.nonzero_cloudops
        self.assertEqual(service.components.repository.get_checkpoint(run_id).local_approval, saved)
        self.api('POST', path+'/decision', {**body, 'decision': 'DENIED'}, expected=409)
        events = service.components.repository.read_run_snapshot(run_id).audit_events
        self.assertEqual(sum(event.type.value == 'APPROVAL_RECORDED' for event in events), 1)
        self.assertEqual(service.components.executor.mutation_calls, 0)

    def test_phase6_post_mutation_evidence_failure_recovers_same_durable_proof(self):
        path = self.start_run()
        self.approve(path)
        service = self.app.runtime.nonzero_cloudops
        append = service.provenance.append_event

        def fail_result(kind, payload):
            if kind == 'nonzero_operator_result':
                raise OSError('injected result write failure')
            return append(kind, payload)

        with patch.object(service.provenance, 'append_event', side_effect=fail_result):
            self.resume(path, expected=503)
        checkpoint = service.components.repository.get_checkpoint(UUID(path.rsplit('/', 1)[1]))
        receipt = checkpoint.local_execution_receipt.model_dump(mode='json', exclude_none=True)
        verification = checkpoint.local_verification.model_dump(mode='json', exclude_none=True)
        self.assertEqual(service.components.executor.mutation_calls, 1)
        self.restart_core()
        done = self.resume(path)
        self.assertTrue(done['reconciled'])
        self.assertEqual(done['receipt'], receipt)
        self.assertEqual(done['verification'], verification)
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.execute_calls, 0)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 1)
        entries = self.api('GET', '/api/nonzero/trace')['entries']
        resumes = [item for item in entries if item['payload']['operation'] == 'execute-approved-portable']
        self.assertEqual([item['event_type'] for item in resumes],
                         ['nonzero_operator_request', 'nonzero_operator_request', 'nonzero_operator_result'])
        self.assertIn(receipt['receipt_hash'], json.dumps(resumes[-1]))
        self.assertTrue(resumes[-1]['payload']['evidence']['value']['reconciled'])

    def test_phase6_truncation_after_success_requires_explicit_integrity_repair(self):
        path = self.start_run()
        self.approve(path)
        done = self.resume(path)
        service = self.app.runtime.nonzero_cloudops
        log = service.provenance.log_path
        original = log.read_bytes()
        # A valid prefix passes hash-chain verification without the durable head.
        log.write_bytes(b''.join(original.splitlines(keepends=True)[:-1]))
        failed = self.resume(path, expected=409)
        self.assertEqual(failed['error'], 'NONZERO_PROVENANCE_HEAD_MISMATCH')
        self.api('POST', '/api/nonzero/runs', GROUP, expected=409)
        self.assertEqual(service.components.executor.mutation_calls, 1)
        self.restart_core()
        self.resume(path, expected=409)
        self.assertIsNone(self.app.runtime._nonzero_service)
        # Explicit operator restoration of the exact saved log, not auto-adoption.
        log.write_bytes(original)
        recovered = self.resume(path)
        self.assertTrue(recovered['reconciled'])
        self.assertEqual(recovered['receipt'], done['receipt'])
        self.assertEqual(recovered['verification'], done['verification'])
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.execute_calls, 0)

    def test_phase6_corruption_after_success_blocks_new_protected_operation(self):
        path = self.start_run()
        self.approve(path)
        self.resume(path)
        service = self.app.runtime.nonzero_cloudops
        log = service.provenance.log_path
        log.write_bytes(log.read_bytes().replace(b'nonzero_operator_result', b'nonzero_operator_tamper', 1))
        self.api('POST', '/api/nonzero/runs', GROUP, expected=409)
        self.resume(path, expected=409)
        self.assertEqual(service.components.executor.mutation_calls, 1)

    def test_phase6_missing_head_never_silently_reanchors_existing_state(self):
        path = self.start_run()
        service = self.app.runtime.nonzero_cloudops
        service._evidence.head_path.unlink()
        self.restart_core()
        self.api('POST', path+'/approval-request', {}, expected=409)
        self.assertIsNone(self.app.runtime._nonzero_service)

    def test_phase6_head_write_failure_after_request_fsync_prevents_dispatch(self):
        path = self.start_run()
        self.approve(path)
        service = self.app.runtime.nonzero_cloudops
        with patch.object(service._evidence, '_write_head', side_effect=OSError('injected head failure')):
            self.resume(path, expected=503)
        self.assertEqual(service.components.executor.execute_calls, 0)
        self.resume(path, expected=409)
        self.assertEqual(service.components.executor.execute_calls, 0)

    def test_phase6_minimum_output_budget_executes_both_actions_once(self):
        self.restart_core({'max_output_bytes': 16384})
        for target in (TARGET, GROUP):
            with self.subTest(target=target['resource_type']):
                result = self.api('POST', '/api/nonzero/runs', target, expected=201)
                path = '/api/nonzero/runs/'+result['run_id']
                self.approve(path)
                done = self.resume(path)
                self.assertEqual(done['final_state'], 'SUCCESS_WITH_EVIDENCE')
                self.assertLess(len(json.dumps(done).encode()), 16384)
                retried = self.resume(path)
                self.assertTrue(retried['reconciled'])
                self.assertEqual(retried['receipt'], done['receipt'])
                self.assertEqual(retried['verification'], done['verification'])
                self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 1)
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 2)

    def test_phase6_large_resource_budget_rejects_before_intent_and_mutation(self):
        self.restart_core({'max_output_bytes': 16384})
        self.api('GET', '/api/nonzero/ready')
        service = self.app.runtime.nonzero_cloudops
        inventory = service.components.inventory
        resources, receipts = inventory._initial_snapshot()
        # Seed a larger valid synthetic fixture; all decisions/execution use HTTP.
        for key, resource in list(resources.items()):
            if resource.resource_id == GROUP['resource_id']:
                resources[key] = type(resource).model_validate({
                    **resource.model_dump(), 'tags': {str(i): 'x'*200 for i in range(16)},
                })
        inventory._write(resources, receipts)
        path = self.start_run(GROUP)
        self.approve(path)
        entries = len(service.provenance.read_all())
        for _ in range(2):
            failed = self.resume(path, expected=409)
            self.assertEqual(failed['error'], 'NONZERO_EXECUTION_OUTPUT_BUDGET_INSUFFICIENT')
        self.assertEqual(len(service.provenance.read_all()), entries)
        self.assertEqual(service.components.executor.execute_calls, 0)
        self.assertEqual(self.api('GET', path)['run_sandbox_mutations'], 0)
        self.restart_core({'max_output_bytes': 32768})
        done = self.resume(path)
        self.assertEqual(done['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(self.app.runtime.nonzero_cloudops.components.executor.mutation_calls, 1)
