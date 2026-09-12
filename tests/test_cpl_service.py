from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from critical_loop.fixture import LocalCPLFixture, FIXTURE_PROMPT, FIXTURE_EVIDENCE
from critical_loop.policy import CostPolicy, INPUT_BOUND_POLICY
from critical_loop.review import SUPPORTED_ROLES, ReviewSnapshot, ReviewValidationError
from critical_loop.service import CriticalPromptLoopService
from providers import ProviderManager
from providers.exact import CancellationToken, ExactCallError, ExactRequest
from providers.messages import ChatMessage


class CPLServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.env = patch.dict('os.environ', {'AOIA_HOME': str(self.root / 'state')})
        self.env.start()
        self.fixture = LocalCPLFixture()
        self.manager = ProviderManager(self.root / 'runtime', fixture_base_url=self.fixture.base_url)
        self.service = CriticalPromptLoopService(self.manager, self.root / 'trace')

    def tearDown(self):
        self.service.close()
        self.fixture.close()
        self.env.stop()
        self.temporary.cleanup()

    def plan(self, **changes):
        return self.service.plan({'prompt': FIXTURE_PROMPT, 'evidence': FIXTURE_EVIDENCE, **changes})

    def execute(self, **changes):
        plan = self.plan(**changes)
        self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        return self.service.wait(plan['run_id'], 5)

    def test_T01_exact_five_original_model_and_same_snapshot(self):
        result = self.execute()
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual(result['generation_requests'], 5)
        self.assertEqual(len(self.fixture.requests), 5)
        self.assertIn('three', result['final_answer'])
        material = [json.loads(r['messages'][-1]['content']) for r in self.fixture.requests]
        self.assertEqual([m['observer_role'] for m in material[1:4]], list(SUPPORTED_ROLES))
        self.assertEqual({m['snapshot']['snapshot_hash'] for m in material[1:4]}, {result['snapshot_hash']})
        self.assertEqual(material[4]['snapshot_hash'], result['snapshot_hash'])
        self.assertEqual(self.fixture.requests[0]['model'], self.fixture.requests[-1]['model'])
        self.assertEqual([r['max_tokens'] for r in self.fixture.requests], [1024, 512, 512, 512, 1024])

    def test_T02_duplicate_and_incomplete_roles_before_transport(self):
        for roles in [[], list(SUPPORTED_ROLES[:2]), [SUPPORTED_ROLES[0]] * 3, list(reversed(SUPPORTED_ROLES))]:
            with self.subTest(roles=roles), self.assertRaises(ExactCallError):
                self.plan(roles=roles)
        self.assertEqual(self.fixture.requests, [])

    def test_T02_same_model_distinct_roles_explicitly_allowed(self):
        result = self.execute(models=['fixture/one'] * 4)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertTrue(result['plan']['shared_model_for_roles'])
        self.assertEqual({r['model'] for r in self.fixture.requests}, {'fixture/one'})

    def test_T03_informed_reviews_and_negative_findings_are_not_transport_failure(self):
        result = self.execute()
        materials = [json.loads(r['messages'][-1]['content']) for r in self.fixture.requests[1:4]]
        self.assertEqual([len(m['prior_observer_metadata']) for m in materials], [0, 1, 2])
        self.assertIn('superseded', materials[1]['prior_observer_metadata'][0]['summary'])
        self.assertTrue(result['conflicts'])
        self.assertEqual(result['reviews'][0]['findings'][0]['severity'], 'critical')
        self.assertEqual(result['execution_status'], 'COMPLETED')

    def test_T04_transport_failure_at_every_stage_is_fail_fast(self):
        for stage in range(1, 6):
            with self.subTest(stage=stage):
                self.fixture.requests.clear()
                self.fixture.faults = {stage: 'http_error'}
                result = self.execute()
                self.assertEqual(result['execution_status'], 'FAILED')
                self.assertEqual(len(self.fixture.requests), stage)
                self.assertIsNone(result['final_answer'])
                self.assertEqual(result['error'], 'PROVIDER_HTTP_503')

    def test_T04_incomplete_critic_never_gets_a_repair_generation(self):
        self.fixture.faults = {2: 'bad_review'}
        result = self.execute()
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertEqual(len(self.fixture.requests), 2)
        self.assertIsNone(result['final_answer'])

    def test_T05_missing_and_wrong_identity_fail_before_further_calls(self):
        for fault in ['missing_model', 'wrong_model']:
            with self.subTest(fault=fault):
                self.fixture.requests.clear()
                self.fixture.faults = {2: fault}
                result = self.execute()
                self.assertEqual(result['execution_status'], 'FAILED')
                self.assertEqual(len(self.fixture.requests), 2)

    def test_T05_router_and_alias_model_rejected_before_transport(self):
        for model in ['free', 'openrouter/free', 'openrouter/auto', 'free/router']:
            with self.subTest(model=model), self.assertRaises(ExactCallError):
                self.plan(models=[model] * 4)
        self.assertEqual(self.fixture.requests, [])

    def test_T05_neighboring_model_change_does_not_mutate_plan(self):
        self.fixture.faults = {1: 'delay'}
        plan = self.plan()
        self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        self.assertTrue(self.fixture.entered.wait(2))
        self.manager.switch_model('gemini/gemini-2.5-flash')
        self.fixture.release.set()
        result = self.service.wait(plan['run_id'], 5)
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual({r['model'] for r in self.fixture.requests}, {'fixture/synthetic'})
        self.assertEqual(self.manager.current_model, 'gemini/gemini-2.5-flash')

    def test_T05_no_generate_or_fallback_used(self):
        with patch.object(self.manager, 'generate', side_effect=AssertionError('ordinary path forbidden')), \
             patch.object(self.manager, 'generate_with_fallback', side_effect=AssertionError('fallback forbidden')):
            self.assertEqual(self.execute()['execution_status'], 'COMPLETED')

    def test_T06_bounds_body_errors_json_and_finish_reason(self):
        for fault in ['huge_success', 'huge_error', 'bad_json', 'output_limit', 'input_limit', 'truncated_completion', 'truncated_http']:
            with self.subTest(fault=fault):
                self.fixture.requests.clear()
                self.fixture.faults = {1: fault}
                result = self.execute()
                self.assertEqual(result['execution_status'], 'FAILED')
                self.assertEqual(len(self.fixture.requests), 1)
                self.assertIsNone(result['final_answer'])

    def test_T06_input_bound_checked_before_transport(self):
        result = self.execute(limits={'input_tokens': 300})
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertEqual(self.fixture.requests, [])

    def test_T06_plan_rejects_infinite_negative_and_oversized_limits(self):
        for limits in [{'draft_tokens': 1025}, {'critic_tokens': 0}, {'input_tokens': -1},
                       {'run_deadline_seconds': float('inf')}, {'request_timeout_seconds': True}]:
            with self.subTest(limits=limits), self.assertRaises(ExactCallError):
                self.plan(limits=limits)

    def test_T06_deadline_and_timeout(self):
        self.fixture.faults = {1: 'delay'}
        started = time.monotonic()
        # Leave time for durable trace fsync before transport; this test asserts
        # HTTP timeout, not that a loaded filesystem starts HTTP within 200 ms.
        result = self.execute(limits={'request_timeout_seconds': .1, 'run_deadline_seconds': 2})
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(self.fixture.requests), 1)

    def test_closure_timeout_in_each_critic_and_final_revision_never_delivers(self):
        for stage in (2, 3, 4, 5):
            with self.subTest(stage=stage):
                self.fixture.requests.clear()
                self.fixture.release.clear()
                self.fixture.faults = {stage: 'delay'}
                result = self.execute(limits={'request_timeout_seconds': .12, 'run_deadline_seconds': 5})
                self.assertEqual(result['execution_status'], 'FAILED')
                self.assertIn(result['error'], {'TRANSPORT_TIMEOUT','DEADLINE_EXCEEDED'})
                self.assertEqual(len(self.fixture.requests), stage)
                self.assertIsNone(result['final_answer'])

    def test_closure_cancel_draft_and_each_critic_is_terminal_without_replay(self):
        for stage in (1, 2, 3, 4):
            with self.subTest(stage=stage):
                self.fixture.requests.clear()
                self.fixture.release.clear()
                self.fixture.faults = {stage:'delay'}
                plan = self.plan()
                self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
                deadline = time.monotonic()+3
                while len(self.fixture.requests) < stage and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(len(self.fixture.requests), stage)
                cancelled = self.service.cancel(plan['run_id'])
                self.assertEqual(cancelled['execution_status'], 'CANCELLED')
                self.fixture.release.set()
                final = self.service.wait(plan['run_id'], 3)
                self.assertEqual(final['execution_status'], 'CANCELLED')
                self.assertIsNone(final['final_answer'])
                self.assertEqual(len(self.fixture.requests), stage)
                with self.assertRaisesRegex(ExactCallError, 'AUTHORIZATION_ALREADY_CONSUMED'):
                    self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
                self.assertTrue(self.service.verify(plan['run_id'])['ok'])

    def test_T06_expired_run_deadline_never_starts_transport(self):
        result = self.execute(limits={'run_deadline_seconds': .000001})
        self.assertEqual(result['execution_status'], 'FAILED')
        self.assertEqual(self.fixture.requests, [])
        self.assertIsNone(result['final_answer'])

    def test_T06_trickling_http_headers_cannot_extend_deadline(self):
        self.fixture.faults = {1: 'slow_headers'}
        request = ExactRequest('openrouter', 'fixture/synthetic', (ChatMessage('user', '{"prompt":"test"}'),),
                               1024, timeout_seconds=.12, transport_scope='TEST')
        started = time.monotonic()
        with self.assertRaises(ExactCallError):
            self.manager.generate_exact(request, CancellationToken(), time.monotonic() + 2)
        self.assertLess(time.monotonic() - started, .5)
        self.assertEqual(len(self.fixture.requests), 1)

    def test_T06_delayed_connection_after_cancel_sends_no_generation(self):
        import http.client
        token = CancellationToken()
        original = http.client.HTTPConnection.connect
        def delayed(connection):
            token.cancel()
            original(connection)
        request = ExactRequest('openrouter', 'fixture/synthetic', (ChatMessage('user', '{"prompt":"test"}'),),
                               1024, transport_scope='TEST')
        with patch.object(http.client.HTTPConnection, 'connect', delayed), self.assertRaises(ExactCallError):
            self.manager.generate_exact(request, token, time.monotonic() + 2)
        self.assertEqual(self.fixture.requests, [])

    def test_T06_live_zero_budget_and_missing_price_are_blocked(self):
        self.manager.fixture_base_url = None
        for label, policy, cap in [
            ('disabled', CostPolicy(), '1'),
            ('zero', CostPolicy(True, '1'), '0'),
            ('missing_price', CostPolicy(True, '1'), '1'),
        ]:
            with self.subTest(label=label):
                service = CriticalPromptLoopService(self.manager, self.root / label, cost_policy=policy)
                with self.assertRaises(ExactCallError):
                    service.plan({'prompt': FIXTURE_PROMPT, 'run_budget_usd': cap})
                service.close()
        self.assertEqual(self.fixture.requests, [])

    def test_T06_conservative_price_and_session_reservation(self):
        self.manager.fixture_base_url = None
        model = self.manager.current_model.removeprefix('openrouter/')
        quote = {model: {'quoted_utc': datetime.now(timezone.utc).isoformat(), 'currency': 'USD',
                        'input_usd_per_million': '1', 'output_usd_per_million': '1',
                        'input_bound_policy': INPUT_BOUND_POLICY}}
        service = CriticalPromptLoopService(self.manager, self.root / 'price',
                    cost_policy=CostPolicy(True, '0.01', json.dumps(quote)))
        with self.assertRaisesRegex(ExactCallError, 'BUDGET_EXCEEDED'):
            service.plan({'prompt': FIXTURE_PROMPT, 'run_budget_usd': '1'})
        service.close()

    def test_T07_cancel_is_responsive_and_late_result_is_discarded(self):
        self.fixture.faults = {1: 'delay'}
        plan = self.plan()
        self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        self.assertTrue(self.fixture.entered.wait(2))
        started = time.monotonic()
        result = self.service.cancel(plan['run_id'])
        self.assertLess(time.monotonic() - started, .4)
        self.assertEqual(result['execution_status'], 'CANCELLED')
        self.fixture.release.set()
        self.service.close()
        result = self.service.get(plan['run_id'])
        self.assertEqual(result['execution_status'], 'CANCELLED')
        self.assertIsNone(result['final_answer'])
        self.assertEqual(len(self.fixture.requests), 1)

    def test_T07_restart_marks_unfinished_run_interrupted_no_replay(self):
        plan = self.plan()
        self.service.close()
        reopened = CriticalPromptLoopService(self.manager, self.root / 'trace')
        self.assertEqual(reopened.get(plan['run_id'])['execution_status'], 'INTERRUPTED')
        with self.assertRaises(ExactCallError):
            reopened.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        self.assertEqual(self.fixture.requests, [])
        reopened.close()

    def test_T08_nonce_hash_and_mutated_plan_rejected(self):
        plan = self.plan()
        for digest, nonce in [('0' * 64, plan['nonce']), (plan['plan_hash'], 'invalid')]:
            with self.subTest(digest=digest), self.assertRaises(ExactCallError):
                self.service.start(plan['run_id'], digest, nonce)
        self.assertEqual(self.fixture.requests, [])

    def test_T08_expiry(self):
        self.service.plan_ttl_seconds = -1
        plan = self.plan()
        with self.assertRaisesRegex(ExactCallError, 'PLAN_EXPIRED'):
            self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
        self.assertEqual(self.fixture.requests, [])

    def test_T08_concurrent_double_start_exactly_one_worker(self):
        plan = self.plan()
        barrier = threading.Barrier(3)
        outcomes = []

        def start():
            barrier.wait()
            try:
                self.service.start(plan['run_id'], plan['plan_hash'], plan['nonce'])
                outcomes.append('started')
            except ExactCallError as error:
                outcomes.append(error.code)

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(2)
        result = self.service.wait(plan['run_id'], 5)
        self.assertCountEqual(outcomes, ['started', 'AUTHORIZATION_ALREADY_CONSUMED'])
        self.assertEqual(result['generation_requests'], 5)
        self.assertEqual(len(self.fixture.requests), 5)

    def test_T09_model_commands_are_data_not_authority(self):
        self.fixture.faults = {1: 'authority_text', 2: 'authority_text', 5: 'authority_text'}
        with patch('subprocess.run', side_effect=AssertionError('CPL must not execute subprocesses')):
            result = self.execute()
        self.assertEqual(result['execution_status'], 'COMPLETED')
        self.assertEqual(result['authority'], 'ADVISORY_ONLY')
        self.assertTrue(result['human_review_required'])
        self.assertIn('onerror', result['final_answer'])

    def test_T13_reopen_completed_and_verify_external_manifest_without_provider(self):
        result = self.execute()
        self.service.close()
        reopened = CriticalPromptLoopService(self.manager, self.root / 'trace')
        report = reopened.get(result['run_id'])
        self.assertEqual(report['final_answer'], result['final_answer'])
        self.assertTrue(reopened.verify(result['run_id'], result['evidence_chain'])['ok'])
        self.assertEqual(len(self.fixture.requests), 5)
        reopened.close()

    def test_T14_known_secrets_redacted_before_hash_and_persistence(self):
        self.fixture.faults = {1: 'secret_text', 5: 'secret_text'}
        result = self.execute()
        self.assertEqual(result['execution_status'], 'COMPLETED')
        files = ''.join(p.read_text() for p in (self.root / 'trace').rglob('*') if p.is_file())
        self.assertNotIn('fixture-key-not-a-real-credential', files)
        self.assertNotIn('sk-EXAMPLESECRET1234567890', files)
        self.assertIn('[REDACTED]', files)
        self.assertTrue(self.service.verify(result['run_id'])['ok'])

    def test_T14_prompt_secrets_rejected_before_network(self):
        with self.assertRaises(ExactCallError):
            self.plan(prompt='my token=sk-EXAMPLESECRET1234567890')
        self.assertEqual(self.fixture.requests, [])

    def test_T15_no_knowledge_promotion_or_training(self):
        before = {str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()}
        result = self.execute()
        after = {str(p.relative_to(self.root)) for p in self.root.rglob('*') if p.is_file()}
        self.assertTrue(all(path.startswith('trace/') for path in after - before))
        self.assertEqual(result['knowledge_promotion'], 'DISABLED')
        self.assertEqual(result['model_training'], 'NONE')

    def test_T12_missing_usage_is_not_zero(self):
        self.fixture.faults = {1: 'missing_usage'}
        result = self.execute()
        self.assertIsNone(result['provider_results'][0]['usage'])
        self.assertEqual(result['provider_results'][0]['reported_model'], 'fixture/synthetic')

    def test_snapshot_integrity_port_retained(self):
        snapshot = ReviewSnapshot.create(session_id='s', original_prompt='p', primary_response='d',
            primary_provider_id='openrouter', primary_model_id='fixture/synthetic',
            knowledge_profile_id=None, evidence_text='source')
        with self.assertRaises(ReviewValidationError):
            replace(snapshot, primary_response='changed').verify_integrity()

    def test_T06_operator_policy_file_is_explicit_bounded_and_zero_rejected(self):
        from critical_loop.policy import load_cost_policy
        path = self.root / 'operator-policy.json'
        for value in [{'live_enabled': False, 'session_budget_usd': '1', 'quotes': {}},
                      {'live_enabled': True, 'session_budget_usd': '0', 'quotes': {}},
                      {'live_enabled': True, 'session_budget_usd': '1', 'quotes': {}, 'approved': True}]:
            path.write_text(json.dumps(value))
            with self.assertRaises(ExactCallError):
                load_cost_policy(path)
        path.write_text(json.dumps({'live_enabled': True, 'session_budget_usd': '1', 'quotes': {}}))
        policy = load_cost_policy(path)
        self.assertTrue(policy.live_enabled)
        self.assertEqual(policy.session_budget_usd, '1')
        self.assertEqual(self.fixture.requests, [])


if __name__ == '__main__':
    unittest.main()
