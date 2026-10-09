"""Existing product composition, credential-free only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.personal_ai_demo_launcher import DemoComposition,PREFERENCE
from runtime.providers.nebius_routing import NebiusProviderPort

class JudgeModeTests(unittest.TestCase):
    def demo(self,mode='FIXTURE'):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        demo=DemoComposition(Path(t.name)/'demo',mode=mode);self.addCleanup(demo.close);return demo
    def test_optional_live_candidate_is_offline_only(self):
        from test_nebius_routing import catalog_receipt, quote
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        policy={'catalog_receipt':catalog_receipt(), 'cost_quote':quote(input_rate='0.06',output_rate='0.24')}
        with patch('runtime.providers.nebius_routing._environment_key',side_effect=AssertionError('No credentials')):
            try:d=DemoComposition(Path(t.name)/'demo',mode='LIVE',live_provider_policy=policy)
            except TypeError:self.fail('Existing native LIVE provider offline policy port not composed')
            self.addCleanup(d.close)
            self.assertIsInstance(d.live_candidate,NebiusProviderPort)
            from runtime.providers.nvidia import ProviderRequest
            from runtime.service_guard.contracts import OUTPUT_SCHEMA
            request=ProviderRequest('judge-offline','judge-trace','nebius',d.live_candidate.model_id,'{}','judge-reservation',128,20,OUTPUT_SCHEMA)
            self.assertLessEqual(d.offline_live_admission(request)['money_nano_usd'],1000000)
            with self.assertRaisesRegex(ValueError,'BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION'):d.prepare()
            self.assertEqual(d.fixture_calls,0)

    def test_judge_badges_use_explicit_provider_target_vocabulary(self):
        d=self.demo();r=d.readiness()
        self.assertEqual(r.get('provider_kind_badge'),'FIXTURE_PROVIDER')
        self.assertEqual(r.get('target_kind_badge'),'FIXTURE_TARGET')
    def test_health_badges_and_caps(self):
        d=self.demo();self.assertTrue(hasattr(d,'readiness'),'Bounded judge readiness missing')
        r=d.readiness();self.assertEqual(r['provider_badge'],'FIXTURE');self.assertEqual(r['target_badge'],'FIXTURE_ONLY');self.assertFalse(r['live_validated']);self.assertEqual(r['authority'],'NONE');self.assertEqual(r['caps']['max_input_bytes'],4096);self.assertEqual(r['caps']['usd_ceiling'],'0.001');self.assertEqual(d.fixture_calls,0)
    def test_live_no_key_does_not_access_supplier_or_fallback(self):
        with patch('runtime.providers.nebius_routing._environment_key',side_effect=AssertionError('Credential supplier forbidden')):
            d=self.demo('LIVE');self.assertTrue(hasattr(d,'readiness'),'Missing no-key readiness');r=d.readiness();self.assertEqual(r['state'],'BLOCKED_PROVIDER');self.assertEqual(r['provider_state'],'NOT_LIVE');self.assertEqual(r['provider_badge'],'LIVE_NEBIUS_TOKEN_FACTORY');self.assertFalse(r['live_validated'])
            with self.assertRaisesRegex(ValueError,'BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION'):d.prepare()
            self.assertEqual(d.fixture_calls,0);self.assertEqual(d.target.read()['effect_count'],0)
    def test_existing_provider_uses_same_core_governor(self):
        d=self.demo();port=d.runtime._lite_scheduler.bindings.provider
        self.assertIsInstance(port,NebiusProviderPort);self.assertIsNotNone(port._governor_binding,'Governor binding missing');self.assertIs(port._governor_binding.governor.core,d.memory.core);self.assertIs(d.guard._governor_binding.governor.core,d.memory.core)
    def test_no_arbitrary_judge_prompt_or_private_projection(self):
        d=self.demo();self.assertTrue(hasattr(d,'validate_judge_request'),'Judge scenario admission missing')
        with self.assertRaisesRegex(ValueError,'JUDGE_SCENARIO_ONLY'):d.web.personal_ai_prepare({'operation_id':d.operation_id,'target_id':d.target_id,'memory_query':'arbitrary terminal command'})
        self.assertNotIn(PREFERENCE,json.dumps(d.readiness()));self.assertEqual(d.fixture_calls,0)
    def test_capsule_metadata_only_and_bound(self):
        d=self.demo();self.assertTrue(hasattr(d,'context_capsule'),'Existing capsule projection missing');c=d.context_capsule();self.assertEqual(c.authority,'NONE');self.assertEqual(c.purpose,'ADVISORY_CONTEXT_ONLY');self.assertNotIn(PREFERENCE,json.dumps(c.as_dict()));self.assertEqual(c.capsule_hash,d.context_capsule().capsule_hash)
    def test_fixture_incomplete_completion_fails_closed(self):
        d=self.demo();d.fixture_finish_reason='length'
        with self.assertRaises(ValueError):d.prepare()
        self.assertEqual(d.target.read()['effect_count'],0);self.assertEqual(d.fixture_calls,1)
