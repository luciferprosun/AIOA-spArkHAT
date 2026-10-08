"""Opt-in native component READ projection; no new policy or execution path."""
from dataclasses import dataclass
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256
from runtime.mission.governor import CoreDualGovernor
from runtime.mission.verification import CoreCommitSelectReveal
from runtime.mission.contracts import logical_id
from runtime.service_guard.service import CoreServiceGuard

STATES=('RESERVED','DISPATCHED','UNKNOWN','COMMITTED','RELEASED')
MODEL='nvidia/Nemotron-3_5-Lightning'

def integer(value):
    if type(value) is not int or not 0<=value<=2**63-1:raise ValueError('CONSOLE_INTEGER')
    return str(value)

def project_governor(state):
    exposure=state['exposure']['global'];counts={name:0 for name in STATES}
    for row in state['reservations'].values():counts[row['state']]+=1
    if type(state['kill']) is not bool:raise ValueError('CONSOLE_KILL')
    return {'status':'AVAILABLE','epoch':integer(state['epoch']),'kill':state['kill'],
        'last_mutation_time':integer(state['last_now']),'money_nano':integer(exposure['money_nano']),
        'risk_units':integer(exposure['risk_units']),'reservation_counts':counts,
        'open_liabilities':counts['UNKNOWN']+counts['DISPATCHED'],
        'amount_semantics':'CONSERVATIVE_BOUND_NOT_MEASURED_SPEND','global_scope':'SINGLE_OWNER_CORE_NAMESPACE',
        'fence_scope':'LOCAL_ONLY_NOT_TARGET_DISTRIBUTED'}

def unknown_governor():
    return {'status':'UNKNOWN','epoch':None,'kill':None,'last_mutation_time':None,'money_nano':None,
        'risk_units':None,'reservation_counts':None,'open_liabilities':None}

@dataclass(frozen=True,slots=True,repr=False)
class NativeConsoleBinding:
    governor:CoreDualGovernor
    model_id:str=MODEL
    guard:CoreServiceGuard|None=None
    operation_id:str='unbound'
    verification:CoreCommitSelectReveal|None=None
    def __post_init__(self):
        if type(self.governor) is not CoreDualGovernor or self.model_id!=MODEL:raise ValueError('CONSOLE_BINDING')
        logical_id(self.operation_id)
        for service,kind in ((self.guard,CoreServiceGuard),(self.verification,CoreCommitSelectReveal)):
            if service is not None and (type(service) is not kind or service.core is not self.governor.core
                or service.runner is not self.governor.runner or service.policy.scope!=self.governor.policy.scope):
                raise ValueError('CONSOLE_CORE_BINDING')
    def read(self,principal):
        self.governor.core.require(principal,Capability.READ,scope=self.governor.policy.scope)
        if self.model_id not in principal.model_binding_ids:raise ValueError('CONSOLE_MODEL_BINDING')
        try:gov=project_governor(self.governor.inspect(principal))
        except Exception:gov=unknown_governor()
        result={'schema':'aioa.native-console.v1','authority':'NONE','execution_authority':False,'auto_retry':False,
            'read_only':True,'mode':'LOCAL_INSPECTION','provider':{'id':'nebius','model':MODEL,
                'availability':'NOT_CHECKED_BY_READ','authority':'ADVISORY_ONLY'},
            'owner_mode':'CORE_OWNER_SCOPED','task_ref':canonical_sha256((self.governor.policy.scope,self.operation_id)),
            'governor':gov,'warrant_status':'UNBOUND','receipt_chain':{'status':'UNBOUND'},
            'readback':{'status':'UNBOUND'},'replay':'READ_ONLY_NO_DISPATCH',
            'verification':{'status':'UNBOUND'},'context':{'status':'UNBOUND'},
            'snapshot_semantics':'COMPONENT_READS_NOT_ONE_ATOMIC_GLOBAL_SNAPSHOT'}
        if self.guard is not None:
            try:
                graph=self.guard.receipt_graph(principal,self.operation_id)
                result['receipt_chain']={key:graph[key] for key in ('projection_status','outcome_status','graph_digest')}
                phases={n['id'] for n in graph['nodes']}
                result['warrant_status']='REVOKED_RECORD' if 'revocation' in phases else 'HISTORICAL_APPROVAL_RECORD' if 'approval' in phases else 'NO_RECORD'
                if self.guard._decision_context_reader is not None:
                    context=self.guard._decision_context_reader.current(principal)
                    result['context']={'status':'CURRENT_READ','capsule_digest':context.capsule_ref,
                        'dependency_digest':context.dependency_digest,'selected_count':len(context.selected),
                        'budget_bytes':self.guard._decision_context_reader.request.context_budget_bytes,'authority':'NONE'}
                    certificate=self.guard.shadow_delta(principal,self.operation_id).as_dict()
                    result['readback']={k:certificate[k] for k in ('status','mode','dependent_completion_blocked','certificate_digest','next_action')}
                else:result['readback']={'status':'UNBOUND','dependent_completion_blocked':True}
            except Exception:
                result['receipt_chain']={'status':'UNKNOWN'};result['readback']={'status':'UNKNOWN','dependent_completion_blocked':True}
                result['context']={'status':'UNKNOWN'};result['warrant_status']='UNKNOWN'
        if self.verification is not None:
            try:
                status=self.verification.inspect(principal,self.operation_id)
                result['verification']={k:status[k] for k in ('status','commit_digest','selection_present','receipt_present') if k in status}
                result['verification']['semantics']='ARTIFACT_COMMIT_AND_PRESENCE_NOT_EFFECT_VERDICT'
            except Exception:result['verification']={'status':'UNKNOWN'}
        if len(canonical_json_bytes(result))>8192:raise ValueError('CONSOLE_BUDGET')
        return result
