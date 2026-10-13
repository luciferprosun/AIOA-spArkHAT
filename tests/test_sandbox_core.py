"""Sandbox effects use the original real Core ledgers and live START ACK."""
from dataclasses import replace
import concurrent.futures
import unittest
from unittest.mock import patch
import test_core_tool_composition as core_fixtures
from test_dual_governor import MODEL
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256, canonical_json_bytes
from runtime.memory_patch.persistence.ports import TransactionContext, RecordKind, StoredRecord
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.providers.nvidia import ProviderRequest


class SandboxCoreTests(unittest.TestCase):
    def setUp(self):
        from runtime.mission.tools import CoreToolRoute
        import inspect
        self.assertIn('variant',inspect.signature(CoreToolRoute).parameters, 'Missing common Core sandbox variant')
        from runtime.mission.sandbox_contracts import SandboxRecipe, SandboxRegistry, SandboxDispatchRequest
        self.base=core_fixtures.CoreToolCompositionTests('test_real_synthetic_attempt_opens_required_g2_and_holds_exposure')
        self.addCleanup(self.base.doCleanups);self.base.setUp()
        self.fx=self.base.fx;self.requests=[];self.Request=SandboxDispatchRequest
        self.registry=SandboxRegistry('workspace-1',(SandboxRecipe('tiny-python-v1','root-1','a'*64,'b'*64,'c'*64),))
        self.route=CoreToolRoute(self.fx.journal,self.base.liability,workspace='workspace-1',policy_revision=2,
            variant='sandbox',sandbox_registry=self.registry,probe=lambda:self.base.current,
            executor=self.execute,target_guard=lambda:self.base.lifecycle,verifier=self.base.verify,
            clock=lambda:self.base.now)
        self.operation=self.route.operation({'action':'run_recipe','recipe_id':'tiny-python-v1',
            'task_id':'sandbox-task','step_id':'effect'},self.base.current)
        self.trace=FaultTrace(FaultKind.LOST_ACK,'sandbox-task','sandbox-request','sha256:'+canonical_sha256(self.operation))
        self.graph=DependencyGraph('sandbox-task',(
            DependencyNode('effect',NodeKind.OPERATION,liability_ids=(classify_fault(self.trace).liability_id,)),
            DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect',))))
        self.binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,self.graph,'completion')
        self.base.liability.initialize(self.fx.p(),self.graph)
        self.advisory_request,self.claim=self.start_job(self.graph,self.binding,'sandbox-advisory')
        self.grant=replace(self.base.grant,session_id='sandbox-session',policy_revision=2,
            capabilities=('PROJECT_WRITE','SANDBOX_EXEC'),completion_digest=self.binding.digest)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),self.grant)
        self.warrant=self.authorize()
        self.reservation=ReservationRequest(self.warrant.money_reservation_id,'sandbox-task','sandbox-exec',MODEL,
            canonical_sha256(self.operation),50,5)

    def start_job(self,graph,binding,request_id):
        request=ProviderRequest(request_id,'sandbox-trace','nebius',MODEL,'offline fixture','budget',128,20)
        envelope=JobEnvelope.from_request(self.fx.ledger.scope,graph.task_id,request,deadline_at=160,money_nano=1,risk_units=0)
        self.fx.gov.submit_job(self.fx.p(Capability.MANAGE),envelope,completion=binding)
        claim=self.fx.gov.claim_job(self.fx.p(),graph.task_id,'fixture-worker',1,lease_seconds=30)
        self.fx.gov.begin_job(self.fx.p(),claim)
        return request,claim

    def execute(self,request):
        self.assertIs(type(request),self.Request);self.requests.append(request)
        self.base.effects[request.operation_digest]='verified sandbox fixture'

    def authorize(self,operation=None,trace=None,nonce='sandbox-nonce'):
        return self.route.authorize(self.fx.p(),self.grant.session_id,operation or self.operation,
            self.binding,self.graph,trace or self.trace,nonce=nonce,model_id=MODEL,money_nano=50,risk_units=5)

    def dispatch(self):
        return self.route.dispatch(self.fx.p(),session_id=self.grant.session_id,warrant=self.warrant,
            operation=self.operation,reservation=self.reservation,completion=self.binding)

    def test_live_ack_builds_exact_stored_request_and_keeps_unknown_until_readback(self):
        result=self.dispatch()
        self.assertEqual('SANDBOX',result['mode']);self.assertEqual('Unknown',result['outcome']['contract_type'])
        self.assertEqual(1,len(self.requests));r=self.requests[0]
        def stored(tx):
            context=self.route._context(tx,self.warrant)[0]
            intent=self.fx.journal._load(tx,self.warrant)[1]
            return context,intent,tx.get(RecordKind.OUTBOX,self.fx.journal._key(self.warrant))
        context,intent,outbox=self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ),Capability.READ),stored)
        self.assertEqual(canonical_json_bytes(intent['operation']),r.operation_bytes)
        self.assertEqual(context['session_id'],r.session_id)
        self.assertEqual('sandbox-task',r.task_id);self.assertEqual('effect',r.step_id)
        self.assertEqual(intent['epoch'],r.policy_epoch)
        self.assertEqual('HELD',outbox.payload['state'])
        self.assertEqual('UNKNOWN',self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations'][self.reservation.request_id]['state'])
        self.assertEqual('OPEN',self.base.liability.inspect(self.fx.p(Capability.READ),'sandbox-task')[0].status.value)
        self.assertEqual(self.warrant.operation_hash,r.operation_digest)
        self.assertEqual(self.grant.digest,r.session_grant_digest)
        self.assertEqual(self.warrant.digest(),r.warrant_digest)
        self.assertEqual(self.warrant.decision_dependency_root.root_digest,r.ddr_digest)
        self.assertEqual(canonical_sha256(self.reservation),r.reservation_digest)
        self.assertEqual(self.binding.digest,r.completion_digest)
        self.assertEqual(self.warrant.nonce,r.idempotency_key)
        self.assertEqual('Applied',self.route.reconcile(self.fx.p(),self.warrant,1)['outcome']['contract_type'])

    def test_retained_unknown_or_applied_never_rebuilds_or_executes(self):
        from runtime.mission.tools import CoreToolRoute
        with patch.object(self.route,'_sandbox_request',wraps=self.route._sandbox_request) as builder:
            self.dispatch();self.dispatch()
            self.route.reconcile(self.fx.p(),self.warrant,1)
            self.assertEqual(1,builder.call_count)
        fresh=CoreToolRoute(self.fx.journal,self.base.liability,workspace='workspace-1',policy_revision=1,
            probe=lambda:self.fail('retained must not probe'),executor=lambda *a:self.fail('retained must not execute'),
            target_guard=lambda:self.base.lifecycle,verifier=self.base.verify,clock=lambda:self.base.now)
        self.assertEqual('SANDBOX',fresh.dispatch(self.fx.p(),session_id=self.grant.session_id,
            warrant=self.warrant,operation=self.operation,reservation=self.reservation,completion=self.binding)['mode'])
        self.assertEqual(1,len(self.requests))

    def test_wrong_task_denies_before_start(self):
        operation={**self.operation,'payload':{**self.operation['payload'],'task_id':'other-task'}}
        trace=replace(self.trace,operation_digest='sha256:'+canonical_sha256(operation))
        with self.assertRaisesRegex(ValueError,'SANDBOX_TASK_BINDING'):
            self.authorize(operation,trace,'wrong-task')
        self.assertEqual([],self.requests)

    def test_optional_step_cannot_borrow_required_liability(self):
        operation=self.route.operation({'action':'run_recipe','recipe_id':'tiny-python-v1',
            'task_id':'optional-task','step_id':'optional'},self.base.current)
        trace=FaultTrace(FaultKind.LOST_ACK,'optional-task','optional-request','sha256:'+canonical_sha256(operation))
        identity=classify_fault(trace).liability_id
        graph=DependencyGraph('optional-task',(
            DependencyNode('required',NodeKind.OPERATION,liability_ids=(identity,)),
            DependencyNode('optional',NodeKind.OPERATION,liability_ids=(identity,)),
            DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('required',))))
        binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,graph,'completion')
        self.base.liability.initialize(self.fx.p(),graph);self.start_job(graph,binding,'optional-advisory')
        grant=replace(self.grant,session_id='optional-session',completion_digest=binding.digest)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),grant)
        with self.assertRaisesRegex(ValueError,'SANDBOX_STEP_BINDING'):
            self.route.authorize(self.fx.p(),grant.session_id,operation,binding,graph,trace,
                nonce='optional-nonce',model_id=MODEL,money_nano=50,risk_units=5)
        self.assertEqual([],self.requests)

    def test_missing_capability_denies_without_state_change(self):
        self.grant=replace(self.grant,session_id='write-only-session',capabilities=('PROJECT_WRITE',))
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),self.grant)
        before=self.base.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'SESSION_SCOPE_DENIED'):self.authorize(nonce='no-sandbox-cap')
        self.assertEqual(before,self.base.path.read_bytes());self.assertEqual([],self.requests)

    def test_lost_start_ack_does_not_reconstruct_permission(self):
        from q09_support import DurableTransaction
        original=DurableTransaction.commit;calls=[]
        def commit(tx):
            changed=tx.snapshot!=tx.factory.state
            original(tx)
            if changed and not calls:
                calls.append(1)
                from runtime.memory_patch.errors import CommitOutcomeUnknown
                raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction,'commit',commit):
            from runtime.memory_patch.errors import CommitOutcomeUnknown
            with self.assertRaises(CommitOutcomeUnknown):self.dispatch()
        self.assertEqual([],self.requests)
        self.assertEqual('Unknown',self.dispatch()['outcome']['contract_type'])
        self.assertEqual([],self.requests)

    def test_concurrent_same_intent_has_one_attempt(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(lambda _:self.dispatch(),range(2)))
        self.assertEqual(1,len(self.requests))
        self.assertTrue(all(r['outcome']['contract_type']=='Unknown' for r in outcomes))

    def response(self):
        from runtime.providers.nvidia import ProviderResponse
        return ProviderResponse(self.advisory_request.request_id,'sandbox-final',MODEL,101,'stop',100,
            {'summary':'Model claims DONE','needs_attention':False},
            {'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})

    def test_model_done_claim_cannot_close_unknown_required_sandbox(self):
        self.dispatch()
        with self.assertRaises(ValueError):self.fx.gov.finish_job(self.fx.p(),self.claim,self.response())
        self.assertEqual('STARTED',self.fx.gov.inspect_job(self.fx.p(Capability.READ),'sandbox-task')['state'])
        self.route.reconcile(self.fx.p(),self.warrant,1)
        result=self.fx.gov.finish_job(self.fx.p(),self.claim,self.response())
        self.assertEqual('DONE',result['state']);self.assertEqual('COMPLETED',result['task_completion'])
        self.assertEqual('NONE',result['authority']);self.assertEqual('UNVERIFIED',result['verification'])

    def test_not_applied_required_sandbox_cannot_become_done(self):
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import NotApplied
        from runtime.mission.liability import Reconciliation
        self.dispatch()
        self.route.verifier=lambda op,w:Reconciliation(w.operation_hash,
            NotApplied((EvidenceRef('absent','no-effect-certificate','sha256:'+'a'*64,'v1'),)),
            EvidenceRef('absent','no-effect-certificate','sha256:'+'a'*64,'v1'),
            EvidenceRef('absent-readback','independent-readback','sha256:'+'c'*64,'v1'))
        self.assertEqual('NotApplied',self.route.reconcile(self.fx.p(),self.warrant,1)['outcome']['contract_type'])
        with self.assertRaises(ValueError):self.fx.gov.finish_job(self.fx.p(),self.claim,self.response())

    def mixed(self, sandbox_first, second_money=40, second_risk=5):
        from runtime.mission.tools import CoreToolRoute
        synthetic=CoreToolRoute(self.fx.journal,self.base.liability,workspace='workspace-1',policy_revision=2,
            probe=lambda:self.base.current,executor=self.base.execute,target_guard=lambda:self.base.lifecycle,
            verifier=self.base.verify,clock=lambda:self.base.now)
        routes=[self.route,synthetic] if sandbox_first else [synthetic,self.route]
        operations=[]
        for i,route in enumerate(routes):
            proposal=({'action':'run_recipe','recipe_id':'tiny-python-v1','task_id':'mixed-task','step_id':f'effect-{i}'}
                if route is self.route else {'action':'write_file','path':'src/main.py','content':'print(2)\n'})
            operations.append(route.operation(proposal,self.base.current))
        traces=[FaultTrace(FaultKind.LOST_ACK,'mixed-task',f'mixed-request-{i}','sha256:'+canonical_sha256(op))
            for i,op in enumerate(operations)]
        graph=DependencyGraph('mixed-task',tuple(DependencyNode(f'effect-{i}',NodeKind.OPERATION,
            liability_ids=(classify_fault(trace).liability_id,)) for i,trace in enumerate(traces))+
            (DependencyNode('completion',NodeKind.COMPLETION_CANDIDATE,('effect-0','effect-1')),))
        binding=TaskCompletionBinding.for_graph(self.fx.ledger.scope,graph,'completion')
        self.base.liability.initialize(self.fx.p(),graph);self.start_job(graph,binding,'mixed-advisory')
        grant=replace(self.grant,session_id='mixed-session',completion_digest=binding.digest)
        self.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),grant)
        args=[]
        for i,(route,op,trace,money,risk) in enumerate(zip(routes,operations,traces,(50,second_money),(5,second_risk))):
            warrant=route.authorize(self.fx.p(),grant.session_id,op,binding,graph,trace,
                nonce=f'mixed-nonce-{i}',model_id=MODEL,money_nano=money,risk_units=risk)
            provider='sandbox-exec' if route is self.route else 'synthetic'
            args.append({'session_id':grant.session_id,'warrant':warrant,'operation':op,'completion':binding,
                'reservation':ReservationRequest(warrant.money_reservation_id,'mixed-task',provider,MODEL,
                    canonical_sha256(op),money,risk)})
        return routes,args

    def check_mixed_budget(self,sandbox_first,second_money,second_risk):
        routes,args=self.mixed(sandbox_first,second_money,second_risk)
        routes[0].dispatch(self.fx.p(),**args[0]);routes[0].reconcile(self.fx.p(),args[0]['warrant'],1)
        attempts=len(self.requests)+len(self.base.calls)
        with self.assertRaisesRegex(ValueError,'SESSION_BUDGET_EXCEEDED'):routes[1].dispatch(self.fx.p(),**args[1])
        self.assertEqual(attempts,len(self.requests)+len(self.base.calls))

    def test_synthetic_settlement_counts_against_sandbox_money(self):self.check_mixed_budget(False,60,5)
    def test_sandbox_settlement_counts_against_synthetic_money(self):self.check_mixed_budget(True,60,5)
    def test_synthetic_settlement_counts_against_sandbox_risk(self):self.check_mixed_budget(False,40,6)
    def test_sandbox_settlement_counts_against_synthetic_risk(self):self.check_mixed_budget(True,40,6)

    def check_hidden_context(self,sandbox_first):
        routes,args=self.mixed(sandbox_first)
        routes[0].dispatch(self.fx.p(),**args[0]);routes[0].reconcile(self.fx.p(),args[0]['warrant'],1)
        def hide(tx):
            row=tx.get(RecordKind.OPERATION,routes[0]._context_key(args[0]['warrant']))
            tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                {**row.payload,'schema':'renamed-context'}),expected_revision=row.revision)
        self.fx.runner.run(TransactionContext(self.fx.p(),Capability.COMMIT),hide)
        with self.assertRaisesRegex(ValueError,'TOOL_CONTEXT_REQUIRED'):routes[1].dispatch(self.fx.p(),**args[1])
    def test_hidden_synthetic_context_cannot_evade_sandbox_accounting(self):self.check_hidden_context(False)
    def test_hidden_sandbox_context_cannot_evade_synthetic_accounting(self):self.check_hidden_context(True)

if __name__=='__main__':unittest.main()
