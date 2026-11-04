"""Advisory chat on MissionService's Core port, workers and cancellation map.

Only digests, authority bindings and receipts are durable. Conversation text is
bounded process memory, expires after 15 minutes and is never a knowledge base.
No function in this module authenticates an operator or resolves a credential.
"""
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import re
import threading
import time
import uuid

from lab.archaioa.authority import AuthorityScope,Money,RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant,RevisionPolicy
from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
from runtime.mission.warrant import approval_digest
from runtime.providers.exact import CancellationToken
from runtime.providers.meta_model_api import MetaChatTask,MetaChatRequest,MetaLiveBinding,MetaAPIError,MODEL,PROVIDER,spend_operation
from runtime.providers.meta_receipts import MetaReceiptView
from .mission_service import require,plain,utc
from .contracts import utc_timestamp

KIND='aioa.mission.chat.v1'
STATES=('PENDING_OWNER','RUNNING','SUCCEEDED','FAILED','UNKNOWN','STOPPED')
FILTER=tuple('CHAT_'+s for s in STATES)
TTL=900

def initialize(service):
    service._chat_payloads={};service._chat_results={};service._chat_governor=None
    service._chat_session=None
    service._chat_authority=None;service._chat_context_probe=None;service._chat_credit_probe=None
    for row in _rows(service):
        if row.payload['state'] in ('CHAT_PENDING_OWNER','CHAT_RUNNING'):
            _change(service,row.record_id,('PENDING_OWNER','RUNNING'),'UNKNOWN',{'error':'CHAT_RESTART_READBACK_REQUIRED'})

def bind(service,governor,authority_probe,*,read_context_probe=None,credit_balance_probe=None):
    from runtime.mission.governor import CoreDualGovernor
    require(type(governor) is CoreDualGovernor and governor.core is service.core
        and governor.runner is service.runner and governor.policy.scope==service.scope
        and callable(authority_probe),'CHAT_NATIVE_BINDING_REQUIRED')
    service._chat_governor=governor;service._chat_authority=authority_probe
    require(read_context_probe is None or callable(read_context_probe),'CHAT_CONTEXT_BINDING_REQUIRED')
    service._chat_context_probe=read_context_probe
    require(credit_balance_probe is None or callable(credit_balance_probe),'CHAT_CREDIT_BINDING_REQUIRED')
    service._chat_credit_probe=credit_balance_probe

def budget_status(service,reader):
    governor=service._chat_governor;require(governor is not None,'CHAT_NOT_CONFIGURED');state=governor.inspect(reader)
    limits=state.get('money_policy',{}).get('limits',{})
    cap=limits.get('task_limit',governor.policy.task_limit.money_nano)
    total=limits.get('global_limit',governor.policy.global_limit.money_nano)
    credit_ready=callable(service._chat_credit_probe) and service._chat_credit_probe(None) is True
    return {'max_budget_usd':None if cap is None else format(Decimal(cap)/10**9,'f'),
        'allocation_usd':None if total is None else format(Decimal(total)/10**9,'f'),
        'local_exposure_usd':format(Decimal(state['exposure']['global']['money_nano'])/10**9,'f'),
        'provider_balance_status':'OWNER_ATTESTED' if credit_ready else 'UNVERIFIED',
        'credit_only':state.get('money_policy',{}).get('schema')=='aioa.governor.money-policy.v2',
        'credit_binding_available':credit_ready}

def _check_context(service,req):
    context=json.loads(req.context_json).get('read_context')
    if context is not None:
        require(callable(service._chat_context_probe),'CHAT_CONTEXT_NOT_BOUND')
        require(service._chat_context_probe(context['request_id'])==context,'CHAT_CONTEXT_CHANGED')

