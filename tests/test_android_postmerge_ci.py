"""Real guard behavior; offline fixtures only, never a toolchain/CI dispatch."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts.android import ci_build as ci

ROOT=Path(__file__).resolve().parents[1]
SHA='a'*40
IMAGE='20261026.354.1'
WORKFLOW='.github/workflows/android-manual-build.yml'


def context():
    revision=hashlib.sha256((ROOT/WORKFLOW).read_bytes()).hexdigest()
    return {'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch',
        'GITHUB_REPOSITORY':'luciferprosun/AIOA-spArkHAT','GITHUB_REPOSITORY_OWNER':'luciferprosun',
        'GITHUB_ACTOR':'luciferprosun','GITHUB_TRIGGERING_ACTOR':'luciferprosun',
        'GITHUB_REF':'refs/heads/main','GITHUB_SHA':SHA,'GITHUB_RUN_ID':'123',
        'GITHUB_RUN_ATTEMPT':'1','GITHUB_JOB':'debug-apk',
        'GITHUB_WORKFLOW_REF':'luciferprosun/AIOA-spArkHAT/'+WORKFLOW+'@refs/heads/main',
        'GITHUB_WORKFLOW_SHA':SHA,'RUNNER_ENVIRONMENT':'github-hosted','RUNNER_ARCH':'X64',
        'RUNNER_TEMP':'/home/runner/work/_temp','ImageOS':'ubuntu24','ImageVersion':IMAGE,
        'AIOA_APPROVE_RUN':'true','AIOA_SDK_LICENSE_ACK':'true','AIOA_ARTIFACT_ACK':'true',
        'AIOA_WORKFLOW_REVISION':revision}


class PostmergeCIGuardTests(unittest.TestCase):
    def test_workflow_denies_stale_sha_and_wrong_actor_before_allocating_build_job(self):
        import yaml
        job=yaml.safe_load((ROOT/WORKFLOW).read_text())['jobs']['debug-apk']
        self.assertIn('inputs.expected_source_sha == github.sha',job['if'])
        self.assertIn("github.actor == 'luciferprosun'",job['if'])
        self.assertIn("github.run_attempt == '1'",job['if'])

    def test_workflow_preflight_precedes_setup_java_and_codeql_tools(self):
        import yaml
        workflow=yaml.safe_load((ROOT/WORKFLOW).read_text())
        for name in ('debug-apk','codeql-kotlin'):
            steps=workflow['jobs'][name]['steps']
            preflight=next(i for i,s in enumerate(steps) if '--preflight-only' in s.get('run',''))
            setup=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('actions/setup-java@'))
            self.assertLess(preflight,setup)
            image=next(i for i,s in enumerate(steps) if 'test "$ImageVersion"' in s.get('run',''))
            checkout=next(i for i,s in enumerate(steps) if s.get('uses','').startswith('actions/checkout@'))
            self.assertLess(image,checkout)

    def test_exact_main_context_admitted(self):
        ci.context_check(context(),SHA,IMAGE)

    def test_old_ref_and_unapproved_refs_deny(self):
        for ref in ['refs/heads/codex/android-toolchain-mobile-20261031',
                    'refs/heads/attacker','refs/tags/unreviewed','refs/pull/27/merge']:
            with self.subTest(ref=ref),self.assertRaises(ci.lib.Blocked):
                ci.context_check({**context(),'GITHUB_REF':ref},SHA,IMAGE)

    def test_owner_workflow_source_and_rerun_drift_deny(self):
        for field,value in [('GITHUB_REPOSITORY_OWNER','attacker'),('GITHUB_ACTOR','attacker'),
            ('GITHUB_TRIGGERING_ACTOR','attacker'),('GITHUB_WORKFLOW_SHA','b'*40),
            ('GITHUB_WORKFLOW_REF','luciferprosun/AIOA-spArkHAT/'+WORKFLOW+'@refs/heads/attacker'),
            ('GITHUB_RUN_ATTEMPT','2'),('AIOA_WORKFLOW_REVISION','0'*64),
            ('GITHUB_JOB','unreviewed'),('AIOA_APPROVE_RUN','false'),
            ('AIOA_SDK_LICENSE_ACK','false'),('AIOA_ARTIFACT_ACK','false')]:
            with self.subTest(field=field),self.assertRaises(ci.lib.Blocked):
                ci.context_check({**context(),field:value},SHA,IMAGE)

    def test_changing_only_source_input_cannot_bypass_actual_context(self):
        with self.assertRaises(ci.lib.Blocked):ci.context_check(context(),'b'*40,IMAGE)

    def test_changing_image_input_to_unreviewed_actual_image_still_denies(self):
        # Unlike a text-to-text equality check, review policy stays pinned.
        env={**context(),'ImageVersion':'20261199.999.1'}
        with self.assertRaises(ci.lib.Blocked):ci.context_check(env,SHA,'20261199.999.1')

    def test_real_workflow_bytes_match_reviewed_revision(self):
        ci.workflow_check(context())

    def test_workflow_tamper_or_symlink_denies_even_when_input_matches_tamper(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/WORKFLOW;path.parent.mkdir(parents=True)
            original=(ROOT/WORKFLOW).read_bytes();path.write_bytes(original+b'\n# drift\n')
            env={**context(),'AIOA_WORKFLOW_REVISION':hashlib.sha256(path.read_bytes()).hexdigest()}
            with patch.object(ci.lib,'REPO',root),self.assertRaises(ci.lib.Blocked):ci.workflow_check(env)
            path.unlink();path.symlink_to(ROOT/WORKFLOW)
            with patch.object(ci.lib,'REPO',root),self.assertRaises(ci.lib.Blocked):ci.workflow_check(context())

    def test_branch_head_observation_exact_and_credential_free(self):
        response=SimpleNamespace(returncode=0,stdout=SHA+'\trefs/heads/main\n',stderr='')
        with patch.object(ci.subprocess,'run',return_value=response) as run:
            ci.branch_head_check(SHA)
        args=run.call_args
        self.assertIn('ls-remote',args.args[0]);self.assertIn('refs/heads/main',args.args[0])
        self.assertIn('https://github.com/luciferprosun/AIOA-spArkHAT.git',args.args[0])
        self.assertLessEqual(args.kwargs['timeout'],30)
        self.assertEqual('0',args.kwargs['env']['GIT_TERMINAL_PROMPT'])
        self.assertFalse(any('TOKEN' in key or 'PASSWORD' in key for key in args.kwargs['env']))

    def test_branch_drift_duplicate_response_and_read_failure_deny(self):
        for code,text in [(0,'b'*40+'\trefs/heads/main\n'),
            (0,SHA+'\trefs/heads/main\n'+SHA+'\trefs/heads/main\n'),
            (0,SHA+'\trefs/heads/other\n'),(1,'')]:
            with self.subTest(code=code,text_kind=len(text)),\
                patch.object(ci.subprocess,'run',return_value=SimpleNamespace(returncode=code,stdout=text,stderr='')),\
                self.assertRaises(ci.lib.Blocked):ci.branch_head_check(SHA)

    def test_bad_context_denies_before_any_effect(self):
        with patch.object(ci,'execute',side_effect=AssertionError('build effect')),\
            patch.object(ci.lib,'source_check',side_effect=AssertionError('source work')):
            with self.assertRaises(ci.lib.Blocked):ci.build({**context(),'AIOA_APPROVE_RUN':'false'},SHA,IMAGE)

    def test_dirty_source_denies_before_branch_probe_or_execute(self):
        with patch.object(ci.lib,'source_check',side_effect=ci.lib.Blocked('BLOCKED_DIRTY_SOURCE')),\
            patch.object(ci,'execute',side_effect=AssertionError('build effect')),\
            patch.object(ci,'branch_head_check',side_effect=AssertionError('network'),create=True):
            with self.assertRaises(ci.lib.Blocked):ci.build(context(),SHA,IMAGE)

    def test_branch_drift_denies_before_execute(self):
        with patch.object(ci.lib,'source_check',return_value={}),\
            patch.object(ci,'workflow_check',return_value=None,create=True),\
            patch.object(ci,'branch_head_check',side_effect=ci.lib.Blocked('BLOCKED_CI_BRANCH_DRIFT'),create=True),\
            patch.object(ci,'execute',side_effect=AssertionError('build effect')):
            with self.assertRaisesRegex(ci.lib.Blocked,'BRANCH_DRIFT'):ci.build(context(),SHA,IMAGE)


if __name__=='__main__':unittest.main()
