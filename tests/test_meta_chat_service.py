"""Real local Core transactions; all provider HTTP is synthetic and patched."""
from dataclasses import replace
from datetime import datetime, timezone
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

    def test_payload_scope_budget_and_utf8_are_closed(self):
        for updates in ({'prompt':'😀'*501},{'max_budget_usd':'0.051'},{'model_id':'gpt'}, {'approved':True}):
            with self.assertRaises(ValueError):self.propose(**updates)

if __name__=='__main__':unittest.main()