def _id(value):require(type(value) is str and re.fullmatch('[0-9a-f]{32}',value),'CHAT_ID_INVALID');return value
def _device(value):require(type(value) is str and re.fullmatch('[0-9a-f]{64}',value),'CHAT_DEVICE_INVALID');return value
def _rows(service):
    def read(tx):
        rows=tx.scan(RecordKind.OPERATION,limit=1024,states=FILTER)
        require(len(rows)<1024,'CHAT_HISTORY_LIMIT')
        return tuple(r for r in rows if r.payload.get('schema')==KIND)
    return service._run(Capability.READ,read)
def _get(service,request_id,device_id=None):
    row=service._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,'chat-'+_id(request_id)))
    require(row is not None and row.payload.get('schema')==KIND,'CHAT_NOT_FOUND')
    require(device_id is None or row.payload['device_id']==_device(device_id),'CHAT_NOT_FOUND')
    return row
def _save(service,tx,identity,data,prior=None):
    row=StoredRecord(RecordKind.OPERATION,identity,service.scope,prior.revision+1 if prior else 1,data)
    if prior:tx.replace(row,expected_revision=prior.revision)
    else:tx.insert(row)
    event=canonical_sha256((identity,row.revision))
    operation=OperationBinding.bind('chat-event-'+event,'CHAT_JOURNAL_TRANSITION',
        {'record_digest':row.payload_digest,'source_sha':data['source_sha'],'request_digest':data['request_digest']})
    append_domain_event(tx,operation,event_id='chat-audit-'+event,proof_id='chat-outbox-'+event,
        resource_id=identity,before=prior.payload['state'] if prior else None,after=data['state'],
        content_digest=row.payload_digest,at=service.ledger.clock())
    return row
def _change(service,identity,allowed,state,updates=None):
    require(state in STATES)
    def write(tx):
        row=tx.get(RecordKind.OPERATION,identity);require(row is not None and row.payload['schema']==KIND)
        data=plain(row.payload)
        if data['state'].removeprefix('CHAT_') not in allowed:return data
        data.update(updates or {},state='CHAT_'+state)
        return plain(_save(service,tx,identity,data,row).payload)
    return service._run(Capability.COMMIT,write)
def _prune(service):
    now=time.monotonic()
    for cache in (service._chat_payloads,service._chat_results):
        for key,value in tuple(cache.items()):
            if now-value[0]>TTL:del cache[key]

