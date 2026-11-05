"""Same-Core chat operations on the existing UID-authenticated operator port.

Financial configuration is private-socket only. The console can send paid text
under an active owner session, but cannot enable it or forward chat_approve.
"""
import secrets
import json
import re
import time
from decimal import Decimal
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from . import wire

READ_OPS=frozenset(('chat_catalog','chat_threads','chat_thread','chat_request','chat_propose','chat_stop','chat_review',
    'chat_send','chat_session_status','chat_session_stop'))

def dispatch(host,owner,value):
    if not host.chat_enabled:raise wire.MobileError(501)
    host.core.require(owner,Capability.OWNER_APPROVAL,scope=host.missions.scope)
    service=host.missions;reader=host.core.local_operator(Capability.READ);op=value['op']
    fields={'chat_catalog':{'op'},'chat_threads':{'op'},'chat_thread':{'op','thread_id'},
        'chat_request':{'op','request_id'},'chat_review':{'op','request_id'},'chat_stop':{'op','request_id'},
        'chat_propose':{'op','payload'},'chat_approve':{'op','request_id','review_digest'},
        'chat_send':{'op','payload'},'chat_session_status':{'op'},'chat_session_stop':{'op'},
        'chat_session_start':{'op','request_id','local_money_limit_usd'}}
    with_read=op in ('chat_propose','chat_send') and set(value)=={'op','payload','read_request_id'}
    if op not in fields or (not with_read and set(value)!=fields[op]):raise wire.MobileError(400)
    if op=='chat_catalog':
        from runtime.meta_hackathon.chat import budget_status
        from runtime.meta_hackathon.chat_session import status
        budget=budget_status(service,reader)
        session=status(service)
        reason=('CHAT_SESSION_REQUIRED' if budget['allocation_usd'] is None and session['state']!='ACTIVE' else
            'CREDIT_BALANCE_NOT_BOUND' if budget['credit_only'] and not budget['credit_binding_available'] else None)
        return {'schema':'aioa.chat.catalog.v1','provider_id':'meta_model_api','model_id':'muse-spark-1.3',
            'mode':'LIVE_OWNER_SESSION' if session['state']=='ACTIVE' else 'LIVE_PENDING_EXACT_OWNER_APPROVAL',
            'session':session,'chat':reason is None,'save_knowledge':False,**budget,
            'blocking_reason':reason,
            'billing_status':'UNVERIFIED','mission_read':'BLOCKED_NATIVE_WORKER_NOT_BOUND',
            'github_write':False,'native_execute':False,'source_sha':host.source[0],'capsule_digest':host.source[1],
            'model_calls':host.model_calls()}
    if op.startswith('chat_session_'):
        from datetime import timedelta
        from runtime.meta_hackathon import chat_session
        host._require_qualified_operator()
        if op=='chat_session_status':return chat_session.status(service)
        if op=='chat_session_stop':return chat_session.stop(service,owner)
        if value['local_money_limit_usd'] is not None:raise wire.MobileError(400)
        lifetime=min(3600,host._auth_deadline-time.monotonic(),host._tls_expires-time.time())
        return chat_session.start(service,owner,session_id=value['request_id'],device_id=host.identity.audience,
            expires_at=service.ledger.clock()+timedelta(seconds=lifetime),authority_check=host._require_qualified_operator)
    if op=='chat_threads':return service.chat_threads(reader)
    if op=='chat_thread':return service.chat_thread(value['thread_id'],reader)
    if op=='chat_request':return service.chat_request(value['request_id'],reader)
    if op=='chat_review':return service.chat_review(value['request_id'],reader)
    if op=='chat_stop':return service.chat_stop(value['request_id'],reader)
    if op=='chat_approve':return service.chat_approve(value['request_id'],value['review_digest'],owner)
    payload=value['payload'];device=host.identity.audience
    if type(payload) is not dict:raise wire.MobileError(400)
    threads=service.chat_threads(reader)['threads']
    existing=next((t for t in threads if t['thread_id']==payload.get('thread_id')),None)
    if existing:device=existing['device_id']
    context=None
    if with_read:
        from runtime.meta_hackathon.native_tools import chat_read_context
        context=chat_read_context(host,value['read_request_id'])
    if op=='chat_send':
        from runtime.meta_hackathon.chat_session import send
        host._require_qualified_operator()
        return send(service,owner,payload,device_id=device,session_id=canonical_sha256(host.instance_id)[:32],
            nonce=secrets.token_hex(16),read_context=context)
    return service.chat_propose(payload,reader,device_id=device,session_id=canonical_sha256(host.instance_id)[:32],
        nonce=secrets.token_hex(16),actor='LINUX_OWNER',read_context=context)


