"""QA harness for the actual webapp, not a second product/runtime.

Signed device → exact synthetic host approval → real Core/files/tests/readback
→ local Git commit → remote denial → signed readback from a fresh app process.
Never a phone, TLS, paid model or production owner certification.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import threading
import time
import uuid

import runtime
from webapp import WebRuntimeService,make_server
from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition,current_source,ROOT
from .signed_fixture import SignedDeviceFixture


def require(value,reason):
    if not value:raise RuntimeError(reason)


def run_demo(evidence_dir):
    evidence=Path(evidence_dir).absolute();evidence.mkdir(mode=0o700,parents=True,exist_ok=False)
    source_sha,capsule=current_source();state=evidence/'state'
    host=OfflineMetaComposition(state);host.enable_unified()
    service=WebRuntimeService(runtime=host.runtime,meta_missions=host.missions,meta_owner=host,mobile_gateway=host.mobile)
    server=make_server('127.0.0.1',0,service)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    port=server.server_port;process=None;closed=False;errors=None
    def call_http(method,path,value=None,headers=None,raw=None):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=40)
        h=dict(headers or {})
        if value is not None:h['Content-Type']='application/json'
        body=raw if raw is not None else json.dumps(value).encode() if value is not None else None
        try:
            connection.request(method,path,body=body,headers=h)
            response=connection.getresponse();data=response.read()
            return response.status,json.loads(data)
        finally:connection.close()
    try:
        token=call_http('GET','/api/session')[1]['token']
        owner=host.core.local_operator(Capability.OWNER_APPROVAL)
        device=SignedDeviceFixture(host.mobile,owner)
        def signed(method,path,value=None):
            frame=device.frame(method,path,value)
            headers={**frame[2],**({'Content-Type':'application/json'} if value is not None else {})}
            status,response=call_http(method,path,headers=headers,raw=frame[3])
            require(status==200,'SIGNED_FIXTURE_REQUEST_FAILED')
            device.verify(response,frame[2]['X-AIOA-Nonce'],method,path)
            return response['data']
        def approve(task):
            code,_=call_http('POST','/api/agent/run',{'task_id':task['task_id'],'preview_digest':task['preview_digest']},
                headers={'X-AIOA-Session-Token':token,'X-AIOA-Intent':'agent-approve-offline-exact-v2'})
            require(code==202,'EXACT_LOCAL_FIXTURE_APPROVAL_FAILED')
            host.missions._workers[task['task_id']].join(40)
            view=signed('GET','/api/mobile/v2/tasks/'+task['task_id'])
            require(view['state']=='AGENT_COMPLETED' and view['receipt']['local_readback_verified'] is True,
                    'REAL_CORE_EFFECT_READBACK_REQUIRED')
            return view
        workspace=signed('POST','/api/mobile/v2/propose',{'schema':'aioa.agent-proposal.v2',
            'recipe_id':'sensorbridge-v1','provider_id':'meta_model_api','request_id':uuid.uuid4().hex})
        done=approve(workspace)
        git=signed('POST','/api/mobile/v2/propose',{'schema':'aioa.agent-proposal.v2',
            'recipe_id':'git-commit-v1','provider_id':'meta_model_api','request_id':uuid.uuid4().hex,
            'source_task_id':workspace['task_id']})
        committed=approve(git)
        remote_status,_=call_http('POST','/api/agent/github-push',{'approved':True},
            headers={'X-AIOA-Session-Token':token,'X-AIOA-Intent':'agent-propose-v2'})
        require(remote_status==403,'REMOTE_WRITE_MUST_REMAIN_DENIED')
        for name,value in (('workspace-receipt',done['receipt']),('git-receipt',committed['receipt'])):
            path=evidence/(name+'.json');path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');path.chmod(0o600)
        server.shutdown();server.server_close();thread.join(3);service.close();closed=True
        errors=open(evidence/'cli-stderr.log','wb');os.fchmod(errors.fileno(),0o600)
        process=subprocess.Popen([sys.executable,'-B','-m','runtime.webapp','--unified-offline',
            '--state-dir',str(state),'--host','127.0.0.1','--port','0'],cwd=ROOT,
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,stderr=errors)
        deadline=time.monotonic()+40;new_port=None
        while time.monotonic()<deadline and process.poll() is None:
            if select.select([process.stdout],[],[],.2)[0]:
                line=process.stdout.readline().decode()
                match=re.search(r'http://127\.0\.0\.1:([0-9]+)',line)
                if match:new_port=int(match.group(1));break
        require(new_port is not None,'DOCUMENTED_COMMAND_RESTART_FAILED');port=new_port
        after=signed('GET','/api/mobile/v2/tasks/'+committed['task_id'])
        require(after['receipt']==committed['receipt'] and after['state']=='AGENT_COMPLETED',
                'FRESH_PROCESS_SIGNED_RECEIPT_MISMATCH')
        status,session=call_http('GET','/api/session');require(status==200,'LOCAL_SESSION_FAILED')
        status,capabilities=call_http('GET','/api/status',headers={'X-AIOA-Session-Token':session['token']})
        require(status==200 and capabilities['source_sha']==source_sha and capabilities['capsule_digest']==capsule,
                'RESTART_SOURCE_BINDING_CHANGED')
        require(capabilities['local_budget']['money_nano']==0,'ZERO_COST_LOCAL_ACCOUNTING_REQUIRED')
        report={'schema':'aioa.unified-offline-demo.v1','status':'PASS_OFFLINE_LOCAL_SLICE',
            'source_sha':source_sha,'capsule_digest':capsule,
            'workspace':{'task_id':done['task_id'],'task_digest':done['task_digest'],'state':done['state'],
                'tests_passed':done['tests']['passed'],'files':done['receipt']['files'],
                'local_readback_verified':done['receipt']['local_readback_verified'],
                'receipt_sha256':hashlib.sha256(json.dumps(done['receipt'],sort_keys=True).encode()).hexdigest()},
            'git':{'task_id':committed['task_id'],'state':committed['state'],
                'predicted_head':git['git']['commit_sha'],'head':committed['receipt']['git']['head'],
                'tree':committed['receipt']['git']['tree'],'branch':committed['receipt']['git']['branch']},
            'fresh_process_signed_readback_verified':True,'remote_write_http_status':remote_status,
            'paid_api_calls':0,'model_invoked':False,'owner_profile':'SYNTHETIC_OFFLINE_FIXTURE',
            'production_owner':'NOT_BOUND','physical_android':False,'tls_verified':False,'apk_built':False,
            'local_budget':capabilities['local_budget'],'automatic_retry':False}
        path=evidence/'DEMO_REPORT.json';path.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n');path.chmod(0o600)
        return report
    finally:
        if process is not None:
            if process.poll() is None:process.send_signal(signal.SIGINT)
            try:process.wait(timeout=15)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            process.stdout.close()
        if errors is not None:errors.close()
        if not closed:
            server.shutdown();server.server_close();thread.join(3);service.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir',required=True,help='Fresh private directory; never overwritten')
    args=parser.parse_args();report=run_demo(Path(args.evidence_dir))
    print(json.dumps({'status':report['status'],'source_sha':report['source_sha'],
        'workspace_task':report['workspace']['task_id'],'git_head':report['git']['head'],
        'fresh_process_signed_readback_verified':report['fresh_process_signed_readback_verified'],
        'paid_api_calls':0,'production_owner':'NOT_BOUND','evidence_dir':str(Path(args.evidence_dir).absolute())},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
