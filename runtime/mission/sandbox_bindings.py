"""Inert, scoped sandbox configuration evidence in the existing Core store.

Filesystem capture belongs to the broker, outside retryable transactions. These
readers only validate canonical data and the existing audit/outbox history.
A binding digest never grants a session, claim, warrant or release ACK.
"""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from runtime.memory_patch.audit import require_record_audit
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.idempotency import OperationBinding
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.contracts import logical_id
from runtime.mission.warrant import require

BINDING_SCHEMA = 'aioa.sandbox-job-config-binding.v1'
BOUND_CONTEXT = 'aioa.sandbox-bound-effect-context.v1'
CONFIG_DOMAIN = 'aioa.sandbox-config-identity.v1'
BINDING_KIND = 'SANDBOX_JOB_CONFIG_BINDING'
BINDING_FIELDS = frozenset(('schema','scope','deployment_id','workspace','task_id',
    'job_envelope_digest','completion_digest','allowed_operations','config_digest',
    'sandbox_profile_digest','root_ref','host_config_sha256','root_identity','provenance'))
PROVENANCE_FIELDS = frozenset(('kind','repository_recipe_digest','source_snapshot_digest',
    'source_identity','coding_task_id','coding_run_id','coding_task_digest','worker_session_id',
    'patchset_sha256','final_tree_sha256','recipe_stages'))


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None,
            'SANDBOX_BINDING_INTEGRITY')
    return value


def root_member(value):
    require(type(value) is str and value not in ('.','..')
            and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value) is not None,
            'SANDBOX_BINDING_ROOT_DENIED')
    return value


@dataclass(frozen=True, slots=True)
class TrustedSandboxBindingPolicy:
    trusted_root: Path
    workspace: str
    profile_digest: str
    recipe: object
    source_snapshot: object
    source_repository: Path
    base_root: Path
    max_configs: int = 32
    max_jobs: int = 64

    def __post_init__(self):
        from runtime.mission.git_publish import GitSourceSnapshot
        from runtime.mission.project_recipe import PythonRepositoryRecipe
        require(type(self.recipe) is PythonRepositoryRecipe
                and type(self.source_snapshot) is GitSourceSnapshot,
                'SANDBOX_BINDING_POLICY_REQUIRED')
        logical_id(self.workspace); digest(self.profile_digest)
        require(all(isinstance(p,Path) and p.is_absolute() and '..' not in p.parts
                    for p in (self.trusted_root,self.source_repository,self.base_root))
                and type(self.max_configs) is int and 1<=self.max_configs<=32
                and type(self.max_jobs) is int and 1<=self.max_jobs<=64,
                'SANDBOX_BINDING_POLICY_REQUIRED')
        require(self.workspace==self.source_snapshot.workspace_id
                and self.recipe.repository_id==self.source_snapshot.repository_id
                and self.recipe.source_base_sha==self.source_snapshot.source_base_sha,
                'SANDBOX_BINDING_SOURCE')
        self.recipe.__post_init__()


@dataclass(frozen=True, slots=True)
class MaterializationBindingInput:
    task: object
    session: object
    candidate: object

    def __post_init__(self):
        from runtime.mission.worker import CandidatePatch, Task, WorkerSession
        require(type(self.task) is Task and type(self.session) is WorkerSession
                and type(self.candidate) is CandidatePatch, 'SANDBOX_BINDING_INPUT')
        require(self.session.task_id==self.task.task_id
                and self.session.run_id==self.task.run_id
                and self.session.task_digest==self.task.digest,'SANDBOX_BINDING_TASK')


@dataclass(frozen=True, slots=True)
class ObservationBindingInput:
    patchset: object
    archive: bytes

    def __post_init__(self):
        from runtime.mission.patchset import PatchSet
        require(type(self.patchset) is PatchSet and type(self.archive) is bytes,
                'SANDBOX_BINDING_INPUT')
        self.patchset.verify_digest()


@dataclass(frozen=True, slots=True)
class CapturedSandboxConfig:
    config: object
    identity_bytes: bytes
    config_digest: str
    host_config_sha256: str
    root_identity_bytes: bytes
    provenance_bytes: bytes
    binding_input: object


@dataclass(frozen=True, slots=True)
class SandboxJobBinding:
    record_bytes: bytes
    mode: str
    operation_bytes: tuple[bytes, ...] = ()

    @property
    def digest(self):
        return canonical_sha256(json.loads(self.record_bytes))

    @property
    def task_id(self):
        return json.loads(self.record_bytes)['task_id']


def binding_key(scope,deployment,workspace,task):
    return canonical_sha256((BINDING_SCHEMA,scope.binding(),deployment,workspace,task))


def audit_descriptor(key,row):
    return OperationBinding.bind('sandbox-binding-'+key,BINDING_KIND,
                                 {'record_digest':row.payload_digest})


