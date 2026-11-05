"""Exact Native owner binding for the existing Core GitHub remote route.

Muse text is proposal data. This module creates neither a Core nor a governor.
It reuses Native's admitted owner, SQLite, host signer, worker cancellation,
warrant ledger, policy epoch, intent/outbox and ServiceGuard. No ambient gh
credential is used. Every ambiguous mutation is readback-only afterwards.
"""
from dataclasses import replace
from datetime import datetime,timezone
from decimal import Decimal
import re
import threading
import time

from lab.archaioa.authority import AuthorityScope,Money,RiskLevel
from lab.archaioa.warrant import EffectWarrant,RevisionPolicy
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.git_publish import RemoteGitPlan,GitTreeSnapshot,CoreRemoteGitRoute,DEMO_REPOSITORY
from runtime.mission.governor import ReservationRequest
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.warrant import approval_digest,require
from runtime.mobile_gateway import wire
from runtime.mobile_gateway.service import plain
from runtime.providers.exact import CancellationToken
from runtime.mcp_bridge import github_remote

OPS=frozenset(('github_auth_status','github_write_list','github_write_status','github_write_approve',
               'github_write_reconcile','github_write_stop'))


def _source(host):
    return github_remote.GitHubAppCredentialSource(host.root/'github-app',mode='LIVE')


def authorization(host):
    host._require_qualified_operator()
    try:
        config,_=_source(host).configuration()
        return {'status':'APP_CONFIGURED_SCOPE_CHECK_AT_START','configured':True,
            'installation_id':config['installation_id'],'repository':DEMO_REPOSITORY,
            'permissions':dict(github_remote.PERMISSIONS),'scope_verified':False,
            'credential_disclosed':False,'ambient_cli_used':False}
    except ValueError:
        return {'status':'BLOCKED_EXTERNAL','configured':False,'reason':'GITHUB_APP_NOT_CONFIGURED',
            'repository':DEMO_REPOSITORY,'scope_verified':False,'credential_disclosed':False,'ambient_cli_used':False}


def blockers(host):
    host._require_qualified_operator()
    governor=getattr(host.missions,'_chat_governor',None)
    if governor is None:return ['NATIVE_CHAT_GOVERNOR_REQUIRED']
    state=governor.inspect(host.core.local_operator(Capability.READ))
    reasons=[]
    if state['kill']:reasons.append('KILL_SWITCH')
    if any(r['state']=='UNKNOWN' for r in state['reservations'].values()):
        reasons.append('BLOCKED_OWNER_LIABILITY_UNKNOWN')
    if not authorization(host)['configured']:reasons.append('GITHUB_APP_NOT_CONFIGURED')
    return reasons


def _get(host,operation_id):
    return host.mobile._get('native-github-'+operation_id)


def _worker_active(host,operation_id):
    worker=host.missions._workers.get('github-'+operation_id)
    return worker is not None and worker.is_alive()


def history(host):
    host._require_qualified_operator()
    states=('GITHUB_PROPOSAL_READING','GITHUB_PROPOSED','GITHUB_APPROVAL_PENDING',
        'GITHUB_APPROVED','GITHUB_RUNNING','GITHUB_RECONCILING','GITHUB_UNKNOWN','GITHUB_VERIFIED')
    rows=host.mobile._run(Capability.READ,lambda tx:tx.scan(RecordKind.OPERATION,limit=1024,states=states))
    rows=[r.payload for r in rows if r.payload.get('core_instance_id') and r.payload.get('source_chat_request_id')]
    rows.sort(key=lambda p:p['created_at'],reverse=True)
    return {'operations':[{'operation_id':p['operation_id'],'status':p['state'],'created_at':p['created_at'],
        'mode':'APPROVED WRITE' if p.get('warrant') else 'PROPOSE'} for p in rows[:20]],
        'history_truncated':len(rows)>20,'authorization':authorization(host),'blockers':blockers(host),
        'automatic_retry':False}


def _save(host,operation_id,data,*,expected=None):
    def mutation(tx):
        host._require_qualified_operator()
        key='native-github-'+operation_id;prior=tx.get(RecordKind.OPERATION,key)
        require(expected is None or prior is not None and prior.payload['state'] in expected,
                'GITHUB_OPERATION_STATE_CHANGED')
        saved=dict(data)
        if prior is not None and prior.payload.get('stop_requested') is True:saved['stop_requested']=True
        host.mobile._record(tx,key,saved,prior,at=int(time.time()))
    host.mobile._run(Capability.COMMIT,mutation)


