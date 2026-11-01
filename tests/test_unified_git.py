"""U3 pure preview, closed remote boundary and real local Git via Core."""
import importlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


class UnifiedGitContractsTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.git_publish'),
                             'selective canonical Git publisher port missing')
        return importlib.import_module('runtime.mission.git_publish')

    def test_stage_preview_predicts_exact_flat_tree_without_git_effect(self):
        api=self.api()
        plan=api.LocalGitPlan({'README.md':b'hello\n'},'a'*64,'b'*32)
        preview=plan.preview()
        self.assertEqual('codex/aioa-sensorbridge-'+'b'*32,preview['branch'])
        # Independently measured with Git hash-object + mktree in a disposable repo.
        self.assertEqual('853694aae8816094a0d875fee7ea26278dbf5d0f',preview['tree_sha'])
        self.assertFalse(preview['remote_write_allowed'])
        self.assertIn('+hello',preview['diff'])

    def test_paths_source_receipt_and_dirty_target_are_exact(self):
        api=self.api()
        for name in ('../escape','/home/l','a/b','.git','bad\\name','-bad'):
            with self.subTest(name=name),self.assertRaises(ValueError):
                api.LocalGitPlan({name:b'x\n'},'a'*64,'b'*32)
        with self.assertRaises(ValueError):api.LocalGitPlan({'README.md':b'x\n'},'forged','b'*32)

    def test_no_remote_effect_is_enabled_by_model_flags_or_preview(self):
        api=self.api(); boundary=api.RemotePublishBoundary()
        for op in ('push','draft_pr','force_push','main','issue_write'):
            with self.subTest(op=op),self.assertRaises(ValueError):boundary.dispatch(op,{'approved':True})

    def test_remote_401_403_429_and_lost_ack_are_not_success_or_retry(self):
        api=self.api()
        for status,want in ((401,'DENIED'),(403,'DENIED'),(429,'BLOCKED_RATE_LIMIT'),(None,'UNKNOWN'),(500,'UNKNOWN')):
            actual=api.RemotePublishBoundary.classify_observation(status)
            self.assertEqual(want,actual['state']);self.assertFalse(actual['automatic_retry'])
            self.assertFalse(actual['effect_verified'])

    def test_core_commits_only_readback_verified_sensorbridge_in_fresh_sandbox(self):
        self.api()
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        from runtime.core_admission import Capability
        import time
        with tempfile.TemporaryDirectory() as temp:
            config=prepare_sensorbridge_sandbox(Path(temp)/'sandbox',workspace='workspace-sensorbridge')
            host=OfflineMetaComposition(Path(temp)/'state',source_probe=lambda:('1'*40,'a'*64))
            self.addCleanup(host.close)
            owner=host.core.local_operator(Capability.OWNER_APPROVAL);reader=host.core.local_operator(Capability.READ)
            host.missions.bind_agent_tools(config,owner)
            self.assertTrue(callable(getattr(host.missions,'propose_git',None)), 'Core Git mission port missing')
            def finish(proposal):
                host.missions.run_agent(proposal['task_id'],proposal['preview_digest'],owner)
                deadline=time.monotonic()+40
                while time.monotonic()<deadline:
                    view=host.missions.agent_view(proposal['task_id'],reader)
                    if view['state'] not in ('AGENT_RUNNING','AGENT_APPROVED'):return view
                    time.sleep(.05)
                self.fail('Git workflow did not finish')
            first=host.missions.propose_agent({'schema':'aioa.agent-proposal.v2','recipe_id':'sensorbridge-v1',
                'provider_id':'meta_model_api','request_id':'c'*32},reader)
            source=finish(first);self.assertEqual('AGENT_COMPLETED',source['state'])
            git=host.missions.propose_git(source['task_id'],'d'*32,reader)
            self.assertFalse(git['git']['remote_write_allowed'])
            result=finish(git)
            self.assertEqual('AGENT_COMPLETED',result['state'],result.get('error'))
            self.assertEqual(git['git']['commit_sha'],result['receipt']['git']['head'])
            self.assertFalse(result['receipt']['git']['remote_write_performed'])
            self.assertTrue(result['receipt']['local_readback_verified'])
            with self.assertRaises(ValueError):host.missions.run_agent(git['task_id'],git['preview_digest'],owner)
            host.close()


if __name__=='__main__':unittest.main()
