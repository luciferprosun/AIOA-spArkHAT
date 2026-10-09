"""Explicit same-Core offline reviewer fixture over existing native services.

No LIVE transport/keys, alternate provider manager, authority or memory system.
Canonical source publication is synthetic; durable native JSON port is a fixture.
"""
from dataclasses import dataclass,replace
from datetime import datetime,timezone
import json
from pathlib import Path
from nv09_support import GuardFixture,LocalTarget,proposal
import test_memory_patch_retrieval as retrieval_fixtures
from nv03_support import DurableFactory
from runtime.core_admission import Capability
from runtime.memory_patch.retrieval.dependencies import CoreSelectedContextReader
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256
from runtime.memory_patch.learning.contracts import CoreVerifierBinding,EvidenceLiteralVerifier,VerificationInput,VerificationVerdict
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.governor import CoreDualGovernor,GovernorPolicy,GovernorBinding,Limits
from runtime.mission.verification import CoreCommitSelectReveal,VerificationPolicy
from runtime.providers.nebius_routing import NebiusProviderPort,ModelRoute,ModelRole,RouteBudget
from runtime.providers.exact import ProviderResult
from runtime.providers.nvidia import ProviderError
from runtime.service_guard.service import CoreServiceGuard,GuardLoopBinding
from runtime.service_guard.contracts import OUTPUT_SCHEMA
from runtime.native_console import NativeConsoleBinding,MODEL

@dataclass(frozen=True)
class LiteralAdvisoryRule:
    expected:str
    def verify(self,request):return VerificationVerdict(request.digest,request.claim==self.expected)

class ReviewedNativePort:
    """Host-only fixture composition. Original response committed before selection.

    It returns no approval and never touches the target. A review gap is a blocked
    advisory, not permission to re-run an uncertain native provider operation.
    """
    def __init__(self,owner,port):
        self.owner,self.port,self.budget=owner,port,port.budget
        self.provider_id,self.model_id=port.provider_id,port.model_id
    def bounded(self,request):
        data=json.loads(request.input_text);data['context_capsule']=self.owner.capsule.as_dict()
        text=json.dumps(data,sort_keys=True,separators=(',',':'))
        if len(text.encode())>4096:raise ProviderError('FIXTURE_CONTEXT_BUDGET',outcome_unknown=False)
        return replace(request,input_text=text)
    def estimated_units(self,request):return self.port.estimated_units(self.bounded(request))
    def request(self,request):
        bound=self.bounded(request);response=self.port.request(bound)
        self.owner.protocol.commit(self.owner.core.local_operator(Capability.COMMIT),self.owner.operation_id,
            canonical_sha256((self.owner.memory.request.request_hash,self.owner.capsule.capsule_hash,bound)),response)
        self.owner.protocol.select(self.owner.core.local_operator(Capability.MANAGE),self.owner.operation_id)
        self.owner.verdict=self.owner.protocol.reveal(self.owner.core.local_operator(Capability.COMMIT),self.owner.operation_id,response)
        self.owner.original_response=response
        if self.owner.verdict['status']!='SUPPORTED':raise ProviderError('FIXTURE_ADVISORY_REVIEW_REQUIRED',outcome_unknown=True)
        return response

