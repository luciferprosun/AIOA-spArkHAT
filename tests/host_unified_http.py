"""U8 one existing HTTP app, signed phone fixture, Core, MCP and real worker."""
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

import runtime
from webapp import WebRuntimeService,make_server
from runtime.core_admission import Capability
from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
from runtime.mcp_bridge.adapter import build_task
from unified_mobile_support import SignedDeviceFixture


class UnifiedHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from runtime.mission.project_recipe import prepare_sensorbridge_sandbox
        cls.prep=tempfile.TemporaryDirectory()
        cls.config=prepare_sensorbridge_sandbox(Path(cls.prep.name)/'sandbox',workspace='workspace-sensorbridge')

    @classmethod
    def tearDownClass(cls):cls.prep.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.source=['1'*40,'a'*64]
        self.host=OfflineMetaComposition(Path(self.tmp.name),source_probe=lambda:tuple(self.source))
        self.addCleanup(self.host.close)
        self.assertTrue(callable(getattr(self.host,'enable_unified',None)),'single existing webapp composition not wired')
        self.host.enable_unified(config=self.config)
        self.service=WebRuntimeService(runtime=self.host.runtime,meta_missions=self.host.missions,
            meta_owner=self.host,mobile_gateway=self.host.mobile)
        self.server=make_server('127.0.0.1',0,self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.close_server)
        self.token=self.http('GET','/api/session',authenticated=False)[1]['token']

    def close_server(self):
        self.server.shutdown();self.server.server_close();self.thread.join(3);self.service.close()

    def http(self,method,path,value=None,*,authenticated=True,intent=None,headers=None,raw=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=40)
        h={'X-AIOA-Session-Token':self.token} if authenticated and hasattr(self,'token') else {}
        if intent:h['X-AIOA-Intent']=intent
        if value is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        body=raw if raw is not None else json.dumps(value).encode() if value is not None else None
        try:
            connection.request(method,path,body=body,headers=h);response=connection.getresponse();data=response.read()
            return response.status,json.loads(data) if response.getheader('Content-Type','').startswith('application/json') else data.decode()
        finally:connection.close()

    def signed(self,client,method,path,value=None):
        frame=client.frame(method,path,value)
        status,response=self.http(method,path,headers={**frame[2],**({'Content-Type':'application/json'} if value is not None else {})},raw=frame[3])
        if status==200:client.verify(response,frame[2]['X-AIOA-Nonce'],method,path)
        return status,response

    def test_status_is_authenticated_truthful_and_one_core(self):
        self.assertEqual(403,self.http('GET','/api/status',authenticated=False)[0])
        status,data=self.http('GET','/api/status')
        self.assertEqual(200,status,data);self.assertTrue(data['unified_profile'])
        self.assertFalse(data['capabilities']['meta_live']);self.assertFalse(data['capabilities']['github_remote_write'])
        self.assertEqual('NOT_BOUND',data['capabilities']['production_owner'])
        self.assertIs(self.service.mobile_gateway.missions,self.host.missions)
        self.assertIs(self.service.core_mcp.missions,self.host.missions)
        status,page=self.http('GET','/')
        self.assertEqual(200,status);self.assertIn('Agent workspace',page)

    def test_signed_mobile_propose_host_exact_approval_receipt_and_git_preview(self):
        owner=self.host.core.local_operator(Capability.OWNER_APPROVAL)
        client=SignedDeviceFixture(self.host.mobile,owner)
        status,response=self.signed(client,'POST','/api/mobile/v2/propose',{
            'schema':'aioa.agent-proposal.v2','recipe_id':'sensorbridge-v1',
            'provider_id':'meta_model_api','request_id':'f'*32})
        self.assertEqual(200,status,response);task=response['data']
        status,view=self.http('GET','/api/agent/tasks/'+task['task_id'])
        self.assertEqual(200,status,view);self.assertEqual(task['preview_digest'],view['preview_digest'])
        exact={'task_id':task['task_id'],'preview_digest':task['preview_digest']}
        self.assertEqual(403,self.http('POST','/api/agent/run',exact)[0])
        status,response=self.http('POST','/api/agent/run',exact,intent='agent-approve-offline-exact-v2')
        self.assertEqual(202,status,response)
        self.host.missions._workers[task['task_id']].join(40)
        status,response=self.signed(client,'GET','/api/mobile/v2/tasks/'+task['task_id'])
        self.assertEqual(200,status,response);done=response['data']
        self.assertEqual('AGENT_COMPLETED',done['state']);self.assertEqual(5,done['tests']['passed'])
        self.assertTrue(done['receipt']['local_readback_verified']);self.assertFalse(any(done['permissions'].values()))
        status,git=self.http('POST','/api/agent/git-preview',{'source_task_id':task['task_id'],'request_id':'e'*32},intent='agent-propose-v2')
        self.assertEqual(200,status,git);self.assertFalse(git['git']['remote_write_allowed'])
        self.assertEqual(403,self.http('POST','/api/agent/github-push',{'approved':True},intent='agent-propose-v2')[0])

    def test_same_server_mcp_bounded_read_and_deny_generic_commands(self):
        task=build_task('fs.read',{'path':'LICENSE'},target_project='aioa',source='mcp_fixture')
        status,data=self.http('POST','/api/agent/mcp/submit',{'task':task.to_dict(),
            'source_sha':self.source[0],'capsule_digest':self.source[1],
            'namespace':'aioa','origin':'OFFLINE_FIXTURE'},intent='agent-mcp-propose-v2')
        self.assertEqual(200,status,data);self.assertEqual('ALLOW',data['decision']);self.assertIn('MIT License',data['read']['text'])
        for path in ('/api/run','/api/agent/shell','/api/agent/install','/api/agent/github-push'):
            self.assertEqual(403,self.http('POST',path,{'command':'id','approved':True},intent='agent-propose-v2')[0])

    def test_query_forged_fields_and_duplicate_headers_do_not_authorize(self):
        self.assertEqual(400,self.http('GET','/api/agent/status?approved=true')[0])
        status,data=self.http('POST','/api/agent/propose',{'approved':True},intent='agent-propose-v2')
        self.assertEqual(400,status,data)

    def test_proposal_lost_ack_can_be_read_without_second_post(self):
        request_id='d'*32
        status,task=self.http('POST','/api/agent/propose',{'schema':'aioa.agent-proposal.v2',
            'recipe_id':'sensorbridge-v1','provider_id':'meta_model_api','request_id':request_id},intent='agent-propose-v2')
        self.assertEqual(200,status,task)
        status,result=self.http('GET','/api/agent/proposals/'+request_id)
        self.assertEqual(200,status,result);self.assertEqual(task['task_id'],result['task_id'])
        status,unknown=self.http('GET','/api/agent/proposals/'+'e'*32)
        self.assertEqual(200,status,unknown);self.assertEqual('AGENT_UNKNOWN',unknown['state'])
        status,data=self.http('POST','/api/agent/run',{'task_id':'agent-'+'a'*32,'preview_digest':'b'*64,'owner':'forged'},intent='agent-approve-offline-exact-v2')
        self.assertEqual(400,status,data)


if __name__=='__main__':unittest.main()
