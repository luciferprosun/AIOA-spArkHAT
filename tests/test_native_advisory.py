"""Local preview E2E: real temporary Native/Core/SQLite; no model or mail traffic."""
from dataclasses import replace
from contextlib import redirect_stdout,redirect_stderr
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch

import test_mobile_pairing as pairing
import test_mobile_chat as chat_fixture
import test_mobile_device_console as console_fixture
from runtime.core_admission import AdmissionError,Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mobile_gateway import wire
from runtime.communication.canonical_mime import prepare_mime,verify_prepared_mime
from runtime.communication.contracts import MailContractError
from test_gmail_contracts import proposal


class NativeAdvisoryTests(unittest.TestCase):
    setUp=pairing.PairingTests.setUp
    tearDown=pairing.PairingTests.tearDown
    start=chat_fixture.NativeChatTests.start
    service=console_fixture.DeviceConsoleTests.service
    tls=console_fixture.DeviceConsoleTests.tls
    console_socket=console_fixture.DeviceConsoleTests.console_socket
    activate=console_fixture.DeviceConsoleTests.activate
    redeem=console_fixture.DeviceConsoleTests.redeem
    navigation=console_fixture.DeviceConsoleTests.navigation

    def call(self,op='command_advice',payload=None,request_id='a'*32,**extra):
        return self.app.operator_request(os.getuid(),{'op':op,'request_id':request_id,
            'payload':payload if payload is not None else {'command':'systemctl status sshd'},**extra})

    def test_command_input_is_advisory_signed_and_idempotent_without_child_or_provider(self):
        with patch('subprocess.Popen') as child,patch('runtime.providers.meta_model_api._https_once') as http:
            result=self.call(payload={'command':'echo ok > local.txt'})
            self.assertEqual('suspicious',result['data']['classification']['status'])
            self.assertFalse(result['receipt']['execution_authorized'])
            self.assertEqual('ADVISORY_PREVIEW',result['receipt']['effect'])
            self.assertEqual(result,self.call(payload={'command':'echo ok > local.txt'}))
            with self.assertRaises(wire.MobileError):self.call(payload={'command':'echo changed'})
            child.assert_not_called();http.assert_not_called()
        wire.verify(self.app.identity.spki,result['signature'],result['receipt'])
        self.assertEqual(wire.digest(wire.canonical(result['data'])),result['receipt']['data_sha256'])
        row=self.app.mobile._get('native-advisory-'+'a'*32)
        self.assertEqual(1,row.revision)

    def test_mail_preview_records_fingerprints_without_content_or_send_authority(self):
        draft={'sender':'author@example.org','to':['reviewer@example.org'],
            'subject':'Private preview subject','body_text':'Private preview body\n'}
        with patch('subprocess.Popen') as child,patch('socket.create_connection') as network:
            result=self.call('mail_preview',draft)
            self.assertEqual('DRAFT_PREVIEW_ONLY',result['data']['status'])
            self.assertEqual('BLOCKED_GMAIL_CORE_TRANSPORT_NOT_BOUND',result['data']['send_status'])
            self.assertFalse(result['receipt']['execution_authorized'])
            self.assertEqual(0,result['receipt']['external_calls'])
            self.assertEqual(result,self.call('mail_preview',draft))
            child.assert_not_called();network.assert_not_called()
        from runtime.mobile_gateway.service import plain
        stored=json.dumps(plain(self.app.mobile._get('native-advisory-'+'a'*32).payload))
        for private in (draft['sender'],draft['to'][0],draft['subject'],draft['body_text']):self.assertNotIn(private,stored)
        wire.verify(self.app.identity.spki,result['signature'],result['receipt'])

    def test_forged_authority_expired_host_wrong_uid_and_oversized_input_are_denied(self):
        with patch('runtime.tools.command_grammar.validate_command_shape') as classify:
            with self.assertRaises(wire.MobileError):self.call(approved=True)
            with self.assertRaises(wire.MobileError):self.call(payload={'command':'x'*2001})
            with self.assertRaises(AdmissionError):self.app.operator_request(os.getuid()+1,{
                'op':'command_advice','request_id':'a'*32,'payload':{'command':'ls'}})
            self.app._auth_deadline=0
            with self.assertRaises(AdmissionError):self.call()
            classify.assert_not_called()

    def test_invalid_mail_is_a_known_recorded_refusal_and_a_corrected_draft_can_follow(self):
        invalid={'sender':'invalid','to':['reviewer@example.org'],'subject':'','body_text':''}
        rejected=self.call('mail_preview',invalid)
        self.assertEqual('INPUT_REJECTED',rejected['data']['status'])
        self.assertFalse(rejected['receipt']['execution_authorized'])
        corrected={**invalid,'sender':'author@example.org','subject':'Ready','body_text':'Local preview only'}
        accepted=self.call('mail_preview',corrected,request_id='b'*32)
        self.assertEqual('DRAFT_PREVIEW_ONLY',accepted['data']['status'])

    def test_shell_evaluation_is_never_signed_as_read_only_advice(self):
        for index,command in enumerate(('ls $(touch /tmp/example)','ls `touch /tmp/example`',
                'ls\ntouch /tmp/example','ls <(touch /tmp/example)','ls /tmp&touch /tmp/example',
                'ls /tmp;touch /tmp/example','ls /tmp | cat')):
            result=self.call(payload={'command':command},request_id=f'{index+1:032x}')
            self.assertEqual('suspicious',result['data']['classification']['status'])
            self.assertEqual('unknown',result['data']['classification']['danger'])

    def test_blank_command_is_known_advisory_rejection_without_invalidating_owner(self):
        result=self.call(payload={'command':''})
        self.assertEqual('reject',result['data']['classification']['status'])
        self.assertFalse(result['receipt']['execution_authorized'])
        self.assertEqual('ADVISORY_ONLY',self.call(request_id='b'*32)['data']['status'])

    def test_variables_escapes_and_unicode_never_expand_or_execute(self):
        commands=('$CMD /tmp','${CMD} /tmp','ls "$TARGET"',r'ls /tmp\;touch /tmp/example',
            'ls\r\ntouch /tmp/example','ls /tmp/\u202eexample','ls /tmp/\x00example')
        with patch('subprocess.Popen') as child,patch('socket.create_connection') as network:
            for index,command in enumerate(commands):
                result=self.call(payload={'command':command},request_id=f'{index+1:032x}')
                self.assertEqual('unknown',result['data']['classification']['danger'])
                self.assertFalse(result['receipt']['execution_authorized'])
                wire.verify(self.app.identity.spki,result['signature'],result['receipt'])
            result=self.call(payload={'command':'ls "/tmp/zażółć 🧪"'})
            self.assertEqual('read_only',result['data']['classification']['danger'])
            self.assertFalse(result['receipt']['execution_authorized'])
            child.assert_not_called();network.assert_not_called()

    def test_invalid_recipient_headers_and_unicode_are_private_signed_refusals(self):
        draft={'sender':'author@example.org','to':['reviewer@example.org'],
            'subject':'Private subject','body_text':'Private body'}
        invalid=({'sender':'author@example.org\r\nBcc: bad@example.org'},
            {'to':['bad']},{'to':['reviewer@example.org\r\nCc: bad@example.org']},
            {'subject':'Private\r\nBcc: bad@example.org'}, {'body_text':'Private\r\nbody'},
            {'body_text':'Private\x00body'},{'body_text':'Private\u202ebody'},
            {'subject':'e\u0301'},{'to':[]},{'to':[f'user{i}@example.org' for i in range(9)]},
            {'to':['REVIEWER@example.org','reviewer@example.org']})
        output=io.StringIO()
        with patch('subprocess.Popen') as child,patch('socket.create_connection') as network,\
                redirect_stdout(output),redirect_stderr(output):
            for index,changed in enumerate(invalid):
                result=self.call('mail_preview',{**draft,**changed},request_id=f'{index+1:032x}')
                self.assertEqual('INPUT_REJECTED',result['data']['status'])
                self.assertFalse(result['receipt']['execution_authorized'])
                wire.verify(self.app.identity.spki,result['signature'],result['receipt'])
            corrected=self.call('mail_preview',draft)
            self.assertEqual('DRAFT_PREVIEW_ONLY',corrected['data']['status'])
            child.assert_not_called();network.assert_not_called()
        self.assertEqual('',output.getvalue())
        for private in ('author@example.org','reviewer@example.org','Private subject','Private body','bad@example.org'):
            self.assertNotIn(private.encode(),(self.root/'core-records.sqlite3').read_bytes())

    def test_changed_mail_recipient_cannot_reuse_id_or_append_an_event(self):
        draft={'sender':'author@example.org','to':['reviewer@example.org'],'subject':'Preview','body_text':'Local only'}
        first=self.call('mail_preview',draft)
        before=self.app.mobile._run(Capability.READ,lambda tx:len(tx.scan(RecordKind.AUDIT,limit=128)))
        with patch('socket.create_connection') as network:
            with self.assertRaises(wire.MobileError) as caught:
                self.call('mail_preview',{**draft,'to':['different@example.org']})
            self.assertEqual(409,caught.exception.status);network.assert_not_called()
        self.assertEqual(first,self.call('mail_preview',draft))
        self.assertEqual(1,self.app.mobile._get('native-advisory-'+'a'*32).revision)
        self.assertEqual(before,self.app.mobile._run(Capability.READ,lambda tx:len(tx.scan(RecordKind.AUDIT,limit=128))))

    def test_committed_advisory_with_lost_ack_is_read_back_without_recomputation(self):
        run=self.app.mobile._run
        def lost(purpose,callback):
            result=run(purpose,callback)
            if purpose is Capability.COMMIT:raise CommitOutcomeUnknown()
            return result
        with patch.object(self.app.mobile,'_run',side_effect=lost),self.assertRaises(CommitOutcomeUnknown):self.call()
        before=run(Capability.READ,lambda tx:len(tx.scan(RecordKind.AUDIT,limit=128)))
        with patch('runtime.tools.command_grammar.validate_command_shape') as classify:
            result=self.call();classify.assert_not_called()
        wire.verify(self.app.identity.spki,result['signature'],result['receipt'])
        self.assertEqual(before,run(Capability.READ,lambda tx:len(tx.scan(RecordKind.AUDIT,limit=128))))
        self.assertEqual(1,self.app.mobile._get('native-advisory-'+'a'*32).revision)

    def test_source_drift_and_new_instance_cannot_rebind_existing_preview(self):
        result=self.call();self.source[1]='c'*64
        with patch('runtime.tools.command_grammar.validate_command_shape') as classify:
            with self.assertRaises(AdmissionError):self.call()
            classify.assert_not_called()
        self.source[1]='b'*64;self.app.close();self.start()
        with self.assertRaises(wire.MobileError) as caught:self.call()
        self.assertEqual(409,caught.exception.status)
        from runtime.mobile_gateway.service import plain
        stored=plain(self.app.mobile._get('native-advisory-'+'a'*32).payload['result'])
        self.assertEqual(result,stored)
        wire.verify(self.app.identity.spki,stored['signature'],stored['receipt'])

    def test_invalid_unicode_transport_is_denied_without_audit_or_session_loss(self):
        with self.assertRaises(wire.MobileError):self.call(payload={'command':'ls \ud800'})
        self.assertIsNone(self.app.mobile._get('native-advisory-'+'a'*32))
        self.assertEqual('ADVISORY_ONLY',self.call()['data']['status'])

    def test_http_preview_requires_existing_console_session_origin_and_csrf(self):
        service=self.service();request=self.tls(service);control=self.console_socket(service)
        value={'op':'command_advice','request_id':'b'*32,'payload':{'command':'ls -l'}}
        self.assertEqual(403,request('POST','/api/native-operator',value)[0])
        token=self.activate(service,request,control)
        headers={'X-AIOA-Session-Token':token,'Origin':self.app.origin}
        self.assertEqual(403,request('POST','/api/native-operator',value,{**headers,'Origin':'https://foreign.invalid'})[0])
        code,raw=request('POST','/api/native-operator',value,headers)
        self.assertEqual(200,code,raw)
        result=wire.strict_json(raw)['data'];self.assertFalse(result['receipt']['execution_authorized'])
        wire.verify(self.app.identity.spki,result['signature'],result['receipt'])
        for op in ('mail_send','gmail_connect','command_execute'):
            self.assertEqual(403,request('POST','/api/native-operator',{**value,'op':op},headers)[0])


class MailExactBindingTests(unittest.TestCase):
    def test_recomputed_digest_of_substituted_mime_is_not_a_proposal_binding(self):
        original=proposal();prepared=prepare_mime(original);raw=prepared.raw_mime.replace(b'option A',b'option B')
        self.assertNotEqual(raw,prepared.raw_mime)
        forged=replace(prepared,raw_mime=raw,mime_sha256=hashlib.sha256(raw).hexdigest())
        with self.assertRaisesRegex(MailContractError,'MAIL_MIME_BINDING_MISMATCH'):verify_prepared_mime(original,forged)

    def test_changed_correlation_or_proposal_is_refused(self):
        original=proposal();prepared=prepare_mime(original)
        with self.assertRaisesRegex(MailContractError,'MAIL_MIME_BINDING_MISMATCH'):
            verify_prepared_mime(original,replace(prepared,correlation_id='different@example.invalid'))
        with self.assertRaisesRegex(MailContractError,'MAIL_MIME_BINDING_MISMATCH'):
            verify_prepared_mime(replace(original,subject='Changed exact subject'),prepared)


if __name__=='__main__':unittest.main()
