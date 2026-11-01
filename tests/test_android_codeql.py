"""Prepared Kotlin tracing contract only: no compiler/CodeQL/Actions invocation."""
from pathlib import Path
import json
from contextlib import ExitStack
import tempfile
import unittest
from unittest.mock import patch

import yaml
from scripts.android import ci_build as ci
from test_android_postmerge_ci import context,SHA,IMAGE,ROOT


def codeql_context():
    return {**context(),'GITHUB_JOB':'codeql-kotlin','AIOA_CODEQL_REQUESTED':'true',
        'AIOA_CODEQL_ACK':'true','AIOA_CODEQL_PROFILE':'advanced-v1'}


class AndroidCodeQLContractTests(unittest.TestCase):
    def readback_fixture(self,root,*,build_changes=None,sarif_changes=None):
        env={**codeql_context(),'RUNNER_TEMP':str(root)}
        build=root/'aioa-android-123-1';build.mkdir(mode=0o700)
        (build/'build.log').write_text('controlled compile returned zero\n')
        (build/'redirect.gradle').write_text('controlled init')
        invocation={'schema':'aioa.android.controlled-build.v1','source_sha':SHA,'purpose':'codeql',
            'workflow_revision':ci.REVIEWED_WORKFLOW_SHA256,
            'init_sha256':ci.lib.sha(build/'redirect.gradle'),'command':['fixed-trace-command']}
        ci.installer.private_write(build/'BUILD_INVOCATION.json',invocation)
        evidence={'schema':'aioa.android.codeql-build.v1','status':'CODEQL_TRACED_BUILD_RETURNED_ZERO',
            'source_sha':SHA,'runner_image':IMAGE,'workflow_revision':ci.REVIEWED_WORKFLOW_SHA256,
            'command':invocation['command'],'codeql_version':'2.27.3','model_calls':0,'apk_built':False,
            'codeql_analyze_verified':False,'server_upload_verified':False,
            'build_log_sha256':ci.lib.sha(build/'build.log'),
            'build_invocation_sha256':ci.lib.sha(build/'BUILD_INVOCATION.json')}
        evidence.update(build_changes or {})
        ci.installer.private_write(build/'CODEQL_BUILD_EVIDENCE.json',evidence)
        output=root/'aioa-codeql-sarif';output.mkdir()
        run={'tool':{'driver':{'name':'CodeQL'}},'automationDetails':{'id':'/language:java-kotlin/'},
            'versionControlProvenance':[{'revisionId':SHA}],'results':[]}
        run.update(sarif_changes or {})
        (output/'java.sarif').write_text(json.dumps({'version':'2.1.0','runs':[run]}))
        return env,build

    def readback(self,env):
        with ExitStack() as stack:
            for obj,name in [(ci,'context_check'),(ci.lib,'source_check'),(ci,'workflow_check'),(ci,'branch_head_check')]:
                stack.enter_context(patch.object(obj,name,return_value=None))
            stack.enter_context(patch.object(ci,'codeql_command',return_value=['fixed-trace-command']))
            return ci.codeql_readback(env,SHA,IMAGE)

    def test_real_sarif_readback_is_filtered_and_never_claims_server_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            env,build=self.readback_fixture(Path(directory));result=self.readback(env)
            self.assertFalse(result['server_upload_verified'])
            self.assertEqual(SHA,result['source_sha']);self.assertEqual(64,len(result['sarif_sha256']))
            self.assertNotIn('command',result);self.assertNotIn('results',result)
            self.assertTrue((build/'codeql-artifact/CODEQL_EVIDENCE.json').is_file())

    def test_wrong_language_and_sarif_source_are_denied(self):
        for change in [{'automationDetails':{'id':'/language:python/'}},
            {'versionControlProvenance':[{'revisionId':'b'*40}]}]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                env,_=self.readback_fixture(Path(directory),sarif_changes=change)
                with self.assertRaises(ci.lib.Blocked):self.readback(env)

    def test_uncontrolled_or_changed_build_evidence_cannot_be_promoted(self):
        for change in [{'status':'FIXTURE_PASS'},{'codeql_version':'unknown'},
            {'command':['fake-compiler']},{'model_calls':1},{'apk_built':True}]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                env,_=self.readback_fixture(Path(directory),build_changes=change)
                with self.assertRaises(ci.lib.Blocked):self.readback(env)

    def test_codeql_context_is_separate_from_apk_and_requires_owner_settings_ack(self):
        ci.context_check(codeql_context(),SHA,IMAGE,purpose='codeql')
        with self.assertRaises(ci.lib.Blocked):ci.context_check(codeql_context(),SHA,IMAGE)
        with self.assertRaises(ci.lib.Blocked):ci.context_check(context(),SHA,IMAGE,purpose='codeql')
        for key,value in [('AIOA_CODEQL_ACK','false'),('AIOA_CODEQL_PROFILE',''),
                          ('AIOA_CODEQL_REQUESTED','false')]:
            with self.subTest(key=key),self.assertRaises(ci.lib.Blocked):
                ci.context_check({**codeql_context(),key:value},SHA,IMAGE,purpose='codeql')

    def test_requesting_codeql_without_actual_advanced_profile_denies_apk_too(self):
        for ack,profile in [('false','advanced-v1'),('true',''),('true','default')]:
            env={**context(),'AIOA_CODEQL_REQUESTED':'true','AIOA_CODEQL_ACK':ack,'AIOA_CODEQL_PROFILE':profile}
            with self.subTest(ack=ack,profile=profile),self.assertRaises(ci.lib.Blocked):ci.context_check(env,SHA,IMAGE)

    def test_codeql_argv_wraps_only_kotlin_compile_in_genuine_bounded_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);home=root/'codeql';home.mkdir();tool=home/'codeql';tool.write_text('fixture binary');tool.chmod(0o700)
            db=root/'databases/java';db.mkdir(parents=True);(db/'codeql-database.yml').write_text('fixture initialized DB')
            with patch.object(ci,'CODEQL_HOME',home,create=True),patch.object(ci,'CODEQL_DATABASE',db,create=True):
                command=ci.codeql_command({'CODEQL_DIST':str(home)},Path('/tmp/cache'),Path('/tmp/init'))
        self.assertEqual([str(tool),'database','trace-command'],command[:3])
        self.assertIn('--threads=1',command);self.assertIn('--ram=2048',command)
        self.assertIn(str(db),command);self.assertIn('--',command)
        self.assertIn(':app:compileDebugKotlin',command)
        self.assertIn('--rerun-tasks',command);self.assertIn('--no-build-cache',command)
        for part in ('--max-workers=1','--no-daemon','-Pkotlin.compiler.execution.strategy=in-process'):
            self.assertIn(part,command)
        for forbidden in ('--no-tracing','assembleDebug','installDebug','publish','testDebugUnitTest'):
            self.assertNotIn(forbidden,command)

    def test_untrusted_codeql_path_and_uninitialized_database_deny(self):
        with self.assertRaises(ci.lib.Blocked):ci.codeql_command({'CODEQL_DIST':'/tmp/model-tool'},Path('/tmp/cache'),Path('/tmp/init'))
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)/'tool';home.mkdir();(home/'codeql').write_text('fixture');(home/'codeql').chmod(0o700)
            with patch.object(ci,'CODEQL_HOME',home,create=True),patch.object(ci,'CODEQL_DATABASE',Path(directory)/'missing-db',create=True):
                with self.assertRaises(ci.lib.Blocked):ci.codeql_command({'CODEQL_DIST':str(home)},Path('/tmp/cache'),Path('/tmp/init'))

    def test_apk_job_stays_readonly_and_codeql_job_is_manual_and_settings_gated(self):
        workflow=yaml.safe_load((ROOT/'.github/workflows/android-manual-build.yml').read_text())
        self.assertEqual({'workflow_dispatch'},set(workflow['on']))
        self.assertEqual({'contents':'read'},workflow['permissions'])
        self.assertEqual({'contents':'read'},workflow['jobs']['debug-apk'].get('permissions',workflow['permissions']))
        inputs=workflow['on']['workflow_dispatch']['inputs']
        self.assertFalse(inputs['enable_codeql']['default']);self.assertFalse(inputs['codeql_settings_ack']['default'])
        job=workflow['jobs']['codeql-kotlin']
        self.assertEqual('debug-apk',job['needs'])
        self.assertIn('inputs.enable_codeql',job['if']);self.assertIn('inputs.codeql_settings_ack',job['if'])
        self.assertIn('vars.AIOA_CODEQL_PROFILE',job['if'])
        self.assertEqual({'contents':'read','security-events':'write'},job['permissions'])
        steps=job['steps'];names=[step.get('name','') for step in steps]
        init=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('github/codeql-action/init@'))
        build=next(i for i,s in enumerate(steps) if '--purpose codeql' in s.get('run','')
            and '--preflight-only' not in s['run'] and '--verify-codeql' not in s['run'])
        analyze=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('github/codeql-action/analyze@'))
        self.assertLess(init,build);self.assertLess(build,analyze)
        self.assertEqual('manual',steps[init]['with']['build-mode'])
        self.assertEqual('java-kotlin',steps[init]['with']['languages'])
        self.assertNotIn('continue-on-error',str(job));self.assertNotIn('secrets.',str(job))

    def test_prepared_advanced_profile_preserves_all_four_current_languages(self):
        path=ROOT/'.github/workflows/codeql-static.yml'
        self.assertTrue(path.exists(),'advanced profile must preserve current analyses')
        workflow=yaml.safe_load(path.read_text());job=workflow['jobs']['analyze']
        self.assertEqual({'actions','c-cpp','javascript-typescript','python'},set(job['strategy']['matrix']['language']))
        self.assertEqual(1,job['strategy']['max-parallel'])
        self.assertIn('vars.AIOA_CODEQL_PROFILE',job['if'])
        self.assertEqual({'contents':'read','security-events':'write'},job['permissions'])
        self.assertNotIn('gradlew',path.read_text());self.assertNotIn('sdkmanager',path.read_text())


if __name__=='__main__':unittest.main()
