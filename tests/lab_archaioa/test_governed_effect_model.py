"""Restricted product checker, not native/distributed/cryptographic proof."""
from dataclasses import replace
import importlib.util
import unittest
from lab.archaioa import effect_model as existing

class GovernedModelPresenceTests(unittest.TestCase):
    def test_governed_product_checker_extends_existing_effect_machine(self):
        self.assertIsNotNone(importlib.util.find_spec('lab.archaioa.governed_model'))

class GovernedModelTests(unittest.TestCase):
    def test_exhaustive_reproducible_product_retains_original_seal(self):
        from lab.archaioa.governed_model import check_governed_model
        first=check_governed_model();self.assertEqual((),first.violations)
        self.assertEqual(first,check_governed_model());self.assertGreater(first.reachable_states,166)
        self.assertEqual('6b32111cdab98d7d55d1b32a8b158a6c942084ab53fefa82043e80a77d2261c4',existing.check_model().digest)
    def ready(self):
        from lab.archaioa.governed_model import GovernedState,step
        value=GovernedState()
        for action in ('verify','require_approval','grant_warrant','record_intent','reserve'):value=step(value,action)
        return value
    def test_budget_kill_and_stale_epoch_reject_dispatch(self):
        from lab.archaioa.governed_model import step
        ready=self.ready()
        for value in (replace(ready,money_nano=0,risk_units=0,reservation='RELEASED'),step(ready,'kill'),step(ready,'invalidate_epoch')):
            with self.assertRaises(existing.TransitionRejected):step(value,'dispatch')
    def test_unknown_holds_both_bounds_and_recovers_only_with_evidence(self):
        from lab.archaioa.governed_model import step
        value=step(step(self.ready(),'dispatch'),'lose_ack')
        self.assertEqual((1,1,'UNKNOWN'),(value.money_nano,value.risk_units,value.reservation))
        for action in ('dispatch','release_not_dispatched','complete','resolve_applied'):
            with self.assertRaises(existing.TransitionRejected):step(value,action)
        for action in ('kill','begin_reconciliation','record_evidence','resolve_applied','complete'):value=step(value,action)
        self.assertTrue(value.effect.completed);self.assertEqual((1,1),(value.money_nano,value.risk_units))
    def test_unsafe_budget_and_refund_states_are_sensitive(self):
        from lab.archaioa.governed_model import step,check_governed_model
        sent=step(self.ready(),'dispatch')
        for bad,name in ((replace(sent,money_nano=2),'PairedBudgetBound'),
                         (replace(sent,risk_units=0),'PairedReservation'),
                         (replace(sent,money_nano=0,risk_units=0,reservation='RELEASED'),'NoRefundAfterDispatch')):
            with self.subTest(name=name),self.assertRaisesRegex(existing.ModelViolation,name):check_governed_model(initial=bad)
