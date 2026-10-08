"""Governor-owned offline job transitions; no loop, store, transport or authority.

The supplied governor/runner own paired budget and immutable native records.
A newly ACKed START permits one synthetic fixture step only. No live provider
or effect executor is imported/wired; every result remains UNVERIFIED advice.
"""
from dataclasses import asdict
from datetime import datetime,timezone
from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event,decode_audit,domain_chain
from runtime.memory_patch.contracts.serialization import canonical_sha256,canonical_json_bytes,freeze_json
from runtime.memory_patch.persistence.idempotency import OperationBinding,execute_once
from runtime.memory_patch.persistence.ports import RecordKind,TransactionContext
from runtime.mission.governor import ReservationRequest,_deny,_identity,_plain
from runtime.mission.job_contracts import JobEnvelope,JobClaim
from runtime.providers.nvidia import ProviderResponse,OUTPUT_SCHEMA
from runtime.service_guard.contracts import parse_proposal

KIND='aioa-offline-advisory-job-v1'
STATES={'QUEUED','CLAIMED','STARTED','UNKNOWN','DONE'}


def key(gov,task,version):return canonical_sha256((KIND,gov.policy.scope,gov.policy.deployment_id,task,version))
def reservation_id(gov,task):return 'job-'+key(gov,task,0)

def load_job(gov,tx,task):
    domain_chain(tx)
    records=tx.scan(RecordKind.OPERATION,limit=1024)
    _deny(len(records)<1024,'HISTORY_QUOTA')
    found=[]
    for row in records:
        if row.payload.get('operation_kind')!=KIND:continue
        p=row.payload
        _deny(set(p)=={'operation_kind','payload_digest','outcome'} and p['payload_digest']==canonical_sha256(p['outcome']),'GOVERNOR_INTEGRITY')
        o=p['outcome'];_deny(set(o)=={'job','prior_digest'},'GOVERNOR_INTEGRITY');j=o['job']
        envelope=JobEnvelope.parse(j['envelope'])
        _deny(set(j)=={'version','envelope','state','claim','result_digest','reservation_id','last_now'}
            and j['state'] in STATES and type(j['version']) is int and 1<=j['version']<=128
            and type(j['last_now']) is int and 0<=j['last_now']<=2**53
            and envelope.scope==gov.policy.scope and row.record_id==key(gov,envelope.task_id,j['version'])
            and j['reservation_id']==reservation_id(gov,envelope.task_id),'GOVERNOR_INTEGRITY')
        if j['claim'] is not None:
            claim=JobClaim(**j['claim'])
            _deny(claim.task_id==envelope.task_id and claim.envelope_digest==envelope.envelope_digest,'GOVERNOR_INTEGRITY')
        else:_deny(j['state']=='QUEUED','GOVERNOR_INTEGRITY')
        _deny((j['result_digest'] is not None)==(j['state']=='DONE'),'GOVERNOR_INTEGRITY')
        if j['result_digest'] is not None:
            from runtime.mission.governor import _digest
            _digest(j['result_digest'])
        event_row=tx.get(RecordKind.AUDIT,'job-'+row.record_id)
        _deny(event_row is not None,'GOVERNOR_INTEGRITY');event=decode_audit(event_row)
        operation=OperationBinding(row.record_id,KIND,p['payload_digest'])
        outbox=tx.get(RecordKind.OUTBOX,'job-outbox-'+row.record_id)
        _deny(event.resource_id==row.record_id and event.event_type==KIND
            and event.content_hashes.get('content')==canonical_sha256(j)
            and event.content_hashes.get('operation')==p['payload_digest']
            and outbox is not None and set(outbox.payload)=={'state','event_id','event_digest','operation_digest','proof_id','core_entry_hash'}
            and outbox.payload['state'] in ('PENDING','PUBLISHED')
            and outbox.payload['event_id']=='job-'+row.record_id and outbox.payload['proof_id']=='job-outbox-'+row.record_id
            and outbox.payload['event_digest']==event.event_hash
            and outbox.payload['operation_digest']==canonical_sha256({'scope':gov.policy.scope.binding(),'operation':operation}),'GOVERNOR_INTEGRITY')
        if envelope.task_id==task:found.append(o)
    current=None
    for o in sorted(found,key=lambda row:row['job']['version']):
        _deny(o['job']['version']==(1 if current is None else current['version']+1)
            and o['prior_digest']==canonical_sha256(current),'GOVERNOR_INTEGRITY')
        if current is not None:
            _deny(canonical_sha256(o['job']['envelope'])==canonical_sha256(current['envelope']) and o['job']['last_now']>=current['last_now'],'GOVERNOR_INTEGRITY')
        current=_plain(o['job'])
    return current


