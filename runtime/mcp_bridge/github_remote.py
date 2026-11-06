"""Native GitHub API transport with an explicit, repository-scoped credential.

No ambient gh/PAT credential, proxy, redirect, automatic retry or default LIVE
mode. This port grants no Core authority. Callers must bind an existing Core
warrant and acknowledged intent before admitting any mutating request.
"""
import base64
from dataclasses import dataclass, field
from datetime import datetime, timezone
import http.client
import os
from pathlib import Path
import re
import ssl
import stat
import threading
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from runtime.mission.git_publish import DEMO_REPOSITORY, DEMO_REPOSITORY_ID, RemoteGitPlan, GitTreeSnapshot, git_object
from runtime.mission.git_recipe import canonical, require, sha256
from runtime.mobile_gateway.wire import strict_json, RESPONSE_LIMIT

API_VERSION='2026-03-10'
PERMISSIONS={'contents':'write','pull_requests':'write'}
PREFIX='/repos/'+DEMO_REPOSITORY


def _https_once(method,path,payload,bearer,cancel,timeout):
    """One bounded TLS request to the fixed host, using existing cancellation."""
    require(method in ('GET','POST') and type(path) is str and path.startswith('/')
        and not any(ord(c)<33 or ord(c)>126 for c in path),'GITHUB_TRANSPORT_DENIED')
    require(type(timeout) in (int,float) and 0<timeout<=20,'GITHUB_TIMEOUT_DENIED')
    body=None if payload is None else canonical(payload)
    require(body is None or len(body)<=RESPONSE_LIMIT,'GITHUB_REQUEST_LIMIT')
    connection=http.client.HTTPSConnection('api.github.com',timeout=timeout,context=ssl.create_default_context())
    connection.auto_open=0
    cancel.attach(connection)
    deadline=time.monotonic()+timeout
    timer=threading.Timer(timeout,cancel.interrupt_transport);timer.daemon=True;timer.start()
    try:
        cancel.check(deadline);connection.connect();cancel.track_socket(connection.sock);cancel.check(deadline)
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':API_VERSION,
                 'User-Agent':'AIOA-Core-CreateOnly/1','Content-Type':'application/json'}
        if bearer is not None:
            require(type(bearer) is str and re.fullmatch(r'[A-Za-z0-9_.-]{16,8192}',bearer),
                    'GITHUB_CREDENTIAL_FORMAT_DENIED')
            headers['Authorization']='Bearer '+bearer
        connection.request(method,path,body=body,headers=headers)
        response=connection.getresponse()
        # Never follow Location and never expose error bodies or request headers.
        if response.status not in (200,201):return response.status,b''
        raw=response.read(RESPONSE_LIMIT+1)
        require(len(raw)<=RESPONSE_LIMIT,'GITHUB_RESPONSE_LIMIT')
        cancel.check(deadline)
        return response.status,raw
    finally:
        timer.cancel();cancel.detach();connection.close()


def _private_file(root,name,limit):
    root=Path(root).absolute();info=root.lstat()
    require(root.resolve()==root and stat.S_ISDIR(info.st_mode) and info.st_uid==os.getuid()
        and not info.st_mode&0o077,'GITHUB_PRIVATE_CREDENTIAL_REQUIRED')
    fd=os.open(root/name,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info=os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1
            and not info.st_mode&0o077 and 0<info.st_size<=limit,'GITHUB_PRIVATE_CREDENTIAL_REQUIRED')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(limit+1)
        after=os.fstat(fd)
        require(len(raw)==info.st_size and (info.st_ino,info.st_size,info.st_mtime_ns)==
            (after.st_ino,after.st_size,after.st_mtime_ns),'GITHUB_PRIVATE_CREDENTIAL_REQUIRED')
        return raw
    finally:os.close(fd)


@dataclass(frozen=True,slots=True)
class InstallationCredential:
    bearer: str=field(repr=False)
    installation_id: int
    expires_at: int
    proof_digest: str
    mode: str

    def evidence(self):
        return {'schema':'aioa.github-scoped-credential.v1','mode':self.mode,
            'installation_id':self.installation_id,'repository_id':DEMO_REPOSITORY_ID,'repository':DEMO_REPOSITORY,
            'permissions':dict(PERMISSIONS),'expires_at':self.expires_at,
            'scope_readback_sha256':self.proof_digest,'credential_disclosed':False}


