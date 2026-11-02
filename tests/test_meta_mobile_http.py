"""Mobile-shaped signed HTTP against the single existing webapp on loopback:0."""
import http.client
import importlib
import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch

import test_meta_mobile_gateway as fixture
from cryptography.hazmat.primitives.asymmetric import ec
from runtime.mobile_gateway import wire
from runtime.browser_agent.offline_adapter import FIXTURE_URL


class NativePairingHTTPTests(unittest.TestCase):
    """Real local TLS/crypto/SQLite, with synthetic OS auth and a test-only CA."""
    composition_type=fixture.NativePairingAdmissionTests.composition_type
    system_metadata=fixture.NativePairingAdmissionTests.system_metadata
    verify_response=fixture.MobileGatewayTests.verify_response
    signed=fixture.MobileGatewayTests.signed

    def test_native_tls_enrollment_status_replay_and_revoke_without_fixture_or_model(self):
        import os,ssl,subprocess,tempfile
        from datetime import datetime,timedelta,timezone
        from pathlib import Path
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.x509.oid import NameOID
        from runtime.webapp import WebRuntimeService,make_server
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.source=['a'*40,'b'*64];self.now=[int(time.time())]
            def system(argv,**kwargs):
                text=f'User={os.getuid()}\nRemote=no\nActive=yes\n' if argv[0]=='/usr/bin/loginctl' else ''
                return subprocess.CompletedProcess(argv,0,text,'')
            with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                app=self.composition_type()(root/'native',origin='https://host.example.org',source_probe=lambda:tuple(self.source))
            self.host,self.device,self.gateway=app.identity,wire.Identity(ec.generate_private_key(ec.SECP256R1())),app.mobile
            self.gateway.clock=lambda:self.now[0]
            key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'test-only native CA')]);now=datetime.now(timezone.utc)
            cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(hours=1))
                .add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName('host.example.org')]),critical=False).sign(key,hashes.SHA256()))
            pem=cert.public_bytes(serialization.Encoding.PEM);certificate=root/'tls.crt';certificate.write_bytes(pem);certificate.chmod(0o600)
            private=root/'tls.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
            service=WebRuntimeService(runtime=app.runtime,meta_missions=app.missions,meta_owner=app,mobile_gateway=app.mobile)
            server=None
            try:
                try:server=make_server('127.0.0.1',0,service,tls_certificate=certificate,tls_key=private)
                except TypeError:self.fail('Native TLS server binding is missing')
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                context=ssl.create_default_context(cadata=pem.decode())
                context.minimum_version=ssl.TLSVersion.TLSv1_3
                context.maximum_version=ssl.TLSVersion.TLSv1_3
                from runtime.core_admission import AdmissionError
                original=self.gateway._host_proof
                def stale(headers):
                    result=original(headers);result['proof']['issued_at']-=60;result['proof']['expires_at']-=60
                    result['signature']=self.host.sign(result['proof']);return result
                with patch.object(self.gateway,'_host_proof',side_effect=stale),patch('ssl.create_default_context',return_value=context):
                    with self.assertRaises(AdmissionError):app.qualify_tls(server.server_address[1])
                with patch('ssl.create_default_context',return_value=context):app.qualify_tls(server.server_address[1])
                settings=app.public_settings();self.assertTrue(settings['tls_spki_pin'].startswith('sha256/'))
                import runtime.webapp as webapp
                factory=getattr(webapp,'make_mobile_operator_server',None)
                if factory is None:self.fail('Private kernel-authenticated operator socket is missing')
                control=factory(app);control_worker=threading.Thread(target=control.serve_forever,daemon=True);control_worker.start()
                try:
                    result=webapp.mobile_operator_client(app.root,{'op':'settings'})
                    self.assertEqual(app.identity.spki,result['data']['host_spki'])
                    denied=webapp.mobile_operator_client(app.root,{'op':'enroll','approved':True})
                    self.assertFalse(denied['ok'])
                finally:control.shutdown();control.server_close();control_worker.join(3)
                def request(method,path,headers=None,body=b''):
                    import socket
                    # Independent client policy at the point of use: the probe
                    # must not configure or weaken this client's TLS context.
                    client_context=ssl.create_default_context(cadata=pem.decode())
                    client_context.minimum_version=ssl.TLSVersion.TLSv1_3
                    client_context.maximum_version=ssl.TLSVersion.TLSv1_3
                    peer=client_context.wrap_socket(socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=5),server_hostname='host.example.org')
                    connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=5);connection.sock=peer
                    try:
                        connection.request(method,path,headers={'Host':'host.example.org','Content-Type':'application/json',**(headers or {})},body=body)
                        response=connection.getresponse();raw=response.read();return response.status,raw
                    finally:connection.close()
                self.assertEqual(404,request('GET','/api/session')[0]);self.assertEqual(404,request('HEAD','/')[0])
                import socket
                idle=socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=5)
                try:
                    try:parallel=request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'f'*64})
                    except (OSError,ssl.SSLError):parallel=None
                finally:idle.close()
                self.assertIsNotNone(parallel,'An unfinished TLS handshake blocked other clients')
                self.assertEqual(200,parallel[0])
                caps=json.loads(request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'d'*64})[1])['capabilities']
                self.assertEqual('TLS_HOST_VERIFIED',caps['remote_deployment']);self.assertFalse(caps['chat']);self.assertFalse(caps['run'])
                owner=app.operator_principal();request_id=secrets.token_hex(16)
                code=self.gateway.issue_enrollment(owner,self.device.spki,native_request_id=request_id)
                with self.assertRaises(wire.MobileError):self.gateway.issue_enrollment(owner,self.device.spki,native_request_id=request_id)
                payload=dict(code=code,device_spki=self.device.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
                payload['signature']=self.device.sign(self.gateway.enrollment_proof(payload))
                status,raw=request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload));self.assertEqual(200,status,raw)
                response=json.loads(raw);self.token,self.session=response['data']['token'],response['data']['session_id']
                self.verify_response(response,payload['nonce'],'POST',wire.BASE+'/enrollment/redeem')
                self.assertEqual(401,request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload))[0])
                args=self.signed('GET','/status');status,raw=request(*args);self.assertEqual(200,status,raw);response=json.loads(raw)
                self.verify_response(response,args[2]['X-AIOA-Nonce'],'GET',wire.BASE+'/status')
                self.assertEqual('NATIVE_STATUS_READ_ONLY_V1',response['data']['mode']);self.assertEqual([],response['data']['missions'])
                self.assertEqual(409,request(*args)[0])
                self.assertEqual(501,request(*self.signed('POST','/preview',{}))[0])
                self.assertEqual(200,request(*self.signed('POST','/session/revoke',{}))[0])
                self.assertEqual(401,request(*self.signed('GET','/status'))[0])
                # A second, unrevoked session and an unused code survive storage
                # reopen but cannot authenticate a different native Core instance.
                fresh=self.gateway.issue_enrollment(app.operator_principal(),self.device.spki,native_request_id=secrets.token_hex(16))
                payload.update(code=fresh,nonce=secrets.token_hex(16));payload['signature']=self.device.sign(self.gateway.enrollment_proof(payload))
                status,raw=request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload));self.assertEqual(200,status,raw)
                self.token,self.session=json.loads(raw)['data']['token'],json.loads(raw)['data']['session_id']
                unused=self.gateway.issue_enrollment(app.operator_principal(),self.device.spki,native_request_id=secrets.token_hex(16))
                old_spki=app.identity.spki
                server.shutdown();server.server_close();worker.join(3);app.close()
                with self.system_metadata(),patch('runtime.meta_hackathon.runtime_adapter.subprocess.run',side_effect=system):
                    app=self.composition_type()(root/'native',origin='https://host.example.org',source_probe=lambda:tuple(self.source))
                self.host,self.gateway=app.identity,app.mobile;self.gateway.clock=lambda:self.now[0]
                self.assertEqual(old_spki,app.identity.spki)
                old=self.gateway._get('mobile-session-'+wire.digest(self.token.encode()))
                self.assertFalse(old.payload['revoked'])
                service=WebRuntimeService(runtime=app.runtime,meta_missions=app.missions,meta_owner=app,mobile_gateway=app.mobile)
                server=make_server('127.0.0.1',0,service,tls_certificate=certificate,tls_key=private)
                worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
                with patch('ssl.create_default_context',return_value=context):app.qualify_tls(server.server_address[1])
                self.assertEqual(401,request(*self.signed('GET','/status'))[0])
                payload.update(code=unused,nonce=secrets.token_hex(16));payload['signature']=self.device.sign(self.gateway.enrollment_proof(payload))
                self.assertEqual(401,request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload))[0])
                expiring=self.gateway.issue_enrollment(app.operator_principal(),self.device.spki,native_request_id=secrets.token_hex(16))
                self.now[0]+=301
                payload.update(code=expiring,nonce=secrets.token_hex(16),issued_at=self.now[0]);payload['signature']=self.device.sign(self.gateway.enrollment_proof(payload))
                self.assertEqual(401,request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload))[0])
                fresh=self.gateway.issue_enrollment(app.operator_principal(),self.device.spki,native_request_id=secrets.token_hex(16))
                payload.update(code=fresh,nonce=secrets.token_hex(16));payload['signature']=self.device.sign(self.gateway.enrollment_proof(payload))
                status,raw=request('POST',wire.BASE+'/enrollment/redeem',body=wire.canonical(payload));self.assertEqual(200,status,raw)
                self.token,self.session=json.loads(raw)['data']['token'],json.loads(raw)['data']['session_id']
                self.now[0]+=601
                self.assertEqual(401,request(*self.signed('GET','/status'))[0])
                self.source[1]='e'*64
                self.assertEqual(503,request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'d'*64})[0])
                self.source[1]='b'*64;app._auth_deadline=time.monotonic()-1
                self.assertEqual(503,request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'d'*64})[0])
                idle=socket.create_connection(('127.0.0.1',server.server_address[1]),timeout=5)
                stopped=threading.Event()
                def shutdown():server.shutdown();stopped.set()
                closer=threading.Thread(target=shutdown,daemon=True);closer.start()
                try:self.assertTrue(stopped.wait(2),'Unfinished TLS blocked bounded shutdown')
                finally:idle.close();closer.join(3)
            finally:
                if server is not None:server.shutdown();server.server_close();worker.join(3)
                app.close()