def write_job(gov,tx,before,job,now):
    _deny(before is None or before['version']<128,'HISTORY_QUOTA')
    job['version']=1 if before is None else before['version']+1;job['last_now']=now
    envelope=JobEnvelope.parse(job['envelope'])
    outcome={'job':job,'prior_digest':canonical_sha256(before)}
    operation=OperationBinding.bind(key(gov,envelope.task_id,job['version']),KIND,outcome)
    def append():
        append_domain_event(tx,operation,event_id='job-'+operation.idempotency_key,
            proof_id='job-outbox-'+operation.idempotency_key,resource_id=operation.idempotency_key,
            before=before['state'] if before else None,after=job['state'],content_digest=canonical_sha256(job),
            at=datetime.fromtimestamp(now,timezone.utc))
        return outcome
    execute_once(tx,operation,append)


def public(job):
    if job is None:return {'state':'NOT_FOUND','authority':'NONE','auto_retry':False}
    return {**_plain(job),'authority':'NONE','verification':'UNVERIFIED','transport_scope':'OFFLINE',
        'auto_retry':False,'reconcile_only':job['state'] in ('STARTED','UNKNOWN'),
        'execution_authority':False}


def change_job(gov,principal,action,*,task_id=None,envelope=None,worker_id=None,epoch=None,lease_seconds=None,claim=None,response=None):
    purpose=Capability.READ if action=='inspect' else Capability.MANAGE if action in ('submit','takeover') else Capability.COMMIT
    gov._require(principal,purpose);now=None if action=='inspect' else gov._now()
    if envelope is not None:
        _deny(type(envelope) is JobEnvelope,'INVALID_RESERVATION_REQUEST')
        envelope=JobEnvelope.parse(envelope.as_dict());task_id=envelope.task_id
        _deny(envelope.scope==gov.policy.scope,'INVALID_RESERVATION_REQUEST')
    if claim is not None:
        _deny(type(claim) is JobClaim,'INVALID_RESERVATION_REQUEST')
        claim=JobClaim(**asdict(claim));task_id=claim.task_id;epoch=claim.governor_epoch
    _identity(task_id)
    if action in ('claim','takeover','renew'):
        _deny(type(lease_seconds) is int and 1<=lease_seconds<=60,'INVALID_RESERVATION_REQUEST')
        if worker_id is not None:_identity(worker_id)
    result_digest=None
    if action=='finish':
        _deny(type(response) is ProviderResponse and response.authority=='ADVISORY_ONLY'
            and response.validation_result=='VALID' and response.finish_reason=='stop'
            and response.http_status==200 and type(response.raw_size) is int and 0<=response.raw_size<=16384,'INVALID_RESERVATION_REQUEST')
        # No payload persisted; hash a bounded exact native response locally.
        _deny(len(canonical_json_bytes(response))<=32768,'INVALID_RESERVATION_REQUEST')
        response=ProviderResponse(**freeze_json(_plain(response)))
        result_digest=canonical_sha256(response)
    def apply(tx):
        before_state=gov._load(tx);state=_plain(before_state);before=load_job(gov,tx,task_id)
        job=_plain(before) if before is not None else None;gov_changed=False;changed=False
        if action=='inspect':return public(job)
        gov._clock(state,now)
        _deny(state['epoch']>0,'STALE_EPOCH')
        if job is not None:_deny(now>=job['last_now'],'CLOCK_UNSAFE')
        if action=='submit':
            _deny(envelope.model_id in principal.model_binding_ids,'MODEL_BINDING_DENIED')
            if job is not None:
                _deny(job['envelope']==envelope.as_dict(),'IDEMPOTENCY_CONFLICT');return public(job)
            _deny(now<envelope.deadline_at,'INVALID_RESERVATION_REQUEST')
            job={'version':0,'envelope':envelope.as_dict(),'state':'QUEUED','claim':None,'result_digest':None,
                'reservation_id':reservation_id(gov,task_id),'last_now':now};changed=True
        else:
            _deny(job is not None,'RESERVATION_REQUIRED');env=JobEnvelope.parse(job['envelope'])
            gov._epoch(state,epoch)
            if action in ('claim','takeover'):
                _deny(not state['kill'],'KILL_SWITCH');_deny(now<env.deadline_at,'INVALID_RESERVATION_REQUEST')
                if action=='claim' and job['state']=='CLAIMED':
                    old=JobClaim(**job['claim'])
                    _deny(old.worker_id==worker_id and old.governor_epoch==epoch and now<old.lease_until,'STALE_RESERVATION_EPOCH')
                    return asdict(old)
                if action=='claim':_deny(job['state']=='QUEUED','INVALID_RESERVATION_REQUEST')
                else:
                    _deny(job['state'] in ('CLAIMED','STARTED','UNKNOWN') and now>=job['claim']['lease_until'],'INVALID_RESERVATION_REQUEST')
                request=ReservationRequest(job['reservation_id'],task_id,'nebius',env.model_id,env.envelope_digest,env.money_nano,env.risk_units)
                _deny(env.model_id in principal.model_binding_ids,'MODEL_BINDING_DENIED')
                entry,gov_changed=gov._reserve_state(state,request,epoch,now)
                if action=='takeover' and job['state']=='CLAIMED' and entry['epoch']!=epoch:
                    _deny(entry['state']=='RESERVED','STALE_RESERVATION_EPOCH')
                    entry['epoch']=epoch;gov_changed=True
                if action=='takeover' and job['state']=='STARTED' and entry['state']=='DISPATCHED':
                    _,changed_unknown=gov._unknown_state(state,job['reservation_id'],epoch,
                        canonical_sha256(('expired-job-lease',env.envelope_digest,job['claim'])),now)
                    gov_changed=gov_changed or changed_unknown
                fence=1 if job['claim'] is None else job['claim']['fence']+1
                new=JobClaim(task_id,env.envelope_digest,worker_id,fence,epoch,min(now+lease_seconds,env.deadline_at))
                job['claim']=asdict(new)
                job['state']='UNKNOWN' if job['state'] in ('STARTED','UNKNOWN') else 'CLAIMED'
                changed=True
            else:
                _deny(claim is not None and job['claim']==asdict(claim),'STALE_RESERVATION_EPOCH')
                if action=='begin' and job['state'] in ('STARTED','UNKNOWN','DONE'):
                    return {'fixture_step_now':False,**public(job)}
                if action=='finish' and job['state']=='DONE':
                    _deny(job['result_digest']==result_digest,'IDEMPOTENCY_CONFLICT');return public(job)
                _deny(now<claim.lease_until and now<env.deadline_at,'STALE_RESERVATION_EPOCH')
                if action=='renew':
                    _deny(job['state']=='CLAIMED' and not state['kill'],'INVALID_RESERVATION_REQUEST')
                    new=JobClaim(task_id,claim.envelope_digest,claim.worker_id,claim.fence,epoch,
                        max(claim.lease_until,min(now+lease_seconds,env.deadline_at)))
                    job['claim']=asdict(new);changed=job['claim']!=before['claim']
                elif action=='begin':
                    _deny(job['state']=='CLAIMED','INVALID_RESERVATION_REQUEST')
                    marker,gov_changed=gov._dispatch_state(state,job['reservation_id'],epoch,now)
                    _deny(marker['dispatch_now'],'DISPATCH_MARKER_REQUIRED')
                    job['state']='STARTED';changed=True
                elif action=='finish':
                    _deny(job['state']=='STARTED' and response.model_id==env.model_id and response.request_id==env.request_id,'INVALID_RESERVATION_REQUEST')
                    payload=_plain(response.parsed_payload)
                    if env.output_schema==OUTPUT_SCHEMA:
                        _deny(type(payload) is dict and set(payload)=={'summary','needs_attention'}
                            and type(payload['summary']) is str and 1<=len(payload['summary'])<=800
                            and type(payload['needs_attention']) is bool,'INVALID_RESERVATION_REQUEST')
                    else:parse_proposal(payload)
                    _,gov_changed=gov._settle_state(state,job['reservation_id'],epoch,result_digest)
                    job.update(state='DONE',result_digest=result_digest);changed=True
                else:_deny(False,'INVALID_RESERVATION_REQUEST')
        if gov_changed or changed:gov._write(tx,before_state,state,now)
        if changed:write_job(gov,tx,before,job,now)
        if action in ('claim','takeover','renew'):return job['claim']
        return {'fixture_step_now':action=='begin' and changed,**public(job)} if action=='begin' else public(job)
    result=gov.runner.run(TransactionContext(principal,purpose),apply)
    if action in ('claim','takeover','renew'):return JobClaim(**result)
    if action=='begin' and result['fixture_step_now']:
        # Expiry during durable persistence consumes START but grants no step;
        # the retained marker can only be inspected/reconciled, never restarted.
        after=gov._now()
        result['fixture_step_now']=now<=after<claim.lease_until and after-now<=gov.policy.max_clock_step_seconds
    return result
