"""Owner-configured direct text chat on the existing Core and governor.

The private native channel enables the session; an authenticated console Send
authorizes each exact message under that grant. No model output can enable it.
Grants expire with native admission and never resume automatically after restart.
Every request still has its own warrant, reservation, one-shot dispatch and receipt.
"""
from datetime import timedelta

from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
from runtime.providers.meta_model_api import MODEL,PROVIDER
from .contracts import utc_timestamp
from .mission_service import require,plain,utc

KIND='aioa.chat.owner-session.v1'


def _get(service,session_id):
    return service._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,'chat-session-'+session_id))


def _save(service,data,prior=None):
    def save(tx):
        row=StoredRecord(RecordKind.OPERATION,'chat-session-'+data['session_id'],service.scope,
            prior.revision+1 if prior else 1,data)
        if prior:tx.replace(row,expected_revision=prior.revision)
        else:tx.insert(row)
        digest=canonical_sha256((row.record_id,row.revision,row.payload_digest))
        binding=OperationBinding.bind('chat-session-event-'+digest,'CHAT_SESSION_AUTHORIZATION',
            {'session_id':data['session_id'],'record_digest':row.payload_digest,'source_sha':data['source_sha']})
        append_domain_event(tx,binding,event_id='chat-session-audit-'+digest,proof_id='chat-session-outbox-'+digest,
            resource_id=row.record_id,before=prior.payload['state'] if prior else None,after=data['state'],
            content_digest=row.payload_digest,at=service.ledger.clock())
        return row
    return service._run(Capability.COMMIT,save)


def start(service,owner,*,session_id,device_id,expires_at,authority_check):
    from . import chat
    service.core.require(owner,Capability.OWNER_APPROVAL,scope=service.scope)
    chat._id(session_id);chat._device(device_id)
    require(callable(authority_check),'CHAT_SESSION_AUTHORITY_REQUIRED')
    with service._lock:
        require(not service._closed and service._chat_governor is not None,'CHAT_NOT_CONFIGURED')
        authority_check();now=service.ledger.clock()
        require(now<expires_at<=now+timedelta(hours=1),'CHAT_SESSION_EXPIRY_INVALID')
        prior=_get(service,session_id)
        if prior is not None:
            # Never reactivate an old/uncertain grant on duplicate input.
            active=require_active(service)
            require(active['session_id']==session_id,'CHAT_SESSION_READBACK_REQUIRED')
            return status(service)
        require(not any(w.is_alive() for w in service._workers.values()),'CHAT_PROVIDER_BUSY')
        require(status(service)['state']!='ACTIVE','CHAT_SESSION_ALREADY_ACTIVE')
        service._chat_session=None
        governor=service._chat_governor;reader=service.core.local_operator(Capability.READ)
        require(not governor.inspect(reader)['kill'],'CHAT_SESSION_STOPPED')
        review=governor.money_policy_review(reader,{k:None for k in
            ('task_limit','owner_provider_limit','global_limit')},request_id='chat-session-'+session_id)
        governor.apply_money_policy(service.core.local_operator(Capability.MANAGE),review,authority_check=authority_check)
        authority_check();current=governor.inspect(reader);sha,capsule=service.source_probe()
        grant={'schema':KIND,'state':'CHAT_SESSION_ACTIVE','session_id':session_id,
            'authorization_basis':'OWNER_SESSION_AND_SEND','provider_id':PROVIDER,'model_id':MODEL,
            'actor':'LINUX_OWNER','device_id':device_id,'owner_scope_digest':canonical_sha256(service.scope),
            'owner_session_id':owner.actor_session_id,'assignment_revision':owner.assignment_revision,
            'source_sha':sha,'capsule_digest':capsule,'issued_at':utc(now),'expires_at':utc(expires_at),
            'policy_epoch':current['epoch'],'policy_request_id':review['request_id'],
            'local_money_limit_usd':None,'tools':[],'max_attempts':1,'provider_billing_status':'UNVERIFIED'}
        row=_save(service,grant);authority_check()
        service._chat_session=(session_id,row.payload_digest)
        return status(service)


