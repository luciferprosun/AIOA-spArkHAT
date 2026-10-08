"""Dual bookkeeping on the existing Core and native serializable transaction port.

Global covers the supported single-owner Core namespace, across all tasks and
providers. Hosted cross-owner accounting is unsupported. This service does not
approve an effect, mint a principal, create a store, call a provider or resolve a
credential. Constructors/imports are inert; operator configuration is explicit.
"""
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import re
import time

from runtime.core_admission import Capability, CoreAdmission, OwnerScope
from runtime.core_admission import CorePrincipal
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.idempotency import OperationBinding, execute_once
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext, TransactionRunner

MAX_AMOUNT = 2**63-1
KIND = 'aioa-dual-governor-v1'
_STATES = frozenset({'RESERVED', 'DISPATCHED', 'UNKNOWN', 'COMMITTED', 'RELEASED'})


class GovernorReason(str, Enum):
    INVALID_AMOUNT = 'INVALID_GOVERNOR_AMOUNT'
    INVALID_IDENTITY = 'INVALID_GOVERNOR_IDENTITY'
    INVALID_DIGEST = 'INVALID_EVIDENCE_DIGEST'
    INVALID_POLICY = 'INVALID_GOVERNOR_POLICY'
    INVALID_BINDINGS = 'INVALID_GOVERNOR_BINDINGS'
    CLOCK_UNSAFE = 'CLOCK_UNSAFE'
    HISTORY_QUOTA = 'HISTORY_QUOTA'
    INTEGRITY = 'GOVERNOR_INTEGRITY'
    POLICY_BINDING = 'POLICY_BINDING'
    BUDGET = 'BUDGET_EXCEEDED'
    STALE_EPOCH = 'STALE_EPOCH'
    INVALID_KILL = 'INVALID_KILL_STATE'
    INVALID_REQUEST = 'INVALID_RESERVATION_REQUEST'
    MODEL_BINDING = 'MODEL_BINDING_DENIED'
    IDEMPOTENCY = 'IDEMPOTENCY_CONFLICT'
    KILL = 'KILL_SWITCH'
    OPEN = 'CIRCUIT_OPEN'
    HALF_OPEN = 'HALF_OPEN_BUSY'
    REQUIRED = 'RESERVATION_REQUIRED'
    STALE_RESERVATION = 'STALE_RESERVATION_EPOCH'
    NO_DISPATCH_PROOF = 'NO_DISPATCH_PROOF_REQUIRED'
    DISPATCH_MARKER = 'DISPATCH_MARKER_REQUIRED'


class GovernorError(MemoryPatchError, ValueError):
    """Native transaction-compatible exception with a closed, public reason."""
    def __init__(self, reason):
        self.reason = GovernorReason(reason)
        super().__init__(ErrorCode.INVALID_REQUEST)
        self.args = (self.reason.value,)


def _deny(condition, code):
    if not condition:
        raise GovernorError(code)


def _amount(value):
    _deny(type(value) is int and 0 <= value <= MAX_AMOUNT, 'INVALID_GOVERNOR_AMOUNT')
    return value


def _identity(value):
    _deny(type(value) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,179}', value) is not None,
          'INVALID_GOVERNOR_IDENTITY')


def _digest(value):
    _deny(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None, 'INVALID_EVIDENCE_DIGEST')


@dataclass(frozen=True, slots=True)
class Limits:
    money_nano: int
    risk_units: int

    def __post_init__(self):
        _amount(self.money_nano); _amount(self.risk_units)


@dataclass(frozen=True, slots=True, repr=False)
class GovernorPolicy:
    scope: OwnerScope
    deployment_id: str
    task_limit: Limits
    owner_provider_limit: Limits
    global_limit: Limits
    failure_threshold: int = 3
    cooldown_seconds: int = 30
    recovery_successes: int = 2
    max_clock_step_seconds: int = 120

    def __post_init__(self):
        _deny(type(self.scope) is OwnerScope, 'INVALID_GOVERNOR_POLICY')
        _identity(self.deployment_id)
        _deny(all(type(v) is Limits for v in (self.task_limit, self.owner_provider_limit, self.global_limit)),
              'INVALID_GOVERNOR_POLICY')
        for value in (self.failure_threshold, self.cooldown_seconds, self.recovery_successes, self.max_clock_step_seconds):
            _deny(type(value) is int and 1 <= value <= 86400, 'INVALID_GOVERNOR_POLICY')
        _deny(self.cooldown_seconds <= self.max_clock_step_seconds, 'INVALID_GOVERNOR_POLICY')

    @property
    def digest(self):
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True, repr=False)
class ReservationRequest:
    request_id: str
    task_id: str
    provider_id: str
    model_id: str
    request_digest: str
    money_nano: int
    risk_units: int

    def __post_init__(self):
        for value in (self.request_id, self.task_id, self.provider_id, self.model_id): _identity(value)
        _digest(self.request_digest)
        _amount(self.money_nano); _amount(self.risk_units)


