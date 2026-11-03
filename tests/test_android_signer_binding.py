"""Offline signer/artifact contracts. No real keytool, keystore or APK claim."""
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from scripts.android import build_apk as build,ci_build as ci


class ControlledDebugSignerTests(unittest.TestCase):
    def generated(self,root):
        calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            if '-genkeypair' in argv:
                p=Path(argv[argv.index('-keystore')+1]);p.write_bytes(b'fixture-private-key');p.chmod(0o600)
            else:
                p=Path(argv[argv.index('-file')+1]);p.write_bytes(b'fixture-public-certificate');p.chmod(0o600)
            return 0
        with patch.object(build,'run_logged',side_effect=run):
            marker=build.prepare_debug_signer(root,Path('/qualified/jdk'),{'PATH':'/usr/bin:/bin'})
        return marker,calls

    def test_ephemeral_debug_signer_is_generated_in_owned_output_and_never_exported(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);marker,calls=self.generated(root)
            self.assertEqual(2,len(calls));self.assertIn('-genkeypair',calls[0]);self.assertIn('-exportcert',calls[1])
            self.assertEqual('/qualified/jdk/bin/keytool',calls[0][0])
            self.assertIn('JKS',calls[0]);self.assertIn('androiddebugkey',calls[0])
            self.assertEqual(build.lib.sha(root/'debug-certificate.der'),marker['certificate_sha256'])
            self.assertEqual(0o600,(root/'debug.keystore').stat().st_mode & 0o777)
            self.assertTrue((root/'DEBUG_SIGNER.json').is_file())
            self.assertNotIn('private_key',marker)

    def test_existing_key_or_symlink_is_never_replaced_or_reused(self):
        for symlink in (False,True):
            with self.subTest(symlink=symlink),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);p=root/'debug.keystore'
                if symlink:p.symlink_to(root/'missing')
                else:p.write_bytes(b'existing operator data')
                with patch.object(build,'run_logged',side_effect=AssertionError('keytool called')):
                    with self.assertRaises(build.lib.Blocked):build.prepare_debug_signer(root,Path('/qualified/jdk'),{})

    def test_wrong_apk_signer_or_changed_private_key_denies_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);marker,_=self.generated(root)
            build.assert_debug_signer({'certificate_sha256':marker['certificate_sha256']},root)
            with self.assertRaises(build.lib.Blocked):build.assert_debug_signer({'certificate_sha256':'0'*64},root)
            (root/'debug.keystore').write_bytes(b'replacement fixture')
            with self.assertRaises(build.lib.Blocked):build.assert_debug_signer({'certificate_sha256':marker['certificate_sha256']},root)

    def test_init_uses_controlled_debug_key_format(self):
        text=build.init_script(Path('/qualified/output'))
        self.assertIn("storeType = 'JKS'",text)
        self.assertIn("keyAlias = 'androiddebugkey'",text)

    def test_verified_artifact_copy_checks_hash_signer_and_metadata_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);apk=root/'app.apk';apk.write_bytes(b'fixture-apk')
            evidence={'apk_sha256':build.lib.sha(apk),'certificate_sha256':'a'*64,'package':'eu.sparkhat.aioa.companion',
                'bytes':apk.stat().st_size,'version_code':3,'version_name':'0.3.0-cosmic','min_sdk':26,'target_sdk':36,
                'permissions':['android.permission.INTERNET'],'signature_permissions':{},'junit_pass':10,'junit_fail':0,'junit_skip':0,
                'lint_errors':0,'report_digests':[],'debuggable':True,'kind':'DEBUG',
                'inspected_checkout_sha':'a'*40}
            with patch.object(ci.verify_apk,'verify',return_value=evidence) as inspect,\
                patch.object(build,'assert_debug_signer',return_value=None):
                artifact=ci.verified_artifact(apk,root,evidence,sdk=Path('/sdk'),jdk=Path('/jdk'),source_sha='a'*40,environment={})
                self.assertEqual(apk.read_bytes(),(artifact/'aioa-companion-debug.apk').read_bytes())
                inspect.assert_called_once()
            for change in [{'certificate_sha256':'b'*64},{'apk_sha256':'0'*64},{'package':'other'},
                {'signature_permissions':{'other.app':'normal'}}]:
                with self.subTest(change=change),tempfile.TemporaryDirectory() as other:
                    destination=Path(other);source=destination/'app.apk';source.write_bytes(b'fixture-apk')
                    with patch.object(ci.verify_apk,'verify',return_value={**evidence,**change}),\
                        patch.object(build,'assert_debug_signer',return_value=None):
                        with self.assertRaises(build.lib.Blocked):
                            ci.verified_artifact(source,destination,evidence,sdk=Path('/sdk'),jdk=Path('/jdk'),source_sha='a'*40,environment={})

    def test_successful_ci_execution_records_versions_from_verified_catalog(self):
        # Full orchestration contract with tools mocked: not a JVM/build claim.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);apk=root/'builds/_app/outputs/apk/debug/app-debug.apk'
            apk.parent.mkdir(parents=True);apk.write_bytes(b'fixture-apk')
            artifact=root/'artifact';artifact.mkdir()
            evidence={'status':'DEBUG_APK_VERIFIED_HOST_ONLY','apk_sha256':ci.lib.sha(apk)}
            argv=['./gradlew','testDebugUnitTest','lintDebug','assembleDebug']
            with patch.object(ci,'prepare',return_value=(root,Path('/jdk'),Path('/sdk'),{}, {},root/'redirect.gradle',argv)),\
                patch.object(build,'run_logged',return_value=0),\
                patch.object(ci.lib,'source_check'),patch.object(ci.lib,'gradle_configuration_check'),\
                patch.object(ci,'sdk_inventory',return_value={}),\
                patch.object(ci.verify_apk,'verify',return_value=dict(evidence)),\
                patch.object(ci.installer,'component_check'),\
                patch.object(build,'_bind_controlled_build',side_effect=lambda e,*_:e),\
                patch.object(build,'prepare_debug_signer',create=True),\
                patch.object(ci,'verified_artifact',return_value=artifact,create=True):
                result=ci.execute({'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'},'a'*40,ci.REVIEWED_IMAGE_VERSION)
            self.assertEqual(ci.installer.catalog()['versions'],result['versions'])

    def test_independent_sha256sum_mismatch_blocks_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);apk=root/'app.apk';apk.write_bytes(b'fixture-apk')
            evidence={'apk_sha256':ci.lib.sha(apk),'certificate_sha256':'a'*64,'package':'eu.sparkhat.aioa.companion',
                'bytes':apk.stat().st_size,'version_code':3,'version_name':'0.3.0-cosmic','min_sdk':26,'target_sdk':36,
                'permissions':['android.permission.INTERNET'],'signature_permissions':{},'junit_pass':10,'junit_fail':0,'junit_skip':0,
                'lint_errors':0,'report_digests':[],'debuggable':True,'kind':'DEBUG','inspected_checkout_sha':'a'*40}
            with patch.object(ci.verify_apk,'verify',return_value=evidence),\
                patch.object(build,'assert_debug_signer'),\
                patch.object(ci.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'0'*64+'  '+str(root/'artifact/aioa-companion-debug.apk')+'\n','')):
                with self.assertRaises(build.lib.Blocked):
                    ci.verified_artifact(apk,root,evidence,sdk=Path('/sdk'),jdk=Path('/jdk'),source_sha='a'*40,environment={})


if __name__=='__main__':unittest.main()