class GitHubAppCredentialSource:
    """Narrow a private App installation to this demo and verify its scope."""
    def __init__(self,root,*,mode='DISABLED',transport=None,clock=time.time):
        require(mode in ('DISABLED','OFFLINE_FIXTURE','LIVE') and callable(clock)
            and (callable(transport) if mode=='OFFLINE_FIXTURE' else transport is None),
            'GITHUB_CREDENTIAL_CONFIGURATION_DENIED')
        self.root,self.mode,self._transport,self.clock=Path(root),mode,transport,clock

    def configuration(self):
        """Private validation only. No credential, signature or network output."""
        try:
            value=strict_json(_private_file(self.root,'app.json',4096))
            require(set(value)=={'schema','client_id','installation_id'} and value['schema']=='aioa.github-app.v1'
                and type(value['client_id']) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',value['client_id'])
                and type(value['installation_id']) is int and 1<=value['installation_id']<=2**53,
                'GITHUB_PRIVATE_CREDENTIAL_REQUIRED')
            key=serialization.load_pem_private_key(_private_file(self.root,'private-key.pem',16384),password=None)
            require(isinstance(key,rsa.RSAPrivateKey) and 2048<=key.key_size<=4096,
                    'GITHUB_PRIVATE_CREDENTIAL_REQUIRED')
            return value,key
        except (OSError,ValueError,TypeError):
            raise ValueError('GITHUB_PRIVATE_CREDENTIAL_REQUIRED') from None

    def mint(self,*,cancel,check):
        require(self.mode!='DISABLED' and callable(check),'GITHUB_CREDENTIAL_DISABLED')
        config,key=self.configuration();now=int(self.clock());check()
        require(not cancel.cancelled,'GITHUB_STOPPED')
        encode=lambda b:base64.urlsafe_b64encode(b).rstrip(b'=')
        data=b'.'.join((encode(canonical({'alg':'RS256','typ':'JWT'})),
            encode(canonical({'iss':config['client_id'],'iat':now-60,'exp':now+120}))))
        jwt=(data+b'.'+encode(key.sign(data,padding.PKCS1v15(),hashes.SHA256()))).decode()
        transport=self._transport if self.mode=='OFFLINE_FIXTURE' else _https_once
        try:
            status,raw=transport('POST','/app/installations/'+str(config['installation_id'])+'/access_tokens',
                {'repository_ids':[DEMO_REPOSITORY_ID],'permissions':dict(PERMISSIONS)},jwt,cancel,15)
            require(status==201,'GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY')
            value=strict_json(raw,limit=RESPONSE_LIMIT)
        except Exception:
            raise ValueError('GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY') from None
        permissions=value.get('permissions');repositories=value.get('repositories')
        require(type(permissions) is dict and set(permissions) in (set(PERMISSIONS),set(PERMISSIONS)|{'metadata'})
            and all(permissions.get(k)==v for k,v in PERMISSIONS.items())
            and permissions.get('metadata','read')=='read' and value.get('repository_selection')=='selected',
            'GITHUB_CREDENTIAL_SCOPE_DENIED')
        expected=[(DEMO_REPOSITORY_ID,DEMO_REPOSITORY)]
        require(type(repositories) is list and all(type(r) is dict for r in repositories)
            and [(r.get('id'),r.get('full_name')) for r in repositories]==expected,'GITHUB_CREDENTIAL_SCOPE_DENIED')
        token=value.get('token')
        # Installation tokens are opaque, including GitHub's 2026 stateless
        # ghs_APPID_JWT format. Keep the transport bound and reject header bytes.
        require(type(token) is str and re.fullmatch(r'[A-Za-z0-9_.-]{16,8192}',token),'GITHUB_CREDENTIAL_SCOPE_DENIED')
        try:
            expiry=datetime.strptime(value['expires_at'],'%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
            require(60<expiry-now<=3600,'GITHUB_CREDENTIAL_SCOPE_DENIED')
        except (KeyError,TypeError,ValueError):raise ValueError('GITHUB_CREDENTIAL_SCOPE_DENIED') from None
        check();require(not cancel.cancelled,'GITHUB_STOPPED')
        try:
            status,raw=transport('GET','/installation/repositories?per_page=100&page=1',None,token,cancel,15)
            require(status==200,'GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY')
            result=strict_json(raw,limit=RESPONSE_LIMIT)
        except Exception:raise ValueError('GITHUB_CREDENTIAL_UNKNOWN_NO_RETRY') from None
        listed=result.get('repositories')
        require(type(result.get('total_count')) is int and result['total_count']==1 and type(listed) is list
            and all(type(r) is dict for r in listed)
            and [(r.get('id'),r.get('full_name')) for r in listed]==expected,'GITHUB_CREDENTIAL_SCOPE_DENIED')
        require(int(self.clock())<expiry and not cancel.cancelled,'GITHUB_CREDENTIAL_EXPIRED')
        proof=sha256(canonical({'installation_id':config['installation_id'],'repository_ids':[DEMO_REPOSITORY_ID],
            'repositories':expected,'permissions':permissions,'expires_at':int(expiry)}))
        return InstallationCredential(token,config['installation_id'],int(expiry),proof,self.mode)


class GitHubCreateOnly:
    """One exact plan, four create-only steps, then independent GET evidence.

    No step can be resumed or retried here. The caller supplies Core's durable
    first-attempt marker; a new object cannot erase it. Readback never POSTs.
    A transport fixture is explicitly labeled and cannot be installed as LIVE.
    """
    def __init__(self,plan,base,credential,*,mode='DISABLED',transport=None,clock=time.time):
        require(type(plan) is RemoteGitPlan and type(base) is GitTreeSnapshot
            and base.sha==plan.base_tree_sha and (type(credential) is InstallationCredential
                or credential is None and mode=='PUBLIC_READ_ONLY'),
            'GITHUB_PLAN_BINDING_REQUIRED')
        require(mode in ('DISABLED','OFFLINE_FIXTURE','LIVE','PUBLIC_READ_ONLY')
            and (credential is None or credential.mode==mode)
            and (callable(transport) if mode=='OFFLINE_FIXTURE' else transport is None)
            and callable(clock),'GITHUB_TRANSPORT_CONFIGURATION_DENIED')
        require(credential is None or type(credential.proof_digest) is str and re.fullmatch('[a-f0-9]{64}',credential.proof_digest)
            and type(credential.installation_id) is int and credential.installation_id>0,
            'GITHUB_CREDENTIAL_SCOPE_DENIED')
        self.plan,self.base,self.credential,self.mode=plan,base,credential,mode
        self.tree=base.add_files(plan.files);self.commit_sha=plan.commit_sha_for_tree(self.tree.sha)
        self._transport,self.clock=transport,clock
        self._attempted=set();self.request_count=0
        self.pull_query=PREFIX+'/pulls?head=luciferprosun%3Aaioa%2Fmuse-'+plan.operation_id+'&base=main&state=all&per_page=2'

    def _call(self,method,path,payload,*,check,cancel,deadline,absent=False):
        require(self.mode!='DISABLED','GITHUB_REMOTE_DISABLED')
        require(self.mode!='PUBLIC_READ_ONLY' or method=='GET','GITHUB_READBACK_ONLY')
        allowed_get={PREFIX,PREFIX+'/git/ref/heads/main',PREFIX+'/git/ref/heads/'+self.plan.branch,
            PREFIX+'/git/commits/'+self.plan.base_sha,PREFIX+'/git/commits/'+self.commit_sha,
            PREFIX+'/git/trees/'+self.base.sha+'?recursive=1',PREFIX+'/git/trees/'+self.tree.sha+'?recursive=1',
            self.pull_query,*(PREFIX+'/git/blobs/'+m['git_blob_sha'] for m in self.plan.manifest().values())}
        require((method=='GET' and payload is None and (path in allowed_get or
            re.fullmatch(re.escape(PREFIX)+r'/pulls/[1-9][0-9]{0,8}',path))) or
            (method=='POST' and path in {PREFIX+'/git/trees',PREFIX+'/git/commits',PREFIX+'/git/refs',PREFIX+'/pulls'}),
            'GITHUB_ENDPOINT_DENIED')
        check();cancel.check(deadline)
        require(self.credential is None or int(self.clock())<self.credential.expires_at,'GITHUB_CREDENTIAL_EXPIRED')
        require(self.request_count<self.plan.payload()['api_request_limit'],'GITHUB_API_BUDGET_EXHAUSTED')
        self.request_count+=1
        transport=self._transport if self.mode=='OFFLINE_FIXTURE' else _https_once
        try:
            status,raw=transport(method,path,payload,self.credential.bearer if self.credential else None,
                cancel,min(15,deadline-time.monotonic()))
        except Exception:
            raise ValueError('GITHUB_WRITE_UNKNOWN_NO_RETRY' if method=='POST' else 'GITHUB_GET_UNVERIFIED') from None
        if status in (401,403,429):
            if method=='POST':raise ValueError('GITHUB_WRITE_UNKNOWN_HTTP_'+str(status)+'_NO_RETRY')
            raise ValueError({401:'GITHUB_AUTHENTICATION_401',403:'GITHUB_PERMISSION_403',429:'GITHUB_RATE_LIMIT_429'}[status])
        try:
            if absent and method=='GET' and status==404:return None
            require(status==(201 if method=='POST' else 200),'GITHUB_HTTP_STATUS_UNCONFIRMED')
            # Reuse the existing bounded duplicate-key/number/depth decoder.
            value=strict_json(b'{"items":'+raw+b'}',limit=RESPONSE_LIMIT)['items'] if path==self.pull_query else strict_json(raw,limit=RESPONSE_LIMIT)
            cancel.check(deadline)
            return value
        except Exception:
            raise ValueError('GITHUB_WRITE_UNKNOWN_NO_RETRY' if method=='POST' else 'GITHUB_GET_UNVERIFIED') from None

    def _repo(self,**args):
        value=self._call('GET',PREFIX,None,**args)
        require(value.get('id')==DEMO_REPOSITORY_ID and value.get('full_name')==DEMO_REPOSITORY
            and value.get('default_branch')=='main' and value.get('private') is False
            and value.get('archived') is False and value.get('disabled') is False,'GITHUB_REPOSITORY_READBACK_MISMATCH')

    def _main(self,**args):
        value=self._call('GET',PREFIX+'/git/ref/heads/main',None,**args)
        require(value.get('ref')=='refs/heads/main' and value.get('object',{}).get('type')=='commit'
            and value['object'].get('sha')==self.plan.base_sha,'GITHUB_BASE_CHANGED')

    def preflight(self,*,check,cancel,deadline=None):
        args={'check':check,'cancel':cancel,'deadline':deadline or time.monotonic()+60}
        self._repo(**args);self._main(**args)
        value=self._call('GET',PREFIX+'/git/commits/'+self.plan.base_sha,None,**args)
        require(value.get('sha')==self.plan.base_sha and value.get('tree',{}).get('sha')==self.base.sha,
                'GITHUB_BASE_CHANGED')
        value=self._call('GET',PREFIX+'/git/trees/'+self.base.sha+'?recursive=1',None,**args)
        require(GitTreeSnapshot.from_github(value,expected_sha=self.base.sha)==self.base,'GITHUB_BASE_CHANGED')
        value=self._call('GET',PREFIX+'/git/ref/heads/'+self.plan.branch,None,absent=True,**args)
        require(value is None,'GITHUB_BRANCH_ALREADY_EXISTS')

    def execute(self,*,check,cancel,begin_step):
        require(self.mode in ('OFFLINE_FIXTURE','LIVE'),'GITHUB_READBACK_ONLY')
        require(callable(begin_step),'GITHUB_DURABLE_STEP_MARKER_REQUIRED')
        deadline=time.monotonic()+120
        args={'check':check,'cancel':cancel,'deadline':deadline}
        self.preflight(**args)
        def post(step,path,payload):
            check();cancel.check(deadline)
            require(step not in self._attempted,'GITHUB_STEP_ALREADY_ATTEMPTED')
            self._attempted.add(step)
            require(begin_step(step,sha256(canonical({'method':'POST','path':path,'payload':payload}))) is True,
                    'GITHUB_STEP_ALREADY_ATTEMPTED')
            return self._call('POST',path,payload,**args)
        tree=post('tree',PREFIX+'/git/trees',{'base_tree':self.base.sha,'tree':[
            {'path':p,'mode':'100644','type':'blob','content':d.decode()} for p,d in self.plan.files.items()]})
        require(tree.get('sha')==self.tree.sha,'GITHUB_TREE_ACK_MISMATCH')
        commit=post('commit',PREFIX+'/git/commits',self.plan.commit_payload(self.tree.sha))
        require(commit.get('sha')==self.commit_sha,'GITHUB_COMMIT_ACK_MISMATCH')
        self._main(**args)
        ref=post('branch',PREFIX+'/git/refs',{'ref':'refs/heads/'+self.plan.branch,'sha':self.commit_sha})
        require(ref.get('ref')=='refs/heads/'+self.plan.branch and ref.get('object',{}).get('sha')==self.commit_sha
            and ref['object'].get('type')=='commit','GITHUB_REF_ACK_MISMATCH')
        # Creating a PR is a separately declared step, only after commit GETs.
        observed=self.readback(**args)
        require(observed['state']=='COMMIT_VERIFIED_PR_MISSING','GITHUB_PR_PRECONDITION_DENIED')
        self._main(**args)
        post('draft_pr',PREFIX+'/pulls',{'title':self.plan.title,'body':self.plan.body,
            'head':self.plan.branch,'base':'main','draft':True,'maintainer_can_modify':False})
        return self.readback(**args)

    def _commit(self,value):
        require(type(value) is dict and value.get('sha')==self.commit_sha
            and value.get('tree',{}).get('sha')==self.tree.sha and value.get('message')==self.plan.message
            and type(value.get('parents')) is list and [p.get('sha') for p in value['parents']]==[self.plan.base_sha],
            'GITHUB_COMMIT_READBACK_MISMATCH')
        expected=self.plan.commit_payload(self.tree.sha)
        for name in ('author','committer'):
            actual=value.get(name)
            require(type(actual) is dict and all(actual.get(k)==v for k,v in expected[name].items()),
                'GITHUB_COMMIT_READBACK_MISMATCH')

    def readback(self,*,check,cancel,deadline=None):
        args={'check':check,'cancel':cancel,'deadline':deadline or time.monotonic()+90}
        self._repo(**args)
        result={'schema':'aioa.github-write-readback.v1','mode':self.mode,'live_verified':False,
            'state':'UNRESOLVED','remote_effect_verified':False,'automatic_retry':False,
            'api_request_limit':self.plan.payload()['api_request_limit'],'write_retry_limit':0,
            'repository':DEMO_REPOSITORY,'repository_id':DEMO_REPOSITORY_ID,'plan_digest':self.plan.digest,
            'branch':self.plan.branch,'expected_commit_sha':self.commit_sha,'commit_sha':None,'pr_url':None}
        ref=self._call('GET',PREFIX+'/git/ref/heads/'+self.plan.branch,None,absent=True,**args)
        commit=self._call('GET',PREFIX+'/git/commits/'+self.commit_sha,None,absent=True,**args)
        if commit is not None:self._commit(commit)
        if ref is None:
            if commit is not None:result.update(state='COMMIT_OBJECT_ONLY',commit_sha=self.commit_sha)
            return result
        require(ref.get('ref')=='refs/heads/'+self.plan.branch and ref.get('object',{}).get('type')=='commit'
            and ref['object'].get('sha')==self.commit_sha,'GITHUB_REF_READBACK_MISMATCH')
        self._commit(commit)
        tree=self._call('GET',PREFIX+'/git/trees/'+self.tree.sha+'?recursive=1',None,**args)
        require(GitTreeSnapshot.from_github(tree,expected_sha=self.tree.sha)==self.tree,'GITHUB_TREE_READBACK_MISMATCH')
        blobs={}
        for path,metadata in self.plan.manifest().items():
            blob=self._call('GET',PREFIX+'/git/blobs/'+metadata['git_blob_sha'],None,**args)
            try:
                require(blob.get('encoding')=='base64' and type(blob.get('content')) is str,'GITHUB_BLOB_READBACK_MISMATCH')
                raw=base64.b64decode(blob['content'].replace('\n',''),validate=True)
                require(blob.get('sha')==metadata['git_blob_sha'] and blob.get('size')==metadata['bytes']
                    and sha256(raw)==metadata['sha256'] and git_object('blob',raw)==metadata['git_blob_sha'],
                    'GITHUB_BLOB_READBACK_MISMATCH')
            except (ValueError,TypeError):raise ValueError('GITHUB_BLOB_READBACK_MISMATCH') from None
            blobs[path]=sha256(raw)
        result.update(state='COMMIT_VERIFIED_PR_MISSING',commit_sha=self.commit_sha,
            commit_url='https://github.com/'+DEMO_REPOSITORY+'/commit/'+self.commit_sha,
            manifest_sha256=sha256(canonical(self.plan.manifest())),
            commit_get_sha256=sha256(canonical(commit)),tree_get_sha256=sha256(canonical(tree)),blobs=blobs)
        pulls=self._call('GET',self.pull_query,None,**args)
        require(type(pulls) is list and len(pulls)<=1,'GITHUB_PR_READBACK_AMBIGUOUS')
        if not pulls:return result
        require(type(pulls[0]) is dict and type(pulls[0].get('number')) is int and 0<pulls[0]['number']<10**9,
                'GITHUB_PR_READBACK_MISMATCH')
        number=pulls[0]['number'];pull=self._call('GET',PREFIX+'/pulls/'+str(number),None,**args)
        url='https://github.com/'+DEMO_REPOSITORY+'/pull/'+str(number)
        require(pull.get('number')==number and pull.get('html_url')==url and pull.get('draft') is True
            and pull.get('state')=='open' and pull.get('merged') is False and pull.get('title')==self.plan.title
            and pull.get('body')==self.plan.body,'GITHUB_PR_READBACK_MISMATCH')
        for name,branch,sha in (('head',self.plan.branch,self.commit_sha),('base','main',self.plan.base_sha)):
            value=pull.get(name,{})
            require(value.get('ref')==branch and value.get('sha')==sha
                and value.get('repo',{}).get('id')==DEMO_REPOSITORY_ID
                and value['repo'].get('full_name')==DEMO_REPOSITORY,'GITHUB_PR_READBACK_MISMATCH')
        # Recheck the ref after the PR GET to detect a concurrent branch change.
        final=self._call('GET',PREFIX+'/git/ref/heads/'+self.plan.branch,None,**args)
        require(final==ref,'GITHUB_REF_CHANGED_DURING_READBACK')
        result.update(state='COMMIT_AND_DRAFT_PR_VERIFIED',remote_effect_verified=True,
            live_verified=self.mode in ('LIVE','PUBLIC_READ_ONLY'),pr_url=url,pr_number=number,
            pr_get_sha256=sha256(canonical(pull)))
        return result


def read_demo_base(*,check,cancel,mode='LIVE',transport=None):
    """Fixed public GETs for a proposal; no credential is minted or loaded."""
    require(mode in ('LIVE','OFFLINE_FIXTURE') and callable(check)
        and (transport is None if mode=='LIVE' else callable(transport)),'GITHUB_READ_CONFIGURATION_DENIED')
    deadline=time.monotonic()+40
    port=_https_once if mode=='LIVE' else transport
    def get(path):
        check();cancel.check(deadline)
        try:
            status,raw=port('GET',path,None,None,cancel,min(10,deadline-time.monotonic()))
            require(status==200,'GITHUB_BASE_READ_UNVERIFIED')
            value=strict_json(raw,limit=RESPONSE_LIMIT);cancel.check(deadline)
            return value
        except Exception:raise ValueError('GITHUB_BASE_READ_UNVERIFIED') from None
    repo=get(PREFIX)
    require(repo.get('id')==DEMO_REPOSITORY_ID and repo.get('full_name')==DEMO_REPOSITORY
        and repo.get('default_branch')=='main' and repo.get('private') is False
        and repo.get('archived') is False and repo.get('disabled') is False,'GITHUB_REPOSITORY_READBACK_MISMATCH')
    ref=get(PREFIX+'/git/ref/heads/main');obj=ref.get('object')
    require(ref.get('ref')=='refs/heads/main' and type(obj) is dict and obj.get('type')=='commit'
        and type(obj.get('sha')) is str and re.fullmatch('[a-f0-9]{40}',obj['sha']),'GITHUB_BASE_READ_UNVERIFIED')
    commit=get(PREFIX+'/git/commits/'+obj['sha']);tree=commit.get('tree')
    require(commit.get('sha')==obj['sha'] and type(tree) is dict and type(tree.get('sha')) is str
        and re.fullmatch('[a-f0-9]{40}',tree['sha']),'GITHUB_BASE_READ_UNVERIFIED')
    snapshot=GitTreeSnapshot.from_github(get(PREFIX+'/git/trees/'+tree['sha']+'?recursive=1'),expected_sha=tree['sha'])
    require(not any(p.startswith('.github/workflows/') for p in snapshot.entries),
        'GITHUB_EXISTING_WORKFLOWS_REVIEW_REQUIRED')
    check()
    return obj['sha'],snapshot
