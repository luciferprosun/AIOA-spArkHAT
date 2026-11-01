"""U1/U2: the real single MissionService, Core journal and registered worker."""
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest

from runtime.core_admission import Capability, AdmissionError
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition


class UnifiedMissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        cls.prep = tempfile.TemporaryDirectory()
        cls.config = prepare_sensorbridge_sandbox(Path(cls.prep.name)/'sandbox', workspace='workspace-sensorbridge')

    @classmethod
    def tearDownClass(cls): cls.prep.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.source = ['1'*40, 'a'*64]
        self.host = OfflineMetaComposition(Path(self.tmp.name), source_probe=lambda: tuple(self.source))
        self.addCleanup(self.host.close)
        self.assertTrue(callable(getattr(self.host.missions, 'bind_agent_tools', None)),
                        'canonical MissionService agent binding missing')
        self.owner = self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader = self.host.core.local_operator(Capability.READ)
        self.host.missions.bind_agent_tools(self.config, self.owner)

    def propose(self, **changes):
        return self.host.missions.propose_agent({'schema':'aioa.agent-proposal.v2',
            'recipe_id':'sensorbridge-v1', 'provider_id':'meta_model_api',
            'request_id':__import__('uuid').uuid4().hex, **changes}, self.reader)

    def execute(self, proposal):
        return self.host.missions.run_agent(proposal['task_id'], proposal['preview_digest'], self.owner)

    def wait(self, task):
        deadline = time.monotonic()+40
        while time.monotonic() < deadline:
            view = self.host.missions.agent_view(task, self.reader)
            if view['state'] not in ('AGENT_APPROVED','AGENT_RUNNING'): return view
            time.sleep(.05)
        self.fail('bounded mission did not finish')

    def test_exact_owner_warrant_real_workspace_tests_and_independent_readback(self):
        proposal = self.propose()
        self.assertEqual('NEEDS_HOST_APPROVAL', proposal['approval_status'])
        self.assertFalse(proposal['permissions']['native_execute'])
        self.execute(proposal); result = self.wait(proposal['task_id'])
        self.assertEqual('AGENT_COMPLETED', result['state'], result.get('error'))
        self.assertTrue(result['receipt']['local_readback_verified'])
        self.assertEqual(5, result['tests']['passed'])
        self.assertEqual({'README.md','sensorbridge.py','test_sensorbridge.py'}, set(result['files']))
        self.assertEqual('OFFLINE_FIXTURE', result['mode']); self.assertFalse(result['live_verified'])
        self.assertIs(self.host.missions.ledger, self.host.missions.agent_journal.ledger)
        self.assertEqual(0, self.host.missions.agent_governor.inspect(self.reader)['exposure']['global']['money_nano'])
        with self.assertRaises(ValueError): self.execute(proposal)

    def test_missing_and_forged_owner_never_dispatch(self):
        proposal = self.propose()
        for owner in (None, replace(self.owner, _seal=b'forged')):
            with self.assertRaises(AdmissionError):
                self.host.missions.run_agent(proposal['task_id'], proposal['preview_digest'], owner)
        self.assertEqual('AGENT_PENDING', self.wait(proposal['task_id'])['state'])

    def test_source_or_preview_change_denies_before_start(self):
        proposal = self.propose()
        with self.assertRaises(ValueError):
            self.host.missions.run_agent(proposal['task_id'], '0'*64, self.owner)
        self.source[1] = 'b'*64
        with self.assertRaises(ValueError): self.execute(proposal)
        self.assertEqual({}, self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_unregistered_recipe_provider_and_approval_text_cannot_bypass_scope(self):
        for changes in ({'recipe_id':'../../escape'}, {'provider_id':'fake-live'},
                        {'approved':True}, {'command':'rm -rf /'}, {'path':'/home/l'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.propose(**changes)

    def test_stop_before_start_has_no_effect_and_no_replay(self):
        proposal = self.propose()
        stopped = self.host.missions.agent_stop(proposal['task_id'], self.reader)
        self.assertEqual('AGENT_STOPPED', stopped['state'])
        with self.assertRaises(ValueError): self.execute(proposal)
        self.assertEqual({}, self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_cpl_veto_is_not_model_authority(self):
        proposal = self.propose()
        self.host.missions.cpl_veto_reader = lambda: True
        with self.assertRaises(ValueError): self.execute(proposal)
        self.assertEqual({}, self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_restart_keeps_pending_unknown_and_does_not_execute(self):
        proposal = self.propose(); self.host.close()
        self.host = OfflineMetaComposition(Path(self.tmp.name), source_probe=lambda: tuple(self.source))
        self.addCleanup(self.host.close)
        owner = self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.host.missions.bind_agent_tools(self.config, owner)
        view = self.host.missions.agent_view(proposal['task_id'], self.host.core.local_operator(Capability.READ))
        self.assertEqual('AGENT_UNKNOWN', view['state'])
        with self.assertRaises(ValueError): self.host.missions.run_agent(proposal['task_id'], proposal['preview_digest'], owner)

    def test_post_effect_ack_loss_requires_independent_reconciliation_never_retry(self):
        proposal=self.propose();route=self.host.missions.agent_route
        original=route.verifier
        route.verifier=lambda operation,warrant: (_ for _ in ()).throw(ValueError('injected readback ACK loss'))
        self.execute(proposal);self.host.missions._workers[proposal['task_id']].join(40)
        unknown=self.host.missions.agent_view(proposal['task_id'],self.reader)
        self.assertEqual('AGENT_UNKNOWN',unknown['state'])
        self.assertTrue(any(r['state']=='UNKNOWN' for r in self.host.missions.agent_governor.inspect(self.reader)['reservations'].values()))
        with self.assertRaises(ValueError):self.execute(proposal)
        self.assertTrue(callable(getattr(self.host.missions,'reconcile_agent',None)),'independent agent readback port missing')
        route.verifier=original
        done=self.host.missions.reconcile_agent(proposal['task_id'],self.reader)
        self.assertEqual('AGENT_COMPLETED',done['state']);self.assertTrue(done['receipt']['local_readback_verified'])
        self.assertEqual(1,len([r for r in self.config.root.glob('run-*')
            if __import__('json').loads((r/'receipt.json').read_bytes()).get('request',{}).get('task_id')==proposal['task_id']]))


if __name__ == '__main__': unittest.main()