def _decode(data):
    p=data['plan']
    plan=RemoteGitPlan(files={k:v.encode() for k,v in p['files'].items()},title=p['pr_title'],body=p['pr_body'],
        **{k:p[k] for k in ('operation_id','issued_at','base_sha','base_tree_sha','source_sha','capsule_digest',
                           'source_reply_sha256','source_receipt_sha256')})
    base=GitTreeSnapshot(p['base_tree_sha'],{k:tuple(v) for k,v in data['base_entries'].items()})
    require(plan.payload()==p,'GITHUB_PLAN_INTEGRITY')
    return plan,base


def _check(host,data,*,write):
    host._require_qualified_operator()
    require(not host.missions._closed,'GITHUB_HOST_CLOSED')
    if write:
        require(host.source==(data['source_sha'],data['capsule_digest'])
            and host.instance_id==data['core_instance_id'],'GITHUB_OWNER_OR_SOURCE_CHANGED')
        require(time.time()<data['expires_at'],'GITHUB_REVIEW_EXPIRED')
        row=_get(host,data['operation_id'])
        require(row is not None and not row.payload.get('stop_requested',False),'GITHUB_STOPPED')
    require(canonical_sha256(data['operation'])==data['review_digest'],'GITHUB_REVIEW_CHANGED')


def _route(host,data,*,write):
    plan,base=_decode(data)
    journal=CoreIntentJournal(host.ledger,host.missions._chat_governor)
    def factory(check,cancel):
        # Called only by ServiceGuard AFTER the exact first START ACK.
        credential=_source(host).mint(cancel=cancel,check=check)
        return github_remote.GitHubCreateOnly(plan,base,credential,mode='LIVE')
    return CoreRemoteGitRoute(journal,plan=plan,base=base,identity=host.identity,
        api_factory=factory,check=lambda:_check(host,data,write=write),
        target_guard=lambda:host.missions._lock,mode='LIVE')


def propose(host,value,message):
    """Only reached after native_tools verified a current successful Muse turn."""
    operation_id=value['request_id'];old=_get(host,operation_id)
    if old is not None:
        require(old.payload.get('source_chat_request_id')==value['chat_request_id'],'GITHUB_REQUEST_CONFLICT')
        return view(host,operation_id)
    now=int(time.time())
    pending={'state':'GITHUB_PROPOSAL_READING','operation_id':operation_id,
        'source_chat_request_id':value['chat_request_id'],'source_reply_sha256':message['receipt']['response_sha256'],
        'source_sha':host.source[0],'capsule_digest':host.source[1],'core_instance_id':host.instance_id,
        'created_at':now,'expires_at':now+300,'stop_requested':False,'warrant':None}
    def reserve(tx):
        host._require_qualified_operator()
        key='native-github-source-'+value['chat_request_id']
        prior=tx.get(RecordKind.OPERATION,key)
        if prior is not None:
            require(prior.payload['source_reply_sha256']==pending['source_reply_sha256'],
                    'GITHUB_MODEL_SOURCE_CONFLICT')
            return prior.payload['operation_id'],False
        host.mobile._record(tx,key,{'state':'GITHUB_SOURCE_BINDING','operation_id':operation_id,
            'source_reply_sha256':pending['source_reply_sha256'],'source_chat_request_id':value['chat_request_id']},at=now)
        host.mobile._record(tx,'native-github-'+operation_id,pending,at=now)
        return operation_id,True
    bound,first=host.mobile._run(Capability.COMMIT,reserve)
    if not first:return view(host,bound)
    base_sha,base=github_remote.read_demo_base(check=host._require_qualified_operator,cancel=CancellationToken())
    plan=RemoteGitPlan.from_model(message['reply'].encode(),operation_id=operation_id,issued_at=now,
        base_sha=base_sha,base_tree_sha=base.sha,source_sha=host.source[0],capsule_digest=host.source[1],
        source_reply_sha256=message['receipt']['response_sha256'],source_receipt_sha256=canonical_sha256(message['receipt']))
    data={**pending,'plan':plan.payload(),'base_entries':{k:list(v) for k,v in base.entries.items()}}
    state=host.missions._chat_governor.inspect(host.core.local_operator(Capability.READ))
    route=_route(host,data,write=True)
    operation=route.operation(host.instance_id,state['epoch'])
    data.update(state='GITHUB_PROPOSED',operation=operation,review_digest=canonical_sha256(operation),
        policy_decision={'decision':'PROPOSE_ONLY','reasons':blockers(host),'observed_at':int(time.time())})
    host._require_qualified_operator()
    _save(host,operation_id,data,expected={'GITHUB_PROPOSAL_READING'})
    return view(host,operation_id)