def budget_dispatch(host,owner,value):
    """Private operator-only configuration; never a paid-call approval."""
    if not host.chat_enabled:raise wire.MobileError(501)
    host.core.require(owner,Capability.OWNER_APPROVAL,scope=host.missions.scope)
    host._require_qualified_operator();reader=host.core.local_operator(Capability.READ)
    governor=host.chat_governor
    if value['op']=='budget_review':
        if (set(value) not in ({'op','request_id','total_usd'},{'op','request_id','total_usd','observed_credit_usd'}) or type(value['request_id']) is not str
                or not wire.HEX32.fullmatch(value['request_id']) or type(value['total_usd']) is not str
                or not re.fullmatch(r'(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,9})?',value['total_usd'])):
            raise wire.MobileError(400)
        amount=Decimal(value['total_usd'])
        if not 0<amount<=148:raise wire.MobileError(400)
        nano=int(amount*10**9)
        review=governor.money_policy_review(reader,{k:nano for k in
            ('task_limit','owner_provider_limit','global_limit')},request_id=value['request_id'])
        credit=None
        if 'observed_credit_usd' in value:
            raw=value['observed_credit_usd']
            if type(raw) is not str or not re.fullmatch(r'(?:0|[1-9][0-9]{0,5})(?:\.[0-9]{1,9})?',raw):raise wire.MobileError(400)
            available=Decimal(raw)
            if available<amount:raise wire.MobileError(400)
            info=host._meta_key_path.lstat();now=int(time.time())
            credit={'kind':'OWNER_META_DASHBOARD_ATTESTATION','credit_nano':int(available*10**9),
                'issued_at':now,'expires_at':now+300,'key_metadata_digest':canonical_sha256((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns))}
        body={'schema':'aioa.native-budget-review.v1','governor_review':review,
            'total_usd':format(amount,'f'),'source_sha':host.source[0],'capsule_digest':host.source[1],
            'core_instance_id':host.instance_id,'provider_balance_status':'UNVERIFIED','paid_calls_authorized':False,
            'credit_observation':credit}
        return {**body,'native_review_digest':canonical_sha256(body)}
    if value['op']!='budget_approve' or set(value)!={'op','review'}:raise wire.MobileError(400)
    review=value['review']
    fields={'schema','governor_review','total_usd','source_sha','capsule_digest','core_instance_id',
        'provider_balance_status','paid_calls_authorized','native_review_digest','credit_observation'}
    if type(review) is not dict or set(review)!=fields:raise wire.MobileError(400)
    body={k:v for k,v in review.items() if k!='native_review_digest'}
    if (review['schema']!='aioa.native-budget-review.v1' or (review['source_sha'],review['capsule_digest'])!=host.source
            or review['core_instance_id']!=host.instance_id or review['provider_balance_status']!='UNVERIFIED'
            or review['paid_calls_authorized'] is not False or canonical_sha256(body)!=review['native_review_digest']):
        raise wire.MobileError(403)
    try:
        amount=Decimal(review['total_usd']);nano=int(amount*10**9)
        if not amount.is_finite() or not 0<amount<=148:raise ValueError()
        if review['governor_review']['limits']!={k:nano for k in ('task_limit','owner_provider_limit','global_limit')}:raise ValueError()
        credit=review['credit_observation']
        if credit is not None:
            if (type(credit) is not dict or set(credit)!={'kind','credit_nano','issued_at','expires_at','key_metadata_digest'}
                    or credit['kind']!='OWNER_META_DASHBOARD_ATTESTATION' or type(credit['credit_nano']) is not int
                    or credit['credit_nano']<nano or type(credit['issued_at']) is not int or type(credit['expires_at']) is not int
                    or not credit['issued_at']<=time.time()<credit['expires_at']==credit['issued_at']+300):raise ValueError()
            info=host._meta_key_path.lstat()
            if credit['key_metadata_digest']!=canonical_sha256((info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)):raise ValueError()
    except (ValueError,TypeError,KeyError,ArithmeticError):raise wire.MobileError(400) from None
    if not host.missions._lock.acquire(timeout=1):raise wire.MobileError(409)
    try:
        if any(worker.is_alive() for worker in host.missions._workers.values()):raise wire.MobileError(409)
        host._require_qualified_operator()
        host._credit_observation=None  # Fail closed on either commit ACK loss.
        result=governor.apply_money_policy(host.core.local_operator(Capability.MANAGE),review['governor_review'],
            authority_check=host._require_qualified_operator)
        host._require_qualified_operator()
        current=governor.inspect(reader)
        host._credit_policy_binding=(current['epoch'],current.get('money_policy',{}).get('request_id'))
        if credit is not None and current.get('money_policy',{}).get('request_id')==review['governor_review']['request_id']:
            data={'state':'MOBILE_META_CREDIT_ATTESTATION',**credit,'source_sha':host.source[0],
                'capsule_digest':host.source[1],'core_instance_id':host.instance_id,
                'native_review_digest':review['native_review_digest'],'policy_epoch':current['epoch'],
                'policy_request_id':review['governor_review']['request_id']}
            key='native-meta-credit-'+review['governor_review']['request_id']
            def save(tx):
                from runtime.memory_patch.persistence.ports import RecordKind
                host._require_qualified_operator()
                prior=tx.get(RecordKind.OPERATION,key)
                if prior is not None:
                    from runtime.mobile_gateway.service import plain
                    existing=plain(prior.payload);existing.pop('schema')
                    if existing!=data:raise wire.MobileError(409)
                    return existing
                host._require_qualified_operator()
                host.mobile._record(tx,key,data,at=int(time.time()));return data
            committed=host.mobile._run(Capability.COMMIT,save)
            host._require_qualified_operator()
            if time.time()<committed['expires_at']:host._credit_observation=committed
        from runtime.meta_hackathon.chat import budget_status
        return {**result,**budget_status(host.missions,reader),'paid_calls_authorized':False}
    finally:host.missions._lock.release()