def _plain(value):
    return json.loads(canonical_json_bytes(value))


def _exposure(reservations):
    totals = {'global': {'money_nano':0, 'risk_units':0}, 'tasks':{}, 'owner_providers':{}}
    for entry in reservations.values():
        if entry['state'] == 'RELEASED':
            continue
        buckets = (totals['global'],
            totals['tasks'].setdefault(entry['task_id'], {'money_nano':0, 'risk_units':0}),
            totals['owner_providers'].setdefault(entry['provider_id'], {'money_nano':0, 'risk_units':0}))
        for bucket in buckets:
            for field in ('money_nano', 'risk_units'):
                bucket[field] = _amount(bucket[field] + _amount(entry[field]))
    return totals


class CoreDualGovernor:
    """Append-only snapshots, paired reservations, current epoch at dispatch CAS.

The final dispatch-commit is the local linearization point, not an atomic
database+HTTP transaction. A later kill/revocation cannot cancel an in-flight
commit or refund it. A lost marker ACK never gives send permission on replay.
"""
    def __init__(self, core, runner, policy, *, clock=time.time):
        _deny(type(core) is CoreAdmission and type(runner) is TransactionRunner
              and type(policy) is GovernorPolicy and callable(clock), 'INVALID_GOVERNOR_BINDINGS')
        self.core, self.runner, self.policy, self.clock = core, runner, policy, clock

    def _require(self, principal, purpose):
        self.core.require(principal, purpose, scope=self.policy.scope)

    def _now(self):
        value = self.clock()
        _deny(type(value) in (int, float) and 0 <= value <= 2**53, 'CLOCK_UNSAFE')
        return int(value)

    def _key(self, version):
        return canonical_sha256((KIND, self.policy.scope, self.policy.deployment_id, version))

    def _initial(self):
        return {'schema':KIND, 'policy_digest':self.policy.digest, 'version':0, 'epoch':0,
                'kill':False, 'last_now':None, 'reservations':{}, 'circuits':{}}

    def _load(self, tx):
        records = tx.scan(RecordKind.OPERATION, limit=1024)
        _deny(len(records) < 1024, 'HISTORY_QUOTA')
        selected=[]
        for record in records:
            if record.payload.get('operation_kind') != KIND:
                continue
            _deny(set(record.payload) == {'operation_kind','payload_digest','outcome'}, 'GOVERNOR_INTEGRITY')
            outcome=record.payload['outcome']
            _deny(set(outcome) == {'state','prior_digest'}, 'GOVERNOR_INTEGRITY')
            _deny(record.payload['payload_digest'] == canonical_sha256(outcome), 'GOVERNOR_INTEGRITY')
            state=outcome['state']
            _deny(state.get('policy_digest') == self.policy.digest, 'POLICY_BINDING')
            _deny(set(state) == set(self._initial()) and state['schema'] == KIND, 'GOVERNOR_INTEGRITY')
            _deny(type(state['version']) is int and 1 <= state['version'] <= 1023, 'GOVERNOR_INTEGRITY')
            _deny(record.record_id == self._key(state['version']) and record.revision == 1, 'GOVERNOR_INTEGRITY')
            selected.append((state['version'],outcome))
        current=self._initial()
        for index,outcome in sorted(selected):
            _deny(index == current['version']+1 and outcome['prior_digest'] == canonical_sha256(current), 'GOVERNOR_INTEGRITY')
            current=_plain(outcome['state'])
            self._validate(current)
        return current

    def _validate(self, state):
        _deny(type(state['epoch']) is int and 1 <= state['epoch'] <= MAX_AMOUNT
              and type(state['kill']) is bool
              and type(state['last_now']) is int and 0 <= state['last_now'] <= 2**53,
              'GOVERNOR_INTEGRITY')
        _deny(type(state['reservations']) is dict and len(state['reservations']) <= 128
              and type(state['circuits']) is dict and len(state['circuits']) <= 32, 'HISTORY_QUOTA')
        for identity,entry in state['reservations'].items():
            _deny(set(entry) == {'request_id','task_id','provider_id','model_id','request_digest',
                  'money_nano','risk_units','binding_digest','epoch','state','evidence_digest','no_dispatch_proof'},
                  'GOVERNOR_INTEGRITY')
            request=ReservationRequest(**{k:entry[k] for k in ReservationRequest.__dataclass_fields__})
            _deny(identity == request.request_id and entry['binding_digest'] == canonical_sha256(request)
                  and entry['state'] in _STATES and type(entry['epoch']) is int
                  and 1 <= entry['epoch'] <= state['epoch'], 'GOVERNOR_INTEGRITY')
            if entry['evidence_digest'] is not None: _digest(entry['evidence_digest'])
            if entry['state'] == 'RELEASED':
                proof=entry['no_dispatch_proof']
                _deny(type(proof) is dict and set(proof) == {'kind','request_digest','epoch','version'}
                      and proof['kind'] == 'DURABLE_NO_DISPATCH_MARKER'
                      and proof['request_digest'] == entry['request_digest']
                      and type(proof['version']) is int and 1 <= proof['version'] <= state['version'],
                      'GOVERNOR_INTEGRITY')
            else:
                _deny(entry['no_dispatch_proof'] is None, 'GOVERNOR_INTEGRITY')
        for provider,circuit in state['circuits'].items():
            _identity(provider)
            _deny(set(circuit) == {'state','failures','successes','opened_at','probe'}
                  and circuit['state'] in {'CLOSED','OPEN','HALF_OPEN'}, 'GOVERNOR_INTEGRITY')
            for field in ('failures','successes','opened_at'): _amount(circuit[field])
            _deny(circuit['probe'] is None or circuit['probe'] in state['reservations'], 'GOVERNOR_INTEGRITY')
        self._budgets(state)

    def _budgets(self, state):
        exposure=_exposure(state['reservations'])
        for limits,buckets in ((self.policy.global_limit,(exposure['global'],)),
                              (self.policy.task_limit,exposure['tasks'].values()),
                              (self.policy.owner_provider_limit,exposure['owner_providers'].values())):
            for bucket in buckets:
                _deny(bucket['money_nano'] <= limits.money_nano and bucket['risk_units'] <= limits.risk_units,
                      'BUDGET_EXCEEDED')

    def _clock(self, state, now):
        previous=state['last_now']
        _deny(previous is None or 0 <= now-previous <= self.policy.max_clock_step_seconds, 'CLOCK_UNSAFE')

    def _epoch(self, state, epoch):
        _deny(type(epoch) is int and epoch == state['epoch'] and epoch > 0, 'STALE_EPOCH')

    def _write(self, tx, before, state, now):
        state['version']=before['version']+1;state['last_now']=now
        self._validate(state)
        outcome={'state':state,'prior_digest':canonical_sha256(before)}
        binding=OperationBinding.bind(self._key(state['version']),KIND,outcome)
        def append():
            append_domain_event(tx,binding,event_id='governor-'+binding.idempotency_key,
                proof_id='governor-outbox-'+binding.idempotency_key,resource_id=binding.idempotency_key,
                before=str(before['version']),after=str(state['version']),content_digest=canonical_sha256(state),
                at=datetime.fromtimestamp(now,timezone.utc))
            return outcome
        execute_once(tx,binding,append)

    def _change(self, principal, purpose, change, *, check_clock=True):
        self._require(principal,purpose);now=self._now()
        def apply(tx):
            before=self._load(tx);state=_plain(before)
            if check_clock:self._clock(state,now)
            result,changed=change(state)
            if changed:self._write(tx,before,state,max(now,state['last_now'] or 0))
            return _plain(result)
        return self.runner.run(TransactionContext(principal,purpose),apply)

    def inspect(self, principal):
        self._require(principal,Capability.READ)
        def read(tx):
            state=self._load(tx)
            return {**state,'authority':'NONE','global_scope':'SINGLE_OWNER_CORE_NAMESPACE',
                    'exposure':_exposure(state['reservations'])}
        return self.runner.run(TransactionContext(principal,Capability.READ),read)

    def start_epoch(self, principal):
        """Explicit Core operator takeover; never automatic at construction."""
        now=self._now()
        def change(state):
            _deny(state['last_now'] is None or now >= state['last_now'], 'CLOCK_UNSAFE')
            state['epoch']=_amount(state['epoch']+1)
            for circuit in state['circuits'].values():
                if circuit['state'] == 'HALF_OPEN':
                    circuit.update(state='OPEN',opened_at=now,probe=None,successes=0)
            return state['epoch'],True
        return self._change(principal,Capability.MANAGE,change,check_clock=False)

    def set_kill(self, principal, active):
        _deny(type(active) is bool,'INVALID_KILL_STATE')
        def change(state):
            changed=state['kill'] != active;state['kill']=active
            return {'kill':active},changed
        return self._change(principal,Capability.MANAGE,change,check_clock=not active)

    def reserve(self, principal, request, epoch):
        self._require(principal,Capability.COMMIT)
        _deny(type(request) is ReservationRequest,'INVALID_RESERVATION_REQUEST')
        request=ReservationRequest(**asdict(request))
        binding=canonical_sha256(request)
        _deny(request.model_id in principal.model_binding_ids,'MODEL_BINDING_DENIED')
        now=self._now()
        def change(state):
            self._epoch(state,epoch)
            existing=state['reservations'].get(request.request_id)
            if existing is not None:
                _deny(existing['binding_digest'] == binding,'IDEMPOTENCY_CONFLICT')
                return existing,False
            _deny(not state['kill'],'KILL_SWITCH')
            _deny(len(state['reservations']) < 128,'HISTORY_QUOTA')
            if request.provider_id not in state['circuits']:
                _deny(len(state['circuits']) < 32,'HISTORY_QUOTA')
            circuit=state['circuits'].setdefault(request.provider_id,
                {'state':'CLOSED','failures':0,'successes':0,'opened_at':0,'probe':None})
            if circuit['state'] == 'OPEN':
                _deny(now-circuit['opened_at'] >= self.policy.cooldown_seconds,'CIRCUIT_OPEN')
                circuit.update(state='HALF_OPEN',probe=None,successes=0)
            if circuit['state'] == 'HALF_OPEN':
                _deny(circuit['probe'] is None,'HALF_OPEN_BUSY')
                circuit['probe']=request.request_id
            entry={**asdict(request),'binding_digest':binding,'epoch':epoch,'state':'RESERVED',
                   'evidence_digest':None,'no_dispatch_proof':None}
            state['reservations'][request.request_id]=entry
            self._budgets(state)
            return entry,True
        return self._change(principal,Capability.COMMIT,change)
    def dispatch_commit(self, principal, request_id, epoch):
        """Final current-state CAS. Only a newly ACKed marker permits one send.

This bookkeeping permission is not an effect warrant. The existing transport
and human-authority checks must still pass. Do not send after an exception.
"""
        _identity(request_id)
        now=self._now()
        def change(state):
            self._epoch(state,epoch)
            entry=state['reservations'].get(request_id)
            _deny(entry is not None,'RESERVATION_REQUIRED')
            if entry['state'] != 'RESERVED':
                return {'dispatch_now':False,'reservation':entry,'reconcile_only':True},False
            _deny(entry['epoch'] == epoch,'STALE_RESERVATION_EPOCH')
            _deny(not state['kill'],'KILL_SWITCH')
            circuit=state['circuits'][entry['provider_id']]
            _deny(circuit['state'] == 'CLOSED' or
                  (circuit['state'] == 'HALF_OPEN' and circuit['probe'] == request_id),'CIRCUIT_OPEN')
            self._clock(state,now)
            self._budgets(state)
            entry['state']='DISPATCHED'
            return {'dispatch_now':True,'reservation':entry,'reconcile_only':False},True
        return self._change(principal,Capability.COMMIT,change)

    def release_not_dispatched(self, principal, request_id, epoch):
        """Native positive proof emitted atomically; no caller-set proof boolean."""
        _identity(request_id)
        def change(state):
            self._epoch(state,epoch)
            entry=state['reservations'].get(request_id)
            _deny(entry is not None,'RESERVATION_REQUIRED')
            if entry['state'] == 'RELEASED': return entry,False
            _deny(entry['state'] == 'RESERVED','NO_DISPATCH_PROOF_REQUIRED')
            entry['no_dispatch_proof']={'kind':'DURABLE_NO_DISPATCH_MARKER',
                'request_digest':entry['request_digest'],'epoch':epoch,'version':state['version']+1}
            entry['state']='RELEASED'
            circuit=state['circuits'][entry['provider_id']]
            if circuit['probe'] == request_id:circuit['probe']=None
            return entry,True
        return self._change(principal,Capability.COMMIT,change)

    def mark_unknown(self, principal, request_id, epoch, evidence_digest):
        _identity(request_id);_digest(evidence_digest)
        now=self._now()
        def change(state):
            self._epoch(state,epoch)
            entry=state['reservations'].get(request_id)
            _deny(entry is not None,'RESERVATION_REQUIRED')
            if entry['state'] == 'UNKNOWN':
                _deny(entry['evidence_digest'] == evidence_digest,'IDEMPOTENCY_CONFLICT')
                return entry,False
            _deny(entry['state'] == 'DISPATCHED','DISPATCH_MARKER_REQUIRED')
            entry.update(state='UNKNOWN',evidence_digest=evidence_digest)
            circuit=state['circuits'][entry['provider_id']]
            circuit['failures']=_amount(circuit['failures']+1)
            circuit['successes']=0
            if circuit['state'] == 'HALF_OPEN' or circuit['failures'] >= self.policy.failure_threshold:
                circuit.update(state='OPEN',opened_at=now,probe=None)
            return entry,True
        return self._change(principal,Capability.COMMIT,change)

    def settle(self, principal, request_id, epoch, evidence_digest):
        """Evidence-referenced pessimistic charge of the entire reserved bound.

It never reports task/effect verification, refunds money/risk or authorizes a
retry. Circuit recovery from UNKNOWN is deliberately not treated as success.
"""
        _identity(request_id);_digest(evidence_digest)
        def change(state):
            self._epoch(state,epoch)
            entry=state['reservations'].get(request_id)
            _deny(entry is not None,'RESERVATION_REQUIRED')
            if entry['state'] == 'COMMITTED':
                _deny(entry['evidence_digest'] == evidence_digest,'IDEMPOTENCY_CONFLICT')
                return entry,False
            _deny(entry['state'] in {'DISPATCHED','UNKNOWN'},'DISPATCH_MARKER_REQUIRED')
            was_unknown=entry['state'] == 'UNKNOWN'
            entry.update(state='COMMITTED',evidence_digest=evidence_digest)
            circuit=state['circuits'][entry['provider_id']]
            if not was_unknown and circuit['state'] == 'HALF_OPEN' and circuit['probe'] == request_id:
                circuit['probe']=None;circuit['successes']+=1
                if circuit['successes'] >= self.policy.recovery_successes:
                    circuit.update(state='CLOSED',failures=0,successes=0)
            elif not was_unknown and circuit['state'] == 'CLOSED':
                circuit['failures']=0
            return entry,True
        return self._change(principal,Capability.COMMIT,change)


@dataclass(frozen=True, slots=True, repr=False)
class GovernorBinding:
    """Explicit Core composition data; not model input or human authority."""
    governor: CoreDualGovernor
    principal: CorePrincipal
    epoch: int
    task_id: str
    advisory_risk_units: int

    def __post_init__(self):
        _deny(type(self.governor) is CoreDualGovernor and type(self.principal) is CorePrincipal,
              'INVALID_GOVERNOR_BINDINGS')
        _identity(self.task_id)
        _deny(type(self.epoch) is int and 1 <= self.epoch <= MAX_AMOUNT, 'STALE_EPOCH')
        _deny(_amount(self.advisory_risk_units) > 0,'INVALID_GOVERNOR_AMOUNT')
        self.governor._require(self.principal,Capability.COMMIT)