def view(host,operation_id):
    host._require_qualified_operator();row=_get(host,operation_id)
    if row is None:return {'status':'NOT_FOUND','operation_id':operation_id,'execution_authorized':False,'automatic_retry':False}
    data=plain(row.payload);data.pop('schema',None)
    result={'status':data['state'],'operation_id':operation_id,'execution_authorized':False,
        'automatic_retry':False,'authorization':authorization(host),'blockers':blockers(host),
        'proposal':{'operation':'code.commit_draft_pr','target_repo':DEMO_REPOSITORY,
                    'source_chat_request_id':data['source_chat_request_id']}}
    if 'plan' in data:
        plan,_=_decode(data);result.update(review={**plan.preview(),
            'expected_commit_sha':data['operation']['payload']['commit_sha'],
            'expected_tree_sha':data['operation']['payload']['tree_sha'],
            'policy_epoch':data['operation']['payload']['policy_epoch']},review_digest=data['review_digest'],
            expires_at=data['expires_at'],owner_approval=data.get('warrant') is not None)
        if host.instance_id!=data['core_instance_id'] or host.source!=(data['source_sha'],data['capsule_digest']):
            result['blockers'].append('GITHUB_OWNER_OR_SOURCE_CHANGED')
        if time.time()>=data['expires_at']:result['blockers'].append('GITHUB_REVIEW_EXPIRED')
        if data.get('stop_requested') is True:result['blockers'].append('GITHUB_STOPPED')
        saved=host.mobile._get('github-result-'+operation_id)
        if saved is not None:result['result']=plain(saved.payload['result'])
        result['approval_available']=data['state']=='GITHUB_PROPOSED' and not result['blockers']
        active=_worker_active(host,operation_id)
        result['readback_available']=data.get('warrant') is not None and not active
        # Expired owner admission may prevent the worker's final local save.
        # A dead worker is uncertain even if this same Native was renewed.
        if not active and data['state'] in ('GITHUB_APPROVED','GITHUB_RUNNING','GITHUB_RECONCILING'):
            result.update(status='GITHUB_UNKNOWN',readback_available=True)
    if 'error' in data:result['error']=data['error']
    if 'policy_decision' in data:result['policy_decision']=data['policy_decision']
    result['signature']=host.identity.sign(result)
    require(len(wire.canonical(result))<=wire.RESPONSE_LIMIT,'GITHUB_REVIEW_RESPONSE_LIMIT')
    return result


def _warrant(host,data,route):
    operation=data['operation'];now=host.ledger.clock()
    deadline=min(data['expires_at'],time.time()+min(240,host._auth_deadline-time.monotonic()))
    expiry=datetime.fromtimestamp(deadline,timezone.utc)
    require((expiry-now).total_seconds()>=120,'GITHUB_OWNER_LEASE_TOO_SHORT')
    task='github-'+data['operation_id']
    scope=AuthorityScope(operation_classes=(operation['operation_class'],),target_scope=operation['target_fingerprint'],
        risk_ceiling=RiskLevel.MODERATE,monetary_ceiling=Money(Decimal(0),'USD'),not_before=now,expires_at=expiry,
        owner_scope=canonical_sha256(host.missions.scope),task_scope=task)
    warrant=EffectWarrant(warrant_id='warrant-'+task,task_id=task,owner_scope=scope.owner_scope,
        operation_class=operation['operation_class'],operation_hash='sha256:'+canonical_sha256(operation),
        target_fingerprint=operation['target_fingerprint'],expected_target_revision=operation['expected_target_revision'],
        revision_policy=RevisionPolicy.REQUIRE,decision_dependency_root=route.dependency_root,
        lease_epoch=operation['payload']['policy_epoch'],authority_scope=scope,approval_digest='sha256:'+'0'*64,
        money_reservation_id='NONE',risk_reservation_id='risk-'+task,nonce='nonce-'+task,issued_at=now,expires_at=expiry)
    return replace(warrant,approval_digest=approval_digest(warrant))


