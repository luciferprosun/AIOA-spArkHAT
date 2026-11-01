"""APK parser and build gate tests, no actual APK/Gradle/JDK/drive."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


class AndroidBuildVerificationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.android.verify_apk'))
        self.verify=importlib.import_module('scripts.android.verify_apk')
        self.build=importlib.import_module('scripts.android.build_apk')

    def test_metadata_requires_exact_package_version_sdk_and_permissions(self):
        good="package: name='eu.sparkhat.aioa.companion' versionCode='2' versionName='0.2.0-n1'\nsdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\n"
        value=self.verify.parse_badging(good)
        self.assertEqual('eu.sparkhat.aioa.companion',value['package'])
        for bad in [good.replace("versionCode='2'","versionCode='1'"),good.replace("sdkVersion:'26'","sdkVersion:'25'"),
                    good.replace('eu.sparkhat.aioa.companion','other.package'),good+"uses-permission: name='android.permission.READ_SMS'\n"]:
            with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_badging(bad)

    def test_signature_is_debug_inventory_not_release_or_phone_certification(self):
        raw='Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate DN: CN=Android Debug, O=Android, C=US\nSigner #1 certificate SHA-256 digest: '+'a'*64+'\n'
        value=self.verify.parse_signature(raw)
        self.assertEqual('DEBUG',value['kind']);self.assertEqual('a'*64,value['certificate_sha256'])
        self.assertFalse(value['phone_tested'])
        with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_signature(raw.replace('CN=Android Debug','CN=Private Owner'))
        with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_signature('DOES NOT VERIFY')

    def test_failed_or_skipped_junit_and_lint_do_not_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);test=root/'TEST.xml';lint=root/'lint.xml'
            cases=''.join('<testcase name="case'+str(n)+'"/>' for n in range(10))
            test.write_text('<testsuite tests="10" failures="0" errors="0" skipped="0">'+cases+'</testsuite>');lint.write_text('<issues/>')
            self.assertEqual(10,self.verify.test_evidence([test],lint)['junit_pass'])
            for attrs in ['tests="10" failures="1" errors="0" skipped="0"','tests="10" failures="0" errors="0" skipped="1"']:
                test.write_text('<testsuite '+attrs+'/>')
                with self.assertRaises(self.verify.lib.Blocked):self.verify.test_evidence([test],lint)
            test.write_text('<testsuite tests="10" failures="0" errors="0" skipped="0">'+cases+'</testsuite>')
            lint.write_text('<issues><issue severity="Error"/></issues>')
            with self.assertRaises(self.verify.lib.Blocked):self.verify.test_evidence([test],lint)

    def test_junit_report_cannot_claim_success_without_actual_testcases(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);test=root/'TEST.xml';lint=root/'lint.xml'
            test.write_text('<testsuite tests="10" failures="0" errors="0" skipped="0"/>');lint.write_text('<issues/>')
            with self.assertRaises(self.verify.lib.Blocked):self.verify.test_evidence([test],lint)

    def test_bounded_child_process_logs_and_timeout_do_not_leave_a_worker(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            status=self.build.run_logged([sys.executable,'-I','-c','print("fixture")'],cwd=root,environment={'PATH':'/usr/bin:/bin'},log=root/'ok.log',timeout=2)
            self.assertEqual(0,status);self.assertEqual('fixture',(root/'ok.log').read_text().strip())
            with self.assertRaises(self.verify.lib.Blocked):
                self.build.run_logged([sys.executable,'-I','-c','import time;time.sleep(2)'],cwd=root,
                    environment={'PATH':'/usr/bin:/bin'},log=root/'timeout.log',timeout=.05)

    def test_local_build_is_blocked_before_process_or_directory_effect(self):
        with patch.object(self.build.lib,'admission',return_value={'status':'BLOCKED_STORAGE_TOOLCHAIN','may_stage':False}),\
             patch.object(self.build,'execute_build',side_effect=AssertionError('Gradle called')):
            result=self.build.build('a'*40)
            self.assertEqual('BLOCKED_STORAGE_TOOLCHAIN',result['status'])

    def test_build_command_is_bounded_and_uses_existing_wrapper(self):
        command=self.build.command(Path('/qualified/gradle-cache'),Path('/qualified/init.gradle'))
        for part in ['--no-daemon','--max-workers=1','testDebugUnitTest','lintDebug','assembleDebug']:self.assertIn(part,command)
        self.assertEqual('./gradlew',command[0]);self.assertNotIn('publish',command);self.assertNotIn('installDebug',command)


if __name__=='__main__':unittest.main()
