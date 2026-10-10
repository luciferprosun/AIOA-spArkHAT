"""Fresh-process synthetic target faults, bounded disposable files only."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import fcntl
import json
import os
import sys
import time

from q09_support import Fixture, DurableTransaction
from nv03_support import atomic_json
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.warrant import EffectWarrant
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.outcome import Applied, NotApplied
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionContext, RecordKind
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.mission.tools import CoreToolRoute, TargetSnapshot, CONTEXT


def main():
    mode,path_text=sys.argv[1:];path=Path(path_text);fx=Fixture(path)
    def read(tx):
        row=tx.get(RecordKind.OPERATION,canonical_sha256((CONTEXT,fx.ledger.scope,'nonce-1')))
        assert row is not None
        return json.loads(canonical_json_bytes(row.payload))
    context=fx.runner.run(TransactionContext(fx.p(Capability.READ),Capability.READ),read)
    warrant=EffectWarrant.from_dict(context['warrant'])
    binding=TaskCompletionBinding.parse(context['completion'])
    request=ReservationRequest(**context['reservation'])
    snapshot=TargetSnapshot(warrant.target_fingerprint,warrant.expected_target_revision,
                            DecisionDependencyRoot.from_dict(context['target_ddr']))
    target=path.with_suffix('.target.json');counter=path.with_suffix('.attempts')
    @contextmanager
    def guard():
        # One trusted target path for every process, distinct from target-CAS lock.
        with path.with_suffix('.lifecycle.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)
    def pause():
        path.with_suffix('.ready').write_text('ready')
        deadline=time.monotonic()+10
        while not path.with_suffix('.release').exists():
            if time.monotonic()>=deadline:raise RuntimeError('fixture barrier timeout')
            time.sleep(.01)
    probes=[]
    def probe():
        probes.append(1)
        if mode=='hold-start' and len(probes)==2:pause()
        if not target.exists():return snapshot
        observed=json.loads(target.read_text())
        return TargetSnapshot(observed['fingerprint'],observed['revision'],snapshot.ddr)
    def execute(operation,decision,limits):
        if mode=='hold-effect':pause()
        # Independently durable attempt count, outside Core transaction and its marker.
        with counter.open('a') as stream:
            stream.write('attempt\n');stream.flush();os.fsync(stream.fileno())
        with path.with_suffix('.target.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            old=json.loads(target.read_text()) if target.exists() else {
                'fingerprint':snapshot.fingerprint,'revision':snapshot.revision,'operation':None}
            assert old['fingerprint']==operation['target_fingerprint']
            assert old['revision']==operation['expected_target_revision']
            atomic_json(target,{'fingerprint':old['fingerprint'],'revision':'revision-2',
                                'operation':decision.operation_hash})
        if mode=='effect-crash':os._exit(75)
    def verify(operation,decision):
        path.with_suffix('.verifier-entered').write_text('entered')
        if target.exists():
            observed=json.loads(target.read_text())
            assert observed['operation']==decision.operation_hash and observed['revision']=='revision-2'
            receipt=EvidenceRef('process-receipt','receipt','sha256:'+canonical_sha256(observed),'v1')
            return Reconciliation(decision.operation_hash,Applied(receipt.evidence_id),receipt,
                EvidenceRef('process-readback','independent-readback','sha256:'+'b'*64,'v1'))
        certificate=EvidenceRef('process-no-effect','no-effect-certificate','sha256:'+'c'*64,'v1')
        return Reconciliation(decision.operation_hash,NotApplied((certificate,)),certificate,
            EvidenceRef('process-absent','independent-readback','sha256:'+'d'*64,'v1'))
    route=CoreToolRoute(fx.journal,CoreLiabilityLedger(fx.core,fx.runner,fx.ledger.scope),
        workspace='workspace-1',policy_revision=1,probe=probe,executor=execute,target_guard=guard,verifier=verify,
        clock=lambda:int(warrant.issued_at.timestamp()))
    operation=route.operation({'action':'write_file','path':'src/main.py','content':'print(1)\n'},snapshot)
    assert 'sha256:'+canonical_sha256(operation)==warrant.operation_hash
    if mode=='reconcile':
        path.with_suffix('.reconcile-started').write_text('started')
        result=route.reconcile(fx.p(),warrant,1)
        print('FRESH_PROCESS_'+result['outcome']['contract_type'])
        fx.close();return
    if mode in ('crash-before-start','crash-after-start'):

        original=DurableTransaction.commit
        def crash(tx):
            if tx.snapshot==tx.factory.state:return original(tx)
            if mode=='crash-after-start':original(tx)
            os._exit(75)
        DurableTransaction.commit=crash
    result=route.dispatch(fx.p(),session_id=context['session_id'],warrant=warrant,
                          operation=operation,reservation=request,completion=binding)
    assert result['outcome']['contract_type']=='Unknown'
    records=route.liability.inspect(fx.p(Capability.READ),warrant.task_id)
    assert records and records[0].status.value=='OPEN'
    print('FRESH_PROCESS_UNKNOWN_NO_REPLAY')
    fx.close()


if __name__=='__main__':main()