def require_active(service,authorization=None,task=None):
    require(not service._closed,'CHAT_NOT_CONFIGURED')
    current=service._chat_session
    require(current is not None,'CHAT_SESSION_REQUIRED')
    row=_get(service,current[0]);require(row is not None,'CHAT_SESSION_REQUIRED')
    grant=plain(row.payload);owner=service.core.local_operator(Capability.OWNER_APPROVAL)
    require(row.payload_digest==current[1] and grant['schema']==KIND
        and grant['state']=='CHAT_SESSION_ACTIVE','CHAT_SESSION_REVOKED')
    require(grant['owner_session_id']==owner.actor_session_id
        and grant['assignment_revision']==owner.assignment_revision,'CHAT_SESSION_OWNER_CHANGED')
    require(service.source_probe()==(grant['source_sha'],grant['capsule_digest']),'CHAT_SESSION_SOURCE_CHANGED')
    require(utc_timestamp(grant['issued_at'])<=service.ledger.clock()<utc_timestamp(grant['expires_at']),
        'CHAT_SESSION_EXPIRED')
    state=service._chat_governor.inspect(service.core.local_operator(Capability.READ))
    require(not state['kill'],'CHAT_SESSION_STOPPED')
    require(state['epoch']==grant['policy_epoch'] and
        state.get('money_policy',{}).get('request_id')==grant['policy_request_id'],'CHAT_SESSION_POLICY_CHANGED')
    expected={'basis':'OWNER_SESSION_AND_SEND','session_id':current[0],'grant_digest':current[1]}
    if authorization is not None:require(authorization==expected,'CHAT_SESSION_BINDING_CHANGED')
    if task is not None:
        require(task.actor=='LINUX_OWNER' and task.device_id==grant['device_id']
            and task.session_id==canonical_sha256(owner.actor_session_id)[:32]
            and task.source_sha==grant['source_sha'],'CHAT_SESSION_SCOPE_DENIED')
    return {**grant,'authorization':expected}


def status(service):
    try:
        active=require_active(service)
        return {'state':'ACTIVE',**{k:active[k] for k in ('session_id','authorization_basis',
            'local_money_limit_usd','expires_at','provider_billing_status')}}
    except ValueError:
        return {'state':'INACTIVE','authorization_basis':None}


def send(service,owner,payload,*,device_id,session_id,nonce,read_context=None):
    from . import chat
    service.core.require(owner,Capability.OWNER_APPROVAL,scope=service.scope)
    reader=service.core.local_operator(Capability.READ)
    with service._lock:
        active=require_active(service);authorization=active['authorization']
        require(type(payload) is dict,'CHAT_PAYLOAD_INVALID')
        request_id=chat._id(payload.get('request_id'))
        prior=service._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,'chat-'+request_id))
        if prior is None:require(not any(r.payload['state']=='CHAT_RUNNING' for r in chat._rows(service)),'CHAT_PROVIDER_BUSY')
        result=chat.propose(service,payload,reader,device_id=device_id,session_id=session_id,nonce=nonce,
            actor='LINUX_OWNER',read_context=read_context,session_authorization=authorization)
        if prior is not None:return result  # ACK/readback only, including PENDING_OWNER and UNKNOWN.
        review=chat.review(service,request_id,reader)
        return chat.approve(service,request_id,review['review_digest'],owner,session_authorization=authorization)


def stop(service,owner):
    from . import chat
    service.core.require(owner,Capability.OWNER_APPROVAL,scope=service.scope)
    with service._lock:
        current=service._chat_session;service._chat_session=None
        if current is None:return status(service)
        # The governor epoch is the final dispatch gate; old warrants cannot be
        # released after this takeover. In-flight/UNKNOWN exposure is retained.
        service._chat_governor.start_epoch(service.core.local_operator(Capability.MANAGE))
        for row in chat._rows(service):
            if row.payload.get('authorization',{}).get('session_id')==current[0]:
                cancel=service._cancels.get(row.record_id)
                if cancel:cancel.cancel()
        row=_get(service,current[0])
        if row is not None:_save(service,{**plain(row.payload),'state':'CHAT_SESSION_STOPPED'},row)
        return status(service)
