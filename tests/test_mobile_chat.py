"""Signed mobile chat on an isolated Native Core; no paid API, real TLS or phone."""
import os,secrets,time,unittest
from pathlib import Path
from unittest.mock import patch
from test_mobile_pairing import PairingTests
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mobile_gateway import wire

class NativeChatTests(unittest.TestCase):
    setUp=PairingTests.setUp
    tearDown=PairingTests.tearDown
    owner=PairingTests.owner
    request=PairingTests.request
    call=PairingTests.call
    status=PairingTests.status
    begin=PairingTests.begin
    approve=PairingTests.approve
    paired=PairingTests.paired

    def start(self):
        self.key=Path(self.tmp.name)/'meta-key';self.key.write_text('SYNTHETIC_NATIVE_CHAT_KEY');self.key.chmod(0o600)
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True})):
            self.app=NativeMobileComposition(self.root,origin='https://host.example.org',source_probe=lambda:tuple(self.source),chat=True,key_path=self.key)
        self.app.tls_verified=True;self.app.tls_pin='sha256/'+'A'*43+'=';self.app._tls_expires=time.time()+3600
        self.app.mobile.clock=lambda:self.now

    def chat_call(self,method,suffix,session,data=None,**alter):
        path=wire.VIEW_BASE+suffix;raw=b'' if data is None else wire.canonical(data)
        proof=wire.request_proof(method,path,raw,token=session['token'],nonce=secrets.token_hex(16),issued_at=self.now,
            audience=self.app.identity.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        headers={'Authorization':'Bearer '+session['token'],'X-AIOA-Nonce':proof['nonce'],'X-AIOA-Issued-At':str(self.now),
            'X-AIOA-Audience':proof['audience'],'X-AIOA-Source-SHA':proof['source_sha'],'X-AIOA-Capsule':proof['capsule_digest'],
            'X-AIOA-Signature':self.device.sign(proof),**alter}
        status,response=self.app.mobile.handle(method,path,headers,raw)
        if status==200:
            wire.verify(self.app.identity.spki,response['signature'],response['proof'])
            self.assertEqual(wire.digest(wire.canonical(response['data'])),response['proof']['data_sha256'])
            self.assertEqual(proof['nonce'],response['proof']['nonce'])
        return status,response

    def payload(self):
        return {'schema':'aioa.mobile.chat-send.v1','thread_id':'2'*32,'request_id':'3'*32,'model_id':'muse-spark-1.3',
            'prompt':'Jaki jest stan AIOA?','max_budget_usd':'0.05'}

    def test_native_profile_exposes_only_advisory_chat_not_spend_or_execution(self):
        code,response=self.app.mobile.handle('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'a'*64},b'')
        self.assertEqual(200,code);caps=response['capabilities'];self.assertTrue(caps['chat'])
        self.assertEqual('NATIVE_ADVISORY_CHAT_V1',caps['profile'])
        for key in ('run','approve','meta_spend','native_execute','github_write','install'):self.assertFalse(caps[key])

    def test_signed_pending_and_readback_same_core_without_paid_request(self):
        _,session=self.paired()
        with patch('runtime.providers.meta_model_api._https_once') as http:
            code,response=self.chat_call('POST','/chat',session,self.payload());self.assertEqual(200,code,response)
            self.assertEqual('PENDING_OWNER',response['data']['state']);http.assert_not_called()
        code,readback=self.chat_call('GET','/chat/requests/'+'3'*32,session)
        self.assertEqual(200,code,readback);self.assertEqual(response['data']['request_digest'],readback['data']['request_digest'])

    def test_changed_source_and_signature_are_denied_before_proposal(self):
        _,session=self.paired()
        for changes in ({'X-AIOA-Source-SHA':'f'*40},{'X-AIOA-Signature':'forged'}):
            self.assertNotEqual(200,self.chat_call('POST','/chat',session,self.payload(),**changes)[0])

    def test_phone_cannot_approve_cost_even_with_valid_session(self):
        _,session=self.paired()
        for suffix in ('/chat/approve','/meta_spend','/run','/approve'):
            self.assertNotEqual(200,self.chat_call('POST',suffix,session,{'approved':True})[0])

    def test_signed_pre_admission_denial_is_exact_but_conflict_stays_uncertain(self):
        _,session=self.paired();body=self.payload()
        status,response=self.chat_call('POST','/chat',session,{**body,'prompt':'x'*2001})
        self.assertEqual(200,status,response)
        self.assertIs(response['data'].get('admitted'),False)
        self.assertEqual(body['request_id'],response['data']['request_id'])
        self.assertEqual('CHAT_PROMPT_LIMIT',response['data']['error'])
        self.assertEqual(200,self.chat_call('POST','/chat',session,body)[0])
        _,conflict=self.chat_call('POST','/chat',session,{**body,'prompt':'different payload'})
        self.assertNotIn('admitted',conflict['data'])

if __name__=='__main__':unittest.main()
