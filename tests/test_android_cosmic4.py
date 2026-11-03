"""Disjoint Cosmic4 build/signing channel. Offline fixtures are not an APK build."""
import unittest
from cryptography.hazmat.primitives.asymmetric import ec
from scripts.android import verify_apk, ci_build
from tests.test_android_postmerge_ci import context, SHA


class Cosmic4ChannelTests(unittest.TestCase):
    def channel(self):
        from scripts.android import cosmic4_channel
        return cosmic4_channel

    def metadata(self):
        c=self.channel()
        return {'package':c.PACKAGE,'version_code':400,'version_name':'4.0.0-cosmic',
                'certificate_sha256':c.CERTIFICATE}

    def test_cosmic4_exact_identity_and_old_channel_are_disjoint(self):
        c=self.channel(); new=self.metadata()
        verify_apk.assert_source_identity(new,channel=c.CHANNEL)
        with self.assertRaises(verify_apk.lib.Blocked):verify_apk.assert_source_identity(new)
        for field,value in [('package','eu.sparkhat.aioa.companion'),('version_code',4),
            ('version_name','0.3.1-cosmic'),('certificate_sha256','0'*64)]:
            with self.subTest(field=field),self.assertRaises(verify_apk.lib.Blocked):
                verify_apk.assert_source_identity({**new,field:value},channel=c.CHANNEL)
        with self.assertRaises(verify_apk.lib.Blocked):
            verify_apk.assert_source_identity(new,channel='UNREVIEWED')

    def test_apk_metadata_channel_does_not_allow_foreign_permissions(self):
        c=self.channel()
        raw=(f"package: name='{c.PACKAGE}' versionCode='400' versionName='4.0.0-cosmic'\n"
             "sdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\napplication-debuggable\n")
        self.assertEqual(c.PACKAGE,verify_apk.parse_badging(raw,channel=c.CHANNEL)['package'])
        with self.assertRaises(verify_apk.lib.Blocked):verify_apk.parse_badging(raw)
        for permission in ['android.permission.READ_SMS',verify_apk.RECEIVER_PERMISSION]:
            with self.assertRaises(verify_apk.lib.Blocked):
                verify_apk.parse_badging(raw+f"uses-permission: name='{permission}'\n",channel=c.CHANNEL)

    def test_narrow_owner_branch_context_and_exact_variant_tasks(self):
        c=self.channel()
        env=context();env.update(GITHUB_REF=c.SOURCE_REF,
            GITHUB_WORKFLOW_REF='luciferprosun/AIOA-spArkHAT/'+ci_build.WORKFLOW_PATH+'@'+c.SOURCE_REF,
            AIOA_APK_CHANNEL=c.CHANNEL)
        ci_build.context_check(env,SHA,'20261026.354.1')
        for field,value in [('GITHUB_REF','refs/heads/attacker'),('GITHUB_ACTOR','attacker'),
            ('GITHUB_WORKFLOW_SHA','f'*40),('AIOA_APK_CHANNEL','ORIGINAL'),('GITHUB_RUN_ATTEMPT','2')]:
            with self.subTest(field=field),self.assertRaises(ci_build.lib.Blocked):
                ci_build.context_check({**env,field:value},SHA,'20261026.354.1')
        main=context();main['AIOA_APK_CHANNEL']=c.CHANNEL
        with self.assertRaises(ci_build.lib.Blocked):ci_build.context_check(main,SHA,'20261026.354.1')
        from pathlib import Path
        from scripts.android import build_apk
        tasks=build_apk.command(Path('/qualified/cache'),Path('/qualified/init'),channel=c.CHANNEL)[-3:]
        self.assertEqual(['testCosmic4UnitTest','lintCosmic4','assembleCosmic4'],tasks)

    def test_missing_signer_never_generates_or_writes_a_replacement(self):
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(ci_build.lib.Blocked):self.channel().prepare_signer(root,root,{}, {})
            self.assertEqual([],list(root.iterdir()))

    def test_signer_password_is_scoped_environment_not_source_or_command(self):
        from pathlib import Path
        from scripts.android import build_apk
        script=build_apk.init_script(Path('/private/job'),channel=self.channel().CHANNEL)
        self.assertIn("System.getenv('AIOA_COSMIC4_PASSWORD')",script)
        self.assertIn("signing.storeType = 'PKCS12'",script)
        self.assertNotIn("storePassword = 'android'",script)
        default=build_apk.init_script(Path('/private/job'))
        self.assertIn("signing.storeType = 'JKS'",default)
        self.assertNotIn('COSMIC4',default)


