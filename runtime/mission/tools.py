"""Capability composition on the existing native Core ports.

Legacy synthetic callbacks and the registered sandbox retain their profiles.
Explicit Portable policy4 joins one managed target and existing executor to
the same Core. No credentials, signer, automatic principal or network is
introduced. Calls are synchronous and cannot outlive their guard. Database
commit is not an external effect transaction; ACK loss never grants replay.
"""
import json
import time
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.contracts import digest_id, identifier
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultTrace, classify_fault, opaque_id
from lab.archaioa.taint import DependencyGraph, NodeKind
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy

from runtime.core_admission import Capability, OwnerScope
from runtime.failure_boundary import RepairBoundaryError, failure_boundary
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.mission.intent import INTENT_KINDS, CoreIntentJournal
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.mission.sandbox_contracts import (
    PORTABLE,
    PORTABLE_REARM,
    SANDBOX,
    SYNTHETIC,
    TOOL_POLICY_VERSIONS,
    SandboxDispatchRequest,
    SandboxOperation,
    SandboxRegistry,
    tool_variant,
)
from runtime.mission.target_settlement import (
    TARGET_BINDING_KIND,
    TARGET_SETTLEMENT_PROFILE,
    TargetBinding,
    TargetSettlementPort,
    VerifiedNoReleaseSettlement,
    VerifiedRearmTargetSettlement,
    VerifiedTargetSettlement,
)
from runtime.mission.warrant import approval_digest, require

SESSION = 'aioa-local-synthetic-session-v1'
LOCAL_SESSION = 'aioa-local-zero-session-v2'
CONTEXT = 'aioa-local-synthetic-effect-context-v1'
EXACT_CONTEXT = 'aioa-local-exact-mock-effect-context-v1'
EXACT_SESSION = 'aioa-local-exact-mock-session-v1'
PORTABLE_SESSION = 'aioa-local-portable-session-v1'
PORTABLE_CONTEXT = 'aioa-local-portable-effect-context-v1'
REARM_SESSION = 'aioa-local-portable-rearm-session-v1'
REARM_CONTEXT = 'aioa-local-portable-rearm-effect-context-v1'


class ToolCapability(str, Enum):
    READ_PROJECT = 'READ_PROJECT'
    PROJECT_WRITE = 'PROJECT_WRITE'
    SANDBOX_EXEC = 'SANDBOX_EXEC'
    DEPENDENCY_INSTALL = 'DEPENDENCY_INSTALL'
    GITHUB_REMOTE_WRITE = 'GITHUB_REMOTE_WRITE'
    BROWSER_EXTERNAL_EFFECT = 'BROWSER_EXTERNAL_EFFECT'
    SYSTEM_INSTALL = 'SYSTEM_INSTALL'
    PORTABLE_RELEASE_ELASTIC_IP = 'PORTABLE_RELEASE_ELASTIC_IP'
    PORTABLE_REARM_DEMO_V1 = 'PORTABLE_REARM_DEMO_V1'


# Trusted immutable policy, never tool annotations or model confirmation flags.
TOOL_CAPABILITIES = MappingProxyType({
    'read_file': ToolCapability.READ_PROJECT, 'search_in_project': ToolCapability.READ_PROJECT,
    'write_file': ToolCapability.PROJECT_WRITE, 'append_file': ToolCapability.PROJECT_WRITE,
    'create_file': ToolCapability.PROJECT_WRITE, 'create_folder': ToolCapability.PROJECT_WRITE,
    'move_file': ToolCapability.PROJECT_WRITE, 'delete_file': ToolCapability.PROJECT_WRITE,
    'scan_project': ToolCapability.PROJECT_WRITE, 'change_directory': ToolCapability.PROJECT_WRITE,
    'shell_execute': ToolCapability.SANDBOX_EXEC, 'run_recipe': ToolCapability.SANDBOX_EXEC,
    'dependency_install': ToolCapability.DEPENDENCY_INSTALL,
    'git_push': ToolCapability.GITHUB_REMOTE_WRITE, 'system_install': ToolCapability.SYSTEM_INSTALL,
    'release_elastic_ip': ToolCapability.PORTABLE_RELEASE_ELASTIC_IP,
    'rearm_demo': ToolCapability.PORTABLE_REARM_DEMO_V1,
})


def tool_capability(name):
    require(type(name) is str, 'UNSUPPORTED_TOOL')
    if name.startswith('browser_'):
        return ToolCapability.BROWSER_EXTERNAL_EFFECT
    require(name in TOOL_CAPABILITIES, 'UNSUPPORTED_TOOL')
    return TOOL_CAPABILITIES[name]


def application_path(value):
    require(type(value) is str and 0 < len(value) <= 256 and '\\' not in value
            and '\x00' not in value and not any(ord(c) < 32 for c in value), 'UNSAFE_TOOL_PATH')
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts
            and len(path.parts) >= 2 and path.parts[0] == 'src'
            and all(not part.startswith('.') for part in path.parts)
            and path.suffix in ('.py', '.txt', '.md', '.json')
            and not any(part.lower() in {'policy','policies','hooks','tests','secrets','credentials',
                'node_modules','vendor','__pycache__'} for part in path.parts)
            and path.name.lower() not in {'package.json','package-lock.json','pyproject.toml',
                'requirements.txt','setup.py','setup.cfg','pipfile','pipfile.lock'}, 'UNSAFE_TOOL_PATH')
    require(str(path) == value, 'UNSAFE_TOOL_PATH')
    return value


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    fingerprint: str
    revision: str
    ddr: DecisionDependencyRoot

    def __post_init__(self):
        digest_id(self.fingerprint, 'fingerprint'); identifier(self.revision, 'revision')
        require(type(self.ddr) is DecisionDependencyRoot, 'INVALID_TARGET_SNAPSHOT')


