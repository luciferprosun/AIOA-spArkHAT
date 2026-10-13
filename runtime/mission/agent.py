"""Explicit offline advisory adapter. Existing Core remains the sole state owner."""
from dataclasses import asdict, dataclass, field
import json
from runtime.core_admission import Capability
from runtime.mission.warrant import require
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256


def parse_advisory(value):
    require(type(value) is dict and len(value)<=3, 'INVALID_ADVISORY')
    kind=value.get('type')
    keys={'type','recipe_id','step_id'} if kind=='RunRecipeProposal' else {'type','text'}
    require(kind in ('RunRecipeProposal','FinalText') and set(value)==keys,'ADVISORY_AUTHORITY_DENIED')
    try:private={key:value[key] for key in keys}
    except KeyError:raise ValueError('INVALID_ADVISORY') from None
    require(all(type(item) is str for item in private.values()),'INVALID_ADVISORY')
    require(private['type']==kind,'INVALID_ADVISORY')
    if kind=='RunRecipeProposal':
        require(len(private['recipe_id'])<=128 and len(private['step_id'])<=128,'ADVISORY_LIMIT')
        from lab.archaioa.faults import opaque_id
        opaque_id(private['recipe_id'],'recipe');opaque_id(private['step_id'],'step')
    else:
        require(len(private['text'])<=1024,'INVALID_FINAL_TEXT')
    try:raw=json.dumps(private,ensure_ascii=False,allow_nan=False).encode('utf-8')
    except (ValueError,TypeError,UnicodeError):raise ValueError('INVALID_ADVISORY') from None
    require(len(raw)<=2048 and (kind!='FinalText' or len(private['text'].encode('utf-8'))<=1024),'ADVISORY_LIMIT')
    return json.loads(raw)


@dataclass(frozen=True,slots=True)
class OfflineAdvisorySequence:
    payloads:tuple[bytes,...]
    def __post_init__(self):
        require(type(self.payloads) is tuple and 1<=len(self.payloads)<=2,'ADVISORY_LIMIT')
        for raw in self.payloads:
            require(type(raw) is bytes and len(raw)<=2048,'ADVISORY_LIMIT')
            parse_advisory(json.loads(raw))
    @classmethod
    def from_results(cls,results):
        require(type(results) is tuple,'INVALID_ADVISORY_SEQUENCE')
        require(1<=len(results)<=2,'ADVISORY_LIMIT')
        return cls(tuple(json.dumps(parse_advisory(v),allow_nan=False).encode() for v in results))
    def results(self):return tuple(json.loads(v) for v in self.payloads)


