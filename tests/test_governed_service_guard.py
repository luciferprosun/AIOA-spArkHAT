"""Risk gate at the original human-authorized disposable target boundary."""
from pathlib import Path
from dataclasses import replace
import tempfile
import unittest
from unittest.mock import patch

from nv09_support import GuardFixture,LocalTarget
from runtime.core_admission import Capability
from runtime.mission.governor import CoreDualGovernor,GovernorBinding,GovernorPolicy,Limits
from runtime.service_guard.service import CoreServiceGuard,GuardLoopBinding


class GovernedServiceGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.target=LocalTarget(self.root/'target');self.addCleanup(self.target.close)
        self.fx=GuardFixture(self.root/'guard',self.target.client);self.addCleanup(self.fx.close)

    def compose(self,*,risk=3,limit=10):
        policy=GovernorPolicy(self.fx.scope,'single-core',Limits(0,limit),Limits(0,limit),Limits(0,limit))
        self.gov=CoreDualGovernor(self.fx.core,self.fx.runner,policy,clock=self.fx.clock)
        self.epoch=self.gov.start_epoch(self.fx.core.local_operator(Capability.MANAGE))
        binding=GovernorBinding(self.gov,self.fx.core.local_operator(Capability.COMMIT),self.epoch,'effect-task',risk)
        try:
            guard=CoreServiceGuard(self.fx.core,self.fx.runner,self.fx.policy,self.target.client,
                clock=self.fx.clock,governor_binding=binding)
        except TypeError:
            self.fail('Existing ServiceGuard lacks the explicit Core risk-governor composition boundary')
        self.fx.guard=guard
        self.fx.bindings=replace(self.fx.bindings,service_guard=GuardLoopBinding(guard,self.fx.operation_id))
        self.fx.runtime._lite_scheduler.bindings=self.fx.bindings
        return guard

    def state(self):
        return self.gov.inspect(self.fx.core.local_operator(Capability.READ))

    def test_risk_budget_denies_human_approved_effect_before_dispatch(self):
        self.compose(limit=2);self.fx.approve()
        result=self.fx.tick()
        self.assertEqual('BLOCKED',result['status'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual(0,self.state()['exposure']['global']['risk_units'])

    def test_one_disposable_effect_has_one_conservative_risk_charge_and_replay_is_read_only(self):
        self.compose();self.fx.approve()
        self.assertEqual('VERIFIED',self.fx.tick()['status'])
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])
        self.assertEqual({'COMMITTED'},{r['state'] for r in self.state()['reservations'].values()})
        self.assertEqual('REPLAY',self.fx.tick()['status'])
        self.assertEqual(1,self.target.client.read()['effect_count'])
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])

    def test_kill_at_original_actual_boundary_yields_zero_disposable_effects(self):
        guard=self.compose();self.fx.approve()
        original=guard._boundary_check
        def kill_first(_instance,*args):
            self.gov.set_kill(self.fx.core.local_operator(Capability.MANAGE),True)
            return original(*args)
        with patch.object(CoreServiceGuard,'_boundary_check',side_effect=kill_first):
            result=self.fx.tick()
        self.assertEqual('BLOCKED',result['status'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual(0,self.state()['exposure']['global']['risk_units'])

    def test_human_revocation_remains_stronger_than_governor_reservation(self):
        guard=self.compose();self.fx.approve();original=guard._boundary_check
        def revoke_first(_instance,*args):
            guard.revoke(self.fx.core.local_operator(Capability.OWNER_APPROVAL),self.fx.operation_id)
            return original(*args)
        with patch.object(CoreServiceGuard,'_boundary_check',side_effect=revoke_first):result=self.fx.tick()
        self.assertEqual('CONSENT_REVOKED',result['reason'])
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual(0,self.state()['exposure']['global']['risk_units'])

    def test_stale_governor_epoch_cannot_cross_existing_target_boundary(self):
        guard=self.compose();self.fx.approve();original=guard._boundary_check
        def take_over(_instance,*args):
            self.gov.start_epoch(self.fx.core.local_operator(Capability.MANAGE))
            return original(*args)
        with patch.object(CoreServiceGuard,'_boundary_check',side_effect=take_over):result=self.fx.tick()
        self.assertIn(result['status'],('BLOCKED','UNKNOWN'))
        self.assertEqual(0,self.target.client.read()['effect_count'])
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])

    def test_lost_target_ack_holds_risk_and_kill_allows_receipt_only_reconciliation(self):
        self.fx.close();self.target.close()
        self.target=LocalTarget(self.root/'loss-target',drop_ack=True);self.addCleanup(self.target.close)
        self.fx=GuardFixture(self.root/'loss-guard',self.target.client);self.addCleanup(self.fx.close)
        self.compose();self.fx.approve()
        self.assertEqual('UNKNOWN',self.fx.tick()['status'])
        self.assertEqual({'UNKNOWN'},{r['state'] for r in self.state()['reservations'].values()})
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])
        self.gov.set_kill(self.fx.core.local_operator(Capability.MANAGE),True)
        self.assertEqual('VERIFIED',self.fx.tick()['status'])
        self.assertEqual(1,self.target.client.read()['effect_count'])
        self.assertEqual({'COMMITTED'},{r['state'] for r in self.state()['reservations'].values()})
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])

    def test_verified_receipt_replay_recovers_unknown_settlement_without_second_effect(self):
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        self.compose();self.fx.approve()
        with patch.object(self.gov,'settle',side_effect=CommitOutcomeUnknown()):
            self.assertEqual('UNKNOWN',self.fx.tick()['status'])
        self.assertEqual(1,self.target.client.read()['effect_count'])
        self.assertEqual({'DISPATCHED'},{r['state'] for r in self.state()['reservations'].values()})
        self.gov.set_kill(self.fx.core.local_operator(Capability.MANAGE),True)
        self.assertEqual('REPLAY',self.fx.tick()['status'])
        self.assertEqual({'COMMITTED'},{r['state'] for r in self.state()['reservations'].values()})
        self.assertEqual(1,self.target.client.read()['effect_count'])
        self.assertEqual(3,self.state()['exposure']['global']['risk_units'])
