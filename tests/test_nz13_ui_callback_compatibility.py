"""Preserve existing callback policy with local fakes, never provider calls."""
import io
import threading
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import main
import webapp

from runtime.memory_patch.errors import CommitOutcomeUnknown


class ForeignFixtureError(Exception):
    pass


class UICompatibilityTests(unittest.TestCase):
    def runtime(self, outputs):
        runtime = main.AgentRuntime.__new__(main.AgentRuntime)
        runtime._agent_bindings = None
        runtime._inspection_only = False
        runtime.debug_raw = False
        runtime.safeguards = SimpleNamespace(disable_model=False)
        calls = []

        def generate(_prompt):
            calls.append(1)
            value = outputs[len(calls) - 1]
            if isinstance(value, Exception):
                raise value
            return value

        runtime.provider_manager = SimpleNamespace(generate=generate)
        return runtime, calls

    def test_daily_quota_keeps_the_existing_single_attempt_policy(self):
        runtime, calls = self.runtime([ForeignFixtureError('PerDay fixture quota')])
        with patch.object(main.time, 'sleep') as delay, redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'PerDay fixture quota'):
            runtime.ask_model('inert fixture')
        self.assertEqual(1, len(calls))
        delay.assert_not_called()

    def test_transient_callback_errors_keep_existing_retry_count_and_delays(self):
        runtime, calls = self.runtime([
            ForeignFixtureError('first fixture error'),
            ForeignFixtureError('second fixture error'), 'fixture response',
        ])
        with patch.object(main.time, 'sleep') as delay, redirect_stdout(io.StringIO()):
            self.assertEqual('fixture response', runtime.ask_model('inert fixture'))
        self.assertEqual(3, len(calls))
        self.assertEqual([1.0, 2.0], [call.args[0] for call in delay.call_args_list])

    def test_exhausted_callback_error_retains_the_legacy_final_error_detail(self):
        runtime, calls = self.runtime([ForeignFixtureError('fixture failure')] * 3)
        with patch.object(main.time, 'sleep') as delay, redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'after retries: fixture failure'):
            runtime.ask_model('inert fixture')
        self.assertEqual(3, len(calls))
        self.assertEqual(2, delay.call_count)

    def test_memory_patch_denial_keeps_the_original_typed_public_response(self):
        runtime = main.AgentRuntime.__new__(main.AgentRuntime)
        runtime._memory_patch_init_lock = threading.RLock()
        runtime._inspection_only = True
        status, response = runtime.memory_patch_operator_request('apply', {})
        self.assertEqual(403, status)
        self.assertIn('ADMISSION_DENIED', str(response))

    def handler(self, service):
        handler = webapp.AOIAWebHandler.__new__(webapp.AOIAWebHandler)
        handler.headers = {}
        handler._service = lambda: service
        responses = []
        handler._write_json = lambda status, value: responses.append((status, value))
        return handler, responses

    def test_meta_domain_error_code_is_not_lost_in_a_generic_callback_wrapper(self):
        class MetaFixtureDenial(ForeignFixtureError):
            code = 'META_OWNER_GO_REQUIRED'

        def deny(*_, **__):
            raise MetaFixtureDenial('private fixture detail')

        handler, responses = self.handler(SimpleNamespace(meta_request=deny))
        handler._handle_meta('GET', urlparse('/api/meta/status'), None)
        self.assertEqual([(403, {'ok': False, 'error': 'META_OWNER_GO_REQUIRED'})], responses)

    def test_unknown_commit_ack_stays_readback_required_without_retry(self):
        calls = []

        def uncertain(*_, **__):
            calls.append(1)
            raise CommitOutcomeUnknown()

        handler, responses = self.handler(SimpleNamespace(coding_request=uncertain))
        handler._handle_agent('GET', urlparse('/api/agent/coding/runtime'), None)
        self.assertEqual(1, len(calls))
        self.assertEqual([(503, {'ok': False,
            'error': 'AGENT_ACK_UNKNOWN_READBACK_REQUIRED', 'automatic_retry': False})], responses)

    def test_existing_public_module_attributes_are_the_same_runtime_objects(self):
        self.assertIs(main.PROMPT_FILE, webapp.PROMPT_FILE)
        self.assertIs(main.ProviderManager, webapp.ProviderManager)
        self.assertIs(main.load_prompt_template, webapp.load_prompt_template)

    def test_runtime_composition_failure_closes_once_and_reraises_original_foreign_object(self):
        from pathlib import Path

        from runtime.core_admission import OwnerScope
        from runtime.failure_boundary import RepairBoundaryError
        from runtime.mission.contracts import MissionContext
        from runtime.mission.lite_contracts import LiteProfile
        from runtime.mission.lite_runtime import LiteBindings

        scope = OwnerScope('fixture-tenant', 'fixture-owner', 'fixture-space', 'fixture-slot')
        context = MissionContext(scope, frozenset({'fixture'}), 'CONTRACT_TEST')
        profile = LiteProfile(scope, 'fixture-watch', 'fixture', enabled=True)
        bindings = LiteBindings(Path('/unused-callback-fixture'), None, None)
        closed = []
        runtime = SimpleNamespace(_lite_memory=None, _lite_cpl=None,
                                  close=lambda: closed.append(1))
        error = ForeignFixtureError('FIXTURE_COMPOSITION_FAILURE')
        with patch.object(main, 'AgentRuntime', return_value=runtime), \
                patch('runtime.mission.lite_runtime.LiteScheduler', side_effect=error), \
                self.assertRaises((ForeignFixtureError, RepairBoundaryError)) as failed:
            main.create_runtime(lite_profile=profile, mission_context=context,
                                lite_bindings=bindings)
        self.assertIs(error, failed.exception)
        self.assertEqual([1], closed)
