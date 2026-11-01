"""Additive signed views of the same canonical MissionService/Core.

No approval/run port. Native host approval remains separate. v1/N1 projection
and transport are preserved; v2 only links typed proposals and observations.
"""
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind
from . import wire
from .service import SCOPE_FIELDS,require,plain


def project(gateway,record):
    require(record.get('schema')=='aioa.agent.mission.v2' and record.get('mode')=='OFFLINE_FIXTURE',503)
    require(all(value is False for value in record['permissions'].values()),503)
    require((record['source_sha'],record['capsule_digest'])==gateway.source,503)
    receipt=record.get('receipt')
    if receipt is not None:
        require(all(receipt.get(k)==record[k] for k in ('task_id','task_digest','source_sha','capsule_digest')),503)
        require(receipt.get('mode')=='OFFLINE_FIXTURE' and receipt.get('live_verified') is False
            and receipt.get('local_readback_verified') is True,503)
    return {**record,'schema':'aioa.mobile.mission-view.v2',
        'owner_scope_digest':gateway.owner_scope_digest,'owner_authority':'NOT_BOUND',
        'billing':'UNVERIFIED','can_run':False,'verified':False,
        'readback_required':record['state']=='AGENT_UNKNOWN','automatic_retry':False}


def _linked(gateway,session,task):
    require(type(task) is str and wire.AGENT_TASK.fullmatch(task),400)
    row=gateway._get('mobile-agent-task-'+task)
    # Check the transport scope BEFORE asking the canonical mission reader.
    require(row is not None and row.payload.get('state')=='MOBILE_AGENT_TASK'
        and all(row.payload[k]==session.data[k] for k in SCOPE_FIELDS),403)
    record=gateway.missions.agent_view(task,gateway.core.local_operator(Capability.READ))
    require(all(row.payload[k]==record[k] for k in ('task_id','task_digest','source_sha','capsule_digest')),503)
    return record


def _key(session,request_id):return 'mobile-agent-proposal-'+wire.digest((session.data['session_id']+request_id).encode())


def _propose(gateway,session,value,*,install=False):
    request_id=value.get('request_id')
    require(type(request_id) is str and wire.HEX32.fullmatch(request_id),400)
    if install:require(set(value)=={'request_id','plan'},400)
    else:
        git=value.get('recipe_id')=='git-commit-v1'
        require(set(value)=={'schema','recipe_id','provider_id','request_id'}|({'source_task_id'} if git else set()),400)
        if git:_linked(gateway,session,value['source_task_id'])
    key=_key(session,request_id);at=int(gateway.clock())
    marker={k:session.data[k] for k in SCOPE_FIELDS}
    marker.update(state='MOBILE_AGENT_PROPOSAL',task_id=None,request_id=request_id,
                  request_digest=wire.digest(wire.canonical(value)))
    def begin(tx):
        require(tx.get(RecordKind.OPERATION,key) is None,409)
        require(len(tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_AGENT_TASK',)))<128,429)
        gateway._record(tx,key,marker,at=at)
    gateway._run(Capability.COMMIT,begin)
    # A crash can leave an orphan pending proposal, never an executable permit.
    # GET reports UNKNOWN and POST is never automatically repeated.
    reader=gateway.core.local_operator(Capability.READ)
    try:
        if install:record=gateway.missions.propose_install(value['plan'],request_id,reader,device_id=session.data['device_id'])
        else:record=gateway.missions.propose_agent(value,reader,device_id=session.data['device_id'])
    except ValueError:raise wire.MobileError(400) from None
    gateway._ready();require((record['source_sha'],record['capsule_digest'])==gateway.source,503)
    linked_at=int(gateway.clock())
    def link(tx):
        row=tx.get(RecordKind.OPERATION,key)
        require(row is not None and row.payload['task_id'] is None,409)
        gateway._record(tx,key,dict(marker,task_id=record['task_id']),row,at=linked_at)
        gateway._record(tx,'mobile-agent-task-'+record['task_id'],{**marker,'state':'MOBILE_AGENT_TASK',
            'task_id':record['task_id'],'task_digest':record['task_digest'],
            'created_order':record['created_at']},at=linked_at)
    gateway._run(Capability.COMMIT,link)
    return project(gateway,record)


def dispatch(gateway,action,identity,session,value):
    require(hasattr(gateway.missions,'agent_route'),503)
    if action=='agent_propose':return _propose(gateway,session,value)
    if action=='agent_install':return _propose(gateway,session,value,install=True)
    if action=='agent_providers':return gateway.missions.provider_catalog(gateway.core.local_operator(Capability.READ))
    if action in ('agent_status','agent_page'):
        rows=gateway._run(Capability.READ,lambda tx:tx.scan(RecordKind.OPERATION,limit=128,states=('MOBILE_AGENT_TASK',)))
        mine=[r for r in rows if all(r.payload[k]==session.data[k] for k in SCOPE_FIELDS)]
        mine.sort(key=lambda r:(r.payload['created_order'],r.payload['task_id']),reverse=True)
        start=0
        if action=='agent_page':
            ids=[r.payload['task_id'] for r in mine];require(identity in ids,403);start=ids.index(identity)+1
        page=mine[start:start+16]
        missions=[]
        for row in page:
            record=_linked(gateway,session,row.payload['task_id'])
            missions.append({k:record[k] for k in ('task_id','task_digest','source_sha','capsule_digest',
                'state','provider_id','model_id','mode','created_at')})
        more=start+len(page)<len(mine)
        return {'schema':'aioa.mobile.agent-status.v2','mode':'OFFLINE_FIXTURE','missions':missions,
            'total_missions':len(mine),'history_truncated':more,
            'next_cursor':page[-1].payload['task_id'] if more else None,
            'owner_authority':'NOT_BOUND','live_verified':False,'automatic_retry':False}
    if action=='agent_proposal':
        row=gateway._get(_key(session,identity))
        require(row is not None and all(row.payload[k]==session.data[k] for k in SCOPE_FIELDS),403)
        if row.payload['task_id'] is None:return {'schema':'aioa.mobile.proposal-readback.v2',
            'state':'AGENT_UNKNOWN','readback_required':True,'automatic_retry':False,'owner_authority':'NOT_BOUND'}
        identity=row.payload['task_id']
    if action=='agent_stop':
        require(set(value)=={'task_id'},400);identity=value['task_id']
    record=_linked(gateway,session,identity)
    if action=='agent_stop':record=gateway.missions.agent_stop(identity,gateway.core.local_operator(Capability.READ))
    return project(gateway,record)
