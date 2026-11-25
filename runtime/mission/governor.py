"""Dual bookkeeping on the existing Core and native serializable transaction port.

Global covers the supported single-owner Core namespace, across all tasks and
providers. Hosted cross-owner accounting is unsupported. This service does not
approve an effect, mint a principal, create a store, call a provider or resolve a
credential. Constructors/imports are inert; operator configuration is explicit.
"""
import re
import time
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.idempotency import OperationBinding, execute_once
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    TransactionContext,
    TransactionRunner,
    TransactionView,
    _register_history_reader,
)
from runtime.mission import execution_capacity as capacity
from runtime.mission.execution_capacity import (
    CapacityTransitionReceipt,
    ExecutionCapacityReview,
)
from runtime.mission.governor_contracts import (
    MAX_AMOUNT,
    ReservationRequest,
    _amount,
    _deny,
    _digest,
    _identity,
    _plain,
)
from runtime.mission.governor_contracts import (
    GovernorError as GovernorError,
)
from runtime.mission.governor_contracts import (
    GovernorReason as GovernorReason,
)
from runtime.mission.warrant import CoreWarrantLedger

KIND = 'aioa-dual-governor-v1'
_STATES = frozenset({'RESERVED', 'DISPATCHED', 'UNKNOWN', 'COMMITTED', 'RELEASED'})


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
        if isinstance(tx, TransactionView):
            return tx._history_read('GOVERNOR_STATE', governor=self)
        return self._load_history(tx)

    def _load_history(self, tx):
        records = tx.scan(RecordKind.OPERATION, limit=1024, operation_kind=KIND)
        _deny(len(records) < 1024, 'HISTORY_QUOTA')
        selected=[]
        for record in records:
            if record.payload.get('operation_kind') != KIND:
                continue
            _deny(set(record.payload) == {'operation_kind','payload_digest','outcome'}, 'GOVERNOR_INTEGRITY')
            outcome=record.payload['outcome']
            _deny(set(outcome) in ({'state','prior_digest'},{'state','prior_digest','policy_transition'},
                {'state','prior_digest','execution_capacity_transition'}), 'GOVERNOR_INTEGRITY')
            _deny(record.payload['payload_digest'] == canonical_sha256(outcome), 'GOVERNOR_INTEGRITY')
            state=outcome['state']
            _deny(state.get('policy_digest') == self.policy.digest, 'POLICY_BINDING')
            _deny(set(state) in tuple(set(self._initial())|extra for extra in
                (set(),{'money_policy'},{'execution_capacity'},{'money_policy','execution_capacity'})) and state['schema'] == KIND, 'GOVERNOR_INTEGRITY')
            _deny(type(state['version']) is int and 1 <= state['version'] <= 1023, 'GOVERNOR_INTEGRITY')
            _deny(record.record_id == self._key(state['version']) and record.revision == 1, 'GOVERNOR_INTEGRITY')
            selected.append((state['version'],outcome))
        current=self._initial();money_requests=set();capacity_requests=set()
        for index,outcome in sorted(selected):
            _deny(index == current['version']+1 and outcome['prior_digest'] == canonical_sha256(current), 'GOVERNOR_INTEGRITY')
            proposed=_plain(outcome['state']);transition=outcome.get('policy_transition')
            if proposed.get('money_policy')!=current.get('money_policy'):
                self._validate_money_transition(current,proposed,_plain(transition) if transition is not None else None)
                identity=transition['request_id']
                _deny(identity not in money_requests,'GOVERNOR_INTEGRITY')
                money_requests.add(identity)
            else:_deny('policy_transition' not in outcome,'GOVERNOR_INTEGRITY')
            retained=outcome.get('execution_capacity_transition')
            if proposed.get('execution_capacity')!=current.get('execution_capacity'):
                _deny(retained is not None,'GOVERNOR_INTEGRITY')
                review,_=self._validate_capacity_transition(tx,current,proposed,_plain(retained))
                identity=review.to_dict()['request_id']
                _deny(identity not in capacity_requests,'GOVERNOR_INTEGRITY')
                capacity_requests.add(identity)
                self._validate_capacity_event(tx,index,outcome)
            else:_deny(retained is None,'GOVERNOR_INTEGRITY')
            current=_plain(outcome['state'])
            self._validate(current)
        return current

    def _validate(self, state):
        if 'execution_capacity' in state:capacity.validate_override(_plain(state['execution_capacity']))
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
        override=state.get('money_policy',{}).get('limits',{})
        risk=state.get('execution_capacity',{}).get('capacity',{}).get('risk_limits',{})
        for name,limits,buckets in (('global_limit',self.policy.global_limit,(exposure['global'],)),
                              ('task_limit',self.policy.task_limit,exposure['tasks'].values()),
                              ('owner_provider_limit',self.policy.owner_provider_limit,exposure['owner_providers'].values())):
            for bucket in buckets:
                ceiling=override.get(name,limits.money_nano)
                _deny((ceiling is None or bucket['money_nano'] <= ceiling) and bucket['risk_units'] <= risk.get(name,limits.risk_units),
                      'BUDGET_EXCEEDED')

    def _clock(self, state, now):
        previous=state['last_now']
        _deny(previous is None or 0 <= now-previous <= self.policy.max_clock_step_seconds, 'CLOCK_UNSAFE')

    def _epoch(self, state, epoch):
        _deny(type(epoch) is int and epoch == state['epoch'] and epoch > 0, 'STALE_EPOCH')

    def _write(self, tx, before, state, now, *, policy_transition=None, execution_capacity_transition=None):
        state['version']=before['version']+1;state['last_now']=now
        self._validate(state)
        outcome={'state':state,'prior_digest':canonical_sha256(before)}
        if policy_transition is not None:
            self._validate_money_transition(before,state,policy_transition)
            outcome['policy_transition']=policy_transition
        if execution_capacity_transition is not None:
            _deny(policy_transition is None,'GOVERNOR_INTEGRITY')
            self._validate_capacity_transition(tx,before,state,execution_capacity_transition)
            outcome['execution_capacity_transition']=execution_capacity_transition
        binding=OperationBinding.bind(self._key(state['version']),KIND,outcome)
        def append():
            append_domain_event(tx,binding,event_id='governor-'+binding.idempotency_key,
                proof_id='governor-outbox-'+binding.idempotency_key,resource_id=binding.idempotency_key,
                before=str(before['version']),after=str(state['version']),content_digest=canonical_sha256(state),
                at=datetime.fromtimestamp(now,UTC))
            return outcome
        execute_once(tx,binding,append)

    def _change(self, principal, purpose, change, *, check_clock=True, reconciliation=False):
        gate = getattr(self.runner, "execution_gate", None)
        with gate.hold() if gate is not None else nullcontext():
            return self._change_under_execution_gate(
                principal, purpose, change, check_clock=check_clock,
                reconciliation=reconciliation,
            )

    def _change_under_execution_gate(self, principal, purpose, change, *,
                                     check_clock=True, reconciliation=False):
        self._require(principal,purpose);now=self._now()
        def apply(tx):
            before=self._load(tx);state=_plain(before)
            if check_clock:
                if reconciliation and state['kill']:
                    # A stopped Core must still account for delayed receipts.
                    # Permit a forward pause only on reconciliation paths;
                    # admission, dispatch and operator unkill retain _clock.
                    _deny(state['last_now'] is None or now >= state['last_now'], 'CLOCK_UNSAFE')
                else:
                    self._clock(state,now)
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

    def _effective_capacity(self,state):
        if 'execution_capacity' in state:
            return capacity.proposal(_plain(state['execution_capacity']['capacity']))
        return {'risk_limits':{name:getattr(self.policy,name).risk_units for name in
            ('task_limit','owner_provider_limit','global_limit')},
            'sandbox_exec_failure_threshold':self.policy.failure_threshold}

    def _validate_capacity_transition(self,tx,before,after,transition):
        review=capacity.ExecutionCapacityReview.from_dict(_plain(transition['review']))
        warrant=capacity.capacity_warrant(review)
        key=canonical_sha256(('aioa-linear-warrant-v1',self.policy.scope,warrant.nonce))
        return capacity.validate_transition(before,after,transition,scope=self.policy.scope,
            deployment_id=self.policy.deployment_id,policy_digest=self.policy.digest,
            prior_capacity=self._effective_capacity(before),exposure_digest=canonical_sha256(_exposure(before['reservations'])),
            current_operation=tx.get(RecordKind.OPERATION,key),current_witness=tx.get(RecordKind.APPROVAL,key))

    def _validate_capacity_event(self,tx,version,outcome):
        from runtime.memory_patch.audit import decode_audit, domain_chain
        domain_chain(tx)
        key=self._key(version)
        event_row=tx.get(RecordKind.AUDIT,'governor-'+key)
        _deny(event_row is not None,'GOVERNOR_INTEGRITY')
        event=decode_audit(event_row)
        binding=OperationBinding.bind(key,KIND,outcome)
        box=tx.get(RecordKind.OUTBOX,'governor-outbox-'+key)
        _deny(box is not None and event.resource_id==key and event.event_type==KIND
            and event.content_hashes.get('content')==canonical_sha256(outcome['state'])
            and event.content_hashes.get('operation')==binding.payload_digest
            and set(box.payload)=={'state','event_id','event_digest','operation_digest','proof_id','core_entry_hash'}
            and box.payload['state'] in ('PENDING','PUBLISHED')
            and box.payload['event_id']=='governor-'+key and box.payload['proof_id']=='governor-outbox-'+key
            and box.payload['event_digest']==event.event_hash
            and box.payload['operation_digest']==canonical_sha256({'scope':self.policy.scope.binding(),'operation':binding}),
            'GOVERNOR_INTEGRITY')
        _deny(box.revision==(1 if box.payload['state']=='PENDING' else 2)
            and (box.payload['core_entry_hash'] is None if box.payload['state']=='PENDING' else
                 type(box.payload['core_entry_hash']) is str and re.fullmatch('[0-9a-f]{64}',box.payload['core_entry_hash']) is not None),
            'GOVERNOR_INTEGRITY')

    def _capacity_readback(self,tx,request_id,review_digest=None,warrant_digest=None,proposed=None):
        self._load(tx)
        found=None
        for row in tx.scan(RecordKind.OPERATION,limit=1024,operation_kind=KIND):
            transition=row.payload['outcome'].get('execution_capacity_transition')
            if transition is not None and transition['review']['request_id']==request_id:
                _deny(found is None,'GOVERNOR_INTEGRITY')
                outcome=row.payload['outcome'];review=transition['review']
                from lab.archaioa.warrant import EffectWarrant
                warrant=EffectWarrant.from_dict(_plain(transition['warrant']))
                _deny(review_digest is None or review_digest==review['review_digest'],'IDEMPOTENCY_CONFLICT')
                _deny(warrant_digest is None or warrant_digest==warrant.digest(),'IDEMPOTENCY_CONFLICT')
                _deny(proposed is None or capacity.same_json(proposed,review['proposed_capacity']),'IDEMPOTENCY_CONFLICT')
                found=capacity.CapacityTransitionReceipt('READBACK_ONLY',outcome['state']['version'],outcome['state']['epoch'],
                    review['review_digest'],warrant.digest(),_plain(transition['consumption']))
        return found

    def execution_capacity_review(self,reader,proposed,*,request_id,host_capture,composition_digest) -> ExecutionCapacityReview:
        from runtime.meta_hackathon.native_authority import (
            CapacityStage,
            NativeCapacityHostCapture,
        )
        _deny(type(host_capture) is NativeCapacityHostCapture and host_capture.foundation.governor is self,
              'INVALID_GOVERNOR_BINDINGS')
        self._require(reader,Capability.READ)
        _deny(reader is host_capture.authorities[0].principal and composition_digest==host_capture.foundation.spec.digest,
              'INVALID_GOVERNOR_BINDINGS')
        proposed=capacity.proposal(proposed);capacity.hexdigest(request_id,32)
        host_capture.require_live(CapacityStage.REVIEW)
        def read(tx):
            host_capture.require_live(CapacityStage.REVIEW,tx=tx)
            host_capture.controller.require_core_view(host_capture,tx)
            before=self._load(tx)
            _deny(before['version']>0 and before['epoch']>0,'STALE_EPOCH')
            candidate=_plain(before);candidate['execution_capacity']={'capacity':proposed}
            self._budgets(candidate)
            a=host_capture.authorities[0]
            body={'schema':capacity.REVIEW_SCHEMA,'request_id':request_id,'scope':list(self.policy.scope.binding()),
                'deployment_id':self.policy.deployment_id,'bootstrap_policy_digest':self.policy.digest,
                'expected_version':before['version'],'expected_epoch':before['epoch'],
                'expected_state_digest':canonical_sha256(before),'expected_exposure_digest':canonical_sha256(_exposure(before['reservations'])),
                'prior_effective_capacity':self._effective_capacity(before),'proposed_capacity':proposed,
                'host_source_sha':a.source[0],'host_source_capsule_digest':a.source[1],'composition_digest':composition_digest,
                'native_admission_revision':a.native_revision,'native_admission_digest':a.native_digest,
                'admission_generation':a.admission_generation,'composition_generation':a.composition_generation,
                'actor_session_id':a.instance_id,'assignment_revision':a.assignment_revision,
                'quiescence':capacity.strict_json(host_capture.quiescence.projection),
                'issued_at':capacity.timestamp(host_capture.captured_at),'expires_at':capacity.timestamp(host_capture.expires_at)}
            result=capacity.ExecutionCapacityReview.from_dict({**body,'review_digest':canonical_sha256(body)})
            candidate_warrant=capacity.capacity_warrant(result)
            _deny(tx.get(RecordKind.OPERATION,host_capture.foundation.ledger._key(candidate_warrant)) is None,
                'IDEMPOTENCY_CONFLICT')
            host_capture.require_live(CapacityStage.REVIEW,tx=tx)
            return result
        result=self.runner.run(TransactionContext(reader,Capability.READ),read)
        host_capture.require_live(CapacityStage.REVIEW)
        return result

    def apply_execution_capacity(self,commit_principal,review,warrant,*,management_principal,ledger,host_capture,quiescence_capture) -> CapacityTransitionReceipt:
        from lab.archaioa.warrant import EffectWarrant

        from runtime.meta_hackathon.native_authority import (
            CapacityStage,
            NativeCapacityHostCapture,
        )
        _deny(type(host_capture) is NativeCapacityHostCapture and host_capture.foundation.governor is self
            and type(review) is capacity.ExecutionCapacityReview and host_capture.review is review
            and type(warrant) is EffectWarrant and type(ledger) is CoreWarrantLedger
            and ledger is host_capture.foundation.ledger and quiescence_capture is host_capture.quiescence,
            'INVALID_GOVERNOR_BINDINGS')
        _deny(commit_principal is host_capture.authorities[1].principal
            and management_principal is host_capture.authorities[0].principal
            and capacity.same_json(warrant.to_dict(),capacity.capacity_warrant(review).to_dict()),'POLICY_BINDING')
        self._require(commit_principal,Capability.COMMIT);self._require(management_principal,Capability.MANAGE)
        host_capture.require_live(CapacityStage.APPLY)
        applied_at=host_capture.applied_at
        now=int(applied_at.timestamp())
        def apply(tx):
            host_capture.require_live(CapacityStage.APPLY,tx=tx)
            host_capture.controller.require_core_view(host_capture,tx)
            before=self._load(tx);r=review.to_dict()
            _deny((before['version'],before['epoch'],canonical_sha256(before),canonical_sha256(_exposure(before['reservations'])))==
                (r['expected_version'],r['expected_epoch'],r['expected_state_digest'],r['expected_exposure_digest']),'POLICY_BINDING')
            _deny(capacity.utc(r['issued_at'])<=applied_at<capacity.utc(r['expires_at'])
                and (before['last_now'] is None or now>=before['last_now']),'CLOCK_UNSAFE')
            stored,_=ledger.require_active_in_transaction(tx,warrant)
            witness=tx.get(RecordKind.APPROVAL,ledger._key(warrant))
            approval={'owner_witness':capacity.snapshot(witness),'warrant_state_before':capacity.snapshot(stored)}
            receipt=ledger.consume_in_transaction(tx,warrant)
            after_warrant=tx.get(RecordKind.OPERATION,ledger._key(warrant))
            approval['warrant_state_after_digest']=after_warrant.payload_digest
            transition={'schema':capacity.TRANSITION_SCHEMA,'review':r,'warrant':warrant.to_dict(),
                'applied_at':capacity.timestamp(applied_at),'approval_at_apply':approval,'consumption':receipt}
            state=_plain(before);state.update(epoch=before['epoch']+1,execution_capacity=capacity.override(review,warrant,receipt))
            self._budgets(state)
            host_capture.require_live(CapacityStage.APPLY,tx=tx)
            self._write(tx,before,state,now,execution_capacity_transition=transition)
            host_capture.require_live(CapacityStage.APPLY,tx=tx)
            return capacity.CapacityTransitionReceipt('APPLIED',state['version'],state['epoch'],r['review_digest'],warrant.digest(),receipt)
        result=self.runner.run(TransactionContext(commit_principal,Capability.COMMIT),apply)
        try:host_capture.require_live(CapacityStage.APPLY)
        except ValueError as error:raise capacity.CapacityAcknowledgedButFenced('READBACK_ONLY') from error
        return result

    def _money_review(self,state,limits,request_id):
        _identity(request_id)
        _deny(type(limits) is dict and set(limits)=={'task_limit','owner_provider_limit','global_limit'},'INVALID_GOVERNOR_POLICY')
        unlimited=all(value is None for value in limits.values())
        if not unlimited:
            for value in limits.values():_amount(value)
        body={'schema':'aioa.governor.money-review.v3' if unlimited else 'aioa.governor.money-review.v2','request_id':request_id,
            'bootstrap_policy_digest':self.policy.digest,'expected_version':state['version'],
            'expected_epoch':state['epoch'],'limits':dict(limits)}
        return {**body,'review_digest':canonical_sha256(body)}

    def money_policy_review(self,principal,limits,*,request_id):
        self._require(principal,Capability.READ)
        return self.runner.run(TransactionContext(principal,Capability.READ),
            lambda tx:self._money_review(self._load(tx),limits,request_id))

    def _validate_money_transition(self,before,after,review):
        _deny(type(review) is dict and set(review)=={'schema','request_id','bootstrap_policy_digest',
            'expected_version','expected_epoch','limits','review_digest'},'GOVERNOR_INTEGRITY')
        expected=self._money_review(before,review['limits'],review['request_id'])
        _deny(canonical_json_bytes(review)==canonical_json_bytes(expected),'POLICY_BINDING')
        _deny(type(after['last_now']) is int and (before['last_now'] is None
            or after['last_now']>=before['last_now']),'CLOCK_UNSAFE')
        policy={'schema':review['schema'].replace('money-review','money-policy'),'limits':review['limits'],
            'request_id':review['request_id'],'review_digest':review['review_digest']}
        unchanged=_plain(before)
        unchanged.update(money_policy=policy,epoch=before['epoch']+1,version=before['version']+1,last_now=after['last_now'])
        _deny(canonical_json_bytes(after)==canonical_json_bytes(unchanged),'GOVERNOR_INTEGRITY')

    def apply_money_policy(self,principal,review,*,authority_check=None):
        """Exact native MANAGE transition in the SAME immutable state chain.

        Bootstrap policy identity and v1 prior hashes remain unchanged. Only
        financial limits change; risk, reservations, UNKNOWN and kill survive.
        This allocates local capacity; it neither verifies provider credit nor
        authorizes any paid request.
        """
        self._require(principal,Capability.MANAGE)
        _deny(type(review) is dict,'GOVERNOR_INTEGRITY')
        _deny(authority_check is None or callable(authority_check),'INVALID_GOVERNOR_BINDINGS')
        now=self._now()
        def apply(tx):
            if authority_check is not None:authority_check()
            before=self._load(tx)
            # Duplicate receipts survive later policy changes and restart.
            for row in tx.scan(RecordKind.OPERATION,limit=1024,operation_kind=KIND):
                prior=row.payload['outcome'].get('policy_transition')
                if prior is not None and prior['request_id']==review.get('request_id'):
                    _deny(canonical_json_bytes(prior)==canonical_json_bytes(review),'IDEMPOTENCY_CONFLICT')
                    return {'readback_only':True,'epoch':before['epoch'],'version':before['version']}
            expected=self._money_review(before,review.get('limits'),review.get('request_id'))
            _deny(canonical_json_bytes(review)==canonical_json_bytes(expected),'POLICY_BINDING')
            _deny(before['last_now'] is None or now>=before['last_now'],'CLOCK_UNSAFE')
            state=_plain(before)
            state.update(epoch=before['epoch']+1,money_policy={'schema':review['schema'].replace('money-review','money-policy'),
                'limits':review['limits'],'request_id':review['request_id'],'review_digest':review['review_digest']})
            self._budgets(state)
            if authority_check is not None:authority_check()
            self._write(tx,before,state,max(now,before['last_now'] or 0),policy_transition=review)
            return {'readback_only':False,'epoch':state['epoch'],'version':state['version']}
        return self.runner.run(TransactionContext(principal,Capability.MANAGE),apply)

    def start_epoch(self, principal, *, native_capture=None):
        """Explicit Core operator takeover; never automatic at construction."""
        gate = getattr(self.runner, "execution_gate", None)
        with gate.hold() if gate is not None else nullcontext():
            return self._start_epoch_under_execution_gate(principal, native_capture=native_capture)

    def _start_epoch_under_execution_gate(self, principal, *, native_capture=None):
        now=self._now()
        def change(state):
            _deny(state['last_now'] is None or now >= state['last_now'], 'CLOCK_UNSAFE')
            state['epoch']=_amount(state['epoch']+1)
            for circuit in state['circuits'].values():
                if circuit['state'] == 'HALF_OPEN':
                    circuit.update(state='OPEN',opened_at=now,probe=None,successes=0)
            return state['epoch'],True
        if native_capture is not None:
            from runtime.meta_hackathon.native_authority import (
                NativeAccessUse,
                NativeAuthorityCapture,
                NativeCapacityCoreView,
            )
            _deny(type(native_capture) is NativeAuthorityCapture and native_capture.purpose is Capability.MANAGE
                and native_capture.use is NativeAccessUse.CONTROL
                and native_capture._access.foundation.governor is self,'INVALID_GOVERNOR_BINDINGS')
            access=native_capture._access
            self._require(principal,Capability.MANAGE)
            _deny(principal is native_capture.principal,'INVALID_GOVERNOR_BINDINGS')
            def initialize(tx):
                access.require_capture(native_capture,Capability.MANAGE,tx=tx)
                _deny(access.foundation.lifecycle._fence is None,'INVALID_GOVERNOR_BINDINGS')
                before=self._load(tx)
                _deny(before==self._initial(),'STALE_EPOCH')
                NativeCapacityCoreView.read_in_transaction(tx,access.foundation).require_idle()
                state=_plain(before);result,changed=change(state)
                _deny(changed,'GOVERNOR_INTEGRITY')
                self._write(tx,before,state,now)
                access.require_capture(native_capture,Capability.MANAGE,tx=tx)
                return result
            return self.runner.run(TransactionContext(principal,Capability.MANAGE),initialize)
        return self._change(principal,Capability.MANAGE,change,check_clock=False)

    def set_kill(self, principal, active):
        _deny(type(active) is bool,'INVALID_KILL_STATE')
        def change(state):
            changed=state['kill'] != active;state['kill']=active
            return {'kill':active},changed
        return self._change(principal,Capability.MANAGE,change,check_clock=not active)

    def _reserve_state(self,state,request,epoch,now):
        binding=canonical_sha256(request)
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

    def reserve(self, principal, request, epoch):
        self._require(principal,Capability.COMMIT)
        _deny(type(request) is ReservationRequest,'INVALID_RESERVATION_REQUEST')
        request=ReservationRequest(**asdict(request))
        canonical_sha256(request)
        _deny(request.model_id in principal.model_binding_ids,'MODEL_BINDING_DENIED')
        now=self._now()
        def change(state):
            return self._reserve_state(state,request,epoch,now)
        return self._change(principal,Capability.COMMIT,change)
    def _dispatch_state(self,state,request_id,epoch,now):
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

    def dispatch_commit(self, principal, request_id, epoch):
        """Final current-state CAS. Only a newly ACKed marker permits one send.

This bookkeeping permission is not an effect warrant. The existing transport
and human-authority checks must still pass. Do not send after an exception.
"""
        _identity(request_id)
        now=self._now()
        def change(state):
            return self._dispatch_state(state,request_id,epoch,now)
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
        return self._change(principal,Capability.COMMIT,change,reconciliation=True)

    def _unknown_state(self,state,request_id,epoch,evidence_digest,now):
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
        threshold=(state.get('execution_capacity',{}).get('capacity',{}).get(
            'sandbox_exec_failure_threshold',self.policy.failure_threshold)
            if entry['provider_id']=='sandbox-exec' else self.policy.failure_threshold)
        if circuit['state'] == 'HALF_OPEN' or circuit['failures'] >= threshold:
            circuit.update(state='OPEN',opened_at=now,probe=None)
        return entry,True

    def mark_unknown(self, principal, request_id, epoch, evidence_digest):
        _identity(request_id);_digest(evidence_digest)
        now=self._now()
        def change(state):
            return self._unknown_state(state,request_id,epoch,evidence_digest,now)
        return self._change(principal,Capability.COMMIT,change,reconciliation=True)

    def _settle_state(self,state,request_id,epoch,evidence_digest):
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

    def settle(self, principal, request_id, epoch, evidence_digest):
        """Evidence-referenced pessimistic charge of the entire reserved bound.

It never reports task/effect verification, refunds money/risk or authorizes a
retry. Circuit recovery from UNKNOWN is deliberately not treated as success.
"""
        _identity(request_id);_digest(evidence_digest)
        def change(state):
            return self._settle_state(state,request_id,epoch,evidence_digest)
        return self._change(principal,Capability.COMMIT,change,reconciliation=True)

    def submit_job(self,principal,envelope,*,completion=None,sandbox_binding_digest=None):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'submit',envelope=envelope,completion=completion,
                          sandbox_binding_digest=sandbox_binding_digest)

    def claim_job(self,principal,task_id,worker_id,epoch,*,lease_seconds):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'claim',task_id=task_id,worker_id=worker_id,epoch=epoch,lease_seconds=lease_seconds)

    def takeover_job(self,principal,task_id,worker_id,epoch,*,lease_seconds):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'takeover',task_id=task_id,worker_id=worker_id,epoch=epoch,lease_seconds=lease_seconds)

    def renew_job(self,principal,claim,*,lease_seconds):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'renew',claim=claim,lease_seconds=lease_seconds)

    def begin_job(self,principal,claim):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'begin',claim=claim)

    def finish_job(self,principal,claim,response):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'finish',claim=claim,response=response)

    def finish_offline_host_job(self, principal, claim):
        """Settle only the retained required-effect proof; never provider advice."""
        from runtime.mission.jobs import change_job
        return change_job(self, principal, 'finish_offline_host', claim=claim)

    def inspect_job(self,principal,task_id):
        from runtime.mission.jobs import change_job
        return change_job(self,principal,'inspect',task_id=task_id)


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


_register_history_reader('GOVERNOR_STATE', CoreDualGovernor._load_history)

# Capacity initialization already reads job history. Import the original reader
# after governor definitions are complete, before the first SQL transaction.
def _load_original_job_history_reader():
    from runtime.mission import jobs
    return jobs._validated_job_rows


_load_original_job_history_reader()
