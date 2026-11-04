"""Private socket bootstrap and same-Core console; synthetic OS auth only."""
import os
import threading
import unittest
import ssl
import socket
import http.client
from datetime import datetime,timedelta,timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from unittest.mock import patch

import test_mobile_pairing as pairing_fixture
from runtime.mobile_gateway import wire
from runtime.core_admission import AdmissionError
from runtime.webapp import WebRuntimeService, make_mobile_operator_server, mobile_operator_client,make_server


class DeviceConsoleTests(unittest.TestCase):
    setUp = pairing_fixture.PairingTests.setUp
    start = pairing_fixture.PairingTests.start
    tearDown = pairing_fixture.PairingTests.tearDown
    navigation={'Origin':'null','Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate',
        'Sec-Fetch-Dest':'document','Content-Type':'application/x-www-form-urlencoded'}

    def redeem(self,request,grant):
        return request('POST','/devices',('delivery='+grant['delivery']).encode(),self.navigation)

    def activate(self,service,request,control):
        grant=control({'op':'console'})['data']
        code,raw=self.redeem(request,grant)
        self.assertEqual(200,code,raw)
        return service.csrf_token

    def service(self):
        return WebRuntimeService(runtime=self.app.runtime,meta_missions=self.app.missions,
            meta_owner=self.app,mobile_gateway=self.app.mobile)

    def console_socket(self,service):
        server=make_mobile_operator_server(self.app,service=service)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(worker.join,3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return lambda body:mobile_operator_client(self.app.root,body)

    def test_http_transport_has_no_owner_before_kernel_bootstrap(self):
        service=self.service()
        with self.assertRaises(wire.MobileError):service.mobile_operator_request({'op':'pairing_list'})

    def test_busy_http_read_lock_is_bounded_before_core_dispatch(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        service.lock.acquire()
        try:
            with patch.object(service,'mobile_operator_request') as dispatch:
                code,raw=request('POST','/api/native-operator',{
                    'op':'tool_read','request_id':'c'*32,'operation':'github.repository'},headers)
                self.assertEqual(409,code,raw)
                self.assertFalse(wire.strict_json(raw)['automatic_retry'])
                dispatch.assert_not_called()
        finally:service.lock.release()
        self.assertIsNone(self.app.mobile._get('native-tool-read-'+'c'*32))

    def test_http_read_timeout_has_durable_unknown_readback_without_dispatch_retry(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        with patch('runtime.mcp_bridge.native_read.read',side_effect=ValueError('TOOL_READ_TIMEOUT')) as read:
            code,raw=request('POST','/api/native-operator',{
                'op':'tool_read','request_id':'c'*32,'operation':'github.repository'},headers)
            self.assertEqual(503,code,raw)
            self.assertFalse(wire.strict_json(raw)['automatic_retry'])
            code,raw=request('POST','/api/native-operator',{'op':'tool_readback','request_id':'c'*32},headers)
            self.assertEqual(200,code,raw)
            data=wire.strict_json(raw)['data']
            self.assertEqual('UNKNOWN',data['state'])
            self.assertEqual('TOOL_READ_TIMEOUT',data['error_code'])
            self.assertNotIn('receipt',data)
            self.assertEqual(1,read.call_count)

    def test_private_socket_uses_longer_deadline_only_for_bounded_tool_read(self):
        service=self.service();control=self.console_socket(service)
        actual=socket.socket;peers=[];test_thread=threading.get_ident()
        def tracked(*args,**kwargs):
            peer=actual(*args,**kwargs)
            if threading.get_ident()==test_thread:peers.append(peer)
            return peer
        with patch.object(socket,'socket',side_effect=tracked),patch('runtime.mcp_bridge.native_read.read',return_value={
                'operation':'git.status','data':{'text':''},'transport':'FIXTURE_NOT_LIVE'}):
            self.assertTrue(control({'op':'status'})['ok'])
            self.assertTrue(control({'op':'tool_read','request_id':'c'*32,'operation':'git.status'})['ok'])
            self.assertTrue(control({'op':'tool_readback','request_id':'c'*32})['ok'])
        self.assertEqual([10,30,10],[peer.gettimeout() for peer in peers])

    def test_cosmic_public_assets_load_without_granting_operator_authority(self):
        service=self.service()
        request=self.tls(service)
        for asset in ('/cosmic_tokens.css','/cosmic_space_grotesk.ttf',
                '/cosmic_manrope.ttf','/cosmic_ibm_plex_mono.ttf','/cosmic_fonts_ofl.txt'):
            with self.subTest(asset=asset):
                code,raw=request('GET',asset)
                self.assertEqual(200,code)
                self.assertTrue(raw)
        self.assertNotEqual(200,request('GET','/host-signing-key.pem')[0])
        self.assertEqual(403,request('POST','/api/native-operator',b'{"op":"pairing_list"}')[0])

    def test_mobile_tls_responses_explicitly_close_connections(self):
        # OkHttp pools a framed HTTP/1.0 response without an explicit close
        # header. With retries disabled, the following pairing POST then sees
        # EOF instead of reaching Core. Cover success and pre-dispatch denials.
        request=self.tls(self.service())
        cases=(('GET','/api/mobile/v1/capabilities',None,
                {'X-AIOA-Challenge':'a'*64},200),
               ('GET','/devices',None,{},200),
               ('POST','/api/mobile/v1/pairing/begin',{}, {},400),
               ('POST','/api/native-operator',{'op':'pairing_list'}, {},403),
               ('GET','/api/session',None,{},404))
        for method,path,body,headers,expected in cases:
            with self.subTest(method=method,path=path):
                self.assertEqual(expected,request(method,path,body,headers)[0])
                self.assertEqual('close',request.response_headers.get('Connection'))

    def test_kernel_bootstrap_enables_only_pairing_ops_and_rotates_transport(self):
        service=self.service();request=self.console_socket(service)
        first=request({'op':'console'})
        self.assertTrue(first['ok'],first)
        self.assertEqual({'delivery','url'},set(first['data']))
        self.assertNotEqual(service.csrf_token,first['data']['delivery'])
        self.assertEqual(self.app.origin+'/devices',first['data']['url'])
        with self.assertRaises(wire.MobileError):service.mobile_operator_request({'op':'pairing_list'})
        for value in ({'op':'enroll'},{'op':'settings'},{'op':'pairing_list','approved':True}):
            with self.subTest(value=value),self.assertRaises(wire.MobileError):service.mobile_operator_request(value)
        second=request({'op':'console'})
        self.assertTrue(second['ok']);self.assertNotEqual(first['data']['delivery'],second['data']['delivery'])
        self.assertFalse(request({'op':'console','uid':os.getuid()})['ok'])

    def test_expired_real_owner_lease_cannot_use_console_grant(self):
        service=self.service();request=self.console_socket(service)
        self.activate(service,self.tls(service),request)
        self.app._auth_deadline=0
        with self.assertRaises(AdmissionError):service.mobile_operator_request({'op':'pairing_list'})
        self.assertFalse(request({'op':'console'})['ok'])

    def test_private_policykit_renewal_rotates_all_browser_grants_and_is_unavailable_over_http(self):
        service=self.service();control=self.console_socket(service);request=self.tls(service)
        token=self.activate(service,request,control);old_cookie=service._mobile_console_cookie
        self.app._auth_deadline=0
        status=control({'op':'operator_auth_status'})['data']
        value={'op':'operator_renew','request_id':'e'*32,**{k:status[k] for k in
            ('source_sha','capsule_digest','core_instance_id','admission_revision')}}
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',
                return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True})) as authenticate:
            self.assertTrue(control(value)['ok']);authenticate.assert_called_once()
        self.assertIsNone(service._mobile_console_uid);self.assertIsNone(service._mobile_console_cookie)
        self.assertIsNone(service._mobile_console_delivery);self.assertNotEqual(token,service.csrf_token)
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'status'},
            {'Origin':self.app.origin,'X-AIOA-Session-Token':token,'Cookie':'__Host-aioa-console='+old_cookie})[0])
        token=self.activate(service,request,control)
        for operation in ({'op':'operator_auth_status'},value):
            self.assertEqual(403,request('POST','/api/native-operator',operation,
                {'Origin':self.app.origin,'X-AIOA-Session-Token':token})[0])

    def test_same_core_status_read_requires_current_kernel_grant_and_exact_payload(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'status'})[0])
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        before=self.app.operator_request(os.getuid(),{'op':'status'})
        code,raw=request('POST','/api/native-operator',{'op':'status'},headers)
        self.assertEqual(200,code,raw)
        data=wire.strict_json(raw)['data']
        self.assertEqual(before,data)
        self.assertEqual('NATIVE_STATUS_READ_ONLY_V1',data['profile'])
        self.assertEqual(0,data['model_calls'])
        self.assertEqual([],data['observations'])
        self.assertEqual([],data['sessions'])
        for value in ({'op':'status','approved':True},{'op':'status','uid':os.getuid()},
                {'op':'settings'},{'op':'enroll'}):
            with self.subTest(value=value):
                self.assertIn(request('POST','/api/native-operator',value,headers)[0],(400,403))
        self.assertEqual(before,self.app.operator_request(os.getuid(),{'op':'status'}))
        self.app._auth_deadline=0
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'status'},headers)[0])

    def test_console_cannot_bind_a_different_service(self):
        service=self.service();service.meta_owner=None
        with self.assertRaises(AdmissionError):make_mobile_operator_server(self.app,service=service)

    def test_native_read_uses_existing_cookie_csrf_and_cannot_forward_write_approval(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        payload={'op':'tool_read','request_id':'c'*32,'operation':'github.repository'}
        self.assertEqual(403,request('POST','/api/native-operator',payload)[0])
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        with patch('runtime.mcp_bridge.native_read.read',return_value={
                'operation':'github.repository','data':{'repository':'luciferprosun/AIOA-spArkHAT'},
                'transport':'FIXTURE_NOT_LIVE'}) as read:
            code,raw=request('POST','/api/native-operator',payload,headers)
            self.assertEqual(200,code,raw)
            receipt=wire.strict_json(raw)['data']
            wire.verify(self.app.identity.spki,receipt['signature'],receipt['receipt'])
            self.assertEqual(1,read.call_count)
            for value in ({**payload,'operation':'issue.create'},{**payload,'approved':True},
                    {'op':'github_approve'},{'op':'chat_approve'},{'op':'cpl_start'}):
                self.assertIn(request('POST','/api/native-operator',value,headers)[0],(400,403))
            self.assertEqual(1,read.call_count)

    def tls(self,service):
        key=ec.generate_private_key(ec.SECP256R1())
        name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'host.example.org')])
        now=datetime.now(timezone.utc)
        cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True)
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('host.example.org')]),critical=False).sign(key,hashes.SHA256()))
        pem=cert.public_bytes(serialization.Encoding.PEM)
        certificate=self.root/'console-test.crt';certificate.write_bytes(pem);certificate.chmod(0o600)
        private=self.root/'console-test.key';private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));private.chmod(0o600)
        server=make_server('127.0.0.1',0,service,tls_certificate=certificate,tls_key=private)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        self.addCleanup(worker.join,3);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        cookie={}
        def request(method,path,body=None,headers=None):
            context=ssl.create_default_context(cadata=pem.decode())
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
            peer=context.wrap_socket(socket.create_connection(server.server_address,timeout=5),server_hostname='host.example.org')
            connection=http.client.HTTPConnection(*server.server_address,timeout=5);connection.sock=peer
            try:
                raw=body if isinstance(body,bytes) else wire.canonical(body) if body is not None else None
                if isinstance(headers,list):
                    connection.putrequest(method,path,skip_host=True,skip_accept_encoding=True)
                    for key,value in [('Host','host.example.org'),*headers]:connection.putheader(key,value)
                    connection.endheaders(raw)
                else:
                    connection.request(method,path,body=raw,
                        headers={'Host':'host.example.org','Content-Type':'application/json',**cookie,**(headers or {})})
                response=connection.getresponse();request.response_headers=dict(response.getheaders())
                if request.response_headers.get('Set-Cookie'):cookie['Cookie']=request.response_headers['Set-Cookie'].split(';')[0]
                return response.status,response.read()
            finally:connection.close()
        request.server=server
        request.certificate_spki=cert.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        return request

    def test_https_console_cannot_bootstrap_authority_and_checks_exact_origin(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        self.assertEqual(200,request('GET','/devices')[0])
        self.assertEqual(404,request('GET','/api/session')[0])
        self.assertEqual(404,request('POST','/api/native-operator?op=console',{})[0])
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'})[0])
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        code,raw=request('POST','/api/native-operator',{'op':'pairing_list'},headers)
        self.assertEqual(200,code,raw)
        self.assertEqual([],wire.strict_json(raw)['data']['devices'])
        self.assertNotIn(token.encode(),request('GET','/devices')[1])
        for value in ({'op':'console'},{'op':'enroll'},{'op':'pairing_list','uid':os.getuid()}):
            with self.subTest(value=value):self.assertIn(request('POST','/api/native-operator',value,headers)[0],(400,403))
        for op in ('budget_review','budget_approve','operator_renew','chat_approve','chat_session_start'):
            with self.subTest(private_op=op):
                self.assertEqual(403,request('POST','/api/native-operator',{'op':op},headers)[0])
        for changed in ({'Origin':'https://evil.example.org'},{'Origin':''},{'X-AIOA-Session-Token':'forged'},
                        {'Sec-Fetch-Site':'cross-site'},{'X-Forwarded-Host':'host.example.org'}):
            with self.subTest(changed=changed):self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},{**headers,**changed})[0])
        control({'op':'console'})
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},headers)[0])

    def test_browser_bootstrap_never_passes_token_to_process_arguments(self):
        import runtime.webapp as webapp
        token='A'*43
        # The launcher receives the bounded grant in memory; the Chrome helper
        # owns stdin/anonymous-pipe delivery, never a credential-bearing file.
        with patch('runtime.mobile_gateway.chrome_console.launch') as launch:
            webapp._launch_mobile_console({'url':self.app.origin+'/devices','delivery':token},self.root)
            launch.assert_called_once_with({'url':self.app.origin+'/devices','delivery':token},self.root)
        source=__import__('inspect').getsource(__import__('runtime.mobile_gateway.chrome_console',fromlist=['launch']))
        self.assertNotIn('localStorage',source)
        self.assertNotIn('--remote-debugging-port',source)
        self.assertNotIn('--no-sandbox',source)
        self.assertNotIn('--ignore-certificate-errors',source)

    def test_file_launcher_allows_only_exact_public_document_navigation(self):
        service=self.service();request=self.tls(service)
        navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        self.assertEqual(200,request('GET','/devices',headers=navigation)[0])
        for changed in ({'Host':'evil.example.org'},{'Origin':'null'},
                        {'Sec-Fetch-Mode':'cors'},{'Sec-Fetch-Dest':'iframe'}):
            with self.subTest(changed=changed):
                self.assertEqual(403,request('GET','/devices',headers={**navigation,**changed})[0])
        for path in ('/mobile_devices.js','/api/mobile/v1/capabilities'):
            with self.subTest(path=path):
                self.assertEqual(403,request('GET',path,headers=navigation)[0])
        for path in ('/index.html','/devices?x=1','/devices/','/devices#operator=bad'):
            with self.subTest(path=path):
                self.assertNotEqual(200,request('GET',path,headers=navigation)[0])
        token=self.activate(service,request,self.console_socket(service))
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},
            {**navigation,'Origin':self.app.origin,'X-AIOA-Session-Token':token})[0])

    def test_unknown_owner_dispatch_is_not_reported_as_definite_auth_denial(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        with patch.object(service,'mobile_operator_request',side_effect=OSError('ACK lost')):
            code,raw=request('POST','/api/native-operator',{'op':'pairing_invite'},headers)
        self.assertEqual(503,code,raw)
        self.assertFalse(wire.strict_json(raw)['automatic_retry'])

    def test_delivery_is_one_time_and_only_returns_transport_after_real_admission(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        grant=control({'op':'console'})['data'];token=service.csrf_token
        self.assertNotIn(token,repr(grant))
        for body in (b'',b'delivery=' + b'B'*43):
            code,raw=request('POST','/devices',body,self.navigation)
            self.assertIn(code,(400,403));self.assertNotIn(token.encode(),raw)
        code,raw=self.redeem(request,grant)
        self.assertEqual(200,code,raw)
        self.assertEqual('no-store',request.response_headers['Cache-Control'])
        self.assertEqual('no-referrer',request.response_headers['Referrer-Policy'])
        self.assertIn('HttpOnly',request.response_headers.get('Set-Cookie',''))
        self.assertIn('Secure',request.response_headers.get('Set-Cookie',''))
        self.assertIn('SameSite=Strict',request.response_headers.get('Set-Cookie',''))
        self.assertNotIn('Location',request.response_headers)
        self.assertNotIn(token.encode(),raw)
        self.assertNotIn(b'aioa-console-credential',raw)
        self.assertNotIn(grant['delivery'].encode(),raw)
        self.assertEqual([],service.mobile_operator_request({'op':'pairing_list'})['devices'])
        public=wire.canonical(service.mobile_operator_request({'op':'pairing_invite'}))
        for secret in (grant['delivery'],token):
            self.assertNotIn(secret.encode(),public)
            for path in self.app.root.rglob('*'):
                if path.is_file():self.assertNotIn(secret.encode(),path.read_bytes(),str(path))
        self.assertEqual(403,self.redeem(request,grant)[0])
        self.assertNotIn(token.encode(),request('GET','/devices')[1])
        fresh=control({'op':'console'})['data']
        self.assertEqual(403,self.redeem(request,grant)[0])
        self.app._auth_deadline=0
        code,raw=self.redeem(request,fresh)
        self.assertEqual(403,code);self.assertNotIn(service.csrf_token.encode(),raw)
        with self.assertRaises(wire.MobileError):service.mobile_operator_request({'op':'pairing_list'})

    def test_delivery_expiry_and_lost_response_never_reissue_credential(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        with patch('time.monotonic',return_value=100):grant=control({'op':'console'})['data']
        with patch('time.monotonic',return_value=131):
            code,raw=self.redeem(request,grant)
        self.assertEqual(403,code);self.assertNotIn(service.csrf_token.encode(),raw)
        fresh=control({'op':'console'})['data']
        # Deliberately discard the successful response: replay must fail closed.
        self.redeem(request,fresh)
        code,raw=self.redeem(request,fresh)
        self.assertEqual(403,code);self.assertNotIn(service.csrf_token.encode(),raw)

    def test_delivery_rejects_malformed_navigation_and_framing_without_consumption(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        grant=control({'op':'console'})['data'];body=('delivery='+grant['delivery']).encode()
        for changed in ({'Origin':self.app.origin},{'Origin':'https://evil.example.org'},
                {'Origin':''},{'Sec-Fetch-Mode':'cors'},{'Sec-Fetch-Dest':'iframe'},
                {'Sec-Fetch-Site':'same-origin'},{'Content-Type':'application/json'},
                {'Transfer-Encoding':'chunked'},{'Forwarded':'for=127.0.0.1'},
                {'X-Forwarded-Host':'host.example.org'},{'Content-Length':'+52'}):
            with self.subTest(changed=changed):
                code,raw=request('POST','/devices',body,{**self.navigation,**changed})
                self.assertIn(code,(400,403));self.assertNotIn(service.csrf_token.encode(),raw)
        for malformed in (body+b'&x=1',body+b'&'+body,b'delivery=%41'+body[10:],b'token='+body[9:],body[:-1]):
            with self.subTest(body=malformed):
                self.assertIn(request('POST','/devices',malformed,self.navigation)[0],(400,403))
        framing=[*self.navigation.items(),('Content-Length','52')]
        for name in self.navigation.keys() | {'Content-Length'}:
            for malformed_headers in ([item for item in framing if item[0]!=name],
                    [*framing,next(item for item in framing if item[0]==name)]):
                with self.subTest(header=name,headers=malformed_headers):
                    self.assertIn(request('POST','/devices',body,malformed_headers)[0],(400,403))
        self.assertEqual(403,request('POST','/devices',body,[*framing,('Host','host.example.org')])[0])
        for path in ('/devices?delivery='+grant['delivery'],'/devices#'+grant['delivery'],
                '/api/native-operator','/devices/'):
            with self.subTest(path=path):self.assertNotEqual(200,request('POST',path,body,self.navigation)[0])
        self.assertEqual(200,self.redeem(request,grant)[0])

    def test_wrong_socket_principal_cannot_issue_delivery(self):
        service=self.service();control=self.console_socket(service)
        with patch('struct.unpack',return_value=(1,os.getuid()+1,1)):
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as peer:
                peer.connect(str(self.app.root/'operator.sock'))
                try:
                    peer.sendall(b'{"op":"console"}\n')
                    with peer.makefile('rb') as stream:result=wire.strict_json(stream.readline())
                except (BrokenPipeError,ConnectionResetError):
                    # Early kernel-peer rejection may close before any bytes
                    # are accepted. No grant or admission may have been issued.
                    result={'ok':False}
            self.assertFalse(result['ok'])
            self.assertNotIn('data',result)
            self.assertIsNone(service._mobile_console_uid)
            self.assertIsNone(service._mobile_console_delivery)
        with self.assertRaises(wire.MobileError):service.mobile_operator_request({'op':'pairing_list'})