@dataclass(frozen=True, slots=True)
class ToolDispatchLimits:
    """Trusted synthetic contract; physical worker enforcement is a U06 gate.

    A callable is not a resource sandbox. No real tool adapter is enabled by
    this type; the fixed synthetic target receives immutable human limits.
    """
    deadline_seconds: int
    output_bytes: int
    egress: str = 'OFF'

    def __post_init__(self):
        require(type(self.deadline_seconds) is int and 0 < self.deadline_seconds <= 20
                and type(self.output_bytes) is int and 0 < self.output_bytes <= 16384
                and self.egress == 'OFF', 'INVALID_TOOL_LIMITS')


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    scope: OwnerScope
    workspace: str
    policy_revision: int
    capabilities: tuple[str, ...]
    completion_digest: str
    issued_at: int
    expires_at: int
    epoch: int
    money_nano: int
    risk_units: int
    deadline_seconds: int
    output_bytes: int
    egress: str = 'OFF'

    def __post_init__(self):
        opaque_id(self.session_id,'session_id'); opaque_id(self.workspace,'workspace')
        require(type(self.scope) is OwnerScope, 'INVALID_SESSION')
        allowed={t.value for t in ToolCapability}
        if type(self) is LocalSessionGrant:allowed|={'GIT_COMMIT','GIT_PUSH','GITHUB_DRAFT_PR'}
        require(type(self.capabilities) is tuple and self.capabilities
                and len(set(self.capabilities)) == len(self.capabilities)
                and all(type(c) is str and c in allowed for c in self.capabilities),
                'INVALID_SESSION')
        require(type(self.completion_digest) is str and len(self.completion_digest)==64
                and all(c in '0123456789abcdef' for c in self.completion_digest), 'INVALID_SESSION')
        require(all(type(getattr(self,f)) is int and getattr(self,f)>0 for f in (
            'policy_revision','issued_at','expires_at','epoch','risk_units','deadline_seconds','output_bytes'))
            and type(self.money_nano) is int
            and (self.money_nano == 0 if type(self) is LocalSessionGrant else self.money_nano > 0)
            and 0 < self.expires_at-self.issued_at <= 300 and self.deadline_seconds<=20
            and self.output_bytes<=16384 and self.egress=='OFF', 'INVALID_SESSION')

    def to_dict(self):
        result=asdict(self);result['scope']=list(self.scope.binding());result['capabilities']=list(self.capabilities)
        return result

    @classmethod
    def parse(cls,value):
        require(type(value) is dict and set(value)==set(cls.__dataclass_fields__), 'SESSION_INTEGRITY')
        value=dict(value)
        require(type(value['scope']) is list and len(value['scope'])==4
                and type(value['capabilities']) is list, 'SESSION_INTEGRITY')
        value['scope']=OwnerScope(*value['scope']);value['capabilities']=tuple(value['capabilities'])
        return cls(**value)

    @property
    def digest(self):
        return canonical_sha256(self.to_dict())


@dataclass(frozen=True, slots=True)
class LocalSessionGrant(SessionGrant):
    """USD0 version; a distinct schema, never a v1 positive-money grant."""


