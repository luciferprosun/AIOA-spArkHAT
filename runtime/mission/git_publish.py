"""Canonical selective Git publisher port; inert previews and closed remote gate.

Lineage: AG04 GitPublishOperation/Registry and predict_public_commit contracts
(see docs/unification). Native effects use the existing Core and sandbox broker.
No W7A imports, second runtime, credential loader or direct remote subprocess.
"""
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType

from runtime.mission.git_recipe import git_object, IDENT, canonical, sha256, require
from runtime.mission.warrant import require as core_require

REPOSITORY='luciferprosun/AIOA-spArkHAT'
BRANCH_PREFIX='codex/aioa-sensorbridge-'
DEMO_REPOSITORY='luciferprosun/AIOA-spArkHAT-Meta-Hackathon-2026'
DEMO_REPOSITORY_ID=1445911975
# v3 host fixture pin: Ubuntu git 1:2.43.0-1ubuntu7.4; dpkg -V git clean.
# Historical SyntheticGitPlan's v1 pin remains unchanged.
LOCAL_GIT_SHA256='eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'


@dataclass(frozen=True, slots=True)
class LocalGitPlan:
    files: dict
    source_receipt_sha256: str
    operation_id: str

    def __post_init__(self):
        require(type(self.files) is dict and 0<len(self.files)<=8,'GIT_FILES_REQUIRED')
        require(type(self.source_receipt_sha256) is str and re.fullmatch('[a-f0-9]{64}',self.source_receipt_sha256)
            and type(self.operation_id) is str and re.fullmatch('[a-f0-9]{32}',self.operation_id),'GIT_SOURCE_BINDING')
        for name,data in self.files.items():
            require(type(name) is str and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',name)
                and name not in ('.git','HEAD','config') and type(data) is bytes and 0<len(data)<=8192
                and b'\0' not in data and data.endswith(b'\n'),'GIT_FILE_SCOPE_DENIED')
            data.decode('utf-8')
        object.__setattr__(self,'files',MappingProxyType(dict(sorted(self.files.items()))))

    @property
    def branch(self):return BRANCH_PREFIX+self.operation_id

    @property
    def message(self):return ('aioa: add verified SensorBridge '+self.operation_id+' [skip ci]\n').encode()

    @property
    def tree_sha(self):
        return git_object('tree',b''.join(b'100644 '+name.encode()+b'\0'+bytes.fromhex(git_object('blob',data))
            for name,data in self.files.items()))

    @property
    def commit_sha(self):
        return git_object('commit',b'tree '+self.tree_sha.encode()+b'\nauthor '+IDENT+b'\ncommitter '+IDENT+b'\n\n'+self.message)

    def diff_bytes(self):
        chunks=[]
        for name,data in self.files.items():
            n=name.encode(); blob=git_object('blob',data).encode();lines=data.splitlines(keepends=True)
            count=b'1' if len(lines)==1 else b'1,'+str(len(lines)).encode()
            chunks.append(b'diff --git a/'+n+b' b/'+n+b'\nnew file mode 100644\nindex '+b'0'*40+b'..'+blob+
                b'\n--- /dev/null\n+++ b/'+n+b'\n@@ -0,0 +'+count+b' @@\n'+b''.join(b'+'+line for line in lines))
        return b''.join(chunks)

    def manifest(self):return {n:{'sha256':sha256(d),'bytes':len(d)} for n,d in self.files.items()}

    def plan_bytes(self):
        return canonical({'schema':'aioa.local-git-plan.v3','repository':REPOSITORY,'branch':self.branch,
            'expected_revision':'empty-repo-v1','tree_sha':self.tree_sha,'commit_sha':self.commit_sha,
            'files':self.manifest(),'diff_sha256':sha256(self.diff_bytes()),
            'source_receipt_sha256':self.source_receipt_sha256,'operation_id':self.operation_id,
            'git_sha256':LOCAL_GIT_SHA256})

    @property
    def digest(self):return sha256(self.plan_bytes())

    def preview(self):
        return {**json.loads(self.plan_bytes()),'diff':self.diff_bytes().decode(),
            'authority':'NONE','remote_write_allowed':False,'draft':True,
            'remote_gate':'BLOCKED_EXACT_OWNER_GO_AND_CREATE_ONLY_TRANSPORT',
            'force':False,'protected_branch_write':False,'model_has_credentials':False,
            'local_repository_profile':'DISPOSABLE_OFFLINE_FIXTURE','canonical_base_verified':False}

    def result_bytes(self):
        return canonical({'schema':'aioa.local-git-result.v3','plan_digest':self.digest,
            'branch':self.branch,'head':self.commit_sha,'tree':self.tree_sha,'status':'CLEAN',
            'files':self.manifest(),'source_receipt_sha256':self.source_receipt_sha256,
            'diff_sha256':sha256(self.diff_bytes()),'remote_write_performed':False})

    def recipe_spec(self):
        root=Path(__file__).parent
        return {'files':{'recipe.py':(root/'git_publish_worker.py').read_bytes(),
            'git_helpers.py':(root/'git_worker.py').read_bytes(),'plan.json':self.plan_bytes(),
            'commit-message.txt':self.message,'diff.patch':self.diff_bytes(),
            **{'source-'+n:d for n,d in self.files.items()}},
            'expected':{'result.json':self.result_bytes(),'diff.patch':self.diff_bytes(),
                **dict(self.files)}}


