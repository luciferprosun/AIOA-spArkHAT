"""Explicit owned real-Linux acceptance; excluded from ordinary test discovery.

Operator: source-only -I -B bootstrap, pinned manifest, private fixture root and
existing user bus. This source operator driver is not an installed product API.
"""
import hashlib
import json
import os
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_nz13_sandbox_job_bindings import SandboxJobBindingTests

from runtime.core_admission import Capability
from runtime.mission.job_contracts import JobClaim
from runtime.mission.sandbox_linux import LinuxSandboxBroker, prepare_linux_sandbox
from runtime.mission.tools import CoreToolRoute
from runtime.providers.exact import CancellationToken

RUNTIME_MANIFEST=Path('/media/l/LSC_DATA3/AIOA_NZ13_PRIVATE_20261108/artifacts/D10_ACTUAL_FUNCTION_R1/PYTHON_RUNTIME_PREPARATION.json')


class ActualSandboxJobBindingTests(unittest.TestCase):
    """Explicitly selected real Linux acceptance; not ordinary discovery."""
    setUp=SandboxJobBindingTests.setUp
    p=SandboxJobBindingTests.p
    prepare=SandboxJobBindingTests.prepare
    route=SandboxJobBindingTests.route
    managed=SandboxJobBindingTests.managed
    parts=SandboxJobBindingTests.parts
    bind=SandboxJobBindingTests.bind
    start=SandboxJobBindingTests.start

    def test_A1BROKER_2SUCCESSIVE_REPAIR_SPECS_RETAINED_READBACK(self):
        import subprocess

        from runtime.mission import repair
        from runtime.mission.repair_validation import (
            CoreRepositoryMaterializer,
            CoreSandboxValidation,
        )
        from runtime.mission.sandbox_bindings import ObservationBindingInput
        from runtime.mission.sandbox_linux import _private_bytes
        runtime_path=RUNTIME_MANIFEST
        trusted=Path('/media/l/LSC_DATA3/AIOA_NZ13_PRIVATE_20261108')
        raw=_private_bytes(runtime_path,trusted,4194304)
        self.assertEqual('fe68478b7ffca20fc6c510b9187e15dafd80f7f4a80e4634eb1c7d56bdfc18b5',hashlib.sha256(raw).hexdigest())
        manifest={}
        for index,(target,entry) in enumerate(json.loads(raw)['manifest'].items()):
            data=_private_bytes(entry['snapshot'],trusted,entry['bytes'])
            self.assertEqual((entry['bytes'],entry['sha256']),(len(data),hashlib.sha256(data).hexdigest()))
            path=self.root/'runtime'/('full-'+str(index));path.write_bytes(data)
            path.chmod(Path(entry['snapshot']).stat().st_mode & 0o700)
            manifest[target]={**entry,'snapshot':str(path)}
        self.manifest=manifest
        self.epoch=self.gov.start_epoch(self.p(Capability.MANAGE))
        self.assertEqual(2,self.epoch)
        constructions={'broker':[],'route':[]};attempts=[]
        broker_init=LinuxSandboxBroker.__init__;route_init=CoreToolRoute.__init__
        broker_run=LinuxSandboxBroker._run
        def count_broker(instance,*args,**kwargs):
            constructions['broker'].append(id(instance));return broker_init(instance,*args,**kwargs)
        def count_route(instance,*args,**kwargs):
            constructions['route'].append(id(instance));return route_init(instance,*args,**kwargs)
        def count_attempt(instance,*args,**kwargs):
            attempts.append(id(instance));return broker_run(instance,*args,**kwargs)
        for cls,name,method in ((LinuxSandboxBroker,'__init__',count_broker),
                               (CoreToolRoute,'__init__',count_route),(LinuxSandboxBroker,'_run',count_attempt)):
            patcher=patch.object(cls,name,method);patcher.start();self.addCleanup(patcher.stop)
        broker,route,first=self.managed()
        # The fixed approved fixture budget remains risk200, and every actual
        # sandbox effect still reserves risk5. No Native/mobile policy changes.
        print('ACTUAL_TASK2_STARTED',self.root,flush=True)
        steps=[];configs=[first];receipts=[]
        def prepared(specs,binding_input):
            if not steps:
                capture=first
            else:
                config=prepare_linux_sandbox(self.root/('batch-'+str(len(configs))),self.manifest,
                    workspace='workspace-1',recipes={str(i):spec for i,(_stage,spec) in enumerate(specs)})
                config=replace(config,registry=replace(config.registry,
                    recipes=tuple(replace(r,timeout_ms=20000) for r in config.registry.recipes)))
                capture=broker.capture_config(config,binding_input=binding_input,
                    recipe_stages=tuple((str(i),stage) for i,(stage,_spec) in enumerate(specs)))
                configs.append(capture)
            made=[]
            for index,(stage,_spec) in enumerate(specs):
                identity='actual-'+str(len(steps))+'-'+str(index)
                step,_handle,_claim=self.start(route,capture,identity,recipe_id=str(index),stage=stage)
                made.append(step);steps.append(step)
            return tuple(made)
        def materialize(spec,_predicted,*,binding_input):
            return prepared((('MATERIALIZE',spec),),binding_input)[0]
        def observe(_root,patchset,*,binding_input):
            self.assertIs(type(binding_input),ObservationBindingInput)
            specs=tuple((stage,self.profile.observation_spec(stage,binding_input.archive,patchset))
                        for stage in repair.TEST_STAGES)
            return prepared(specs,binding_input)
        materializer=CoreRepositoryMaterializer(self.journal,materialize,profile=self.profile,
            source_snapshot=self.source_snapshot,source_repository=self.source_support.repo.path,
            base_root=self.base,output_root=self.root/'candidates',sandbox_jobs=True)
        validation=CoreSandboxValidation(self.journal,observe,profile=self.profile,sandbox_jobs=True)
        results=[]
        for binding_input in self.binding_inputs:
            candidate=materializer.materialize(binding_input.task,binding_input.session,binding_input.candidate)
            predicted=self.profile.materialization_spec(self.base,source=self.source,task=binding_input.task,
                worker_session_id=binding_input.session.session_id,candidate=binding_input.candidate)[0]
            session=validation.open(candidate,predicted)
            outcomes=[session.run(stage) for stage in repair.TEST_STAGES]
            self.assertEqual(['PASS']*3,[outcome.status for outcome in outcomes],session.failure_code)
            self.assertEqual(0,session.close())
            results.append([outcome.status for outcome in outcomes])
            for step in steps[len(receipts):]:
                raw,receipt,run=route.sandbox_receipt(self.p(Capability.READ),
                    operation=step.arguments['operation'],warrant=step.arguments['warrant'])
                self.assertTrue(receipt['project_code_started'])
                self.assertEqual('READBACK_VERIFIED',receipt['status'])
                state=self.gov.inspect_job(self.p(Capability.READ),step.arguments['completion'].task_id)
                self.gov.finish_offline_host_job(self.p(),JobClaim(**state['claim']))
                receipts.append({'task_id':step.arguments['completion'].task_id,
                    'operation':step.arguments['operation'],'warrant':step.arguments['warrant'].to_dict(),
                    'raw_sha256':hashlib.sha256(raw).hexdigest(),'run_ref':str(run.relative_to(self.root))})
        for step,retained in zip(steps,receipts,strict=True):
            raw,_receipt,_run=route.sandbox_receipt(self.p(Capability.READ),
                operation=step.arguments['operation'],warrant=step.arguments['warrant'])
            self.assertEqual(retained['raw_sha256'],hashlib.sha256(raw).hexdigest())
        # Real STOP at the final release boundary: no Y, retained UNKNOWN,
        # no second attempt, and no optimistic release of the owner fence.
        stopped,_handle,_claim=self.start(route,first,'actual-stopped-before-Y')
        token=CancellationToken();probes=[]
        def stop_probe():
            probes.append(1)
            if len(probes)==4:token.cancel()
            return self.snapshot
        route.probe=stop_probe
        route.dispatch(stopped.principal,**stopped.arguments,cancel=token)
        stop_raw,stop_receipt,stop_run=route.sandbox_receipt(self.p(Capability.READ),
            operation=stopped.arguments['operation'],warrant=stopped.arguments['warrant'])
        self.assertTrue(token.cancelled)
        self.assertFalse(stop_receipt['project_code_started'])
        self.assertEqual('UNKNOWN',stop_receipt['status'])
        self.assertEqual(9,len(attempts))
        route.dispatch(stopped.principal,**stopped.arguments)
        self.assertEqual(9,len(attempts))
        self.assertEqual((1,1),(len(constructions['broker']),len(constructions['route'])))
        manifest={'schema':'owned.task2.actual.v1','root':str(self.root),'scope':list(self.scope.binding()),
            'profile_digest':first.config.profile_digest,'seed_root_ref':first.config.root.name,
            'source_repository':str(self.source_support.repo.path),'source_base_sha':self.source_support.repo.base,
            'base_root':str(self.base),'receipts':receipts,'broker_count':len(constructions['broker']),'route_count':len(constructions['route']),
            'attempts':len(attempts),'stop_receipt_sha256':hashlib.sha256(stop_raw).hexdigest(),
            'stop_run_ref':str(stop_run.relative_to(self.root)),'stop_project_ack':False,
            'broker_object_id':id(broker),'route_object_id':id(route),'project_acks':len(receipts),
            'canonical_epoch':self.epoch,'configs':[{'root_ref':capture.config.root.name,'config_digest':capture.config_digest}
                       for capture in configs],'validation':results,'provider_calls':0}
        manifest_path=self.root/'actual-manifest.json'
        manifest_path.write_bytes(json.dumps(manifest,sort_keys=True,indent=2).encode())
        manifest_path.chmod(0o600)
        broker.close();self.runner.close();self.core.close()
        child=Path('/media/l/LSC_DATA3/AIOA_NZ13_PRIVATE_20261108/scripts/nz13_task2_history_readback_r1.py')
        result=subprocess.run([__import__('sys').executable,'-I','-B',str(child),str(manifest_path)],
            capture_output=True,timeout=120,check=False,env=dict(os.environ))
        (self.root/'restart.log').write_bytes(result.stdout+result.stderr)
        self.assertEqual(0,result.returncode,result.stderr.decode())
        report=json.loads((self.root/'restart-result.json').read_bytes())
        self.assertEqual(('HISTORY_ONLY',0,8),(report['mode'],report['project_acks'],report['readbacks']))
        print('ACTUAL_TASK2_FIXTURE',self.root,'ACKS',len(receipts),'BROKER',id(broker),'ROUTE',id(route))



def main(manifest_path,fixture_root):
    global RUNTIME_MANIFEST
    from runtime.mission.sandbox_linux import _private_path
    trusted=Path('/media/l/LSC_DATA3/AIOA_NZ13_PRIVATE_20261108')
    _private_path(fixture_root,trusted,directory=True)
    _private_path(manifest_path,trusted)
    RUNTIME_MANIFEST=manifest_path
    os.environ['NZ13_NATIVE_TASK_FIXTURES']=str(fixture_root)
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ActualSandboxJobBindingTests)
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('Explicit manifest and private fixture root required')
    raise SystemExit(0 if main(Path(sys.argv[1]),Path(sys.argv[2])) else 1)
