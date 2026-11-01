"""U6 same mission through signed v2, with existing N1 unchanged."""
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.mobile_gateway.service import MobileGateway
from runtime.mobile_gateway import wire
from unified_mobile_support import SignedDeviceFixture

BASE='/api/mobile/v2'


class UnifiedMobileTests(unittest.TestCase):
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
        self.addCleanup(lambda:self.host.close())
        self.owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader=self.host.core.local_operator(Capability.READ)
        self.host.missions.bind_agent_tools(self.config,self.owner)
        self.identity=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        self.gateway=MobileGateway(self.host.missions,identity=self.identity,fixture=True)
        self.client=SignedDeviceFixture(self.gateway,self.owner)

    def propose(self,request_id='1'*32):
        status,response=self.client.request('POST',BASE+'/propose',{'schema':'aioa.agent-proposal.v2',
            'recipe_id':'sensorbridge-v1','provider_id':'meta_model_api','request_id':request_id})
        self.assertEqual(200,status,response)
        return response['data']

    def test_signed_proposal_host_approval_real_files_and_receipt_are_same_mission(self):
        task=self.propose();self.assertEqual('aioa.mobile.mission-view.v2',task['schema'])
        self.assertEqual('NEEDS_HOST_APPROVAL',task['approval_status'])
        self.assertFalse(any(task['permissions'].values()))
        self.host.missions.run_agent(task['task_id'],task['preview_digest'],self.owner)
        self.host.missions._workers[task['task_id']].join(40)
        status,response=self.client.request('GET',BASE+'/tasks/'+task['task_id'])
        self.assertEqual(200,status,response);view=response['data']
        self.assertEqual('AGENT_COMPLETED',view['state']);self.assertTrue(view['receipt']['local_readback_verified'])
        self.assertEqual(5,view['tests']['passed']);self.assertIn('README.md',view['diff'])
        canonical=self.host.missions.agent_view(task['task_id'],self.reader)
        self.assertEqual(canonical['receipt'],view['receipt']);self.assertFalse(any(view['permissions'].values()))
        status,old=self.client.request('GET',wire.BASE+'/status')
        self.assertEqual(200,status);self.assertEqual([],old['data']['missions'])

    def test_duplicate_frame_and_duplicate_proposal_require_get_readback(self):
        task=self.propose()
        frame=self.client.frame('GET',BASE+'/tasks/'+task['task_id'])
        self.assertEqual(200,self.gateway.handle(*frame)[0]);self.assertEqual(409,self.gateway.handle(*frame)[0])
        status,response=self.client.request('POST',BASE+'/propose',{'schema':'aioa.agent-proposal.v2',
            'recipe_id':'sensorbridge-v1','provider_id':'meta_model_api','request_id':'1'*32})
        self.assertEqual(409,status)
        status,response=self.client.request('GET',BASE+'/proposals/'+'1'*32)
        self.assertEqual(200,status,response);self.assertEqual(task['task_id'],response['data']['task_id'])

    def test_cross_device_denies_before_canonical_mission_lookup(self):
        task=self.propose();other=SignedDeviceFixture(self.gateway,self.owner)
        with patch.object(self.host.missions,'agent_view',side_effect=AssertionError('cross-device read')):
            status,response=other.request('GET',BASE+'/tasks/'+task['task_id'])
        self.assertEqual(403,status,response)

    def test_session_loss_handoff_keeps_old_scope_and_never_replays_pending(self):
        task=self.propose();old=self.client
        self.host.close()
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:tuple(self.source))
        self.owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader=self.host.core.local_operator(Capability.READ)
        self.host.missions.bind_agent_tools(self.config,self.owner)
        self.gateway=MobileGateway(self.host.missions,identity=self.identity,fixture=True)
        old.gateway=self.gateway
        fresh=SignedDeviceFixture(self.gateway,self.owner,identity=old.device)
        self.assertNotEqual(old.token,fresh.token)
        with patch.object(self.host.missions,'agent_view',side_effect=AssertionError('old scope read')):
            self.assertEqual(401,old.request('GET',BASE+'/proposals/'+'1'*32)[0])
            self.assertEqual(403,fresh.request('GET',BASE+'/proposals/'+'1'*32)[0])
            self.assertEqual(403,fresh.request('GET',BASE+'/tasks/'+task['task_id'])[0])
        before=self.host.missions.agent_view(task['task_id'],self.reader)
        self.assertEqual('AGENT_UNKNOWN',before['state'])
        self.client=fresh
        new=self.propose('2'*32)
        after=self.host.missions.agent_view(task['task_id'],self.reader)
        self.assertNotEqual(task['task_id'],new['task_id'])
        self.assertEqual(before,after)
        self.assertIsNone(after['receipt'])
        self.assertEqual('NEEDS_HOST_APPROVAL',new['approval_status'])

    def test_mobile_never_exposes_owner_or_native_write_ports(self):
        for action in ('run','approve','install','native_execute','github_write','meta_spend'):
            with self.subTest(action=action):
                status,response=self.client.request('POST',BASE+'/'+action,{'approved':True})
                self.assertEqual(501,status,response)

    def test_restart_and_stop_keep_unknown_without_replay(self):
        task=self.propose();self.host.close()
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:tuple(self.source))
        self.owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.host.missions.bind_agent_tools(self.config,self.owner)
        self.gateway=MobileGateway(self.host.missions,identity=self.identity,fixture=True);self.client.gateway=self.gateway
        status,response=self.client.request('GET',BASE+'/tasks/'+task['task_id'])
        self.assertEqual(200,status,response);self.assertEqual('AGENT_UNKNOWN',response['data']['state'])
        status,response=self.client.request('POST',BASE+'/stop',{'task_id':task['task_id']})
        self.assertEqual(200,status,response);self.assertEqual('AGENT_UNKNOWN',response['data']['state'])


if __name__=='__main__':unittest.main()