def propose(service,payload,reader,*,device_id,session_id,nonce,actor='ANDROID',read_context=None,session_authorization=None):
    service.core.require(reader,Capability.READ,scope=service.scope)
    fields={'schema','thread_id','request_id','model_id','prompt'}
    if session_authorization is None:fields.add('max_budget_usd')
    require(type(payload) is dict and set(payload)==fields,'CHAT_PAYLOAD_INVALID')
    schema='aioa.mobile.chat-send.v1' if session_authorization is None else 'aioa.mobile.chat-send.v2'
    require(payload['schema']==schema and payload['model_id']==MODEL,'CHAT_MODEL_INVALID')
    device_id=_device(device_id);request_id=_id(payload['request_id']);thread_id=_id(payload['thread_id'])
    _id(session_id);_id(nonce)
    require(type(payload['prompt']) is str and payload['prompt'].strip() and 1<=len(payload['prompt'].encode())<=2000,'CHAT_PROMPT_LIMIT')
    if session_authorization is None:
        require(type(payload['max_budget_usd']) is str and re.fullmatch(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,9})?',payload['max_budget_usd']),'CHAT_BUDGET_INVALID')
        ceiling=Decimal('.05') if actor=='ANDROID' else Decimal('148')
        cap=budget_status(service,reader)['max_budget_usd']
        require(0<Decimal(payload['max_budget_usd'])<=min(ceiling,Decimal(cap) if cap is not None else ceiling),'CHAT_BUDGET_INVALID')
    else:
        from . import chat_session
        require(actor=='LINUX_OWNER','CHAT_SESSION_SCOPE_DENIED')
        chat_session.require_active(service,session_authorization)
    submission=canonical_sha256({'payload':payload,'device_id':device_id,**({'read_context':read_context} if read_context is not None else {})})
    with service._lock:
        require(not service._closed and service._chat_governor is not None,'CHAT_NOT_CONFIGURED')
        _prune(service)
        prior=service._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,'chat-'+request_id))
        if prior:
            require(prior.payload.get('schema')==KIND and prior.payload['device_id']==device_id
                and prior.payload['submission_digest']==submission,'CHAT_REQUEST_CONFLICT')
            return request(service,request_id,reader,device_id=device_id)
        rows=_rows(service);thread_rows=sorted((r for r in rows if r.payload['thread_id']==thread_id),key=lambda r:r.payload['created_order'])
        require(all(r.payload['device_id']==device_id for r in thread_rows),'CHAT_NOT_FOUND')
        require(not any(r.payload['state'] in ('CHAT_PENDING_OWNER','CHAT_RUNNING') for r in thread_rows),'CHAT_THREAD_BUSY')
        require(len(rows)<128 and len(service._chat_payloads)<24,'CHAT_HISTORY_LIMIT')
        history=[]
        for row in thread_rows:
            key=row.payload['request_id'];source=service._chat_payloads.get(key);result=service._chat_results.get(key)
            if row.payload['state']=='CHAT_SUCCEEDED' and source and result:
                history.extend((('user',source[1].prompt),('assistant',result[1])))
        while len(history)>20 or sum(len(text.encode()) for _,text in history)>12000:history=history[2:]
        sha,capsule=service.source_probe();now=service.ledger.clock()
        deadline=now+timedelta(minutes=5)
        if session_authorization is not None:
            active=chat_session.require_active(service,session_authorization)
            deadline=min(deadline,utc_timestamp(active['expires_at']))
        if read_context is not None:
            require(actor=='LINUX_OWNER' and type(read_context) is dict,'CHAT_CONTEXT_NOT_BOUND')
            require(callable(service._chat_context_probe) and service._chat_context_probe(read_context.get('request_id'))==read_context,'CHAT_CONTEXT_CHANGED')
            deadline=min(deadline,datetime.fromtimestamp(read_context['expires_at'],timezone.utc))
        task=MetaChatTask('chat-'+request_id,canonical_sha256(service.scope),sha,utc(deadline),
            device_id,thread_id,request_id,session_id,nonce,actor)
        require(service._chat_authority(task),'CHAT_AUTHORITY_REVOKED')
        if session_authorization is not None:chat_session.require_active(service,session_authorization,task)
        context={'schema':'aioa.chat.core-context.v1','core':'ADMITTED','profile':'NATIVE_ADVISORY_CHAT_V1',
            'source_sha':sha,'capsule_digest':capsule,'native_execute':False,'github_write':False,'save_knowledge':False,
            'mission_read':'BLOCKED_NATIVE_WORKER_NOT_BOUND'}
        if read_context is not None:context.update(schema='aioa.chat.core-context.v2',read_context=read_context)
        req=MetaChatRequest(task,payload['prompt'],canonical_json_bytes(context).decode(),history=tuple(history),
            budget_usd=payload.get('max_budget_usd','0'),capsule_digest=capsule)
        # This is a reservation derived from the exact bounded payload, not an
        # arbitrary per-message or session spending cap.
        if session_authorization is not None:req=replace(req,budget_usd=format(req.estimate(),'f'))
        req.payload();require(req.estimate()<=Decimal(req.budget_usd),'CHAT_BUDGET_INSUFFICIENT')
        data={'schema':KIND,'state':'CHAT_PENDING_OWNER','request_id':request_id,'thread_id':thread_id,
            'device_id':device_id,'actor':actor,'task_id':task.task_id,'task_digest':task.digest,
            'request_digest':req.digest,'submission_digest':submission,'binding':req.public_binding(),
            'source_sha':sha,'capsule_digest':capsule,'created_at':utc(now),'created_order':int(now.timestamp()*1000000),
            'model_id':MODEL,'provider_id':PROVIDER,'max_budget_usd':req.budget_usd,'reserved_bound_usd':None,
            'cost_estimate_usd':format(req.estimate(),'f'),'receipt':None,'error':None,'live_verified':False}
        if session_authorization is not None:data['authorization']=dict(session_authorization)
        # Intent/ACK barrier is committed before any approval or provider call.
        service._run(Capability.COMMIT,lambda tx:_save(service,tx,task.task_id,data))
        service._chat_payloads[request_id]=(time.monotonic(),req)
        return request(service,request_id,reader,device_id=device_id)

