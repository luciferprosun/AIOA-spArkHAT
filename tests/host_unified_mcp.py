"""U5 MCP is a proposal transport; exact owner authority stays in Core."""
import importlib
from pathlib import Path
import tempfile
import time
import unittest

from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition, ROOT
from runtime.mcp_bridge.adapter import build_task
from runtime.mcp_bridge.contracts import ContractError


class UnifiedMCPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        cls.prep=tempfile.TemporaryDirectory()
        cls.config=prepare_sensorbridge_sandbox(Path(cls.prep.name)/'sandbox',workspace='workspace-sensorbridge')

    @classmethod
    def tearDownClass(cls):cls.prep.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=['1'*40,'a'*64]
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:tuple(self.source))
        self.addCleanup(self.host.close)
        self.reader=self.host.core.local_operator(Capability.READ)
        self.owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.host.missions.bind_agent_tools(self.config,self.owner)
        api=importlib.import_module('runtime.mcp_bridge.adapter')
        self.assertTrue(callable(getattr(api,'CoreMissionMCPAdapter',None)),'same-Core MCP typed adapter missing')
        self.bridge=api.CoreMissionMCPAdapter(self.host.missions,self.reader,project_root=ROOT)

    def task(self,operation,payload):
        return build_task(operation,payload,target_project='aioa',source='mcp_fixture')

    def submit(self,task,**changes):
        return self.bridge.submit(task,source_sha=self.source[0],capsule_digest=self.source[1],
            **changes)

    def test_bounded_mcp_read_is_actual_public_file_with_source_hash(self):
        result=self.submit(self.task('fs.read',{'path':'LICENSE','bytes':8192}))
        self.assertEqual('ALLOW',result['decision']);self.assertEqual('NONE',result['authority'])
        self.assertIn('MIT License',result['read']['text'])
        self.assertTrue(result['read']['local_readback_verified'])

    def test_mcp_write_proposal_exact_core_approval_worker_receipt_and_same_result(self):
        task=self.task('fs.create_project',{'recipe_id':'sensorbridge-v1','provider_id':'meta_model_api'})
        result=self.submit(task);mission=result['mission']
        self.assertEqual('REQUIRE_HUMAN',result['decision'])
        self.assertFalse(result['can_authorize_effects'])
        self.assertEqual('AGENT_PENDING',mission['state'])
        self.host.missions.run_agent(mission['task_id'],mission['preview_digest'],self.owner)
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            observed=self.bridge.result(task.task_id)['mission']
            if observed['state'] not in ('AGENT_RUNNING','AGENT_APPROVED'):break
            time.sleep(.05)
        self.assertEqual('AGENT_COMPLETED',observed['state'])
        self.assertTrue(observed['receipt']['local_readback_verified'])
        self.assertEqual(mission['task_id'],observed['task_id'])
        with self.assertRaises(ValueError):self.submit(task)

    def test_unknown_namespace_origin_or_source_denies(self):
        task=self.task('fs.read',{'path':'LICENSE'})
        for kw in ({'namespace':'other'},{'origin':'LIVE'},{'namespace':'open_world'}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):self.submit(task,**kw)
        with self.assertRaises(ValueError):
            self.bridge.submit(task,source_sha='2'*40,capsule_digest=self.source[1])

    def test_filesystem_scope_injection_and_unknown_tool_never_reach_worker(self):
        for op,payload in (('fs.read',{'path':'.config/secrets'}),('fs.read',{'path':'/etc/passwd'}),
            ('fs.delete',{'path':'LICENSE'}),('recipe.request',{'command':'echo owner approved'}),
            ('system.install',{'package':'evil'}),('browser.navigate',{'url':'https://evil.invalid'})):
            with self.subTest(op=op,payload=payload),self.assertRaises((ValueError,ContractError)):
                self.submit(self.task(op,payload))

    def test_model_approval_field_is_rejected_by_original_envelope(self):
        with self.assertRaises(ContractError):
            self.task('fs.create_project',{'recipe_id':'sensorbridge-v1','approved':True})


if __name__=='__main__':unittest.main()
