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
        good="package: name='eu.sparkhat.aioa.companion' versionCode='3' versionName='0.3.0-cosmic'\nsdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\n"
        value=self.verify.parse_badging(good)
        self.assertEqual('eu.sparkhat.aioa.companion',value['package'])
        for bad in [good.replace("versionCode='3'","versionCode='1'"),good.replace("sdkVersion:'26'","sdkVersion:'25'"),
                    good.replace('eu.sparkhat.aioa.companion','other.package'),good+"uses-permission: name='android.permission.READ_SMS'\n"]:
            with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_badging(bad)

    def test_signature_is_debug_inventory_not_release_or_phone_certification(self):
        raw='Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate DN: CN=Android Debug, O=Android, C=US\nSigner #1 certificate SHA-256 digest: '+'a'*64+'\n'
        value=self.verify.parse_signature(raw)
        self.assertEqual('DEBUG',value['kind']);self.assertEqual('a'*64,value['certificate_sha256'])
        self.assertFalse(value['phone_tested'])
        with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_signature(raw.replace('CN=Android Debug','CN=Private Owner'))
        with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_signature('DOES NOT VERIFY')

    def test_androidx_permission_requires_its_exact_signature_definition_in_the_apk(self):
        # AAPT-format fixture, not an actual APK or Android build claim.
        permission='eu.sparkhat.aioa.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'
        badging="package: name='eu.sparkhat.aioa.companion' versionCode='3' versionName='0.3.0-cosmic'\nsdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\nuses-permission: name='"+permission+"'\napplication-debuggable\n"
        declaration=('    E: permission (line=10)\n'
            '      A: android:name(0x01010003)="'+permission+'" (Raw: "'+permission+'")\n'
            '      A: android:protectionLevel(0x01010009)=(type 0x11)0x2\n')
        tree='N: android=http://schemas.android.com/apk/res/android\n  E: manifest (line=2)\n'+declaration+'    E: application (line=20)\n'
        signature='Verified using v2 scheme (APK Signature Scheme v2): true\nSigner #1 certificate DN: CN=Android Debug\nSigner #1 certificate SHA-256 digest: '+'a'*64+'\n'
        cases=[('signature',tree,True),('normal',tree.replace('0x2\n','0x0\n'),False),
            ('dangerous',tree.replace('0x2\n','0x1\n'),False),
            ('privileged',tree.replace('0x2\n','0x12\n'),False),
            ('wrong-package',tree.replace(permission,'other.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'),False),
            ('missing-definition','  E: manifest (line=2)\n    E: application (line=20)\n',False),
            ('duplicate-definition',tree.replace(declaration,declaration*2),False),
            ('nested-definition',tree.replace('    E: permission','      E: permission'),False)]
        for name,xml,allowed in cases:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);apk=root/'app.apk';apk.write_bytes(b'apk-fixture')
                reports=root/'builds/_app';(reports/'test-results/testDebugUnitTest').mkdir(parents=True);(reports/'reports').mkdir()
                (reports/'test-results/testDebugUnitTest/TEST-fixture.xml').write_text('<testsuite tests="1"><testcase name="fixture"/></testsuite>')
                (reports/'reports/lint-results-debug.xml').write_text('<issues/>')
                def tool(argv,**kwargs):
                    text=xml if argv[1:3]==['dump','xmltree'] else badging if Path(argv[0]).name=='aapt' else signature
                    return self.verify.subprocess.CompletedProcess(argv,0,text,'')
                with patch.object(self.verify.subprocess,'run',side_effect=tool) as calls:
                    if allowed:
                        try:result=self.verify.verify(apk,root,sdk=root/'sdk',jdk=root/'jdk',source_sha='a'*40,environment={})
                        except self.verify.lib.Blocked as error:self.fail('Valid AndroidX signature permission refused: '+error.code)
                        self.assertEqual({permission:'signature'},result['signature_permissions'])
                        self.assertTrue(any(c.args[0][1:3]==['dump','xmltree'] for c in calls.call_args_list))
                    else:
                        with self.assertRaises(self.verify.lib.Blocked) as error:
                            self.verify.verify(apk,root,sdk=root/'sdk',jdk=root/'jdk',source_sha='a'*40,environment={})
                        self.assertEqual('BLOCKED_APK_RECEIVER_PERMISSION',error.exception.code)

    def test_extra_or_foreign_permission_is_never_granted_by_androidx_compatibility(self):
        permission='eu.sparkhat.aioa.companion.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION'
        good="package: name='eu.sparkhat.aioa.companion' versionCode='3' versionName='0.3.0-cosmic'\nsdkVersion:'26'\ntargetSdkVersion:'36'\nuses-permission: name='android.permission.INTERNET'\nuses-permission: name='"+permission+"'\n"
        self.assertEqual(['android.permission.INTERNET',permission],self.verify.parse_badging(good)['permissions'])
        for bad in [good+"uses-permission: name='android.permission.READ_SMS'\n",
            good.replace(permission,'other.app.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION')]:
            with self.assertRaises(self.verify.lib.Blocked):self.verify.parse_badging(bad)

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
