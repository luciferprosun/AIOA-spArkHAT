"""Bounded offline advisory bookkeeping contracts, never execution authority."""
from dataclasses import asdict, dataclass, field

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.mission.governor import _amount, _deny, _digest, _identity
from runtime.providers.nvidia import OUTPUT_SCHEMA, ProviderRequest

MODEL='nvidia/Nemotron-3_5-Lightning'
OFFLINE_HOST_MODEL = 'aioa/offline-host-worker-v1'
OFFLINE_HOST_PROVIDER = 'offline-host'
OFFLINE_HOST_SCHEMA = 'aioa.offline-host-job.v1'
OFFLINE_HOST_OUTPUT = 'aioa.local-required-effects.v1'

@dataclass(frozen=True,slots=True,repr=False)
class JobEnvelope:
    scope:OwnerScope
    task_id:str
    request_id:str
    request_digest:str
    model_id:str
    output_schema:str
    max_output_tokens:int
    request_timeout:int
    deadline_at:int
    money_nano:int
    risk_units:int
    envelope_digest:str=field(init=False)

    def __post_init__(self):
        _deny(type(self.scope) is OwnerScope,'INVALID_RESERVATION_REQUEST')
        for v in (self.task_id,self.request_id):_identity(v)
        _digest(self.request_digest);_amount(self.money_nano);_amount(self.risk_units)
        local = self.offline_host
        _deny((local or self.model_id == MODEL and self.output_schema in (OUTPUT_SCHEMA, 'aioa-service-proposal-v1'))
            and type(self.max_output_tokens) is int and 1<=self.max_output_tokens<=512
            and type(self.request_timeout) is int and 1<=self.request_timeout<=30
            and type(self.deadline_at) is int and 0<self.deadline_at<=2**53,'INVALID_RESERVATION_REQUEST')
        if local:
            _deny(type(self.money_nano) is int and self.money_nano == 0
                  and type(self.risk_units) is int and self.risk_units == 0
                  and self.max_output_tokens == 1 and self.request_timeout == 20,
                  'INVALID_RESERVATION_REQUEST')
        object.__setattr__(self,'envelope_digest',canonical_sha256(self,exclude_fields=('envelope_digest',)))

    @property
    def offline_host(self):
        return self.model_id == OFFLINE_HOST_MODEL and self.output_schema == OFFLINE_HOST_OUTPUT

    @property
    def provider_id(self):
        return OFFLINE_HOST_PROVIDER if self.offline_host else 'nebius'

    @classmethod
    def for_offline_host(cls, scope, task_id, *, request_id, request_digest, deadline_at):
        """No provider request, synthetic usage or execution permission is fabricated."""
        _deny(cls is JobEnvelope, 'INVALID_RESERVATION_REQUEST')
        return cls(scope, task_id, request_id, request_digest, OFFLINE_HOST_MODEL,
                   OFFLINE_HOST_OUTPUT, 1, 20, deadline_at, 0, 0)

    @classmethod
    def from_request(cls,scope,task_id,request,*,deadline_at,money_nano,risk_units):
        _deny(type(request) is ProviderRequest and request.provider_id=='nebius'
            and request.model_id == MODEL and request.requested_output_schema in (OUTPUT_SCHEMA, 'aioa-service-proposal-v1')
            and type(request.input_text) is str and len(request.input_text.encode())<=4096,'INVALID_RESERVATION_REQUEST')
        return cls(scope,task_id,request.request_id,canonical_sha256(request),request.model_id,
            request.requested_output_schema,request.max_output_tokens,request.request_timeout,deadline_at,money_nano,risk_units)

    def as_dict(self):
        verified=JobEnvelope(**{k:getattr(self,k) for k in self.__dataclass_fields__ if k!='envelope_digest'})
        _deny(self.envelope_digest==verified.envelope_digest,'GOVERNOR_INTEGRITY')
        result={**asdict(self),'scope':list(self.scope.binding()),'schema':'aioa.offline-advisory-job.v1',
            'authority':'NONE','provider_id':self.provider_id,'transport_scope':'OFFLINE','verification':'UNVERIFIED'}
        if self.offline_host:
            result.update(schema=OFFLINE_HOST_SCHEMA, worker_certification='NOT_CERTIFIED')
        _deny(len(canonical_json_bytes(result))<=4096,'INVALID_RESERVATION_REQUEST')
        return result

    @classmethod
    def parse(cls,value):
        import json
        value = json.loads(canonical_json_bytes(value))
        keys=set(cls.__dataclass_fields__)-{'envelope_digest'}
        common = {'schema', 'authority', 'provider_id', 'transport_scope', 'verification', 'envelope_digest'}
        _deny(type(value) is dict and set(value) in (keys | common, keys | common | {'worker_certification'}),
              'GOVERNOR_INTEGRITY')
        envelope=cls(**{**{k:value[k] for k in keys},'scope':OwnerScope(*value['scope'])})
        _deny(envelope.envelope_digest==value['envelope_digest']
              and value == envelope.as_dict(), 'GOVERNOR_INTEGRITY')
        return envelope

@dataclass(frozen=True,slots=True,repr=False)
class JobClaim:
    task_id:str
    envelope_digest:str
    worker_id:str
    fence:int
    governor_epoch:int
    lease_until:int
    def __post_init__(self):
        _identity(self.task_id);_identity(self.worker_id);_digest(self.envelope_digest)
        for v in (self.fence,self.governor_epoch,self.lease_until):
            _deny(type(v) is int and 1<=v<=2**53,'INVALID_RESERVATION_REQUEST')
