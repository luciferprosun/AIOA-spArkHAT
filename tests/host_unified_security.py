"""U9 cross-contract and filesystem adversarial cases on the real Core path."""
from datetime import timedelta
from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

from runtime.core_admission import Capability,OwnerScope,AdmissionError
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.meta_hackathon import agent_operations as operations
from runtime.mission.tools import SessionGrant,LocalSessionGrant
from lab.archaioa.warrant import EffectWarrant




class UnifiedAuthoritySecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        cls.prep=tempfile.TemporaryDirectory()
        cls.config=prepare_sensorbridge_sandbox(Path(cls.prep.name)/'sandbox',workspace='workspace-sensorbridge')

    @classmethod
    def tearDownClass(cls):cls.prep.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:('1'*40,'a'*64))
        self.addCleanup(self.host.close)
        self.owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        self.reader=self.host.core.local_operator(Capability.READ)
        self.host.missions.bind_agent_tools(self.config,self.owner)

    def propose(self):
        return self.host.missions.propose_agent({'schema':'aioa.agent-proposal.v2','recipe_id':'sensorbridge-v1',
            'provider_id':'meta_model_api','request_id':__import__('uuid').uuid4().hex},self.reader)

    def finish(self,task):
        self.host.missions.run_agent(task['task_id'],task['preview_digest'],self.owner)
        self.host.missions._workers[task['task_id']].join(40)
        return self.host.missions.agent_view(task['task_id'],self.reader)

    def edit(self,task,mutate):
        def change(tx):
            row=tx.get(RecordKind.OPERATION,task['task_id']);data=operations.plain(row.payload);mutate(data)
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,data),expected_revision=row.revision)
        self.host.missions._run(Capability.COMMIT,change)

    def test_narrower_human_session_cannot_authorize_larger_worker_limits(self):
        task=self.propose()
        def narrow(data):
            approval=data['approval_payload'];grant=LocalSessionGrant.parse(approval['session_grant'])
            grant=replace(grant,deadline_seconds=1,output_bytes=1024)
            approval['session_grant']=grant.to_dict()
            approval['operation']['payload']['session_grant_digest']=grant.digest
            data['preview_digest']=canonical_sha256(approval)
        self.edit(task,narrow)
        current=self.host.missions.agent_view(task['task_id'],self.reader)
        result=self.finish(current)
        self.assertEqual('AGENT_UNKNOWN',result['state'])
        self.assertEqual({},self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_valid_but_expired_owner_principal_denies(self):
        task=self.propose();clock=self.host.core._clock
        self.host.core._clock=lambda:self.owner.expires_at+timedelta(seconds=1)
        try:
            with self.assertRaises(AdmissionError):
                self.host.missions.run_agent(task['task_id'],task['preview_digest'],self.owner)
        finally:self.host.core._clock=clock
        self.assertEqual({},self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_revoked_session_and_policy_epoch_change_deny_before_start(self):
        for mutation in ('revoked','epoch'):
            with self.subTest(mutation=mutation):
                task=self.propose();lock=self.host.missions._agent_effect_lock
                lock.acquire()
                try:
                    self.host.missions.run_agent(task['task_id'],task['preview_digest'],self.owner)
                    if mutation=='revoked':
                        self.host.missions.agent_route.revoke_session(self.host.core.local_operator(Capability.MANAGE),task['operation']['payload']['session_id'])
                    else:self.host.missions.agent_governor.start_epoch(self.host.core.local_operator(Capability.MANAGE))
                finally:lock.release()
                self.host.missions._workers[task['task_id']].join(40)
                self.assertEqual('AGENT_UNKNOWN',self.host.missions.agent_view(task['task_id'],self.reader)['state'])
                self.assertEqual({},self.host.missions.agent_governor.inspect(self.reader)['reservations'])

    def test_independent_readback_rejects_symlink_and_hardlink_receipts(self):
        task=self.propose();done=self.finish(task)
        self.assertEqual('AGENT_COMPLETED',done['state'])
        data=operations.plain(operations._get(self.host.missions,task['task_id']).payload)
        warrant=EffectWarrant.from_dict(data['warrant']);operation=data['approval_payload']['operation']
        request=operations.dispatch_request(operation,warrant)
        path=self.config.root/('run-'+request.digest)/'receipt.json';saved=path.with_name('saved-receipt.json')
        path.rename(saved)
        try:
            path.symlink_to(saved)
            with self.subTest(kind='symlink'),self.assertRaises((ValueError,OSError)):
                self.host.missions.agent_broker.verify(operation,warrant)
        finally:
            path.unlink();saved.rename(path)
        hard=path.with_name('hard-receipt.json');os.link(path,hard)
        try:
            with self.subTest(kind='hardlink'),self.assertRaises((ValueError,OSError)):
                self.host.missions.agent_broker.verify(operation,warrant)
        finally:hard.unlink()


if __name__=='__main__':unittest.main()
