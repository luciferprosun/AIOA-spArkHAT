"""Qualified host: actual Core/namespace/local Git acceptance."""
import importlib
from pathlib import Path
import tempfile
import unittest


class NativeGitPublicationTests(unittest.TestCase):
    def api(self):return importlib.import_module('runtime.mission.git_publish')

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
            # A template reread is not the independently verified source artifact.
            # Fault-inject a changed template while the fixture source probe is fixed.
            from unittest.mock import patch
            from runtime.mission.project_recipe import SensorBridgePlan
            changed=SensorBridgePlan('fixture:sensorbridge').files()
            changed['sensorbridge.py']+=b'\n# unverified template drift\n'
            with patch.object(SensorBridgePlan,'files',return_value=changed):
                git=host.missions.propose_git(source['task_id'],'d'*32,reader)
            self.assertEqual(source['receipt']['files']['sensorbridge.py']['sha256'],git['files']['sensorbridge.py']['sha256'])
            self.assertFalse(git['git']['remote_write_allowed'])
            result=finish(git)
            self.assertEqual('AGENT_COMPLETED',result['state'],result.get('error'))
            self.assertEqual(git['git']['commit_sha'],result['receipt']['git']['head'])
            self.assertFalse(result['receipt']['git']['remote_write_performed'])
            self.assertTrue(result['receipt']['local_readback_verified'])
            with self.assertRaises(ValueError):host.missions.run_agent(git['task_id'],git['preview_digest'],owner)
            host.close()


if __name__=='__main__':unittest.main()