def request(service,request_id,reader,*,device_id=None):
    service.core.require(reader,Capability.READ,scope=service.scope)
    with service._lock:
        _prune(service);row=_get(service,request_id,device_id);data=plain(row.payload)
        content=service._chat_payloads.get(request_id);reply=service._chat_results.get(request_id)
        if data['state']=='CHAT_PENDING_OWNER' and service.ledger.clock()>=utc_timestamp(data['binding']['deadline']):
            data=_change(service,row.record_id,('PENDING_OWNER',),'FAILED',{'error':'CHAT_APPROVAL_EXPIRED'})
        if data['state']=='CHAT_PENDING_OWNER' and content is None:
            data.update(state='CHAT_UNKNOWN',error='CHAT_PENDING_ACK_UNKNOWN')
        worker=service._workers.get(row.record_id)
        if data['state']=='CHAT_RUNNING' and (worker is None or not worker.is_alive()):
            data.update(state='CHAT_UNKNOWN',error='CHAT_WORKER_READBACK_UNKNOWN')
        data.update(schema='aioa.mobile.chat-result.v1',state=data['state'].removeprefix('CHAT_'),
            prompt=content[1].prompt if content else None,reply=reply[1] if reply else None,
            text_state='AVAILABLE' if content else 'HISTORY_EXPIRED',save_knowledge=False,
            current_source=service.source_probe()==(data['source_sha'],data['capsule_digest']))
        return data

def threads(service,reader,*,device_id=None):
    service.core.require(reader,Capability.READ,scope=service.scope)
    if device_id is not None:_device(device_id)
    with service._lock:
        _prune(service);latest={};source=tuple(service.source_probe())
        for row in sorted(_rows(service),key=lambda r:r.payload['created_order']):
            data=row.payload
            if device_id is None or data['device_id']==device_id:
                summary={k:data[k] for k in ('thread_id','device_id','request_id','created_at','model_id','source_sha','capsule_digest')}
                summary.update(state=data['state'].removeprefix('CHAT_'),
                    current_source=(data['source_sha'],data['capsule_digest'])==source,
                    text_available=data['request_id'] in service._chat_payloads and data['request_id'] in service._chat_results)
                latest.pop(data['thread_id'],None);latest[data['thread_id']]=summary
        return {'schema':'aioa.mobile.chat-threads.v1','threads':list(latest.values())[-24:],'save_knowledge':False}

def thread(service,thread_id,reader,*,device_id=None):
    service.core.require(reader,Capability.READ,scope=service.scope);_id(thread_id)
    rows=sorted((r for r in _rows(service) if r.payload['thread_id']==thread_id),key=lambda r:r.payload['created_order'])
    require(rows and all(device_id is None or r.payload['device_id']==device_id for r in rows),'CHAT_NOT_FOUND')
    messages=[request(service,r.payload['request_id'],reader,device_id=device_id) for r in rows][-20:]
    while len(canonical_json_bytes(messages))>48000:messages.pop(0)
    return {'schema':'aioa.mobile.chat-thread.v1','thread_id':thread_id,'save_knowledge':False,
        'messages':messages,'history_truncated':len(messages)<len(rows)}

