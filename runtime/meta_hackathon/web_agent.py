"""Authenticated local ports of WebRuntimeService; never another HTTP app."""
from runtime.core_admission import Capability
from . import agent_operations


def require(value,code='AGENT_REQUEST_DENIED'):
    if not value:raise ValueError(code)


def status(web):
    service=web.meta_missions;reader=service.core.local_operator(Capability.READ)
    rows=agent_operations._rows(service)
    governor=service.agent_governor.inspect(reader)
    unresolved=any(r['state']=='UNKNOWN' for r in governor['reservations'].values())
    sha,capsule=service.source_probe()
    return {'unified_profile':True,'product_name':'AIOA spArkHAT','subtitle':'One Core Mission Control',
        'source_sha':sha,'capsule_digest':capsule,'model':'meta_model_api/muse-spark-1.3',
        'tools':['Registered SensorBridge workspace + Python tests','Exact local Git commit','Bounded MCP LICENSE READ'],
        'capabilities':{'core':'BOUND_OFFLINE_FIXTURE','production_owner':'NOT_BOUND',
            'local_workspace_fixture':True,'local_git_fixture':True,'mcp_bounded_read':True,
            'mcp_proposals':True,'mobile_signed_fixture':web.mobile_gateway is not None,
            'meta_live':False,'nebius_live':False,'github_remote_write':False,'dependency_install':False,
            'system_install':False,'browser_external':False,'remote_tls':'NOT_QUALIFIED','apk':'NOT_BUILT',
            'unresolved_intent':unresolved,'kill':governor['kill']},
        'provider_catalog':service.provider_catalog(reader),
        'agent_missions':[{'task_id':r.record_id,'state':r.payload['state'],'created_at':r.payload['created_at'],
            'source_sha':r.payload['source_sha'],'receipt_present':r.payload['receipt'] is not None}
            for r in sorted(rows,key=lambda r:r.payload['created_at'],reverse=True)[:16]],
        'agent_history_total':len(rows),'agent_history_truncated':len(rows)>16,
        'local_budget':{'money_nano':governor['exposure']['global']['money_nano'],
            'risk_units':governor['exposure']['global']['risk_units']},'automatic_retry':False}


def request(web,action,payload,*,intent):
    require(web.unified_profile and web.meta_missions is not None,'AGENT_COMPOSITION_NOT_BOUND')
    service=web.meta_missions;reader=service.core.local_operator(Capability.READ)
    if action=='status':return status(web)
    if action=='providers':return service.provider_catalog(reader)
    require(type(payload) is dict)
    if action=='proposal-readback':
        require(set(payload)=={'request_id'})
        return service.agent_proposal_readback(payload['request_id'],reader)
    if action=='reconcile':
        require(set(payload)=={'task_id'} and intent=='agent-readback-v2')
        return service.reconcile_agent(payload['task_id'],reader)
    if action in ('view','stop'):
        require(set(payload)=={'task_id'})
        return service.agent_view(payload['task_id'],reader) if action=='view' else service.agent_stop(payload['task_id'],reader)
    if action=='propose':return service.propose_agent(payload,reader)
    if action=='git-preview':
        require(set(payload)=={'source_task_id','request_id'})
        return service.propose_git(payload['source_task_id'],payload['request_id'],reader)
    if action=='install-preview':
        require(set(payload)=={'plan','request_id'})
        return service.propose_install(payload['plan'],payload['request_id'],reader)
    if action=='run':
        require(set(payload)=={'task_id','preview_digest'})
        require(intent=='agent-approve-offline-exact-v2' and service.scope.tenant_id=='offline-fixture'
            and service.manager._meta_provider.mode=='MOCK','AGENT_PRODUCTION_OWNER_NOT_BOUND')
        # Explicitly labelled local fixture admission. There is no production
        # owner endpoint and this can never authorize LIVE model/remote effects.
        return service.run_agent(payload['task_id'],payload['preview_digest'],
                                 service.core.local_operator(Capability.OWNER_APPROVAL))
    if action.startswith('mcp-'):
        web.core_mcp.reader=reader
        if action=='mcp-result':
            require(set(payload)=={'task_id'})
            return web.core_mcp.result(payload['task_id'])
        from runtime.mcp_bridge.task_bus import parse_task_dict
        require(action=='mcp-submit' and set(payload)=={'task','namespace','origin','source_sha','capsule_digest'})
        require(type(payload['task']) is dict and 'fingerprint' in payload['task'])
        return web.core_mcp.submit(parse_task_dict(payload['task']),namespace=payload['namespace'],origin=payload['origin'],
            source_sha=payload['source_sha'],capsule_digest=payload['capsule_digest'])
    raise ValueError('AGENT_ROUTE_DENIED')
