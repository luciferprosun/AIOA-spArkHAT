"""Qualified-host fault acceptance; every attempt crosses the real fixture Core.

Adversarial worker bytes are supplied only by this trusted test host and sealed
into its private approved profile. No application/model input supplies code.
"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid

from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.meta_hackathon import agent_operations
from runtime.mission.project_recipe import ProjectSeed, SensorBridgePlan, prepare_sensorbridge_sandbox
from runtime.mission import sandbox_linux
from runtime.mission.sandbox_contracts import SandboxRegistry


class NativeFaultAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prep=tempfile.TemporaryDirectory()
        cls.base=prepare_sensorbridge_sandbox(Path(cls.prep.name)/'baseline',workspace='workspace-sensorbridge')

    @classmethod
    def tearDownClass(cls):cls.prep.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.host=None
        self.addCleanup(lambda:self.host.close() if self.host else None)

    def host_with(self,config):
        host=OfflineMetaComposition(self.root/'state',source_probe=lambda:('1'*40,'a'*64))
        self.host=host
        host.missions.bind_agent_tools(config,host.core.local_operator(Capability.OWNER_APPROVAL))
        return host

    def proposal(self):
        return self.host.missions.propose_agent({'schema':'aioa.agent-proposal.v2','recipe_id':'sensorbridge-v1',
            'provider_id':'meta_model_api','request_id':uuid.uuid4().hex},self.host.core.local_operator(Capability.READ))

    def finish(self,task):
        service=self.host.missions
        service.run_agent(task['task_id'],task['preview_digest'],self.host.core.local_operator(Capability.OWNER_APPROVAL))
        service._workers[task['task_id']].join(40)
        self.assertFalse(service._workers[task['task_id']].is_alive(),'bounded worker did not finish')
        return service.agent_view(task['task_id'],self.host.core.local_operator(Capability.READ))

    def fault_config(self,script,*,timeout_ms=10000):
        plan=SensorBridgePlan('fixture:sensorbridge')
        spec=plan.recipe_spec(ProjectSeed(plan.project_ref,0,None))
        spec['files']['recipe.py']=script
        config=sandbox_linux.prepare_linux_sandbox(self.root/'sandbox',self.base.runtime(),
            workspace='workspace-sensorbridge',recipes={'recipe:sensorbridge-v1':spec})
        return replace(config,registry=SandboxRegistry(config.registry.workspace,tuple(
            replace(recipe,timeout_ms=timeout_ms) for recipe in config.registry.recipes)))

    def unknown_fault(self,script,*,reason,memory=False):
        config=self.fault_config(script);self.host_with(config)
        task=self.proposal();result=self.finish(task)
        self.assertEqual('AGENT_UNKNOWN',result['state']);self.assertIsNone(result['receipt'])
        rows=list(config.root.glob('run-*/receipt.json'));self.assertEqual(1,len(rows))
        evidence=json.loads(rows[0].read_text())
        terminal=evidence['observations'].get('worker_terminal',{})
        print('NATIVE_FAULT_EVIDENCE '+json.dumps({'case':self._testMethodName,'stage':evidence['stage'],
            'error':evidence.get('error'),'project_code_started':evidence['project_code_started'],
            'termination_reason':terminal.get('termination_reason'),'child_exit_code':terminal.get('child_exit_code'),
            'output_bytes':len(terminal.get('stdout','').encode())+len(terminal.get('stderr','').encode()),
            'memory_error':'MemoryError' in terminal.get('stderr',''),
            'unit_terminal_observed':evidence['unit_terminal_observed'],
            'cgroup_absent_after_cleanup':evidence['cgroup_absent_after_cleanup']}),flush=True)
        self.assertEqual(reason,terminal.get('termination_reason'))
        self.assertNotEqual(0,terminal.get('child_exit_code'))
        self.assertLessEqual(len(terminal.get('stdout','').encode())+len(terminal.get('stderr','').encode()),
            config.registry.recipes[0].max_output_bytes)
        if memory:self.assertIn('MemoryError',terminal.get('stderr',''))
        self.assertTrue(evidence['project_code_started'],'fault must happen after actual dispatch')
        self.assertEqual('UNKNOWN',evidence['status'])
        self.assertTrue(evidence['cleanup']);self.assertTrue(evidence['unit'].startswith('aioa-sandbox-'))
        self.assertTrue(evidence['unit_terminal_observed']);self.assertTrue(evidence['cgroup_absent_after_cleanup'])
        with self.assertRaises(ValueError):self.finish(task)
        self.assertEqual(1,len(list(config.root.glob('run-*/receipt.json'))))
        self.assertEqual(0,self.host.missions.agent_governor.inspect(self.host.core.local_operator(Capability.READ))['exposure']['global']['money_nano'])

    def test_cpu_deadline_is_unknown_and_cannot_retry(self):
        self.unknown_fault(b'while True:\n    pass\n',reason='TIMEOUT')

    def test_memory_limit_is_unknown_and_cannot_retry(self):
        self.unknown_fault(b'value=bytearray(1024*1024*1024)\n',reason='EXITED',memory=True)

    def test_oversized_worker_output_is_unknown_and_cannot_retry(self):
        self.unknown_fault(b'import sys\nsys.stdout.write("x"*(1024*1024))\nsys.stdout.flush()\n',reason='OUTPUT_LIMIT')

    def test_stop_after_owned_cgroup_ready_never_runs_project_code(self):
        self.host_with(self.base);task=self.proposal();original=sandbox_linux.bounded_line;fired=[]
        def intercept(*args,**kwargs):
            value=original(*args,**kwargs)
            if value.get('stage')=='WORK_READY' and not fired:
                fired.append(True)
                self.host.missions.agent_stop(task['task_id'],self.host.core.local_operator(Capability.READ))
            return value
        with patch.object(sandbox_linux,'bounded_line',side_effect=intercept):result=self.finish(task)
        self.assertTrue(fired);self.assertEqual('AGENT_UNKNOWN',result['state'])
        data=agent_operations.plain(agent_operations._get(self.host.missions,task['task_id']).payload)
        warrant=agent_operations.EffectWarrant.from_dict(data['warrant'])
        request=agent_operations.dispatch_request(data['approval_payload']['operation'],warrant)
        evidence=json.loads((self.base.root/('run-'+request.digest)/'receipt.json').read_text())
        self.assertFalse(evidence['project_code_started']);self.assertTrue(evidence['cleanup'])
        self.assertTrue(evidence['unit_terminal_observed']);self.assertTrue(evidence['cgroup_absent_after_cleanup'])
        self.assertIsNone(result['receipt'])

    def test_git_post_commit_ack_loss_survives_restart_and_readback_without_second_commit(self):
        host=self.host_with(self.base);source=self.finish(self.proposal())
        self.assertEqual('AGENT_COMPLETED',source['state'])
        git=host.missions.propose_git(source['task_id'],uuid.uuid4().hex,host.core.local_operator(Capability.READ))
        data=agent_operations.plain(agent_operations._get(host.missions,git['task_id']).payload)
        route,_,_=agent_operations._local_binding(host.missions,data)
        route.verifier=lambda *_:(_ for _ in ()).throw(ValueError('injected post-commit readback ACK loss'))
        unknown=self.finish(git);self.assertEqual('AGENT_UNKNOWN',unknown['state'])
        host.close();host=self.host_with(self.base)
        reader=host.core.local_operator(Capability.READ)
        with self.assertRaises(ValueError):self.finish(git)
        done=host.missions.reconcile_agent(git['task_id'],reader)
        self.assertEqual('AGENT_COMPLETED',done['state'])
        self.assertEqual(git['git']['commit_sha'],done['receipt']['git']['head'])
        _,config,_=agent_operations._local_binding(host.missions,agent_operations.plain(
            agent_operations._get(host.missions,git['task_id']).payload))
        self.assertEqual(1,len(list(config.root.glob('run-*/receipt.json'))))
        self.assertFalse(done['receipt']['git']['remote_write_performed'])


if __name__=='__main__':unittest.main(verbosity=2)
