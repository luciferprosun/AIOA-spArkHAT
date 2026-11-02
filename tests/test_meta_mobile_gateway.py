"""Real existing Core records, fixture provider, ephemeral transport keys."""
import importlib
import importlib.util
import json
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec
from runtime.core_admission import AdmissionError, Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.browser_agent.offline_adapter import FIXTURE_URL
from runtime.mobile_gateway import wire


class NativePairingAdmissionTests(unittest.TestCase):
    """Hermetic OS-auth simulations; never evidence of a real owner admission."""

    def composition_type(self):
        module=importlib.import_module('runtime.meta_hackathon.runtime_adapter')
        cls=getattr(module,'NativeMobileComposition',None)
        if cls is None:self.fail('Native pairing composition is missing; fixture must stay blocked')
        return cls

    def system_metadata(self):
        import stat
        from types import SimpleNamespace
        original=Path.lstat
        def metadata(path,*args,**kwargs):
            if str(path) in ('/usr/bin/pkcheck','/usr/bin/loginctl'):
                return SimpleNamespace(st_mode=stat.S_IFREG|0o755,st_uid=0)
            return original(path,*args,**kwargs)
        return patch.object(Path,'lstat',metadata)

    def test_missing_system_operator_authentication_denies_before_core_storage(self):
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'native'
            def system(argv,**kwargs):
                if argv[0]=='/usr/bin/loginctl':
                    import os
                    return subprocess.CompletedProcess(argv,0,f'User={os.getuid()}\nRemote=no\nActive=yes\n','')
                return subprocess.CompletedProcess(argv,2,'','authentication required')
            with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                with self.assertRaises(AdmissionError):self.composition_type()(root,origin='https://host.example.org')
            self.assertFalse(root.exists(),'denied authentication created Core storage')

    def test_admitted_native_core_stays_unavailable_until_real_tls_qualification(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as directory:
            def system(argv,**kwargs):
                text=f'User={os.getuid()}\nRemote=no\nActive=yes\n' if argv[0]=='/usr/bin/loginctl' else ''
                return subprocess.CompletedProcess(argv,0,text,'')
            with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                app=self.composition_type()(Path(directory)/'native',origin='https://host.example.org',
                    source_probe=lambda:('a'*40,'b'*64))
            try:
                self.assertIs(app.core,app.missions.core)
                self.assertIs(app.core,app.runtime._memory_patch_admission)
                self.assertNotEqual('offline-fixture',app.core.local_operator(Capability.READ).scope.tenant_id)
                status,body=app.mobile.handle('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'c'*64},b'')
                self.assertEqual(200,status)
                self.assertEqual('TLS_QUALIFICATION_PENDING',body['capabilities']['remote_deployment'])
                owner=app.operator_principal()
                with self.assertRaises(wire.MobileError):app.mobile.issue_enrollment(owner,wire.Identity(ec.generate_private_key(ec.SECP256R1())).spki)
                with self.assertRaises(AdmissionError):
                    app.core.local_operator(Capability.ACTIVATE)
            finally:app.close()

    def test_native_operator_socket_request_rejects_other_uid_and_approval_flags(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as directory:
            def system(argv,**kwargs):
                text=f'User={os.getuid()}\nRemote=no\nActive=yes\n' if argv[0]=='/usr/bin/loginctl' else ''
                return subprocess.CompletedProcess(argv,0,text,'')
            with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                app=self.composition_type()(Path(directory)/'native',origin='https://host.example.org',source_probe=lambda:('a'*40,'b'*64))
            try:
                call=getattr(app,'operator_request',None)
                if call is None:self.fail('Kernel-peer-bound native operator port is missing')
                with self.assertRaises(AdmissionError):call(os.getuid()+1,{'op':'status'})
                with self.assertRaises(wire.MobileError):call(os.getuid(),{'op':'enroll','approved':True})
            finally:app.close()

    def test_failed_native_setup_releases_lease_and_preserves_the_bad_key(self):
        import os,subprocess
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'native';root.mkdir(mode=0o700)
            key=root/'host-signing-key.pem';key.write_bytes(b'not-a-private-key');key.chmod(0o600)
            def system(argv,**kwargs):
                text=f'User={os.getuid()}\nRemote=no\nActive=yes\n' if argv[0]=='/usr/bin/loginctl' else ''
                return subprocess.CompletedProcess(argv,0,text,'')
            with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                with self.assertRaises(Exception):self.composition_type()(root,origin='https://host.example.org',source_probe=lambda:('a'*40,'b'*64))
                self.assertEqual(b'not-a-private-key',key.read_bytes())
                key.unlink()  # Test-owned invalid bytes only, never a user key.
                try:app=self.composition_type()(root,origin='https://host.example.org',source_probe=lambda:('a'*40,'b'*64))
                except AdmissionError:self.fail('Failed setup retained the native runtime lease')
                app.close()


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

    def test_old_enrollment_cannot_cross_host_identity_rotation(self):
        code=self.gateway.issue_enrollment(self.owner,self.device.spki)
        self.host=wire.Identity(ec.generate_private_key(ec.SECP256R1()));self.gateway=self.make_gateway()
        data=dict(code=code,device_spki=self.device.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],
            audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        data['signature']=self.device.sign(self.gateway.enrollment_proof(data))
        self.assertEqual(401,self.gateway.handle('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))[0])

    def test_old_session_cannot_cross_host_identity_rotation(self):
        self.host=wire.Identity(ec.generate_private_key(ec.SECP256R1()));self.gateway=self.make_gateway()
        self.assertEqual(401,self.call('GET','/status')[0])

    def test_runtime_provider_drift_cannot_keep_fixture_capabilities_enabled(self):
        self.composition.manager._meta_provider.mode='LIVE'
        self.assertEqual(503,self.call('GET','/status')[0])

    def test_native_audit_mobile_records_outbox_and_reopen_share_one_chain(self):
        from datetime import datetime,timezone
        from runtime.memory_patch.audit import append_domain_event,domain_chain,require_record_audit
        from runtime.memory_patch.persistence.idempotency import OperationBinding
        from runtime.memory_patch.persistence.ports import RecordKind,TransactionContext
        self.composition.close()
        self.composition=OfflineMetaComposition(Path(self.tmp.name)/'mixed-audit',source_probe=lambda:tuple(self.source))
        self.owner=self.composition.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader=self.composition.core.local_operator(Capability.READ)
        def native(label):
            def write(tx):
                return append_domain_event(tx,OperationBinding.bind(label,'FIXTURE_METADATA_ONLY',{'fixture':label}),
                    event_id=label,proof_id=label+'-outbox',resource_id=label,before=None,after='RECORDED',
                    content_digest='e'*64,at=datetime.fromtimestamp(self.now[0],timezone.utc))
            return self.composition.runner.run(TransactionContext(self.composition.core.local_operator(Capability.COMMIT),Capability.COMMIT),write)
        native('fixture-native-before')
        self.gateway=self.make_gateway();self.token,self.session=self.enroll(self.device)
        self.assertEqual(200,self.call('GET','/status')[0]);self.assertEqual(200,self.call('POST','/session/revoke',{})[0])
        native('fixture-native-after')
        def inspect(tx):
            events=domain_chain(tx)
            session=tx.get(RecordKind.OPERATION,'mobile-session-'+wire.digest(self.token.encode()))
            self.assertEqual(session.payload_digest,require_record_audit(tx,session).content_hashes['content'])
            self.assertEqual(len(events),len(tx.scan(RecordKind.OUTBOX,limit=1024)))
            return len(events)
        count=self.composition.runner.run(TransactionContext(self.reader,Capability.READ),inspect)
        self.assertGreater(count,5)
        root=self.composition.root;self.composition.close()
        self.composition=OfflineMetaComposition(root,source_probe=lambda:tuple(self.source))
        self.reader=self.composition.core.local_operator(Capability.READ)
        self.assertEqual(count,self.composition.runner.run(TransactionContext(self.reader,Capability.READ),inspect))

    def test_maximum_history_has_bounded_signed_pages_and_no_lost_task(self):
        from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord,TransactionContext
        from runtime.meta_hackathon.contracts import BrowserTaskV1
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.mobile_gateway.service import SCHEMA
        first,_=self.preview();self.call('POST','/stop',{'task_id':first['task_id']})
        original=self.composition.missions.evidence(first['task_id'],self.reader)
        link=self.gateway._get('mobile-task-'+first['task_id'])
        all_ids={first['task_id']}
        # Seed admissible Core fixture history in one native transaction, without
        # model/tool execution. Transport READ still uses real signed requests.
        def history(tx):
            for n in range(127):
                task_id='meta-'+format(n,'032x');all_ids.add(task_id)
                task_data=dict(original['task'],task_id=task_id)
                task_data['allowed_origins']=tuple(task_data['allowed_origins'])
                task=BrowserTaskV1(**task_data)
                data=dict(original,task_id=task_id,task=task.to_dict(),task_digest=task.digest,state='STOPPED',
                    created_order=original['created_order']+n+1,provider_receipt=None,
                    browser_receipt=dict(task_digest=task.digest,source_sha=self.source[0],capsule_digest=self.source[1],
                        owner_scope_digest=original['owner_scope_digest'],content_sha256='e'*64))
                tx.insert(StoredRecord(RecordKind.OPERATION,task_id,self.composition.missions.scope,1,data))
                linked=dict(link.payload,task_id=task_id,task_digest=task.digest,created_order=data['created_order'])
                tx.insert(StoredRecord(RecordKind.OPERATION,'mobile-task-'+task_id,self.composition.missions.scope,1,linked))
        self.composition.runner.run(TransactionContext(self.composition.core.local_operator(Capability.COMMIT),Capability.COMMIT),history)
        found=set();suffix='/status'
        for _ in range(9):
            status,response=self.call('GET',suffix)
            self.assertEqual(200,status,response);self.assertLessEqual(len(wire.canonical(response)),65536)
            data=response['data'];self.assertLessEqual(len(data['missions']),16)
            self.assertEqual(128,data['total_missions'])
            ids={task['task_id'] for task in data['missions']}
            self.assertFalse(found & ids);found |= ids
            cursor=data['next_cursor']
            if cursor is None:break
            suffix='/status/pages/'+cursor
        self.assertEqual(all_ids,found)
        self.assertEqual(403,self.call('GET','/status/pages/meta-'+'f'*32)[0])


if __name__=='__main__':unittest.main()
