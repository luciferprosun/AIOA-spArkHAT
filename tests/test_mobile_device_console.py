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

    def test_kernel_bootstrap_enables_only_pairing_ops_and_rotates_transport(self):
        service=self.service();request=self.console_socket(service)
        first=request({'op':'console'})
        self.assertTrue(first['ok'],first)
        self.assertEqual(service.csrf_token,first['data']['token'])
        self.assertEqual(self.app.origin+'/devices',first['data']['url'])
        self.assertEqual([],service.mobile_operator_request({'op':'pairing_list'})['devices'])
        for value in ({'op':'enroll'},{'op':'settings'},{'op':'pairing_list','approved':True}):
            with self.subTest(value=value),self.assertRaises(wire.MobileError):service.mobile_operator_request(value)
        second=request({'op':'console'})
        self.assertTrue(second['ok']);self.assertNotEqual(first['data']['token'],second['data']['token'])
        self.assertFalse(request({'op':'console','uid':os.getuid()})['ok'])

    def test_expired_real_owner_lease_cannot_use_console_grant(self):
        service=self.service();request=self.console_socket(service)
        self.assertTrue(request({'op':'console'})['ok'])
        self.app._auth_deadline=0
        with self.assertRaises(AdmissionError):service.mobile_operator_request({'op':'pairing_list'})
        self.assertFalse(request({'op':'console'})['ok'])

    def test_console_cannot_bind_a_different_service(self):
        service=self.service();service.meta_owner=None
        with self.assertRaises(AdmissionError):make_mobile_operator_server(self.app,service=service)

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
        def request(method,path,body=None,headers=None):
            context=ssl.create_default_context(cadata=pem.decode())
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_3
            peer=context.wrap_socket(socket.create_connection(server.server_address,timeout=5),server_hostname='host.example.org')
            connection=http.client.HTTPConnection(*server.server_address,timeout=5);connection.sock=peer
            try:
                connection.request(method,path,body=wire.canonical(body) if body is not None else None,
                    headers={'Host':'host.example.org','Content-Type':'application/json',**(headers or {})})
                response=connection.getresponse();return response.status,response.read()
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
        token=control({'op':'console'})['data']['token']
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        code,raw=request('POST','/api/native-operator',{'op':'pairing_list'},headers)
        self.assertEqual(200,code,raw)
        self.assertEqual([],wire.strict_json(raw)['data']['devices'])
        self.assertNotIn(token.encode(),request('GET','/devices')[1])
        for value in ({'op':'console'},{'op':'enroll'},{'op':'pairing_list','uid':os.getuid()}):
            with self.subTest(value=value):self.assertIn(request('POST','/api/native-operator',value,headers)[0],(400,403))
        for changed in ({'Origin':'https://evil.example.org'},{'Origin':''},{'X-AIOA-Session-Token':'forged'},
                        {'Sec-Fetch-Site':'cross-site'},{'X-Forwarded-Host':'host.example.org'}):
            with self.subTest(changed=changed):self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},{**headers,**changed})[0])
        control({'op':'console'})
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},headers)[0])

    def test_browser_bootstrap_never_passes_token_to_process_arguments(self):
        import runtime.webapp as webapp
        from pathlib import Path
        token='A'*43;seen=[]
        def launch(argv,**kwargs):
            self.assertNotIn(token,str(argv));self.assertNotIn(token,str(kwargs))
            page=Path(argv[1].removeprefix('file://'))
            self.assertEqual(0o600,page.stat().st_mode&0o777)
            self.assertEqual(0o700,page.parent.stat().st_mode&0o777)
            self.assertIn(token,page.read_text());seen.append(page)
            class Process:returncode=0
            return Process()
        with patch('subprocess.run',side_effect=launch),patch('time.sleep'):
            webapp._launch_mobile_console({'url':self.app.origin+'/devices','token':token},self.root)
        self.assertEqual(1,len(seen));self.assertFalse(seen[0].exists())

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
        token=self.console_socket(service)({'op':'console'})['data']['token']
        self.assertEqual(403,request('POST','/api/native-operator',{'op':'pairing_list'},
            {**navigation,'Origin':self.app.origin,'X-AIOA-Session-Token':token})[0])

    def test_unknown_owner_dispatch_is_not_reported_as_definite_auth_denial(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        token=control({'op':'console'})['data']['token']
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        with patch.object(service,'mobile_operator_request',side_effect=OSError('ACK lost')):
            code,raw=request('POST','/api/native-operator',{'op':'pairing_invite'},headers)
        self.assertEqual(503,code,raw)
        self.assertFalse(wire.strict_json(raw)['automatic_retry'])