class UnifiedFixture:
    def __init__(self,root,*,drop_ack=False):
        self.root=Path(root);self.closed=False;self.provider_calls=[];self.operation_id='unified-advisory-effect'
        self.claim='The reviewed policy permits requesting human review of maintenance.';self.fixture_claim=self.claim
        self.target=LocalTarget(self.root/'target',drop_ack=drop_ack)
        self.fx=GuardFixture(self.root/'runtime',self.target.client,operation_id=self.operation_id,
            extra_hat_ids=('test-hat',),model_id=MODEL)
        self.core,self.runner=self.fx.core,self.fx.runner;self.path=self.fx.root/'native-fixture.json'
        self.memory=retrieval_fixtures.RetrievalFixture(core=self.core)
        self.source=self.memory.candidate(source_id='unified-source',content=self.claim)
        self.memory.sources.values=(self.memory.ranked_input(self.source),)
        self.reader=self.core.local_operator(Capability.READ)
        self.context=CoreSelectedContextReader(self.memory.service,self.memory.request,(('unified-source','chunk-one'),))
        lanes=self.memory.service.retrieve(self.reader,self.memory.request,include_personal=False)
        self.capsule=self.memory.service.context_capsule(self.reader,self.memory.request,lanes)
        self.compose(start=True)
    def current(self,principal,response):
        self.core.require(principal,Capability.READ,scope=self.fx.scope)
        snapshot=self.context.current(principal)
        lanes=self.memory.service.retrieve(principal,self.memory.request,include_personal=False)
        items=[item for item in lanes.temporal.applicable_items
            if (item.identity.source_id,item.identity.chunk_id)==self.context.selected_slots[0]]
        if len(items)!=1:raise ValueError('FIXTURE_SELECTED_EVIDENCE_GAP')
        item=items[0]
        from runtime.memory_patch.retrieval.dependencies import selected_canonical_snapshot
        admitted=selected_canonical_snapshot(self.memory.service,principal,self.memory.request,lanes,
            selected_refs=(('CANONICAL_EVIDENCE',item.item_hash),))
        if admitted.dependency_digest!=snapshot.dependency_digest:raise ValueError('FIXTURE_CHANGED_SELECTION')
        return VerificationInput(self.fx.scope,'test-hat',self.operation_id,response.parsed_payload['reason_summary'],
            ((item.identity.source_id,item.identity.knowledge_version_id,item.artifact_digest,item.excerpt.text),),
            datetime.fromtimestamp(self.fx.clock(),timezone.utc))
    def compose(self,*,start):
        policy=GovernorPolicy(self.fx.scope,'unified-native-core',Limits(1000000,10),Limits(1000000,15),Limits(1000000,20))
        self.gov=CoreDualGovernor(self.core,self.runner,policy,clock=self.fx.clock)
        self.epoch=self.gov.start_epoch(self.core.local_operator(Capability.MANAGE)) if start else self.gov.inspect(self.reader)['epoch']
        self.guard=CoreServiceGuard(self.core,self.runner,self.fx.policy,self.target.client,clock=self.fx.clock,
            governor_binding=GovernorBinding(self.gov,self.core.local_operator(Capability.COMMIT),self.epoch,self.operation_id,3),
            decision_context_reader=self.context)
        mechanical=CoreVerifierBinding('literal','literal','admitted-source',EvidenceLiteralVerifier())
        advisory=CoreVerifierBinding('fixture-rule','literal-rule','same-synthetic-family',LiteralAdvisoryRule(self.claim))
        self.protocol=CoreCommitSelectReveal(self.core,self.runner,VerificationPolicy(self.fx.scope,'test-hat',OUTPUT_SCHEMA,('fixture-rule',)),
            mechanical,(advisory,),current_input=self.current,picker=lambda pool,count:pool[:count],
            clock=lambda:datetime.fromtimestamp(self.fx.clock(),timezone.utc))
        owner=self
        class ExactFixture:
            def __init__(self,**kwargs):pass
            def generate_exact(self,request,*args):
                owner.provider_calls.append(request)
                data=json.loads(request.messages[-1].content);value=proposal(data['observation'],reason_summary=owner.fixture_claim)
                return ProviderResult(content=json.dumps(value),provider_connection_id='nebius',requested_model=MODEL,
                    reported_model=MODEL,identity_status='EXACT_MATCH',request_id='unified-fixture-receipt',
                    usage={'prompt_tokens':20,'completion_tokens':40,'total_tokens':60},finish_reason='stop',transport_scope='TEST',latency_ms=1)
        now=datetime.now(timezone.utc).isoformat()
        route=ModelRoute(ModelRole.FAST,'nebius',MODEL,RouteBudget(8192,256,30,'0.001'),now)
        quote={'model_id':MODEL,'currency':'USD','input_usd_per_million':'0.06','output_usd_per_million':'0.24',
            'quoted_utc':now,'input_bound_policy':'utf8-bytes-plus-framing-v1'}
        native=NebiusProviderPort(route,self.fx.budget,quote,secret_supplier=lambda:'explicit-fixture-handle',provider_factory=ExactFixture,
            clock=self.fx.clock,transport_scope='TEST',governor_binding=GovernorBinding(self.gov,self.core.local_operator(Capability.COMMIT),self.epoch,self.operation_id,1))
        self.provider=ReviewedNativePort(self,native)
        self.fx.guard=self.guard
        from main import create_runtime
        self.fx.runtime.close()
        self.fx.profile=replace(self.fx.profile,provider_id='nebius',model_id=MODEL,route_role='FAST')
        self.fx.bindings=replace(self.fx.bindings,state_root=self.fx.root/'nebius-journal',provider=self.provider,
            service_guard=GuardLoopBinding(self.guard,self.operation_id))
        self.fx.runtime=create_runtime(lite_profile=self.fx.profile,mission_context=self.fx.context,lite_bindings=self.fx.bindings)
        self.console=NativeConsoleBinding(self.gov,guard=self.guard,operation_id=self.operation_id,verification=self.protocol)
    def prepare(self):return self.execute()
    def approve(self):return self.fx.approve()
    def execute(self):
        self.fx.clock_value+=1
        return self.guard.cycle(self.fx.runtime._lite_scheduler,self.operation_id)
    def change_source(self):
        self.source=self.memory.candidate(source_id='unified-source',version='new-revision',content='Changed reviewed rule')
        self.memory.sources.values=(self.memory.ranked_input(self.source),)
    def reopen(self):
        self.runner.close();self.runner=TransactionRunner(self.core,DurableFactory(self.path));self.fx.runner=self.runner
        self.compose(start=False)
    def close(self):
        if not self.closed:
            self.closed=True;self.fx.close();self.target.close()

