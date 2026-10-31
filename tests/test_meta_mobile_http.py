"""Mobile-shaped signed HTTP against the single existing webapp on loopback:0."""
import http.client
import importlib
import json
import secrets
import threading
import time
import unittest
from unittest.mock import patch

import test_meta_mobile_gateway as fixture
from cryptography.hazmat.primitives.asymmetric import ec
from runtime.mobile_gateway import wire
from runtime.browser_agent.offline_adapter import FIXTURE_URL


class MobileHTTPTests(unittest.TestCase):
    make_gateway=fixture.MobileGatewayTests.make_gateway
    enroll=fixture.MobileGatewayTests.enroll
    signed=fixture.MobileGatewayTests.signed
    verify_response=fixture.MobileGatewayTests.verify_response
    preview=fixture.MobileGatewayTests.preview

    def setUp(self):
        fixture.MobileGatewayTests.setUp(self)
        from runtime.webapp import WebRuntimeService, make_server
        self.service=WebRuntimeService(runtime=self.composition.runtime,meta_missions=self.composition.missions,
            meta_owner=self.composition,mobile_gateway=self.gateway)
        self.server=make_server('127.0.0.1',0,service=self.service)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        if hasattr(self,'server'):
            self.server.shutdown();self.server.server_close();self.thread.join(3)
        fixture.MobileGatewayTests.tearDown(self)

    def request(self,method,path,headers,body):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=8)
        try:
            connection.request(method,path,body=body,headers={'Content-Type':'application/json',**headers})
            response=connection.getresponse();return response.status,json.loads(response.read())
        finally:connection.close()

    def call(self,method,suffix,data=None,**kw):
        args=self.signed(method,suffix,data,**kw)
        status,response=self.request(*args)
        if status==200:self.verify_response(response,args[2]['X-AIOA-Nonce'],method,args[1])
        return status,response

    def test_http_enrollment_existing_core_run_receipt_stop_and_replay(self):
        status,proof=self.request('GET',wire.BASE+'/capabilities',{'X-AIOA-Challenge':'e'*64},b'')
        self.assertEqual(200,status);wire.verify(self.host.spki,proof['signature'],proof['proof'])
        self.device=wire.Identity(ec.generate_private_key(ec.SECP256R1()))
        code=self.gateway.issue_enrollment(self.owner,self.device.spki)
        data=dict(code=code,device_spki=self.device.spki,nonce=secrets.token_hex(16),issued_at=self.now[0],
            audience=self.host.audience,source_sha=self.source[0],capsule_digest=self.source[1])
        data['signature']=self.device.sign(self.gateway.enrollment_proof(data))
        status,enrolled=self.request('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))
        self.assertEqual(200,status);self.verify_response(enrolled,data['nonce'],'POST',wire.BASE+'/enrollment/redeem')
        self.assertEqual(401,self.request('POST',wire.BASE+'/enrollment/redeem',{},wire.canonical(data))[0])
        self.token,self.session=enrolled['data']['token'],enrolled['data']['session_id']
        task,_=self.preview();raw=self.composition.missions.evidence(task['task_id'],self.reader)
        self.composition.missions.run(task['task_id'],raw['preview_digest'],self.owner)
        for _ in range(100):
            result=self.call('GET','/evidence/'+task['task_id'])[1]['data']
            if result['state']!='RUNNING':break
            time.sleep(.02)
        self.assertEqual('OFFLINE_FIXTURE',result['state']);self.assertFalse(result['verified'])
        self.assertEqual(task['task_digest'],result['task_digest'])
        self.assertEqual(task['owner_scope_digest'],result['owner_scope_digest'])
        host_result=self.composition.missions.evidence(task['task_id'],self.reader)
        self.assertTrue(host_result['result']['core_warrant_consumed'])
        self.assertEqual(host_result['browser_receipt']['content_sha256'],result['receipt']['content_sha256'])
        self.assertEqual(1,self.composition.driver.read_count)
        next_task,_=self.preview()
        args=self.signed('POST','/stop',{'task_id':next_task['task_id']})
        self.assertEqual('STOPPED',self.request(*args)[1]['data']['state'])
        self.assertEqual(409,self.request(*args)[0]);self.assertEqual(1,self.composition.driver.read_count)

    def test_http_csrf_cors_wrong_host_duplicate_header_and_loopback_token_are_denied(self):
        for headers in ({'Origin':'https://evil.invalid'},{'Sec-Fetch-Site':'cross-site'}, {'Host':'evil.invalid'}):
            args=self.signed('GET','/status');args[2].update(headers)
            self.assertEqual(403,self.request(*args)[0])
        self.assertEqual(401,self.request('GET',wire.BASE+'/status',{'X-AIOA-Session-Token':self.service.csrf_token},b'')[0])
        args=self.signed('GET','/status')
        conn=http.client.HTTPConnection('127.0.0.1',self.server.server_address[1],timeout=8)
        try:
            conn.putrequest('GET',args[1])
            for k,v in args[2].items():conn.putheader(k,v)
            conn.putheader('X-AIOA-Nonce',args[2]['X-AIOA-Nonce']);conn.endheaders()
            self.assertEqual(400,conn.getresponse().status)
        finally:conn.close()

    def test_lost_preview_ack_only_reads_back_and_double_submit_is_denied(self):
        proposal=secrets.token_hex(16)
        body=dict(proposal_id=proposal,instruction='Przeczytaj',mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL)
        args=self.signed('POST','/preview',body)
        self.assertEqual(200,self.request(*args)[0]) # ACK intentionally discarded by client
        self.assertEqual(409,self.request(*args)[0])
        status,found=self.call('GET','/proposals/'+proposal)
        self.assertEqual(200,status);self.assertEqual('PREVIEWED',found['data']['state'])
        self.assertEqual(1,len(self.composition.missions._rows()));self.assertEqual(0,self.composition.driver.read_count)

    def test_unknown_after_native_restart_remains_unknown_after_stop(self):
        task,_=self.preview()
        self.composition.missions.close()
        module=importlib.import_module('runtime.meta_hackathon.mission_service')
        restarted=module.MissionService(self.composition.ledger,self.composition.manager,self.composition.browser,
                                        lambda:tuple(self.source))
        self.composition.missions=restarted
        self.gateway=self.make_gateway();self.service.mobile_gateway=self.gateway;self.service.meta_missions=restarted
        self.assertEqual('UNKNOWN',self.call('GET','/evidence/'+task['task_id'])[1]['data']['state'])
        self.assertEqual('UNKNOWN',self.call('POST','/stop',{'task_id':task['task_id']})[1]['data']['state'])
        self.assertEqual(0,self.composition.driver.read_count)

    def test_crash_between_core_preview_and_link_stays_unknown_without_retry(self):
        proposal=secrets.token_hex(16)
        real=self.composition.missions.preview
        def crash(*args):
            real(*args);raise OSError('simulated ACK loss; no secrets')
        with patch.object(self.composition.missions,'preview',side_effect=crash):
            self.assertEqual(503,self.call('POST','/preview',dict(proposal_id=proposal,instruction='x',
                mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        self.assertEqual('UNKNOWN',self.call('GET','/proposals/'+proposal)[1]['data']['state'])
        self.assertEqual(409,self.call('POST','/preview',dict(proposal_id=proposal,instruction='x',
            mode='OFFLINE_FIXTURE',target_url=FIXTURE_URL))[0])
        self.assertEqual(1,len(self.composition.missions._rows()))

    def test_wrong_receipt_is_rejected_not_promoted_to_verified(self):
        task,_=self.preview()
        self.composition.missions._change(task['task_id'],{'PREVIEWED'},'UNKNOWN',
            {'browser_receipt':{'task_digest':'0'*64,'source_sha':self.source[0]}})
        self.assertEqual(503,self.call('GET','/evidence/'+task['task_id'])[0])

    def test_http_header_names_are_case_insensitive(self):
        args=self.signed('GET','/status')
        self.assertEqual(200,self.request(args[0],args[1],{k.lower():v for k,v in args[2].items()},args[3])[0])

    def test_nonce_barrier_survives_complete_core_storage_reopen(self):
        args=self.signed('GET','/status');self.assertEqual(200,self.request(*args)[0])
        root=self.composition.root;self.composition.close()
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        self.composition=OfflineMetaComposition(root,source_probe=lambda:tuple(self.source))
        self.gateway=self.make_gateway()
        self.service.mobile_gateway=self.gateway;self.service.meta_missions=self.composition.missions
        self.assertEqual(409,self.request(*args)[0]);self.assertEqual(200,self.call('GET','/status')[0])


if __name__=='__main__':unittest.main()