def validate_payload(value,scope,deployment,workspace,task):
    require(type(value) is dict and set(value)==BINDING_FIELDS
            and value['schema']==BINDING_SCHEMA and value['scope']==list(scope.binding())
            and value['deployment_id']==deployment and value['workspace']==workspace
            and value['task_id']==task and len(canonical_json_bytes(value))<=16384,
            'SANDBOX_BINDING_INTEGRITY')
    logical_id(workspace); logical_id(task); root_member(value['root_ref'])
    for name in ('job_envelope_digest','completion_digest','config_digest',
                 'sandbox_profile_digest','host_config_sha256'):
        digest(value[name])
    identity=value['root_identity']
    require(type(identity) is dict and set(identity)=={'device','inode','uid','mode'}
            and all(type(v) is int and v>=0 for v in identity.values()),
            'SANDBOX_BINDING_INTEGRITY')
    provenance=value['provenance']
    require(type(provenance) is dict and set(provenance)==PROVENANCE_FIELDS
            and provenance['kind'] in ('MATERIALIZE','OBSERVE'), 'SANDBOX_BINDING_INTEGRITY')
    for name in ('repository_recipe_digest','source_snapshot_digest','coding_task_digest',
                 'patchset_sha256','final_tree_sha256'):
        digest(provenance[name])
    from runtime.mission.patchset import SourceIdentity
    require(type(provenance['source_identity']) is dict, 'SANDBOX_BINDING_INTEGRITY')
    source=SourceIdentity(**provenance['source_identity'])
    require(source.workspace_id==workspace,'SANDBOX_BINDING_SOURCE')
    for name in ('coding_task_id','coding_run_id','worker_session_id'):
        logical_id(provenance[name])
    stages=provenance['recipe_stages']
    from runtime.mission.repair import TEST_STAGES
    require(type(stages) is list and 1<=len(stages)<=3
            and all(type(p) is list and len(p)==2 and all(type(v) is str for v in p)
                    for p in stages), 'SANDBOX_BINDING_INTEGRITY')
    require(len({p[0] for p in stages})==len(stages)
            and len({p[1] for p in stages})==len(stages)
            and (tuple(p[1] for p in stages)==('MATERIALIZE',)
                 if provenance['kind']=='MATERIALIZE'
                 else all(p[1] in TEST_STAGES for p in stages)), 'SANDBOX_BINDING_INTEGRITY')
    operations=value['allowed_operations']
    require(type(operations) is list and 1<=len(operations)<=32
            and all(type(p) is dict and set(p)=={'step_id','operation_digest'} for p in operations),
            'SANDBOX_BINDING_INTEGRITY')
    for operation in operations:
        logical_id(operation['step_id'])
        require(type(operation['operation_digest']) is str
                and operation['operation_digest'].startswith('sha256:'), 'SANDBOX_BINDING_INTEGRITY')
        digest(operation['operation_digest'][7:])
    require(operations==sorted(operations,key=lambda p:p['step_id'])
            and len({p['step_id'] for p in operations})==len(operations),'SANDBOX_BINDING_INTEGRITY')
    return value


def read_binding(tx,scope,deployment,workspace,task,*,expected_digest=None):
    key=binding_key(scope,deployment,workspace,task)
    row=tx.get(RecordKind.OPERATION,key)
    require(row is not None and row.kind is RecordKind.OPERATION and row.record_id==key
            and row.scope==scope and row.revision==1,'SANDBOX_JOB_BINDING_REQUIRED')
    value=validate_payload(json.loads(canonical_json_bytes(row.payload)),scope,deployment,workspace,task)
    if expected_digest is not None:
        require(digest(expected_digest)==canonical_sha256(value),'SANDBOX_BINDING_INTEGRITY')
    event=require_record_audit(tx,row)
    event_row=tx.get(RecordKind.AUDIT,'sandbox-binding-audit-'+key)
    require(event_row is not None and event_row.scope==scope and event_row.revision==1,
            'SANDBOX_BINDING_AUDIT')
    descriptor=audit_descriptor(key,row)
    require(event.audit_event_id=='sandbox-binding-audit-'+key
            and event.event_type==BINDING_KIND and event.resource_id==key
            and event.state_before is None and event.state_after=='BOUND'
            and event.content_hashes.get('content')==row.payload_digest
            and event.content_hashes.get('operation')==descriptor.payload_digest,
            'SANDBOX_BINDING_AUDIT')
    proof='sandbox-binding-proof-'+key
    outbox=tx.get(RecordKind.OUTBOX,proof)
    require(outbox is not None and outbox.scope==scope
            and set(outbox.payload)=={'state','event_id','event_digest','operation_digest','proof_id','core_entry_hash'}
            and outbox.payload['state'] in ('PENDING','PUBLISHED')
            and outbox.payload['event_id']==event.audit_event_id and outbox.payload['proof_id']==proof
            and outbox.payload['event_digest']==event.event_hash
            and outbox.payload['operation_digest']==canonical_sha256({'scope':scope.binding(),'operation':descriptor}),
            'SANDBOX_BINDING_OUTBOX')
    pending=outbox.payload['state']=='PENDING'
    require(outbox.revision==(1 if pending else 2)
            and (outbox.payload['core_entry_hash'] is None if pending else
                 type(outbox.payload['core_entry_hash']) is str
                 and re.fullmatch('[0-9a-f]{64}',outbox.payload['core_entry_hash']) is not None),
            'SANDBOX_BINDING_OUTBOX')
    return value


def binding_for_job(gov,tx,envelope,completion,binding_digest):
    rows=tx.scan(RecordKind.OPERATION,limit=1024)
    require(len(rows)<1024,'HISTORY_QUOTA')
    matches=[row for row in rows if row.payload.get('schema')==BINDING_SCHEMA
             and row.payload.get('task_id')==envelope.task_id]
    if binding_digest is None:
        require(not matches,'SANDBOX_JOB_BINDING_REQUIRED')
        return None
    require(len(matches)==1 and completion is not None,'SANDBOX_JOB_BINDING_REQUIRED')
    value=read_binding(tx,gov.policy.scope,gov.policy.deployment_id,matches[0].payload['workspace'],
                       envelope.task_id,expected_digest=binding_digest)
    require(value['job_envelope_digest']==envelope.envelope_digest
            and value['completion_digest']==completion.digest,'SANDBOX_BINDING_JOB')
    return value
