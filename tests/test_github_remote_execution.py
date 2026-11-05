"""Offline GitHub protocol faults. A fixture result is never LIVE evidence."""
import base64
import json
import time
import unittest

from runtime.mission.git_publish import RemoteGitPlan, GitTreeSnapshot, git_object, DEMO_REPOSITORY
from runtime.mcp_bridge.github_remote import InstallationCredential, PREFIX
from runtime.providers.exact import CancellationToken


class RemoteExecutionTests(unittest.TestCase):
    def setUp(self):
        self.base=GitTreeSnapshot(git_object('tree',b''),{})
        self.plan=RemoteGitPlan(files={'agent-demo/proposal.py':b'VALUE = 1\n'},title='Add a proposal',
            body='Model proposal reviewed by owner.',operation_id='1'*32,issued_at=1793851200,
            base_sha='2'*40,base_tree_sha=self.base.sha,source_sha='3'*40,capsule_digest='4'*64,
            source_reply_sha256='5'*64,source_receipt_sha256='6'*64)
        self.tree=self.base.add_files(self.plan.files);self.commit=self.plan.commit_sha_for_tree(self.tree.sha)
        self.credential=InstallationCredential('ghs_OFFLINE_TEST_ONLY',73,int(time.time())+3600,'a'*64,'OFFLINE_FIXTURE')
        self.cancel=CancellationToken();self.calls=[];self.markers={};self.objects={};self.fail=None
        self.bad_blob=False;self.kill=False

    def check(self):
        if self.kill:raise ValueError('OWNER_STOPPED')

    def begin(self,step,digest):
        if step in self.markers:return False
        self.markers[step]=digest;return True

    def tree_value(self,tree):
        return {'sha':tree.sha,'truncated':False,'tree':[{'path':p,'mode':m,'type':t,'sha':s}
            for p,(m,t,s) in tree.entries.items()]}

    def pull(self):
        return {'number':1,'html_url':'https://github.com/'+DEMO_REPOSITORY+'/pull/1','state':'open',
            'draft':True,'merged':False,'title':self.plan.title,'body':self.plan.body,
            'head':{'ref':self.plan.branch,'sha':self.commit,'repo':{'id':1445911975,'full_name':DEMO_REPOSITORY}},
            'base':{'ref':'main','sha':self.plan.base_sha,'repo':{'id':1445911975,'full_name':DEMO_REPOSITORY}}}

    def transport(self,method,path,payload,bearer,cancel,timeout):
        self.calls.append((method,path,payload))
        result={};status=200
        if method=='POST':
            self.assertIn(path,(PREFIX+'/git/trees',PREFIX+'/git/commits',PREFIX+'/git/refs',PREFIX+'/pulls'))
            marker_check=getattr(self,'marker_assertion',None)
            if marker_check is not None:marker_check()
            else:self.assertTrue(self.markers,'durable step must precede every POST')
            self.assertEqual(self.credential.bearer,bearer)
            self.objects[path]=payload;status=201
            if path.endswith('/trees'):result={'sha':self.tree.sha}
            elif path.endswith('/commits'):result={'sha':self.commit}
            elif path.endswith('/refs'):result={'ref':'refs/heads/'+self.plan.branch,'object':{'type':'commit','sha':self.commit}}
            else:result=self.pull()
            if path==self.fail:raise TimeoutError('provider response lost AFTER remote application')
        else:
            self.assertEqual(self.credential.bearer,bearer,'independent GET uses only the same narrowed installation')
            if path==PREFIX:result={'id':1445911975,'full_name':DEMO_REPOSITORY,'default_branch':'main','private':False,'archived':False,'disabled':False}
            elif path==PREFIX+'/git/ref/heads/main':result={'ref':'refs/heads/main','object':{'type':'commit','sha':self.plan.base_sha}}
            elif path==PREFIX+'/git/commits/'+self.plan.base_sha:result={'sha':self.plan.base_sha,'tree':{'sha':self.base.sha}}
            elif path==PREFIX+'/git/trees/'+self.base.sha+'?recursive=1':result=self.tree_value(self.base)
            elif path==PREFIX+'/git/ref/heads/'+self.plan.branch:
                if PREFIX+'/git/refs' not in self.objects:return 404,b''
                result={'ref':'refs/heads/'+self.plan.branch,'object':{'type':'commit','sha':self.commit}}
            elif path==PREFIX+'/git/commits/'+self.commit:
                if PREFIX+'/git/commits' not in self.objects:return 404,b''
                p=self.plan.commit_payload(self.tree.sha)
                result={**p,'sha':self.commit,'tree':{'sha':self.tree.sha},'parents':[{'sha':self.plan.base_sha}]}
            elif path==PREFIX+'/git/trees/'+self.tree.sha+'?recursive=1':result=self.tree_value(self.tree)
            elif path.startswith(PREFIX+'/git/blobs/'):
                data=b'CHANGED\n' if self.bad_blob else next(data for data in self.plan.files.values()
                    if git_object('blob',data)==path.rsplit('/',1)[1])
                result={'sha':path.rsplit('/',1)[1],'size':len(data),'encoding':'base64','content':base64.b64encode(data).decode()}
            elif path.startswith(PREFIX+'/pulls?'):result=[self.pull()] if PREFIX+'/pulls' in self.objects else []
            elif path==PREFIX+'/pulls/1':result=self.pull()
            else:raise AssertionError((method,path))
        return status,json.dumps(result).encode()

    def api(self):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly
        return GitHubCreateOnly(self.plan,self.base,self.credential,mode='OFFLINE_FIXTURE',transport=self.transport)

    def execute(self,api):
        return api.execute(check=self.check,cancel=self.cancel,begin_step=self.begin)

    def test_exact_create_only_sequence_and_independent_full_readback(self):
        api=self.api();result=self.execute(api)
        self.assertEqual(['tree','commit','branch','draft_pr'],list(self.markers))
        self.assertEqual([PREFIX+s for s in ('/git/trees','/git/commits','/git/refs','/pulls')],
            [p for m,p,_ in self.calls if m=='POST'])
        self.assertEqual(self.commit,result['commit_sha']);self.assertTrue(result['remote_effect_verified'])
        self.assertEqual('OFFLINE_FIXTURE',result['mode']);self.assertFalse(result['live_verified'])
        self.assertFalse(self.objects[PREFIX+'/pulls']['maintainer_can_modify'])
        posts=sum(m=='POST' for m,_,_ in self.calls)
        with self.assertRaises(ValueError):self.execute(self.api())
        self.assertEqual(posts,sum(m=='POST' for m,_,_ in self.calls))

    def test_api_budget_and_expired_credentials_stop_before_network(self):
        from dataclasses import replace
        api=self.api();api.request_count=48
        with self.assertRaisesRegex(ValueError,'GITHUB_API_BUDGET_EXHAUSTED'):
            api.readback(check=self.check,cancel=self.cancel)
        self.assertEqual([],self.calls)
        self.credential=replace(self.credential,expires_at=int(time.time())-1)
        with self.assertRaisesRegex(ValueError,'GITHUB_CREDENTIAL_EXPIRED'):
            self.execute(self.api())
        self.assertEqual([],self.calls)

    def test_authentication_and_permission_errors_never_retry_or_disclose_body(self):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly
        for status,code in ((401,'GITHUB_AUTHENTICATION_401'),(403,'GITHUB_PERMISSION_403'),(429,'GITHUB_RATE_LIMIT_429')):
            calls=[]
            def denied(*args):calls.append(args[0]);return status,b'SECRET_UNTRUSTED_BODY'
            api=GitHubCreateOnly(self.plan,self.base,self.credential,mode='OFFLINE_FIXTURE',transport=denied)
            with self.assertRaisesRegex(ValueError,code) as found:self.execute(api)
            self.assertEqual(['GET'],calls);self.assertNotIn('SECRET',str(found.exception))

    def test_public_base_read_uses_four_gets_and_rejects_scope_or_incomplete_tree(self):
        from runtime.mcp_bridge.github_remote import read_demo_base
        repo={'id':1445911975,'full_name':DEMO_REPOSITORY,'default_branch':'main','private':False,'archived':False,'disabled':False}
        replies={PREFIX:repo,PREFIX+'/git/ref/heads/main':{'ref':'refs/heads/main','object':{'type':'commit','sha':self.plan.base_sha}},
            PREFIX+'/git/commits/'+self.plan.base_sha:{'sha':self.plan.base_sha,'tree':{'sha':self.base.sha}},
            PREFIX+'/git/trees/'+self.base.sha+'?recursive=1':self.tree_value(self.base)}
        calls=[]
        def read(method,path,body,bearer,cancel,timeout):
            self.assertEqual('GET',method);self.assertIsNone(body);self.assertIsNone(bearer)
            calls.append(path);return 200,json.dumps(replies[path]).encode()
        def run():return read_demo_base(check=self.check,cancel=self.cancel,mode='OFFLINE_FIXTURE',transport=read)
        self.assertEqual((self.plan.base_sha,self.base),run());self.assertEqual(4,len(calls))
        repo['id']=1
        with self.assertRaisesRegex(ValueError,'GITHUB_REPOSITORY_READBACK_MISMATCH'):run()
        repo['id']=1445911975
        replies[PREFIX+'/git/trees/'+self.base.sha+'?recursive=1']['truncated']=True
        with self.assertRaises(ValueError):run()

    def test_lost_ack_stops_sequence_and_recovery_performs_only_get(self):
        for endpoint in ('/git/trees','/git/commits','/git/refs','/pulls'):
            with self.subTest(endpoint=endpoint):
                self.calls=[];self.markers={};self.objects={};self.fail=PREFIX+endpoint
                api=self.api()
                with self.assertRaisesRegex(ValueError,'GITHUB_WRITE_UNKNOWN_NO_RETRY'):self.execute(api)
                before=sum(m=='POST' for m,_,_ in self.calls)
                result=self.api().readback(check=self.check,cancel=self.cancel)
                self.assertEqual(before,sum(m=='POST' for m,_,_ in self.calls))
                self.assertEqual(endpoint=='/pulls',result['remote_effect_verified'])
                self.assertFalse(result['automatic_retry'])

    def test_altered_blob_cannot_verify_and_stop_prevents_all_io(self):
        api=self.api();self.execute(api);self.bad_blob=True
        with self.assertRaisesRegex(ValueError,'GITHUB_BLOB_READBACK_MISMATCH'):
            api.readback(check=self.check,cancel=self.cancel)
        self.kill=True;self.calls=[]
        with self.assertRaisesRegex(ValueError,'OWNER_STOPPED'):self.execute(self.api())
        self.assertEqual([],self.calls)

    def test_public_recovery_has_no_credential_and_can_never_enter_execute(self):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly
        api=GitHubCreateOnly(self.plan,self.base,None,mode='PUBLIC_READ_ONLY')
        with self.assertRaisesRegex(ValueError,'GITHUB_READBACK_ONLY'):self.execute(api)
        self.assertEqual([],self.calls)


if __name__=='__main__':unittest.main()