def _tree_hashes(entries):
    """Hash every directory from complete entries using existing Git hashing."""
    groups={'':[]}
    for path,(mode,kind,sha) in entries.items():
        parent,_,name=path.rpartition('/')
        require(not parent or parent in entries and entries[parent][:2]==('040000','tree'),'GITHUB_TREE_PARENT_DENIED')
        groups.setdefault(parent,[]).append((name,mode,kind,sha,path))
        if kind=='tree':groups.setdefault(path,[])
    hashes={}
    for directory in sorted(groups,key=lambda p:len(p.split('/')) if p else 0,reverse=True):
        chunks=[]
        for name,mode,kind,sha,path in sorted(groups[directory],key=lambda e:e[0].encode()+ (b'/' if e[2]=='tree' else b'\0')):
            object_sha=hashes[path] if kind=='tree' else sha
            chunks.append(('40000' if kind=='tree' else mode).encode()+b' '+name.encode()+b'\0'+bytes.fromhex(object_sha))
        hashes[directory]=git_object('tree',b''.join(chunks))
    return hashes


@dataclass(frozen=True, slots=True)
class GitTreeSnapshot:
    """Complete immutable tree evidence; truncated API lists are insufficient."""
    sha: str
    entries: dict

    def __post_init__(self):
        require(type(self.sha) is str and re.fullmatch('[a-f0-9]{40}',self.sha),'GITHUB_TREE_SHA_DENIED')
        require(type(self.entries) is dict and len(self.entries)<=4096,'GITHUB_TREE_LIMIT')
        allowed={('100644','blob'),('100755','blob'),('120000','blob'),('040000','tree'),('160000','commit')}
        for path,value in self.entries.items():
            require(type(path) is str and 1<=len(path.encode())<=512 and '\0' not in path
                and all(p and p not in ('.','..') for p in path.split('/')) and len(path.split('/'))<=32,
                'GITHUB_TREE_PATH_DENIED')
            require(type(value) is tuple and len(value)==3 and value[:2] in allowed
                and type(value[2]) is str and re.fullmatch('[a-f0-9]{40}',value[2]),'GITHUB_TREE_ENTRY_DENIED')
        hashes=_tree_hashes(self.entries)
        require(hashes['']==self.sha and all(value[1]!='tree' or hashes[path]==value[2]
            for path,value in self.entries.items()),'GITHUB_TREE_HASH_MISMATCH')
        object.__setattr__(self,'entries',MappingProxyType(dict(self.entries)))

    @classmethod
    def from_github(cls,value,*,expected_sha):
        require(type(value) is dict and value.get('sha')==expected_sha and value.get('truncated') is False
            and type(value.get('tree')) is list and len(value['tree'])<=4096,'GITHUB_TREE_READBACK_DENIED')
        entries={}
        for entry in value['tree']:
            require(type(entry) is dict and type(entry.get('path')) is str and entry['path'] not in entries,
                'GITHUB_TREE_ENTRY_DENIED')
            entries[entry['path']]=(entry.get('mode'),entry.get('type'),entry.get('sha'))
        return cls(expected_sha,entries)

    def add_files(self,files):
        entries=dict(self.entries)
        for path,data in files.items():
            require(type(path) is str and path.startswith('agent-demo/') and path not in entries
                and type(data) is bytes,'GITHUB_CREATE_ONLY_REQUIRED')
            parts=path.split('/')
            for index in range(1,len(parts)):
                parent='/'.join(parts[:index])
                if parent in entries:require(entries[parent][:2]==('040000','tree'),'GITHUB_TREE_PARENT_DENIED')
                else:entries[parent]=('040000','tree','0'*40)
            entries[path]=('100644','blob',git_object('blob',data))
        hashes=_tree_hashes(entries)
        for path,value in tuple(entries.items()):
            if value[1]=='tree':entries[path]=('040000','tree',hashes[path])
        return GitTreeSnapshot(hashes[''],entries)


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteGitPlan:
    """Pure remote review data. Construction grants no dispatch capability.

    Model content and native provenance are separate inputs. Base/source/branch
    bindings cannot be supplied through model JSON. Existing local plan and
    network-OFF recipe contracts are unchanged.
    """
    files: dict
    title: str
    body: str
    operation_id: str
    issued_at: int
    base_sha: str
    base_tree_sha: str
    source_sha: str
    capsule_digest: str
    source_reply_sha256: str
    source_receipt_sha256: str

    def __post_init__(self):
        require(type(self.issued_at) is int and 1<=self.issued_at<=253402300799,'GITHUB_TIME_BINDING')
        for name,size in (('operation_id',32),('base_sha',40),('base_tree_sha',40),
                ('source_sha',40),('capsule_digest',64),('source_reply_sha256',64),('source_receipt_sha256',64)):
            value=getattr(self,name)
            require(type(value) is str and re.fullmatch('[a-f0-9]{'+str(size)+'}',value),'GITHUB_SOURCE_BINDING')
        require(type(self.title) is str and self.title.strip() and len(self.title.encode())<=160
            and all(ord(c)>=32 and ord(c)!=127 for c in self.title),'GITHUB_TITLE_DENIED')
        require(type(self.body) is str and self.body.strip() and len(self.body.encode())<=4000
            and all(c in '\n\t' or ord(c)>=32 and ord(c)!=127 for c in self.body),'GITHUB_BODY_DENIED')
        require(type(self.files) is dict and 1<=len(self.files)<=4,'GITHUB_FILES_REQUIRED')
        clean={};folded=set()
        reserved={'con','prn','aux','nul',*(f'com{i}' for i in range(1,10)),*(f'lpt{i}' for i in range(1,10))}
        for path,data in self.files.items():
            require(type(path) is str and len(path)<=160,'GITHUB_PATH_DENIED')
            parts=path.split('/')
            require(2<=len(parts)<=4 and parts[0]=='agent-demo'
                and all(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,47}',p) for p in parts[1:-1])
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}\.(?:md|txt|py)',parts[-1])
                and all(p.split('.')[0].lower() not in reserved for p in parts)
                and path.lower() not in folded,'GITHUB_PATH_DENIED')
            require(type(data) is bytes and 1<=len(data)<=8192 and data.endswith(b'\n')
                and b'\x00' not in data and b'\r' not in data,'GITHUB_CONTENT_DENIED')
            content=data.decode('utf-8')
            require(all(c in '\n\t' or ord(c)>=32 and ord(c)!=127 for c in content),'GITHUB_CONTENT_DENIED')
            clean[path]=data;folded.add(path.lower())
        require(sum(map(len,clean.values()))<=16384,'GITHUB_CONTENT_LIMIT')
        object.__setattr__(self,'files',MappingProxyType(dict(sorted(clean.items()))))

    @classmethod
    def from_model(cls,raw,**native_binding):
        from runtime.mobile_gateway.wire import strict_json,RESPONSE_LIMIT
        require(type(raw) is bytes and len(raw)<=32768,'GITHUB_PROPOSAL_LIMIT')
        value=strict_json(raw,limit=RESPONSE_LIMIT)
        require(type(value) is dict and set(value)=={'schema','operation','target_repo','files','title','body'}
            and value['schema']=='aioa.muse.github-change.v1'
            and value['operation']=='code.commit_draft_pr' and value['target_repo']==DEMO_REPOSITORY,
            'GITHUB_PROPOSAL_SCOPE_DENIED')
        require(type(value['files']) is dict and all(type(v) is str for v in value['files'].values()),'GITHUB_FILES_REQUIRED')
        return cls(files={k:v.encode('utf-8') for k,v in value['files'].items()},
            title=value['title'],body=value['body'],**native_binding)

    @property
    def branch(self):return 'aioa/muse-'+self.operation_id

    @property
    def message(self):return self.title+'\n\nAIOA operation: '+self.operation_id+'\n'

    def commit_payload(self,tree_sha):
        from datetime import datetime,timezone
        require(type(tree_sha) is str and re.fullmatch('[a-f0-9]{40}',tree_sha),'GITHUB_TREE_SHA_DENIED')
        identity={'name':'AIOA Core','email':'aioa-core@aioa.invalid',
            'date':datetime.fromtimestamp(self.issued_at,timezone.utc).isoformat().replace('+00:00','Z')}
        return {'message':self.message,'tree':tree_sha,'parents':[self.base_sha],
            'author':dict(identity),'committer':dict(identity)}

    def commit_sha_for_tree(self,tree_sha):
        self.commit_payload(tree_sha)
        identity=b'AIOA Core <aioa-core@aioa.invalid> '+str(self.issued_at).encode()+b' +0000'
        raw=(b'tree '+tree_sha.encode()+b'\nparent '+self.base_sha.encode()+b'\nauthor '+identity+
            b'\ncommitter '+identity+b'\n\n'+self.message.encode())
        return git_object('commit',raw)

    def manifest(self):
        return {p:{'sha256':sha256(data),'git_blob_sha':git_object('blob',data),
                   'bytes':len(data),'mode':'100644'} for p,data in self.files.items()}

    def diff_bytes(self):
        from difflib import unified_diff
        return ''.join('diff --git a/'+p+' b/'+p+'\nnew file mode 100644\n'+
            ''.join(unified_diff([],data.decode().splitlines(keepends=True),fromfile='/dev/null',tofile='b/'+p))
            for p,data in self.files.items()).encode()

    def payload(self):
        return {'schema':'aioa.remote-git-plan.v1','repository':DEMO_REPOSITORY,'repository_id':DEMO_REPOSITORY_ID,
            'operation':'code.commit_draft_pr','operation_id':self.operation_id,'issued_at':self.issued_at,
            'commit_identity':self.commit_payload(self.base_tree_sha)['author'],'base_ref':'main','base_sha':self.base_sha,
            'base_tree_sha':self.base_tree_sha,'branch':self.branch,'commit_message':self.message,
            'pr_title':self.title,'pr_body':self.body,'draft':True,'force':False,'merge':False,
            'files':{p:data.decode() for p,data in self.files.items()},'manifest':self.manifest(),
            'diff_sha256':sha256(self.diff_bytes()),'source_sha':self.source_sha,'capsule_digest':self.capsule_digest,
            'source_reply_sha256':self.source_reply_sha256,'source_receipt_sha256':self.source_receipt_sha256}

    @property
    def digest(self):return sha256(canonical(self.payload()))

    def preview(self):
        return {**self.payload(),'plan_digest':self.digest,'diff':self.diff_bytes().decode(),
            'authority':'NONE','execution_authorized':False}


