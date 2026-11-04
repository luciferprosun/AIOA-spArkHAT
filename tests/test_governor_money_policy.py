"""Real native journal fixtures; policy changes never spend or clear UNKNOWN."""
import unittest
import json
from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord,TransactionRunner
from runtime.memory_patch.adapters.cockroach.repositories import canonical_record
from runtime.core_admission import Capability,AdmissionError
from runtime.memory_patch.contracts.serialization import canonical_sha256
import test_dual_governor as fixture


class MoneyPolicyTests(unittest.TestCase):
    setUp=fixture.DualGovernorTests.setUp
    principal=fixture.DualGovernorTests.principal
    request=fixture.DualGovernorTests.request
    reserve=fixture.DualGovernorTests.reserve
    inspect=fixture.DualGovernorTests.inspect
    dispatch=fixture.DualGovernorTests.dispatch

    def review(self,amount=148000000000,request_id='budget-1'):
        return self.gov.money_policy_review(self.principal(Capability.READ),
            {'task_limit':amount,'owner_provider_limit':amount,'global_limit':amount},request_id=request_id)
    def apply(self,review):
        return self.gov.apply_money_policy(self.principal(Capability.MANAGE),review)

    def test_transition_preserves_unknown_exposure_kill_circuits_and_prior_bytes(self):
        self.reserve();self.dispatch();self.gov.mark_unknown(self.principal(),'r1',self.epoch,canonical_sha256('unknown'))
        self.gov.set_kill(self.principal(Capability.MANAGE),True)
        # Each old canonical row (including audit/outbox) must remain byte-identical.
        old_rows={raw:digest for raw,digest in json.loads(self.path.read_text())}
        before=self.inspect();review=self.review();self.apply(review);after=self.inspect()
        new_rows={raw:digest for raw,digest in json.loads(self.path.read_text())}
        self.assertTrue(old_rows.items()<=new_rows.items())
        self.assertEqual(before['reservations'],after['reservations']);self.assertEqual(before['exposure'],after['exposure'])
        self.assertEqual(before['circuits'],after['circuits']);self.assertEqual(before['kill'],after['kill'])
        self.assertEqual(before['epoch']+1,after['epoch']);self.assertEqual(148000000000,after['money_policy']['limits']['global_limit'])
        # Same governor/bootstrap/namespace and immutable old history.
        self.assertEqual(before['policy_digest'],after['policy_digest'])
        first=after['version'];self.apply(review);self.assertEqual(first,self.inspect()['version'])

    def test_forged_principal_changed_review_and_stale_epoch_are_denied(self):
        review=self.review()
        with self.assertRaises(AdmissionError):self.gov.apply_money_policy(None,review)
        changed={**review,'limits':{**review['limits'],'global_limit':1}}
        with self.assertRaises(ValueError):self.apply(changed)
        self.gov.start_epoch(self.principal(Capability.MANAGE))
        with self.assertRaises(ValueError):self.apply(review)

    def test_lower_than_existing_exposure_is_denied_without_refund(self):
        self.reserve();before=self.inspect()
        with self.assertRaises(ValueError):self.apply(self.review(1))
        self.assertEqual(before,self.inspect())

    def test_restart_reads_v1_and_transition_history_and_old_epoch_cannot_dispatch(self):
        self.reserve();review=self.review();self.apply(review)
        restored=self.Governor(self.core,self.runner,self.policy,clock=lambda:self.now)
        self.assertEqual(self.inspect(),restored.inspect(self.principal(Capability.READ)))
        with self.assertRaises(ValueError):restored.dispatch_commit(self.principal(),'r1',self.epoch)

    def rewrite_last(self,change):
        rows=json.loads(self.path.read_text());candidates=[]
        for index,(raw,digest) in enumerate(rows):
            data=json.loads(raw)
            if data['payload'].get('operation_kind')=='aioa-dual-governor-v1':
                candidates.append((data['payload']['outcome']['state']['version'],index,data))
        _,index,data=max(candidates);outcome=data['payload']['outcome'];change(outcome)
        data['payload']['payload_digest']=canonical_sha256(outcome)
        record=StoredRecord(RecordKind(data['kind']),data['record_id'],self.policy.scope,data['revision'],data['payload'])
        rows[index]=[canonical_record(record),record.payload_digest]
        self.path.write_text(json.dumps(rows))

    def test_changed_limits_without_explicit_transition_are_rejected(self):
        self.apply(self.review())
        self.rewrite_last(lambda value:value.pop('policy_transition'))
        with self.assertRaises(ValueError):self.inspect()

    def test_transition_cannot_change_kill_or_reservations(self):
        self.apply(self.review())
        self.rewrite_last(lambda value:value['state'].update(kill=True))
        with self.assertRaises(ValueError):self.inspect()

    def test_transition_reader_rejects_backward_time(self):
        self.apply(self.review())
        self.rewrite_last(lambda value:value['state'].update(last_now=99))
        with self.assertRaises(ValueError):self.inspect()

    def test_transition_reader_rejects_duplicate_historical_request(self):
        self.apply(self.review());self.apply(self.review(147000000000,request_id='budget-2'))
        def duplicate(value):
            review=value['policy_transition'];review['request_id']='budget-1'
            review['review_digest']=canonical_sha256({k:v for k,v in review.items() if k!='review_digest'})
            value['state']['money_policy'].update(request_id=review['request_id'],review_digest=review['review_digest'])
        self.rewrite_last(duplicate)
        with self.assertRaises(ValueError):self.inspect()

    def test_lost_policy_commit_ack_is_readback_only_and_never_reapplied(self):
        from test_memory_patch_persistence_ports import FakeFactory
        from runtime.memory_patch.errors import CommitOutcomeUnknown
        factory=FakeFactory();runner=TransactionRunner(self.core,factory);self.addCleanup(runner.close)
        gov=self.Governor(self.core,runner,self.policy,clock=lambda:self.now)
        gov.start_epoch(self.principal(Capability.MANAGE))
        review=gov.money_policy_review(self.principal(Capability.READ),self.review()['limits'],request_id='ack-lost')
        factory.commit_faults=['unknown_after_commit']
        with self.assertRaises(CommitOutcomeUnknown):gov.apply_money_policy(self.principal(Capability.MANAGE),review)
        current=gov.inspect(self.principal(Capability.READ))
        self.assertTrue(gov.apply_money_policy(self.principal(Capability.MANAGE),review)['readback_only'])
        self.assertEqual(current,gov.inspect(self.principal(Capability.READ)))

    def test_explicit_unlimited_money_policy_retains_unknown_risk_and_history(self):
        self.reserve();self.dispatch()
        self.gov.mark_unknown(self.principal(),'r1',self.epoch,canonical_sha256('unknown'))
        before=self.inspect();old_rows=json.loads(self.path.read_text())
        review=self.review(None,request_id='unlimited-chat')
        self.assertEqual('aioa.governor.money-review.v3',review['schema'])
        self.apply(review);after=self.inspect()
        self.assertEqual(before['reservations'],after['reservations'])
        self.assertEqual(before['exposure'],after['exposure'])
        self.assertEqual(before['circuits'],after['circuits'])
        self.assertEqual(before['policy_digest'],after['policy_digest'])
        self.assertEqual({key:None for key in review['limits']},after['money_policy']['limits'])
        self.assertTrue(all(row in json.loads(self.path.read_text()) for row in old_rows))
        restored=self.Governor(self.core,self.runner,self.policy,clock=lambda:self.now)
        self.assertEqual(after,restored.inspect(self.principal(Capability.READ)))
        with self.assertRaises(ValueError):self.apply(self.review(1,request_id='too-low'))

    def test_unlimited_is_explicit_and_does_not_accept_partial_or_boolean_limits(self):
        for amount in (False,True,-1,'unlimited'):
            with self.subTest(amount=amount),self.assertRaises(ValueError):self.review(amount)
        with self.assertRaises(ValueError):
            self.gov.money_policy_review(self.principal(Capability.READ),
                {'task_limit':None,'owner_provider_limit':1,'global_limit':None},request_id='mixed')

    def test_unlimited_money_does_not_remove_risk_or_kill_gates(self):
        self.apply(self.review(None));self.epoch=self.inspect()['epoch']
        self.reserve(self.request(money=10**12,risk=1))
        with self.assertRaisesRegex(ValueError,'BUDGET_EXCEEDED'):
            self.reserve(self.request('excess-risk',money=1,risk=20))
        self.gov.set_kill(self.principal(Capability.MANAGE),True)
        with self.assertRaisesRegex(ValueError,'KILL_SWITCH'):
            self.reserve(self.request('after-stop',money=1,risk=1))


if __name__=='__main__':unittest.main()
