"""Real existing Core records, fixture provider, ephemeral transport keys."""
import importlib
import importlib.util
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from runtime.core_admission import AdmissionError, Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.browser_agent.offline_adapter import FIXTURE_URL
from runtime.mobile_gateway import wire


class MobileGatewayTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mobile_gateway.service'), 'gateway missing')
        self.Gateway = importlib.import_module('runtime.mobile_gateway.service').MobileGateway
        self.tmp = tempfile.TemporaryDirectory()
        self.source = list(getattr(self, 'fixture_source', ('a'*40, 'b'*64)))
        self.composition = OfflineMetaComposition(Path(self.tmp.name)/'core', delay_seconds=.15,
                                                 source_probe=lambda: tuple(self.source))
        self.now = [int(time.time())]
        self.host = wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        self.device = wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        self.gateway = self.make_gateway()
        self.owner = self.composition.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader = self.composition.core.local_operator(Capability.READ)
        self.token, self.session = self.enroll(self.device)

    def tearDown(self):
        if hasattr(self, 'composition'): self.composition.close()
        if hasattr(self, 'tmp'): self.tmp.cleanup()

    def make_gateway(self):
        return self.Gateway(self.composition.missions, identity=self.host, fixture=True, clock=lambda:self.now[0])

    def enroll(self, device):
        code = self.gateway.issue_enrollment(self.owner, device.spki)
        payload = dict(code=code, device_spki=device.spki, nonce=secrets.token_hex(16),
                       issued_at=self.now[0], audience=self.host.audience,
                       source_sha=self.source[0], capsule_digest=self.source[1])
        payload['signature'] = device.sign(self.gateway.enrollment_proof(payload))
        status, response = self.gateway.handle('POST', wire.BASE+'/enrollment/redeem', {}, wire.canonical(payload))
        self.assertEqual(200,status,response)
        self.verify_response(response, payload['nonce'], 'POST', wire.BASE+'/enrollment/redeem')
        return response['data']['token'], response['data']['session_id']

    def signed(self, method, suffix, data=None, *, device=None, token=None, nonce=None, issued_at=None):
        raw = b'' if data is None else wire.canonical(data)
        path = wire.BASE+suffix
        proof = wire.request_proof(method,path,raw,token=token or self.token,
            nonce=nonce or secrets.token_hex(16),issued_at=self.now[0] if issued_at is None else issued_at,
            audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        headers = {'Authorization':'Bearer '+(token or self.token), 'X-AIOA-Nonce':proof['nonce'],
            'X-AIOA-Issued-At':str(proof['issued_at']),'X-AIOA-Audience':proof['audience'],
            'X-AIOA-Source-SHA':proof['source_sha'],'X-AIOA-Capsule':proof['capsule_digest'],
            'X-AIOA-Signature':(device or self.device).sign(proof)}
        return method,path,headers,raw

    def call(self, method, suffix, data=None, **kw):
        args=self.signed(method,suffix,data,**kw)
        status,response=self.gateway.handle(*args)
        if status==200:self.verify_response(response,args[2]['X-AIOA-Nonce'],method,args[1])
        return status,response

    def verify_response(self,response,nonce,method,path):
        proof=response['proof']
        self.assertEqual(nonce,proof['nonce']);self.assertEqual(method,proof['method'])
        self.assertEqual(path,proof['path']);self.assertEqual(self.host.audience,proof['audience'])
        self.assertEqual(wire.digest(wire.canonical(response['data'])),proof['data_sha256'])
        self.assertEqual(self.source[0],proof['source_sha']);self.assertEqual(self.source[1],proof['capsule_digest'])
        wire.verify(self.host.spki,response['signature'],proof)

    def preview(self):
        proposal=secrets.token_hex(16)
        status,response=self.call('POST','/preview',dict(proposal_id=proposal,instruction='Przeczytaj fixture',
            mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))
        self.assertEqual(200,status,response)
        return response['data'],proposal

    def test_default_remote_deployment_blocks_code_issuance_and_requests(self):
        gateway=self.Gateway(self.composition.missions)
        with self.assertRaises(wire.MobileError):gateway.issue_enrollment(self.owner,self.device.spki)
        self.assertEqual(503,gateway.handle('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'a'*64},b'')[0])

    def test_fresh_host_proof_binds_challenge_capabilities_source_origin(self):
        status,response=self.gateway.handle('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'f'*64},b'')
        self.assertEqual(200,status)
        self.assertEqual('f'*64,response['proof']['challenge'])
        self.assertEqual('https://fixture.invalid',response['proof']['origin'])
        self.assertEqual(wire.digest(wire.canonical(response['capabilities'])),response['proof']['capabilities_sha256'])
        wire.verify(self.host.spki,response['signature'],response['proof'])
        with self.assertRaises(wire.MobileError):wire.verify(self.device.spki,response['signature'],response['proof'])
        self.assertFalse(response['capabilities']['run']);self.assertFalse(response['capabilities']['meta_spend'])

    def test_only_host_owner_can_issue_prebound_one_time_enrollment(self):
        for principal in (self.reader,None,object()):
            with self.assertRaises(AdmissionError):self.gateway.issue_enrollment(principal,self.device.spki)
        code=self.gateway.issue_enrollment(self.owner,self.device.spki,ttl=1)
        self.now[0]+=2
        p=dict(code=code,device_spki=self.device.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],
               audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        p['signature']=self.device.sign(self.gateway.enrollment_proof(p))
        self.assertEqual(401,self.gateway.handle('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(p))[0])

    def test_previews_use_same_core_without_warrant_or_effect_and_redact(self):
        result,proposal=self.preview()
        row=self.composition.missions.evidence(result['task_id'],self.reader)
        self.assertEqual(row['task_digest'],result['task_digest'])
        self.assertEqual(row['owner_scope_digest'],result['owner_scope_digest'])
        self.assertEqual('PREVIEWED',result['state']);self.assertFalse(result['verified'])
        self.assertEqual(0,self.composition.driver.read_count)
        self.assertNotIn('proposal',result);self.assertNotIn('instruction',json.dumps(result))
        status,readback=self.call('GET','/proposals/'+proposal)
        self.assertEqual(200,status);self.assertEqual(result,readback['data'])

    def test_replay_survives_gateway_restart_and_changed_body_is_denied(self):
        args=self.signed('GET','/status')
        self.assertEqual(200,self.gateway.handle(*args)[0]);self.gateway=self.make_gateway()
        self.assertEqual(409,self.gateway.handle(*args)[0])
        args=self.signed('POST','/stop',{'task_id':'meta-'+'f'*32})
        self.assertEqual(401,self.gateway.handle(*args[:3],b'{}')[0])

    def test_wrong_device_expiry_audience_and_future_are_denied(self):
        for kwargs in ({'device':self.host},{'issued_at':self.now[0]-31},{'issued_at':self.now[0]+31}):
            self.assertEqual(401,self.call('GET','/status',**kwargs)[0])
        args=self.signed('GET','/status');args[2]['X-AIOA-Audience']='0'*64
        self.assertEqual(401,self.gateway.handle(*args)[0])

    def test_new_enrollment_revokes_old_session_and_self_revoke_persists(self):
        old=self.token
        self.token,self.session=self.enroll(self.device)
        self.assertEqual(401,self.call('GET','/status',token=old)[0])
        self.assertEqual(200,self.call('POST','/session/revoke',{})[0])
        self.gateway=self.make_gateway()
        self.assertEqual(401,self.call('GET','/status')[0])

    def test_cross_device_task_status_evidence_stop_are_denied(self):
        result,_=self.preview(); other=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        token,session=self.enroll(other)
        self.assertEqual([],self.call('GET','/status',device=other,token=token)[1]['data']['missions'])
        for method,path,data in [('GET','/tasks/'+result['task_id'],None),('GET','/evidence/'+result['task_id'],None),
                                 ('POST','/stop',{'task_id':result['task_id']})]:
            self.assertEqual(403,self.call(method,path,data,device=other,token=token)[0])
        self.assertEqual('PREVIEWED',self.composition.missions.evidence(result['task_id'],self.reader)['state'])

    def test_source_drift_and_changed_task_binding_fail_closed(self):
        result,_=self.preview()
        self.source[1]='c'*64
        self.assertEqual(503,self.call('GET','/status')[0]);self.source[1]='b'*64
        self.composition.missions._change(result['task_id'],{'PREVIEWED'},'UNKNOWN',{'task_digest':'d'*64})
        self.assertEqual(503,self.call('GET','/evidence/'+result['task_id'])[0])

    def test_same_proposal_double_submit_has_no_second_mission(self):
        result,proposal=self.preview()
        self.assertEqual(409,self.call('POST','/preview',dict(proposal_id=proposal,instruction='Przeczytaj fixture',
            mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        self.assertEqual(1,len(self.composition.missions._rows()))

    def test_mobile_has_no_run_approve_write_shell_owner_or_paid_routes(self):
        for route in ('run','approve','chat','native_execute','meta_spend','github_write','owner_pairing_m12'):
            self.assertEqual(501,self.call('POST','/'+route,{})[0])
        self.assertEqual(403,self.call('POST','/preview',dict(proposal_id=secrets.token_hex(16),instruction='x',
            mode='LIVE',target_url=FIXTURE_URL))[0])
        self.assertEqual(0,self.composition.driver.read_count)

    def test_oversize_unknown_fields_and_url_injection_fail_closed(self):
        args=self.signed('POST','/preview',{'x':'x'*17000})
        self.assertEqual(413,self.gateway.handle(*args)[0])
        for data in [dict(proposal_id=secrets.token_hex(16),instruction='x',mode='OFFLINE_FIXTURE',target_url='https://evil.invalid'),
                     dict(proposal_id=secrets.token_hex(16),instruction='x',mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL,owner_approved=True)]:
            self.assertIn(self.call('POST','/preview',data)[0],(400,403))

    def test_expired_session_is_denied_even_with_fresh_valid_request_signature(self):
        self.now[0]+=601
        self.assertEqual(401,self.call('GET','/status')[0])

    def test_stolen_code_cannot_be_rebound_to_another_signing_key(self):
        code=self.gateway.issue_enrollment(self.owner,self.device.spki)
        other=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        data=dict(code=code,device_spki=other.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],
            audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        data['signature']=other.sign(self.gateway.enrollment_proof(data))
        self.assertEqual(401,self.gateway.handle('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))[0])

    def test_core_records_do_not_store_code_token_or_instruction(self):
        code=self.gateway.issue_enrollment(self.owner,self.device.spki)
        text='N1_PRIVATE_FIXTURE_INSTRUCTION_NOT_IN_AUDIT'
        self.assertEqual(200,self.call('POST','/preview',dict(proposal_id=secrets.token_hex(16),instruction=text,
            mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        state=(self.composition.root/'core-records.json').read_text()
        for secret in (code,self.token,text):self.assertNotIn(secret,state)


if __name__=='__main__':unittest.main()
