"""Synthetic paired misses, never a claim of model independence."""
import importlib.util
import unittest
from runtime.memory_patch.learning.contracts import CoreVerifierBinding, EvidenceLiteralVerifier, VerificationVerdict

class CanaryPresenceTests(unittest.TestCase):
    def test_seeded_pair_miss_canary_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('nv08_canary'))

class CanaryTests(unittest.TestCase):
    def binding(self,name,verifier):
        return CoreVerifierBinding(name,'fixture-method','fixture-family',verifier)

    def test_seeded_result_is_exact_and_local_only(self):
        from nv08_canary import run_canary
        pair=(self.binding('a',EvidenceLiteralVerifier()),self.binding('b',EvidenceLiteralVerifier()))
        first=run_canary(pair,seed=73,cases=64)
        self.assertEqual(first,run_canary(pair,seed=73,cases=64))
        self.assertEqual('SYNTHETIC_FIXTURE',first['mode']);self.assertEqual('NONE',first['authority'])
        self.assertFalse(first['independence_proven']);self.assertEqual(0,first['provider_calls'])
        self.assertEqual(64,first['cases']);self.assertGreater(first['fault_pairs'],0)
        self.assertEqual(0,first['joint_misses'])

    def test_identical_soft_verifiers_show_joint_misses_and_positive_covariance(self):
        from nv08_canary import run_canary
        class Soft:
            def verify(self,request):
                return VerificationVerdict(request.digest,request.claim.startswith('Fixture fact'))
        shared=Soft();pair=(self.binding('a',shared),self.binding('b',shared))
        result=run_canary(pair,seed=73,cases=96)
        self.assertGreater(result['joint_misses'],0);self.assertGreater(result['covariance'],0)
        self.assertTrue(result['shared_instance']);self.assertTrue(result['shared_method'])
        self.assertFalse(result['independence_proven'])

    def test_no_samples_cannot_claim_zero_risk_or_independence(self):
        from nv08_canary import run_canary
        pair=(self.binding('a',EvidenceLiteralVerifier()),self.binding('b',EvidenceLiteralVerifier()))
        value=run_canary(pair,seed=1,cases=0)
        self.assertEqual('UNKNOWN_NO_COMPLETE_FAULT_PAIRS',value['statistics_status'])
        self.assertIsNone(value['covariance']);self.assertIsNone(value['joint_miss_rate'])

    def test_zero_variance_is_not_independence(self):
        from nv08_canary import run_canary
        class Always:
            def verify(self,request):return VerificationVerdict(request.digest,True)
        result=run_canary((self.binding('a',Always()),self.binding('b',Always())),seed=3,cases=64)
        self.assertEqual(1.0,result['joint_miss_rate']);self.assertEqual(0.0,result['covariance'])
        self.assertIsNone(result['correlation']);self.assertFalse(result['independence_proven'])

    def test_crashes_are_not_counted_as_successful_detections(self):
        from nv08_canary import run_canary
        class Crash:
            def verify(self,request):raise RuntimeError('fixture failure')
        result=run_canary((self.binding('a',Crash()),self.binding('b',EvidenceLiteralVerifier())),seed=5,cases=32)
        self.assertEqual(32,result['incomplete_cases']);self.assertEqual(0,result['fault_pairs'])
        self.assertEqual('UNKNOWN_NO_COMPLETE_FAULT_PAIRS',result['statistics_status'])

    def test_bounds_and_forged_results_fail_closed(self):
        from nv08_canary import run_canary
        pair=(self.binding('a',EvidenceLiteralVerifier()),self.binding('b',EvidenceLiteralVerifier()))
        for n in (-1,257,True):
            with self.assertRaises(ValueError):run_canary(pair,seed=1,cases=n)
        class Forged:
            def verify(self,request):return VerificationVerdict('0'*64,True)
        result=run_canary((self.binding('a',Forged()),pair[1]),seed=1,cases=16)
        self.assertEqual(16,result['incomplete_cases'])
