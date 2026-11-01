"""R4/R6 regressions, offline native-probe fixtures only; no real JVM/CI."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from scripts.android import ci_build as ci
from test_android_postmerge_ci import context,SHA,IMAGE,ROOT
import test_android_image_metadata as image_tests


class ApkUpdateDiagnosticsTests(unittest.TestCase):
    def execution_failure(self,*,purpose='apk',verification_error=None):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        parent=Path(tmp.name);root=parent/'aioa-android-123-1';root.mkdir(mode=0o700)
        env={**context(),'RUNNER_TEMP':str(parent)}
        argv=['./gradlew','testDebugUnitTest','lintDebug','assembleDebug']
        def run(command,**kwargs):
            if command[-1]=='--format=json':text=json.dumps({'version':'2.27.3'});code=0
            elif purpose=='codeql':text='> Task :app:compileDebugKotlin FAILED\n';code=1
            else:text='> Task :app:testDebugUnitTest\n> Task :app:lintDebug\n> Task :app:assembleDebug\n';code=0
            kwargs['log'].write_text(text);kwargs['log'].chmod(0o600);return code
        with contextlib.ExitStack() as stack:
            for obj,name,options in [(ci,'preflight',{}),(ci,'prepare',{'return_value':(root,root/'jdk-17',root/'sdk',{}, {},root/'init.gradle',argv)}),
                (ci,'codeql_tool_check',{'return_value':(Path('/trusted/codeql'),Path('/trusted/db'))}),
                (ci.build_apk,'prepare_debug_signer',{}),(ci.build_apk,'run_logged',{'side_effect':run}),
                (ci.lib,'source_check',{}),(ci.lib,'gradle_configuration_check',{}),
                (ci,'sdk_inventory',{'return_value':{}}),(ci.installer,'component_check',{}),
                (ci.verify_apk,'verify',{'side_effect':ci.lib.Blocked(verification_error or 'BLOCKED_APK_CONTRACT')})]:
                stack.enter_context(patch.object(obj,name,**options))
            with self.assertRaises(ci.lib.Blocked):ci.build(env,SHA,IMAGE,purpose=purpose)
        return json.loads((parent/('aioa-failure-123-1-'+purpose)/'BUILD_FAILURE_EVIDENCE.json').read_text())

    def test_verifier_junit_or_lint_failure_is_not_reported_as_signature_failure(self):
        for code,stage,role in [('BLOCKED_JUNIT_MISSING','JVM_TESTS','JUNIT_REPORT'),('BLOCKED_LINT_RESULT','LINT','LINT_REPORT')]:
            with self.subTest(code=code):
                v=self.execution_failure(verification_error=code)
                self.assertEqual(stage,v['stage']);self.assertEqual(role,v['path_role'])
                self.assertEqual(code,v['error_code']);self.assertEqual('FAIL',v['stage_statuses'][stage])
                self.assertNotEqual('FAIL',v['stage_statuses']['SIGNATURE_VERIFY'])

    def test_codeql_compile_failure_remains_codeql_without_running_marker(self):
        v=self.execution_failure(purpose='codeql')
        self.assertEqual('CODEQL',v['stage']);self.assertEqual('FAIL',v['stage_statuses']['CODEQL'])
        self.assertNotEqual('FAIL',v['stage_statuses']['GRADLE_BOOTSTRAP'])
        self.assertNotIn('RUNNING',v['stage_statuses'].values())
        for stage in ('JVM_TESTS','LINT','ASSEMBLE'):self.assertEqual('NOT_RUN',v['stage_statuses'][stage])

    def probe(self,root,*,arch='amd64',javac='17.0.21'):
        jdk=root/'jdk-17';jdk.mkdir();calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            text=('java.home = '+str(jdk)+'\nos.arch = '+arch+'\nopenjdk version 17.0.21 Temurin-17.0.21+9\n'
                if argv[0].endswith('/java') else 'javac '+javac+'\n')
            kwargs['log'].write_text(text);kwargs['log'].chmod(0o600)
            return 0
        with patch.object(ci.build_apk,'run_logged',side_effect=run):
            result=ci.check_jdk(root,jdk,ci.environment(root,jdk,root/'sdk'))
        return calls,result

    def test_same_private_jdk_java_javac_and_arch_are_actually_probed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);calls,result=self.probe(root)
            self.assertEqual(['java','javac'],[Path(x[0]).name for x in calls])
            self.assertTrue(all(str(root/'jdk-17/bin') in x[0] for x in calls))
            self.assertEqual('amd64',result['architecture']);self.assertEqual('17.0.21',result['javac_version'])

    def test_wrong_javac_or_arch_is_rejected_before_gradle(self):
        for kwargs in [{'javac':'21.0.1'},{'arch':'aarch64'}]:
            with self.subTest(kwargs=kwargs),tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ci.lib.Blocked):self.probe(Path(directory),**kwargs)

    def test_prepare_error_before_root_keeps_original_code_role_and_not_run(self):
        with tempfile.TemporaryDirectory() as directory:
            parent=Path(directory);env={**context(),'RUNNER_TEMP':str(parent)}
            error=ci.lib.Blocked('BLOCKED_SYMLINK')
            error.ci_stage='JDK_PREPARE';error.ci_path_role='JDK_ROOT'
            with patch.object(ci,'preflight'),patch.object(ci,'execute',side_effect=error):
                with self.assertRaises(ci.lib.Blocked):ci.build(env,SHA,IMAGE)
            self.assertFalse((parent/'aioa-android-123-1').exists())
            p=parent/'aioa-failure-123-1-apk/BUILD_FAILURE_EVIDENCE.json';v=json.loads(p.read_text())
            self.assertEqual('BLOCKED_SYMLINK',v['error_code']);self.assertEqual('JDK_PREPARE',v['stage'])
            self.assertEqual('JDK_ROOT',v['path_role']);self.assertEqual([],v['logs']);self.assertIsNone(v['exit_code'])
            for stage in ('JVM_TESTS','LINT','ASSEMBLE','SIGNATURE_VERIFY','ARTIFACT_UPLOAD','CODEQL'):
                self.assertEqual('NOT_RUN',v['stage_statuses'][stage])
            self.assertNotIn('JAVA_HOME',p.read_text());self.assertNotIn(str(parent),p.read_text())

    def test_native_stage_annotation_carries_actual_failure_without_root(self):
        stages=ci.new_stages()
        try:
            with ci.phase(stages,'JDK_PREPARE','JOB_ROOT'):
                raise ci.lib.Blocked('BLOCKED_SYMLINK')
        except ci.lib.Blocked as error:
            self.assertEqual('JDK_PREPARE',error.ci_stage);self.assertEqual('JOB_ROOT',error.ci_path_role)
            self.assertEqual('FAIL',error.ci_stage_statuses['JDK_PREPARE'])
            self.assertEqual('NOT_RUN',error.ci_stage_statuses['JVM_TESTS'])

    def test_failed_jvm_task_does_not_invent_lint_or_assemble(self):
        stages=ci.new_stages()
        stage=ci.gradle_stages('> Task :app:compileDebugKotlin\n> Task :app:testDebugUnitTest FAILED\n',stages)
        self.assertEqual('JVM_TESTS',stage);self.assertEqual('FAIL',stages['JVM_TESTS'])
        self.assertEqual('NOT_RUN',stages['LINT']);self.assertEqual('NOT_RUN',stages['ASSEMBLE'])

    def test_no_second_jdk_setup_and_same_private_home_exported_for_codeql(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        self.assertNotIn('actions/setup-java@',(ROOT/'.github/workflows/android-manual-build.yml').read_text())
        compile_step=next(s for s in workflow['jobs']['codeql-kotlin']['steps'] if s.get('id')=='controlled_build')
        self.assertIn('JAVA_HOME=',compile_step['run']);self.assertIn('GITHUB_ENV',compile_step['run'])
        self.assertIn('/jdk-17',compile_step['run'])

    def test_conflicting_image_values_are_recorded_before_refusal(self):
        helper=image_tests.ImageMetadataConsistencyTests();ns,_=helper.bootstrap();out=io.StringIO()
        with contextlib.redirect_stdout(out),self.assertRaises(SystemExit):
            ns['check_image'](helper.raw('20261025.353.1'),{'ImageVersion':'20261026.354.1'})
        record=json.loads(out.getvalue().splitlines()[0])
        self.assertEqual('20261025.353.1',record['metadata_version'])
        self.assertEqual('20261026.354.1',record['declared_version'])
        self.assertEqual(64,len(record['metadata_sha256']))
        w=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        run=w['jobs']['debug-apk']['steps'][0]['run']
        self.assertLess(run.index('python3 -B'),run.index('test "$ImageVersion"'))


if __name__=='__main__':unittest.main()