def review(service,request_id,reader):
    data=request(service,request_id,reader)
    require(data['state']=='PENDING_OWNER' and data['prompt'] is not None,'CHAT_NOT_PENDING')
    req=service._chat_payloads[request_id][1]
    require(service.source_probe()==(req.task.source_sha,req.capsule_digest),'CHAT_SOURCE_CHANGED')
    require(service._chat_authority(req.task),'CHAT_AUTHORITY_REVOKED')
    _check_context(service,req)
    require(service.ledger.clock()<utc_timestamp(req.task.deadline_utc),'CHAT_APPROVAL_EXPIRED')
    epoch=service._chat_governor.inspect(reader)['epoch']
    result={**data,'policy_epoch':epoch,'endpoint':'https://api.meta.ai/v1/chat/completions','max_attempts':1,
        'billing_status':'OWNER_SESSION_AUTHORIZED' if data.get('authorization') else 'OWNER_CONFIRMATION_REQUIRED',
        'request_payload':req.payload(),'review_digest':None}
    result['review_digest']=canonical_sha256({k:result[k] for k in ('request_digest','source_sha','capsule_digest','max_budget_usd','policy_epoch','endpoint','max_attempts')})
    return result

def approve(service,request_id,review_digest,owner_principal,*,session_authorization=None):
    # Exact per-message review or a native owner session plus authenticated Send.
    # HTTP cannot create a spending session or forward the chat_approve operation.
    service.core.require(owner_principal,Capability.OWNER_APPROVAL,scope=service.scope)
    with service._lock:
        current=review(service,request_id,service.core.local_operator(Capability.READ))
        require(current['review_digest']==review_digest,'CHAT_REVIEW_CHANGED')
        require(not any(r.payload['state']=='CHAT_RUNNING' for r in _rows(service)),'CHAT_PROVIDER_BUSY')
        req=service._chat_payloads[request_id][1];governor=service._chat_governor
        require(current.get('authorization')==session_authorization,'CHAT_SESSION_BINDING_CHANGED')
        def session_check():
            if session_authorization is not None:
                from . import chat_session
                chat_session.require_active(service,session_authorization,req.task)
        session_check()
        credit_required=governor.inspect(service.core.local_operator(Capability.READ)).get('money_policy',{}).get('schema')=='aioa.governor.money-policy.v2'
        def credit_check():
            if credit_required:
                require(callable(service._chat_credit_probe) and service._chat_credit_probe(req) is True,'CREDIT_BALANCE_NOT_BOUND')
        credit_check()  # No reservation, key read or transport before this gate.
        operation=spend_operation(req.digest,req.public_binding());now=service.ledger.clock()
        from runtime.mission.governor import ReservationRequest
        amount=int((req.estimate()*10**9).to_integral_value(rounding=ROUND_CEILING))
        reserve=ReservationRequest('chat-spend-'+request_id,req.task.task_id,PROVIDER,MODEL,canonical_sha256(operation),amount,1)
        authority=AuthorityScope(operation_classes=(operation['operation_class'],),target_scope=operation['target_fingerprint'],
            risk_ceiling=RiskLevel.MODERATE,monetary_ceiling=Money(Decimal(req.budget_usd),'USD'),not_before=now,
            expires_at=utc_timestamp(req.task.deadline_utc),
            owner_scope=req.task.owner_scope_digest,task_scope=req.task.task_id)
        evidence=(EvidenceRef('chat-request','request','sha256:'+req.digest,'v1'),)
        if session_authorization is not None:
            evidence+=(EvidenceRef('owner-chat-session','authorization','sha256:'+session_authorization['grant_digest'],'v1'),)
        warrant=EffectWarrant(warrant_id='chat-warrant-'+request_id,task_id=req.task.task_id,owner_scope=req.task.owner_scope_digest,
            operation_class=operation['operation_class'],operation_hash='sha256:'+canonical_sha256(operation),
            target_fingerprint=operation['target_fingerprint'],expected_target_revision=req.task.source_sha,revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot(evidence),
            lease_epoch=current['policy_epoch'],authority_scope=authority,approval_digest='sha256:'+'0'*64,
            money_reservation_id=reserve.request_id,risk_reservation_id=reserve.request_id,nonce=uuid.uuid4().hex,issued_at=now,expires_at=authority.expires_at)
        warrant=replace(warrant,approval_digest=approval_digest(warrant));commit=service.core.local_operator(Capability.COMMIT)
        try:
            governor.reserve(commit,reserve,warrant.lease_epoch)
            service.ledger.approve(owner_principal,warrant)
            def admitted_source():
                require(service._chat_authority(req.task),'CHAT_AUTHORITY_REVOKED')
                session_check()
                credit_check()  # Trusted probe must be pure; never a Core/HTTP callback.
                return service.source_probe()
            binding=MetaLiveBinding(service.ledger,governor,commit,warrant,reserve,True,True,source_reader=admitted_source,
                session_dispatch=session_authorization is not None)
            binding.check(req)
            _change(service,req.task.task_id,('PENDING_OWNER',),'RUNNING',{'warrant_digest':warrant.digest(),
                'reserved_bound_usd':format(Decimal(amount)/10**9,'f'),'policy_epoch':warrant.lease_epoch})
        except Exception:
            _change(service,req.task.task_id,('PENDING_OWNER','RUNNING'),'UNKNOWN',{'error':'CHAT_APPROVAL_ACK_UNKNOWN'})
            raise ValueError('CHAT_APPROVAL_ACK_UNKNOWN') from None
        cancel=CancellationToken();service._cancels[req.task.task_id]=cancel
        worker=threading.Thread(target=_execute,args=(service,req,binding,cancel),daemon=True)
        service._workers[req.task.task_id]=worker;worker.start()
        return request(service,request_id,service.core.local_operator(Capability.READ))

