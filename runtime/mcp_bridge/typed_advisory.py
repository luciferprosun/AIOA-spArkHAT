"""Opt-in, offline READ/result binding on the existing Core admission boundary.

No transport, signer, readback, dispatch or effect capability. Digests are
transport observations, never proof that a provider or target was contacted.
Duplicate suppression is bounded to this adapter lifetime, not a durable effect
journal. Legacy raw Commander observations are not safe public projections.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
import re
from runtime.core_admission import Capability
from runtime.providers.nvidia import ProviderRequest
from .contracts import ContractError, TaskEnvelope, TaskResult, TaskState
from .policy import evaluate_task, PolicyEffect
from .read_ops import validate_read_payload

SCHEMA='aioa.mcp-read-advisory.v1'

def _deny():
    raise ContractError('MCP_ADVISORY_DENIED')

def _digest(value):
    if type(value) is not str or re.fullmatch('[a-f0-9]{64}',value) is None:_deny()
    return value

def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

@dataclass(frozen=True,slots=True)
class ArtifactRef:
    artifact_ref: str
    sha256: str
    offset: int
    max_bytes: int
    max_lines: int

@dataclass(frozen=True,slots=True)
class Question:
    code: str
    evidence_digest: str

@dataclass(frozen=True,slots=True)
class AdvisoryResult:
    binding_ref: str
    task_fingerprint: str
    request_fingerprint: str
    model_id: str
    response_sha256: str
    artifacts: tuple[ArtifactRef,...]
    questions: tuple[Question,...]
    def to_dict(self):
        return {**asdict(self),'artifacts':[asdict(x) for x in self.artifacts],
                'questions':[asdict(x) for x in self.questions], 'schema':SCHEMA,
                'authority':'ADVISORY_ONLY','can_authorize_effects':False,
                'provenance':'TRANSPORT_EVIDENCE_ONLY','mode':'OFFLINE_FIXTURE'}

class ReadAdvisoryAdapter:
    def __init__(self,core):
        self._core=core
        self._bindings={}
        self._requests={}
        self._seen=set()

    def bind(self,task,request,principal):
        scope=self._core.require(principal,Capability.READ)
        if type(task) is not TaskEnvelope or type(request) is not ProviderRequest:_deny()
        try:
            task.__post_init__()
            if evaluate_task(task).effect is not PolicyEffect.ALLOW:_deny()
            if request.provider_id not in {'nebius','nvidia'}:_deny()
            if request.model_id not in principal.model_binding_ids:_deny()
            if re.fullmatch(r'[A-Za-z0-9._-]+/[A-Za-z0-9._:-]+',request.model_id) is None:_deny()
            for text in (request.request_id,request.trace_id,request.budget_reservation_id,request.requested_output_schema):
                if type(text) is not str or not 1<=len(text)<=128 or any(ord(c)<32 for c in text):_deny()
            if type(request.input_text) is not str or not 1<=len(request.input_text.encode())<=4096:_deny()
            for value,maximum in ((request.max_output_tokens,128),(request.request_timeout,20)):
                if type(value) is not int or not 1<=value<=maximum:_deny()
            request_digest=_hash(asdict(request))
            binding=_hash([task.fingerprint,request_digest,list(scope.binding())])
        except (AttributeError,TypeError,ValueError,RecursionError):_deny()
        prior=self._requests.get(request.request_id)
        if prior is not None and prior!=binding:_deny()
        if binding not in self._bindings:
            if len(self._bindings)>=128:_deny()
            self._requests[request.request_id]=binding
            self._bindings[binding]=(task.task_id,task.fingerprint,request_digest,request.model_id,scope)
        return binding

    def admit(self,binding,result,principal):
        scope=self._core.require(principal,Capability.READ)
        _digest(binding)
        expected=self._bindings.get(binding)
        if expected is None or binding in self._seen or scope!=expected[4]:_deny()
        if type(result) is not TaskResult:_deny()
        try:
            result.__post_init__()
            if result.task_id!=expected[0] or result.state not in {TaskState.DONE,TaskState.WAITING_FOR_HUMAN}:_deny()
            data=result.metadata
            keys={'schema','binding_ref','task_fingerprint','model_id','finish_reason','mode','response_sha256','artifacts','questions'}
            if type(data) is not dict or set(data)!=keys:_deny()
            if (data['schema']!=SCHEMA or data['binding_ref']!=binding or data['task_fingerprint']!=expected[1]
                or data['model_id']!=expected[3] or data['finish_reason']!='stop' or data['mode']!='OFFLINE_FIXTURE'):_deny()
            response=_digest(data['response_sha256'])
            artifacts=data['artifacts'];questions=data['questions']
            if type(artifacts) is not list or len(artifacts)>8 or type(questions) is not list or len(questions)>8:_deny()
            refs=[];ids=[]
            for value in artifacts:
                if type(value) is not dict or set(value)!={'artifact_id','sha256','offset','max_bytes','max_lines'}:_deny()
                payload={k:v for k,v in value.items() if k!='sha256'}
                validate_read_payload('artifact.get',payload)
                digest=_digest(value['sha256']);ids.append(value['artifact_id'])
                refs.append(ArtifactRef(_hash(value['artifact_id']),digest,value['offset'],value['max_bytes'],value['max_lines']))
            if len(set(ids))!=len(ids) or tuple(ids)!=result.artifact_ids:_deny()
            qs=[]
            for value in questions:
                if type(value) is not dict or set(value)!={'code','evidence_digest'}:_deny()
                if value['code'] not in {'MISSING_EVIDENCE','CONFLICTING_EVIDENCE','NEEDS_HUMAN_REVIEW'}:_deny()
                qs.append(Question(value['code'],_digest(value['evidence_digest'])))
            if result.state is TaskState.WAITING_FOR_HUMAN and not qs:_deny()
            admitted=AdvisoryResult(binding,expected[1],expected[2],expected[3],response,tuple(refs),tuple(qs))
        except (AttributeError,TypeError,ValueError,RecursionError):_deny()
        self._seen.add(binding)
        return admitted
