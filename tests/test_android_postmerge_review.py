"""Independent review reproductions; fake CLI/logs, never a real Android build."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import yaml
from scripts.android import ci_build as ci
import test_android_codeql as codeql_tests
from test_android_postmerge_ci import context,SHA,IMAGE,ROOT


class AndroidPostmergeReviewTests(unittest.TestCase):
    def test_trace_cli_source_root_does_not_override_android_wrapper_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);android=root/'clients/android';android.mkdir(parents=True)
            wrapper=android/'gradlew';wrapper.write_text('#!/bin/sh\npwd\n');wrapper.chmod(0o700)
            tool=root/'codeql';db=root/'database';db.mkdir()
            # Model documented CLI fallback, rather than Python's process cwd.
            tool.write_text('#!/usr/bin/python3\nimport os,sys,subprocess\n'
                'work=next((a.split("=",1)[1] for a in sys.argv if a.startswith("--working-dir=")),'+repr(str(root))+')\n'
                'raise SystemExit(subprocess.run(sys.argv[sys.argv.index("--")+1:],cwd=work).returncode)\n')
            tool.chmod(0o700)
            with patch.object(ci.lib,'REPO',root),patch.object(ci,'codeql_tool_check',return_value=(tool,db)):
                argv=ci.codeql_command({},root/'cache',root/'init.gradle')
            result=subprocess.run(argv,cwd=android,env={'PATH':'/usr/bin:/bin'},capture_output=True,text=True,timeout=10)
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertEqual(str(android),result.stdout.strip())

    def test_all_analyze_steps_disable_database_publication(self):
        for name in ('android-manual-build.yml','codeql-static.yml'):
            workflow=yaml.safe_load((ROOT/'.github/workflows'/name).read_text())
            for job in workflow['jobs'].values():
                for step in job.get('steps',[]):
                    if step.get('uses','').startswith('github/codeql-action/analyze@'):
                        with self.subTest(workflow=name):self.assertIs(False,step['with'].get('upload-database'))

    def test_weekly_scanning_is_preserved_without_automatic_android_build(self):
        static=yaml.safe_load((ROOT/'.github/workflows/codeql-static.yml').read_text())
        self.assertEqual([{'cron':'17 3 * * 1'}],static['on'].get('schedule'))
        self.assertIn('vars.AIOA_CODEQL_PROFILE',static['jobs']['analyze']['if'])
        apk=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        self.assertEqual({'workflow_dispatch'},set(apk['on']))

    def test_sarif_without_optional_revision_keeps_external_source_verification_pending(self):
        helper=codeql_tests.AndroidCodeQLContractTests()
        with tempfile.TemporaryDirectory() as directory:
            env,_=helper.readback_fixture(Path(directory))
            path=Path(directory)/'aioa-codeql-sarif/java.sarif'
            sarif=json.loads(path.read_text());sarif['runs'][0].pop('versionControlProvenance')
            path.write_text(json.dumps(sarif))
            result=helper.readback(env)
            self.assertFalse(result['server_upload_verified'])
            self.assertEqual('PENDING_SERVER_COMMIT_SHA_READBACK',result['source_verification_status'])
            self.assertEqual('ABSENT',result['sarif_embedded_revision'])
            self.assertEqual(env['AIOA_SARIF_ID'],result['server_sarif_id'])

    def test_missing_actual_analyze_upload_id_cannot_claim_a_server_binding(self):
        helper=codeql_tests.AndroidCodeQLContractTests()
        with tempfile.TemporaryDirectory() as directory:
            env,_=helper.readback_fixture(Path(directory));env.pop('AIOA_SARIF_ID',None)
            with self.assertRaises(ci.lib.Blocked):helper.readback(env)

    def test_failed_preflight_creates_no_failure_artifact_and_calls_no_tools(self):
        with patch.object(ci,'preflight',side_effect=ci.lib.Blocked('BLOCKED_CI_OWNER_OR_RUNNER_CONTEXT')),\
            patch.object(ci,'execute') as execute,patch.object(ci,'record_failure') as record:
            with self.assertRaises(ci.lib.Blocked):ci.build(context(),SHA,IMAGE)
            execute.assert_not_called();record.assert_not_called()

    def test_failed_attempt_retains_only_bounded_structured_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);env={**context(),'RUNNER_TEMP':str(base)}
            build=base/'aioa-android-123-1';build.mkdir(mode=0o700)
            source='clients/android/app/src/main/java/eu/sparkhat/aioa/companion/MobileClient.kt'
            taint='SYNTHETIC_PRIVATE_OPERATOR_MARKER'
            raw=('> Task :app:compileDebugKotlin FAILED\n'
                'e: file://'+str(ROOT/source)+':73:25 Unresolved reference '+taint+'\n'+taint+'\n').encode()
            log=build/'build.log';log.write_bytes(raw);log.chmod(0o600)
            error=ci.lib.Blocked('BLOCKED_CI_BUILD_FAILED');error.build_exit_code=1
            with patch.object(ci,'preflight'),patch.object(ci,'execute',side_effect=error):
                with self.assertRaises(ci.lib.Blocked):ci.build(env,SHA,IMAGE)
            path=base/'aioa-failure-123-1-apk/BUILD_FAILURE_EVIDENCE.json'
            value=json.loads(path.read_text())
            self.assertEqual('FAILED_NO_APK_PUBLICATION',value['status'])
            self.assertEqual(1,value['exit_code']);self.assertFalse(value['automatic_retry'])
            self.assertEqual(ci.lib.sha(log),value['logs'][0]['sha256'])
            self.assertEqual([{'path':source,'line':73,'column':25,'category':'UNRESOLVED_REFERENCE'}],value['compiler_locations'])
            self.assertNotIn(taint,path.read_text());self.assertNotIn(str(ROOT),path.read_text())
            self.assertFalse(value['apk_verified']);self.assertEqual('STRUCTURED_DIAGNOSTIC_AVAILABLE',value['diagnostic_status'])

    def test_unrecognized_or_tainted_output_does_not_become_a_raw_log_export(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);env={**context(),'RUNNER_TEMP':str(base)}
            root=base/'aioa-android-123-1';root.mkdir(mode=0o700)
            log=root/'build.log';log.write_text('unknown private output /home/operator/key\n');log.chmod(0o600)
            ci.record_failure(env,SHA,IMAGE,ci.lib.Blocked('UNTRUSTED_CODE_VALUE'))
            value=json.loads((base/'aioa-failure-123-1-apk/BUILD_FAILURE_EVIDENCE.json').read_text())
            self.assertEqual('DIAGNOSTIC_UNAVAILABLE',value['diagnostic_status'])
            self.assertEqual([],value['compiler_locations'])
            self.assertNotIn('/home/operator',json.dumps(value));self.assertNotIn('UNTRUSTED_CODE_VALUE',json.dumps(value))

    def test_failure_upload_is_separate_and_only_after_failed_controlled_build(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        for name in ('debug-apk','codeql-kotlin'):
            steps=workflow['jobs'][name]['steps']
            uploads=[s for s in steps if 'BUILD_FAILURE_EVIDENCE.json' in s.get('with',{}).get('path','')]
            self.assertEqual(1,len(uploads),name);step=uploads[0]
            self.assertIn('failure()',step['if']);self.assertIn("steps.controlled_build.outcome == 'failure'",step['if'])
            self.assertEqual(1,step['with']['retention-days'])
            self.assertNotIn('build.log',step['with']['path']);self.assertNotIn('apk',Path(step['with']['path']).suffix)


if __name__=='__main__':unittest.main()