def _execute(service,req,binding,cancel):
    try:
        require(service._chat_authority(req.task),'CHAT_AUTHORITY_REVOKED')
        _check_context(service,req)
        result=service.manager.generate_meta_chat(req,cancel,live_binding=binding)
        receipt=MetaReceiptView(service.ledger,governor=binding.governor,source_reader=service.source_probe).readback(req.digest)
        require(result.live_verified and receipt['response_sha256']==hashlib.sha256(result.text.encode()).hexdigest(),'CHAT_RECEIPT_UNKNOWN')
        binding.governor.settle(binding.principal,binding.reservation.request_id,binding.warrant.lease_epoch,canonical_sha256(receipt))
        with service._lock:
            if cancel.cancelled:raise ValueError('CHAT_STOPPED')
            service._chat_results[req.task.request_id]=(time.monotonic(),result.text)
            _change(service,req.task.task_id,('RUNNING',),'SUCCEEDED',{'receipt':receipt,'live_verified':True})
    except Exception as error:
        code=error.code if type(error) is MetaAPIError else 'CHAT_RECEIPT_UNKNOWN'
        state='STOPPED' if cancel.cancelled else 'FAILED' if code in ('META_AUTH_DENIED','META_CONTRACT_REJECTED','META_RATE_LIMITED','META_BILLING_UNAVAILABLE','META_UNAVAILABLE') else 'UNKNOWN'
        try:_change(service,req.task.task_id,('RUNNING',),state,{'error':code})
        except Exception:pass  # Existing durable RUNNING projects UNKNOWN after restart.

def stop(service,request_id,reader,*,device_id=None):
    service.core.require(reader,Capability.READ,scope=service.scope)
    with service._lock:
        row=_get(service,request_id,device_id);cancel=service._cancels.get(row.record_id)
        if cancel:cancel.cancel()
        _change(service,row.record_id,('PENDING_OWNER','RUNNING'),'STOPPED',{'error':'CHAT_STOPPED'})
        return request(service,request_id,reader,device_id=device_id)
