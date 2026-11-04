"""Native session authorization and real SQLite; all provider traffic is synthetic."""
from datetime import timedelta
import json
import os
import time
import unittest
from unittest.mock import patch

import test_mobile_chat as fixture
import test_mobile_device_console as console_fixture
from runtime.core_admission import Capability,AdmissionError
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.governor import ReservationRequest


class NativeChatSessionTests(unittest.TestCase):
    setUp=fixture.NativeChatTests.setUp
    start=fixture.NativeChatTests.start
    tearDown=fixture.NativeChatTests.tearDown
    service=console_fixture.DeviceConsoleTests.service
    tls=console_fixture.DeviceConsoleTests.tls
    console_socket=console_fixture.DeviceConsoleTests.console_socket
    activate=console_fixture.DeviceConsoleTests.activate
    redeem=console_fixture.DeviceConsoleTests.redeem
    navigation=console_fixture.DeviceConsoleTests.navigation
    def owner(self,op,**fields):
        return self.app.operator_request(os.getuid(),dict(op=op,**fields))

    def begin(self,request_id='1'*32):
        return self.owner('chat_session_start',request_id=request_id,local_money_limit_usd=None)

    def payload(self,request_id='2'*32,prompt='Cześć, porozmawiamy?'):
        return {'schema':'aioa.mobile.chat-send.v2','request_id':request_id,'thread_id':'3'*32,
            'model_id':'muse-spark-1.3','prompt':prompt}

    def send(self,request_id='2'*32,prompt='Cześć, porozmawiamy?'):
        return self.owner('chat_send',payload=self.payload(request_id,prompt))

    def response(self):
        return 200,json.dumps({'id':'synthetic-session-chat','model':'muse-spark-1.3',
            'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'Cześć! O czym chcesz porozmawiać?'}}],
            'usage':{'prompt_tokens':8,'completion_tokens':12,'total_tokens':20}}).encode()

    def wait(self,request_id='2'*32):
        for _ in range(200):
            result=self.owner('chat_request',request_id=request_id)
            if result['state']!='RUNNING':return result
            time.sleep(.01)
        self.fail('chat worker did not finish')

    def test_start_is_audited_without_paid_call_or_another_password(self):
        with patch('runtime.providers.meta_model_api._https_once') as http, \
                patch('runtime.providers.meta_model_api.load_private_key') as key, \
                patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid') as password:
            session=self.begin()
            self.assertEqual('ACTIVE',session['state'])
            self.assertIsNone(session['local_money_limit_usd'])
            self.assertEqual('OWNER_SESSION_AND_SEND',session['authorization_basis'])
            http.assert_not_called();key.assert_not_called();password.assert_not_called()
        catalog=self.owner('chat_catalog')
        self.assertEqual('LIVE_OWNER_SESSION',catalog['mode'])
        self.assertTrue(catalog['chat']);self.assertFalse(catalog['credit_only'])
        self.assertIsNone(catalog['allocation_usd'])

    def test_two_sends_run_without_per_message_approval_and_share_history(self):
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as http, \
                patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid') as password:
            self.send();first=self.wait();self.assertEqual('SUCCEEDED',first['state'])
            self.send('4'*32,'A pamiętasz moje poprzednie pytanie?')
            second=self.wait('4'*32);self.assertEqual('SUCCEEDED',second['state'])
            self.assertEqual(2,http.call_count);password.assert_not_called()
        self.assertEqual('OWNER_SESSION_AND_SEND',first['authorization']['basis'])
        self.assertEqual('1'*32,first['authorization']['session_id'])
        req=self.app.missions._chat_payloads['4'*32][1]
        self.assertIn(('user','Cześć, porozmawiamy?'),req.history)
        self.assertEqual(format(req.estimate(),'f'),req.budget_usd)
        self.assertTrue(second['live_verified']);self.assertFalse(second['save_knowledge'])

    def test_successful_conversation_does_not_open_the_failure_circuit_after_three_messages(self):
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as http:
            for index in range(6):
                request_id=format(index+10,'032x')
                self.send(request_id,'Kontynuuj rozmowę.')
                self.assertEqual('SUCCEEDED',self.wait(request_id)['state'])
            self.assertEqual(6,http.call_count)
        state=self.app.chat_governor.inspect(self.app.core.local_operator(Capability.READ))
        self.assertEqual('CLOSED',state['circuits']['meta_model_api']['state'])
        self.assertEqual(0,state['circuits']['meta_model_api']['failures'])

    def test_actual_uncertain_calls_still_open_the_circuit_and_retain_every_hold(self):
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once',side_effect=TimeoutError()) as http:
            for index in range(3):
                request_id=format(index+10,'032x');self.send(request_id)
                self.assertEqual('UNKNOWN',self.wait(request_id)['state'])
            with self.assertRaises(ValueError):self.send('f'*32)
            self.assertEqual(3,http.call_count)
        state=self.app.chat_governor.inspect(self.app.core.local_operator(Capability.READ))
        self.assertEqual('OPEN',state['circuits']['meta_model_api']['state'])
        self.assertEqual(3,len(state['reservations']))
        self.assertTrue(all(r['state']=='UNKNOWN' for r in state['reservations'].values()))

    def test_two_verified_probe_messages_recover_circuit_without_resolving_old_unknown(self):
        gov=self.app.chat_governor;reader=self.app.core.local_operator(Capability.READ)
        commit=self.app.core.local_operator(Capability.COMMIT);epoch=gov.inspect(reader)['epoch']
        for index in range(3):
            request=ReservationRequest('old-'+str(index),'old-task-'+str(index),
                'meta_model_api','muse-spark-1.3',canonical_sha256(index),1,1)
            gov.reserve(commit,request,epoch);gov.dispatch_commit(commit,request.request_id,epoch)
            gov.mark_unknown(commit,request.request_id,epoch,canonical_sha256(('old-unknown',index)))
        before=gov.inspect(reader)['reservations'];self.begin()
        with patch.object(gov,'clock',side_effect=lambda:time.time()+31), \
                patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as http:
            self.send();self.assertEqual('SUCCEEDED',self.wait()['state'])
            self.assertEqual('HALF_OPEN',gov.inspect(reader)['circuits']['meta_model_api']['state'])
            self.send('4'*32);self.assertEqual('SUCCEEDED',self.wait('4'*32)['state'])
            self.assertEqual(2,http.call_count)
            after=gov.inspect(reader)
        self.assertEqual('CLOSED',after['circuits']['meta_model_api']['state'])
        self.assertEqual(before,{key:value for key,value in after['reservations'].items() if key in before})

    def test_no_session_rejected_and_http_cannot_create_financial_session(self):
        from runtime.webapp import WebRuntimeService
        from runtime.mobile_gateway import wire
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(Exception):self.send()
            service=object.__new__(WebRuntimeService)
            service.mobile_only=True;service._mobile_console_uid=os.getuid();service.meta_owner=self.app
            for op in ('chat_session_start','chat_approve','budget_approve'):
                with self.assertRaises(wire.MobileError):service.mobile_operator_request({'op':op})
            http.assert_not_called()

    def test_unknown_and_spent_exposure_survive_unlimited_session(self):
        gov=self.app.chat_governor;reader=self.app.core.local_operator(Capability.READ)
        commit=self.app.core.local_operator(Capability.COMMIT);epoch=gov.inspect(reader)['epoch']
        request=ReservationRequest('old-unknown','old-task','meta_model_api','muse-spark-1.3','a'*64,49000000,1)
        gov.reserve(commit,request,epoch);gov.dispatch_commit(commit,request.request_id,epoch)
        gov.mark_unknown(commit,request.request_id,epoch,canonical_sha256('lost-old-reply'))
        before=gov.inspect(reader)['reservations'][request.request_id]
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()):
            self.send();self.assertEqual('SUCCEEDED',self.wait()['state'])
        after=gov.inspect(reader)
        self.assertEqual(before,after['reservations'][request.request_id])
        self.assertGreater(after['exposure']['global']['money_nano'],50000000)

    def test_unknown_response_is_readback_only_on_duplicate_send(self):
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once',side_effect=TimeoutError()) as http:
            self.send();self.assertEqual('UNKNOWN',self.wait()['state'])
            self.assertEqual('UNKNOWN',self.send()['state'])
            self.assertEqual(1,http.call_count)
            with self.assertRaises(Exception):self.send(prompt='different text')

    def test_revoke_expiry_and_source_change_prevent_new_calls(self):
        self.begin();self.owner('chat_session_stop')
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(Exception):self.send()
            self.begin('5'*32)
            now=self.app.missions.ledger.clock()
            with patch.object(self.app.missions.ledger,'clock',return_value=now+timedelta(hours=2)):
                with self.assertRaises(Exception):self.send()
            self.source[0]='f'*40
            with self.assertRaises(Exception):self.send()
            http.assert_not_called()

    def test_restart_does_not_restore_a_spending_session(self):
        self.begin();self.app.close();self.start()
        with patch('runtime.providers.meta_model_api._https_once') as http:
            self.assertNotEqual('LIVE_OWNER_SESSION',self.owner('chat_catalog')['mode'])
            with self.assertRaises(Exception):self.send()
            http.assert_not_called()

    def test_unlimited_session_keeps_kill_switch_and_unknown_reservations(self):
        self.begin();self.app.chat_governor.set_kill(self.app.core.local_operator(Capability.MANAGE),True)
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with self.assertRaises(Exception):self.send()
            http.assert_not_called()

    def test_exact_http_session_origin_and_csrf_are_required_for_direct_send(self):
        from runtime.mobile_gateway import wire
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        value={'op':'chat_send','payload':self.payload()}
        with patch('runtime.providers.meta_model_api._https_once',return_value=self.response()) as http:
            self.assertEqual(403,request('POST','/api/native-operator',value)[0])
            token=self.activate(service,request,control)
            headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
            self.begin()
            self.assertEqual(403,request('POST','/api/native-operator',{'op':'chat_session_start'},headers)[0])
            for altered in ({'Origin':'https://evil.example.org'},{'X-AIOA-Session-Token':'forged'}):
                self.assertEqual(403,request('POST','/api/native-operator',value,{**headers,**altered})[0])
            http.assert_not_called()
            code,raw=request('POST','/api/native-operator',value,headers)
            self.assertEqual(200,code,raw)
            self.assertEqual('OWNER_SESSION_AND_SEND',wire.strict_json(raw)['data']['authorization']['basis'])
            self.assertEqual('SUCCEEDED',self.wait()['state']);self.assertEqual(1,http.call_count)

    def test_wrong_uid_forged_fields_and_android_cannot_expand_session_authority(self):
        from runtime.meta_hackathon import chat_session
        from runtime.mobile_gateway import wire
        with self.assertRaises(AdmissionError):
            self.app.operator_request(os.getuid()+1,{'op':'chat_session_start','request_id':'1'*32,'local_money_limit_usd':None})
        self.begin();reader=self.app.core.local_operator(Capability.READ)
        authorization=chat_session.require_active(self.app.missions)['authorization']
        with patch('runtime.providers.meta_model_api._https_once') as http:
            for extra in ({'max_budget_usd':'0'},{'approved':True},{'operation':'github.issue.create'},
                    {'session_authorization':authorization}):
                with self.assertRaises(ValueError):self.owner('chat_send',payload={**self.payload(),**extra})
            with self.assertRaises(ValueError):
                self.app.missions.chat_propose(self.payload(),reader,device_id=self.app.identity.audience,
                    session_id='a'*32,nonce='b'*32,actor='ANDROID',session_authorization=authorization)
            with self.assertRaises(wire.MobileError):
                self.owner('chat_send',payload=self.payload(),approved=True)
            http.assert_not_called()
        catalog=self.owner('chat_catalog')
        self.assertFalse(catalog['github_write']);self.assertFalse(catalog['native_execute'])

    def test_pending_intent_after_lost_host_ack_never_auto_approves_on_replay(self):
        self.begin()
        with patch('runtime.providers.meta_model_api._https_once') as http:
            with patch('runtime.meta_hackathon.chat.approve',side_effect=ValueError('synthetic lost host ACK')):
                with self.assertRaises(ValueError):self.send()
            result=self.send()
            self.assertEqual('PENDING_OWNER',result['state']);http.assert_not_called()
        self.assertEqual({},self.app.chat_governor.inspect(self.app.core.local_operator(Capability.READ))['reservations'])

    def test_session_revocation_is_rechecked_before_credential_loading(self):
        manager=self.app.missions.manager;generate=manager.generate_meta_chat
        self.begin()
        def revoked(*args,**kwargs):
            self.owner('chat_session_stop')
            return generate(*args,**kwargs)
        with patch.object(manager,'generate_meta_chat',side_effect=revoked), \
                patch('runtime.providers.meta_model_api.load_private_key') as key, \
                patch('runtime.providers.meta_model_api._https_once') as http:
            self.send();self.assertIn(self.wait()['state'],('UNKNOWN','STOPPED'))
            key.assert_not_called();http.assert_not_called()


if __name__=='__main__':unittest.main()
