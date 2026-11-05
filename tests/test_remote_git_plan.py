"""Pure proposal validation; no provider, credential, network or Git process."""
import json
import hashlib
import unittest

from runtime.mission import git_publish


class RemoteGitPlanTests(unittest.TestCase):
    def setUp(self):
        self.model={'schema':'aioa.muse.github-change.v1','operation':'code.commit_draft_pr',
            'target_repo':'luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026',
            'title':'Add a small Muse example','body':'Proposed by Muse; owner approval required.',
            'files':{'agent-demo/example.md':'# Example\nA short proposal.\n'}}
        self.host={'operation_id':'1'*32,'issued_at':1793844000,'base_sha':'2'*40,'base_tree_sha':'3'*40,
            'source_sha':'4'*40,'capsule_digest':'5'*64,'source_reply_sha256':'6'*64,
            'source_receipt_sha256':'7'*64}

    def parse(self,model=None,**host):
        self.assertTrue(hasattr(git_publish,'RemoteGitPlan'),'typed remote file proposal is not bound')
        return git_publish.RemoteGitPlan.from_model(json.dumps(model or self.model).encode(),**(self.host|host))

    def test_exact_manifest_branch_and_full_review_are_immutable_and_inert(self):
        plan=self.parse();review=plan.preview()
        self.assertEqual('aioa/muse-'+'1'*32,plan.branch)
        self.assertEqual(1445911975,review['repository_id'])
        self.assertEqual('NONE',review['authority']);self.assertFalse(review['execution_authorized'])
        self.assertEqual(self.model['files'],review['files'])
        self.assertIn('+A short proposal.\n',review['diff'])
        self.assertEqual('100644',review['manifest']['agent-demo/example.md']['mode'])
        self.model['files']['agent-demo/example.md']='changed\n'
        self.assertNotEqual(self.model['files'],plan.preview()['files'])
        with self.assertRaises(TypeError):plan.files['agent-demo/evil.md']=b'bad\n'

    def test_model_cannot_set_authority_credentials_branch_or_other_repository(self):
        for update in ({'approved':True},{'token':'nope'},{'branch':'main'},
                {'target_repo':'luciferprosun/AIOA-spArkHAT'},{'operation':'issue.create'},
                {'base_sha':'f'*40},{'files':{'agent-demo/empty.md':''}}):
            with self.subTest(update=update),self.assertRaises(ValueError):self.parse(self.model|update)

    def test_path_modes_and_content_are_closed(self):
        for path in ('../a.md','agent-demo/../a.md','/agent-demo/a.md','agent-demo//a.md',
                'agent-demo/a\\b.md','agent-demo/.github/a.md','agent-demo/a.sh',
                'agent-demo/CON.md','agent-demo/a\n.md','.github/workflows/a.yml'):
            with self.subTest(path=path),self.assertRaises(ValueError):self.parse(self.model|{'files':{path:'x\n'}})
        for content in ('x\0\n','x\r\n','x'*8193+'\n',{'mode':'120000','content':'symlink'}):
            with self.subTest(content=str(content)[:30]),self.assertRaises(ValueError):
                self.parse(self.model|{'files':{'agent-demo/a.md':content}})

    def test_oversize_prefix_conflicts_and_invalid_host_binding_are_denied(self):
        for files in ({f'agent-demo/{i}.md':'x\n' for i in range(5)},
                {f'agent-demo/{i}.md':'x'*6000+'\n' for i in range(3)},
                {'agent-demo/a.md':'x\n','agent-demo/a.md/child.md':'x\n'}):
            with self.assertRaises(ValueError):self.parse(self.model|{'files':files})
        for key in self.host:
            with self.subTest(key=key),self.assertRaises(ValueError):self.parse(**{key:'invalid'})

    def test_duplicate_json_keys_and_model_text_outside_json_are_denied(self):
        self.parse()
        for raw in (b'{"schema":"x","schema":"x"}',b'```json\n{}\n```',b'null',b'[]'):
            with self.assertRaises(ValueError):git_publish.RemoteGitPlan.from_model(raw,**self.host)

    def test_full_base_tree_is_verified_and_only_new_ordinary_files_are_added(self):
        self.assertTrue(hasattr(git_publish,'GitTreeSnapshot'))
        def obj(kind,data):return hashlib.sha1(kind.encode()+b' '+str(len(data)).encode()+b'\0'+data).hexdigest()
        blob=obj('blob',b'base\n');root=obj('tree',b'100644 README.md\0'+bytes.fromhex(blob))
        response={'sha':root,'truncated':False,'tree':[{'path':'README.md','mode':'100644','type':'blob','sha':blob}]}
        base=git_publish.GitTreeSnapshot.from_github(response,expected_sha=root)
        plan=self.parse(base_tree_sha=root);changed=base.add_files(plan.files)
        self.assertEqual(base.entries['README.md'],changed.entries['README.md'])
        self.assertEqual(('100644','blob',obj('blob',plan.files['agent-demo/example.md'])),changed.entries['agent-demo/example.md'])
        sub=obj('tree',b'100644 example.md\0'+bytes.fromhex(changed.entries['agent-demo/example.md'][2]))
        expected=obj('tree',b'100644 README.md\0'+bytes.fromhex(blob)+b'40000 agent-demo\0'+bytes.fromhex(sub))
        self.assertEqual(expected,changed.sha)
        self.assertEqual(root,base.sha)
        with self.assertRaises(ValueError):base.add_files({'README.md':b'overwrite\n'})
        for invalid in (response|{'truncated':True},response|{'sha':'f'*40},response|{'tree':[]}):
            with self.assertRaises(ValueError):git_publish.GitTreeSnapshot.from_github(invalid,expected_sha=root)

    def test_existing_symlink_cannot_become_a_parent_directory(self):
        self.assertTrue(hasattr(git_publish,'GitTreeSnapshot'))
        sha=git_publish.git_object('blob',b'elsewhere')
        root=git_publish.git_object('tree',b'120000 agent-demo\0'+bytes.fromhex(sha))
        base=git_publish.GitTreeSnapshot.from_github({'sha':root,'truncated':False,'tree':[
            {'path':'agent-demo','mode':'120000','type':'blob','sha':sha}]},expected_sha=root)
        with self.assertRaises(ValueError):base.add_files(self.parse().files)

    def test_commit_is_predictable_before_post_and_binds_parent_identity_time_and_message(self):
        plan=self.parse();payload=plan.commit_payload('a'*40)
        identity=b'AIOA Core <aioa-core@aioa.invalid> 1793844000 +0000'
        raw=b'tree '+b'a'*40+b'\nparent '+b'2'*40+b'\nauthor '+identity+b'\ncommitter '+identity+b'\n\n'+plan.message.encode()
        expected=hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        self.assertEqual(expected,plan.commit_sha_for_tree('a'*40))
        self.assertEqual(['2'*40],payload['parents']);self.assertEqual(payload['author'],payload['committer'])
        self.assertEqual('AIOA Core',payload['author']['name'])
        self.assertNotEqual(expected,self.parse(issued_at=1793844001).commit_sha_for_tree('a'*40))
        self.assertNotEqual(plan.digest,self.parse(base_sha='b'*40).digest)


if __name__=='__main__':unittest.main()