class RemotePublishBoundary:
    """No default network actuator or authority inferred from a preview.

    An actual create-only transport, credentials and exact per-step native GO
    remain a separate gate. Observations below classify uncertainty, not effects.
    """
    def dispatch(self, operation, proposal):
        raise ValueError('GITHUB_REMOTE_BLOCKED_SEPARATE_EXACT_OWNER_GO')

    @staticmethod
    def classify_observation(status):
        state='DENIED' if status in (401,403) else 'BLOCKED_RATE_LIMIT' if status==429 else 'UNKNOWN'
        return {'state':state,'automatic_retry':False,'effect_verified':False,'authority':'NONE'}


class CoreRemoteGitRoute:
    """Registered remote slice on the existing Core journal and ServiceGuard.

    Construction is Native-only. api_factory/check/target_guard are trusted host
    ports, never values supplied by a model or HTTP client. Credential creation
    is deferred until the existing owner-wide START barrier has admitted the
    exact operation. The route owns no separate Core, governor or state store.
    """
    def __init__(self,journal,*,plan,base,identity,api_factory,check,target_guard,mode):
        from runtime.mission.intent import CoreIntentJournal
        from runtime.mobile_gateway.wire import Identity
        core_require(type(journal) is CoreIntentJournal and type(plan) is RemoteGitPlan
            and type(base) is GitTreeSnapshot and base.sha==plan.base_tree_sha and type(identity) is Identity
            and callable(api_factory) and callable(check) and callable(target_guard)
            and mode in ('LIVE','OFFLINE_FIXTURE'),'GITHUB_NATIVE_ROUTE_REQUIRED')
        self.journal,self.plan,self.base,self.identity=journal,plan,base,identity
        self.core,self.runner,self.scope=journal.ledger.core,journal.ledger.runner,journal.ledger.scope
        self.api_factory,self.check,self.target_guard,self.mode=api_factory,check,target_guard,mode
        self.tree=base.add_files(plan.files)

    @property
    def dependency_root(self):
        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.evidence import EvidenceRef
        return DecisionDependencyRoot((
            EvidenceRef('github-plan','task','sha256:'+self.plan.digest,'v1'),
            EvidenceRef('muse-receipt','receipt','sha256:'+self.plan.source_receipt_sha256,'v1'),
            EvidenceRef('native-source','context','sha256:'+self.plan.capsule_digest,self.plan.source_sha)))

    def operation(self,session_id,epoch):
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        return {'operation_class':'GITHUB_CREATE_COMMIT_PR_V1',
            'target_fingerprint':'sha256:'+canonical_sha256({'repository':DEMO_REPOSITORY,'repository_id':DEMO_REPOSITORY_ID}),
            'expected_target_revision':'git-'+self.plan.base_sha,'payload':{
                'schema':'aioa.github-remote-operation.v1','repository_id':DEMO_REPOSITORY_ID,
                'principal_session_id':session_id,'policy_epoch':epoch,'mode':self.mode,
                'plan':self.plan.payload(),'plan_digest':self.plan.digest,'tree_sha':self.tree.sha,
                'commit_sha':self.plan.commit_sha_for_tree(self.tree.sha)}}

    def validate(self,tx,warrant,operation,*,consumed=False):
        core_require(operation==self.operation(tx.context.principal.actor_session_id,warrant.lease_epoch)
            and warrant.decision_dependency_root==self.dependency_root,'GITHUB_WARRANT_BINDING_MISMATCH')
        core_require((warrant.expires_at-warrant.issued_at).total_seconds()<=300,'GITHUB_WARRANT_WINDOW_DENIED')
        governor=self.journal.governor;state=governor._load(tx);governor._epoch(state,warrant.lease_epoch)
        core_require(not state['kill'],'KILL_SWITCH')
        self.journal.ledger.require_active_in_transaction(tx,warrant,consumed=consumed)

    def _save(self,tx,key,data):
        from runtime.memory_patch.audit import append_domain_event
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.idempotency import OperationBinding
        from runtime.memory_patch.persistence.ports import RecordKind,StoredRecord
        prior=tx.get(RecordKind.OPERATION,key)
        row=StoredRecord(RecordKind.OPERATION,key,self.scope,prior.revision+1 if prior else 1,data)
        if prior:tx.replace(row,expected_revision=prior.revision)
        else:tx.insert(row)
        identity=canonical_sha256([key,row.revision])
        operation=OperationBinding.bind('github-op-'+identity,'GITHUB_CORE_RECORD',
            {'record_digest':row.payload_digest,'plan_digest':self.plan.digest})
        append_domain_event(tx,operation,event_id='github-audit-'+identity,proof_id='github-outbox-'+identity,
            resource_id=key,before=prior.payload['state'] if prior else None,after=data['state'],
            content_digest=row.payload_digest,at=self.journal.ledger.clock())
        return row

    def begin_step(self,principal,warrant,operation,step,digest):
        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mcp_bridge.github_remote import PREFIX
        p=self.plan
        expected={
            'tree':('/git/trees',{'base_tree':self.base.sha,'tree':[
                {'path':path,'mode':'100644','type':'blob','content':data.decode()} for path,data in p.files.items()]}),
            'commit':('/git/commits',p.commit_payload(self.tree.sha)),
            'branch':('/git/refs',{'ref':'refs/heads/'+p.branch,'sha':p.commit_sha_for_tree(self.tree.sha)}),
            'draft_pr':('/pulls',{'title':p.title,'body':p.body,'head':p.branch,'base':'main','draft':True,
                                'maintainer_can_modify':False})}
        core_require(step in expected and digest==sha256(canonical({'method':'POST','path':PREFIX+expected[step][0],
            'payload':expected[step][1]})),'GITHUB_STEP_BINDING_MISMATCH')
        key='github-step-'+p.operation_id+'-'+step
        def start(tx):
            self.validate(tx,warrant,operation,consumed=True)
            _,intent=self.journal._load(tx,warrant)
            core_require(intent is not None and intent['resolution'] is None,'GITHUB_INTENT_REQUIRED')
            if tx.get(RecordKind.OPERATION,key) is not None:return False
            earlier=list(expected)[:list(expected).index(step)]
            core_require(all(tx.get(RecordKind.OPERATION,'github-step-'+p.operation_id+'-'+s) is not None for s in earlier),
                'GITHUB_STEP_ORDER_DENIED')
            self._save(tx,key,{'schema':'aioa.github-step.v1','state':'GITHUB_STEP_UNKNOWN',
                'step':step,'request_digest':digest,'warrant_digest':warrant.digest(),
                'operation_hash':warrant.operation_hash,'automatic_retry':False})
            return True
        return self.journal._run(principal,Capability.COMMIT,start)

    def bind_api(self,check,cancel):
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly
        api=self.api_factory(check,cancel)
        core_require(type(api) is GitHubCreateOnly and api.plan==self.plan and api.base==self.base
            and api.mode==self.mode and (api._transport is None if self.mode=='LIVE' else callable(api._transport)),
            'GITHUB_REGISTERED_EXECUTOR_REQUIRED')
        return api

    def result(self,principal):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.memory_patch.persistence.ports import RecordKind
        def read(tx):
            row=tx.get(RecordKind.OPERATION,'github-result-'+self.plan.operation_id)
            return json.loads(canonical_json_bytes(row.payload))['result'] if row else None
        return self.journal._run(principal,Capability.READ,read)

    def complete(self,principal,warrant,observation,*,historical=False):
        from runtime.core_admission import Capability
        from runtime.memory_patch.contracts.serialization import canonical_sha256
        from runtime.memory_patch.persistence.ports import RecordKind
        from runtime.mission.liability import Reconciliation
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import Applied
        from runtime.mobile_gateway.wire import canonical as wire_canonical
        core_require(observation['plan_digest']==self.plan.digest and observation['mode'] in
            (('LIVE','PUBLIC_READ_ONLY') if self.mode=='LIVE' else ('OFFLINE_FIXTURE',)),'GITHUB_READBACK_BINDING_MISMATCH')
        terminal=observation['remote_effect_verified'] is True
        receipt={'schema':'aioa.github-write-receipt.v1','operation_id':self.plan.operation_id,
            'plan_digest':self.plan.digest,'warrant_digest':warrant.digest(),'operation_hash':warrant.operation_hash,
            'source_reply_sha256':self.plan.source_reply_sha256,'source_receipt_sha256':self.plan.source_receipt_sha256,
            'source_sha':self.plan.source_sha,'capsule_digest':self.plan.capsule_digest,
            'observed_at':int(self.journal.ledger.clock().timestamp()),'mode':self.mode,
            'live_verified':self.mode=='LIVE' and terminal,'commit_sha':observation.get('commit_sha'),
            'github_url':observation.get('commit_url'),'pr_url':observation.get('pr_url'),
            'state':'CODE_COMMITTED_AND_DRAFT_PR_CREATED' if self.mode=='LIVE' and terminal else
                'OFFLINE_PROTOCOL_VERIFIED' if terminal else 'UNKNOWN',
            'readback_sha256':canonical_sha256(observation),'automatic_retry':False}
        result={'observation':observation,'receipt':receipt,'signature':self.identity.sign(receipt),
                'receipt_sha256':sha256(wire_canonical(receipt))}
        def save(tx):
            _,intent=self.journal._load(tx,warrant)
            core_require(intent is not None and intent['operation']['payload']['plan_digest']==self.plan.digest,
                'GITHUB_INTENT_REQUIRED')
            if intent['resolution'] is not None:return self.journal._public(intent)
            if not historical:self.validate(tx,warrant,intent['operation'],consumed=True)
            if terminal:
                for step in ('tree','commit','branch','draft_pr'):
                    key='github-step-'+self.plan.operation_id+'-'+step
                    row=tx.get(RecordKind.OPERATION,key)
                    core_require(row is not None and row.payload.get('warrant_digest')==warrant.digest()
                        and row.payload.get('operation_hash')==warrant.operation_hash,
                        'GITHUB_AIOA_DISPATCH_PROVENANCE_REQUIRED')
                    from runtime.memory_patch.contracts.serialization import canonical_json_bytes
                    data=json.loads(canonical_json_bytes(row.payload))
                    self._save(tx,key,{**data,'state':'GITHUB_STEP_VERIFIED',
                        'readback_sha256':canonical_sha256(observation)})
            self._save(tx,'github-result-'+self.plan.operation_id,{'schema':'aioa.github-result.v1',
                'state':'GITHUB_VERIFIED' if terminal else 'GITHUB_UNKNOWN','result':result})
            if not terminal:return self.journal._public(intent)
            proof=EvidenceRef('github-receipt-'+self.plan.operation_id,'receipt','sha256:'+canonical_sha256(result),'v1')
            read=EvidenceRef('github-get-'+self.plan.operation_id,'independent-readback',
                'sha256:'+canonical_sha256(observation),'v1')
            resolution=Reconciliation(warrant.operation_hash,Applied(proof.evidence_id),proof,read)
            epoch=self.journal.governor._load(tx)['epoch']
            return self.journal.apply_resolution_in_transaction(tx,warrant,epoch,resolution)
        return self.journal._run(principal,Capability.COMMIT,save)

    def dispatch(self,principal,warrant,operation,reservation,*,cancel):
        from runtime.service_guard.service import CoreServiceGuard
        return CoreServiceGuard.dispatch_registered_remote_git(self,principal,warrant,operation,reservation,cancel=cancel)

    def reconcile(self,principal,warrant,*,cancel,api=None):
        from runtime.core_admission import Capability
        from runtime.mcp_bridge.github_remote import GitHubCreateOnly
        self.core.require(principal,Capability.COMMIT,scope=self.scope)
        with self.target_guard():
            self.check()
            if self.mode=='LIVE':
                core_require(api is None,'GITHUB_READBACK_INJECTION_DENIED')
                api=GitHubCreateOnly(self.plan,self.base,None,mode='PUBLIC_READ_ONLY')
            core_require(type(api) is GitHubCreateOnly and api.plan==self.plan and api.base==self.base
                and api.mode==('PUBLIC_READ_ONLY' if self.mode=='LIVE' else 'OFFLINE_FIXTURE'),
                'GITHUB_READBACK_BINDING_MISMATCH')
            # Existing intent is required before any recovery GET. No active
            # warrant/old owner session is resurrected after restart or expiry.
            _,intent=self.journal._run(principal,Capability.COMMIT,lambda tx:self.journal._load(tx,warrant))
            core_require(intent is not None and intent['operation']['payload']['plan_digest']==self.plan.digest,
                         'GITHUB_INTENT_REQUIRED')
            observation=api.readback(check=self.check,cancel=cancel)
            self.check()
            return self.complete(principal,warrant,observation,historical=True)
