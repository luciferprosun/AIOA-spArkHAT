"""Core-owned contracts; baseline tests remain unchanged in the imported subtree."""
import http.client
import importlib.metadata
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from commands import build_command_registry
from nonzero_cloudops import NonZeroCloudOpsService, NonZeroError, module_descriptor
from nonzero_cloudops.service import BASELINE, JUDGE_SHA
from webapp import WebRuntimeService, make_server

AVAILABLE = module_descriptor()['available']
TARGET = {'resource_type': 'AWS::EC2::EIP', 'resource_id': 'eipalloc-0123456789abcdef0'}


def decision(challenge, value='APPROVED'):
    request = challenge['request']
    result = {name: request[name] for name in ('request_id', 'run_id', 'proposal_id',
        'request_hash', 'proposal_hash', 'evidence_hash', 'proposal_version')}
    return {**result, 'decision_nonce': challenge['decision_nonce'], 'decision': value}


class NonZeroRegistrationTests(unittest.TestCase):
    def test_existing_registry_and_dependency_free_discovery(self):
        names = build_command_registry().names()
        for name in ['nonzero', 'cpl', 'review', 'model', 'hat', 'providers', 'tools']:
            self.assertIn(name, names)
        descriptor = module_descriptor()
        self.assertEqual(descriptor['source_sha'], JUDGE_SHA)
        self.assertEqual(descriptor['mode'], 'portable')
        self.assertFalse(descriptor['live_aws_enabled'])
        self.assertFalse(descriptor['external_models_enabled'])
        result = build_command_registry().execute('/nonzero status', None)
        self.assertTrue(json.loads(result.message)['registered'])
        self.assertEqual(result.exit_code, 0)

    def test_missing_optional_dependencies_fail_without_state_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'nz'
            with patch('nonzero_cloudops.service.importlib.metadata.version',
                       side_effect=importlib.metadata.PackageNotFoundError):
                self.assertFalse(module_descriptor()['available'])
                with self.assertRaisesRegex(NonZeroError, 'OPTIONAL_DEPENDENCIES_UNAVAILABLE'):
                    NonZeroCloudOpsService(root)
            self.assertFalse(root.exists())

    def test_baseline_is_local_and_license_preserved(self):
        self.assertTrue((BASELINE / 'LICENSE').read_text().startswith('MIT License'))
        self.assertTrue((BASELINE / 'pyproject.toml').is_file())
        self.assertTrue((BASELINE / 'tests').is_dir())
        self.assertFalse((BASELINE / '.git').exists())


