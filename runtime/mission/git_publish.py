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

REPOSITORY='luciferprosun/AIOA-spArkHAT'
BRANCH_PREFIX='codex/aioa-sensorbridge-'
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
