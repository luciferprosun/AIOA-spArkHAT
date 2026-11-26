"""One bounded mission facade over existing Core records and P01 READ.

Model output is advisory. No credential loading, owner admission, standalone
database, browser process or paid transport is constructed here.
"""
import hashlib
import json
import os
import threading
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, timedelta
from decimal import Decimal
from enum import Enum

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.browser_agent.chrome_read_adapter import OfflineFixtureRead
from runtime.browser_agent.offline_adapter import (
    FIXTURE_ORIGIN,
    FIXTURE_TEXT,
    FIXTURE_URL,
)
from runtime.core_admission import Capability
from runtime.failure_boundary import RepairBoundaryError, failure_boundary
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.warrant import CoreWarrantLedger, approval_digest
from runtime.providers.exact import CancellationToken
from runtime.providers.meta_model_api import (
    MODEL,
    PROVIDER,
    MetaLiveBinding,
    MetaPlanRequest,
)
from runtime.providers.meta_receipts import MetaReceiptView
from runtime.providers.tool_calling import ToolCall

from .contracts import BrowserTaskV1
from .mission_read_offline import read_operation, run_read_once
from .offline_receipts import (
    MOCK_RESPONSE_SCHEMA,
    BudgetReservation,
    OfflineReceiptLedger,
)
from .provider_offline import build_offline_envelope

KIND = 'aioa.meta.mission.v1'
ACTIVE = frozenset({'PREVIEWED', 'RUNNING', 'LIVE_PENDING_AUTHORIZATION'})


class MissionState(str, Enum):
    PREVIEWED = 'PREVIEWED'
    RUNNING = 'RUNNING'
    OFFLINE_FIXTURE = 'OFFLINE_FIXTURE'
    LIVE_PENDING_AUTHORIZATION = 'LIVE_PENDING_AUTHORIZATION'
    LIVE_VERIFIED = 'LIVE_VERIFIED'
    UNKNOWN = 'UNKNOWN'
    DENIED = 'DENIED'
    STOPPED = 'STOPPED'
    BLOCKED = 'BLOCKED'


TRANSITIONS = {'PREVIEWED': {'RUNNING', 'UNKNOWN', 'DENIED', 'STOPPED'},
               'RUNNING': {'OFFLINE_FIXTURE', 'UNKNOWN', 'STOPPED', 'BLOCKED'},
               'LIVE_PENDING_AUTHORIZATION': {'RUNNING', 'UNKNOWN', 'DENIED', 'STOPPED'}}


class MissionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code='META_MISSION_DENIED'):
    if not value: raise MissionError(code)


def plain(value): return json.loads(canonical_json_bytes(value))
def utc(value): return value.astimezone(UTC).isoformat().replace('+00:00', 'Z')


@dataclass(frozen=True)
class MissionRequest:
    instruction: str
    mode: str
    target_url: str

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == {'instruction', 'mode', 'target_url'})
        require(type(value['instruction']) is str and 1 <= len(value['instruction'].encode()) <= 2000)
        require(value['mode'] in ('OFFLINE_FIXTURE', 'LIVE') and value['target_url'] == FIXTURE_URL)
        return cls(**value)


def make_mock_receipt(task, correlation_id, now):
    """Existing receipt ledger with 0 USD; never a substitute for a LIVE result."""
    envelope = build_offline_envelope(task, 'Bounded offline task', budget_usd_limit=0.0)
    reservation = BudgetReservation(task.digest, task.owner_scope_digest, task.source_sha, MODEL,
        correlation_id, canonical_sha256(correlation_id), utc(now), utc(now+timedelta(minutes=2)), 512, '0.00')
    raw = {'schema': MOCK_RESPONSE_SCHEMA, 'model': MODEL, 'task_digest': task.digest,
        'owner_scope_digest': task.owner_scope_digest, 'source_sha': task.source_sha,
        'attempt_id': correlation_id, 'nonce_sha256': reservation.nonce_sha256,
        'completion_tokens': 0, 'status': 'MOCK_DONE'}
    return OfflineReceiptLedger(max_total_usd='0.00').record_once(reservation, envelope,
        mock_response_json=json.dumps(raw), mock_cost_usd='0.00', now_utc=utc(now))


