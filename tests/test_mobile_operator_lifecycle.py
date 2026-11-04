"""Isolated real Core records; PolicyKit is synthetic and no live service runs."""
import os
import time
import unittest
from unittest.mock import Mock, patch

import test_mobile_pairing as fixture
from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.errors import MemoryPatchError
from runtime.mobile_gateway import wire


class OperatorLifecycleTests(unittest.TestCase):
    setUp=fixture.PairingTests.setUp
    start=fixture.PairingTests.start
    tearDown=fixture.PairingTests.tearDown

    def status(self):return self.app.operator_request(os.getuid(),{'op':'operator_auth_status'})
    def renewal(self):
        data=self.status()
        return {'op':'operator_renew','request_id':'1'*32,**{k:data[k] for k in
            ('source_sha','capsule_digest','core_instance_id','admission_revision')}}
    def invoke(self,value=None,callback=None):
        return self.app.operator_request(os.getuid(),value or self.renewal(),invalidate_console=callback or Mock())
    def auth(self):
        return patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',
            return_value=(os.getuid(),{'uid':os.getuid(),'test_only':True}))

    def test_expired_lease_renews_same_core_only_after_real_authentication_and_grant_invalidation(self):
        core,instance=self.app.core,self.app.instance_id;self.app._auth_deadline=0
        self.assertEqual('AUTH_REQUIRED',self.status()['state'])
        before=self.status()['admission_revision'];callback=Mock()
        with self.auth() as auth:
            result=self.invoke(callback=callback);auth.assert_called_once();callback.assert_called_once()
        self.assertEqual('READY',result['state']);self.assertEqual(before+1,result['admission_revision'])
        self.assertIs(core,self.app.core);self.assertEqual(instance,self.app.instance_id)
        self.assertIsNotNone(self.app.operator_principal())

    def test_wrong_binding_extra_approval_and_wrong_peer_never_authenticate(self):
        value=self.renewal()
        with self.auth() as auth:
            for field,bad in (('source_sha','f'*40),('capsule_digest','f'*64),('core_instance_id','forged'),
                              ('admission_revision',0),('approved',True),('uid',os.getuid())):
                with self.subTest(field=field),self.assertRaises((AdmissionError,wire.MobileError)):
                    self.invoke({**value,field:bad})
            with self.assertRaises(AdmissionError):self.app.operator_request(os.getuid()+1,value,invalidate_console=Mock())
            auth.assert_not_called()

    def test_cancel_source_drift_and_missing_web_invalidator_fail_closed(self):
        self.app._auth_deadline=0;value=self.renewal()
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',side_effect=AdmissionError()):
            with self.assertRaises(AdmissionError):self.invoke(value)
        self.assertEqual('AUTH_REQUIRED',self.status()['state'])
        with self.auth() as auth:
            with self.assertRaises(AdmissionError):self.app.operator_request(os.getuid(),{**value,'request_id':'2'*32})
            auth.assert_not_called()
        def drift():
            self.source[0]='e'*40;return os.getuid(),{'uid':os.getuid()}
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',side_effect=drift):
            with self.assertRaises(AdmissionError):self.invoke({**value,'request_id':'3'*32})
        with self.assertRaises(AdmissionError):self.app.operator_principal()

    def test_duplicate_request_cannot_extend_lease_or_authenticate_twice(self):
        value=self.renewal()
        with self.auth() as auth:
            self.invoke(value);deadline=self.app._auth_deadline
            result=self.invoke(value)
            self.assertEqual(deadline,self.app._auth_deadline);self.assertEqual('READBACK_ONLY',result['renewal'])
            auth.assert_called_once()
        self.app._auth_deadline=0
        with self.auth() as auth:
            self.assertEqual('AUTH_REQUIRED',self.invoke(value)['state']);auth.assert_not_called()

    def test_commit_ack_loss_never_publishes_renewed_lease_or_retries(self):
        value=self.renewal();original=self.app.mobile._run
        def lost(cap,fn):
            result=original(cap,fn)
            if cap is Capability.COMMIT:raise RuntimeError('synthetic commit ACK loss')
            return result
        with self.auth(),patch.object(self.app.mobile,'_run',side_effect=lost):
            with self.assertRaises(RuntimeError):self.invoke(value)
        self.assertEqual('AUTH_REQUIRED',self.status()['state'])
        with self.auth() as auth:
            self.assertEqual('AUTH_REQUIRED',self.invoke(value)['state']);auth.assert_not_called()

    def test_active_worker_cannot_be_interrupted_by_renewal(self):
        self.app.missions._workers['synthetic']=Mock(is_alive=lambda:True)
        with self.auth() as auth:
            with self.assertRaises(wire.MobileError):self.invoke()
            auth.assert_not_called()
        self.app.missions._workers.clear()

    def test_existing_profile_preflight_accepts_same_native_history_and_denies_auth_time_drift(self):
        from runtime.mobile_gateway.desktop import validate_existing_profile
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        snapshot=validate_existing_profile(self.app.root)
        self.assertEqual(4,len(snapshot));root=self.app.root;self.app.close()
        def drift():
            info=(root/'core-records.sqlite3').stat()
            os.utime(root/'core-records.sqlite3',ns=(info.st_atime_ns,info.st_mtime_ns+1))
            return os.getuid(),{'uid':os.getuid(),'test_only':True}
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',side_effect=drift):
            with self.assertRaises(AdmissionError):NativeMobileComposition(root,origin='https://host.example.org',
                source_probe=lambda:tuple(self.source),existing_profile=True)
        with self.auth():self.app=NativeMobileComposition(root,origin='https://host.example.org',
            source_probe=lambda:tuple(self.source),existing_profile=True)
        self.assertEqual(0,self.app.model_calls())

    def chat_host(self):
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        root=self.app.root;self.app.close();key=root/'synthetic-meta-key'
        key.write_text('SYNTHETIC_NOT_LIVE');key.chmod(0o600)
        with self.auth():self.app=NativeMobileComposition(root,origin='https://host.example.org',chat=True,
            key_path=key,source_probe=lambda:tuple(self.source),existing_profile=True)
        self.app.tls_verified=True;self.app._tls_expires=time.time()+3600

    def test_epoch_takeover_preserves_unknown_exposure_and_kill_and_fences_old_dispatch(self):
        from runtime.mission.governor import ReservationRequest
        self.chat_host();gov=self.app.chat_governor
        reader=self.app.core.local_operator(Capability.READ);commit=self.app.core.local_operator(Capability.COMMIT)
        epoch=gov.inspect(reader)['epoch']
        request=ReservationRequest('synthetic-held','synthetic-task','meta_model_api','muse-spark-1.3','a'*64,1000,1)
        gov.reserve(commit,request,epoch);gov.dispatch_commit(commit,request.request_id,epoch)
        gov.mark_unknown(commit,request.request_id,epoch,'b'*64)
        gov.set_kill(self.app.core.local_operator(Capability.MANAGE),True)
        before=gov.inspect(reader);self.app._auth_deadline=0
        with self.auth(),patch('runtime.providers.meta_model_api._https_once') as transport:
            self.invoke();transport.assert_not_called()
        after=gov.inspect(reader)
        self.assertEqual(epoch+1,after['epoch']);self.assertEqual(before['reservations'],after['reservations'])
        self.assertEqual(before['exposure'],after['exposure']);self.assertTrue(after['kill'])
        with self.assertRaises(ValueError):gov.dispatch_commit(commit,request.request_id,epoch)

    def test_epoch_ack_loss_and_invalidation_failure_never_publish_a_new_lease(self):
        self.chat_host();value=self.renewal();before=self.status()['admission_revision']
        with self.auth(),patch.object(self.app.chat_governor,'start_epoch',side_effect=RuntimeError('synthetic epoch ACK loss')):
            with self.assertRaises(RuntimeError):self.invoke(value)
        self.assertEqual('AUTH_REQUIRED',self.status()['state'])
        self.assertEqual(before,self.status()['admission_revision'])
        value={**self.renewal(),'request_id':'2'*32}
        with self.auth(),self.assertRaises(RuntimeError):self.invoke(value,callback=Mock(side_effect=RuntimeError('synthetic callback failure')))
        self.assertEqual('AUTH_REQUIRED',self.status()['state'])
        with self.auth() as auth:
            self.assertEqual('READBACK_ONLY',self.invoke(value)['renewal']);auth.assert_not_called()

    def test_cancel_does_not_extend_a_still_valid_lease(self):
        before=self.app._auth_deadline
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',side_effect=AdmissionError()):
            with self.assertRaises(AdmissionError):self.invoke()
        self.assertEqual(before,self.app._auth_deadline)

    def test_missing_host_identity_never_generates_a_replacement_for_existing_history(self):
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        root=self.app.root;self.app.close();(root/'host-signing-key.pem').unlink()
        with self.auth() as auth,self.assertRaises((AdmissionError,ValueError)):
            NativeMobileComposition(root,origin='https://host.example.org',source_probe=lambda:tuple(self.source),existing_profile=True)
        auth.assert_not_called();self.assertFalse((root/'host-signing-key.pem').exists())

    def test_host_identity_removed_during_policykit_fails_before_replacement(self):
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        root=self.app.root;self.app.close()
        def removed():
            (root/'host-signing-key.pem').unlink();return os.getuid(),{'uid':os.getuid(),'test_only':True}
        with patch('runtime.meta_hackathon.runtime_adapter._desktop_operator_uid',side_effect=removed),self.assertRaises((AdmissionError,ValueError)):
            NativeMobileComposition(root,origin='https://host.example.org',source_probe=lambda:tuple(self.source),existing_profile=True)
        self.assertFalse((root/'host-signing-key.pem').exists())

    def test_final_status_read_failure_leaves_renewal_closed_after_commit(self):
        value=self.renewal();snapshot=self.status()
        with self.auth(),patch.object(self.app,'operator_auth_status',side_effect=[snapshot,RuntimeError('synthetic read ACK loss')]):
            with self.assertRaises(RuntimeError):self.invoke(value)
        self.assertEqual(0,self.app._auth_deadline)

    def test_existing_database_removed_at_sqlite_open_is_not_recreated(self):
        import sqlite3
        from runtime.memory_patch.persistence.ports import LocalCoreRecordFactory
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.mobile_gateway.desktop import validate_existing_profile
        root=self.app.root;self.app.close();expected=validate_existing_profile(root)
        original=sqlite3.connect
        def removed(*args,**kwargs):
            (root/'core-records.sqlite3').unlink();return original(*args,**kwargs)
        with patch('sqlite3.connect',side_effect=removed),self.assertRaises((sqlite3.Error,MemoryPatchError)):
            LocalCoreRecordFactory(root/'core-records.sqlite3',self.app.core,expected_file=expected)
        self.assertFalse((root/'core-records.sqlite3').exists())

    def test_host_key_replaced_at_actual_open_is_denied(self):
        from pathlib import Path
        from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
        root=self.app.root;self.app.close();key=root/'host-signing-key.pem'
        replacement=root/'synthetic-replacement';replacement.write_bytes(key.read_bytes());replacement.chmod(0o600)
        original=os.open
        def replaced(path,*args,**kwargs):
            if Path(path)==key:os.replace(replacement,key)
            return original(path,*args,**kwargs)
        with self.auth(),patch('os.open',side_effect=replaced),self.assertRaises(AdmissionError):
            NativeMobileComposition(root,origin='https://host.example.org',source_probe=lambda:tuple(self.source),existing_profile=True)

    def test_native_budget_review_binds_source_and_instance_and_never_calls_a_model(self):
        self.chat_host()
        value={'op':'budget_review','request_id':'d'*32,'total_usd':'148'}
        with patch('runtime.providers.meta_model_api._https_once') as transport:
            review=self.app.operator_request(os.getuid(),value)
            bad={**review,'source_sha':'e'*40}
            with self.assertRaises((ValueError,wire.MobileError,AdmissionError)):
                self.app.operator_request(os.getuid(),{'op':'budget_approve','review':bad})
            result=self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
            self.assertEqual('148',result['allocation_usd']);self.assertEqual('UNVERIFIED',result['provider_balance_status'])
            self.assertFalse(result['paid_calls_authorized']);transport.assert_not_called()

    def test_credit_attestation_is_expiring_key_bound_and_replay_cannot_extend_it(self):
        self.chat_host()
        review=self.app.operator_request(os.getuid(),{'op':'budget_review','request_id':'c'*32,
            'total_usd':'148','observed_credit_usd':'148'})
        self.assertIsNone(self.app._credit_observation)
        result=self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertEqual('OWNER_ATTESTED',result['provider_balance_status']);self.assertTrue(self.app._chat_credit_authority(None))
        expires=self.app._credit_observation['expires_at']
        self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertEqual(expires,self.app._credit_observation['expires_at'])
        with patch('time.time',return_value=expires):self.assertFalse(self.app._chat_credit_authority(None))
        info=self.app._meta_key_path.stat();os.utime(self.app._meta_key_path,ns=(info.st_atime_ns,info.st_mtime_ns+1))
        self.assertFalse(self.app._chat_credit_authority(None))

    def credit_review(self):
        return self.app.operator_request(os.getuid(),{'op':'budget_review','request_id':'b'*32,
            'total_usd':'148','observed_credit_usd':'148'})

    def test_budget_commit_rechecks_native_lease_inside_transaction(self):
        self.chat_host();review=self.credit_review();governor=self.app.chat_governor
        reader=self.app.core.local_operator(Capability.READ);before=governor.inspect(reader)
        original=governor.apply_money_policy
        def expire(*args,**kwargs):
            self.app._auth_deadline=0
            return original(*args,**kwargs)
        with patch.object(governor,'apply_money_policy',side_effect=expire):
            with self.assertRaises(MemoryPatchError) as denied:
                self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertIsInstance(denied.exception.__cause__,AdmissionError)
        self.assertEqual(before,governor.inspect(reader));self.assertIsNone(self.app._credit_observation)

    def test_credit_commit_rechecks_source_inside_transaction(self):
        self.chat_host();review=self.credit_review();original=self.app.mobile._run
        def drift(cap,callback):
            if cap is Capability.COMMIT:self.source[0]='e'*40
            return original(cap,callback)
        with patch.object(self.app.mobile,'_run',side_effect=drift):
            with self.assertRaises(MemoryPatchError) as denied:
                self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertIsInstance(denied.exception.__cause__,AdmissionError)
        self.assertIsNone(self.app._credit_observation)
        self.assertIsNone(self.app.mobile._get('native-meta-credit-'+'b'*32))

    def test_credit_commit_ack_loss_and_renewal_do_not_publish_or_reuse_credit(self):
        self.chat_host();review=self.credit_review();original=self.app.mobile._run
        def lost(cap,callback):
            result=original(cap,callback)
            if cap is Capability.COMMIT:raise RuntimeError('synthetic credit ACK loss')
            return result
        with patch.object(self.app.mobile,'_run',side_effect=lost):
            with self.assertRaises(RuntimeError):
                self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertFalse(self.app._chat_credit_authority(None))
        self.app.operator_request(os.getuid(),{'op':'budget_approve','review':review})
        self.assertTrue(self.app._chat_credit_authority(None))
        with self.auth():self.invoke()
        self.assertIsNone(self.app._credit_observation);self.assertIsNone(self.app._credit_policy_binding)
        self.assertFalse(self.app._chat_credit_authority(None));self.assertEqual(0,self.app.model_calls())


if __name__=='__main__':unittest.main()
