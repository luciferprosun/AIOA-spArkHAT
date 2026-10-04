"""Executable PRE-04 evidence and independent unsafe-state sensitivity checks."""
from dataclasses import FrozenInstanceError, asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from lab.archaioa.effect_model import (
    ACTIONS, State, TransitionRejected, ModelViolation, check_model,
    format_trace, invariant_violations, transition,
)

INVARIANTS = (
    'NoEffectWithoutWarrant', 'NoWarrantReuse', 'NoAuthorityAmplification',
    'NoStaleEpochCommit', 'NoUnknownToSuccessWithoutEvidence',
    'NoCompletedTaskWithOpenLiability',
)
ROOT = Path(__file__).resolve().parents[2]


def run_path(*actions):
    s = State()
    for action in actions:
        s = transition(s, action)
    return s


def ready():
    return run_path('verify', 'require_approval', 'grant_warrant', 'record_intent')


def dispatched():
    return transition(ready(), 'dispatch')


class EffectModelTests(unittest.TestCase):
    def rejects(self, s, *actions):
        before = s.serialize()
        for action in actions:
            with self.subTest(action=action), self.assertRaises(TransitionRejected):
                transition(s, action)
            self.assertEqual(s.serialize(), before)

    def test_exhaustive_fixed_point_and_exact_counts(self):
        result = check_model()
        self.assertEqual(result.violations, ())
        self.assertEqual((result.reachable_states, result.transitions,
                          result.rejected_attempts, result.max_depth), (166, 336, 2818, 13))
        self.assertEqual(result.transitions + result.rejected_attempts,
                         result.reachable_states * len(ACTIONS))
        self.assertEqual(result.digest, '6b32111cdab98d7d55d1b32a8b158a6c942084ab53fefa82043e80a77d2261c4')
        self.assertEqual(check_model(depth_bound=13), result)
        with self.assertRaisesRegex(ModelViolation, 'DepthBoundNotExhaustive'):
            check_model(depth_bound=12)

    def test_each_property_rejects_independently_corrupted_state(self):
        d = dispatched()
        success = transition(transition(d, 'ack_applied'), 'commit_applied')
        fixtures = (
            replace(d, authorized_consumption=False),
            replace(d, effect_count=2),
            replace(d, dispatch_attenuation_valid=False),
            replace(success, commit_epoch_current=False),
            replace(success, unknown_seen=True, reconciliation_evidence=False),
            replace(transition(success, 'complete'), open_liability_count=1),
        )
        for name, unsafe in zip(INVARIANTS, fixtures):
            with self.subTest(property=name):
                self.assertEqual(invariant_violations(unsafe), (name,))
                with self.assertRaisesRegex(ModelViolation, name):
                    check_model(initial=unsafe)
                self.rejects(unsafe, *ACTIONS)

    def test_property_additional_branches(self):
        d = dispatched()
        for field in ('warrant_present', 'warrant_consumed'):
            self.assertIn(INVARIANTS[0], invariant_violations(replace(d, **{field: False})))
        self.assertIn(INVARIANTS[3], invariant_violations(replace(d, dispatch_epoch_current=False)))
        unsafe = replace(d, phase='COMPLETED', completed=True, outcome='UNKNOWN',
                         unknown_seen=True, reconciliation_evidence=True)
        self.assertIn(INVARIANTS[4], invariant_violations(unsafe))
        self.assertIn(INVARIANTS[5], invariant_violations(unsafe))

    def test_duplicate_dispatch_all_post_consumption_phases(self):
        d = dispatched()
        ack = transition(d, 'ack_applied')
        executed = transition(ack, 'commit_applied')
        unknown = transition(d, 'lose_ack')
        recon = transition(unknown, 'begin_reconciliation')
        for state in (d, ack, executed, transition(executed, 'complete'), unknown, recon):
            self.rejects(state, 'dispatch', 'grant_warrant', 'record_intent')
            self.assertEqual(state.effect_count, 1)
        # Force the phase back to the dispatch entry without changing consumed history.
        self.rejects(replace(d, phase='INTENT_RECORDED'), 'dispatch')

    def test_unknown_cannot_auto_retry_or_succeed(self):
        unknown = transition(dispatched(), 'lose_ack')
        self.assertEqual(unknown.open_liability_count, 1)
        self.rejects(unknown, 'dispatch', 'complete', 'commit_applied',
                     'resolve_applied', 'ack_applied', 'retry')
        recon = transition(unknown, 'begin_reconciliation')
        self.rejects(recon, 'dispatch', 'resolve_applied', 'resolve_not_applied', 'complete')

    def test_dispatch_guards(self):
        for field in ('warrant_current', 'authority_attenuation_valid', 'lease_epoch_current',
                      'warrant_present'):
            self.rejects(replace(ready(), **{field: False}), 'dispatch')
        self.rejects(State(), 'dispatch')

    def test_stale_epoch_blocks_commit_and_resolution(self):
        d = dispatched()
        for ack_action, commit_action in (('ack_applied', 'commit_applied'),
                                         ('ack_not_applied', 'commit_not_applied')):
            ack = transition(d, ack_action)
            stale = transition(ack, 'invalidate_epoch')
            self.rejects(stale, commit_action)
        recon = transition(transition(d, 'lose_ack'), 'begin_reconciliation')
        evidenced = transition(recon, 'record_evidence')
        self.rejects(transition(evidenced, 'invalidate_epoch'), 'resolve_applied', 'resolve_not_applied')

    def test_completion_with_open_liability_fails(self):
        executed = transition(transition(dispatched(), 'ack_applied'), 'commit_applied')
        self.rejects(replace(executed, open_liability_count=1), 'complete')

    def test_reconciliation_only_resolves_existing_effect(self):
        recon = transition(transition(dispatched(), 'lose_ack'), 'begin_reconciliation')
        evidenced = transition(recon, 'record_evidence')
        for action, outcome in (('resolve_applied', 'APPLIED'), ('resolve_not_applied', 'NOT_APPLIED')):
            resolved = transition(evidenced, action)
            self.assertEqual(resolved.effect_count, recon.effect_count)
            self.assertTrue(resolved.warrant_consumed)
            self.assertEqual(resolved.outcome, outcome)
            self.assertEqual(resolved.open_liability_count, 0)
            self.assertTrue(transition(resolved, 'complete').completed)
            self.rejects(resolved, 'dispatch')

    def test_authorization_witnesses_survive_later_invalidation(self):
        s = dispatched()
        for action in ('invalidate_warrant', 'invalidate_attenuation', 'invalidate_epoch'):
            s = transition(s, action)
        self.assertEqual(invariant_violations(s), ())
        self.assertTrue(s.authorized_consumption)
        self.rejects(s, 'dispatch')

    def test_immutable_strict_domain_and_trace(self):
        with self.assertRaises(FrozenInstanceError):
            State().phase = 'COMPLETED'
        for unsafe in (replace(State(), effect_count=3), replace(State(), completed=1),
                       replace(State(), phase='INVALID'), replace(State(), outcome='INVALID'),
                       replace(State(), effect_count=True), replace(State(), open_liability_count=2)):
            self.rejects(unsafe, 'verify')
        trace = format_trace((('Init', State()), ('dispatch', dispatched())), ('example',))
        self.assertTrue(trace.startswith('Invariant failure: example\n0: Init {'))
        self.assertIn('\n1: dispatch {', trace)
        with self.assertRaisesRegex(ModelViolation, '0: Init'):
            check_model(initial=replace(dispatched(), effect_count=2))

    def test_deterministic_counts_and_digest_across_hash_seeds(self):
        expected = asdict(check_model())
        expected['violations'] = []
        code = '''
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in (
            'runtime', 'deploy', 'web', 'requests', 'socket', 'urllib',
            'http', 'boto3', 'botocore', 'sqlite3', 'psycopg', 'openai',
        ):
            raise AssertionError('forbidden import: ' + fullname)
sys.meta_path.insert(0, Block())
import runpy
runpy.run_module('lab.archaioa.effect_model', run_name='__main__')
'''
        for seed in ('0', '1', '91'):
            env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONPATH=str(ROOT))
            process = subprocess.run([sys.executable, '-c', code],
                                     cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertEqual(json.loads(process.stdout), expected)

    def test_tla_structural_artifact_only(self):
        spec = (ROOT / 'lab/archaioa/formal/ArchAIOAEffect.tla').read_text()
        self.assertIn('UNCHECKED_BY_TLC', spec)
        for name in INVARIANTS + ('Init', 'Next', 'Spec'):
            self.assertRegex(spec, r'(?m)^' + name + r'\s*==')
        self.assertIn('EXTENDS Naturals', spec)
        self.assertTrue(spec.rstrip().endswith('============================================================================='))
