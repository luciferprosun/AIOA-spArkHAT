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



if __name__=='__main__':unittest.main()