def run_unified(root):
    fx=UnifiedFixture(root)
    try:
        before=fx.prepare();no_authority_count=fx.target.client.read()['effect_count']
        try:csr_before=fx.protocol.inspect(fx.reader,fx.operation_id)
        except Exception:csr_before={'status':'UNKNOWN'}
        fx.approve();result=fx.execute()
        shadow=fx.guard.shadow_delta(fx.reader,fx.operation_id).as_dict();digest=shadow['certificate_digest']
        fx.reopen();replay=fx.execute();after=fx.target.client.read()
        replay_shadow=fx.guard.shadow_delta(fx.reader,fx.operation_id).as_dict()
        from webapp import WebRuntimeService
        ui=WebRuntimeService(runtime=fx.fx.runtime,native_console=fx.console).authority_payload()
        console=ui['native_console'];scheduler=fx.fx.runtime._lite_scheduler
        csr_after=console['verification']
        csr_fields=('status','commit_digest','selection_present','receipt_present')
        checks={'no_effect_without_human':not before['dispatch_attempted'] and no_authority_count==0,
            'native_effect_verified':result['status']=='VERIFIED' and result['verified_effect'] is True,
            'replay_one_effect':replay['status']=='REPLAY' and after['effect_count']==1,
            'shadow_verified':shadow['status']=='VERIFIED_FIXTURE_DELTA' and not shadow['dependent_completion_blocked'],
            'reopened_shadow_verified':replay_shadow['status']=='VERIFIED_FIXTURE_DELTA' and not replay_shadow['dependent_completion_blocked'],
            'shadow_replay_exact':replay_shadow['certificate_digest']==digest,
            'one_offline_call':len(fx.provider_calls)==1,
            'native_profile_bound':scheduler.profile==scheduler.journal.profile and scheduler.profile.digest==scheduler.journal.state['manifest_digest'],
            'journal_model_bound':all(r['provider_id']=='nebius' and r['model_id']==MODEL for r in scheduler.journal.reservations()),
            'advisory_supported_not_authority':fx.verdict['status']=='SUPPORTED' and fx.verdict['authority']=='NONE' and not fx.verdict['execution_authority'],
            'csr_metadata_complete':csr_before.get('authority')=='NONE' and all(
                row.get('status')=='COMMITTED' and row.get('selection_present') is True
                and row.get('receipt_present') is True and row.get('commit_digest')==fx.verdict['commit_digest']
                for row in (csr_before,csr_after)),
            'csr_metadata_replay_stable':all(csr_before.get(k)==csr_after.get(k) for k in csr_fields),
            'console_governor_available':console['governor']['status']=='AVAILABLE' and console['governor']['open_liabilities']==0,
            'console_context_current':console['context']['status']=='CURRENT_READ',
            'console_receipt_complete':console['receipt_chain'].get('projection_status')=='COMPLETE',
            'console_readback_verified':console['readback']['status']=='VERIFIED_FIXTURE_DELTA',
            'console_no_authority':console['authority']=='NONE' and not console['execution_authority']}
        return {'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'mode':'FIXTURE','provider':'nebius','model':MODEL,
            'authority':'NONE','same_core':True,'advisory_only':True,'no_approval_effect_count':no_authority_count,
            'effect_count':after['effect_count'],'duplicate_effects':max(0,after['effect_count']-1),
            'live_provider_calls':0,'offline_provider_calls':len(fx.provider_calls),'native_port':'NebiusProviderPort',
            'capsule_digest':fx.capsule.capsule_hash,'verifier_status':fx.verdict['status'],
            'verification_metadata':csr_after,
            'shadow_delta_digest':digest,'replay_status':replay['status'],'console':console,'ui_path':'EXISTING_AUTHORITY_TIMELINE',
            'backend':'EXPLICIT_NATIVE_JSON_TEST_PORT','source_admission':'SYNTHETIC_NATIVE_CATALOG',
            'restart_scope':'NATIVE_PORT_REOPEN_SAME_OWNER_CORE','cpl_nonzero':'EXISTING_MODULE_COMPATIBILITY_GATES_SEPARATE; NOT NEW EFFECT EXECUTOR'}
    finally:fx.close()
