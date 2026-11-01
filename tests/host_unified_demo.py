"""Reproduce the actual offline vertical slice, including a fresh host process."""
import importlib
from pathlib import Path
import tempfile
import unittest


class UnifiedDemoTests(unittest.TestCase):
    def test_signed_workspace_tests_local_commit_and_process_restart(self):
        root=Path(__file__).resolve().parents[1]
        self.assertTrue((root/'scripts/unification/offline_demo.py').is_file(),'reproducible offline demo missing')
        api=importlib.import_module('scripts.unification.offline_demo')
        with tempfile.TemporaryDirectory() as temp:
            report=api.run_demo(Path(temp)/'evidence')
            self.assertEqual('AGENT_COMPLETED',report['workspace']['state'])
            self.assertEqual(5,report['workspace']['tests_passed'])
            self.assertTrue(report['workspace']['local_readback_verified'])
            self.assertEqual(report['git']['predicted_head'],report['git']['head'])
            self.assertTrue(report['fresh_process_signed_readback_verified'])
            self.assertEqual(403,report['remote_write_http_status'])
            self.assertEqual(0,report['paid_api_calls'])
            self.assertEqual('NOT_BOUND',report['production_owner'])


if __name__=='__main__':unittest.main()