@unittest.skipUnless(AVAILABLE, 'Non-Zero optional Python >=3.12 extra is not installed')
class NonZeroServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'nz'
        self.service = NonZeroCloudOpsService(self.root)

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def call(self, method, path, payload=None, expected=200):
        status, body = self.service.request(method, path, payload, operator=True)
        self.assertEqual(status, expected, body)
        return body.get('result', body)

    def start(self):
        result = self.call('POST', '/api/runs', TARGET, expected=201)
        self.assertEqual(result['final_state'], 'AWAITING_APPROVAL')
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)
        return result['run_id']

    def test_full_operator_flow_and_replay_survives_restart(self):
        run = self.start()
        path = '/api/runs/' + run
        blocked = self.call('POST', path + '/resume', {'confirm_execution': True}, expected=403)
        self.assertEqual(blocked['failure_code'], 'LOCAL_APPROVAL_REQUIRED')
        challenge = self.call('POST', path + '/approval-request', {})
        valid = decision(challenge)
        mismatch = self.call('POST', path + '/decision', {**valid, 'proposal_hash': '0' * 64}, expected=403)
        self.assertEqual(mismatch['failure_code'], 'LOCAL_APPROVAL_BINDING_MISMATCH')
        self.call('POST', path + '/decision', valid)
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)
        completed = self.call('POST', path + '/resume', {'confirm_execution': True})
        self.assertEqual(completed['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertEqual(completed['verification']['receipt_hash'], completed['receipt']['receipt_hash'])
        with ThreadPoolExecutor(max_workers=2) as pool:
            repeated = list(pool.map(lambda _: self.service.request(
                'POST', path + '/resume', {'confirm_execution': True}, operator=True), range(2)))
        self.assertTrue(all(code == 200 for code, _ in repeated))
        self.assertEqual(self.service._runtime.executor.mutation_calls, 1)
        self.call('POST', path + '/decision', {**valid, 'decision': 'DENIED'}, expected=409)
        view = self.call('GET', path)
        self.assertEqual(view['run_sandbox_mutations'], 1)
        self.assertEqual(view['evidence_integrity'], 'VERIFIED')
        self.assertEqual(view['runtime']['process_external_network_calls'], 0)
        self.assertFalse(view['runtime']['real_cloud_mutations_enabled'])
        self.service.close()
        self.service = NonZeroCloudOpsService(self.root)
        recovered = self.call('POST', path + '/resume', {'confirm_execution': True})
        self.assertTrue(recovered['reconciled'])
        self.assertEqual(recovered['receipt']['receipt_hash'], completed['receipt']['receipt_hash'])
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)
        trace = self.service.trace(operator=True)
        self.assertTrue(trace['ok'])
        rendered = json.dumps(trace)
        self.assertNotIn(challenge['decision_nonce'], rendered)
        self.assertNotIn(self.service._authorization, rendered)
        self.assertIn(JUDGE_SHA, rendered)
        self.assertIn(run, rendered)
        self.assertIn(completed['receipt']['receipt_hash'], rendered)

    def test_denial_is_terminal_without_mutation(self):
        path = '/api/runs/' + self.start()
        challenge = self.call('POST', path + '/approval-request', {})
        self.call('POST', path + '/decision', decision(challenge, 'DENIED'))
        completed = self.call('POST', path + '/resume', {'confirm_execution': True})
        self.assertEqual(completed['final_state'], 'DENIED_BY_HUMAN')
        self.assertNotIn('receipt', completed)
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)

    def test_unauthorized_and_arbitrary_capabilities_are_rejected(self):
        with self.assertRaisesRegex(NonZeroError, 'OPERATOR_REQUIRED'):
            self.service.request('POST', '/api/runs', TARGET)
        with self.assertRaisesRegex(NonZeroError, 'OPERATOR_REQUIRED'):
            self.service.trace()
        for path in ['https://example.invalid', '/api/session', '/api/runs/../../secret',
                     '/api/shell', '/api/aws/execute', '/api/files']:
            with self.subTest(path=path), self.assertRaisesRegex(NonZeroError, 'ROUTE_NOT_ALLOWED'):
                self.service.request('POST', path, {}, operator=True)
        self.call('POST', '/api/runs', {**TARGET, 'operator': True, 'approved': True}, expected=400)
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)
        self.assertEqual(self.service._runtime.model_provider.calls, 0)

    def test_explicit_execution_confirmation_and_bounded_inputs(self):
        path = '/api/runs/' + self.start()
        self.call('POST', path + '/resume', {}, expected=400)
        self.call('POST', path + '/resume', {'confirm_execution': False}, expected=400)
        for payload in [[], {'x': float('nan')}, {'x': 'x' * 17000}]:
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(NonZeroError):
                self.service.request('POST', '/api/runs', payload, operator=True)
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)

    def test_environment_cannot_enable_live_providers(self):
        self.service.close()
        with patch.dict('os.environ', {'AIOA_RUNTIME_MODE': 'aws', 'AIOA_MODEL_PROVIDER': 'bedrock',
                                       'AIOA_AWS_INTEGRATION_ENABLED': 'true'}):
            self.service = NonZeroCloudOpsService(self.root)
            self.start()
        ready = self.call('GET', '/ready')['runtime']
        self.assertEqual(ready['provider'], 'mock')
        self.assertFalse(ready['aws_calls_allowed'])
        self.assertEqual(ready['process_external_network_calls'], 0)

    def test_state_lease_permissions_and_symlink_boundary(self):
        with self.assertRaisesRegex(NonZeroError, 'STATE_ALREADY_OWNED'):
            NonZeroCloudOpsService(self.root)
        self.assertEqual((self.root / 'operator.credential').stat().st_mode & 0o777, 0o600)
        link = Path(self.temporary.name) / 'link'
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(NonZeroError, 'UNSAFE_STATE_PATH'):
            NonZeroCloudOpsService(link)
        self.start()  # A failed competing lease did not release the original lease.

    def test_core_kill_switch_and_corrupt_provenance_fail_closed(self):
        self.service._guard = lambda: True
        with self.assertRaisesRegex(NonZeroError, 'KILL_SWITCH'):
            self.service.request('POST', '/api/runs', TARGET, operator=True)
        self.call('GET', '/ready')
        self.service._guard = lambda: False
        self.start()
        original = self.service.provenance.read_all
        entries = original()
        entries[0]['payload_hash'] = '0' * 64
        with patch.object(self.service.provenance, 'read_all', return_value=entries), \
             self.assertRaisesRegex(NonZeroError, 'PROVENANCE_CORRUPT'):
            self.service.request('POST', '/api/runs', TARGET, operator=True)
        self.assertEqual(self.service._runtime.executor.mutation_calls, 0)

    def test_evidence_write_failure_stops_before_module_dispatch(self):
        with patch.object(self.service.provenance, 'append_event', side_effect=OSError), \
             patch.object(self.service._application, 'handle') as dispatch:
            with self.assertRaises(OSError):
                self.service.request('POST', '/api/runs', TARGET, operator=True)
            dispatch.assert_not_called()


