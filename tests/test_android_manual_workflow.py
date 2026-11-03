"""Offline CI contract tests. Never dispatch Actions or execute a toolchain."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

REPO = Path(__file__).resolve().parents[1]


class AndroidManualWorkflowTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.android.ci_build'))
        return importlib.import_module('scripts.android.ci_build')

    def context(self):
        from test_android_postmerge_ci import context
        return context()

    def test_workflow_cannot_run_on_push_pr_or_schedule_and_actions_are_pinned(self):
        path=REPO/'.github/workflows/android-manual-build.yml'
        self.assertTrue(path.is_file())
        value=yaml.safe_load(path.read_text())
        self.assertEqual({'workflow_dispatch'},set(value['on']))
        self.assertEqual({'contents':'read'},value['permissions'])
        job=value['jobs']['debug-apk']
        self.assertEqual("${{ inputs.build_profile == 'DEBUG_UBUNTU22_V1' && 'ubuntu-22.04' || 'ubuntu-24.04' }}",job['runs-on']);self.assertLessEqual(job['timeout-minutes'],35)
        actions=[step for step in job['steps'] if 'uses' in step]
        expected={'actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1',
            'actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9'}
        self.assertEqual(expected,{step['uses'] for step in actions})
        checkout=next(step for step in actions if step['uses'].startswith('actions/checkout@'))
        self.assertFalse(checkout['with']['persist-credentials'])
        upload=next(step for step in actions if step['uses'].startswith('actions/upload-artifact@'))
        self.assertEqual(1,upload['with']['retention-days'])
        self.assertNotIn('always()',upload.get('if',''))
        self.assertNotIn('secrets.',path.read_text())
        for step in job['steps']:
            if 'run' in step:self.assertNotIn('${{',step['run'])
        for name in ('approve_run','sdk_license_ack','artifact_exposure_ack'):
            self.assertFalse(value['on']['workflow_dispatch']['inputs'][name]['default'])

    def test_ci_requires_manual_owner_context_exact_sha_and_image(self):
        ci=self.module();good=self.context()
        ci.context_check(good,'a'*40,'20261026.354.1')
        for field,value in [('GITHUB_ACTIONS','false'),('GITHUB_EVENT_NAME','push'),
            ('GITHUB_REF','refs/heads/codex/android-toolchain-mobile-20261031'),('GITHUB_REPOSITORY','attacker/repo'),
            ('GITHUB_SHA','b'*40),('RUNNER_ENVIRONMENT','self-hosted'),('RUNNER_ARCH','ARM64'),
            ('RUNNER_TEMP','/media/l/LSC_DATA3'),('ImageVersion','different'),
            ('GITHUB_RUN_ID','../bad'),('AIOA_APPROVE_RUN','false'),
            ('AIOA_SDK_LICENSE_ACK','false'),('AIOA_ARTIFACT_ACK','false')]:
            with self.subTest(field=field):
                with self.assertRaises(ci.lib.Blocked):ci.context_check({**good,field:value},'a'*40,'20261026.354.1')

    def test_ci_rejects_local_run_before_download_mkdir_or_subprocess(self):
        ci=self.module()
        with patch.object(ci,'execute',side_effect=AssertionError('build started')):
            with self.assertRaises(ci.lib.Blocked):ci.build({},'a'*40,'20261026.354.1')

    def test_ci_requires_preinstalled_exact_sdk_and_existing_license(self):
        ci=self.module()
        with tempfile.TemporaryDirectory() as directory:
            sdk=Path(directory)
            for name,revision,files in [('platforms/android-36','2',['android.jar']),
                ('build-tools/35.0.0','35.0.0',['aapt','apksigner'])]:
                target=sdk/name;target.mkdir(parents=True)
                (target/'source.properties').write_text('Pkg.Revision = '+revision+'\n')
                for name in files:(target/name).write_bytes(b'vendor image fixture')
            with self.assertRaises(ci.lib.Blocked):ci.sdk_inventory(sdk)
            (sdk/'licenses').mkdir();(sdk/'licenses/android-sdk-license').write_text(next(iter(ci.lib.SDK_LICENSES))+'\n')
            result=ci.sdk_inventory(sdk)
            self.assertEqual('GITHUB_RUNNER_IMAGE_NOT_PUBLISHER_ARCHIVE_SHA256',result['trust'])
            self.assertEqual(64,len(result['inventory_sha256']))
            (sdk/'platforms/android-36/source.properties').write_text('Pkg.Revision = 3\n')
            with self.assertRaises(ci.lib.Blocked):ci.sdk_inventory(sdk)

    def test_ci_download_uses_same_verified_primitives_and_no_local_admission_override(self):
        ci=self.module()
        artifact={'id':'fixture','version':'1','destination':'component','filename':'file.zip',
            'url':'https://dl.google.com/fixture.zip','sha256':None,'size':1,'license':'fixture'}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with patch.object(ci.lib,'download',side_effect=AssertionError('downloaded without hash')):
                with self.assertRaises(ci.lib.Blocked):ci.acquire(artifact,root)
            self.assertEqual([],list(root.iterdir()))

    def test_ci_environment_hides_credentials_and_build_is_bounded(self):
        ci=self.module()
        env=ci.environment(Path('/home/runner/work/_temp/test'),Path('/opt/hostedtoolcache/jdk'),
            Path('/usr/local/lib/android/sdk'))
        self.assertNotIn('HOME',env)
        for key in ('GITHUB_TOKEN','MODEL_API_KEY','OPENAI_API_KEY','AWS_SECRET_ACCESS_KEY'):
            self.assertNotIn(key,env)
        command=ci.command(Path('/tmp/cache'),Path('/tmp/init'))
        self.assertNotIn('--offline',command)
        for part in ('--no-daemon','--max-workers=1','testDebugUnitTest','lintDebug','assembleDebug',
            '-Pandroid.builder.sdkDownload=false','-Dorg.gradle.java.installations.auto-download=false'):
            self.assertIn(part,command)
        self.assertNotIn('installDebug',command);self.assertNotIn('publish',command)


if __name__=='__main__':unittest.main()