def _worker(host,data,warrant,cancel,*,reconcile=False):
    operation_id=data['operation_id']
    try:
        route=_route(host,data,write=not reconcile)
        commit=host.core.local_operator(Capability.COMMIT)
        if reconcile:
            outcome=route.reconcile(commit,warrant,cancel=cancel)
        else:
            data={**data,'state':'GITHUB_RUNNING'}
            _save(host,operation_id,data,expected={'GITHUB_APPROVED'})
            from runtime.providers.meta_model_api import MODEL
            reserve=ReservationRequest(warrant.risk_reservation_id,warrant.task_id,'github',MODEL,
                canonical_sha256(data['operation']),0,1)
            outcome=route.dispatch(commit,warrant,data['operation'],reserve,cancel=cancel)
        state='GITHUB_VERIFIED' if outcome['outcome']['contract_type']=='Applied' else 'GITHUB_UNKNOWN'
        _save(host,operation_id,{**data,'state':state},expected={'GITHUB_RUNNING','GITHUB_RECONCILING'})
    except Exception as error:
        code=str(error)
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,99}',code):code='GITHUB_OUTCOME_UNKNOWN_READBACK_REQUIRED'
        try:_save(host,operation_id,{**data,'state':'GITHUB_UNKNOWN','error':code})
        except Exception:pass  # Existing intent/step markers remain authoritative.


def dispatch(host,owner,value):
    host._require_qualified_operator();host.core.require(owner,Capability.OWNER_APPROVAL,scope=host.missions.scope)
    op=value['op']
    if op in ('github_auth_status','github_write_list'):
        if set(value)!={'op'}:raise wire.MobileError(400)
        return authorization(host) if op=='github_auth_status' else history(host)
    expected={'op','operation_id','review_digest'} if op=='github_write_approve' else {'op','operation_id'}
    if (op not in OPS or set(value)!=expected or type(value.get('operation_id')) is not str
            or not wire.HEX32.fullmatch(value['operation_id'])):raise wire.MobileError(400)
    identity=value['operation_id']
    if op=='github_write_status':return view(host,identity)
    row=_get(host,identity)
    if row is None:raise wire.MobileError(409)
    data=plain(row.payload);data.pop('schema',None)
    if op=='github_write_stop':
        token=host.missions._cancels.get('github-'+identity)
        if token:token.cancel()
        _save(host,identity,{**data,'stop_requested':True})
        raw=data.get('warrant') or data.get('candidate_warrant')
        if raw:
            warrant=EffectWarrant.from_dict(raw)
            if host.mobile._get(host.ledger._key(warrant)) is not None:host.ledger.revoke(owner,warrant)
        return view(host,identity)
    with host.missions._lock:
        if op=='github_write_approve':
            if data.get('state')!='GITHUB_PROPOSED' or value['review_digest']!=data.get('review_digest'):
                raise wire.MobileError(409)
            _check(host,data,write=True)
            reasons=blockers(host)
            if reasons:
                _save(host,identity,{**data,'policy_decision':{'decision':'DENY','reasons':reasons,
                    'review_digest':data['review_digest'],'observed_at':int(time.time())}},expected={'GITHUB_PROPOSED'})
                blocked=view(host,identity);blocked.pop('signature')
                blocked.update(status='BLOCKED_EXTERNAL',execution_authorized=False)
                blocked['signature']=host.identity.sign(blocked)
                return blocked
            route=_route(host,data,write=True);warrant=_warrant(host,data,route)
            # Durable pre-approval marker makes a lost approval ACK non-repeatable.
            data={**data,'state':'GITHUB_APPROVAL_PENDING','candidate_warrant':warrant.to_dict(),
                'policy_decision':{'decision':'EXACT_OWNER_APPROVAL','review_digest':data['review_digest'],
                    'observed_at':int(time.time()),'warrant_digest':warrant.digest()}}
            _save(host,identity,data,expected={'GITHUB_PROPOSED'})
            host.ledger.approve(owner,warrant)
            data={**data,'state':'GITHUB_APPROVED','warrant':warrant.to_dict()}
            _save(host,identity,data,expected={'GITHUB_APPROVAL_PENDING'})
        else:
            if not data.get('warrant') or _worker_active(host,identity):raise wire.MobileError(409)
            warrant=EffectWarrant.from_dict(data['warrant'])
            data={**data,'state':'GITHUB_RECONCILING'};_save(host,identity,data)
        cancel=CancellationToken();key='github-'+identity
        worker=threading.Thread(target=_worker,args=(host,data,warrant,cancel),
            kwargs={'reconcile':op=='github_write_reconcile'},daemon=True)
        host.missions._cancels[key]=cancel;host.missions._workers[key]=worker;worker.start()
    return view(host,identity)