def financial_budget_review(state_dir,total_usd,*,approve=False,observed_credit_usd=None):
    """Same native human review channel as financial_review, with no inference."""
    import subprocess
    from runtime.webapp import mobile_operator_client
    from runtime.meta_hackathon.runtime_adapter import _desktop_operator_uid
    packet={'op':'budget_review','request_id':secrets.token_hex(16),'total_usd':total_usd}
    if observed_credit_usd is not None:packet['observed_credit_usd']=observed_credit_usd
    result=mobile_operator_client(state_dir,packet)
    if result.get('ok') is not True:raise SystemExit('BUDGET_REVIEW_DENIED_OR_UNKNOWN')
    review=result['data']
    if not approve:print(json.dumps(review,indent=2));return
    _desktop_operator_uid()
    text=('AIOA — LOCAL HACKATHON ALLOCATION\n\n'+json.dumps(review,indent=2)+
        '\n\nThis total includes existing reservations, committed exposure and UNKNOWN. It does not add provider credits, '
        'verify the Meta balance through an API or authorize a model call. Any supplied credit value must be your '
        'fresh observation of the same account in the authenticated Meta dashboard; it expires after five minutes. '
        'Other applications can consume those credits. Meta spend alerts are not hard account caps. '
        'Existing risk, replay, STOP and exact per-request approval controls remain. Older code may not read the new policy history.')
    done=subprocess.run(['/usr/bin/zenity','--text-info','--title=AIOA: exact local budget configuration',
        '--width=850','--height=650','--checkbox=I confirm this allocation and any credit value I personally observed; no model call',
        '--timeout=180'],input=text,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=190,check=False)
    if done.returncode:raise SystemExit('BUDGET_OWNER_CANCELLED')
    response=mobile_operator_client(state_dir,{'op':'budget_approve','review':review})
    print(json.dumps(response));return

def financial_review(state_dir,request_id,*,approve=False):
    """Explicit native human decision, never a flag inside model/HTTP content."""
    import subprocess
    from runtime.webapp import mobile_operator_client
    from runtime.meta_hackathon.runtime_adapter import _desktop_operator_uid
    if type(request_id) is not str or not wire.HEX32.fullmatch(request_id):raise SystemExit('CHAT_REQUEST_ID_REQUIRED')
    result=mobile_operator_client(state_dir,{'op':'chat_review','request_id':request_id})
    if result.get('ok') is not True:raise SystemExit('CHAT_REVIEW_DENIED_OR_UNKNOWN')
    review=result['data']
    public={k:review[k] for k in ('task_id','request_id','request_digest','source_sha','capsule_digest','model_id',
        'max_budget_usd','cost_estimate_usd','policy_epoch','endpoint','max_attempts','review_digest','prompt','request_payload')}
    if not approve:
        print(json.dumps(public,ensure_ascii=False,indent=2));return
    _desktop_operator_uid()
    text=('AIOA — ONE PAID META MESSAGE\n\n'+json.dumps(public,ensure_ascii=False,indent=2)+
        '\n\nYou are approving standard Meta Model API usage with a maximum cost of USD '+review['max_budget_usd']+'. '
        'Account billing remains UNVERIFIED. One attempt, without automatic retry. '
        'This does not approve tools, GitHub WRITE or further messages.')
    completed=subprocess.run(['/usr/bin/zenity','--text-info','--title=AIOA: exact Muse cost approval',
        '--width=850','--height=650','--checkbox=I approve only this message and its cost ceiling',
        '--ok-label=Approve one attempt','--cancel-label=Cancel','--timeout=180'],
        input=text,text=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=190,check=False)
    if completed.returncode!=0:raise SystemExit('CHAT_OWNER_CANCELLED_NO_CALL')
    result=mobile_operator_client(state_dir,{'op':'chat_approve','request_id':request_id,'review_digest':review['review_digest']})
    print(json.dumps({'ok':result.get('ok') is True,'request_id':request_id,'state':result.get('data',{}).get('state'),
        'automatic_retry':False},ensure_ascii=False))