class UsbHostContractTests(unittest.TestCase):
    def helper(self):
        from scripts.android import provision_usb
        return provision_usb

    def test_android_content_stdout_has_exact_result_prefix_and_no_extra_output(self):
        import base64
        from runtime.mobile_gateway import wire
        value={'schema':'public fixture'}
        encoded=base64.urlsafe_b64encode(wire.canonical(value)).decode().rstrip('=')
        raw='Result: Bundle[{json_b64='+encoded+'}]'+chr(10)
        self.assertEqual(value,self.helper().parse_content_stdout(raw))
        for bad in [raw+'extra',raw.replace('Result: ',''),'Error: denied'+chr(10)+raw,raw.replace(encoded,encoded+'=')]:
            with self.assertRaises(ValueError):self.helper().parse_content_stdout(bad)

    def test_exact_usb_identity_proves_key_possession_and_binds_package_signer_source(self):
        from runtime.mobile_gateway import wire
        identity=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        from scripts.android import cosmic4_channel as c
        proof={'schema':'aioa.mobile.usb-identity.v1','challenge':'c'*64,'issued_at':1000,
            'package':c.PACKAGE,'certificate_sha256':c.CERTIFICATE,'apk_source_sha':'a'*40,'device_spki':identity.spki}
        value={'proof':proof,'signature':identity.sign(proof)}
        self.assertEqual(identity.spki,self.helper().verify_identity(value,'c'*64,'a'*40,1001))
        for key,bad in [('challenge','d'*64),('package','other.app'),('certificate_sha256','0'*64),
            ('apk_source_sha','b'*40),('issued_at',900)]:
            changed={**proof,key:bad}; signed={'proof':changed,'signature':identity.sign(changed)}
            with self.subTest(key=key),self.assertRaises(ValueError):self.helper().verify_identity(signed,'c'*64,'a'*40,1001)
        with self.assertRaises(ValueError):self.helper().verify_identity({**value,'signature':'AAAA'},'c'*64,'a'*40,1001)

    def test_pending_must_exactly_bind_phone_record_device_digest_and_sas(self):
        p=self.helper()
        device='a'*64; record={'request_id':'b'*32,'request_digest':'c'*64,'expires_at':1300}
        pending={**record,'device_id':device,'sas':p.sas(record['request_digest']),'state':'PENDING',
            'device_name':'AIOA Android','automatic_retry':False}
        p.verify_pending(pending,record,device,1001)
        for key,value in [('device_id','0'*64),('request_id','0'*32),('request_digest','0'*64),
            ('sas','000000'),('state','APPROVED'),('expires_at',1000),('automatic_retry',True)]:
            with self.subTest(key=key),self.assertRaises(ValueError):p.verify_pending({**pending,key:value},record,device,1001)

    def test_installed_bytes_must_match_reviewed_apk_before_identity_is_trusted(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        p=self.helper()
        with tempfile.TemporaryDirectory() as directory:
            apk=Path(directory)/'reviewed.apk';apk.write_bytes(b'controlled APK fixture')
            delivery=p.UsbDelivery('C6QWKF4P7DFEUCQ4','a'*40,Path(directory),Path(directory)/'evidence',apk)
            with patch.object(delivery,'installed_bytes',return_value=b'controlled APK fixture'):
                delivery.verify_installation()
            with patch.object(delivery,'installed_bytes',return_value=b'repacked different APK'):
                with self.assertRaises(ValueError):delivery.verify_installation()

    def test_first_usb_stage_starts_from_idle_process_even_if_activity_is_already_open(self):
        from pathlib import Path
        from unittest.mock import patch
        p=self.helper();delivery=p.UsbDelivery('C6QWKF4P7DFEUCQ4','a'*40,Path('/state'),Path('/out'),Path('/apk'))
        spki='public-key-fixture'
        empty={'pairing':None,'binding_invalid':False,'device_spki':spki,'apk_source_sha':'a'*40,'delivery':{'delivery':'EMPTY'}}
        events=[]
        with patch.object(delivery,'call',side_effect=lambda op: events.append('read') or empty), \
            patch.object(delivery,'adb',side_effect=lambda *args: events.append(args)):
            delivery.prepare_idle_installation(spki)
        self.assertEqual(['read',('shell','am','force-stop','eu.sparkhat.aioa.companion.cosmic4'),'read'],events)
        for bad in [{**empty,'pairing':{'request_id':'uncertain'}}, {**empty,'delivery':{'delivery':'STARTED_NO_AUTOMATIC_RETRY'}},
                    {**empty,'device_spki':'substituted'},{**empty,'binding_invalid':True}]:
            with patch.object(delivery,'call',return_value=bad),patch.object(delivery,'adb') as mutate:
                with self.assertRaises(ValueError):delivery.prepare_idle_installation(spki)
                mutate.assert_not_called()

    def test_approval_claim_survives_restart_and_ack_loss(self):
        import tempfile
        from pathlib import Path
        p=self.helper()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'approval-attempt.json'
            p.claim_approval(path,{'request_id':'a'*32,'request_digest':'b'*64,'sas':'123456'})
            original=path.read_bytes()
            with self.assertRaises(ValueError):p.claim_approval(path,{'request_id':'a'*32,'request_digest':'b'*64,'sas':'123456'})
            self.assertEqual(original,path.read_bytes())

    def test_core_readback_must_match_actual_android_proof_not_a_fresh_other_session(self):
        from runtime.mobile_gateway import wire
        identity=wire.Identity(ec.generate_private_key(ec.SECP256R1())); device='a'*64
        proof={'schema':wire.OBSERVATION if hasattr(wire,'OBSERVATION') else 'aioa.mobile.observation.v1',
            'device_id':device,'session_id':'b'*32,'nonce':'c'*32,'method':'GET','path':wire.BASE+'/status',
            'audience':identity.audience,'source_sha':'d'*40,'capsule_digest':'e'*64,'owner_scope_digest':'f'*64,
            'issued_at':1000,'expires_at':1030,'data_sha256':'1'*64}
        observation={'proof':proof,'signature':identity.sign(proof)}
        app={**observation,'fresh':True}
        self.helper().verify_status_readback(app,[observation],identity.spki,device,'d'*40,'e'*64,1001)
        for observations,time in [([],1001),([observation],1030),([{'proof':{**proof,'nonce':'0'*32},'signature':observation['signature']}],1001)]:
            with self.assertRaises(ValueError):self.helper().verify_status_readback(app,observations,identity.spki,device,'d'*40,'e'*64,time)


if __name__=='__main__':unittest.main()