@dataclass(frozen=True,slots=True)
class CoreAgentBindings:
    route:object
    principal:object
    session_id:str
    operation_bytes:bytes
    warrant:object
    reservation:object
    completion:object
    claim:object
    response:object=field(repr=False,compare=False)
    advisory:OfflineAdvisorySequence|None=None
    response_bytes:bytes=field(init=False,repr=False)
    def __post_init__(self):
        from runtime.mission.tools import CoreToolRoute
        from runtime.mission.sandbox_contracts import SANDBOX
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        from runtime.providers.nvidia import ProviderResponse
        from runtime.mission.job_contracts import JobClaim
        require(type(self.route) is CoreToolRoute and self.route.bound_variant is SANDBOX
                and type(self.route.executor) is LinuxSandboxBroker
                and self.route.verifier==self.route.executor.verify,'INVALID_AGENT_BINDINGS')
        require(type(self.operation_bytes) is bytes and len(self.operation_bytes)<=8192
                and type(self.claim) is JobClaim and type(self.response) is ProviderResponse
                and (self.advisory is None or type(self.advisory) is OfflineAdvisorySequence),'INVALID_AGENT_BINDINGS')
        operation=json.loads(self.operation_bytes)
        self.route.sandbox_registry.validate(operation)
        require(canonical_json_bytes(operation)==self.operation_bytes,'INVALID_AGENT_BINDINGS')
        raw=canonical_json_bytes(self.response)
        response=json.loads(raw)
        payload=response['parsed_payload']
        require(response['authority']=='ADVISORY_ONLY' and response['validation_result']=='VALID'
                and response['finish_reason']=='stop' and response['http_status']==200
                and type(response['raw_size']) is int and 0<=response['raw_size']<=16384
                and type(payload) is dict and set(payload)=={'summary','needs_attention'}
                and type(payload['summary']) is str and 1<=len(payload['summary'])<=800
                and type(payload['needs_attention']) is bool,'INVALID_AGENT_RESPONSE')
        require(len(raw)<=32768,'INVALID_AGENT_BINDINGS')
        object.__setattr__(self,'response_bytes',raw)
        self.validate()
    def validate(self):
        from runtime.mission.jobs import load_job
        operation=json.loads(self.operation_bytes)
        def read(tx):
            context,binding,_,_=self.route._context(tx,self.warrant)
            job=load_job(self.route.journal.governor,tx,self.claim.task_id)
            response=json.loads(self.response_bytes)
            require(job is not None and job['claim']==asdict(self.claim)
                    and job['state'] in ('STARTED','UNKNOWN','DONE')
                    and job['envelope']['envelope_digest']==self.claim.envelope_digest
                    and job['envelope']['request_id']==response['request_id']
                    and job['envelope']['model_id']==response['model_id']
                    and job['envelope']['output_schema']=='aioa-readonly-advice-v1'
                    and binding==self.completion
                    and job.get('completion_binding')==context['completion']
                    and context['session_id']==self.session_id
                    and context['reservation']==asdict(self.reservation)
                    and self.claim.task_id==self.warrant.task_id
                    and 'sha256:'+canonical_sha256(operation)==self.warrant.operation_hash,
                    'AGENT_CORE_BINDING_MISMATCH')
        self.route._run(self.principal,Capability.COMMIT,read)
    def step(self,value):
        try:proposal=parse_advisory(value)
        except ValueError as exc:return {'status':'POLICY_BLOCKED','reason':str(exc)}
        if proposal['type']=='FinalText':
            return {'status':'ADVISORY_ONLY','text':proposal['text']}
        operation=json.loads(self.operation_bytes)
        if (proposal['recipe_id'],proposal['step_id'])!=(operation['payload']['recipe_id'],operation['payload']['step_id']):
            return {'status':'POLICY_BLOCKED','reason':'AGENT_SCOPE_DENIED'}
        try:
            self.validate()
            result=self.route.dispatch(self.principal,session_id=self.session_id,warrant=self.warrant,
                operation=operation,reservation=self.reservation,completion=self.completion)
            if result['outcome']['contract_type']=='Unknown':
                result=self.route.reconcile(self.principal,self.warrant,self.claim.governor_epoch)
        except Exception as exc:
            # Read retained Core truth only. ACK loss never grants another effect
            # or hides a committed readback behind a clean policy denial.
            try:
                retained=self.route._run(self.principal,Capability.COMMIT,
                    lambda tx:self.route._retained(tx,self.session_id,self.warrant,
                        operation,self.reservation,self.completion))
            except Exception:
                return {'status':'UNKNOWN','reason':type(exc).__name__}
            if retained is None:
                return {'status':'POLICY_BLOCKED','reason':type(exc).__name__}
            kind=retained['outcome']['contract_type']
            status='BLOCKED_COMPLETION' if kind=='Applied' else 'FAIL' if kind=='NotApplied' else 'UNKNOWN'
            return {'status':status,'effect':retained,'reason':type(exc).__name__}
        if result['outcome']['contract_type']!='Applied':
            return {'status':'FAIL' if result['outcome']['contract_type']=='NotApplied' else 'UNKNOWN',
                    'effect':result}
        from runtime.providers.nvidia import ProviderResponse
        try:
            done=self.route.journal.governor.finish_job(self.principal,self.claim,
                ProviderResponse(**json.loads(self.response_bytes)))
        except Exception as exc:
            return {'status':'BLOCKED_COMPLETION','effect':result,'reason':str(exc)}
        return {'status':'COMPLETED','effect':result,'job':done}
    def run(self):
        if self.advisory is None:return {'status':'PROVIDER_UNAVAILABLE'}
        results=[]
        for value in self.advisory.results():
            result=self.step(value);results.append(result)
            if result['status']!='ADVISORY_ONLY':return {**result,'turns':len(results)}
        return {'status':'ADVISORY_ONLY','results':results,'turns':len(results)}
