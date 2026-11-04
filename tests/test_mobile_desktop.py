"""Desktop commands use the existing private host; no real GUI or process."""
from argparse import Namespace
import importlib
import os
import socket
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


class DesktopTests(unittest.TestCase):
    def module(self):return importlib.import_module('runtime.mobile_gateway.desktop')
    def status(self,state='READY'):
        return {'state':state,'source_sha':'a'*40,'capsule_digest':'b'*64,'core_instance_id':'instance',
            'admission_revision':1,'current_source':True}
    def test_healthy_host_reopens_same_private_console_without_start_or_renew(self):
        calls=[]
        def client(root,value):
            calls.append(value)
            return {'ok':True,'data':{'delivery':'PRIVATE_TEST_ONLY','url':'https://host.invalid/devices'} if value['op']=='console' else self.status()}
        result=self.module().prepare_console(Path('/unused'),('a'*40,'b'*64),client=client)
        self.assertEqual('https://host.invalid/devices',result['url'])
        self.assertEqual(['operator_auth_status','console'],[v['op'] for v in calls])

    def test_explicit_direct_chat_preference_starts_once_without_password_or_prompt(self):
        calls=[]
        def client(root,value):
            calls.append(value)
            return {'ok':True,'data':{'state':'INACTIVE' if value['op']=='chat_session_status' else 'ACTIVE'}}
        self.module().prepare_chat_session(Path('/unused'),client=client)
        self.assertEqual(['chat_session_status','chat_session_start'],[v['op'] for v in calls])
        self.assertIsNone(calls[-1]['local_money_limit_usd'])
        self.assertNotIn('prompt',calls[-1])

    def test_active_direct_chat_session_is_reused_and_unknown_start_is_not_retried(self):
        client=Mock(return_value={'ok':True,'data':{'state':'ACTIVE'}})
        self.module().prepare_chat_session(Path('/unused'),client=client)
        self.assertEqual(1,client.call_count)
        client=Mock(side_effect=[{'ok':True,'data':{'state':'INACTIVE'}},TimeoutError()])
        with self.assertRaises(TimeoutError):self.module().prepare_chat_session(Path('/unused'),client=client)
        self.assertEqual(2,client.call_count)

    def test_direct_chat_launcher_is_an_explicit_opt_in(self):
        module=self.module()
        self.assertNotIn('--mobile-chat-direct',module.launcher_files('/checkout','/state')['aioa-mission-control'])
        self.assertIn('--mobile-chat-direct',module.launcher_files('/checkout','/state',direct_chat=True)['aioa-mission-control'])
    def test_expired_host_requires_native_renewal_with_exact_binding(self):
        calls=[]
        def client(root,value):
            calls.append(value)
            if value['op']=='operator_auth_status':return {'ok':True,'data':self.status('AUTH_REQUIRED')}
            return {'ok':True,'data':self.status() if value['op']=='operator_renew' else {'delivery':'test'}}
        self.module().prepare_console(Path('/unused'),('a'*40,'b'*64),client=client)
        self.assertEqual(['operator_auth_status','operator_renew','console'],[v['op'] for v in calls])
        self.assertEqual({'op','request_id','source_sha','capsule_digest','core_instance_id','admission_revision'},set(calls[1]))
    def test_source_mismatch_unknown_ack_and_old_server_never_open_or_restart(self):
        for response in ({'ok':False},{'ok':True,'data':{**self.status(),'source_sha':'e'*40}}):
            client=Mock(return_value=response)
            with self.subTest(response=response),self.assertRaises(ValueError):
                self.module().prepare_console(Path('/unused'),('a'*40,'b'*64),client=client)
            self.assertEqual(1,client.call_count)
        client=Mock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError):self.module().prepare_console(Path('/unused'),('a'*40,'b'*64),client=client)
        self.assertEqual(1,client.call_count)
    def test_start_refuses_an_empty_state_before_spawning_or_installing(self):
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen') as spawn:
            root=Path(tmp);root.chmod(0o700)
            args=Namespace(state_dir=str(root),mobile_origin='https://host.invalid',mobile_chat=True,
                mobile_tls_certificate=str(root/'tls/host.crt'),mobile_tls_key=str(root/'tls/host.key'),host='127.0.0.1',port=4317)
            with self.assertRaises(ValueError):self.module().start_existing_profile(args)
            spawn.assert_not_called()
    def test_empty_or_unrelated_database_never_starts_a_new_core(self):
        for unrelated in (False,True):
            with tempfile.TemporaryDirectory() as tmp,patch('subprocess.Popen') as spawn:
                root=Path(tmp);root.chmod(0o700)
                for name in ('core-records.sqlite3','host-signing-key.pem','runtime.lock'):
                    (root/name).write_bytes(b'');(root/name).chmod(0o600)
                if unrelated:
                    with sqlite3.connect(root/'core-records.sqlite3') as db:db.execute('CREATE TABLE unrelated (value TEXT)')
                args=Namespace(state_dir=str(root),mobile_origin='https://host.invalid',mobile_chat=True,
                    mobile_tls_certificate=str(root/'tls/host.crt'),mobile_tls_key=str(root/'tls/host.key'),host='127.0.0.1',port=4317)
                with self.assertRaises(ValueError):self.module().start_existing_profile(args)
                spawn.assert_not_called()
    def test_occupied_native_port_denies_before_any_core_construction_or_authentication(self):
        from runtime.webapp import main
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen(1)
            port=listener.getsockname()[1]
            arguments=['webapp','--mobile-native','--state-dir','/not-read',
                '--mobile-origin','https://host.invalid','--mobile-tls-certificate','/not-read.crt',
                '--mobile-tls-key','/not-read.key','--port',str(port)]
            with patch('sys.argv',arguments),patch('runtime.meta_hackathon.runtime_adapter.NativeMobileComposition',
                    side_effect=RuntimeError('CORE_CONSTRUCTED_TOO_EARLY')) as core:
                with self.assertRaises(OSError):main()
                core.assert_not_called()
    def test_launcher_files_quote_paths_and_have_no_credentials_or_alternate_state(self):
        module=self.module()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'checkout with spaces';root.mkdir()
            files=module.launcher_files(root,Path(tmp)/'private state')
            self.assertEqual({'aioa-mission-control','aioa-mission-control.desktop'},set(files))
            self.assertIn("'"+str(root)+"'",files['aioa-mission-control'])
            self.assertIn('--mobile-operator desktop',files['aioa-mission-control'])
            self.assertIn('AIOA spArkHAT — White Hole Mission Control',files['aioa-mission-control.desktop'])
            self.assertNotIn('sudo',str(files));self.assertNotIn('MODEL_API_KEY',str(files))

    def test_unstarted_private_server_is_closed_without_blocking_shutdown(self):
        from runtime.webapp import main
        owner=Mock();server=Mock();server.server_address=('127.0.0.1',4317);control=Mock()
        arguments=['webapp','--mobile-native','--state-dir','/synthetic','--mobile-origin','https://host.invalid',
            '--mobile-tls-certificate','/synthetic.crt','--mobile-tls-key','/synthetic.key']
        with patch('sys.argv',arguments),patch('runtime.webapp.ThreadingHTTPServer',return_value=server),\
             patch('runtime.meta_hackathon.runtime_adapter.NativeMobileComposition',return_value=owner),\
             patch('runtime.webapp.WebRuntimeService'),patch('runtime.webapp.make_server',return_value=server),\
             patch('runtime.webapp.make_mobile_operator_server',return_value=control),\
             patch('threading.Thread',side_effect=[Mock(),Mock(start=Mock(side_effect=RuntimeError('synthetic thread failure')))]):
            with self.assertRaises(RuntimeError):main()
        control.shutdown.assert_not_called();control.server_close.assert_called_once();owner.close.assert_called_once()


if __name__=='__main__':unittest.main()
