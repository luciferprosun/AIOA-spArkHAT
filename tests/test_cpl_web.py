"""Real loopback HTTP requests through the same AgentRuntime and provider adapter."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from critical_loop.fixture import FIXTURE_PROMPT, FIXTURE_EVIDENCE
from webapp import WebRuntimeService, make_server


class CPLWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {'AOIA_HOME': self.temp.name})
        self.env.start()
        self.service = WebRuntimeService(cpl_fixture=True)
        self.fixture = self.service.runtime._owned_cpl_fixture
        self.server = make_server('127.0.0.1', 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.token = self.request('GET', '/api/session', token=False)[1]['token']

    def tearDown(self):
        self.service.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.env.stop()
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, token=True, headers=None, raw=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=3)
        selected = {'Content-Type': 'application/json'}
        if token:
            selected['X-AIOA-Session-Token'] = self.token
        selected.update(headers or {})
        body = raw if raw is not None else json.dumps(payload) if payload is not None else None
        connection.request(method, path, body=body, headers=selected)
        response = connection.getresponse()
        status, response_headers = response.status, dict(response.getheaders())
        data = response.read()
        connection.close()
        return status, json.loads(data), response_headers

    def plan(self):
        status, plan, _ = self.request('POST', '/api/cpl/plan',
            {'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE})
        self.assertEqual(status, 201, plan)
        return plan

    @staticmethod
    def approval(plan):
        return {key: plan[key] for key in ['run_id', 'plan_hash', 'nonce']}

    def test_T10_cli_and_real_web_share_exact_service_and_full_result(self):
        runtime = self.service.runtime
        cli = runtime.command_registry.execute('/cpl fixture', runtime)
        self.assertEqual(cli.exit_code, 0)
        cli_view = json.loads(cli.message)
        status, view, _ = self.request('GET', '/api/cpl/runs/' + cli_view['run_id'])
        self.assertEqual(status, 200)
        self.assertEqual(view['execution_status'], 'COMPLETED')
        self.assertEqual(len(view['reviews']), 3)
        self.assertTrue(view['draft'] and view['final_answer'])
        self.assertIs(self.service.runtime.critical_loop.manager, runtime.provider_manager)
        self.assertEqual(view['snapshot_hash'], cli_view['snapshot_hash'])
        self.fixture.requests.clear()
        plan = self.plan()
        self.assertEqual(self.request('POST', '/api/cpl/start', self.approval(plan))[0], 202)
        final = runtime.critical_loop.wait(plan['run_id'], 5)
        self.assertEqual(final['execution_status'], 'COMPLETED')
        self.assertEqual(final['approval']['source'], 'LOCAL_HTTP_NONCE')
        self.assertEqual(len(self.fixture.requests), 5)
        self.assertEqual(self.request('POST', '/api/cpl/verify', {'run_id': plan['run_id'],
            'manifest': final['evidence_chain']})[1]['ok'], True)

    def test_T11_host_origin_token_and_no_cors(self):
        payload = {'prompt': FIXTURE_PROMPT}
        for headers, token in [({'Host': 'evil.invalid'}, True), ({'Origin': 'https://evil.invalid'}, True),
                               ({'Origin': 'null'}, True), ({'Sec-Fetch-Site': 'cross-site'}, True), ({}, False)]:
            with self.subTest(headers=headers, token=token):
                status, _, response_headers = self.request('POST', '/api/cpl/plan', payload, headers=headers, token=token)
                self.assertEqual(status, 403)
                self.assertNotIn('Access-Control-Allow-Origin', response_headers)
        self.assertEqual(self.fixture.requests, [])
        self.assertEqual(self.request('POST', '/api/cpl/plan', payload,
            headers={'Origin': f'http://127.0.0.1:{self.port}'})[0], 201)

    def test_T11_status_and_cancel_responsive_during_real_http(self):
        self.fixture.faults = {1: 'delay'}
        plan = self.plan()
        self.request('POST', '/api/cpl/start', self.approval(plan))
        self.assertTrue(self.fixture.entered.wait(2))
        started = time.monotonic()
        status, view, _ = self.request('GET', '/api/cpl/runs/' + plan['run_id'])
        self.assertEqual((status, view['execution_status']), (200, 'DRAFTING'))
        status, view, _ = self.request('POST', '/api/cpl/cancel', {'run_id': plan['run_id']})
        self.assertEqual((status, view['execution_status']), (200, 'CANCELLED'))
        self.assertLess(time.monotonic() - started, .7)
        self.fixture.release.set()
        result = self.service.runtime.critical_loop.wait(plan['run_id'], 3)
        self.assertIsNone(result['final_answer'])
        self.assertEqual(len(self.fixture.requests), 1)

    def test_T08_http_double_start_and_fake_approval_rejected(self):
        plan = self.plan()
        approval = self.approval(plan)
        self.assertEqual(self.request('POST', '/api/cpl/start', {**approval, 'approved': True})[0], 400)
        self.assertEqual(self.request('POST', '/api/cpl/start', {**approval, 'nonce': 'wrong'})[0], 400)
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.request('POST', '/api/cpl/start', approval)[0], range(2)))
        self.assertEqual(sorted(statuses), [202, 409])
        self.service.runtime.critical_loop.wait(plan['run_id'], 5)
        self.assertEqual(len(self.fixture.requests), 5)

    def test_T11_chat_cannot_bypass_cpl_approval(self):
        for payload in [{'prompt': '/cpl fixture'}, {'prompt': FIXTURE_PROMPT, 'mode': 'cpl'}]:
            self.assertEqual(self.request('POST', '/api/chat', payload)[0], 400)
        self.assertEqual(self.fixture.requests, [])

    def test_T11_body_bounds_duplicate_fields_nonfinite_and_framing(self):
        for raw in [b'{"prompt":"a","prompt":"b"}', b'{"prompt":NaN}', b'{', b'[]']:
            self.assertEqual(self.request('POST', '/api/cpl/plan', raw=raw)[0], 400)
        self.assertEqual(self.request('POST', '/api/cpl/plan', raw=b'x' * 24001)[0], 413)
        self.assertEqual(self.request('POST', '/api/cpl/plan', {}, headers={'Transfer-Encoding': 'chunked'})[0], 400)
        self.assertEqual(self.fixture.requests, [])

    def test_T10_error_exposed_without_raw_provider_error(self):
        self.fixture.faults = {2: 'http_error'}
        plan = self.plan()
        self.request('POST', '/api/cpl/start', self.approval(plan))
        self.service.runtime.critical_loop.wait(plan['run_id'], 5)
        _, view, _ = self.request('GET', '/api/cpl/runs/' + plan['run_id'])
        self.assertEqual(view['error'], 'PROVIDER_HTTP_503')
        self.assertEqual(view['execution_status'], 'FAILED')
        self.assertIsNone(view['final_answer'])

    def test_T16_existing_chat_commands_status_and_review_stay_separate(self):
        status, result, _ = self.request('POST', '/api/chat', {'prompt': '/help'})
        self.assertEqual(status, 200)
        self.assertIn('Local commands', str(result))
        self.assertEqual(self.request('GET', '/api/status')[0], 200)
        runtime = self.service.runtime
        cli_plan = runtime.command_registry.execute('/cpl plan-json ' + json.dumps({
            'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE, 'models': ['fixture/chosen'] * 4,
            'run_budget_usd': '0'}), runtime)
        planned = json.loads(cli_plan.message)
        self.assertEqual(planned['plan']['models'], ['fixture/chosen'] * 4)
        self.assertEqual(planned['plan']['evidence'], FIXTURE_EVIDENCE)
        self.assertEqual(planned['execution_status'], 'PLANNED')
        self.assertEqual(self.fixture.requests, [])


if __name__ == '__main__':
    unittest.main()
