"""Typed operation ports of the existing MissionService, not another runtime.

All state is in its existing native transaction runner. This initial executable
profile is explicitly OFFLINE; production owner admission is NOT_BOUND.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
import re
import stat
import threading

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import Capability
from runtime.memory_patch.audit import append_domain_event
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits, ReservationRequest
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.liability import CoreLiabilityLedger
from runtime.mission.project_recipe import SensorBridgePlan
from runtime.mission.sandbox_contracts import SandboxDispatchRequest
from runtime.mission.sandbox_linux import (LinuxSandboxBroker, TrustedSandboxConfig, prepare_linux_sandbox,
    save_host_config,load_host_config,read_evidence_file)
from runtime.mission.tools import CoreToolRoute, LocalSessionGrant
from runtime.mission.warrant import approval_digest
from runtime.providers.exact import CancellationToken
from runtime.providers.meta_model_api import MODEL, PROVIDER

KIND = 'aioa.agent.mission.v2'
STATES = ('AGENT_PENDING','AGENT_APPROVED','AGENT_RUNNING','AGENT_COMPLETED',
          'AGENT_FAILED','AGENT_UNKNOWN','AGENT_STOPPED')
ACTIVE = frozenset(STATES[:3])
PERMISSIONS = {key:False for key in ('run','approve','native_execute','install','github_write','meta_spend')}


def require(value, code='AGENT_REQUEST_DENIED'):
    if not value: raise ValueError(code)


def plain(value): return json.loads(canonical_json_bytes(value))


def _rows(service):
    rows = service._run(Capability.READ, lambda tx: tx.scan(RecordKind.OPERATION, limit=1024, states=STATES))
    require(len(rows)<1024, 'AGENT_HISTORY_LIMIT')
    return tuple(row for row in rows if row.payload.get('schema') == KIND)


def _get(service, task):
    require(type(task) is str and re.fullmatch(r'agent-[0-9a-f]{32}', task), 'AGENT_TASK_REQUIRED')
    row = service._run(Capability.READ, lambda tx: tx.get(RecordKind.OPERATION, task))
    require(row is not None and row.payload.get('schema') == KIND, 'AGENT_NOT_FOUND')
    return row


def _save(service, tx, data, row=None):
    revision = row.revision+1 if row else 1
    record = StoredRecord(RecordKind.OPERATION, data['task_id'], service.scope, revision, data)
    if row: tx.replace(record, expected_revision=row.revision)
    else: tx.insert(record)
    identity = canonical_sha256([record.record_id, revision])
    binding = OperationBinding.bind('agent-change-'+identity, 'AGENT_MISSION_RECORD',
        {'record_digest': record.payload_digest, 'source_sha': data['source_sha'],
         'capsule_digest': data['capsule_digest']})
    append_domain_event(tx, binding, event_id='agent-audit-'+identity,
        proof_id='agent-outbox-'+identity, resource_id=record.record_id,
        before=row.payload['state'] if row else None, after=data['state'],
        content_digest=record.payload_digest, at=service.ledger.clock())


def _change(service, task, allowed, state, **updates):
    require(state in STATES)
    def change(tx):
        row=tx.get(RecordKind.OPERATION,task)
        require(row is not None and row.payload.get('schema')==KIND, 'AGENT_NOT_FOUND')
        data=plain(row.payload)
        if data['state'] not in allowed: return data
        data.update(updates,state=state); _save(service,tx,data,row)
        return data
    return service._run(Capability.COMMIT,change)


def recover(service):
    for row in _rows(service):
        if row.payload['state'] in ACTIVE:
            _change(service,row.record_id,ACTIVE,'AGENT_UNKNOWN',error='RESTART_READBACK_REQUIRED')


def bind_tools(service, config, owner):
    service.core.require(owner,Capability.OWNER_APPROVAL,scope=service.scope)
    require(type(config) is TrustedSandboxConfig and not service._closed, 'AGENT_TOOLS_REQUIRED')
    # This profile cannot silently become native production authority.
    require(service.scope.tenant_id=='offline-fixture' and service.manager._meta_provider.mode=='MOCK',
            'AGENT_PRODUCTION_OWNER_NOT_BOUND')
    require(not hasattr(service,'agent_route'), 'AGENT_TOOLS_ALREADY_BOUND')
    require({r.recipe_id for r in config.registry.recipes}=={'recipe:sensorbridge-v1'}, 'AGENT_REGISTRY_DENIED')
    limits=Limits(0,64)
    service.agent_governor=CoreDualGovernor(service.core,service.runner,
        GovernorPolicy(service.scope,'unified-local-v2',Limits(0,4),limits,limits,
                       max_clock_step_seconds=86400))
    service.agent_epoch=service.agent_governor.start_epoch(service.core.local_operator(Capability.MANAGE))
    service.agent_journal=CoreIntentJournal(service.ledger,service.agent_governor)
    service.agent_broker=LinuxSandboxBroker(config)
    service.agent_config=config
    service._agent_effect_lock=threading.RLock()
    service.cpl_veto_reader=lambda:False  # declared fixture-only; not a LIVE CPL certificate
    liability=CoreLiabilityLedger(service.core,service.runner,service.scope)
    service.agent_route=_make_route(service, config, service.agent_broker, liability)
    service._agent_routes={'sensorbridge':service.agent_route}
    service._agent_configs={'sensorbridge':config}
    service._agent_brokers={'sensorbridge':service.agent_broker}


def _make_route(service, config, broker, liability=None):
    liability=liability or CoreLiabilityLedger(service.core,service.runner,service.scope)
    return CoreToolRoute(service.agent_journal,liability,
        workspace=config.registry.workspace,policy_revision=2,probe=lambda:None,
        executor=lambda operation,warrant,release,cancel: broker.dispatch(
            dispatch_request(operation,warrant),release,cancel=cancel),
        target_guard=lambda:service._agent_effect_lock,
        verifier=broker.verify, variant='sandbox',sandbox_registry=config.registry)


def _git_config(service, plan):
    from dataclasses import replace as dc_replace
    from runtime.mission.sandbox_contracts import SandboxRegistry
    key='git-plan-'+plan.digest
    require(key not in service._agent_configs,'GIT_PREPARATION_ALREADY_EXISTS')
    config=prepare_linux_sandbox(service.agent_config.root.parent/key,service.agent_config.runtime(),
        workspace=service.agent_route.workspace,recipes={'recipe:git-commit-v3':plan.recipe_spec()})
    config=dc_replace(config,registry=SandboxRegistry(config.registry.workspace,tuple(
        dc_replace(r,timeout_ms=20000,max_output_bytes=16384) for r in config.registry.recipes)))
    save_host_config(config)
    broker=LinuxSandboxBroker(config)
    service._agent_configs[key]=config;service._agent_brokers[key]=broker
    service._agent_routes[key]=_make_route(service,config,broker)
    return key,config


def _local_binding(service,data):
    key=data['config_ref']
    if key not in service._agent_routes and re.fullmatch(r'git-plan-[a-f0-9]{64}',key):
        config=load_host_config(service.agent_config.root.parent/key,trusted_root=service.agent_config.root.parent)
        require(config.registry.workspace==service.agent_route.workspace,'AGENT_WORKSPACE_CHANGED')
        broker=LinuxSandboxBroker(config)
        service._agent_configs[key]=config;service._agent_brokers[key]=broker
        service._agent_routes[key]=_make_route(service,config,broker)
    require(key in service._agent_routes,'AGENT_READBACK_CONFIG_NOT_BOUND')
    return service._agent_routes[key],service._agent_configs[key],service._agent_brokers[key]


def propose(service, payload, reader, *, device_id='local-host'):
    service.core.require(reader,Capability.READ,scope=service.scope)
    require(hasattr(service,'agent_route') and not service._closed, 'AGENT_TOOLS_NOT_BOUND')
    git=type(payload) is dict and payload.get('recipe_id')=='git-commit-v1'
    require(type(payload) is dict and set(payload)=={'schema','recipe_id','provider_id','request_id'}|({'source_task_id'} if git else set())
        and payload['schema']=='aioa.agent-proposal.v2' and payload['recipe_id'] in ('sensorbridge-v1','git-commit-v1')
        and payload['provider_id']==PROVIDER and type(payload['request_id']) is str
        and re.fullmatch(r'[0-9a-f]{32}',payload['request_id']), 'AGENT_PROPOSAL_DENIED')
    require(type(device_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}',device_id), 'AGENT_DEVICE_DENIED')
    with service._lock:
        sha,capsule=service.source_probe(); now=int(service.ledger.clock().timestamp())
        task='agent-'+canonical_sha256([service.scope.binding(),device_id,payload['request_id']])[:32]
        for row in _rows(service):
            if row.record_id==task:
                require(row.payload['request_digest']==canonical_sha256(payload)
                    and row.payload['device_id']==device_id,'AGENT_REQUEST_CONFLICT')
                return view(service,task,reader)
            require(row.payload['state'] not in ACTIVE,'AGENT_ACTIVE')
        plan=SensorBridgePlan('fixture:sensorbridge'); files={} if git else plan.files()
        config_ref,config='sensorbridge',service.agent_config
        operation_class,recipe_id,revision='SANDBOX_EXEC','recipe:sensorbridge-v1','sensorbridge-v1'
        git_preview=None
        if git:
            from runtime.mission.git_publish import LocalGitPlan
            source=plain(_get(service,payload['source_task_id']).payload)
            require(source['state']=='AGENT_COMPLETED' and source['receipt']['local_readback_verified'] is True
                and source['source_sha']==sha and source['capsule_digest']==capsule
                and source['approval_payload']['operation']['operation_class']=='SANDBOX_EXEC', 'GIT_VERIFIED_SOURCE_REQUIRED')
            _,source_config,broker=_local_binding(service,source)
            source_operation=source['approval_payload']['operation']
            source_warrant=EffectWarrant.from_dict(source['warrant'])
            broker.verify(source_operation,source_warrant)
            source_run=source_config.root/('run-'+dispatch_request(source_operation,source_warrant).digest)
            require(source['receipt']['files']==source_operation['payload']['manifest'],'GIT_SOURCE_RECEIPT_CHANGED')
            for name,pin in source['receipt']['files'].items():
                require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name),'GIT_SOURCE_PATH_DENIED')
                content=read_evidence_file(source_run,'artifact-'+name,8192)
                require(len(content)==pin['bytes'] and hashlib.sha256(content).hexdigest()==pin['sha256'],
                        'GIT_VERIFIED_SOURCE_CHANGED')
                files[name]=content
            plan=LocalGitPlan(files,canonical_sha256(source['receipt']),task[-32:])
            config_ref,config=_git_config(service,plan)
            operation_class,recipe_id,revision='GIT_COMMIT','recipe:git-commit-v3','empty-repo-v1'
            git_preview=plan.preview()
        request_digest=canonical_sha256(payload)
        task_digest=canonical_sha256({'task_id':task,'request_digest':request_digest,
            'source_sha':sha,'capsule_digest':capsule,'manifest':plan.manifest(),
            'owner_scope':service.scope.binding(),'device_id':device_id})
        grant=LocalSessionGrant(session_id='session-'+task,scope=service.scope,
            workspace=service.agent_route.workspace,policy_revision=2,capabilities=(operation_class,),
            completion_digest=task_digest,issued_at=now,expires_at=now+300,epoch=service.agent_epoch,
            money_nano=0,risk_units=1,deadline_seconds=20,output_bytes=16384)
        fingerprint='sha256:'+canonical_sha256([grant.workspace,plan.digest,config.profile_digest,0])
        inner={'operation_class':'SANDBOX_EXEC','target_fingerprint':fingerprint,
            'expected_target_revision':revision, 'payload':config.registry.payload({
                'action':'run_recipe','recipe_id':recipe_id,'task_id':task,'step_id':'commit' if git else 'create-test'})}
        operation={'operation_class':operation_class,'target_fingerprint':fingerprint,
            'expected_target_revision':revision,'payload':{
                'schema':'aioa.local-operation.v2','operation_id':task,'workspace':grant.workspace,
                'principal_session_id':reader.actor_session_id,'session_id':grant.session_id,
                'session_grant_digest':grant.digest,'policy_epoch':service.agent_epoch,
                'device_id':device_id,'task_digest':task_digest,'source_sha':sha,'capsule_digest':capsule,
                'scope':list(files),'manifest':plan.manifest(),'expiry':grant.expires_at,
                'sandbox_operation':inner}}
        approval={'operation':operation,'session_grant':grant.to_dict(),
            'summary':'Create an exact local commit of verified SensorBridge files in a fresh isolated Git repository.' if git else
                'Create SensorBridge files in a fresh isolated workspace and run 5 registered Python tests.',
            'includes':['GIT_COMMIT'] if git else ['WORKSPACE_WRITE','SANDBOX_EXEC'],'risk_units':1,'budget_usd':'0',
            'network':'OFF','provider_id':PROVIDER,'model_id':MODEL,'mode':'OFFLINE_FIXTURE',
            'planner':'REGISTERED_RECIPE_NO_MODEL_CALL','files':{n:{**plan.manifest()[n],
                'text':d.decode('utf-8')} for n,d in files.items()},'git':git_preview}
        data={'schema':KIND,'task_id':task,'task_digest':task_digest,'request_digest':request_digest,
            'device_id':device_id,'source_sha':sha,'capsule_digest':capsule,'state':'AGENT_PENDING',
            'created_at':now,'expires_at':now+300,'provider_id':PROVIDER,'model_id':MODEL,
            'mode':'OFFLINE_FIXTURE','live_verified':False,'approval_payload':approval,'config_ref':config_ref,
            'preview_digest':canonical_sha256(approval),'warrant':None,'receipt':None,
            'tests':{'status':'NOT_RUN','passed':0},'error':None,'stop_requested':False}
        service._run(Capability.COMMIT,lambda tx:_save(service,tx,data))
        return view(service,task,reader)


def propose_git(service,source_task,request_id,reader,*,device_id='local-host'):
    return propose(service,{'schema':'aioa.agent-proposal.v2','recipe_id':'git-commit-v1',
        'provider_id':PROVIDER,'request_id':request_id,'source_task_id':source_task},reader,device_id=device_id)


def propose_install(service,payload,request_id,reader,*,device_id='local-host'):
    from runtime.mission.install_plan import DependencyInstallPlan
    service.core.require(reader,Capability.READ,scope=service.scope)
    require(not service._closed and type(request_id) is str and re.fullmatch('[a-f0-9]{32}',request_id))
    require(type(device_id) is str and re.fullmatch('[A-Za-z0-9_-]{1,128}',device_id))
    plan=DependencyInstallPlan.parse(payload);preview=plan.preview()
    with service._lock:
        sha,capsule=service.source_probe();now=int(service.ledger.clock().timestamp())
        task='agent-'+canonical_sha256([service.scope.binding(),device_id,request_id])[:32]
        for row in _rows(service):
            if row.record_id==task:
                require(row.payload['request_digest']==plan.digest,'AGENT_REQUEST_CONFLICT')
                return view(service,task,reader)
            require(row.payload['state'] not in ACTIVE,'AGENT_ACTIVE')
        operation={'operation_class':'DEPENDENCY_INSTALL',
            'target_fingerprint':'sha256:'+canonical_sha256([service.scope.binding(),plan.digest]),
            'expected_target_revision':'venv-unqualified-v1','payload':{
                'schema':'aioa.local-operation.v2','plan':json.loads(plan.canonical_bytes),
                'source_sha':sha,'capsule_digest':capsule,'device_id':device_id}}
        approval={'summary':'Review exact project-only dependency plan; installation is blocked.',
            'operation':operation,'files':{},'includes':['DEPENDENCY_INSTALL'],'install_plan':preview}
        data={'schema':KIND,'task_id':task,'task_digest':canonical_sha256(approval),
            'request_digest':plan.digest,'device_id':device_id,'source_sha':sha,'capsule_digest':capsule,
            'state':'AGENT_PENDING','created_at':now,'expires_at':now+300,
            'provider_id':PROVIDER,'model_id':MODEL,'mode':'OFFLINE_FIXTURE','live_verified':False,
            'approval_payload':approval,'config_ref':'INSTALL_NOT_BOUND','preview_digest':canonical_sha256(approval),
            'warrant':None,'receipt':None,'tests':{'status':'NOT_RUN','passed':0},'error':None,'stop_requested':False}
        service._run(Capability.COMMIT,lambda tx:_save(service,tx,data))
        return view(service,task,reader)


def _check(service, data):
    require(not service._closed, 'AGENT_CLOSED')
    require(service.source_probe()==(data['source_sha'],data['capsule_digest']), 'AGENT_SOURCE_CHANGED')
    require(int(service.ledger.clock().timestamp())<data['expires_at'], 'AGENT_EXPIRED')
    require(canonical_sha256(data['approval_payload'])==data['preview_digest'], 'AGENT_PREVIEW_CHANGED')
    require(service.cpl_veto_reader() is False, 'AGENT_CPL_VETO')
    current=_get(service,data['task_id']).payload
    require(current['preview_digest']==data['preview_digest'] and not current['stop_requested'], 'AGENT_STOPPED')


def _warrant(service,data):
    operation=data['approval_payload']['operation']; now=service.ledger.clock()
    expiry=min(now+timedelta(seconds=60),datetime.fromtimestamp(data['expires_at'],timezone.utc))
    scope=AuthorityScope(operation_classes=(operation['operation_class'],),target_scope=operation['target_fingerprint'],
        risk_ceiling=RiskLevel.MODERATE,monetary_ceiling=Money(Decimal(0),'USD'),not_before=now,expires_at=expiry,
        owner_scope=canonical_sha256(service.scope),task_scope=data['task_id'])
    w=EffectWarrant(warrant_id='warrant-'+data['task_id'],task_id=data['task_id'],owner_scope=scope.owner_scope,
        operation_class=operation['operation_class'],operation_hash='sha256:'+canonical_sha256(operation),
        target_fingerprint=operation['target_fingerprint'],expected_target_revision=operation['expected_target_revision'],
        revision_policy=RevisionPolicy.REQUIRE,decision_dependency_root=DecisionDependencyRoot((
            EvidenceRef('agent-task','task','sha256:'+data['task_digest'],'v2'),
            EvidenceRef('agent-source','context','sha256:'+data['capsule_digest'],data['source_sha']))),
        lease_epoch=service.agent_epoch,authority_scope=scope,approval_digest='sha256:'+'0'*64,
        money_reservation_id='NONE',risk_reservation_id='risk-'+data['task_id'],nonce='nonce-'+data['task_id'],
        issued_at=now,expires_at=expiry)
    return replace(w,approval_digest=approval_digest(w))


def reservation(operation,warrant):
    return ReservationRequest(warrant.risk_reservation_id,warrant.task_id,'local-worker',MODEL,
                              canonical_sha256(operation),0,1)


def dispatch_request(operation,warrant):
    payload=operation['payload']; inner=payload['sandbox_operation']
    return SandboxDispatchRequest(canonical_json_bytes(inner),'sha256:'+canonical_sha256(inner),
        warrant.task_id,inner['payload']['step_id'],payload['session_id'],payload['session_grant_digest'],
        warrant.lease_epoch,warrant.digest(),warrant.decision_dependency_root.digest(),
        canonical_sha256(reservation(operation,warrant)),payload['task_digest'],warrant.task_id)


def run(service, task, digest, owner):
    service.core.require(owner,Capability.OWNER_APPROVAL,scope=service.scope)
    with service._lock:
        require(hasattr(service,'agent_route'), 'AGENT_TOOLS_NOT_BOUND')
        data=plain(_get(service,task).payload)
        require(data['state']=='AGENT_PENDING' and data['preview_digest']==digest, 'AGENT_NOT_PENDING')
        require(data['approval_payload']['operation']['operation_class'] in ('SANDBOX_EXEC','GIT_COMMIT'),
                'AGENT_EXECUTION_ADAPTER_NOT_BOUND')
        _check(service,data)
        grant=LocalSessionGrant.parse(data['approval_payload']['session_grant'])
        warrant=_warrant(service,data)
        route,_,_=_local_binding(service,data)
        try:
            route.create_session(owner,grant)
            service.ledger.approve(owner,warrant)
            _change(service,task,{'AGENT_PENDING'},'AGENT_APPROVED',warrant=warrant.to_dict())
        except Exception:
            _change(service,task,ACTIVE,'AGENT_UNKNOWN',error='APPROVAL_ACK_UNKNOWN_NO_RETRY')
            raise
        cancel=CancellationToken();service._cancels[task]=cancel
        thread=threading.Thread(target=_execute,args=(service,data,warrant,cancel),daemon=True)
        service._workers[task]=thread;thread.start()
        return view(service,task,service.core.local_operator(Capability.READ))


def _execute(service,data,warrant,cancel):
    task=data['task_id']; operation=data['approval_payload']['operation']
    try:
        route,config,_=_local_binding(service,data)
        _change(service,task,{'AGENT_APPROVED'},'AGENT_RUNNING')
        result=route.dispatch_registered_local(service.core.local_operator(Capability.COMMIT),
            warrant,operation,reservation(operation,warrant),check=lambda:_check(service,data),cancel=cancel)
        require(result['outcome']['contract_type']=='Applied','AGENT_READBACK_UNKNOWN')
        _complete(service,data,warrant,result,config,allowed={'AGENT_RUNNING'})
    except Exception:
        try:_change(service,task,ACTIVE,'AGENT_UNKNOWN',error='LOCAL_OUTCOME_UNKNOWN_READBACK_REQUIRED')
        except Exception:pass  # START/receipt remain durable; restart cannot retry


def _complete(service,data,warrant,result,config,*,allowed):
    operation=data['approval_payload']['operation'];request=dispatch_request(operation,warrant)
    path=config.root/('run-'+request.digest)/'artifact-result.json'
    pin=config.inputs()[operation['payload']['sandbox_operation']['payload']['recipe_id']]['expected']['result.json']
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd);raw=os.read(fd,pin['bytes']+1)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and len(raw)==pin['bytes']
            and hashlib.sha256(raw).hexdigest()==pin['sha256'],'AGENT_ARTIFACT_CHANGED')
    finally:os.close(fd)
    actual=json.loads(raw);git=operation['operation_class']=='GIT_COMMIT'
    require(actual.get('head')==data['approval_payload']['git']['commit_sha'] if git else actual['tests_passed']==5,
            'AGENT_EFFECT_READBACK_REQUIRED')
    receipt={'schema':'aioa.agent.local-receipt.v2','task_id':data['task_id'],'task_digest':data['task_digest'],
        'operation_digest':warrant.operation_hash,'warrant_digest':warrant.digest(),
        'source_sha':data['source_sha'],'capsule_digest':data['capsule_digest'],
        'provider_id':data['provider_id'],'model_id':data['model_id'],'mode':'OFFLINE_FIXTURE',
        'model_invoked':False,'live_verified':False,'local_readback_verified':True,
        'files':operation['payload']['manifest'],'resolution':result,
        'tests_passed':0 if git else actual['tests_passed'],'git':actual if git else None}
    return _change(service,data['task_id'],allowed,'AGENT_COMPLETED',receipt=receipt,error=None,
        tests={'status':'NOT_RUN_GIT_COMMIT_ONLY' if git else 'PASS','passed':0 if git else actual['tests_passed']})


def proposal_readback(service,request_id,reader,*,device_id='local-host'):
    service.core.require(reader,Capability.READ,scope=service.scope)
    require(type(request_id) is str and re.fullmatch('[a-f0-9]{32}',request_id))
    task='agent-'+canonical_sha256([service.scope.binding(),device_id,request_id])[:32]
    row=service._run(Capability.READ,lambda tx:tx.get(RecordKind.OPERATION,task))
    if row is None:return {'schema':'aioa.agent.proposal-readback.v2','task_id':None,
        'state':'AGENT_UNKNOWN','readback_required':True,'automatic_retry':False}
    return view(service,task,reader)


def reconcile(service,task,reader):
    """Independent readback only. No START, executor, grant or effect retry."""
    service.core.require(reader,Capability.READ,scope=service.scope)
    data=plain(_get(service,task).payload)
    if data['state']!='AGENT_UNKNOWN' or data['warrant'] is None:return view(service,task,reader)
    route,config,broker=_local_binding(service,data)
    with service._agent_effect_lock:
        warrant=EffectWarrant.from_dict(data['warrant']);operation=data['approval_payload']['operation']
        try:resolution=broker.verify(operation,warrant)
        except (ValueError,OSError):return view(service,task,reader)
        epoch=service.agent_governor.inspect(reader)['epoch']
        principal=service.core.local_operator(Capability.COMMIT)
        result=service.agent_journal._run(principal,Capability.COMMIT,lambda tx:
            service.agent_journal.apply_resolution_in_transaction(tx,warrant,epoch,resolution))
        _complete(service,data,warrant,result,config,allowed={'AGENT_UNKNOWN'})
    return view(service,task,reader)


def view(service,task,reader):
    service.core.require(reader,Capability.READ,scope=service.scope)
    data=plain(_get(service,task).payload); approval=data['approval_payload']
    public={k:v for k,v in data.items() if k not in ('warrant','approval_payload','request_digest','config_ref')}
    completed=data['state']=='AGENT_COMPLETED'
    public.update(approval_status='NEEDS_HOST_APPROVAL' if data['state']=='AGENT_PENDING' else data['state'],
        permissions=dict(PERMISSIONS),summary=approval['summary'],operation=approval['operation'],
        files=approval['files'],diff={name:{'before_sha256':None,'after_sha256':file['sha256'],
            'status':'READBACK_VERIFIED' if completed else 'PROPOSED_CREATE'} for name,file in approval['files'].items()},
        steps=[{'kind':name,'state':'COMPLETED' if completed else data['state']} for name in
               ('PLAN','EXACT_HOST_APPROVAL','START','WORKSPACE_WRITE','SANDBOX_EXEC','INDEPENDENT_READBACK')],
        install_plan=approval.get('install_plan') or {'status':'NOT_REQUESTED','system_install':'DENY'},
        git=approval.get('git') or {'status':'PREVIEW_ONLY','remote_write':'BLOCKED_SEPARATE_OWNER_GO'},
        planner='REGISTERED_RECIPE_NO_MODEL_CALL', model_invoked=False,
        native_owner='NOT_BOUND_PRODUCTION',automatic_retry=False)
    return public


def stop(service,task,reader):
    service.core.require(reader,Capability.READ,scope=service.scope)
    with service._lock:
        data=_get(service,task).payload
        cancel=service._cancels.get(task)
        if cancel:cancel.cancel()
        if data['state']=='AGENT_PENDING':
            _change(service,task,{'AGENT_PENDING'},'AGENT_STOPPED',stop_requested=True)
        elif data['state'] in ACTIVE:
            _change(service,task,ACTIVE,'AGENT_UNKNOWN',stop_requested=True,error='STOP_READBACK_REQUIRED')
        return view(service,task,reader)