class MissionService:
    def __init__(self, ledger, manager, browser, source_probe):
        require(type(ledger) is CoreWarrantLedger)
        self.ledger, self.core, self.runner, self.scope = ledger, ledger.core, ledger.runner, ledger.scope
        self.manager, self.browser, self.source_probe = manager, browser, source_probe
        self._lock = threading.RLock()
        self._workers, self._cancels = {}, {}
        self._live_bindings = {}
        self._closed = False
        self._native_foundation = None
        # Pending work is never resumed on restart; old ACKs cannot grant dispatch.
        for row in self._rows():
            if row.payload['state'] in ACTIVE:
                self._change(row.record_id, ACTIVE, 'UNKNOWN', {'error': 'RESTART_READBACK_REQUIRED'})
        from . import agent_operations
        agent_operations.recover(self)
        from . import chat
        chat.initialize(self)

    def bind_chat(self, governor, authority_probe, **context_binding):
        self._native_execution_gate()
        from . import chat
        return chat.bind(self,governor,authority_probe,**context_binding)

    def chat_propose(self, payload, reader, **identity):
        self._native_execution_gate()
        from . import chat
        return chat.propose(self,payload,reader,**identity)

    def chat_request(self, request_id, reader, **scope):
        from . import chat
        return chat.request(self,request_id,reader,**scope)

    def chat_threads(self, reader, **scope):
        from . import chat
        return chat.threads(self,reader,**scope)

    def chat_thread(self, thread_id, reader, **scope):
        from . import chat
        return chat.thread(self,thread_id,reader,**scope)

    def chat_review(self, request_id, reader):
        from . import chat
        return chat.review(self,request_id,reader)

    def chat_approve(self, request_id, review_digest, owner_principal):
        self._native_execution_gate()
        from . import chat
        return chat.approve(self,request_id,review_digest,owner_principal)

    def chat_stop(self, request_id, reader, **scope):
        from . import chat
        return chat.stop(self,request_id,reader,**scope)

    def bind_agent_tools(self, config, owner_principal):
        self._native_execution_gate()
        from . import agent_operations
        return agent_operations.bind_tools(self, config, owner_principal)

    def propose_agent(self, payload, reader, *, device_id='local-host'):
        self._native_execution_gate()
        from . import agent_operations
        return agent_operations.propose(self, payload, reader, device_id=device_id)

    def run_agent(self, task_id, preview_digest, owner_principal):
        from . import agent_operations
        return agent_operations.run(self, task_id, preview_digest, owner_principal)

    def propose_git(self, source_task_id, request_id, reader, *, device_id='local-host'):
        self._native_execution_gate()
        from . import agent_operations
        return agent_operations.propose_git(self, source_task_id, request_id, reader, device_id=device_id)

    def propose_install(self, payload, request_id, reader, *, device_id='local-host'):
        self._native_execution_gate()
        from . import agent_operations
        return agent_operations.propose_install(self, payload, request_id, reader, device_id=device_id)

    def agent_view(self, task_id, reader):
        from . import agent_operations
        return agent_operations.view(self, task_id, reader)

    def agent_stop(self, task_id, reader):
        from . import agent_operations
        return agent_operations.stop(self, task_id, reader)

    def agent_proposal_readback(self, request_id, reader):
        from . import agent_operations
        return agent_operations.proposal_readback(self, request_id, reader)

    def reconcile_agent(self, task_id, reader):
        from . import agent_operations
        return agent_operations.reconcile(self, task_id, reader)

    def provider_catalog(self, reader):
        self.core.require(reader, Capability.READ, scope=self.scope)
        rows=sorted(self._rows(),key=lambda row:row.payload.get('created_order',0),reverse=True)
        last=next((row for row in rows if row.payload.get('mode')=='OFFLINE_FIXTURE'
                   and row.payload.get('provider_receipt') is not None),None)
        invocation=None if last is None else {'task_id':last.record_id,'task_digest':last.payload['task_digest'],
            'source_sha':last.payload['source_sha'],'capsule_digest':last.payload['capsule_digest'],
            'provider_id':PROVIDER,'model_id':MODEL,'mode':'OFFLINE_FIXTURE','live_verified':False,
            'receipt_sha256':canonical_sha256(last.payload['provider_receipt'])}
        return self.manager.unified_catalog(receipt_view=MetaReceiptView(self.ledger,source_reader=self.source_probe),
                                            last_fixture_invocation=invocation)

    def _native_execution_gate(self):
        if self._native_foundation is not None:self._native_foundation.lifecycle.require_execution()

    def _prepare_native_worker(self,identity,kind,args,*,cancel=None):
        """Closed actual producers publish identical thread/token before SQL."""
        from .native_authority import NativeOwnedWorkHandle
        cancel=cancel or CancellationToken();done=threading.Event()
        foundation=self._native_foundation
        broker=None
        if foundation is not None and kind=='AGENT':
            from .agent_operations import _local_binding
            _,_,broker=_local_binding(self,args[0])
        handle=None
        work_context=(*args,self.manager,self.manager._meta_provider) if kind=='MISSION_LIVE' else args
        def invoke():
            returned=False
            try:
                with failure_boundary('NATIVE_WORKER_CALLBACK_FAILED'):
                    if kind=='MISSION_LIVE':
                        require(self.manager is work_context[3] and self.manager._meta_provider is work_context[4],
                                'NATIVE_WORK_BINDING')
                        self._execute_live(*args,cancel)
                    elif kind=='MISSION_OFFLINE':
                        record,task,call,warrant,now=args
                        self._execute(record,task,call,warrant,cancel,now)
                    elif kind=='AGENT':
                        from . import agent_operations
                        agent_operations._execute(self,*args,cancel)
                    elif kind=='GITHUB_PENDING':
                        from . import github_write
                        slot=args[0]
                        github_write._worker(slot['host'],slot['data'],slot['warrant'],cancel,reconcile=slot['reconcile'])
                    elif kind=='GITHUB':
                        from . import github_write
                        host,data,warrant,reconcile=args
                        github_write._worker(host,data,warrant,cancel,reconcile=reconcile)
                returned=True
            except (ValueError,RepairBoundaryError):
                pass  # Fixed boundary text only; no callback/credential text escapes.
            finally:
                if handle is not None:
                    if returned:
                        with foundation.lifecycle.lock:
                            require(foundation.lifecycle._handles.get(identity) is handle,'NATIVE_WORK_REQUIRED')
                            marker=(threading.current_thread(),done,os.getpid(),kind)
                            handle.returned=(*marker,work_context) if kind=='MISSION_LIVE' else marker
                    else:foundation.lifecycle.quarantine(handle)
                done.set()
        require(kind in ('MISSION_LIVE','MISSION_OFFLINE','AGENT','GITHUB','GITHUB_PENDING'),'NATIVE_PRODUCER_REQUIRED')
        thread=threading.Thread(target=invoke,daemon=True)
        if foundation is not None:
            role='NATIVE_GITHUB' if kind in ('GITHUB','GITHUB_PENDING') else 'LEGACY_MISSION'
            producer=foundation.owner if kind in ('GITHUB','GITHUB_PENDING') else self
            with foundation.lifecycle.lock:
                handle=foundation.lifecycle.begin_work(producer,role,identity,cancel,thread,done)
                require(type(handle) is NativeOwnedWorkHandle,'NATIVE_WORK_REQUIRED')
                handle.kind=kind;handle.context=work_context
                handle.broker=broker
                if kind=='AGENT':handle.target=args[0]['approval_payload']['operation']['target_fingerprint']
                elif kind=='GITHUB_PENDING':handle.target=args[0]['data']['operation']['target_fingerprint']
                self._cancels[identity]=cancel;self._workers[identity]=thread
        return cancel,thread,handle

    def _start_native_worker(self,thread,handle):
        if handle is not None:self._native_foundation.lifecycle.before_start(handle)
        thread.start()  # No lifecycle lock remains held.

    def _native_operation_snapshot(self,handle):
        """Original returned worker + actual join + exact same-Core retained joins."""
        from lab.archaioa.warrant import EffectWarrant
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        from runtime.mission.tools import CoreToolRoute
        from runtime.mobile_gateway.service import SCHEMA

        from . import agent_operations, github_write
        from .native_authority import NativeOwnedWorkHandle
        foundation=self._native_foundation
        require(type(handle) is NativeOwnedWorkHandle and handle.foundation is foundation,'NATIVE_WORK_REQUIRED')
        returned=handle.returned
        if (type(returned) is not tuple or len(returned)!=4 or returned[0] is not handle.thread
                or returned[1] is not handle.done or returned[2]!=os.getpid() or returned[3]!=handle.kind
                or not handle.started or not handle.done.is_set() or handle.thread is threading.current_thread()
                or handle.thread.ident is None or handle.quarantined):return None
        try:
            with foundation.lifecycle.lock:
                require(foundation.lifecycle._handles.get(handle.task_id) is handle
                    and self._workers.get(handle.task_id) is handle.thread
                    and self._cancels.get(handle.task_id) is handle.cancel,'NATIVE_WORK_BINDING')
            handle.thread.join(timeout=0)
            if handle.thread.is_alive():return None
            if handle.kind=='AGENT':
                data,warrant=handle.context
                require(handle.producer is self and handle.role=='LEGACY_MISSION' and data['task_id']==handle.task_id
                        and self.agent_journal is foundation.intent_journal and self.agent_governor is foundation.governor,
                        'NATIVE_WORK_BINDING')
                route=self._agent_routes[data['config_ref']];broker=self._agent_brokers[data['config_ref']]
                require(type(route) is CoreToolRoute and route.journal is foundation.intent_journal
                        and type(broker) is LinuxSandboxBroker and broker is handle.broker
                        and broker._active_cancel is None and broker._quarantined is False,'NATIVE_CLEANUP_UNPROVEN')
                operation=data['approval_payload']['operation'];key=handle.task_id;schema=agent_operations.KIND
                fields=('task_id','task_digest','preview_digest','source_sha','capsule_digest','config_ref')
            elif handle.kind=='GITHUB_PENDING':
                slot=handle.context[0];data,warrant=slot['data'],slot['warrant']
                require(slot['host'] is foundation.owner and slot['reconcile'] is False
                        and handle.producer is foundation.owner and handle.role=='NATIVE_GITHUB'
                        and handle.task_id=='github-'+data['operation_id'],'NATIVE_WORK_BINDING')
                operation=data['operation'];key='native-github-'+data['operation_id'];schema=SCHEMA
                fields=('operation_id','source_chat_request_id','source_reply_sha256','source_sha','capsule_digest','core_instance_id','review_digest')
            else:return None
            require(type(warrant) is EffectWarrant and warrant.task_id==handle.task_id
                    and warrant.operation_hash=='sha256:'+canonical_sha256(operation)
                    and handle.target==operation['target_fingerprint'],'NATIVE_WORK_BINDING')
            def read(tx):
                if handle.kind=='GITHUB_PENDING':github_write.retained_in_transaction(tx)
                row=tx.get(RecordKind.OPERATION,key)
                require(row is not None and row.payload.get('schema')==schema,'NATIVE_WORK_BINDING')
                row.verify();value=plain(row.payload)
                require(all(type(value.get(name)) is type(data[name]) and value.get(name)==data[name] for name in fields)
                        and type(value.get('warrant')) is dict
                        and EffectWarrant.from_dict(value['warrant']).digest()==warrant.digest(),'NATIVE_WORK_BINDING')
                _,_,active=self.ledger._load(tx,warrant)
                require(active.digest()==warrant.digest(),'NATIVE_WORK_BINDING')
                _,intent=foundation.intent_journal._load(tx,warrant)
                require(intent is not None and canonical_sha256(intent['operation'])==canonical_sha256(operation),'NATIVE_INTENT_REQUIRED')
                return row,value,plain(intent),warrant
            return self._run(Capability.READ,read)
        except (ValueError,MemoryPatchError,OSError,RuntimeError,KeyError,TypeError,AttributeError):return None

    def _native_retirement_observation(self,handle):
        """Join and canonical evidence are observed outside every lifecycle lock."""
        from runtime.memory_patch.errors import MemoryPatchError

        from .native_authority import NativeOwnedWorkHandle
        require(type(handle) is NativeOwnedWorkHandle and handle.foundation is self._native_foundation,
                'NATIVE_WORK_REQUIRED')
        returned=handle.returned
        if handle.kind=='MISSION_LIVE':return self._native_live_retirement_observation(handle)
        if handle.kind in ('AGENT','GITHUB_PENDING'):
            snapshot=self._native_operation_snapshot(handle)
            if snapshot is None:return None
            row,value,intent,warrant=snapshot
            resolution=intent.get('resolution')
            if type(resolution) is not dict or resolution.get('outcome',{}).get('contract_type')!='Applied':return None
            if handle.kind=='AGENT':
                receipt=value.get('receipt')
                if (value.get('state')!='AGENT_COMPLETED' or type(receipt) is not dict
                        or receipt.get('schema')!='aioa.agent.local-receipt.v2'
                        or receipt.get('task_id')!=handle.task_id or receipt.get('warrant_digest')!=warrant.digest()
                        or receipt.get('operation_digest')!=warrant.operation_hash
                        or receipt.get('local_readback_verified') is not True or receipt.get('model_invoked') is not False
                        or receipt.get('mode')!='OFFLINE_FIXTURE' or receipt.get('resolution',{}).get('outcome')!=resolution['outcome']
                        or handle.broker._active_cancel is not None or handle.broker._quarantined is not False):return None
            elif value.get('state')!='GITHUB_VERIFIED':return None
            return (returned,handle.thread,handle.cancel,handle.done,row.payload_digest,row.revision,handle.broker,handle.target)
        if (handle.producer is not self or handle.role!='LEGACY_MISSION' or handle.kind!='MISSION_OFFLINE'
                or type(returned) is not tuple or len(returned)!=4 or returned[0] is not handle.thread
                or returned[1] is not handle.done or returned[2]!=os.getpid() or returned[3]!=handle.kind
                or not handle.started or not handle.done.is_set() or handle.thread is threading.current_thread()
                or handle.thread.ident is None or handle.quarantined):return None
        try:
            handle.thread.join(timeout=0)
            if handle.thread.is_alive():return None
            record,_,_,warrant,_=handle.context
            require(record['task_id']==handle.task_id and warrant.task_id==handle.task_id,'NATIVE_WORK_BINDING')
            row=self._get(handle.task_id);row.verify();value=plain(row.payload)
            require(value['state']=='OFFLINE_FIXTURE' and value.get('warrant_digest')==warrant.digest()
                    and value.get('task_id')==handle.task_id and type(value.get('result')) is dict
                    and value['result'].get('status')=='OFFLINE_LINKED_UNVERIFIED'
                    and type(value.get('browser_receipt')) is dict,'NATIVE_WORK_NOT_SETTLED')
        except (ValueError,MemoryPatchError,OSError,RuntimeError):return None
        return (returned,handle.thread,handle.cancel,handle.done,row.payload_digest,row.revision,'MISSION_RETURN_JOIN')

    def _native_live_retirement_observation(self,handle):
        """Original plan worker, canonical ACK/consumption and charged spend only.

        A provider receipt is advisory. Only the same Core's completed attempt,
        exact receipt and evidence-linked COMMITTED reservation prove settlement;
        this READ never settles, refunds, consumes, dispatches or grants a retry.
        """
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.mission.governor import ReservationRequest
        from runtime.providers.meta_model_api import ProviderPlan, spend_operation
        from runtime.providers.meta_receipts import KIND as ATTEMPT_KIND
        from runtime.providers.meta_receipts import cost
        from runtime.providers.tool_calling import strict_json

        from .contracts import utc_timestamp
        from .native_authority import NativeAccessUse
        foundation=self._native_foundation;capture=None
        try:
            returned,context=handle.returned,handle.context
            require(handle.producer is self and handle.role=='LEGACY_MISSION' and handle.kind=='MISSION_LIVE'
                and type(context) is tuple and len(context)==5 and type(returned) is tuple and len(returned)==5
                and returned[0] is handle.thread and returned[1] is handle.done and returned[2]==os.getpid()
                and returned[3]==handle.kind and returned[4] is context and handle.started and handle.done.is_set()
                and handle.thread is not threading.current_thread() and handle.thread.ident is not None
                and not handle.quarantined,'NATIVE_WORK_BINDING')
            with foundation.lifecycle.lock:
                require(foundation.lifecycle._handles.get(handle.task_id) is handle
                    and self._workers.get(handle.task_id) is handle.thread
                    and self._cancels.get(handle.task_id) is handle.cancel,'NATIVE_WORK_BINDING')
            handle.thread.join(timeout=0)
            if handle.thread.is_alive():return None
            record,request,binding,manager,provider=context
            require(type(record) is dict and type(request) is MetaPlanRequest and type(binding) is MetaLiveBinding
                and type(binding.warrant) is EffectWarrant and type(binding.reservation) is ReservationRequest
                and type(handle.cancel) is CancellationToken and binding.ledger is self.ledger is foundation.ledger
                and binding.governor is foundation.governor and self.manager is manager
                and manager._meta_provider is provider and provider.mode=='LIVE' and provider._active_attempt_id is None
                and binding.session_dispatch is False,'NATIVE_WORK_BINDING')
            with handle.cancel._lock:
                require(handle.cancel._connection is None and handle.cancel._socket is None,'NATIVE_CLEANUP_UNPROVEN')
            capture=foundation.access.capture(Capability.READ,use=NativeAccessUse.READ)
            source=self.source_probe()
            public=request.public_binding();warrant=binding.warrant;reservation=binding.reservation
            operation=spend_operation(request.digest,public)
            require(source==foundation.owner.source==(request.task.source_sha,request.capsule_digest)
                and binding.source_reader()==source and record['task_id']==request.task.task_id==handle.task_id
                and record['task']==request.task.to_dict() and record['task_digest']==request.task.digest
                and record['mode']=='LIVE' and record['state']=='LIVE_PENDING_AUTHORIZATION'
                and record['native_spend_binding']=='BOUND' and record['provider_request_digest']==request.digest
                and record['correlation_id']==request.correlation_id and record['capsule_digest']==request.capsule_digest
                and record['instruction_sha256']==hashlib.sha256(request.instruction.encode()).hexdigest()
                and record['owner_scope_digest']==request.task.owner_scope_digest==canonical_sha256(self.scope)
                and record['provider_id']==public['provider_id'] and record['model_id']==public['model_id']
                and public['model_id'] in capture.principal.model_binding_ids
                and binding.principal.actor_session_id==capture.principal.actor_session_id==foundation.owner.instance_id
                and binding.principal.assignment_revision==capture.principal.assignment_revision,'NATIVE_WORK_BINDING')
            self.core.require(binding.principal,Capability.COMMIT,scope=self.scope)
            self.ledger._check(warrant)
            require(warrant.task_id==handle.task_id and warrant.operation_class==operation['operation_class']
                and warrant.operation_hash=='sha256:'+canonical_sha256(operation)
                and warrant.target_fingerprint==operation['target_fingerprint']
                and warrant.expected_target_revision==request.task.source_sha and warrant.owner_scope==request.task.owner_scope_digest
                and warrant.money_reservation_id==warrant.risk_reservation_id==reservation.request_id
                and reservation.task_id==handle.task_id and reservation.provider_id==public['provider_id']
                and reservation.model_id==public['model_id'] and reservation.request_digest==canonical_sha256(operation)
                and public['model_id'] in binding.principal.model_binding_ids
                and warrant.authority_scope.monetary_ceiling.currency=='USD'
                and request.estimate()*10**9<=reservation.money_nano<=Decimal(request.budget_usd)*10**9<=50000000
                and 0<reservation.money_nano<=warrant.authority_scope.monetary_ceiling.amount*10**9
                and reservation.risk_units>0 and self.ledger.clock()<utc_timestamp(request.task.deadline_utc),
                'NATIVE_WORK_BINDING')
            def read(tx):
                foundation.access.require_capture(capture,Capability.READ,tx=tx)
                row=tx.get(RecordKind.OPERATION,handle.task_id)
                attempt=tx.get(RecordKind.OPERATION,'meta-api-attempt-'+request.digest)
                receipt=tx.get(RecordKind.RECEIPT,'meta-api-'+request.digest)
                require(row is not None and attempt is not None and receipt is not None,'NATIVE_CLEANUP_UNPROVEN')
                for retained in (row,attempt,receipt):
                    retained.verify();require(retained.scope==self.scope,'NATIVE_WORK_BINDING')
                value=plain(row.payload);data=plain(attempt.payload);proof=plain(receipt.payload)
                mutable={'state','stopped','native_spend_binding','error','proposal','provider_receipt'}
                require(set(value)==set(record) and all(value[k]==v for k,v in record.items() if k not in mutable)
                    and value['schema']==KIND and value['state'] in ('BLOCKED','STOPPED')
                    and value['stopped'] is (value['state']=='STOPPED') and value['stopped'] is handle.cancel.cancelled
                    and value['native_spend_binding']=='CONSUMED' and value['error']=='CHROME_LIVE_BLOCKED_CONTAINMENT'
                    and value['result'] is None and value['browser_receipt'] is None
                    and value['verified'] is False and value['live_verified'] is False and value['dispatch_allowed'] is False,
                    'NATIVE_WORK_NOT_SETTLED')
                raw=value['proposal'];call=ToolCall(raw['id'],raw['function']['name'],raw['function']['arguments']);call.validate()
                require(call.to_wire()==raw and call.name=='navigate_read'
                    and strict_json(call.arguments_json)==request.plan_fields(),'NATIVE_WORK_BINDING')
                approved,approval,active=self.ledger._load_unrevoked(tx,warrant);approved.verify()
                witness=tx.get(RecordKind.APPROVAL,self.ledger._key(warrant))
                require(witness is not None,'NATIVE_WORK_BINDING');witness.verify()
                require(active==warrant and approval['consumption']==self.ledger._receipt(warrant)
                    and witness.scope==self.scope and witness.payload.get('revoked') is False
                    and witness.payload.get('session_id')==capture.principal.actor_session_id
                    and witness.payload.get('assignment_revision')==capture.assignment_revision,'NATIVE_WORK_BINDING')
                expected={'schema':ATTEMPT_KIND,'state':ATTEMPT_KIND+':COMPLETED',
                    'attempt_id':'meta-api-attempt-'+request.digest,'attempt':1,'request_digest':request.digest,'binding':public,
                    'policy_epoch':warrant.lease_epoch,'warrant_digest':warrant.digest(),'nonce_digest':canonical_sha256(warrant.nonce),
                    'approval_record_id':self.ledger._key(warrant),'operation_digest':reservation.request_digest,
                    'reservation_id':reservation.request_id,'input_bound':public['input_token_bound'],
                    'output_bound':request.max_output_tokens,'cost_estimate':str(request.estimate()),'settled_cost':None,
                    'http_status':200,'error_code':None,'created_at':data['created_at'],'sequence':data['sequence']}
                require(canonical_json_bytes(data)==canonical_json_bytes(expected) and attempt.revision==3 and receipt.revision==1
                    and type(data['sequence']) is int and 1<=data['sequence']<=1023
                    and warrant.issued_at<=utc_timestamp(data['created_at'])<warrant.expires_at,'NATIVE_WORK_BINDING')
                usage=proof['usage']
                require(type(usage) is dict and set(usage)=={'prompt_tokens','completion_tokens','total_tokens'}
                    and all(type(n) is int and n>=0 for n in usage.values())
                    and usage['total_tokens']==usage['prompt_tokens']+usage['completion_tokens']
                    and usage['prompt_tokens']<=public['input_token_bound'] and usage['completion_tokens']<=request.max_output_tokens,
                    'NATIVE_WORK_BINDING')
                from runtime.providers.meta_model_api import INPUT_PRICE, OUTPUT_PRICE
                require(cost(proof['cost_estimate_usd'])==(Decimal(usage['prompt_tokens'])*INPUT_PRICE
                    +Decimal(usage['completion_tokens'])*OUTPUT_PRICE)/1000000,'NATIVE_WORK_BINDING')
                canonical=ProviderPlan(call,request.digest,usage,'META_API_LIVE_VERIFIED',proof['cost_estimate_usd'],
                    provider_id=public['provider_id'],model_id=public['model_id'],live_verified=True,binding=public).receipt()
                canonical.update(attempt_id=data['attempt_id'],attempt=1,policy_epoch=warrant.lease_epoch,
                    warrant_digest=warrant.digest(),nonce_digest=canonical_sha256(warrant.nonce))
                require(canonical_json_bytes(proof)==canonical_json_bytes(canonical)==canonical_json_bytes(value['provider_receipt']),
                    'NATIVE_WORK_BINDING')
                state=binding.governor._load(tx);entry=state['reservations'].get(reservation.request_id)
                require(state['epoch']==warrant.lease_epoch and state['kill'] is False and entry is not None
                    and all(entry[k]==getattr(reservation,k) for k in ReservationRequest.__dataclass_fields__)
                    and entry['state']=='COMMITTED' and entry['evidence_digest']==canonical_sha256(proof),
                    'NATIVE_WORK_NOT_SETTLED')
                foundation.access.require_capture(capture,Capability.READ,tx=tx)
                return (row.payload_digest,row.revision,attempt.payload_digest,receipt.payload_digest,
                    approved.payload_digest,canonical_sha256(state))
            observed=self.runner.run(TransactionContext(capture.principal,Capability.READ),read)
            foundation.access.require_capture(capture,Capability.READ)
            require(handle.returned is returned and handle.context is context and self.manager is manager
                and manager._meta_provider is provider and provider._active_attempt_id is None,'NATIVE_WORK_BINDING')
            with handle.cancel._lock:
                require(handle.cancel._connection is None and handle.cancel._socket is None,'NATIVE_CLEANUP_UNPROVEN')
            return (returned,handle.thread,handle.cancel,handle.done,*observed,'MISSION_LIVE_RETURN_JOIN')
        except (ValueError,MemoryPatchError,OSError,RuntimeError,KeyError,TypeError,AttributeError):return None
        finally:
            if capture is not None:capture.close()

    def _retire_native_workers(self):
        foundation=self._native_foundation
        if foundation is None:return
        with foundation.lifecycle.lock:
            handles=tuple(handle for handle in foundation.lifecycle._handles.values() if not handle.synchronous)
        for handle in handles:foundation.lifecycle.retire_work(handle)

    @contextmanager
    def _native_synchronous(self,identity,kind):
        foundation=self._native_foundation
        if foundation is None:
            yield None
            return
        from .native_authority import NativePhase, deny
        lifecycle=foundation.lifecycle
        parent=None
        if kind in ('AGENT_SETTLEMENT','GITHUB_SETTLEMENT'):
            with lifecycle.lock:
                parent=lifecycle._handles.get(identity)
                role='LEGACY_MISSION' if kind=='AGENT_SETTLEMENT' else 'NATIVE_GITHUB'
                producer=self if kind=='AGENT_SETTLEMENT' else foundation.owner
                deny(parent is not None and parent.producer is producer and parent.role==role and parent.foundation is foundation
                     and not parent.synchronous and not parent.quarantined
                     and lifecycle.phase in (NativePhase.CAPACITY_ADMIN,NativePhase.ACTIVE) and lifecycle._fence is None)
        elif kind == 'WORKER_MODEL_CALL':
            lifecycle.require_execution()
            role,producer='LEGACY_MISSION',self
        else:
            deny(kind in ('GITHUB_PREFLIGHT','GITHUB_CONTROL'))
            lifecycle.require_execution()
            role,producer='NATIVE_GITHUB',foundation.owner
        token=parent.cancel if parent is not None else CancellationToken()
        handle=lifecycle.begin_synchronous(producer,role,'sync-'+kind.lower()+'-'+identity,token,parent=parent)
        handle.kind=kind
        if parent is not None:lifecycle._boundary.settlement_handle=handle
        try:
            if parent is not None:deny(self._native_operation_snapshot(parent) is not None)
            yield handle
        except BaseException:
            lifecycle.quarantine(handle)
            raise
        else:
            lifecycle.complete_synchronous(handle)
        finally:
            handle.done.set()
            if parent is not None:del lifecycle._boundary.settlement_handle
        if parent is not None:self._retire_native_workers()

    def retained_in_transaction(self,tx):
        rows=tx.scan(RecordKind.OPERATION,limit=1024,states=tuple(state.value for state in MissionState))
        require(len(rows)<1024,'META_MISSION_HISTORY_LIMIT')
        selected=tuple(row for row in rows if row.payload.get('schema')==KIND)
        for row in selected:
            require(row.record_id==row.payload.get('task_id') and row.payload.get('state') in {state.value for state in MissionState},
                    'META_MISSION_INTEGRITY')
        return selected

    def _run(self, purpose, callback):
        foundation=self._native_foundation
        if foundation is not None and getattr(foundation.lifecycle._boundary,'settlement_handle',None) is not None:
            from .native_authority import NativeAccessUse
            capture=foundation.access.capture(purpose,use=NativeAccessUse.SETTLEMENT)
            try:
                def guarded(tx):
                    foundation.access.require_capture(capture,purpose,tx=tx)
                    result=callback(tx)
                    foundation.access.require_capture(capture,purpose,tx=tx)
                    return result
                return self.runner.run(TransactionContext(capture.principal,purpose),guarded)
            finally:capture.close()
        principal = self.core.local_operator(purpose)
        return self.runner.run(TransactionContext(principal, purpose), callback)

    def _rows(self):
        def read(tx):
            # The existing port applies state filtering before LIMIT. Warrant
            # rows must not crowd missions out of active/restart checks.
            rows = tx.scan(RecordKind.OPERATION, limit=1024, states=tuple(state.value for state in MissionState))
            require(len(rows) < 1024, 'META_MISSION_HISTORY_LIMIT')
            return tuple(row for row in rows if row.payload.get('schema') == KIND)
        return self._run(Capability.READ, read)

    def _get(self, identity):
        require(type(identity) is str and identity.startswith('meta-') and len(identity) <= 80)
        row = self._run(Capability.READ, lambda tx: tx.get(RecordKind.OPERATION, identity))
        require(row is not None and row.payload.get('schema') == KIND, 'META_MISSION_NOT_FOUND')
        return row

    def _change(self, identity, allowed, state, updates=None):
        def change(tx):
            row = tx.get(RecordKind.OPERATION, identity)
            require(row is not None and row.payload.get('schema') == KIND, 'META_MISSION_NOT_FOUND')
            data = plain(row.payload)
            if data['state'] not in allowed: return data
            require(state in TRANSITIONS.get(data['state'], ()), 'META_STATE_TRANSITION_DENIED')
            MissionState(state)
            data.update(updates or {}, state=state)
            tx.replace(StoredRecord(RecordKind.OPERATION, identity, self.scope, row.revision+1, data),
                       expected_revision=row.revision)
            return data
        return self._run(Capability.COMMIT, change)

    def preview(self, payload, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        request = MissionRequest.parse(payload)
        with self._lock:
            require(not self._closed, 'META_SERVICE_CLOSED')
            require(not any(row.payload['state'] in ACTIVE for row in self._rows()), 'META_MISSION_ACTIVE')
            now = self.ledger.clock(); sha, capsule = self.source_probe()
            identity, correlation = 'meta-'+uuid.uuid4().hex, 'meta-corr-'+uuid.uuid4().hex
            task = BrowserTaskV1(task_id=identity, owner_scope_digest=canonical_sha256(self.scope),
                source_sha=sha, allowed_origins=(FIXTURE_ORIGIN,), target_url=FIXTURE_URL,
                deadline_utc=utc(now+timedelta(minutes=2)), operation='navigate_read',
                max_pages=1, timeout_ms=8000, max_chars=1600)
            record = {'schema': KIND, 'task_id': identity, 'task_digest': task.digest,
                'owner_scope_digest': task.owner_scope_digest, 'source_sha': sha,
                'capsule_digest': capsule, 'provider_id': PROVIDER, 'model_id': MODEL,
                'deadline': task.deadline_utc, 'budget_usd': '0', 'allowed_origins': list(task.allowed_origins),
                'correlation_id': correlation, 'stopped': False, 'mode': request.mode,
                'state': 'LIVE_PENDING_AUTHORIZATION' if request.mode == 'LIVE' else 'PREVIEWED',
                'created_at': utc(now), 'created_order': int(now.timestamp()*1000000),
                'verified': False, 'live_verified': False, 'dispatch_allowed': False,
                'task': task.to_dict(), 'instruction_sha256': hashlib.sha256(request.instruction.encode()).hexdigest(),
                'result': None, 'browser_receipt': None, 'provider_receipt': None, 'error': None}
            if request.mode == 'OFFLINE_FIXTURE':
                proposal = self.manager.generate_meta_plan(MetaPlanRequest(task, request.instruction, correlation,
                                                                          capsule_digest=capsule),
                                                           CancellationToken())
                record['proposal'] = proposal.call.to_wire()
                record['provider_receipt'] = proposal.receipt()
            else:
                record['proposal'] = None
                record['error'] = 'META_API_LIVE_BLOCKED_OWNER_GO'
            record['preview_digest'] = canonical_sha256(record)
            self._run(Capability.COMMIT, lambda tx: tx.insert(StoredRecord(RecordKind.OPERATION,
                                identity, self.scope, 1, record)))
            return plain(record)

    def bind_live_request(self, identity, request, binding):
        """Native host-only port; no HTTP route mints admission or approvals.

        The host brings an exact, already-approved Core operation. This binds
        transport data, never creates authority, a reservation or a warrant.
        """
        self._native_execution_gate()
        require(type(request) is MetaPlanRequest and type(binding) is MetaLiveBinding,
                'META_NATIVE_AUTHORITY_NOT_BOUND')
        require(binding.ledger is self.ledger and self.manager._meta_provider.mode == 'LIVE',
                'META_NATIVE_AUTHORITY_NOT_BOUND')
        with self._lock:
            row = self._get(identity); data = plain(row.payload)
            require(data['state'] == 'LIVE_PENDING_AUTHORIZATION' and identity not in self._live_bindings)
            require(request.task.to_dict() == data['task']
                and request.correlation_id == data['correlation_id']
                and request.capsule_digest == data['capsule_digest']
                and hashlib.sha256(request.instruction.encode()).hexdigest() == data['instruction_sha256'],
                'META_NATIVE_REQUEST_MISMATCH')
            request.payload()
            require(Decimal(0) < Decimal(request.budget_usd) <= Decimal('.05'), 'META_BUDGET_DENIED')
            binding.check(request)  # Stored human approval, epoch, source, exact cost.
            data.update(native_spend_binding='BOUND', budget_usd=request.budget_usd,
                        provider_request_digest=request.digest, error=None)
            data['preview_digest'] = canonical_sha256(data)
            def write(tx):
                tx.replace(StoredRecord(RecordKind.OPERATION, identity, self.scope, row.revision+1, data),
                           expected_revision=row.revision)
            self._run(Capability.COMMIT, write)
            self._live_bindings[identity] = (request, binding)
            return plain(data)

    def _warrant(self, record, operation, now):
        expires = min(now+timedelta(seconds=60), __import__('datetime').datetime.fromisoformat(record['deadline'].replace('Z', '+00:00')))
        scope = AuthorityScope(operation_classes=(operation['operation_class'],),
            target_scope=operation['target_fingerprint'], risk_ceiling=RiskLevel.LOW,
            monetary_ceiling=Money(Decimal(0), 'USD'), not_before=now, expires_at=expires,
            owner_scope=record['owner_scope_digest'], task_scope=record['task_id'])
        warrant = EffectWarrant(warrant_id='warrant-'+record['task_id'], task_id=record['task_id'],
            owner_scope=record['owner_scope_digest'], operation_class=operation['operation_class'],
            operation_hash='sha256:'+canonical_sha256(operation), target_fingerprint=operation['target_fingerprint'],
            expected_target_revision=record['source_sha'], revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((
                EvidenceRef('meta-task', 'task', 'sha256:'+record['task_digest'], 'v1'),
                EvidenceRef('meta-source', 'context', 'sha256:'+record['capsule_digest'], 'v1'),)),
            lease_epoch=0, authority_scope=scope, approval_digest='sha256:'+'0'*64,
            money_reservation_id='NONE', risk_reservation_id='NONE', nonce=record['correlation_id'],
            issued_at=now, expires_at=expires)
        return replace(warrant, approval_digest=approval_digest(warrant))

    def run(self, identity, preview_digest, owner_principal):
        gate = getattr(getattr(self._native_foundation, "runner", None), "execution_gate", None)
        with gate.hold() if gate is not None else nullcontext():
            return self._run_under_execution_gate(identity, preview_digest, owner_principal)

    def _run_under_execution_gate(self, identity, preview_digest, owner_principal):
        self._native_execution_gate()
        self.core.require(owner_principal, Capability.OWNER_APPROVAL, scope=self.scope)
        with self._lock:
            record = plain(self._get(identity).payload)
            if record['state'] == 'LIVE_PENDING_AUTHORIZATION':
                require(identity in self._live_bindings, 'META_API_LIVE_BLOCKED_OWNER_GO')
                require(record['preview_digest'] == preview_digest, 'META_MISSION_NOT_PREVIEWED')
                request, binding = self._live_bindings[identity]
                binding.check(request)
                native=None
                if self._native_foundation is not None:
                    native=self._prepare_native_worker(identity,'MISSION_LIVE',(record,request,binding))
                self._change(identity, {'LIVE_PENDING_AUTHORIZATION'}, 'RUNNING',
                             {'native_spend_binding':'CONSUMING'})
                del self._live_bindings[identity]
                if native is not None:
                    cancel,thread,handle=native
                    self._start_native_worker(thread,handle)
                else:
                    cancel = CancellationToken(); self._cancels[identity] = cancel
                    thread = threading.Thread(target=self._execute_live, args=(record, request, binding, cancel), daemon=True)
                    self._workers[identity] = thread; thread.start()
                return self.evidence(identity, self.core.local_operator(Capability.READ))
            require(record['state'] == 'PREVIEWED' and record['preview_digest'] == preview_digest,
                    'META_MISSION_NOT_PREVIEWED')
            if self.source_probe() != (record['source_sha'], record['capsule_digest']):
                self._change(identity, {'PREVIEWED'}, 'DENIED', {'error': 'META_SOURCE_DRIFT'})
                raise MissionError('META_SOURCE_DRIFT')
            now = self.ledger.clock(); task = BrowserTaskV1.parse(record['task']); raw = record['proposal']
            call = ToolCall(raw['id'], raw['function']['name'], raw['function']['arguments'])
            operation = read_operation(task, call, expected_content_sha256=hashlib.sha256(FIXTURE_TEXT.encode()).hexdigest(), initial_utc=now)
            warrant = self._warrant(record, operation, now)
            native=None
            if self._native_foundation is not None:
                native=self._prepare_native_worker(identity,'MISSION_OFFLINE',(record,task,call,warrant,now))
            try:
                with failure_boundary('OWNED_WORK_CALLBACK_FAILED'):
                    self.ledger.approve(owner_principal, warrant)
                    self._change(identity, {'PREVIEWED'}, 'RUNNING', {'warrant_digest': warrant.digest()})
            except (ValueError, RepairBoundaryError):
                if native is not None:self._native_foundation.lifecycle.quarantine(native[2])
                self._change(identity, {'PREVIEWED', 'RUNNING'}, 'UNKNOWN', {'error': 'META_APPROVAL_ACK_UNKNOWN'})
                raise MissionError('META_APPROVAL_ACK_UNKNOWN') from None
            if native is not None:
                cancel,thread,handle=native
                self._start_native_worker(thread,handle)
            else:
                cancel = CancellationToken(); self._cancels[identity] = cancel
                thread = threading.Thread(target=self._execute, args=(record, task, call, warrant, cancel, now), daemon=True)
                self._workers[identity] = thread; thread.start()
            return self.evidence(identity, self.core.local_operator(Capability.READ))

    def _execute_live(self, record, request, binding, cancel):
        identity = record['task_id']
        try:
            with failure_boundary('OWNED_WORK_CALLBACK_FAILED'):
                plan = self.manager.generate_meta_plan(request, cancel, live_binding=binding)
                diagnostics = self.manager._meta_provider.diagnostics()
                receipt = diagnostics['last_live_receipt']
                require(receipt is not None and receipt['request_digest'] == request.digest,
                        'META_RECEIPT_READBACK_UNKNOWN')
                # A paid plan never authorizes browser dispatch. No fixture result is
                # substituted for LIVE; containment and exact READ authority are separate.
                self._change(identity, {'RUNNING'}, 'STOPPED' if cancel.cancelled else 'BLOCKED',
                    {'provider_receipt':receipt, 'proposal':plan.call.to_wire(), 'stopped':cancel.cancelled,
                     'native_spend_binding':'CONSUMED', 'error':'CHROME_LIVE_BLOCKED_CONTAINMENT'})
        except (ValueError, RepairBoundaryError):
            self._change(identity, {'RUNNING'}, 'STOPPED' if cancel.cancelled else 'UNKNOWN',
                {'stopped':cancel.cancelled, 'native_spend_binding':'NOT_REUSABLE',
                 'error':'META_PROVIDER_READBACK_UNKNOWN'})

    def _execute(self, record, task, call, warrant, cancel, initial):
        identity = record['task_id']
        try:
            with failure_boundary('OWNED_WORK_CALLBACK_FAILED'):
                reader = OfflineFixtureRead(self.browser, cancel, self.ledger.clock,
                    lambda: self.source_probe() == (record['source_sha'], record['capsule_digest']))
                receipt = make_mock_receipt(task, record['correlation_id'], self.ledger.clock())
                result = run_read_once(ledger=self.ledger,
                    read_principal=self.core.local_operator(Capability.READ),
                    commit_principal=self.core.local_operator(Capability.COMMIT), task=task, call=call, warrant=warrant,
                    current_source_sha=self.source_probe()[0], expected_content_sha256=hashlib.sha256(FIXTURE_TEXT.encode()).hexdigest(),
                    initial_utc=initial, provider_receipt=receipt, cancel=cancel, fixture_reader=reader)
                state = 'STOPPED' if cancel.cancelled else ('OFFLINE_FIXTURE' if result['status'] == 'OFFLINE_LINKED_UNVERIFIED' else 'UNKNOWN')
                if reader.last_receipt is not None:
                    reader.last_receipt.update(correlation_id=record['correlation_id'], provider_id=PROVIDER,
                        model_id=MODEL, deadline=record['deadline'], budget_usd='0',
                        allowed_origins=record['allowed_origins'], capsule_digest=record['capsule_digest'],
                        stopped=cancel.cancelled)
                self._change(identity, {'RUNNING'}, state, {'result': result, 'browser_receipt': reader.last_receipt,
                                                           'stopped': cancel.cancelled})
        except (ValueError, RepairBoundaryError):
            self._change(identity, {'RUNNING'}, 'STOPPED' if cancel.cancelled else 'UNKNOWN',
                         {'error': 'META_READBACK_UNKNOWN', 'stopped': cancel.cancelled})

    def evidence(self, identity, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        return plain(self._get(identity).payload)

    def evidence_many(self, identities, principal):
        """One bounded READ snapshot of existing records; no provider or effects."""
        self.core.require(principal, Capability.READ, scope=self.scope)
        require(type(identities) is tuple and 1 <= len(identities) <= 16)
        require(all(type(i) is str and i.startswith('meta-') and len(i) <= 80 for i in identities))
        require(len(set(identities)) == len(identities))
        rows = self._run(Capability.READ, lambda tx: tuple(tx.get(RecordKind.OPERATION, i) for i in identities))
        require(all(row is not None and row.payload.get('schema') == KIND for row in rows), 'META_MISSION_NOT_FOUND')
        return tuple(plain(row.payload) for row in rows)

    def stop(self, identity, principal):
        foundation = self._native_foundation
        gate = getattr(getattr(foundation, "runner", None), "execution_gate", None)
        with gate.hold() if gate is not None else nullcontext():
            return self._stop_under_execution_gate(identity, principal)

    def _stop_under_execution_gate(self, identity, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        with self._lock:
            self._live_bindings.pop(identity, None)
            cancel = self._cancels.get(identity)
            if cancel is not None: cancel.cancel()
            self._get(identity)
            self._change(identity, ACTIVE | {'LIVE_PENDING_AUTHORIZATION'}, 'STOPPED', {'stopped': True})
            return self.evidence(identity, principal)

    def status(self, principal):
        self.core.require(principal, Capability.READ, scope=self.scope)
        rows = sorted(self._rows(), key=lambda row: row.payload.get('created_order', 0))
        provider = self.manager._meta_provider
        view = provider.receipt_view
        require(view is None or view.ledger is self.ledger, 'META_RECEIPT_SCOPE_MISMATCH')
        view = view or MetaReceiptView(self.ledger, source_reader=self.source_probe)
        return {'schema': 'aioa.meta.mission-status.v1',
            'mode': 'OFFLINE_FIXTURE' if provider.mode == 'MOCK' else 'LIVE_PENDING_AUTHORIZATION',
            'provider': provider.diagnostics(receipt_view=view),
            'chrome_live': 'BLOCKED_CONTAINMENT_AND_OWNER_GO', 'active_task_id': next((r.record_id for r in rows if r.payload['state'] in ACTIVE), None),
            'missions': [{'task_id': r.record_id, 'state': r.payload['state'],
                          'created_at': r.payload.get('created_at')} for r in rows],
            'live_verified': False, 'budget_usd': '0'}

    def close(self):
        foundation = self._native_foundation
        gate = getattr(getattr(foundation, "runner", None), "execution_gate", None)
        with gate.hold() if gate is not None else nullcontext():
            self._closed = True
            for cancel in tuple(self._cancels.values()): cancel.cancel()
        for task, thread in tuple(self._workers.items()): thread.join(timeout=12 if task.startswith('agent-') else 2)
