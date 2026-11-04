"""Real local Core transactions; all provider HTTP is synthetic and patched."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime.core_admission import Capability,CoreAdmission,LocalOwnerAssignment,OwnerScope
from runtime.memory_patch.persistence.ports import LocalCoreRecordFactory,TransactionRunner,RecordKind,TransactionContext
from runtime.mission.warrant import CoreWarrantLedger
from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,Limits
from runtime.providers.config import ProviderManager
from runtime.providers.meta_model_api import MetaModelProvider
from runtime.meta_hackathon.mission_service import MissionService


class MetaChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(MissionService,'chat_propose'),'Missing bounded chat in existing MissionService')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.key=self.root/'key';self.key.write_text('SYNTHETIC_META_CHAT_KEY_NEVER_LIVE');self.key.chmod(0o600)
        self.now=datetime(2026,6,1,tzinfo=timezone.utc);self.source=['1'*40,'c'*64];self.valid=True
        self.scope=OwnerScope('fixture-chat','fixture-owner','fixture-workspace','fixture-slot')
        self.core=CoreAdmission(LocalOwnerAssignment(self.scope,frozenset(Capability),frozenset({'fixture'}),
            frozenset({'muse-spark-1.3'}),operator_approved=True),clock=lambda:self.now);self.addCleanup(self.core.close)
        self.runner=TransactionRunner(self.core,LocalCoreRecordFactory(self.root/'records.sqlite3',self.core));self.addCleanup(self.runner.close)
        self.ledger=CoreWarrantLedger(self.core,self.runner,self.scope,clock=lambda:self.now)
        limits=Limits(50000000,20);self.gov=CoreDualGovernor(self.core,self.runner,GovernorPolicy(self.scope,'chat-test',limits,limits,limits),clock=lambda:100)
        self.gov.start_epoch(self.p(Capability.MANAGE))
        self.manager=ProviderManager(self.root,meta_only=True);self.manager.configure_meta(MetaModelProvider(mode='LIVE',key_path=self.key))
        self.service=self.make_service();self.addCleanup(self.service.close)
        self.body={'schema':'aioa.mobile.chat-send.v1','thread_id':'2'*32,'request_id':'3'*32,
            'model_id':'muse-spark-1.3','prompt':'Jaki jest stan Core?','max_budget_usd':'0.05'}
        self.identity={'device_id':'d'*64,'session_id':'4'*32,'nonce':'5'*32,'actor':'ANDROID'}

    def p(self,cap=Capability.READ):return self.core.local_operator(cap)
    def make_service(self):
        service=MissionService(self.ledger,self.manager,None,lambda:tuple(self.source))
        service.bind_chat(self.gov,lambda task:self.valid)
        return service
    def propose(self,**updates):return self.service.chat_propose({**self.body,**updates},self.p(),**self.identity)
    def read(self):return self.service.chat_request(self.body['request_id'],self.p(),device_id=self.identity['device_id'])
    def approve(self,review=None):
        review=review or self.service.chat_review(self.body['request_id'],self.p())
        return self.service.chat_approve(self.body['request_id'],review['review_digest'],self.p(Capability.OWNER_APPROVAL))
    def response(self):
        return (200,json.dumps({'id':'synthetic-chat','model':'muse-spark-1.3','choices':[{'finish_reason':'stop',
            'message':{'role':'assistant','content':'Core jest ADMITTED; narzędzia natywne są wyłączone.'}}],
            'usage':{'prompt_tokens':5,'completion_tokens':10,'total_tokens':15}}).encode())
    def wait(self):
        for _ in range(100):
            result=self.read()
            if result['state']!='RUNNING':return result
            time.sleep(.01)
        self.fail('worker did not finish')

    def test_pending_is_durable_without_loading_key_or_posting(self):
        with patch('runtime.providers.meta_model_api.load_private_key') as key,patch('runtime.providers.meta_model_api._https_once') as http:
            result=self.propose();self.assertEqual('PENDING_OWNER',result['state']);self.assertFalse(result['live_verified'])
            key.assert_not_called();http.assert_not_called()
        raw=self.runner.run(TransactionContext(self.p(),Capability.READ),lambda tx:tx.get(RecordKind.OPERATION,'chat-'+self.body['request_id']))
        self.assertNotIn(self.body['prompt'],json.dumps(dict(raw.payload),default=str))
        self.assertTrue(self.service.chat_threads(self.p(),device_id='d'*64)['threads'])

    def test_thread_summary_separates_current_text_from_expired_and_old_source_history(self):
        self.propose()
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()):
            self.approve();self.assertEqual('SUCCEEDED',self.wait()['state'])
        row=self.service.chat_threads(self.p())['threads'][0]
        self.assertEqual('SUCCEEDED',row['state']);self.assertTrue(row['current_source'])
        self.assertTrue(row['text_available']);self.assertEqual(self.source[0],row['source_sha'])
        self.source[0]='f'*40
        self.assertFalse(self.service.chat_threads(self.p())['threads'][0]['current_source'])
        with patch('runtime.meta_hackathon.chat.time.monotonic',return_value=time.monotonic()+901):
            self.assertFalse(self.service.chat_threads(self.p())['threads'][0]['text_available'])
        self.assertEqual('SUCCEEDED',self.read()['state'])

    def test_thread_summaries_are_ordered_by_latest_message_not_first_creation(self):
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()):
            for request,thread in (('3'*32,'2'*32),('6'*32,'7'*32),('8'*32,'2'*32)):
                self.body.update(request_id=request,thread_id=thread)
                self.propose();self.approve();self.assertEqual('SUCCEEDED',self.wait()['state'])
        rows=self.service.chat_threads(self.p())['threads']
        self.assertEqual(['7'*32,'2'*32],[r['thread_id'] for r in rows])

    def test_exact_owner_approval_produces_one_shared_receipt_and_text(self):
        self.propose()
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as http:
            self.approve();result=self.wait()
            self.assertEqual('SUCCEEDED',result['state']);self.assertTrue(result['live_verified'])
            self.assertEqual('synthetic-chat',result['receipt']['provider_request_id'])
            self.assertIn('ADMITTED',result['reply']);self.assertEqual(1,http.call_count)
            with self.assertRaises(ValueError):self.approve()
        same=self.service.chat_thread('2'*32,self.p(),device_id='d'*64)
        self.assertEqual(result['request_id'],same['messages'][0]['request_id'])

    def test_duplicate_id_is_readback_and_changed_payload_is_denied(self):
        first=self.propose();again=self.propose()
        self.assertEqual(first['request_digest'],again['request_digest'])
        with self.assertRaises(ValueError):self.propose(prompt='changed')

    def test_read_context_uses_existing_exact_approval_and_is_rechecked_without_extra_calls(self):
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        observed=int(self.now.timestamp())
        context={'schema':'aioa.chat.read-context.v1','trust':'UNTRUSTED_READ_DATA','request_id':'a'*32,
            'operation':'github.repository','observed_at':observed,'expires_at':observed+300,
            'source_sha':self.source[0],'capsule_digest':self.source[1],
            'data_sha256':canonical_sha256({'repository':'public-fixture'}),'receipt_sha256':'e'*64,
            'data':{'repository':'public-fixture'}}
        current=[context]
        self.service.bind_chat(self.gov,lambda task:self.valid,read_context_probe=lambda request_id:current[0])
        identity={**self.identity,'actor':'LINUX_OWNER'}
        first=self.service.chat_propose(self.body,self.p(),**identity,read_context=context)
        review=self.service.chat_review(self.body['request_id'],self.p())
        self.assertEqual(first['request_digest'],review['request_digest'])
        self.assertIn('UNTRUSTED_READ_DATA',review['request_payload']['messages'][-2]['content'])
        with self.assertRaises(ValueError):
            self.service.chat_propose(self.body,self.p(),**identity,read_context={**context,'receipt_sha256':'f'*64})
        current[0]={**context,'receipt_sha256':'f'*64}
        with patch('runtime.providers.meta_model_api._https_once') as transport:
            with self.assertRaises(ValueError):self.approve(review)
            transport.assert_not_called()

    def test_configurable_total_148_preserves_history_and_unknown_credit_blocks_paid_calls(self):
        self.identity['actor']='LINUX_OWNER'
        review=self.gov.money_policy_review(self.p(),{k:148000000000 for k in
            ('task_limit','owner_provider_limit','global_limit')},request_id='hackathon-budget')
        self.gov.apply_money_policy(self.p(Capability.MANAGE),review)
        pending=self.propose(max_budget_usd='148')
        self.assertEqual('PENDING_OWNER',pending['state'])
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaisesRegex(ValueError,'CREDIT_BALANCE_NOT_BOUND'):self.approve()
            http.assert_not_called()
        self.assertEqual({},self.gov.inspect(self.p())['reservations'])

    def test_148_ceiling_with_trusted_credit_settles_synthetic_response_and_exact_receipt(self):
        self.identity['actor']='LINUX_OWNER'
        review=self.gov.money_policy_review(self.p(),{k:148000000000 for k in
            ('task_limit','owner_provider_limit','global_limit')},request_id='budget-positive')
        self.gov.apply_money_policy(self.p(Capability.MANAGE),review)
        self.service.bind_chat(self.gov,lambda task:self.valid,credit_balance_probe=lambda req:True)
        self.propose(max_budget_usd='148')
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as transport:
            self.approve();result=self.wait()
        self.assertEqual('SUCCEEDED',result['state']);self.assertEqual(1,transport.call_count)
        self.assertEqual('148',result['receipt']['binding']['budget_usd'])
        self.assertEqual('COMMITTED',self.gov.inspect(self.p())['reservations']['chat-spend-'+self.body['request_id']]['state'])

    def test_android_v1_ceiling_does_not_expand_with_linux_owner_allocation(self):
        review=self.gov.money_policy_review(self.p(),{k:148000000000 for k in
            ('task_limit','owner_provider_limit','global_limit')},request_id='budget-android')
        self.gov.apply_money_policy(self.p(Capability.MANAGE),review)
        with patch('runtime.providers.meta_model_api._https_once') as transport:
            with self.assertRaisesRegex(ValueError,'CHAT_BUDGET_INVALID'):self.propose(max_budget_usd='0.051')
            transport.assert_not_called()
        self.assertEqual([],self.service.chat_threads(self.p())['threads'])

    def test_forged_owner_and_review_digest_do_not_reach_http(self):
        self.propose()
        with patch('runtime.providers.meta_model_api._https_once') as http:
            for principal,digest in ((None,'0'*64),(replace(self.p(Capability.OWNER_APPROVAL),_seal=b'forged'),'0'*64),
                                     (self.p(Capability.OWNER_APPROVAL),'0'*64)):
                with self.assertRaises((ValueError,PermissionError)):
                    self.service.chat_approve('3'*32,digest,principal)
            http.assert_not_called()

    def test_device_isolation_precedes_read_and_duplicate_lookup(self):
        self.propose()
        for method,args in ((self.service.chat_request,('3'*32,)),(self.service.chat_thread,('2'*32,))):
            with self.assertRaises(ValueError):method(*args,self.p(),device_id='f'*64)
        with self.assertRaises(ValueError):self.service.chat_propose(self.body,self.p(),**{**self.identity,'device_id':'f'*64})

    def test_source_and_revocation_veto_approval(self):
        self.propose();review=self.service.chat_review('3'*32,self.p());self.valid=False
        with self.assertRaises(ValueError):self.approve(review)
        self.valid=True;self.source[0]='f'*40
        with self.assertRaises(ValueError):self.approve(review)

    def test_restart_preserves_request_barrier_and_drops_text_without_post(self):
        self.propose();self.service.close();self.service=self.make_service()
        self.assertEqual('UNKNOWN',self.read()['state']);self.assertIsNone(self.read()['prompt'])
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(ValueError):self.approve()
            self.propose();http.assert_not_called()

    def test_lost_provider_ack_is_unknown_and_never_retried(self):
        self.propose()
        with patch('runtime.providers.meta_model_api._https_once',side_effect=TimeoutError()) as http:
            self.approve();self.assertEqual('UNKNOWN',self.wait()['state'])
            with self.assertRaises(ValueError):self.approve()
            self.propose();self.assertEqual(1,http.call_count)

    def test_stop_pending_prevents_all_cost(self):
        self.propose();result=self.service.chat_stop('3'*32,self.p(),device_id='d'*64)
        self.assertEqual('STOPPED',result['state'])
        with self.assertRaises(ValueError):self.approve()

    def test_expired_unapproved_request_finishes_without_any_cost(self):
        self.propose();self.now+=timedelta(minutes=6)
        self.assertEqual('FAILED',self.read()['state'])
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(ValueError):self.approve()
            http.assert_not_called()

    def test_governor_veto_never_loads_key_or_dispatches(self):
        self.propose();self.gov.set_kill(self.p(Capability.MANAGE),True)
        with patch('runtime.providers.meta_model_api.load_private_key') as key,patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(ValueError):self.approve()
            key.assert_not_called();http.assert_not_called()

    def test_payload_scope_budget_and_utf8_are_closed(self):
        for updates in ({'prompt':'😀'*501},{'max_budget_usd':'0.051'},{'model_id':'gpt'}, {'approved':True}):
            with self.assertRaises(ValueError):self.propose(**updates)

if __name__=='__main__':unittest.main()
