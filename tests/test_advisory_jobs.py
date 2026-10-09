"""Offline job state/fence over one native governor, no scheduler or transport."""
from dataclasses import replace
import importlib.util
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.providers.nvidia import ProviderRequest,ProviderResponse
import test_dual_governor as native_fixtures

class AdvisoryJobPresenceTests(unittest.TestCase):
    def test_governor_owns_native_offline_job_contract(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.job_contracts'))
        from runtime.mission.governor import CoreDualGovernor
        self.assertTrue(callable(getattr(CoreDualGovernor,'submit_job',None)))

class AdvisoryJobTests(unittest.TestCase):
    def setUp(self):
        from runtime.mission.job_contracts import JobEnvelope
        self.fx=native_fixtures.DualGovernorTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.gov=self.fx.gov;self.p=self.fx.principal();self.host=self.fx.principal(Capability.MANAGE)
        self.read=self.fx.principal(Capability.READ)
        self.request=ProviderRequest('native-request','native-trace','nebius',native_fixtures.MODEL,'Fixture bounded advice','native-budget',128,20)
        self.envelope=JobEnvelope.from_request(native_fixtures.SCOPE,
            'advisory-job',self.request,deadline_at=160,money_nano=50,risk_units=5)
        self.gov.submit_job(self.host,self.envelope)
    def claim(self,worker='worker-a'):
        return self.gov.claim_job(self.p,self.envelope.task_id,worker,self.fx.epoch,lease_seconds=10)
    def start(self,claim):return self.gov.begin_job(self.p,claim)
    def response(self):return ProviderResponse(self.request.request_id,'synthetic-receipt',native_fixtures.MODEL,101,'stop',100,
        {'summary':'Synthetic advisory only','needs_attention':False},{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
    def test_same_envelope_replay_never_duplicates_reservation(self):
        self.gov.submit_job(self.host,self.envelope);claim=self.claim()
        self.assertEqual(claim,self.claim());self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])
        with self.assertRaises(ValueError):self.gov.submit_job(self.host,replace(self.envelope,request_digest='a'*64))
    def test_paired_budget_failure_leaves_queued_job_without_partial_claim(self):
        self.gov.submit_job(self.host,replace(self.envelope,task_id='too-risky',risk_units=11))
        with self.assertRaises(ValueError):self.gov.claim_job(self.p,'too-risky','worker-b',self.fx.epoch,lease_seconds=10)
        self.assertEqual('QUEUED',self.gov.inspect_job(self.read,'too-risky')['state'])
        self.assertEqual(0,self.fx.inspect()['exposure']['global']['money_nano'])
    def test_claim_start_result_single_use_and_advisory_only(self):
        claim=self.claim();self.assertTrue(self.start(claim)['fixture_step_now'])
        self.assertFalse(self.start(claim)['fixture_step_now'])
        result=self.gov.finish_job(self.p,claim,self.response())
        self.assertEqual('DONE',result['state']);self.assertEqual('NONE',result['authority'])
        self.assertEqual(result,self.gov.finish_job(self.p,claim,self.response()))
        self.assertFalse(self.start(claim)['fixture_step_now'])
    def test_concurrent_claims_have_one_owner_and_one_paired_charge(self):
        def run(worker):
            try:return self.claim(worker).worker_id
            except ValueError:return 'DENIED'
        with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(run,['worker-a','worker-b']))
        self.assertEqual(1,results.count('DENIED'));self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])
    def test_expired_claim_takeover_fences_old_worker_and_does_not_charge_twice(self):
        old=self.claim();self.fx.now=110
        new=self.gov.takeover_job(self.host,old.task_id,'worker-b',self.fx.epoch,lease_seconds=10)
        self.assertEqual(old.fence+1,new.fence)
        with self.assertRaises(ValueError):self.start(old)
        self.assertTrue(self.start(new)['fixture_step_now'])
        with self.assertRaises(ValueError):self.gov.finish_job(self.p,old,self.response())
        self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])
    def test_started_takeover_is_unknown_no_second_fixture_step(self):
        old=self.claim();self.start(old);self.fx.now=110
        new=self.gov.takeover_job(self.host,old.task_id,'worker-b',self.fx.epoch,lease_seconds=10)
        self.assertEqual('UNKNOWN',self.gov.inspect_job(self.read,old.task_id)['state'])
        self.assertFalse(self.start(new)['fixture_step_now'])
        with self.assertRaises(ValueError):self.gov.finish_job(self.p,new,self.response())
        self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])
    def test_kill_and_stale_epoch_block_begin_but_leave_readback_available(self):
        claim=self.claim();self.gov.set_kill(self.host,True)
        with self.assertRaises(ValueError):self.start(claim)
        self.assertEqual('CLAIMED',self.gov.inspect_job(self.read,claim.task_id)['state'])
        self.gov.set_kill(self.host,False);self.gov.start_epoch(self.host)
        with self.assertRaises(ValueError):self.start(claim)
    def test_lost_start_ack_and_restart_do_not_repeat_step(self):
        claim=self.claim()
        from nv03_support import DurableTransaction
        original=DurableTransaction.commit
        def lost(tx):
            original(tx);raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',lost):
            with self.assertRaises(CommitOutcomeUnknown):self.start(claim)
        from runtime.mission.governor import CoreDualGovernor
        restarted=CoreDualGovernor(self.fx.core,self.fx.runner,self.fx.policy,clock=lambda:self.fx.now)
        self.assertFalse(restarted.begin_job(self.p,claim)['fixture_step_now'])
        self.assertEqual('STARTED',restarted.inspect_job(self.read,claim.task_id)['state'])
    def test_result_identity_and_model_authority_mismatch_fail_closed(self):
        claim=self.claim();self.start(claim)
        for bad in (replace(self.response(),authority='APPROVED'),replace(self.response(),model_id='other-model'),replace(self.response(),request_id='other-request')):
            with self.subTest(value=bad.model_id),self.assertRaises(ValueError):self.gov.finish_job(self.p,claim,bad)
        self.assertEqual('STARTED',self.gov.inspect_job(self.read,claim.task_id)['state'])
    def test_read_worker_cannot_claim_and_envelope_contains_no_prompt(self):
        with self.assertRaises(ValueError):self.gov.claim_job(self.read,self.envelope.task_id,'read-worker',self.fx.epoch,lease_seconds=10)
        self.assertNotIn(self.request.input_text,str(self.envelope.as_dict()))

    def test_renew_returns_new_claim_and_old_claim_cannot_begin(self):
        old=self.claim();self.fx.now=105
        new=self.gov.renew_job(self.p,old,lease_seconds=10)
        self.assertEqual(115,new.lease_until)
        with self.assertRaises(ValueError):self.start(old)
        self.assertTrue(self.start(new)['fixture_step_now'])

    def test_expiry_during_durable_start_grants_zero_fixture_steps(self):
        from nv03_support import DurableTransaction
        claim=self.claim();original=DurableTransaction.commit
        def late(tx):original(tx);self.fx.now=110
        with patch.object(DurableTransaction,'commit',late):result=self.start(claim)
        self.assertFalse(result['fixture_step_now'])
        self.assertFalse(self.start(claim)['fixture_step_now'])
        self.assertEqual('STARTED',self.gov.inspect_job(self.read,claim.task_id)['state'])

    def test_lost_result_ack_has_one_durable_result_and_no_restart(self):
        from nv03_support import DurableTransaction
        claim=self.claim();self.start(claim);response=self.response();original=DurableTransaction.commit
        def lost(tx):original(tx);raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',lost):
            with self.assertRaises(CommitOutcomeUnknown):self.gov.finish_job(self.p,claim,response)
        self.assertEqual('DONE',self.gov.finish_job(self.p,claim,response)['state'])
        self.assertFalse(self.start(claim)['fixture_step_now'])
        self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_provider_payload_is_snapshotted_before_retry_callback(self):
        claim=self.claim();self.start(claim);response=self.response();expected=canonical_sha256(response)
        original=self.fx.factory.begin
        def begin(*args,**kwargs):
            response.parsed_payload.clear();response.parsed_payload['approved']=True
            return original(*args,**kwargs)
        with patch.object(self.fx.factory,'begin',begin):result=self.gov.finish_job(self.p,claim,response)
        self.assertEqual('DONE',result['state']);self.assertEqual(expected,result['result_digest'])

    def test_global_epoch_takeover_of_undispatched_claim_transfers_fence_only(self):
        old=self.claim();self.fx.now=110;epoch=self.gov.start_epoch(self.host)
        new=self.gov.takeover_job(self.host,old.task_id,'worker-b',epoch,lease_seconds=10)
        self.assertTrue(self.start(new)['fixture_step_now'])
        with self.assertRaises(ValueError):self.start(old)
        self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_unknown_takeover_retains_native_unknown_reservation(self):
        old=self.claim();self.start(old);self.fx.now=110
        self.gov.takeover_job(self.host,old.task_id,'worker-b',self.fx.epoch,lease_seconds=10)
        reservation=self.gov.inspect_job(self.read,old.task_id)['reservation_id']
        self.assertEqual('UNKNOWN',self.fx.inspect()['reservations'][reservation]['state'])

    def test_fresh_process_restart_observes_start_and_never_repeats_it(self):
        import json,subprocess,sys
        from dataclasses import asdict
        claim=self.claim();self.start(claim)
        code='''import json,sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
from runtime.core_admission import Capability
from runtime.mission.governor import CoreDualGovernor
from runtime.mission.job_contracts import JobClaim
from runtime.memory_patch.persistence.ports import TransactionRunner
import test_dual_governor as f
from nv03_support import DurableFactory
value=json.loads(sys.stdin.read());c=f.core();runner=TransactionRunner(c,DurableFactory(value['path']))
from runtime.mission.governor import GovernorPolicy,Limits
policy=GovernorPolicy(f.SCOPE,'local-core',Limits(100,10),Limits(150,15),Limits(200,20),failure_threshold=2,cooldown_seconds=10,recovery_successes=2,max_clock_step_seconds=120)
gov=CoreDualGovernor(c,runner,policy,clock=lambda:100);claim=JobClaim(**value['claim'])
r=gov.begin_job(c.local_operator(Capability.COMMIT),claim);print(json.dumps({'state':r['state'],'step':r['fixture_step_now']}))
runner.close();c.close()
'''
        result=subprocess.run([sys.executable,'-B','-c',code],input=json.dumps({'path':str(self.fx.path),'claim':asdict(claim)}),text=True,capture_output=True,timeout=10)
        self.assertEqual(0,result.returncode,result.stderr)
        self.assertEqual({'state':'STARTED','step':False},json.loads(result.stdout))

    def test_other_task_claim_is_not_invalidated_by_task_takeover(self):
        self.gov.submit_job(self.host,replace(self.envelope,task_id='another-job',request_id='another-request'))
        other=self.gov.claim_job(self.p,'another-job','worker-other',self.fx.epoch,lease_seconds=20)
        old=self.claim();self.fx.now=110
        self.gov.takeover_job(self.host,old.task_id,'worker-b',self.fx.epoch,lease_seconds=10)
        self.assertTrue(self.gov.begin_job(self.p,other)['fixture_step_now'])
        self.assertEqual(100,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_lease_expiry_denies_late_result_and_keeps_full_exposure(self):
        claim=self.claim();self.start(claim);self.fx.now=110
        with self.assertRaises(ValueError):self.gov.finish_job(self.p,claim,self.response())
        self.assertEqual('STARTED',self.gov.inspect_job(self.read,claim.task_id)['state'])
        self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_cross_owner_read_and_authority_bearing_envelope_are_denied(self):
        from runtime.mission.job_contracts import JobEnvelope
        from test_memory_patch_persistence_ports import make_admission
        other=make_admission(owner='other-owner');self.addCleanup(other.close)
        with self.assertRaises(ValueError):self.gov.inspect_job(other.local_operator(Capability.READ),self.envelope.task_id)
        with self.assertRaises(ValueError):JobEnvelope.parse({**self.envelope.as_dict(),'approved':True})

    def test_invalid_clock_does_not_block_job_readback(self):
        claim=self.claim();self.start(claim)
        for label,value in [('negative',-1),('nan',float('nan')),('infinite',float('inf'))]:
            with self.subTest(clock=label):
                self.fx.now=value
                self.assertEqual('STARTED',self.gov.inspect_job(self.read,claim.task_id)['state'])
                self.assertEqual(50,self.fx.inspect()['exposure']['global']['money_nano'])

    def test_sustained_renewal_advances_durable_governor_clock(self):
        self.gov.submit_job(self.host,replace(self.envelope,task_id='long-job',request_id='long-request',deadline_at=1000))
        claim=self.gov.claim_job(self.p,'long-job','worker-long',self.fx.epoch,lease_seconds=60)
        for now in (150,200,250):
            self.fx.now=now;claim=self.gov.renew_job(self.p,claim,lease_seconds=60)
            self.assertEqual(now,self.fx.inspect()['last_now'])
        self.assertTrue(self.start(claim)['fixture_step_now'])

    def test_job_only_renewal_cannot_hide_cross_task_clock_rollback(self):
        self.gov.submit_job(self.host,replace(self.envelope,task_id='long-job',request_id='long-request',deadline_at=1000))
        claim=self.gov.claim_job(self.p,'long-job','worker-long',self.fx.epoch,lease_seconds=60)
        for now in (150,200):
            self.fx.now=now;claim=self.gov.renew_job(self.p,claim,lease_seconds=60)
        self.fx.now=150
        with self.assertRaisesRegex(ValueError,'CLOCK_UNSAFE'):self.claim()
        self.assertEqual('QUEUED',self.gov.inspect_job(self.read,self.envelope.task_id)['state'])
