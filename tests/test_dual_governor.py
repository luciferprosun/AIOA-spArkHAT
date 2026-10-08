"""Atomic native-port governor fixtures, not live Cockroach/cloud certification."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.audit import domain_chain
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext, TransactionRunner
from nv03_support import DurableFactory
from test_memory_patch_persistence_ports import FakeFactory

SCOPE = OwnerScope('governor-tenant', 'governor-owner', 'governor-space', 'governor-slot')
MODEL = 'nvidia/Nemotron-3_5-Lightning'


def core():
    return CoreAdmission(LocalOwnerAssignment(SCOPE, frozenset(Capability),
        frozenset({'test-hat'}), frozenset({MODEL}), operator_approved=True),
        clock=lambda: datetime(2030, 1, 1, tzinfo=timezone.utc))


class GovernorPresenceTests(unittest.TestCase):
    def test_native_core_has_dual_durable_reservation_protocol(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.governor'),
            'Token-unit LiteJournal cannot reserve money and operational risk atomically')


class DualGovernorTests(unittest.TestCase):
    def setUp(self):
        from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits, ReservationRequest
        self.Governor, self.Policy, self.Limits, self.Request = CoreDualGovernor, GovernorPolicy, Limits, ReservationRequest
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'native.json'
        self.core = core(); self.addCleanup(self.core.close)
        self.factory = DurableFactory(self.path)
        self.runner = TransactionRunner(self.core, self.factory); self.addCleanup(self.runner.close)
        self.now = 100
        self.policy = self.Policy(SCOPE, 'local-core', self.Limits(100, 10), self.Limits(150, 15), self.Limits(200, 20),
            failure_threshold=2, cooldown_seconds=10, recovery_successes=2, max_clock_step_seconds=120)
        self.gov = self.Governor(self.core, self.runner, self.policy, clock=lambda: self.now)
        self.epoch = self.gov.start_epoch(self.principal(Capability.MANAGE))

    def principal(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def request(self, identity='r1', *, task='task1', provider='nebius', money=50, risk=5, digest=None):
        return self.Request(identity, task, provider, MODEL, digest or canonical_sha256((identity, task, provider)), money, risk)

    def reserve(self, request=None):
        return self.gov.reserve(self.principal(), request or self.request(), self.epoch)

    def inspect(self):
        return self.gov.inspect(self.principal(Capability.READ))

    def dispatch(self, identity='r1'):
        return self.gov.dispatch_commit(self.principal(), identity, self.epoch)

    def test_exact_budget_boundary_reserves_both_dimensions(self):
        self.reserve(self.request(money=100, risk=10))
        self.assertEqual({'money_nano': 100, 'risk_units': 10}, self.inspect()['exposure']['global'])
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.reserve(self.request('r2', money=1, risk=0))

    def test_negative_boolean_and_overflow_amounts_cannot_reserve(self):
        for amount in (-1, True, 2**63, 1.5):
            for field in ('money_nano', 'risk_units'):
                with self.subTest(amount=amount, field=field), self.assertRaises(ValueError):
                    self.reserve(replace(self.request(), **{field: amount}))
        self.assertEqual(0, self.inspect()['exposure']['global']['money_nano'])

    def test_money_and_risk_failure_roll_back_together(self):
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.reserve(self.request(money=1, risk=11))
        self.assertEqual({}, self.inspect()['reservations'])

    def test_task_cap_counts_requests_across_providers(self):
        self.reserve(self.request(money=75, risk=0))
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.reserve(self.request('r2', provider='fixture-other', money=26, risk=0))

    def test_owner_provider_cap_counts_different_tasks(self):
        self.reserve(self.request(task='a', money=100, risk=0))
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.reserve(self.request('r2', task='b', money=51, risk=0))

    def test_global_cap_counts_all_tasks_and_provider_pools(self):
        self.reserve(self.request(task='a', money=100, risk=0))
        self.reserve(self.request('r2', task='b', provider='fixture-other', money=100, risk=0))
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            self.reserve(self.request('r3', task='c', provider='fixture-third', money=1, risk=0))

    def test_identical_id_replay_does_not_reserve_twice(self):
        first = self.reserve(); self.reserve()
        self.assertEqual(first['request_digest'], self.inspect()['reservations']['r1']['request_digest'])
        self.assertEqual(50, self.inspect()['exposure']['global']['money_nano'])

    def test_changed_payload_same_identity_is_conflict(self):
        self.reserve()
        with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
            self.reserve(self.request(money=51))
        self.assertEqual(50, self.inspect()['exposure']['global']['money_nano'])

    def test_concurrent_reservations_cannot_double_spend(self):
        results = []
        barrier = threading.Barrier(2)
        def reserve_one(identity):
            barrier.wait()
            try:
                self.reserve(self.request(identity, money=75, risk=0)); results.append('reserved')
            except ValueError:
                results.append('denied')
        threads = [threading.Thread(target=reserve_one, args=(i,)) for i in ('a', 'b')]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5); self.assertFalse(thread.is_alive())
        self.assertEqual(['denied', 'reserved'], sorted(results))
        self.assertEqual(75, self.inspect()['exposure']['global']['money_nano'])

    def test_dispatch_marker_is_single_use_before_transport(self):
        self.reserve()
        self.assertTrue(self.dispatch()['dispatch_now'])
        self.assertFalse(self.dispatch()['dispatch_now'])
        self.assertEqual('DISPATCHED', self.inspect()['reservations']['r1']['state'])

    def test_positive_reserved_no_dispatch_certificate_releases_atomically(self):
        self.reserve()
        result = self.gov.release_not_dispatched(self.principal(), 'r1', self.epoch)
        self.assertEqual('RELEASED', result['state'])
        self.assertEqual('DURABLE_NO_DISPATCH_MARKER', result['no_dispatch_proof']['kind'])
        self.assertEqual(0, self.inspect()['exposure']['global']['money_nano'])
        self.assertFalse(self.dispatch()['dispatch_now'])

    def test_used_or_unknown_reservation_cannot_be_refunded(self):
        self.reserve(); self.dispatch()
        self.gov.mark_unknown(self.principal(), 'r1', self.epoch, canonical_sha256('timeout'))
        with self.assertRaisesRegex(ValueError, 'NO_DISPATCH_PROOF_REQUIRED'):
            self.gov.release_not_dispatched(self.principal(), 'r1', self.epoch)
        self.assertEqual({'money_nano':50, 'risk_units':5}, self.inspect()['exposure']['global'])

    def test_unknown_survives_restart_and_never_auto_dispatches(self):
        self.reserve(); self.dispatch()
        self.gov.mark_unknown(self.principal(), 'r1', self.epoch, canonical_sha256('lost-ack'))
        second = self.Governor(self.core, self.runner, self.policy, clock=lambda:self.now)
        self.assertEqual('UNKNOWN', second.inspect(self.principal(Capability.READ))['reservations']['r1']['state'])
        self.assertFalse(second.dispatch_commit(self.principal(), 'r1', self.epoch)['dispatch_now'])

    def test_unknown_liability_is_not_reset_by_budget_window(self):
        self.reserve(); self.dispatch()
        self.gov.mark_unknown(self.principal(), 'r1', self.epoch, canonical_sha256('unknown'))
        self.now += 3600
        self.assertEqual(50, self.inspect()['exposure']['global']['money_nano'])
        with self.assertRaisesRegex(ValueError, 'CLOCK_UNSAFE'):
            self.reserve(self.request('r2'))

    def test_evidence_bound_pessimistic_settlement_is_idempotent(self):
        self.reserve(); self.dispatch()
        digest = canonical_sha256('independent-readback')
        self.gov.settle(self.principal(), 'r1', self.epoch, digest)
        self.gov.settle(self.principal(), 'r1', self.epoch, digest)
        self.assertEqual('COMMITTED', self.inspect()['reservations']['r1']['state'])
        self.assertEqual(50, self.inspect()['exposure']['global']['money_nano'])
        with self.assertRaisesRegex(ValueError, 'IDEMPOTENCY_CONFLICT'):
            self.gov.settle(self.principal(), 'r1', self.epoch, canonical_sha256('different'))

    def test_kill_denies_new_reserves_and_dispatch_but_not_read_or_settlement(self):
        self.reserve(); self.dispatch()
        self.gov.set_kill(self.principal(Capability.MANAGE), True)
        self.assertTrue(self.inspect()['kill'])
        with self.assertRaisesRegex(ValueError, 'KILL_SWITCH'):
            self.reserve(self.request('r2'))
        self.gov.settle(self.principal(), 'r1', self.epoch, canonical_sha256('readback'))
        self.assertEqual('COMMITTED', self.inspect()['reservations']['r1']['state'])

    def test_kill_before_dispatch_commit_produces_zero_transport(self):
        self.reserve()
        self.gov.set_kill(self.principal(Capability.MANAGE), True)
        with self.assertRaisesRegex(ValueError, 'KILL_SWITCH'):
            self.dispatch()
        self.assertEqual('RESERVED', self.inspect()['reservations']['r1']['state'])

    def test_epoch_takeover_fences_prior_reservation_and_old_writer(self):
        self.reserve()
        new_epoch = self.gov.start_epoch(self.principal(Capability.MANAGE))
        self.assertEqual(self.epoch+1, new_epoch)
        with self.assertRaisesRegex(ValueError, 'STALE_EPOCH'):
            self.dispatch()
        with self.assertRaisesRegex(ValueError, 'STALE_RESERVATION_EPOCH'):
            self.gov.dispatch_commit(self.principal(), 'r1', new_epoch)
        self.assertEqual(50, self.inspect()['exposure']['global']['money_nano'])

    def test_model_and_worker_principals_cannot_change_kill_or_epoch(self):
        for purpose in (Capability.CANDIDATE, Capability.COMMIT, Capability.READ):
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                self.gov.set_kill(self.principal(purpose), True)
        self.assertFalse(self.inspect()['kill'])

    def test_other_owner_cannot_inspect_or_reserve(self):
        other = CoreAdmission(LocalOwnerAssignment(OwnerScope('other','other','other','other'),
            frozenset(Capability), frozenset({'test-hat'}), frozenset({MODEL}), operator_approved=True))
        self.addCleanup(other.close)
        with self.assertRaises(ValueError):
            self.gov.reserve(other.local_operator(Capability.COMMIT), self.request(), self.epoch)
        with self.assertRaises(ValueError):
            self.gov.inspect(other.local_operator(Capability.READ))

    def test_clock_rollback_or_forward_jump_cannot_open_circuit(self):
        for now in (99, 1000):
            self.now = now
            with self.subTest(now=now), self.assertRaisesRegex(ValueError, 'CLOCK_UNSAFE'):
                self.reserve()
        self.assertEqual({}, self.inspect()['reservations'])

    def test_operator_kill_remains_available_when_clock_is_unsafe(self):
        self.now=99
        self.gov.set_kill(self.principal(Capability.MANAGE),True)
        self.assertTrue(self.inspect()['kill'])
        self.assertEqual(100,self.inspect()['last_now'])

    def test_unadmitted_payload_fails_before_principal_field_access(self):
        with self.assertRaises(ValueError):
            self.gov.reserve({'approved':True},self.request(),self.epoch)
        self.assertEqual({},self.inspect()['reservations'])

    def fail_request(self, identity, task):
        self.reserve(self.request(identity, task=task, money=1, risk=1)); self.dispatch(identity)
        self.gov.mark_unknown(self.principal(), identity, self.epoch, canonical_sha256(identity))

    def test_failure_threshold_opens_and_cooldown_resists_flapping(self):
        self.fail_request('a', 'a'); self.fail_request('b', 'b')
        self.assertEqual('OPEN', self.inspect()['circuits']['nebius']['state'])
        self.now += 9
        with self.assertRaisesRegex(ValueError, 'CIRCUIT_OPEN'):
            self.reserve(self.request('c', task='c', money=1, risk=1))
        self.assertEqual('OPEN', self.inspect()['circuits']['nebius']['state'])

    def test_half_open_probe_is_exclusive_and_needs_two_successes(self):
        self.fail_request('a','a'); self.fail_request('b','b'); self.now += 10
        self.reserve(self.request('probe1', task='c', money=1, risk=1))
        self.assertEqual('HALF_OPEN', self.inspect()['circuits']['nebius']['state'])
        with self.assertRaisesRegex(ValueError, 'HALF_OPEN_BUSY'):
            self.reserve(self.request('probe2', task='d', money=1, risk=1))
        self.dispatch('probe1'); self.gov.settle(self.principal(),'probe1',self.epoch,canonical_sha256('ok1'))
        self.assertEqual('HALF_OPEN',self.inspect()['circuits']['nebius']['state'])
        self.reserve(self.request('probe2',task='d',money=1,risk=1));self.dispatch('probe2')
        self.gov.settle(self.principal(),'probe2',self.epoch,canonical_sha256('ok2'))
        self.assertEqual('CLOSED',self.inspect()['circuits']['nebius']['state'])

    def test_restart_during_half_open_conservatively_reopens(self):
        self.fail_request('a','a');self.fail_request('b','b');self.now += 10
        self.reserve(self.request('probe',task='c',money=1,risk=1))
        new_epoch=self.gov.start_epoch(self.principal(Capability.MANAGE))
        self.assertEqual('OPEN',self.inspect()['circuits']['nebius']['state'])
        with self.assertRaisesRegex(ValueError,'STALE_RESERVATION_EPOCH'):
            self.gov.dispatch_commit(self.principal(),'probe',new_epoch)

    def test_governor_events_use_native_audit_and_insert_only_operations(self):
        self.reserve();self.dispatch()
        events=self.runner.run(TransactionContext(self.principal(Capability.READ),Capability.READ),domain_chain)
        self.assertEqual(3,len(events))
        self.assertEqual(list(range(3)),[e.sequence_number for e in events])
        operations=[r for (_,kind,_),r in self.factory.state.items() if kind is RecordKind.OPERATION]
        self.assertEqual({1},{r.revision for r in operations})

    def test_lost_reservation_ack_keeps_exposure_without_transport(self):
        factory=FakeFactory(commit_faults=['unknown_after_commit'])
        runner=TransactionRunner(self.core,factory);self.addCleanup(runner.close)
        gov=self.Governor(self.core,runner,self.policy,clock=lambda:self.now)
        with self.assertRaises(CommitOutcomeUnknown):gov.start_epoch(self.principal(Capability.MANAGE))
        epoch=gov.inspect(self.principal(Capability.READ))['epoch']
        factory.commit_faults=['unknown_after_commit']
        with self.assertRaises(CommitOutcomeUnknown):gov.reserve(self.principal(),self.request(),epoch)
        state=gov.inspect(self.principal(Capability.READ))
        self.assertEqual('RESERVED',state['reservations']['r1']['state'])
        self.assertEqual(50,state['exposure']['global']['money_nano'])

    def test_lost_dispatch_ack_never_replays_marker_as_send_permission(self):
        factory=FakeFactory();runner=TransactionRunner(self.core,factory);self.addCleanup(runner.close)
        gov=self.Governor(self.core,runner,self.policy,clock=lambda:self.now)
        epoch=gov.start_epoch(self.principal(Capability.MANAGE));gov.reserve(self.principal(),self.request(),epoch)
        factory.commit_faults=['unknown_after_commit']
        with self.assertRaises(CommitOutcomeUnknown):gov.dispatch_commit(self.principal(),'r1',epoch)
        self.assertFalse(gov.dispatch_commit(self.principal(),'r1',epoch)['dispatch_now'])
        self.assertEqual(50,gov.inspect(self.principal(Capability.READ))['exposure']['global']['money_nano'])

    def test_complete_scan_quota_fails_closed_instead_of_forgetting_exposure(self):
        factory=FakeFactory();runner=TransactionRunner(self.core,factory);self.addCleanup(runner.close)
        for n in range(1024):
            record=StoredRecord(RecordKind.OPERATION,str(n),SCOPE,1,{'state':'unrelated'})
            factory.state[(SCOPE.binding(),record.kind,record.record_id)]=record
        gov=self.Governor(self.core,runner,self.policy,clock=lambda:self.now)
        with self.assertRaisesRegex(ValueError,'HISTORY_QUOTA'):
            gov.start_epoch(self.principal(Capability.MANAGE))

    def test_policy_change_cannot_silently_reuse_old_liabilities(self):
        self.reserve()
        changed=replace(self.policy,global_limit=self.Limits(201,20))
        gov=self.Governor(self.core,self.runner,changed,clock=lambda:self.now)
        with self.assertRaisesRegex(ValueError,'POLICY_BINDING'):
            gov.inspect(self.principal(Capability.READ))

    def test_opaque_transport_text_and_authority_fields_are_not_governor_inputs(self):
        with self.assertRaises(TypeError):self.Request(**{**asdict(self.request()),'approved':True})

    def test_restart_in_fresh_process_retains_unknown_liability(self):
        self.reserve();self.dispatch()
        self.gov.mark_unknown(self.principal(),'r1',self.epoch,canonical_sha256('lost'))
        code='''from pathlib import Path
import sys,json
from test_dual_governor import core,SCOPE
from nv03_support import DurableFactory
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
c=core();r=TransactionRunner(c,DurableFactory(Path(sys.argv[1])))
p=GovernorPolicy(SCOPE,'local-core',Limits(100,10),Limits(150,15),Limits(200,20),failure_threshold=2,cooldown_seconds=10,recovery_successes=2,max_clock_step_seconds=120)
g=CoreDualGovernor(c,r,p,clock=lambda:100)
s=g.inspect(c.local_operator(Capability.READ))
assert s['reservations']['r1']['state']=='UNKNOWN'
assert s['exposure']['global']['money_nano']==50
print('FRESH_PROCESS_UNKNOWN_RETAINED')
r.close();c.close()
'''
        result=subprocess.run([sys.executable,'-B','-c',code,str(self.path)],capture_output=True,text=True,timeout=8)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual('FRESH_PROCESS_UNKNOWN_RETAINED',result.stdout.strip())