class CoreToolRoute:
    """Common Core adapter with explicit trusted variants; no default backend."""
    def __init__(self,journal,liability,*,workspace,policy_revision,probe,executor,target_guard=None,verifier=None,clock=None,
                 variant='synthetic',sandbox_registry=None,target_settlement=None):
        require(type(journal) is CoreIntentJournal and type(liability) is CoreLiabilityLedger
                and journal.ledger.core is liability.core and journal.ledger.runner is liability.runner
                and journal.ledger.scope==liability.scope and callable(probe) and callable(executor)
                and callable(target_guard) and (verifier is None or callable(verifier)), 'INVALID_TOOL_ROUTE')
        opaque_id(workspace,'workspace')
        require(type(policy_revision) is int and policy_revision in TOOL_POLICY_VERSIONS
                and type(variant) is str and variant in ('synthetic','sandbox','portable'), 'INVALID_TOOL_ROUTE')
        self.bound_variant=tool_variant(policy_revision,
            'SANDBOX_EXEC' if variant=='sandbox' else ('PORTABLE_REARM_DEMO_V1' if policy_revision == 5
                else 'PORTABLE_RELEASE_ELASTIC_IP') if variant=='portable' else 'PROJECT_WRITE')
        require((variant in ('synthetic','portable') and sandbox_registry is None)
                or (variant=='sandbox' and type(sandbox_registry) is SandboxRegistry
                    and sandbox_registry.workspace==workspace), 'INVALID_TOOL_ROUTE')
        self.sandbox_registry=sandbox_registry
        self.journal,self.liability=journal,liability
        self.core,self.runner,self.scope=liability.core,liability.runner,liability.scope
        self.workspace,self.policy_revision=workspace,policy_revision
        self.probe,self.executor,self.verifier=probe,executor,verifier
        self.target_guard=target_guard
        self.clock=clock or (lambda:int(time.time()))
        self.target_settlement = target_settlement
        self._target_port_binding = target_settlement
        self._target_descriptor = getattr(target_settlement, 'binding', None)
        self._require_target_binding()

    def _require_target_binding(self):
        port = self.target_settlement
        require(port is self._target_port_binding, 'TARGET_PORT_BINDING_CHANGED')
        if port is None:
            require(self.bound_variant not in (PORTABLE, PORTABLE_REARM), 'TARGET_PORT_BINDING_REQUIRED')
            return
        require(isinstance(port, TargetSettlementPort)
                and port.profile == TARGET_SETTLEMENT_PROFILE
                and self.bound_variant in (SYNTHETIC, PORTABLE, PORTABLE_REARM)
                and port.core is self.core is self.journal.ledger.core is self.liability.core
                and port.runner is self.runner is self.journal.ledger.runner is self.liability.runner
                and port.scope == self.scope == self.journal.ledger.scope == self.liability.scope
                and port.workspace == self.workspace
                and type(port.binding) is TargetBinding and port.binding == self._target_descriptor
                and port.binding.scope == self.scope and port.binding.workspace == self.workspace,
                'TARGET_PORT_BINDING_REQUIRED')
        if self.bound_variant in (PORTABLE, PORTABLE_REARM):
            from runtime.mission.portable_target import CorePortableTarget
            from runtime.mission.target_projection import CoreTargetProjection
            require(type(port) is CoreTargetProjection and type(self.executor) is CorePortableTarget
                    and self.executor.projection is port, 'PORTABLE_CORE_ADAPTER_REQUIRED')
            self.executor.require_route_binding(self)

    def _target_snapshot(self, snapshot, *, insert=False):
        require(type(snapshot) is TargetSnapshot, 'INVALID_TARGET_SNAPSHOT')
        refs = [ref for ref in snapshot.ddr.evidence_refs if ref.kind == TARGET_BINDING_KIND]
        if self.target_settlement is None:
            require(not refs, 'TARGET_PORT_REQUIRED_FOR_DURABLE_CONTEXT')
            return snapshot
        expected = self._target_descriptor.evidence()
        if insert and not refs:
            return replace(snapshot, ddr=DecisionDependencyRoot(snapshot.ddr.evidence_refs + (expected,)))
        require(refs == [expected], 'TARGET_PORT_DURABLE_BINDING_MISMATCH')
        return snapshot

    def _context_target_snapshot(self,warrant,context):
        # Accounting may validate mixed legacy/bound context facts without a
        # target adapter. Every outcome/recovery/authority path requires this
        # durable participation check separately; no context is rewritten.
        snapshot=TargetSnapshot(warrant.target_fingerprint,warrant.expected_target_revision,
                                DecisionDependencyRoot.from_dict(context['target_ddr']))
        return self._target_snapshot(snapshot)

    def _probe_target(self):
        self._require_target_binding()
        return self._target_snapshot(self.probe(), insert=True)

    def _run(self,principal,purpose,callback):
        self.core.require(principal,purpose,scope=self.scope)
        self._require_target_binding()
        def checked(tx):
            self._require_target_binding()
            return callback(tx)
        return self.runner.run(TransactionContext(principal,purpose),checked)

    def session_key(self,session_id):
        opaque_id(session_id,'session_id')
        return canonical_sha256((SESSION,self.scope,session_id))

    def _session(self,tx,session_id,*,active=True):
        row=tx.get(RecordKind.OPERATION,self.session_key(session_id))
        require(row is not None,'SESSION_REQUIRED')
        state=json.loads(canonical_json_bytes(row.payload))
        fields = {'schema', 'grant', 'revoked', 'assignment_revision'}
        exact = state.get('schema') in (EXACT_SESSION, PORTABLE_SESSION, REARM_SESSION)
        require(set(state) == (fields | {'owner_session_id'} if exact else fields)
                and state['schema'] in (SESSION, LOCAL_SESSION, EXACT_SESSION, PORTABLE_SESSION, REARM_SESSION)
                and type(state['revoked']) is bool and type(state['assignment_revision']) is int,
                'SESSION_INTEGRITY')
        if exact:
            owner_session = state['owner_session_id']
            require(type(owner_session) is str and len(owner_session) == 64
                    and all(c in '0123456789abcdef' for c in owner_session),
                    'SESSION_INTEGRITY')
        grant=(LocalSessionGrant if state['schema'] in (LOCAL_SESSION, PORTABLE_SESSION, REARM_SESSION) else SessionGrant).parse(state['grant'])
        require(grant.session_id==session_id and grant.scope==self.scope and grant.workspace==self.workspace
                and grant.policy_revision in TOOL_POLICY_VERSIONS
                and state['assignment_revision']>=1,'SESSION_BINDING')
        expected = {3: EXACT_SESSION, 4: PORTABLE_SESSION, 5: REARM_SESSION}.get(grant.policy_revision)
        require(state['schema'] == expected if expected is not None
                else state['schema'] in (SESSION, LOCAL_SESSION), 'SESSION_POLICY_DOWNGRADE')
        if active:
            if exact:
                require(state['owner_session_id'] == tx.context.principal.actor_session_id,
                        'OWNER_SESSION_CHANGED')
            require(not state['revoked'] and grant.issued_at<=self.clock()<grant.expires_at
                    and grant.policy_revision==self.policy_revision
                    and state['assignment_revision']==tx.context.principal.assignment_revision,'SESSION_INACTIVE')
            gov=self.journal.governor;before=gov._load(tx);gov._epoch(before,grant.epoch)
            require(not before['kill'],'KILL_SWITCH')
        return row,state,grant

    def create_session(self,principal,grant):
        require(type(grant) in (SessionGrant, LocalSessionGrant),'INVALID_SESSION')
        def change(tx):
            if grant.policy_revision == 3:
                require(type(grant) is SessionGrant, 'EXACT_MOCK_GRANT_REQUIRED')
            if grant.policy_revision in (4, 5):
                selected = PORTABLE_REARM if grant.policy_revision == 5 else PORTABLE
                require(type(grant) is LocalSessionGrant
                        and grant.capabilities == (selected.operation_class,), 'PORTABLE_LOCAL_GRANT_REQUIRED')
            require(grant.scope==self.scope and grant.workspace==self.workspace
                    and grant.policy_revision==self.policy_revision
                    and grant.issued_at<=self.clock()<grant.expires_at,'SESSION_BINDING')
            gov=self.journal.governor;before=gov._load(tx);gov._epoch(before,grant.epoch)
            require(not before['kill'],'KILL_SWITCH')
            key=self.session_key(grant.session_id)
            require(tx.get(RecordKind.OPERATION,key) is None,'SESSION_ALREADY_REGISTERED')
            state = {'schema': LOCAL_SESSION if type(grant) is LocalSessionGrant else SESSION,
                     'grant': grant.to_dict(), 'revoked': False,
                     'assignment_revision': principal.assignment_revision}
            if grant.policy_revision in (3, 4, 5):
                state.update(schema={3: EXACT_SESSION, 4: PORTABLE_SESSION, 5: REARM_SESSION}[grant.policy_revision],
                             owner_session_id=principal.actor_session_id)
            tx.insert(StoredRecord(RecordKind.OPERATION, key, self.scope, 1, state))
        return self._run(principal,Capability.OWNER_APPROVAL,change)

    def validate_registered_local(self, tx, warrant, operation, *, consumed=False):
        """Pure native checks for the additive local-zero tool profile."""
        require(type(operation) is dict and operation['payload']['schema'] == 'aioa.local-operation.v2',
                'LOCAL_OPERATION_REQUIRED')
        payload = operation['payload']
        _, _, grant = self._session(tx, payload['session_id'])
        require(type(grant) is LocalSessionGrant and grant.money_nano == 0
                and grant.digest == payload['session_grant_digest']
                and grant.completion_digest == payload['task_digest']
                and grant.epoch == warrant.lease_epoch
                and payload['workspace'] == self.workspace
                and operation['operation_class'] in grant.capabilities, 'LOCAL_SESSION_BINDING')
        state = self.journal.governor._load(tx)
        self.journal.governor._epoch(state, grant.epoch)
        require(not state['kill'], 'KILL_SWITCH')
        require(self.sandbox_registry is not None, 'LOCAL_REGISTRY_REQUIRED')
        inner = payload['sandbox_operation']
        self.sandbox_registry.validate(inner)
        require(inner['payload']['task_id'] == warrant.task_id
                and inner['target_fingerprint'] == operation['target_fingerprint']
                and inner['expected_target_revision'] == operation['expected_target_revision'], 'LOCAL_TARGET_BINDING')
        require(inner['payload']['timeout_ms'] <= grant.deadline_seconds*1000
                and inner['payload']['max_output_bytes'] <= grant.output_bytes
                and inner['payload']['network_profile'] == grant.egress == 'OFF','LOCAL_RESOURCE_GRANT_MISMATCH')
        self.journal.ledger.require_active_in_transaction(tx, warrant, consumed=consumed)
        return grant

    def dispatch_registered_local(self, principal, warrant, operation, reservation, *, check, cancel):
        from runtime.service_guard.service import CoreServiceGuard
        return CoreServiceGuard.dispatch_registered_local(self, principal, warrant, operation,
                                                         reservation, check=check, cancel=cancel)

    def revoke_session(self,principal,session_id):
        self.core.require(principal,Capability.MANAGE,scope=self.scope)
        with self.target_guard():
            return self._revoke_session(principal,session_id)

    def _revoke_session(self,principal,session_id):
        def change(tx):
            row,state,_=self._session(tx,session_id,active=False)
            if not state['revoked']:
                tx.replace(StoredRecord(row.kind,row.record_id,row.scope,row.revision+1,
                    {**state,'revoked':True}),expected_revision=row.revision)
        return self._run(principal,Capability.MANAGE,change)

    def operation(self,proposal,snapshot):
        if self.bound_variant in (PORTABLE, PORTABLE_REARM):
            from runtime.mission.portable_target import _portable_operation
            parsed = _portable_operation(proposal).to_dict()
            self._operation(parsed, snapshot)
            return parsed
        if self.bound_variant is SANDBOX:
            require(type(snapshot) is TargetSnapshot,'INVALID_TARGET_SNAPSHOT')
            result={'operation_class':'SANDBOX_EXEC','target_fingerprint':snapshot.fingerprint,
                    'expected_target_revision':snapshot.revision,
                    'payload':self.sandbox_registry.payload(proposal)}
            return self.sandbox_registry.validate(result).to_dict()
        return self._synthetic_operation(proposal,snapshot)

    def _synthetic_operation(self,proposal,snapshot):
        require(type(proposal) is dict and set(proposal)=={'action','path','content'}
                and proposal['action']=='write_file' and type(proposal['content']) is str
                and type(snapshot) is TargetSnapshot,'UNSUPPORTED_TOOL')
        application_path(proposal['path'])
        result={'operation_class':tool_capability(proposal['action']).value,
                'target_fingerprint':snapshot.fingerprint,'expected_target_revision':snapshot.revision,
                'payload':{'tool':proposal['action'],'workspace':self.workspace,
                           'path':proposal['path'],'content':proposal['content']}}
        require(len(canonical_json_bytes(result))<=4096,'TOOL_INPUT_LIMIT')
        return result

    def _operation(self,operation,snapshot,*,variant=None,historical=False):
        variant=variant or self.bound_variant
        require(type(operation) is dict and type(operation.get('payload')) is dict,'INVALID_TOOL_OPERATION')
        require(operation.get('operation_class')==variant.operation_class,'INVALID_TOOL_OPERATION')
        if variant in (PORTABLE, PORTABLE_REARM):
            from runtime.mission.portable_target import _portable_operation
            parsed = _portable_operation(operation).to_dict()
            require(type(snapshot) is TargetSnapshot and parsed['payload']['workspace'] == self.workspace
                    and parsed['target_fingerprint'] == snapshot.fingerprint
                    and parsed['expected_target_revision'] == snapshot.revision, 'STALE_TOOL_BINDING')
            if not historical:
                require(self.bound_variant is variant and self._target_descriptor is not None
                        and parsed['payload']['target_binding_digest'] == self._target_descriptor.digest(),
                        'PORTABLE_TARGET_BINDING')
            return
        if variant is SANDBOX:
            parsed=SandboxOperation.parse(operation)
            require(operation['payload']['workspace']==self.workspace
                    and operation['target_fingerprint']==snapshot.fingerprint
                    and operation['expected_target_revision']==snapshot.revision,'STALE_TOOL_BINDING')
            if not historical:self.sandbox_registry.validate(parsed.to_dict())
            return
        payload=operation['payload']
        require(set(payload)=={'tool','workspace','path','content'} and payload['workspace']==self.workspace,
                'INVALID_TOOL_OPERATION')
        require(operation==self._synthetic_operation({'action':payload['tool'],'path':payload['path'],
                'content':payload['content']},snapshot),'STALE_TOOL_BINDING')

    @staticmethod
    def _snapshot_operation(operation):
        # Caller-owned nested dictionaries must not cross trusted callback boundaries.
        require(type(operation) is dict and type(operation.get('payload')) is dict,'INVALID_TOOL_OPERATION')
        encoded=canonical_json_bytes(operation)
        maximum = 65536 if operation['payload'].get('schema') in (
            'aioa.portable-operation.v1', 'aioa.portable-rearm-operation.v1') else 4096
        require(len(encoded)<=maximum,'TOOL_INPUT_LIMIT')
        return json.loads(encoded)

    @staticmethod
    def _ddr(snapshot,completion,grant,reservation):
        # Goal graph includes operation liability; keep goal binding in DDR to avoid a hash cycle.
        return DecisionDependencyRoot(snapshot.ddr.evidence_refs+(EvidenceRef('required-completion',
            'required-task-binding','sha256:'+completion.digest,'v1'),
            EvidenceRef('session-grant','human-root-grant','sha256:'+grant.digest,'v1'),
            EvidenceRef('tool-reservation','exact-reservation','sha256:'+canonical_sha256(reservation),'v1')))

    def _context_key(self,warrant):
        return canonical_sha256((CONTEXT,self.scope,warrant.nonce))

    def _context(self,tx,warrant):
        row=tx.get(RecordKind.OPERATION,self._context_key(warrant))
        require(row is not None,'TOOL_AUTHORIZATION_REQUIRED')
        context=json.loads(canonical_json_bytes(row.payload))
        require(set(context)=={'schema','session_id','grant_digest','completion','graph','trace',
                              'warrant','reservation','target_ddr'} and context['schema'] in (CONTEXT, EXACT_CONTEXT, PORTABLE_CONTEXT, REARM_CONTEXT)
                and EffectWarrant.from_dict(context['warrant'])==warrant,'TOOL_CONTEXT_INTEGRITY')
        binding=TaskCompletionBinding.parse(context['completion'])
        graph=DependencyGraph.from_dict(context['graph']);trace=FaultTrace.from_dict(context['trace'])
        require(binding.scope==self.scope and graph.task_id==trace.task_id==binding.task_id==warrant.task_id
                and canonical_sha256(graph.to_dict())==binding.graph_digest
                and trace.operation_digest==warrant.operation_hash,'TOOL_CONTEXT_INTEGRITY')
        _, session_state, grant=self._session(tx,context['session_id'],active=False)
        require(context['schema'] == {3: EXACT_CONTEXT, 4: PORTABLE_CONTEXT, 5: REARM_CONTEXT}.get(grant.policy_revision, CONTEXT),
                'TOOL_CONTEXT_POLICY_DOWNGRADE')
        witness = tx.get(RecordKind.APPROVAL, self.journal.ledger._key(warrant))
        if grant.policy_revision in (3, 4, 5):
            # Historical structure only: fresh dispatch checks current
            # session/revocation/consumption below. Readback stays possible.
            require(witness is not None and set(witness.payload) == {
                'schema', 'warrant_digest', 'session_id',
                'assignment_revision', 'revoked'}
                and witness.payload['schema'] == 'aioa.warrant-owner-witness.v1'
                and witness.payload['warrant_digest'] == warrant.digest()
                and witness.payload['session_id'] == session_state['owner_session_id']
                and type(witness.payload['assignment_revision']) is int
                and witness.payload['assignment_revision'] == session_state['assignment_revision']
                and type(witness.payload['revoked']) is bool,
                'HUMAN_APPROVAL_REQUIRED')
        else:
            require(witness is None, 'TOOL_CONTEXT_POLICY_DOWNGRADE')
        variant=tool_variant(grant.policy_revision,warrant.operation_class)
        portable = variant in (PORTABLE, PORTABLE_REARM)
        request=ReservationRequest(**context['reservation'])
        snapshot=TargetSnapshot(warrant.target_fingerprint,warrant.expected_target_revision,
                                DecisionDependencyRoot.from_dict(context['target_ddr']))
        require(context['grant_digest']==grant.digest and grant.completion_digest==binding.digest
                and request.request_id==warrant.risk_reservation_id
                and warrant.money_reservation_id == ('NONE' if portable else request.request_id)
                and request.task_id==warrant.task_id and request.provider_id==variant.provider_id
                and request.request_digest==warrant.operation_hash.removeprefix('sha256:')
                and request.risk_units>=5 and (request.money_nano == 0 if portable else request.money_nano > 0)
                and self._ddr(snapshot,binding,grant,request)==warrant.decision_dependency_root,
                'TOOL_CONTEXT_INTEGRITY')
        if portable:
            require(type(grant) is LocalSessionGrant and grant.money_nano == 0
                    and warrant.authority_scope.monetary_ceiling.amount == 0
                    and warrant.authority_scope.monetary_ceiling.currency == 'USD', 'TOOL_CONTEXT_ZERO_USD')
        _,stored_graph=self.liability._load(tx,warrant.task_id)
        require(stored_graph['graph']==graph.to_dict(),'DEPENDENCY_GRAPH_CONFLICT')
        prior,intent=self.journal._load(tx,warrant)
        if prior is not None:
            self._operation(intent['operation'],snapshot,variant=variant,historical=True)
            if variant is SANDBOX:self._sandbox_scope(intent['operation'],binding,graph,trace,grant)
            if portable:self._portable_scope(intent['operation'], binding, grant, session_state, warrant=warrant)
            entry=stored_graph['entries'].get(classify_fault(trace).liability_id)
            require(entry is not None and intent['reservation']==canonical_sha256(request)
                    and intent['resolution']==entry['resolution'],'TOOL_RECONCILIATION_INTEGRITY')
        return context,binding,graph,trace

    def _mode(self,tx,warrant):
        context,_,_,_=self._context(tx,warrant)
        _,_,grant=self._session(tx,context['session_id'],active=False)
        return tool_variant(grant.policy_revision,warrant.operation_class).mode

    @staticmethod
    def _sandbox_scope(operation,completion,graph,trace,grant):
        payload=operation['payload']
        require(payload['task_id']==completion.task_id==graph.task_id==trace.task_id,
                'SANDBOX_TASK_BINDING')
        by_id={n.node_id:n for n in graph.nodes};seen=set();pending=[completion.candidate_id]
        while pending:
            node=pending.pop();require(node in by_id,'INVALID_TOOL_BINDING')
            if node not in seen:seen.add(node);pending.extend(by_id[node].required_dependencies)
        step=by_id.get(payload['step_id'])
        require(step is not None and step.node_id in seen and step.kind is NodeKind.OPERATION
                and classify_fault(trace).liability_id in step.liability_ids,'SANDBOX_STEP_BINDING')
        require(payload['timeout_ms']<=grant.deadline_seconds*1000
                and payload['max_output_bytes']<=grant.output_bytes,'SESSION_SCOPE_DENIED')

    @staticmethod
    def _portable_scope(operation, completion, grant, session_state, *, warrant=None):
        payload = operation['payload']
        require(type(grant) is LocalSessionGrant and grant.policy_revision in (4, 5)
                and tool_variant(grant.policy_revision, operation['operation_class']) in (PORTABLE, PORTABLE_REARM)
                and payload['task_id'] == completion.task_id
                and payload['workspace'] == grant.workspace
                and payload['session_id'] == grant.session_id
                and payload['policy_epoch'] == grant.epoch
                and payload['principal_session_id'] == session_state['owner_session_id'],
                'PORTABLE_SESSION_BINDING')
        if grant.policy_revision == 5:
            request = payload['request']
            require(request['actor_session_id'] == session_state['owner_session_id']
                    and request['assignment_revision'] == session_state['assignment_revision']
                    and payload['domain_input']['binding']['scope'] == asdict(grant.scope),
                    'PORTABLE_REARM_OWNER_BINDING')
            if warrant is not None:
                require(request['decision_nonce_hash'] == canonical_sha256(warrant.nonce)
                        and datetime.fromisoformat(request['requested_at']) <= warrant.issued_at
                        and warrant.expires_at <= datetime.fromisoformat(request['expires_at']),
                        'PORTABLE_REARM_WARRANT_REQUEST_BINDING')

    def _sandbox_request(self,tx,grant,context,warrant):
        # Only called by the current synchronous live-ACK branch, never by replay.
        _,intent=self.journal._load(tx,warrant)
        require(intent is not None and intent['resolution'] is None
                and intent['outcome']['contract_type']=='Unknown','SANDBOX_START_BINDING')
        operation=self.sandbox_registry.validate(intent['operation'])
        payload=operation.to_dict()['payload']
        return SandboxDispatchRequest(operation.operation_bytes,warrant.operation_hash,
            payload['task_id'],payload['step_id'],context['session_id'],grant.digest,grant.epoch,
            warrant.digest(),warrant.decision_dependency_root.root_digest,
            canonical_sha256(ReservationRequest(**context['reservation'])),
            TaskCompletionBinding.parse(context['completion']).digest,warrant.nonce)

    def _native_job(self,tx,completion,*,dispatch=False):
        from runtime.mission.jobs import load_job
        job=load_job(self.journal.governor,tx,completion.task_id)
        require(job is not None and 'completion_binding' in job
                and TaskCompletionBinding.parse(job['completion_binding'])==completion,
                'REQUIRED_TASK_BINDING_REQUIRED')
        from runtime.mission.job_contracts import JobClaim, JobEnvelope
        gov=self.journal.governor;state=gov._load(tx);now=gov._now()
        gov._clock(state,now)
        require(job['state']=='STARTED' and now>=job['last_now'],'REQUIRED_TASK_INACTIVE')
        envelope=JobEnvelope.parse(job['envelope']);claim=JobClaim(**job['claim'])
        gov._epoch(state,claim.governor_epoch)
        require(claim.task_id==completion.task_id and claim.envelope_digest==envelope.envelope_digest
                and now<claim.lease_until and now<envelope.deadline_at,'REQUIRED_TASK_INACTIVE')
        return job

    def authorize(self,principal,session_id,operation,completion,graph,trace,*,nonce,model_id,money_nano,risk_units):
        require(self.policy_revision not in (3, 4, 5), 'EXACT_OWNER_APPROVAL_REQUIRED')
        return self._authorize(principal, session_id, operation, completion, graph, trace,
            nonce=nonce, model_id=model_id, money_nano=money_nano, risk_units=risk_units, exact=False)

    def authorize_exact(self, principal, session_id, operation, completion, graph, trace,
                        *, nonce, model_id, money_nano, risk_units):
        """One exact owner witness in the existing ledger, explicit policies3/4.

        No model boolean, delegated v1 grant or reconstructed START ACK
        substitutes for this current-session OWNER_APPROVAL transaction.
        """
        self.core.require(principal, Capability.OWNER_APPROVAL, scope=self.scope)
        require(self.policy_revision in (3, 4, 5), 'EXACT_OWNER_POLICY_REQUIRED')
        operation = self._snapshot_operation(operation)
        with self.target_guard():
            return self._authorize(principal, session_id, operation, completion, graph, trace,
                nonce=nonce, model_id=model_id, money_nano=money_nano, risk_units=risk_units, exact=True)

    def _authorize(self, principal, session_id, operation, completion, graph, trace,
                   *, nonce, model_id, money_nano, risk_units, exact):
        purpose = Capability.OWNER_APPROVAL if exact else Capability.COMMIT
        self.core.require(principal, purpose, scope=self.scope)
        require(exact == (self.policy_revision in (3, 4, 5)), 'EXACT_OWNER_POLICY_REQUIRED')
        operation=self._snapshot_operation(operation)
        require(type(completion) is TaskCompletionBinding and type(graph) is DependencyGraph
                and type(trace) is FaultTrace,'INVALID_TOOL_BINDING')
        opaque_id(nonce,'nonce')
        snapshot=self._probe_target();self._operation(operation,snapshot)
        require(model_id in principal.model_binding_ids,'MODEL_BINDING_DENIED')
        def change(tx):
            _,session_state,grant=self._session(tx,session_id)
            self._native_job(tx,completion)
            if self.bound_variant is SANDBOX:self._sandbox_scope(operation,completion,graph,trace,grant)
            portable = self.bound_variant in (PORTABLE, PORTABLE_REARM)
            if portable:self._portable_scope(operation, completion, grant, session_state)
            require(completion.scope==self.scope and completion.digest==grant.completion_digest
                    and completion.task_id==graph.task_id==trace.task_id
                    and completion.graph_digest==canonical_sha256(graph.to_dict())
                    and trace.operation_digest=='sha256:'+canonical_sha256(operation)
                    and operation['operation_class'] in grant.capabilities
                    and type(money_nano) is int
                    and (money_nano == grant.money_nano == 0 if portable else 0 < money_nano <= grant.money_nano)
                    and type(risk_units) is int and 5<=risk_units<=grant.risk_units,'SESSION_SCOPE_DENIED')
            _,stored_graph=self.liability._load(tx,completion.task_id)
            require(stored_graph['graph']==graph.to_dict(),'DEPENDENCY_GRAPH_CONFLICT')
            by_id={n.node_id:n for n in graph.nodes};seen=set();pending=[completion.candidate_id]
            while pending:
                node=pending.pop();require(node in by_id,'INVALID_TOOL_BINDING')
                if node not in seen:seen.add(node);pending.extend(by_id[node].required_dependencies)
            require(any(classify_fault(trace).liability_id in by_id[n].liability_ids for n in seen),
                    'LIABILITY_DEPENDENCY_REQUIRED')
            reservation_id=canonical_sha256((self.bound_variant.reservation_domain,self.scope,nonce))
            reservation=ReservationRequest(reservation_id,completion.task_id,self.bound_variant.provider_id,model_id,
                                           canonical_sha256(operation),money_nano,risk_units)
            start=datetime.fromtimestamp(self.clock(),UTC)
            end=datetime.fromtimestamp(grant.expires_at,UTC)
            if portable:
                from runtime.mission.portable_target import _portable_operation
                parsed = _portable_operation(operation)
                request = (parsed.request.to_dict() if self.bound_variant is PORTABLE_REARM
                           else parsed.domain_input.to_dict()['request'])
                if self.bound_variant is PORTABLE_REARM:
                    require(request['decision_nonce_hash'] == canonical_sha256(nonce), 'PORTABLE_REARM_NONCE_BINDING')
                request_start = datetime.fromisoformat(request['requested_at'])
                request_end = datetime.fromisoformat(request['expires_at'])
                require(request_start <= start < request_end, 'PORTABLE_REQUEST_EXPIRED')
                end = min(end, request_end)
            owner=canonical_sha256(self.scope)
            scope=AuthorityScope((operation['operation_class'],),snapshot.fingerprint,RiskLevel.MODERATE,
                Money(Decimal(money_nano)/Decimal(10**9),'USD'),start,end,owner,completion.task_id)
            warrant=EffectWarrant(warrant_id=nonce,task_id=completion.task_id,owner_scope=owner,
                operation_class=operation['operation_class'],operation_hash=trace.operation_digest,
                target_fingerprint=snapshot.fingerprint,expected_target_revision=snapshot.revision,
                revision_policy=RevisionPolicy.REQUIRE,decision_dependency_root=self._ddr(snapshot,completion,grant,reservation),
                lease_epoch=grant.epoch,authority_scope=scope,approval_digest='sha256:'+'0'*64,
                money_reservation_id='NONE' if portable else reservation_id,risk_reservation_id=reservation_id,nonce=nonce,
                issued_at=start,expires_at=end)
            warrant=replace(warrant,approval_digest=approval_digest(warrant))
            ledger=self.journal.ledger;ledger._check(warrant)
            require(tx.get(RecordKind.OPERATION,ledger._key(warrant)) is None,'NONCE_ALREADY_REGISTERED')
            if exact:
                # The existing intent key deduplicates task+operation, not nonce.
                # Never issue an alias approval that could poison later history
                # joins. Keep the earlier authority unchanged and require an
                # explicit new Task/Run instead of silently retrying the effect.
                rows = tx.scan(RecordKind.OPERATION, limit=1024)
                require(len(rows) < 1024, 'TOOL_HISTORY_QUOTA')
                for row in rows:
                    if row.payload.get('schema') in (CONTEXT, EXACT_CONTEXT, PORTABLE_CONTEXT, REARM_CONTEXT):
                        existing = EffectWarrant.from_dict(json.loads(canonical_json_bytes(row.payload['warrant'])))
                        require((existing.task_id, existing.operation_hash)
                                != (warrant.task_id, warrant.operation_hash),
                                'OPERATION_ALREADY_AUTHORIZED')
            # Exact policy uses the existing human approval transaction.
            # Legacy policies retain their deterministic narrower delegation.
            if exact:
                ledger.approve_in_transaction(tx, warrant)
            else:
                ledger._save(tx,warrant,{'schema':'aioa-linear-warrant-v1','root':warrant.to_dict(),
                                        'active':warrant.to_dict(),'consumption':None})
            context={'schema':REARM_CONTEXT if self.bound_variant is PORTABLE_REARM else PORTABLE_CONTEXT if portable else EXACT_CONTEXT if exact else CONTEXT,'session_id':session_id,'grant_digest':grant.digest,
                     'completion':completion.to_dict(),'graph':graph.to_dict(),'trace':trace.to_dict(),
                     'warrant':warrant.to_dict(),'reservation':asdict(reservation),'target_ddr':snapshot.ddr.to_dict()}
            tx.insert(StoredRecord(RecordKind.OPERATION,self._context_key(warrant),self.scope,1,context))
            return warrant
        return self._run(principal,purpose,change)

    def _check(self,tx,session_id,warrant,operation,completion,snapshot):
        _,session_state,grant=self._session(tx,session_id)
        self._native_job(tx,completion,dispatch=True)
        context,binding,graph,trace=self._context(tx,warrant)
        self._context_target_snapshot(warrant,context)
        require(context['session_id']==session_id and context['grant_digest']==grant.digest
                and binding==completion and completion.digest==grant.completion_digest
                and operation['operation_class'] in grant.capabilities
                and self._ddr(snapshot,completion,grant,ReservationRequest(**context['reservation']))==warrant.decision_dependency_root,'STALE_TOOL_BINDING')
        self._operation(operation,snapshot)
        if grant.policy_revision in (3, 4, 5):
            # This method runs after START only in the live ACK branch.
            # A retained intent never grants another callback attempt.
            intent_row, _ = self.journal._load(tx, warrant)
            self.journal.ledger.require_active_in_transaction(
                tx, warrant, consumed=intent_row is not None)
        if self.bound_variant is SANDBOX:self._sandbox_scope(operation,completion,graph,trace,grant)
        if self.bound_variant in (PORTABLE, PORTABLE_REARM):self._portable_scope(operation, completion, grant, session_state, warrant=warrant)
        require(warrant.target_fingerprint==snapshot.fingerprint
                and warrant.expected_target_revision==snapshot.revision,'STALE_TOOL_BINDING')
        _,stored=self.liability._load(tx,warrant.task_id)
        require(stored['graph']==graph.to_dict(),'DEPENDENCY_GRAPH_CONFLICT')
        return grant,context,graph,trace

    def _retained(self,tx,session_id,warrant,operation,reservation,completion):
        context,binding,_,_=self._context(tx,warrant)
        snapshot=self._context_target_snapshot(warrant,context)
        _,_,grant=self._session(tx,context['session_id'],active=False)
        variant=tool_variant(grant.policy_revision,warrant.operation_class)
        self._operation(operation,snapshot,variant=variant,historical=True)
        require(session_id==context['session_id'] and binding==completion
                and type(reservation) is ReservationRequest
                and asdict(reservation)==context['reservation']
                and 'sha256:'+canonical_sha256(operation)==warrant.operation_hash,
                'TOOL_CONTEXT_INTEGRITY')
        row,intent=self.journal._load(tx,warrant)
        if row is not None and self.target_settlement is not None:
            self.target_settlement.check_history_in_transaction(tx, warrant, intent)
        return None if row is None else {'mode':variant.mode,**self.journal._public(intent)}

    def dispatch(self,principal,*,session_id,warrant,operation,reservation,completion,cancel=None):
        self.core.require(principal,Capability.COMMIT,scope=self.scope)
        if cancel is not None:
            from runtime.providers.exact import CancellationToken
            require(type(cancel) is CancellationToken and self.bound_variant in (SANDBOX, PORTABLE, PORTABLE_REARM),
                    'SANDBOX_CANCEL_BINDING')
            require(not cancel.cancelled,'SANDBOX_CANCELLED')
        operation=self._snapshot_operation(operation)
        # Guard before DB/CAS locks. Acquisition failure is a denial, never fallback.
        # It covers the synchronous attempt, not only the last authority check.
        with self.target_guard():
            return self._dispatch(principal,session_id=session_id,warrant=warrant,
                operation=operation,reservation=reservation,completion=completion,cancel=cancel)

    def _dispatch(self,principal,*,session_id,warrant,operation,reservation,completion,cancel=None):
        self.core.require(principal,Capability.COMMIT,scope=self.scope)
        portable = self.bound_variant in (PORTABLE, PORTABLE_REARM)
        marker_key = 'local_step_now' if portable else 'fixture_step_now'
        retained=self._run(principal,Capability.COMMIT,lambda tx:
            self._retained(tx,session_id,warrant,operation,reservation,completion))
        if retained is not None:return retained
        snapshot=self._probe_target()
        def start(tx):
            # Competing START may have committed after the read above. Retained
            # observation never invokes target IO or activates expired authority.
            if self._retained(tx,session_id,warrant,operation,reservation,completion) is not None:
                return {marker_key:False}
            grant,context,graph,trace=self._check(tx,session_id,warrant,operation,completion,snapshot)
            require(type(reservation) is ReservationRequest
                    and asdict(reservation)==context['reservation'],'RESERVATION_BINDING')
            gov=self.journal.governor;state=gov._load(tx)
            # Sum existing native reservations only; authorized-but-not-started context is not charged.
            money=risk=0
            rows=tx.scan(RecordKind.OPERATION,limit=1024);require(len(rows)<1024,'TOOL_HISTORY_QUOTA')
            known_intents=set();known_reservations=set()
            for row in rows:
                c=json.loads(canonical_json_bytes(row.payload))
                if c.get('schema') in (CONTEXT, EXACT_CONTEXT, PORTABLE_CONTEXT, REARM_CONTEXT):
                    w=EffectWarrant.from_dict(c['warrant']);self._context(tx,w)
                    reservation_id = w.risk_reservation_id if c['schema'] in (PORTABLE_CONTEXT, REARM_CONTEXT) else w.money_reservation_id
                    known_intents.add(w.digest());known_reservations.add(reservation_id)
                    if c['session_id']==session_id:
                        entry=state['reservations'].get(reservation_id)
                        intent_row,_=self.journal._load(tx,w)
                        require((entry is None)==(intent_row is None),'TOOL_ACCOUNTING_INTEGRITY')
                        if entry is not None:
                            require(entry['task_id']==w.task_id,'TOOL_ACCOUNTING_INTEGRITY')
                            if entry['state']!='RELEASED':
                                money+=entry['money_nano'];risk+=entry['risk_units']
            # Reverse joins detect deleted/renamed context after START; no clean-by-absence accounting.
            for row in rows:
                c=json.loads(canonical_json_bytes(row.payload))
                if c.get('schema') in INTENT_KINDS and c.get('operation',{}).get('payload',{}).get('tool') in {'write_file','run_recipe','release_elastic_ip','rearm_demo'}:
                    require(c['warrant_digest'] in known_intents,'TOOL_CONTEXT_REQUIRED')
            for request_id,entry in state['reservations'].items():
                if entry['provider_id'] in {'synthetic','sandbox-exec','portable-local'}:
                    require(request_id in known_reservations,'TOOL_CONTEXT_REQUIRED')
            prior,_=self.journal._load(tx,warrant)
            if prior is None:
                require(money+reservation.money_nano<=grant.money_nano
                        and risk+reservation.risk_units<=grant.risk_units,'SESSION_BUDGET_EXCEEDED')
            result=(self.journal._start_in_transaction(tx,warrant,operation,reservation,local_zero=True)
                    if portable else self.journal.start_in_transaction(tx,warrant,operation,reservation))
            if result[marker_key]:
                if self.target_settlement is not None:
                    self.target_settlement.start_in_transaction(tx, warrant, operation, snapshot)
                self.liability.record_unknown_in_transaction(tx,trace,graph,
                    datetime.fromtimestamp(self.clock(),UTC))
                if portable:
                    from runtime.mission.portable_target import _PortableStartAck
                    result['_portable_ack'] = _PortableStartAck.issue_in_transaction(self, tx, warrant)
            return result
        result=self._run(principal,Capability.COMMIT,start)
        def readback(tx):
            _, state = self.journal._load(tx, warrant)
            require(state is not None, 'INTENT_REQUIRED')
            if self.target_settlement is not None:
                self.target_settlement.check_history_in_transaction(tx, warrant, state)
            return {'mode': self._mode(tx,warrant), **self.journal._public(state)}
        if result[marker_key]:
            # Only this ACK grants the one attempt. Never recover an attempt from durable START.
            fresh=self._probe_target()
            def prepare(tx):
                grant,context,_,_=self._check(tx,session_id,warrant,operation,completion,fresh)
                if self.bound_variant is SANDBOX:
                    return self._sandbox_request(tx,grant,context,warrant)
                if self.target_settlement is not None and not portable:
                    self.target_settlement.before_release_in_transaction(tx, warrant, operation, fresh)
                return ToolDispatchLimits(grant.deadline_seconds,grant.output_bytes,grant.egress)
            prepared=self._run(principal,Capability.COMMIT,prepare)
            try:
                with failure_boundary('TOOL_EXECUTOR_UNKNOWN', preserve=(CommitOutcomeUnknown,) if portable else ()):
                    if self.bound_variant is SANDBOX:
                        from runtime.mission.sandbox_linux import LinuxSandboxBroker
                        if type(self.executor) is LinuxSandboxBroker:
                            def release_check():
                                snapshot=self._probe_target()
                                def check(tx):
                                    grant,context,_,_=self._check(tx,session_id,warrant,operation,completion,snapshot)
                                    current=self._sandbox_request(tx,grant,context,warrant)
                                    require(current==prepared,'SANDBOX_REQUEST_BINDING')
                                return self._run(principal,Capability.COMMIT,check)
                            if cancel is None:self.executor.dispatch(prepared,release_check)
                            else:self.executor.dispatch(prepared,release_check,cancel=cancel)
                        else:self.executor(prepared)
                    else:
                        if portable:
                            from runtime.mission.portable_target import (
                                CorePortableWriteRelease,
                            )
                            release = CorePortableWriteRelease.from_live_ack(self, principal, session_id,
                                warrant, operation, completion, prepared, result['_portable_ack'], cancel=cancel)
                            try:
                                acknowledgment = self.executor.dispatch(
                                    self._snapshot_operation(operation), warrant, prepared, release)
                            finally:
                                release.close()
                        else:
                            acknowledgment = self.executor(self._snapshot_operation(operation),warrant,prepared)
                        if self.target_settlement is not None and acknowledgment is not None:
                            self._target_descriptor.require_ack(warrant, acknowledgment)
                            def record_ack(tx):
                                self.target_settlement.record_ack_in_transaction(tx, warrant, acknowledgment)
                            self._run(principal, Capability.COMMIT, record_ack)
            except (ValueError, RepairBoundaryError):
                # An adapter exception proves no terminal result. Preserve
                # native UNKNOWN without logging callback data or retrying.
                return self._run(principal, Capability.COMMIT, readback)
        return self._run(principal, Capability.COMMIT, readback)

    def inspect(self,principal,warrant):
        def read(tx):
            context,_,_,_=self._context(tx,warrant)
            self._context_target_snapshot(warrant,context)
            _,state=self.journal._load(tx,warrant);require(state is not None,'INTENT_REQUIRED')
            if self.target_settlement is not None:
                self.target_settlement.check_history_in_transaction(tx, warrant, state)
            return {'mode':self._mode(tx,warrant),**self.journal._public(state)}
        return self._run(principal,Capability.READ,read)

    def reconcile(self,principal,warrant,epoch):
        self.core.require(principal,Capability.COMMIT,scope=self.scope)
        with self.target_guard():
            return self._reconcile(principal,warrant,epoch)

    def _reconcile(self,principal,warrant,epoch):
        def read(tx):
            context,_,_,trace=self._context(tx,warrant)
            self._context_target_snapshot(warrant,context)
            _,intent=self.journal._load(tx,warrant);require(intent is not None,'INTENT_REQUIRED')
            _,state=self.liability._load(tx,warrant.task_id)
            entry=state['entries'].get(classify_fault(trace).liability_id)
            require(entry is not None,'LIABILITY_STATE_REQUIRED')
            require(intent['resolution']==entry['resolution'],'TOOL_RECONCILIATION_INTEGRITY')
            if self.target_settlement is not None:
                self.target_settlement.check_history_in_transaction(tx, warrant, intent)
            return intent,entry,trace
        intent,entry,trace=self._run(principal,Capability.COMMIT,read)
        mode=self._run(principal,Capability.COMMIT,lambda tx:self._mode(tx,warrant))
        if intent['resolution'] is not None:return {'mode':mode,**self.journal._public(intent)}
        require(self.verifier is not None,'INDEPENDENT_READBACK_REQUIRED')
        try:
            with failure_boundary('TOOL_READBACK_UNAVAILABLE'):
                observed=self.verifier(intent['operation'],warrant)
        except (ValueError, RepairBoundaryError):
            require(False,'INDEPENDENT_READBACK_UNAVAILABLE')
        if self.target_settlement is not None:
            require(type(observed) in (VerifiedTargetSettlement, VerifiedNoReleaseSettlement, VerifiedRearmTargetSettlement),
                    'VERIFIED_TARGET_OBSERVATION_REQUIRED')
            self._target_descriptor.require_observation(observed.target)
            resolution = observed.resolution
        else:
            resolution = observed
        require(type(resolution) is Reconciliation and resolution.operation_digest==warrant.operation_hash,
                'UNRESOLVED_READBACK')
        def change(tx):
            if self.target_settlement is not None:
                self.target_settlement.apply_resolution_in_transaction(tx, warrant, epoch, observed)
            self.liability.apply_resolution_in_transaction(tx,warrant.task_id,
                classify_fault(trace).liability_id,datetime.fromtimestamp(self.clock(),UTC),resolution,entry)
            return self.journal.apply_resolution_in_transaction(tx,warrant,epoch,resolution)
        result=self._run(principal,Capability.COMMIT,change)
        return {'mode':mode,**result}
