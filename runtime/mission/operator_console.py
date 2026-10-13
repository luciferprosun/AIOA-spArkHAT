"""Owner-scoped projection and explicit STOP/reconciliation on existing Core.

No provider, listener, signer, store, approval or effect dispatcher. The trusted
host supplies its existing AgentRuntime and Core principal; model dictionaries
cannot become control requests or completion verdicts.
"""
from dataclasses import dataclass
import json
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.mission.agent import CoreAgentBindings
from runtime.mission.governor import _exposure
from runtime.mission.jobs import load_job
from runtime.mission.warrant import require
from runtime.native_console import project_governor

LIMITATIONS = (
    'U08/DEV-E2E01: fresh owned arithmetic or reviewed task-list CLI template; no arbitrary code or dependencies',
    'U09: fresh synthetic local Git only; remote writes disabled',
    'D3/D4/D8 unified installed user workflow NOT_ACCEPTED',
    'Managed browser unavailable; no network or browser fallback',
    'Fixture authority is not production authority',
)

def unavailable_status():
    return {'schema':'aioa.operator-console.v1','status':'UNAVAILABLE',
        'reason':'EXISTING_CORE_AGENT_BINDING_REQUIRED','authority':'NONE',
        'read_only':True,'auto_retry':False,'evidence_level':'NOT_ACCEPTED',
        'limitations':list(LIMITATIONS)}

@dataclass(frozen=True, slots=True, repr=False)
class CoreOperatorConsole:
    binding: CoreAgentBindings

    def __post_init__(self):
        require(type(self.binding) is CoreAgentBindings, 'CONSOLE_CORE_BINDING')

    def read(self, principal):
        b=self.binding;route=b.route
        # Foreign owners receive no metadata, including whether this job exists.
        route.core.require(principal,Capability.READ,scope=route.scope)
        def read(tx):
            context,completion,_,_=route._context(tx,b.warrant)
            _,session,grant=route._session(tx,b.session_id,active=False)
            job=load_job(route.journal.governor,tx,b.claim.task_id)
            require(context['session_id']==b.session_id and completion==b.completion
                and job is not None and job.get('completion_binding')==context['completion'],
                'CONSOLE_CORE_BINDING')
            governor=route.journal.governor._load(tx)
            _,intent=route.journal._load(tx,b.warrant)
            outcome='NOT_STARTED' if intent is None else intent['outcome']['contract_type']
            require(outcome in ('NOT_STARTED','Unknown','Applied','NotApplied'),'CONSOLE_OUTCOME')
            resolution=None if intent is None else intent['resolution']
            active=(not session['revoked'] and grant.issued_at<=route.clock()<grant.expires_at
                and grant.epoch==governor['epoch']
                and session['assignment_revision']==principal.assignment_revision)
            value={'schema':'aioa.operator-console.v1','status':'AVAILABLE','authority':'NONE',
                'read_only':True,'auto_retry':False,
                'task_ref':canonical_sha256((route.scope,b.claim.task_id)),
                'session_ref':canonical_sha256((route.scope,b.session_id)),
                'task_state':job['state'],'session_state':'ACTIVE' if active else 'INACTIVE',
                'pending_grants':[] if active else ['LOCAL_PROJECT_SESSION'],
                'governor':project_governor({**governor,'exposure':_exposure(governor['reservations'])}),
                'outcome':outcome,'receipt_digest':None if resolution is None else resolution['receipt']['digest'],
                'readback_digest':None if resolution is None else resolution['readback']['digest'],
                'completion_verified':job['state']=='DONE' and outcome=='Applied'
                    and job.get('completion_proof') is not None,
                'reconciliation':'READBACK_REQUIRED' if outcome=='Unknown' else 'NO_AUTOMATIC_ACTION',
                'evidence_level':'CORE_VALIDATED_RECEIPT' if outcome=='Applied' else 'UNVERIFIED',
                'browser':'BLOCKED_ENVIRONMENT',
                'provider':{'availability':'NOT_CHECKED_BY_READ','authority':'ADVISORY_ONLY'},
                'snapshot_semantics':'ONE_CORE_READ_TRANSACTION','limitations':list(LIMITATIONS)}
            require(len(canonical_json_bytes(value))<=4096,'CONSOLE_BUDGET')
            return value
        try:return route._run(principal,Capability.READ,read)
        except Exception:
            return {'schema':'aioa.operator-console.v1','status':'UNKNOWN','reason':'CORE_READ_UNAVAILABLE',
                'authority':'NONE','read_only':True,'auto_retry':False,'task_state':'UNKNOWN',
                'outcome':'Unknown','completion_verified':False,'evidence_level':'UNVERIFIED',
                'limitations':list(LIMITATIONS)}

    def stop(self,principal):
        route=self.binding.route
        route.core.require(principal,Capability.MANAGE,scope=route.scope)
        try:route.journal.governor.set_kill(principal,True)
        except Exception:return {'status':'UNKNOWN','reason':'STOP_ACK_UNKNOWN','auto_retry':False}
        return {'status':'STOPPED','auto_retry':False,'scope':'EXISTING_OWNER_CORE'}

    def reconcile(self,principal):
        b=self.binding
        b.route.core.require(principal,Capability.COMMIT,scope=b.route.scope)
        try:
            # Existing route invokes independent verifier only, never dispatcher.
            result=b.route.reconcile(principal,b.warrant,b.claim.governor_epoch)
            return {'status':result['outcome']['contract_type'],'auto_retry':False,'completion_claimed':False}
        except Exception:
            return {'status':'UNKNOWN','reason':'RECONCILIATION_UNAVAILABLE','auto_retry':False,
                    'completion_claimed':False}

def run_console_cli(argv,*,runtime_factory,principals=None):
    """Existing installed CLI, no default principal or automatic owner setup."""
    from runtime.mission.cli import DiagnosticParser
    parser=DiagnosticParser(prog='aioa-sparkhat console')
    parser.add_argument('operation',choices=('status','stop','reconcile'))
    parser.add_argument('--json',action='store_true')
    runtime=None
    try:
        args=parser.parse_args(argv);runtime=runtime_factory()
        purpose={'status':Capability.READ,'stop':Capability.MANAGE,'reconcile':Capability.COMMIT}[args.operation]
        principal=None if principals is None else principals[purpose]
        result=getattr(runtime,'operator_'+args.operation)(principal)
        code=0 if result['status'] in ('AVAILABLE','STOPPED','Applied','NotApplied') else 3
    except Exception:
        result={'schema':'aioa.operator-console.v1','status':'POLICY_BLOCKED',
                'reason':'CONSOLE_REQUEST_DENIED','auto_retry':False};code=4
    finally:
        if runtime is not None:runtime.close()
    # JSON CLI data, never HTML; no task content, private payload or exception echo.
    print(json.dumps(result,sort_keys=True,ensure_ascii=True,allow_nan=False))
    return code