class MobileHTTPTests(unittest.TestCase):
    make_gateway=fixture.MobileGatewayTests.make_gateway
    enroll=fixture.MobileGatewayTests.enroll
    signed=fixture.MobileGatewayTests.signed
    verify_response=fixture.MobileGatewayTests.verify_response
    preview=fixture.MobileGatewayTests.preview

    def setUp(self):
        fixture.MobileGatewayTests.setUp(self)
        from runtime.webapp import WebRuntimeService, make_server
        self.service=WebRuntimeService(runtime=self.composition.runtime,meta_missions=self.composition.missions,
            meta_owner=self.composition,mobile_gateway=self.gateway)
        self.server=make_server('127.0.0.1',0,service=self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        if hasattr(self,'server'):
            self.server.shutdown();self.server.server_close();self.thread.join(3)
        fixture.MobileGatewayTests.tearDown(self)

    def request(self,method,path,headers,body):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=8)
        try:
            connection.request(method,path,body=body,headers={'Content-Type':'application/json',**headers})
            response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()

    def call(self,method,suffix,data=None,**kw):
        args=self.signed(method,suffix,data,**kw)
        status,response=self.request(*args)
        if status==200:self.verify_response(response,args[2]['X-AIOA-Nonce'],method,args[1])
        return status,response

    def test_http_enrollment_existing_core_run_receipt_stop_and_replay(self):
        status,proof=self.request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'e'*64},b'')
        self.assertEqual(200,status);wire.verify(self.host.spki,proof['signature'],proof['proof'])
        self.device=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        code=self.gateway.issue_enrollment(self.owner,self.device.spki)
        data=dict(code=code,device_spki=self.device.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],
            audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        data['signature']=self.device.sign(self.gateway.enrollment_proof(data))
        status,enrolled=self.request('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))
        self.assertEqual(200,status);self.verify_response(enrolled,data['nonce'],'POST',wire.BASE+'/enrollment/redeem')
        self.assertEqual(401,self.request('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))[0])
        self.token,self.session=enrolled['data']['token'],enrolled['data']['session_id']
        task,_=self.preview();raw=self.composition.missions.evidence(task['task_id'],self.reader)
        self.composition.missions.run(task['task_id'],raw['preview_digest'],self.owner)
        for _ in range(100):
            result=self.call('GET','/evidence/'+task['task_id'])[1]['data']
            if result['state']!='RUNNING':break
            time.sleep(.02)
        self.assertEqual('OFFLINE_FIXTURE',result['state']);self.assertFalse(result['verified'])
        self.assertEqual(task['task_digest'],result['task_digest'])
        self.assertEqual(task['owner_scope_digest'],result['owner_scope_digest'])
        host_result=self.composition.missions.evidence(task['task_id'],self.reader)
        self.assertTrue(host_result['result']['core_warrant_consumed'])
        self.assertEqual(host_result['browser_receipt']['content_sha256'],result['receipt']['content_sha256'])
        self.assertEqual(1,self.composition.driver.read_count)
        next_task,_=self.preview()
        args=self.signed('POST','/stop',{'task_id':next_task['task_id']})
        self.assertEqual('STOPPED',self.request(*args)[1]['data']['state'])
        self.assertEqual(409,self.request(*args)[0]);self.assertEqual(1,self.composition.driver.read_count)
        self.evidence_summary={'schema':'aioa.mobile.fixture-demo.v1','status':'HOST_GATEWAY_MOBILE_FIXTURE_PASS',
            'task_id':task['task_id'],'task_digest':task['task_digest'],'source_sha':task['source_sha'],
            'capsule_digest':task['capsule_digest'],'owner_scope_digest':task['owner_scope_digest'],
            'model_id':result['model_id'],'provider_id':result['provider_id'],'receipt':result['receipt'],
            'core_warrant_consumed':True,'fixture_reads':1,'signature_verification':'PASS',
            'second_task_stop':'STOPPED','replay_http_status':409,'verified':False,'live_verified':False,
            'phone_paired':False,'paid_calls':0,'public_browser_calls':0,'listener':'LOOPBACK_DYNAMIC_TEST_ONLY'}

    def test_http_csrf_cors_wrong_host_duplicate_header_and_loopback_token_are_denied(self):
        for headers in ({'Origin':'https://evil.invalid'},{'Sec-Fetch-Site':'cross-site'}, {'Host':'evil.invalid'}):
            args=self.signed('GET','/status');args[2].update(headers)
            self.assertEqual(403,self.request(*args)[0])
        self.assertEqual(401,self.request('GET',wire.BASE+'/status',{'X-AIOA-Session-Token':self.service.csrf_token},b'')[0])
        args=self.signed('GET','/status')
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=8)
        try:
            conn.putrequest('GET',args[1])
            for k,v in args[2].items():conn.putheader(k,v)
            conn.putheader('X-AIOA-Nonce',args[2]['X-AIOA-Nonce']);conn.endheaders()
            self.assertEqual(400,conn.getresponse().status)
        finally:conn.close()

    def test_lost_preview_ack_only_reads_back_and_double_submit_is_denied(self):
        proposal=secrets.token_hex(16)
        body=dict(proposal_id=proposal,instruction='Przeczytaj',mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL)
        args=self.signed('POST','/preview',body)
        self.assertEqual(200,self.request(*args)[0]) # ACK intentionally discarded by client
        self.assertEqual(409,self.request(*args)[0])
        status,found=self.call('GET','/proposals/'+proposal)
        self.assertEqual(200,status);self.assertEqual('PREVIEWED',found['data']['state'])
        self.assertEqual(1,len(self.composition.missions._rows()));self.assertEqual(0,self.composition.driver.read_count)

    def test_unknown_after_native_restart_remains_unknown_after_stop(self):
        task,_=self.preview()
        self.composition.missions.close()
        module=importlib.import_module('runtime.meta_hackathon.mission_service')
        restarted=module.MissionService(self.composition.ledger,self.composition.manager,self.composition.browser,
                                        lambda:tuple(self.source))
        self.composition.missions=restarted
        self.gateway=self.make_gateway();self.service.mobile_gateway=self.gateway;self.service.meta_missions=restarted
        self.assertEqual('UNKNOWN',self.call('GET','/evidence/'+task['task_id'])[1]['data']['state'])
        self.assertEqual('UNKNOWN',self.call('POST','/stop',{'task_id':task['task_id']})[1]['data']['state'])
        self.assertEqual(0,self.composition.driver.read_count)

    def test_crash_between_core_preview_and_link_stays_unknown_without_retry(self):
        proposal=secrets.token_hex(16)
        real=self.composition.missions.preview
        def crash(*args):
            real(*args);raise OSError('simulated ACK loss; no secrets')
        with patch.object(self.composition.missions,'preview',side_effect=crash):
            self.assertEqual(503,self.call('POST','/preview',dict(proposal_id=proposal,instruction='x',
                mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        self.assertEqual('UNKNOWN',self.call('GET','/proposals/'+proposal)[1]['data']['state'])
        self.assertEqual(409,self.call('POST','/preview',dict(proposal_id=proposal,instruction='x',
            mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        self.assertEqual(1,len(self.composition.missions._rows()))

    def test_wrong_receipt_is_rejected_not_promoted_to_verified(self):
        task,_=self.preview()
        self.composition.missions._change(task['task_id'],{'PREVIEWED'},'UNKNOWN',
            {'browser_receipt':{'task_digest':'0'*64,'source_sha':self.source[0]}})
        self.assertEqual(503,self.call('GET','/evidence/'+task['task_id'])[0])

    def test_http_header_names_are_case_insensitive(self):
        args=self.signed('GET','/status')
        self.assertEqual(200,self.request(args[0],args[1],{k.lower():v for k,v in args[2].items()},args[3])[0])

    def test_nonce_barrier_survives_complete_core_storage_reopen(self):
        args=self.signed('GET','/status');self.assertEqual(200,self.request(*args)[0])
        root=self.composition.root;self.composition.close()
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        self.composition=OfflineMetaComposition(root,source_probe=lambda:tuple(self.source))
        self.gateway=self.make_gateway()
        self.service.mobile_gateway=self.gateway;self.service.meta_missions=self.composition.missions
        self.assertEqual(409,self.request(*args)[0]);self.assertEqual(200,self.call('GET','/status')[0])

    def test_crash_after_host_approval_before_worker_dispatch_stays_unknown(self):
        task,_=self.preview();raw=self.composition.missions.evidence(task['task_id'],self.reader)
        with patch('runtime.meta_hackathon.mission_service.threading.Thread'):
            run=self.composition.missions.run(task['task_id'],raw['preview_digest'],self.owner)
            self.assertEqual('RUNNING',run['state']);self.composition.missions.close()
        module=importlib.import_module('runtime.meta_hackathon.mission_service')
        self.composition.missions=module.MissionService(self.composition.ledger,self.composition.manager,
            self.composition.browser,lambda:tuple(self.source))
        self.gateway=self.make_gateway();self.service.mobile_gateway=self.gateway
        self.assertEqual('UNKNOWN',self.call('GET','/evidence/'+task['task_id'])[1]['data']['state'])
        self.assertEqual(0,self.composition.driver.read_count)


if __name__=='__main__':unittest.main()
