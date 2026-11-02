"""Isolated Core/SQLite pairing; OS auth and TLS are synthetic, never phone LIVE."""
import os
import secrets
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec
from runtime.core_admission import AdmissionError
from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mobile_gateway import wire


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/'core'
        self.source=['a'*40,'b'*64];self.now=int(time.time())
        self.device=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        self.start()

    def start(self):
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True})):
            self.app=NativeMobileComposition(self.root,origin='https://host.example.org',source_probe=lambda:tuple(self.source))
        self.app.tls_verified=True;self.app.tls_pin='sha256/'+'A'*43+'='
        self.app._tls_expires=time.time()+3600;self.app.mobile.clock=lambda:self.now

    def tearDown(self):
        self.app.close();self.tmp.cleanup()

    def owner(self,op,**fields):
        try:return self.app.operator_request(os.getuid(),dict(op=op,**fields))
        except wire.MobileError as exc:self.fail('Expected owner operation '+op+' success, got '+str(exc.status))

    def request(self,path,device=None,**fields):
        device=device or self.device
        value=dict(schema='aioa.mobile.pairing-request.v1',device_spki=device.spki,
            nonce=secrets.token_hex(16),issued_at=self.now,audience=self.app.identity.audience,
            origin=self.app.origin,source_sha=self.source[0],capsule_digest=self.source[1],**fields)
        value['signature']=device.sign(dict(value,method='POST',path=wire.BASE+path))
        return value

    def call(self,path,value=None,**fields):
        value=value or self.request(path,**fields)
        code,result=self.app.mobile.handle('POST',wire.BASE+path,{},wire.canonical(value))
        if code==200:
            wire.verify(self.app.identity.spki,result['signature'],result['proof'])
            self.assertEqual(wire.digest(wire.canonical(value)),result['proof']['request_sha256'])
            self.assertEqual(wire.digest(wire.canonical(result['data'])),result['proof']['data_sha256'])
        return code,result

    def status(self,session):
        path=wire.BASE+'/status';nonce=secrets.token_hex(16)
        proof=wire.request_proof('GET',path,b'',token=session['token'],nonce=nonce,
            issued_at=self.now,audience=self.app.identity.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        headers={'Authorization':'Bearer '+session['token'],'X-AIOA-Nonce':nonce,
            'X-AIOA-Issued-At':str(self.now),'X-AIOA-Audience':self.app.identity.audience,
            'X-AIOA-Source-SHA':self.source[0],'X-AIOA-Capsule':self.source[1],
            'X-AIOA-Signature':self.device.sign(proof)}
        return self.app.mobile.handle('GET',path,headers,b'')

    def begin(self):
        invite=self.owner('pairing_invite')
        value=self.request('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name='Test phone')
        code,result=self.call('/pairing/begin',value);self.assertEqual(200,code,result)
        return value,result['data']

    def approve(self,data):
        return self.owner('pairing_approve',**{k:data[k] for k in ('request_id','request_digest','sas')})

    def paired(self):
        _,data=self.begin();self.approve(data)
        code,result=self.call('/pairing/complete',request_id=data['request_id']);self.assertEqual(200,code,result)
        self.assertEqual(200,self.status(result['data'])[0])
        return data,result['data']

    def test_invite_signed_public_and_exact_owner_approval_required(self):
        value,data=self.begin();packet=value['invite']
        wire.verify(self.app.identity.spki,packet['signature'],packet['invite'])
        self.assertNotIn('token',wire.canonical(packet).decode())
        self.assertEqual('PENDING',data['state'])
        self.assertEqual(403,self.call('/pairing/complete',request_id=data['request_id'])[0])
        with self.assertRaises(wire.MobileError):
            self.app.operator_request(os.getuid(),dict(op='pairing_approve',request_id=data['request_id'],request_digest='f'*64,sas=data['sas']))
        self.approve(data)
        self.assertEqual('APPROVED',self.call('/pairing/status',request_id=data['request_id'])[1]['data']['state'])

    def test_forged_expired_invite_and_wrong_origin_denied(self):
        invite=self.owner('pairing_invite');invite['invite']['origin']='https://evil.example.org'
        self.assertEqual(401,self.call('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name='Phone')[0])
        invite=self.owner('pairing_invite');self.now+=301
        self.assertEqual(401,self.call('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name='Phone')[0])

    def test_replayed_begin_and_nonce_deny_with_signed_readback(self):
        value,data=self.begin()
        self.assertEqual(409,self.call('/pairing/begin',value)[0])
        request=self.request('/pairing/status',request_id=data['request_id'])
        self.assertEqual(200,self.call('/pairing/status',request)[0])
        self.assertEqual(409,self.call('/pairing/status',request)[0])
        self.assertEqual('PENDING',self.call('/pairing/status',request_id=data['request_id'])[1]['data']['state'])

    def test_substituted_key_cannot_poll_or_complete(self):
        _,data=self.begin();other=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        for path in ('/pairing/status','/pairing/complete'):
            self.assertEqual(401,self.call(path,self.request(path,device=other,request_id=data['request_id']))[0])

    def test_duplicate_approval_does_not_issue_second_binding(self):
        _,data=self.begin();self.approve(data)
        with self.assertRaises(wire.MobileError) as caught:self.app.operator_request(os.getuid(),dict(op='pairing_approve',**{k:data[k] for k in ('request_id','request_digest','sas')}))
        self.assertEqual(409,caught.exception.status)
        self.assertEqual(1,len(self.owner('pairing_list')['devices']))

    def test_concurrent_begin_consumes_one_invite(self):
        invite=self.owner('pairing_invite')
        values=[self.request('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name='Phone') for _ in range(2)]
        with ThreadPoolExecutor(2) as pool:codes=list(pool.map(lambda v:self.call('/pairing/begin',v)[0],values))
        self.assertEqual([200,409],sorted(codes))

    def test_completed_ack_loss_readback_and_fresh_reconnect(self):
        data,session=self.paired()
        self.assertEqual('COMPLETED',self.call('/pairing/status',request_id=data['request_id'])[1]['data']['state'])
        self.assertEqual(409,self.call('/pairing/complete',request_id=data['request_id'])[0])
        code,response=self.call('/session/challenge',device_id=data['device_id']);self.assertEqual(200,code,response)
        challenge=response['data']
        request=self.request('/session/reconnect',**{k:challenge[k] for k in ('device_id','challenge_id','challenge_nonce')})
        code,response=self.call('/session/reconnect',request);self.assertEqual(200,code,response)
        self.assertNotEqual(session['session_id'],response['data']['session_id'])
        self.assertEqual(409,self.call('/session/reconnect',request)[0])
        self.assertNotEqual(200,self.status(session)[0])

    def test_restart_preserves_binding_but_rejects_old_challenge(self):
        data,_=self.paired();old=self.call('/session/challenge',device_id=data['device_id'])[1]['data']
        self.app.close();self.source=['c'*40,'d'*64];self.start()
        self.assertEqual(401,self.call('/session/reconnect',**{k:old[k] for k in ('device_id','challenge_id','challenge_nonce')})[0])
        code,response=self.call('/session/challenge',device_id=data['device_id']);self.assertEqual(200,code,response)
        fresh=response['data']
        self.assertEqual(200,self.call('/session/reconnect',**{k:fresh[k] for k in ('device_id','challenge_id','challenge_nonce')})[0])

    def test_revoke_denies_existing_session_and_future_challenge(self):
        data,session=self.paired();self.owner('pairing_revoke',device_id=data['device_id'])
        self.assertEqual(403,self.call('/session/challenge',device_id=data['device_id'])[0])
        self.assertNotEqual(200,self.status(session)[0])
        self.assertEqual('REVOKED',self.call('/pairing/status',request_id=data['request_id'])[1]['data']['state'])

    def test_http_cannot_approve_or_accept_caller_operator_flag(self):
        self.assertNotEqual(200,self.call('/pairing/approve',request_id='a'*32)[0])
        with self.assertRaises(AdmissionError):self.app.operator_request(os.getuid()+1,{'op':'pairing_invite'})
        with self.assertRaises(wire.MobileError):self.app.operator_request(os.getuid(),{'op':'pairing_invite','operator_approved':True})

    def test_source_origin_audience_substitution_denied(self):
        for field,bad in [('source_sha','e'*40),('origin','https://evil.example.org'),('audience','f'*64)]:
            invite=self.owner('pairing_invite');request=self.request('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name='Phone')
            request[field]=bad;unsigned={k:v for k,v in request.items() if k!='signature'}
            request['signature']=self.device.sign(dict(unsigned,method='POST',path=wire.BASE+'/pairing/begin'))
            self.assertNotEqual(200,self.call('/pairing/begin',request)[0])

    def test_request_shape_and_name_bounds_fail_closed(self):
        for name in ('','a'*65,'phone\n'):
            invite=self.owner('pairing_invite')
            self.assertEqual(400,self.call('/pairing/begin',invite=invite,request_id=secrets.token_hex(16),device_name=name)[0])

    def test_reconnect_rotates_bounded_records_over_128_app_starts(self):
        data,session=self.paired()
        for index in range(130):
            self.now+=31
            code,response=self.call('/session/challenge',device_id=data['device_id'])
            self.assertEqual(200,code,(index,response))
            challenge=response['data']
            code,response=self.call('/session/reconnect',**{k:challenge[k] for k in ('device_id','challenge_id','challenge_nonce')})
            self.assertEqual(200,code,(index,response))
        self.assertEqual(1,len(self.owner('pairing_list')['devices']))

    def test_new_challenge_invalidates_prior_challenge(self):
        data,_=self.paired()
        old=self.call('/session/challenge',device_id=data['device_id'])[1]['data']
        self.call('/session/challenge',device_id=data['device_id'])
        self.assertNotEqual(200,self.call('/session/reconnect',**{k:old[k] for k in ('device_id','challenge_id','challenge_nonce')})[0])
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind
        for _ in range(3):
            fresh=self.call('/session/challenge',device_id=data['device_id'])[1]['data']
            self.assertEqual(200,self.call('/session/reconnect',**{k:fresh[k] for k in ('device_id','challenge_id','challenge_nonce')})[0])
        counts=self.app.mobile._run(Capability.READ,lambda tx:[len(tx.scan(RecordKind.OPERATION,limit=128,states=(state,)))
            for state in ('MOBILE_DEVICE','MOBILE_SESSION','MOBILE_RECONNECT_CHALLENGE')])
        self.assertEqual([1,1,1],counts)

    def test_legacy_operator_revoke_also_revokes_durable_binding(self):
        data,_=self.paired();self.owner('revoke',device_spki=self.device.spki)
        self.assertEqual(403,self.call('/session/challenge',device_id=data['device_id'])[0])

    def test_unknown_commit_ack_reads_completed_without_repeating_effect(self):
        from runtime.memory_patch.persistence import ports
        _,data=self.begin();self.approve(data)
        original=ports.LocalCoreTransaction.commit
        def lost_ack(transaction):
            original(transaction)
            raise OSError('synthetic lost commit ACK')
        with patch.object(ports.LocalCoreTransaction,'commit',lost_ack):
            code,response=self.call('/pairing/complete',request_id=data['request_id'])
        self.assertEqual(503,code);self.assertFalse(response['automatic_retry'])
        self.assertEqual('COMPLETED',self.call('/pairing/status',request_id=data['request_id'])[1]['data']['state'])
        self.assertEqual(409,self.call('/pairing/complete',request_id=data['request_id'])[0])

    def test_expired_challenge_and_wrong_host_binding_deny(self):
        data,_=self.paired();challenge=self.call('/session/challenge',device_id=data['device_id'])[1]['data']
        self.now+=61
        self.assertEqual(401,self.call('/session/reconnect',**{k:challenge[k] for k in ('device_id','challenge_id','challenge_nonce')})[0])
        self.app.close()
        # Public origin change is not authorized by a preserved local key.
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True})):
            self.app=NativeMobileComposition(self.root,origin='https://other.example.org',source_probe=lambda:tuple(self.source))
        self.app.tls_verified=True;self.app.tls_pin='sha256/'+'A'*43+'=';self.app._tls_expires=time.time()+3600
        self.app.mobile.clock=lambda:self.now
        self.assertEqual(401,self.call('/session/challenge',device_id=data['device_id'])[0])

    def test_future_skew_nonce_remains_replay_blocked_through_acceptance_window(self):
        data,_=self.paired()
        request=self.request('/session/challenge',device_id=data['device_id'])
        request['issued_at']=self.now+30
        request['signature']=self.device.sign(dict({k:v for k,v in request.items() if k!='signature'},method='POST',path=wire.BASE+'/session/challenge'))
        self.assertEqual(200,self.call('/session/challenge',request)[0])
        self.now+=31
        self.assertEqual(409,self.call('/session/challenge',request)[0])
        self.now+=30
        self.assertEqual(401,self.call('/session/challenge',request)[0])
        self.assertEqual(200,self.call('/session/challenge',device_id=data['device_id'])[0])

    def test_nonce_window_rate_limit_recovers_after_window_expires(self):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mobile_gateway.service import plain
        data,_=self.paired()
        def fill(tx):
            key='mobile-device-'+data['device_id'];row=tx.get(RecordKind.OPERATION,key)
            record=plain(row.payload);record.pop('schema')
            record['recent_nonces']=[{'nonce':format(index,'032x'),'expires_at':self.now+60} for index in range(128)]
            self.app.mobile._record(tx,key,record,row,at=self.now)
        self.app.mobile._run(Capability.COMMIT,fill)
        self.assertEqual(429,self.call('/session/challenge',device_id=data['device_id'])[0])
        self.now+=61
        self.assertEqual(200,self.call('/session/challenge',device_id=data['device_id'])[0])

    def test_expired_operator_cannot_issue_session_or_approve(self):
        data,_=self.paired();self.app._auth_deadline=0
        self.assertEqual(503,self.call('/session/challenge',device_id=data['device_id'])[0])
        with self.assertRaises(AdmissionError):self.app.operator_request(os.getuid(),{'op':'pairing_invite'})
