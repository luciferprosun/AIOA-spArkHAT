"""Actual synthetic dispatch under native Core; no host tool or provider."""
from dataclasses import replace
from importlib.util import find_spec
from pathlib import Path
import concurrent.futures
import tempfile
import threading
import unittest
from unittest.mock import patch
from q09_support import Fixture, DurableTransaction
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.outcome import Applied, NotApplied
from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionContext, RecordKind, StoredRecord
from runtime.mission.completion import TaskCompletionBinding, TaskDependency
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.mission.governor import ReservationRequest
from test_dual_governor import MODEL


class CoreToolCompositionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(find_spec('runtime.mission.tools'),'Missing human-rooted common tool route')
        from runtime.mission.tools import CoreToolRoute, SessionGrant, TargetSnapshot
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'state.json'
        self.fx=Fixture(self.path);self.addCleanup(self.fx.close)
        self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        self.now=int(self.fx.warrant.issued_at.timestamp())
        self.current=TargetSnapshot(self.fx.warrant.target_fingerprint,'revision-1',DecisionDependencyRoot())
        self.calls=[];self.verifications=[];self.effects={}
        self.liability=CoreLiabilityLedger(self.fx.core,self.fx.runner,self.fx.ledger.scope)
        self.lifecycle=threading.RLock()
        self.route=CoreToolRoute(self.fx.journal,self.liability,workspace='workspace-1',policy_revision=1,
            probe=lambda:self.current,executor=self.execute,target_guard=lambda:self.lifecycle,verifier=self.verify,clock=lambda:self.now)
        self.proposal={'action':'write_file','path':'src/main.py','content':'print(1)\n'}
        self.operation=self.route.operation(self.proposal,self.current)
        self.trace=FaultTrace(FaultKind.LOST_ACK,'tool-task','tool-request','sha256:'+canonical_sha256(self.operation))
        self.identity=classify_fault(self.trace).liability_id
        self.graph=DependencyGraph('tool-task',(
            DependencyNode('effect',NodeKind.OPERATION,liability_ids=(self.identity,)),
            DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect',))))
        self.binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,self.graph,'completion')
        self.liability.initialize(self.fx.p(),self.graph)
        from runtime.providers.nvidia import ProviderRequest, ProviderResponse
        from runtime.mission.job_contracts import JobEnvelope
        request=ProviderRequest('advisory-tool-task','tool-trace','nebius',MODEL,
                                'synthetic advisory only','tool-budget',128,20)
        envelope=JobEnvelope.from_request(self.fx.ledger.scope,'tool-task',request,
                                         deadline_at=160,money_nano=1,risk_units=0)
        self.fx.gov.submit_job(self.fx.p(Capability.MANAGE),envelope,completion=self.binding)
        self.claim=self.fx.gov.claim_job(self.fx.p(),'tool-task','fixture-worker',1,lease_seconds=30)
        self.fx.gov.begin_job(self.fx.p(),self.claim)
        self.response=ProviderResponse(request.request_id,'synthetic-final',MODEL,101,'stop',100,
            {'summary':'Model done text is advisory','needs_attention':False},
            {'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
        self.grant=SessionGrant('session-1',self.fx.ledger.scope,'workspace-1',1,('PROJECT_WRITE',),
            self.binding.digest,self.now,self.now+120,1,100,10,20,4096)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),self.grant)
        self.warrant,self.request=self.authorize()

    def authorize(self,nonce='nonce-1'):
        w=self.route.authorize(self.fx.p(),self.grant.session_id,self.operation,self.binding,self.graph,
            self.trace,nonce=nonce,model_id=MODEL,money_nano=50,risk_units=5)
        return w,ReservationRequest(w.money_reservation_id,'tool-task','synthetic',MODEL,
                                    canonical_sha256(self.operation),50,5)

    def execute(self,operation,warrant,limits=None):
        self.calls.append(warrant.operation_hash)
        if operation['expected_target_revision']!=self.current.revision:raise ValueError('TARGET_CAS_DENIED')
        self.effects[warrant.operation_hash]=operation['payload']['content']

    def verify(self,operation,warrant):
        self.verifications.append(1)
        if warrant.operation_hash not in self.effects:return None
        return Reconciliation(warrant.operation_hash,Applied('target-receipt'),
            EvidenceRef('target-receipt','receipt','sha256:'+'a'*64,'v1'),
            EvidenceRef('target-readback','independent-readback','sha256:'+'b'*64,'v1'))

    def dispatch(self,**overrides):
        args=dict(session_id=self.grant.session_id,warrant=self.warrant,operation=self.operation,
                  reservation=self.request,completion=self.binding);args.update(overrides)
        return self.route.dispatch(self.fx.p(),**args)

    def assert_original_effect_and_journal(self, warrant=None):
        warrant=warrant or self.warrant
        self.assertEqual('print(1)\n',self.effects[warrant.operation_hash])
        intent=self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ),Capability.READ),
            lambda tx:self.fx.journal._load(tx,warrant)[1])
        self.assertEqual('print(1)\n',intent['operation']['payload']['content'])

    def test_authorize_snapshots_operation_before_target_probe(self):
        import copy
        original=copy.deepcopy(self.operation)
        def probe():
            self.operation['payload']['content']='print(999)\n'
            return self.current
        self.route.probe=probe
        try:warrant,request=self.authorize('copy-authorize')
        except ValueError as error:self.fail(f'Caller mutation changed authorization input: {error}')
        self.assertEqual(self.trace.operation_digest,warrant.operation_hash)
        request=replace(request,request_digest=self.trace.operation_digest.removeprefix('sha256:'))
        self.dispatch(warrant=warrant,reservation=request,operation=original)
        self.assert_original_effect_and_journal(warrant)

    def guard_mutation_preserves_operation(self, when):
        from contextlib import contextmanager
        def mutate():self.operation['payload']['content']='print(999)\n'
        @contextmanager
        def guarded():
            if when=='enter':mutate()
            with self.lifecycle:yield
        def factory():
            if when=='factory':mutate()
            return guarded()
        self.route.target_guard=factory
        try:self.dispatch()
        except ValueError as error:self.fail(f'Caller mutation changed dispatch input: {error}')
        self.assert_original_effect_and_journal()

    def test_dispatch_snapshots_operation_before_guard_factory(self):
        self.guard_mutation_preserves_operation('factory')

    def test_dispatch_snapshots_operation_before_guard_entry(self):
        self.guard_mutation_preserves_operation('enter')

    def test_post_start_probe_cannot_change_authorized_effect(self):
        probes=[]
        def probe():
            probes.append(1)
            if len(probes)==2:self.operation['payload']['content']='print(999)\n'
            return self.current
        self.route.probe=probe
        self.dispatch()
        self.assert_original_effect_and_journal()

    def test_executor_cannot_mutate_caller_operation(self):
        def execute(operation,warrant,limits):
            self.execute(operation,warrant,limits)
            operation['payload']['content']='print(999)\n'
        self.route.executor=execute
        self.dispatch()
        self.assertEqual('print(1)\n',self.operation['payload']['content'])
        self.assert_original_effect_and_journal()

    def test_real_synthetic_attempt_opens_required_g2_and_holds_exposure(self):
        result=self.dispatch();self.assertEqual('SYNTHETIC_ONLY',result['mode'])
        self.assertEqual('Unknown',result['outcome']['contract_type']);self.assertEqual(1,len(self.calls))
        self.assertEqual('OPEN',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)
        self.assertEqual(51,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['money_nano'])

    def test_missing_grant_denies_without_execution_or_state_change(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.dispatch(session_id='absent')
        self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def test_model_flags_and_sensitive_paths_cannot_lower_authority(self):
        for proposal in ({**self.proposal,'approved':True},{**self.proposal,'requires_confirmation':False},
                         *({**self.proposal,'path':p} for p in ('.git/hooks/pre-commit',
                            '.github/workflows/build.yml','pyproject.toml','../outside')),
                         {'action':'shell_execute','command':'true'}):
            with self.subTest(proposal=proposal),self.assertRaises(ValueError):self.route.operation(proposal,self.current)
        self.assertEqual([],self.calls)

    def test_payload_target_goal_dependency_and_ddr_drift_deny(self):
        for operation in ({**self.operation,'payload':{**self.operation['payload'],'content':'changed'}},
                          {**self.operation,'target_fingerprint':'sha256:'+'e'*64},
                          {**self.operation,'expected_target_revision':'changed'}):
            with self.assertRaises(ValueError):self.dispatch(operation=operation)
        for binding in (replace(self.binding,graph_digest='e'*64),replace(self.binding,candidate_id='other'),
                        replace(self.binding,dependencies=(TaskDependency(self.binding.scope,'B','d'*64,'candidate'),))):
            with self.assertRaises(ValueError):self.dispatch(completion=binding)
        self.current=replace(self.current,ddr=DecisionDependencyRoot((EvidenceRef('changed','dependency','sha256:'+'f'*64,'v2'),)))
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls)

    def test_fresh_target_revision_denies_before_consumption(self):
        self.current=replace(self.current,revision='revision-2')
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls);self.assertIsNone(self.fx.ledger.inspect(self.fx.p(Capability.READ),self.warrant))

    def test_revoke_denies_new_effect_but_keeps_readback(self):
        self.dispatch();other,request=self.authorize('revoked-new-nonce')
        self.route.revoke_session(self.fx.p(Capability.MANAGE),self.grant.session_id)
        with self.assertRaises(ValueError):self.dispatch(warrant=other,reservation=request)
        self.assertEqual('Unknown',self.dispatch()['outcome']['contract_type'])
        self.assertEqual('Unknown',self.route.inspect(self.fx.p(Capability.READ),self.warrant)['outcome']['contract_type'])
        self.assertEqual('Applied',self.route.reconcile(self.fx.p(),self.warrant,1)['outcome']['contract_type'])
        self.assertEqual(1,len(self.calls))

    def test_expiry_kill_stale_epoch_deny(self):
        self.now=self.grant.expires_at
        with self.assertRaises(ValueError):self.dispatch()
        self.now=self.grant.issued_at;self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),True)
        with self.assertRaises(ValueError):self.dispatch()
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),False);self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls)

    def test_native_job_lease_expiry_with_live_grant_denies_authorize_and_dispatch(self):
        self.fx.gov.clock=lambda:130
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.authorize('expired-job')
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def test_current_grant_cannot_use_previous_epoch_native_claim(self):
        self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        self.grant=replace(self.grant,session_id='new-epoch-session',epoch=2)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),self.grant)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.authorize('stale-job-claim')
        self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def fresh_gate_after_start(self,change):
        probes=[]
        def probe():
            probes.append(1)
            if len(probes)==2:change()
            return self.current
        self.route.probe=probe
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls)
        self.assertEqual('Unknown',self.route.inspect(self.fx.p(Capability.READ),self.warrant)['outcome']['contract_type'])
        self.assertEqual('OPEN',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)
        self.assertEqual(51,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['money_nano'])

    def test_job_expiring_after_start_keeps_unknown_without_attempt(self):
        self.fresh_gate_after_start(lambda:setattr(self.fx.gov,'clock',lambda:160))

    def test_revoked_after_start_keeps_unknown_without_attempt(self):
        self.fresh_gate_after_start(lambda:self.route.revoke_session(self.fx.p(Capability.MANAGE),self.grant.session_id))

    def test_policy_drift_after_start_keeps_unknown_without_attempt(self):
        self.fresh_gate_after_start(lambda:setattr(self.route,'policy_revision',2))

    def test_kill_after_start_keeps_unknown_without_attempt(self):
        self.fresh_gate_after_start(lambda:self.fx.gov.set_kill(self.fx.p(Capability.MANAGE),True))

    def test_target_drift_after_start_keeps_unknown_without_attempt(self):
        self.fresh_gate_after_start(lambda:setattr(self,'current',replace(self.current,revision='revision-2')))

    def concurrent_reconcile_cannot_retire_active_attempt(self,inside_executor):
        import copy,threading
        entered=threading.Event();release=threading.Event();verifier_entered=threading.Event()
        started=threading.Event();probes=[]
        def pause():
            entered.set()
            if not release.wait(5):raise RuntimeError('test barrier timeout')
        def probe():
            probes.append(1)
            if not inside_executor and len(probes)==2:pause()
            return self.current
        def execute(*args):
            if inside_executor:pause()
            self.execute(*args)
        def verify(operation,warrant):
            verifier_entered.set()
            if self.calls:return self.verify(operation,warrant)
            return Reconciliation(warrant.operation_hash,NotApplied((EvidenceRef('no-effect','no-effect-certificate','sha256:'+'c'*64,'v1'),)),
                EvidenceRef('no-effect','no-effect-certificate','sha256:'+'c'*64,'v1'),
                EvidenceRef('absent-readback','independent-readback','sha256:'+'d'*64,'v1'))
        # A different route object shares the same trusted target lifecycle port.
        other=copy.copy(self.route);other.verifier=verify
        self.route.probe=probe;self.route.executor=execute
        def reconcile():
            started.set()
            return other.reconcile(self.fx.p(),self.warrant,1)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            dispatch=pool.submit(self.dispatch)
            try:
                self.assertTrue(entered.wait(3),'dispatch did not reach durable START barrier')
                finish=pool.submit(reconcile);self.assertTrue(started.wait(3))
                verified_while_attempt_pending=verifier_entered.wait(.25)
            finally:release.set()
            dispatch.result(timeout=5);result=finish.result(timeout=5)
        self.assertFalse(verified_while_attempt_pending,'NotApplied verifier raced an active permitted attempt')
        self.assertEqual(1,len(self.calls));self.assertEqual('Applied',result['outcome']['contract_type'])
        self.assertEqual('CLOSED',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)

    def test_reconcile_serializes_with_attempt_after_start_across_route_instances(self):
        self.concurrent_reconcile_cannot_retire_active_attempt(False)

    def test_reconcile_serializes_with_active_executor_before_target_write(self):
        self.concurrent_reconcile_cannot_retire_active_attempt(True)

    def test_native_deadline_expiry_with_live_grant_denies_dispatch(self):
        self.fx.gov.clock=lambda:160
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def test_missing_or_failed_lifecycle_guard_cannot_start(self):
        from runtime.mission.tools import CoreToolRoute
        with self.assertRaises(ValueError):
            CoreToolRoute(self.fx.journal,self.liability,workspace='workspace-1',policy_revision=1,
                probe=lambda:self.current,executor=self.execute)
        def unavailable():raise OSError('unavailable')
        self.route.target_guard=unavailable;before=self.path.read_bytes()
        with self.assertRaises(OSError):self.dispatch()
        self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def test_duplicate_and_competing_starts_count_one_executor_attempt(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.dispatch(),range(2)))
        self.assertEqual(1,len(self.calls));self.assertTrue(all(r['outcome']['contract_type']=='Unknown' for r in results))
        self.dispatch();self.assertEqual(1,len(self.calls))

    def test_lost_commit_ack_holds_unknown_without_dispatch_or_replay(self):
        original=DurableTransaction.commit
        def lost(tx):
            changed=tx.snapshot!=tx.factory.state
            original(tx)
            if changed:raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',lost),self.assertRaises(CommitOutcomeUnknown):self.dispatch()
        self.assertEqual([],self.calls);self.dispatch();self.assertEqual([],self.calls)
        self.assertEqual('OPEN',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)

    def test_unknown_blocks_revised_nonce_and_required_completion(self):
        self.dispatch();other,req=self.authorize('nonce-2')
        with self.assertRaises(ValueError):self.dispatch(warrant=other,reservation=req)
        def finish(tx):return self.liability.require_completion_in_transaction(tx,'tool-task','completion',self.binding.graph_digest)
        with self.assertRaises(ValueError):self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),finish)
        with self.assertRaises(ValueError):self.fx.gov.finish_job(self.fx.p(),self.claim,self.response)
        self.assertEqual('STARTED',self.fx.gov.inspect_job(self.fx.p(Capability.READ),'tool-task')['state'])
        self.assertEqual(1,len(self.calls))

    def test_closed_required_effect_cannot_be_silently_repeated(self):
        self.dispatch();self.route.reconcile(self.fx.p(),self.warrant,1);other,req=self.authorize('nonce-2')
        with self.assertRaises(ValueError):self.dispatch(warrant=other,reservation=req)
        self.assertEqual(1,len(self.calls))

    def test_retained_reconciliation_never_reverifies_or_rewrites(self):
        self.dispatch();first=self.route.reconcile(self.fx.p(),self.warrant,1);before=self.path.read_bytes()
        self.assertEqual(first,self.route.reconcile(self.fx.p(),self.warrant,1))
        self.assertEqual([1],self.verifications);self.assertEqual(before,self.path.read_bytes())
        def finish(tx):return self.liability.require_completion_in_transaction(tx,'tool-task','completion',self.binding.graph_digest)
        self.assertEqual([self.identity],self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),finish)['applied_liability_ids'])
        result=self.fx.gov.finish_job(self.fx.p(),self.claim,self.response)
        self.assertEqual('DONE',result['state']);self.assertEqual('COMPLETED',result['task_completion'])
        self.assertEqual('NONE',result['authority']);self.assertEqual('UNVERIFIED',result['verification'])

    def test_missing_receipt_keeps_unknown_and_exposure(self):
        self.dispatch();self.effects.clear()
        with self.assertRaises(ValueError):self.route.reconcile(self.fx.p(),self.warrant,1)
        self.assertEqual('Unknown',self.route.inspect(self.fx.p(Capability.READ),self.warrant)['outcome']['contract_type'])
        self.dispatch();self.assertEqual(1,len(self.calls))

    def test_corrupt_session_cannot_be_recreated_by_model(self):
        def corrupt(tx):
            row=tx.get(RecordKind.OPERATION,self.route.session_key(self.grant.session_id))
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                {**row.payload,'revoked':'false'}),expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),corrupt);before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.dispatch()
        self.assertEqual(before,self.path.read_bytes());self.assertEqual([],self.calls)

    def test_forged_or_wrong_purpose_principal_cannot_create_session(self):
        for principal in (None,{'approved':True},self.fx.core.critic_candidate(),self.fx.p()):
            with self.assertRaises(ValueError):self.route.create_session(principal,replace(self.grant,session_id='forged'))
        self.assertEqual([],self.calls)

    def test_dispatch_cannot_reduce_trusted_risk_money_or_change_model_provider(self):
        for request in (replace(self.request,risk_units=1),replace(self.request,money_nano=1),
                        replace(self.request,provider_id='other'),replace(self.request,model_id='other')):
            before=self.path.read_bytes()
            with self.assertRaises(ValueError):self.dispatch(reservation=request)
            self.assertEqual(before,self.path.read_bytes())
        self.assertEqual([],self.calls)

    def test_changed_context_session_binding_denies_readback_and_reconciliation(self):
        self.dispatch()
        def corrupt(tx):
            row=tx.get(RecordKind.OPERATION,self.route._context_key(self.warrant))
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                {**row.payload,'grant_digest':'f'*64}),expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),corrupt)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):self.route.inspect(self.fx.p(Capability.READ),self.warrant)
        with self.assertRaises(ValueError):self.route.reconcile(self.fx.p(),self.warrant,1)
        self.assertEqual(before,self.path.read_bytes());self.assertEqual([],self.verifications)

    def test_route_cannot_mint_a_second_purpose_principal_during_dispatch(self):
        principal=self.fx.p()
        with patch.object(self.fx.core,'local_operator',side_effect=AssertionError('new principal forbidden')):
            self.route.dispatch(principal,session_id=self.grant.session_id,warrant=self.warrant,
                operation=self.operation,reservation=self.request,completion=self.binding)
        self.assertEqual(1,len(self.calls))

    def test_missing_required_native_job_cannot_authorize_effect(self):
        trace=replace(self.trace,task_id='no-native-job')
        identity=classify_fault(trace).liability_id
        graph=DependencyGraph(trace.task_id,(
            DependencyNode('effect',NodeKind.OPERATION,liability_ids=(identity,)),
            DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect',))))
        binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,graph,'completion')
        grant=replace(self.grant,session_id='without-job',completion_digest=binding.digest)
        self.liability.initialize(self.fx.p(),graph)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),grant)
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.route.authorize(self.fx.p(),grant.session_id,self.operation,binding,graph,trace,
                nonce='no-job-nonce',model_id=MODEL,money_nano=50,risk_units=5)
        self.assertEqual(before,self.path.read_bytes());self.assertEqual([],self.calls)

    def test_unadmitted_principal_is_rejected_before_target_probe(self):
        for principal in (None, {'approved': True}, self.fx.core.critic_candidate(),
                          self.fx.p(Capability.READ)):
            with self.subTest(principal=type(principal).__name__):
                probes=[];before=self.path.read_bytes()
                with patch.object(self.route,'probe',side_effect=lambda:probes.append(1) or self.current):
                    with self.assertRaises(ValueError):
                        self.route.authorize(principal,self.grant.session_id,self.operation,self.binding,
                            self.graph,self.trace,nonce='invalid-principal',model_id=MODEL,money_nano=50,risk_units=5)
                    with self.assertRaises(ValueError):
                        self.route.dispatch(principal,session_id=self.grant.session_id,warrant=self.warrant,
                            operation=self.operation,reservation=self.request,completion=self.binding)
                self.assertEqual([],probes);self.assertEqual(before,self.path.read_bytes())

    def test_synthetic_target_receives_immutable_human_resource_limits(self):
        budgets=[]
        def execute(operation,warrant,limits):
            budgets.append(limits);self.execute(operation,warrant)
        self.route.executor=execute;self.dispatch()
        self.assertEqual(1,len(self.calls));self.assertEqual(1,len(budgets))
        self.assertEqual(self.grant.deadline_seconds,budgets[0].deadline_seconds)
        self.assertEqual(self.grant.output_bytes,budgets[0].output_bytes)
        self.assertEqual('OFF',budgets[0].egress)
        with self.assertRaises((AttributeError,TypeError)):budgets[0].output_bytes=999999

    def two_effects(self, *, second_money=60, second_risk=5):
        from runtime.providers.nvidia import ProviderRequest
        from runtime.mission.job_contracts import JobEnvelope
        operations=[self.route.operation({**self.proposal,'content':f'print({i})\n'},self.current)
                    for i in (10,20)]
        traces=[FaultTrace(FaultKind.LOST_ACK,'two-effects',f'request-{i}',
                          'sha256:'+canonical_sha256(op)) for i,op in enumerate(operations)]
        graph=DependencyGraph('two-effects',tuple(
            DependencyNode(f'effect-{i}',NodeKind.OPERATION,liability_ids=(classify_fault(t).liability_id,))
            for i,t in enumerate(traces))+(DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,
                                                        ('effect-0','effect-1')),))
        binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,graph,'completion')
        self.liability.initialize(self.fx.p(),graph)
        provider_request=ProviderRequest('two-advisory','two-trace','nebius',MODEL,'fixture','budget',128,20)
        envelope=JobEnvelope.from_request(self.fx.ledger.scope,graph.task_id,provider_request,
                                         deadline_at=160,money_nano=1,risk_units=0)
        self.fx.gov.submit_job(self.fx.p(Capability.MANAGE),envelope,completion=binding)
        claim=self.fx.gov.claim_job(self.fx.p(),graph.task_id,'fixture-worker',1,lease_seconds=30)
        self.fx.gov.begin_job(self.fx.p(),claim)
        grant=replace(self.grant,session_id='two-session',completion_digest=binding.digest)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),grant)
        args=[]
        for i,(op,trace,money,risk) in enumerate(zip(operations,traces,(50,second_money),(5,second_risk))):
            w=self.route.authorize(self.fx.p(),grant.session_id,op,binding,graph,trace,
                                  nonce=f'two-nonce-{i}',model_id=MODEL,money_nano=money,risk_units=risk)
            args.append(dict(session_id=grant.session_id,warrant=w,operation=op,completion=binding,
                reservation=ReservationRequest(w.money_reservation_id,graph.task_id,'synthetic',MODEL,
                                               canonical_sha256(op),money,risk)))
        return args

    def test_aggregate_money_cap_includes_settled_effects(self):
        args=self.two_effects(second_money=60)
        self.route.dispatch(self.fx.p(),**args[0]);self.route.reconcile(self.fx.p(),args[0]['warrant'],1)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'SESSION_BUDGET_EXCEEDED'):
            self.route.dispatch(self.fx.p(),**args[1])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(1,len(self.calls))

    def test_aggregate_risk_cap_includes_settled_effects(self):
        args=self.two_effects(second_money=50,second_risk=6)
        self.route.dispatch(self.fx.p(),**args[0]);self.route.reconcile(self.fx.p(),args[0]['warrant'],1)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'SESSION_BUDGET_EXCEEDED'):
            self.route.dispatch(self.fx.p(),**args[1])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(1,len(self.calls))

    def test_renamed_started_context_cannot_hide_charged_history(self):
        args=self.two_effects(second_money=40)
        self.route.dispatch(self.fx.p(),**args[0]);self.route.reconcile(self.fx.p(),args[0]['warrant'],1)
        def corrupt(tx):
            row=tx.get(RecordKind.OPERATION,self.route._context_key(args[0]['warrant']))
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                {**row.payload,'schema':'hidden-context'}),expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),corrupt)
        before=self.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'TOOL_CONTEXT_REQUIRED'):
            self.route.dispatch(self.fx.p(),**args[1])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(1,len(self.calls))

    def test_atomic_resolution_rolls_back_both_ledgers_and_governor(self):
        self.dispatch();before=self.path.read_bytes()
        with patch.object(self.fx.journal,'apply_resolution_in_transaction',side_effect=ValueError('injected')):
            with self.assertRaises(MemoryPatchError):self.route.reconcile(self.fx.p(),self.warrant,1)
        self.assertEqual(before,self.path.read_bytes())
        self.assertEqual('Unknown',self.route.inspect(self.fx.p(Capability.READ),self.warrant)['outcome']['contract_type'])
        self.assertEqual('OPEN',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)
        self.assertEqual(5,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['risk_units'])
        self.route.reconcile(self.fx.p(),self.warrant,1);self.assertEqual(1,len(self.calls))

    def test_independent_not_applied_preserves_charge_and_cannot_finish_required_job(self):
        self.dispatch()
        self.route.verifier=lambda _op,w:Reconciliation(w.operation_hash,NotApplied((
            EvidenceRef('no-effect','independent-readback','sha256:'+'c'*64,'v1'),)),
            EvidenceRef('target-receipt','no-effect-certificate','sha256:'+'a'*64,'v1'),
            EvidenceRef('target-readback','independent-readback','sha256:'+'b'*64,'v1'))
        self.assertEqual('NotApplied',self.route.reconcile(self.fx.p(),self.warrant,1)['outcome']['contract_type'])
        self.assertEqual(5,self.fx.gov.inspect(self.fx.p(Capability.READ))['exposure']['global']['risk_units'])
        with self.assertRaises(ValueError):self.fx.gov.finish_job(self.fx.p(),self.claim,self.response)
        self.assertEqual('STARTED',self.fx.gov.inspect_job(self.fx.p(Capability.READ),'tool-task')['state'])

    def test_exact_duplicate_returns_retained_unknown_after_target_revision_changes(self):
        self.dispatch();self.current=replace(self.current,revision='revision-2')
        before=self.path.read_bytes()
        self.assertEqual('Unknown',self.dispatch()['outcome']['contract_type'])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(1,len(self.calls))
        altered={**self.operation,'payload':{**self.operation['payload'],'content':'forged'}}
        with self.assertRaises(ValueError):self.dispatch(operation=altered)
        self.assertEqual(1,len(self.calls));self.assertEqual(before,self.path.read_bytes())

    def test_exact_duplicate_after_required_done_is_retained_without_probe_or_new_charge(self):
        self.dispatch();self.route.reconcile(self.fx.p(),self.warrant,1)
        self.fx.gov.finish_job(self.fx.p(),self.claim,self.response)
        before=self.path.read_bytes()
        with patch.object(self.route,'probe',side_effect=AssertionError('retained read must not probe')):
            self.assertEqual('Applied',self.dispatch()['outcome']['contract_type'])
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(1,len(self.calls))

    def test_wrong_owner_workspace_and_foreign_core_deny_without_state_change(self):
        from runtime.core_admission import OwnerScope
        foreign=Fixture(Path(self.tmp.name)/'foreign.json');self.addCleanup(foreign.close)
        scope=replace(self.grant.scope,owner_id='foreign-owner')
        for grant in (replace(self.grant,session_id='wrong-owner',scope=scope),
                      replace(self.grant,session_id='wrong-workspace',workspace='workspace-2')):
            before=self.path.read_bytes()
            with self.assertRaises(ValueError):self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),grant)
            self.assertEqual(before,self.path.read_bytes())
        probes=[];before=self.path.read_bytes()
        with patch.object(self.route,'probe',side_effect=lambda:probes.append(1) or self.current):
            with self.assertRaises(ValueError):
                self.route.dispatch(foreign.p(),session_id=self.grant.session_id,warrant=self.warrant,
                    operation=self.operation,reservation=self.request,completion=self.binding)
        amplified={**self.operation,'payload':{**self.operation['payload'],'workspace':'workspace-2'}}
        with self.assertRaises(ValueError):self.dispatch(operation=amplified)
        self.assertEqual([],probes);self.assertEqual([],self.calls);self.assertEqual(before,self.path.read_bytes())

    def child(self,mode,expected=0):
        import subprocess,sys
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).with_name('core_tool_process_support.py')),
                               mode,str(self.path)],capture_output=True,text=True,timeout=20)
        self.assertEqual(expected,result.returncode,result.stderr)
        return result.stdout

    def attempt_count(self):
        counter=self.path.with_suffix('.attempts')
        return len(counter.read_text().splitlines()) if counter.exists() else 0

    def concurrent_process_reconcile(self,mode):
        import subprocess,sys,time
        command=[sys.executable,'-B',str(Path(__file__).with_name('core_tool_process_support.py'))]
        def wait_file(suffix):
            deadline=time.monotonic()+5
            while not self.path.with_suffix(suffix).exists():
                self.assertLess(time.monotonic(),deadline,'process barrier missing '+suffix)
                time.sleep(.01)
        first=subprocess.Popen([*command,mode,str(self.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        second=None
        try:
            wait_file('.ready')
            second=subprocess.Popen([*command,'reconcile',str(self.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            wait_file('.reconcile-started');time.sleep(.2)
            verified_early=self.path.with_suffix('.verifier-entered').exists()
        finally:
            self.path.with_suffix('.release').write_text('release')
            out1,err1=first.communicate(timeout=15)
            if second is not None:out2,err2=second.communicate(timeout=15)
        self.assertFalse(verified_early,'process verifier bypassed active target lifecycle guard')
        self.assertEqual(0,first.returncode,err1);self.assertEqual(0,second.returncode,err2)
        self.assertIn('FRESH_PROCESS_Applied',out2);self.assertEqual(1,self.attempt_count())
        self.assertEqual('Applied',self.route.inspect(self.fx.p(Capability.READ),self.warrant)['outcome']['contract_type'])
        self.assertEqual('CLOSED',self.liability.inspect(self.fx.p(Capability.READ),'tool-task')[0].status.value)

    def test_fresh_process_reconcile_waits_for_post_start_attempt(self):
        self.concurrent_process_reconcile('hold-start')

    def test_fresh_process_reconcile_waits_inside_executor_before_target_write(self):
        self.concurrent_process_reconcile('hold-effect')

    def test_two_fresh_process_admissions_execute_exactly_once(self):
        import subprocess,sys
        argv=[sys.executable,'-B',str(Path(__file__).with_name('core_tool_process_support.py')),'dispatch',str(self.path)]
        processes=[subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
        for process in processes:
            out,err=process.communicate(timeout=15)
            self.assertEqual(0,process.returncode,err);self.assertIn('UNKNOWN_NO_REPLAY',out)
        self.assertEqual(1,self.attempt_count())

    def test_fresh_process_crash_before_start_allows_only_first_real_attempt(self):
        before=self.path.read_bytes();self.child('crash-before-start',75)
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(0,self.attempt_count())
        self.child('dispatch');self.assertEqual(1,self.attempt_count())
        self.child('dispatch');self.assertEqual(1,self.attempt_count())

    def test_fresh_process_crash_after_start_never_dispatches_on_recovery(self):
        self.child('crash-after-start',75);self.assertEqual(0,self.attempt_count())
        self.assertIn('UNKNOWN_NO_REPLAY',self.child('dispatch'));self.assertEqual(0,self.attempt_count())

    def test_fresh_process_lost_effect_ack_and_real_target_cas_never_redispatch(self):
        import json
        self.child('effect-crash',75);self.assertEqual(1,self.attempt_count())
        target=json.loads(self.path.with_suffix('.target.json').read_text())
        self.assertEqual('revision-2',target['revision']);self.assertEqual(self.warrant.operation_hash,target['operation'])
        self.child('dispatch');self.assertEqual(1,self.attempt_count())
        with self.assertRaises(ValueError):self.fx.gov.finish_job(self.fx.p(),self.claim,self.response)