@unittest.skipUnless(AVAILABLE, 'Non-Zero optional Python >=3.12 extra is not installed')
class NonZeroWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'AOIA_HOME': self.temporary.name})
        self.env.start()
        self.service = WebRuntimeService(cpl_fixture=True)
        self.server = make_server('127.0.0.1', 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.token = self.request('GET', '/api/session', token=False)[1]['token']

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.service.close()
        self.env.stop()
        self.temporary.cleanup()

    def request(self, method, path, payload=None, *, token=True, intent=True, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=15)
        selected = {'Content-Type': 'application/json'}
        if token:
            selected['X-AIOA-Session-Token'] = self.token
        if intent:
            selected['X-AIOA-Intent'] = 'nonzero-operator-v1'
        selected.update(headers or {})
        connection.request(method, path, None if payload is None else json.dumps(payload), selected)
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_host_origin_session_and_intent_before_initialization(self):
        for changes in [{'token': False}, {'intent': False}, {'headers': {'Origin': 'https://evil.invalid'}},
                        {'headers': {'Host': 'evil.invalid'}}, {'headers': {'Sec-Fetch-Site': 'cross-site'}}]:
            self.assertEqual(self.request('POST', '/api/nonzero/runs', TARGET, **changes)[0], 403)
        self.assertEqual(self.request('GET', '/api/nonzero/status', token=False)[0], 403)
        self.assertIsNone(self.service.runtime._nonzero_service)
        self.assertTrue(self.request('GET', '/api/nonzero/status')[1]['registered'])
        self.assertIsNone(self.service.runtime._nonzero_service)

    def test_cli_and_api_share_runtime_and_complete_approved_flow(self):
        runtime = self.service.runtime
        result = runtime.command_registry.execute('/nonzero start-json ' + json.dumps(TARGET), runtime)
        self.assertEqual(result.exit_code, 0, result.message)
        run = json.loads(result.message)['result']['run_id']
        path = '/api/nonzero/runs/' + run
        self.assertEqual(self.request('GET', path)[0], 200)
        challenge = self.request('POST', path + '/approval-request', {})[1]['result']
        self.assertEqual(self.request('POST', path + '/decision', decision(challenge))[0], 200)
        result = self.request('POST', path + '/resume', {'confirm_execution': True})
        self.assertEqual(result[0], 200, result)
        self.assertEqual(result[1]['result']['final_state'], 'SUCCESS_WITH_EVIDENCE')
        self.assertIs(runtime.nonzero_cloudops, runtime._nonzero_service)
        self.assertTrue(self.request('GET', '/api/nonzero/trace')[1]['ok'])
        self.assertEqual(runtime._owned_cpl_fixture.requests, [])

    def test_chat_and_unknown_fields_cannot_assert_operator_authority(self):
        for mode in ['plain', 'cpl']:
            response = self.request('POST', '/api/chat', {'prompt': '/nonzero ready', 'mode': mode})
            self.assertEqual(response[0], 400)
            self.assertEqual(response[1]['error'], 'NONZERO_REQUIRES_OPERATOR_ENDPOINTS')
        self.assertIsNone(self.service.runtime._nonzero_service)
        self.assertEqual(self.request('POST', '/api/nonzero/runs', {**TARGET, 'operator': True})[0], 400)
        self.assertEqual(self.request('GET', '/api/nonzero/ready?token=ignored')[0], 400)

    def test_core_safeguard_reaches_module_and_normal_core_status_remains(self):
        runtime = self.service.runtime
        runtime.safeguards = replace(runtime.safeguards, kill_switch=True)
        self.assertEqual(self.request('POST', '/api/nonzero/runs', TARGET)[0], 403)
        status, payload = self.request('GET', '/api/status')
        self.assertEqual(status, 200)
        self.assertIn('critical_loop', payload)
        self.assertIn('evidence_review', payload)
        self.assertIn('nonzero_cloudops', payload)
        self.assertEqual(self.request('GET', '/api/nonzero/ready')[0], 200)


if __name__ == '__main__':
    unittest.main()
