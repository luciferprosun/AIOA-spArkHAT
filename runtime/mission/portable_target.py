"""Exact managed Portable operations through the existing Core and executor.

Fact codecs grant no authority. One live CoreToolRoute acknowledgment, current
owner approval, an adopted target and its held guard bind the synchronous write.
Product physical INIT and automatic rearm remain closed; no Native activation occurs here.
"""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from os import getpid
from threading import get_ident
from types import MethodType
from uuid import UUID

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import opaque_id
from lab.archaioa.outcome import Applied, NotApplied
from lab.archaioa.warrant import EffectWarrant
from nonzero_cloudops.adapters.portable import (
    _RESOURCE_ADAPTER,
    PortableExecutor,
    PortableInventoryObservation,
    PortableStateStore,
    _canonical_inventory_bytes,
    _NonTransferableGuardValue,
    _PortableGuardEntry,
)
from nonzero_cloudops.adapters.resources import default_mock_resources
from nonzero_cloudops.models import (
    ApprovalDecision,
    ElasticIpResource,
    LocalApprovalDecisionRecord,
    LocalApprovalRequestRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    ProposalState,
    RemediationOperation,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
)
from nonzero_cloudops.models.public_enums import AuthorityGate

from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.intent import INTENT_KINDS
from runtime.mission.liability import Reconciliation
from runtime.mission.target_projection import (
    MAX_TARGET_HISTORY,
    PHYSICAL_HISTORY,
    REGISTERED_HEAD,
    CoreTargetProjection,
)
from runtime.mission.target_settlement import (
    FencedNoReleaseCertificate,
    TargetBinding,
    TargetExecutionAck,
    TargetObservation,
    TargetRearmWriteObservation,
    TargetWriteObservation,
    VerifiedNoReleaseSettlement,
    VerifiedRearmTargetSettlement,
    VerifiedTargetSettlement,
)
from runtime.mission.warrant import require

PORTABLE_INPUT = 'aioa.portable-domain-input.v1'
PORTABLE_INPUT_MAX_BYTES = 49152


def _inventory(value):
    require(type(value) is dict and set(value) == {'format_version', 'resources', 'receipts'}
            and type(value['format_version']) is int and value['format_version'] == 1
            and type(value['resources']) is list and type(value['receipts']) is list,
            'PORTABLE_INPUT_INVENTORY')
    try:
        resources = [_RESOURCE_ADAPTER.validate_python(item) for item in value['resources']]
        receipts = [LocalExecutionReceipt.model_validate(item) for item in value['receipts']]
        resource_map = {(item.resource_type, item.resource_id, item.region): item for item in resources}
        receipt_map = {item.idempotency_key: item for item in receipts}
        normalized = PortableStateStore._payload(resource_map, receipt_map)
    except (TypeError, ValueError):
        require(False, 'PORTABLE_INPUT_INVENTORY')
    require(len(resource_map) == len(resources) and len(receipt_map) == len(receipts)
            and canonical_json_bytes(normalized) == canonical_json_bytes(value),
            'PORTABLE_INPUT_INVENTORY')
    return resource_map, receipt_map


@dataclass(frozen=True, slots=True)
class PortableDomainInput:
    """Immutable exact proposal, request and complete pre-state, never permission.

    Legacy domain approval/intent records may later reflect the existing Core
    decision. They are deliberately absent from this pre-approval input codec.
    No model, provider, path, callable or executor can be registered here.
    """
    canonical_input: bytes = field(repr=False)
    state_root: str = field(init=False)
    resources_root: str = field(init=False)
    receipts_root: str = field(init=False)

    def __post_init__(self):
        raw = self.canonical_input
        require(type(raw) is bytes and 0 < len(raw) <= PORTABLE_INPUT_MAX_BYTES,
                'PORTABLE_INPUT_BYTES')
        try:
            value = json.loads(raw)
            canonical = canonical_json_bytes(value)
        except (TypeError, ValueError, RecursionError):
            require(False, 'PORTABLE_INPUT_CANONICAL')
        require(canonical == raw, 'PORTABLE_INPUT_CANONICAL')
        require(type(value) is dict
                and set(value) == {'schema', 'proposal', 'evidence', 'request', 'inventory'}
                and value['schema'] == PORTABLE_INPUT, 'PORTABLE_INPUT_SHAPE')
        try:
            proposal = RemediationProposal.model_validate(value['proposal'])
            evidence = ResourceEvidence.model_validate(value['evidence'])
            request = LocalApprovalRequestRecord.model_validate(value['request'])
        except (TypeError, ValueError):
            require(False, 'PORTABLE_INPUT_DOMAIN')
        for name, parsed in [('proposal', proposal), ('evidence', evidence), ('request', request)]:
            require(canonical_json_bytes(parsed.model_dump(mode='json')) == canonical_json_bytes(value[name]),
                    'PORTABLE_INPUT_DOMAIN_CANONICAL')
        require(proposal.operation_type is RemediationOperation.RELEASE_ELASTIC_IP
                and proposal.status is ProposalState.AWAITING_APPROVAL
                and proposal.authority_class is AuthorityGate.PLAN_AND_CONFIRM
                and proposal.authorizes_execution is False
                and isinstance(evidence.resource, ElasticIpResource)
                and evidence.resource.association_id is None
                and proposal.normalized_parameters == {'allocation_id': proposal.target_resource_id},
                'PORTABLE_INPUT_OPERATION_DENIED')
        require(proposal.run_id == evidence.run_id
                and proposal.correlation_id == evidence.correlation_id
                and proposal.evidence_hash == evidence.evidence_hash
                and proposal.evidence_fingerprint == evidence.stable_fingerprint()
                and proposal.target_resource_type is evidence.resource.resource_type
                and proposal.target_resource_id == evidence.resource.resource_id
                and evidence.observed_at <= proposal.created_at,
                'PORTABLE_INPUT_EVIDENCE_BINDING')
        resources, receipts = _inventory(value['inventory'])
        key = (proposal.target_resource_type, proposal.target_resource_id, evidence.resource.region)
        require(resources.get(key) == evidence.resource, 'PORTABLE_INPUT_TARGET_DRIFT')
        require(f'local-exec:{proposal.run_id}:{proposal.proposal_hash}' not in receipts
                and not any(receipt.run_id == proposal.run_id
                            and receipt.proposal_hash == proposal.proposal_hash
                            for receipt in receipts.values()), 'PORTABLE_INPUT_ALREADY_RECEIPTED')
        require(proposal.created_at <= request.requested_at
                and request.expires_at <= proposal.expires_at, 'PORTABLE_INPUT_REQUEST_BINDING')
        expected = LocalApprovalRequestRecord.create(
            request_id=request.request_id, proposal=proposal,
            actor_session_id=request.actor_session_id,
            decision_nonce_hash=request.decision_nonce_hash,
            requested_at=request.requested_at, expires_at=request.expires_at)
        require(expected == request and proposal.created_at <= request.requested_at
                and request.expires_at <= proposal.expires_at,
                'PORTABLE_INPUT_REQUEST_BINDING')
        for name, part in [('state_root', value['inventory']),
                           ('resources_root', value['inventory']['resources']),
                           ('receipts_root', value['inventory']['receipts'])]:
            object.__setattr__(self, name, hashlib.sha256(_canonical_inventory_bytes(part)).hexdigest())

    @property
    def authority(self):
        return 'NONE'

    def to_dict(self):
        return json.loads(self.canonical_input)


PORTABLE_OPERATION_CLASS = 'PORTABLE_RELEASE_ELASTIC_IP'
PORTABLE_OPERATION_SCHEMA = 'aioa.portable-operation.v1'


@dataclass(frozen=True, slots=True)
class PortableOperation:
    """Distinct exact tool input; the fixed caller still needs Core authority.

    A matching request actor and binding digest are facts to be joined to the
    live Core context, not authentication. This value carries no path, argv,
    executor, release permit or replay permission.
    """
    canonical_operation: bytes = field(repr=False)

    def __post_init__(self):
        raw = self.canonical_operation
        require(type(raw) is bytes and 0 < len(raw) <= 65536, 'PORTABLE_OPERATION_BYTES')
        try:
            value = json.loads(raw)
            canonical = canonical_json_bytes(value)
        except (TypeError, ValueError, RecursionError):
            require(False, 'PORTABLE_OPERATION_CANONICAL')
        require(canonical == raw, 'PORTABLE_OPERATION_CANONICAL')
        require(type(value) is dict and set(value) == {
            'operation_class', 'target_fingerprint', 'expected_target_revision', 'payload'}
            and value['operation_class'] == PORTABLE_OPERATION_CLASS
            and type(value['payload']) is dict, 'PORTABLE_OPERATION_SHAPE')
        payload = value['payload']
        require(set(payload) == {'schema', 'tool', 'workspace', 'task_id', 'session_id',
                                 'principal_session_id', 'policy_epoch', 'target_binding_digest', 'domain_input'}
                and payload['schema'] == PORTABLE_OPERATION_SCHEMA
                and payload['tool'] == 'release_elastic_ip', 'PORTABLE_OPERATION_SHAPE')
        for name in ('principal_session_id', 'target_binding_digest'):
            digest = payload[name]
            require(type(digest) is str and len(digest) == 64
                    and all(character in '0123456789abcdef' for character in digest),
                    'PORTABLE_OPERATION_IDENTITY')
        for name in ('workspace', 'task_id', 'session_id'):
            opaque_id(payload[name], 'portable ' + name)
        opaque_id(value['expected_target_revision'], 'portable target revision')
        epoch = payload['policy_epoch']
        require(type(epoch) is int and 0 < epoch < 2**63, 'PORTABLE_OPERATION_POLICY_BINDING')
        pack = PortableDomainInput(canonical_json_bytes(payload['domain_input']))
        require(value['target_fingerprint'] == 'sha256:' + pack.state_root,
                'PORTABLE_OPERATION_TARGET_BINDING')
        require(payload['principal_session_id'] == pack.to_dict()['request']['actor_session_id'],
                'PORTABLE_OPERATION_OWNER_BINDING')

    @classmethod
    def parse(cls, value):
        require(type(value) is dict, 'PORTABLE_OPERATION_SHAPE')
        return cls(canonical_json_bytes(value))

    @classmethod
    def create(cls, *, workspace, task_id, session_id, principal_session_id, policy_epoch,
               target_binding_digest, target_revision, domain_input):
        require(type(domain_input) is PortableDomainInput, 'PORTABLE_DOMAIN_FACTS_REQUIRED')
        return cls.parse({
            'operation_class': PORTABLE_OPERATION_CLASS,
            'target_fingerprint': 'sha256:' + domain_input.state_root,
            'expected_target_revision': target_revision,
            'payload': {'schema': PORTABLE_OPERATION_SCHEMA, 'tool': 'release_elastic_ip',
                'workspace': workspace, 'task_id': task_id, 'session_id': session_id,
                'principal_session_id': principal_session_id, 'policy_epoch': policy_epoch,
                'target_binding_digest': target_binding_digest, 'domain_input': domain_input.to_dict()},
        })

    @property
    def domain_input(self):
        return PortableDomainInput(canonical_json_bytes(self.to_dict()['payload']['domain_input']))

    @property
    def authority(self):
        return 'NONE'

    @property
    def digest(self):
        return 'sha256:' + hashlib.sha256(self.canonical_operation).hexdigest()

    def to_dict(self):
        return json.loads(self.canonical_operation)


PORTABLE_REARM_INPUT = 'aioa.portable-rearm-domain-input.v1'
PORTABLE_REARM_REQUEST = 'aioa.portable-rearm-request.v1'
PORTABLE_REARM_SCHEMA = 'aioa.portable-rearm-operation.v1'
PORTABLE_REARM_CLASS = 'PORTABLE_REARM_DEMO_V1'
PORTABLE_REARM_TEMPLATE = 'aioa.portable-demo-eip-template.v1'


def _rearm_root(value):
    require(type(value) is str and len(value) == 64
            and all(character in '0123456789abcdef' for character in value), 'PORTABLE_REARM_DIGEST')


def _rearm_bytes(raw, schema, fields, maximum):
    require(type(raw) is bytes and 0 < len(raw) <= maximum, 'PORTABLE_REARM_BYTES')
    try:
        value = json.loads(raw)
        require(canonical_json_bytes(value) == raw, 'PORTABLE_REARM_CANONICAL')
    except (TypeError, ValueError, RecursionError):
        require(False, 'PORTABLE_REARM_CANONICAL')
    require(type(value) is dict and set(value) == fields and value['schema'] == schema,
            'PORTABLE_REARM_SHAPE')
    return value


def _rearm_time(value):
    require(type(value) is str, 'PORTABLE_REARM_TIME')
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        require(False, 'PORTABLE_REARM_TIME')
    require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)
            and parsed.isoformat() == value, 'PORTABLE_REARM_TIME')
    return parsed


def _rearm_template(query):
    require(type(query) is ResourceQuery, 'PORTABLE_REARM_QUERY')
    selected = tuple(resource for resource in default_mock_resources() if type(resource) is ElasticIpResource)
    require(len(selected) == 1, 'PORTABLE_REARM_FIXED_TEMPLATE')
    template = selected[0]
    require((query.resource_type, query.resource_id, query.region)
            == (template.resource_type, template.resource_id, template.region), 'PORTABLE_REARM_QUERY')
    return template


def _rearm_consumed(query, resources, receipts):
    template = _rearm_template(query)
    require((query.resource_type, query.resource_id, query.region) not in resources,
            'PORTABLE_REARM_RESOURCE_PRESENT')
    relevant = tuple(receipts[key] for key in sorted(receipts) if (
        receipts[key].target_resource_type == query.resource_type
        and receipts[key].target_resource_id == query.resource_id
        and receipts[key].before_resource.region == query.region))
    require(relevant and all(receipt.operation_type is RemediationOperation.RELEASE_ELASTIC_IP
            and receipt.before_resource == template and receipt.after_resource is None for receipt in relevant),
            'PORTABLE_REARM_RELEASE_SET')
    return relevant


@dataclass(frozen=True, slots=True)
class PortableRearmDomainInput:
    """Complete guarded facts for one fixed demo restoration; never authority."""
    canonical_input: bytes = field(repr=False)
    state_root: str = field(init=False)
    resources_root: str = field(init=False)
    receipts_root: str = field(init=False)

    def __post_init__(self):
        value = _rearm_bytes(self.canonical_input, PORTABLE_REARM_INPUT, {
            'schema', 'binding', 'head_revision', 'generation', 'target_revision', 'history_digest',
            'epoch', 'query', 'template_version', 'template_digest', 'template',
            'release_receipt_hashes', 'inventory', 'state_root', 'resources_root', 'receipts_root'}, PORTABLE_INPUT_MAX_BYTES)
        binding = value['binding']
        require(type(binding) is dict and set(binding) == {'scope', 'workspace', 'target_id',
                'incarnation', 'guard_fingerprint'} and type(binding['scope']) is dict
                and set(binding['scope']) == {'tenant_id', 'owner_id', 'space_id', 'slot_id'},
                'PORTABLE_REARM_BINDING')
        fixed = TargetBinding(**{**binding, 'scope': OwnerScope(**binding['scope'])})
        require(asdict(fixed) == binding, 'PORTABLE_REARM_BINDING')
        require(type(value['head_revision']) is int and value['head_revision'] >= 1
                and type(value['generation']) is int and 1 <= value['generation'] < MAX_TARGET_HISTORY
                and type(value['epoch']) is int and 0 < value['epoch'] < 2**63,
                'PORTABLE_REARM_REVISION')
        opaque_id(value['target_revision'], 'rearm target revision')
        _rearm_root(value['history_digest'])
        try:
            query = ResourceQuery.model_validate(value['query'])
        except (TypeError, ValueError):
            require(False, 'PORTABLE_REARM_QUERY')
        require(query.model_dump(mode='json') == value['query'], 'PORTABLE_REARM_QUERY')
        template = _rearm_template(query).model_dump(mode='json')
        require(value['template_version'] == PORTABLE_REARM_TEMPLATE and value['template'] == template
                and value['template_digest'] == canonical_sha256({'schema': PORTABLE_REARM_TEMPLATE, 'resource': template}),
                'PORTABLE_REARM_FIXED_TEMPLATE')
        resources, receipts = _inventory(value['inventory'])
        relevant = _rearm_consumed(query, resources, receipts)
        hashes = value['release_receipt_hashes']
        require(type(hashes) is list and hashes == sorted({receipt.receipt_hash for receipt in relevant})
                and len(hashes) == len(relevant), 'PORTABLE_REARM_COMPLETE_RECEIPTS')
        for name, part in [('state_root', value['inventory']), ('resources_root', value['inventory']['resources']),
                           ('receipts_root', value['inventory']['receipts'])]:
            digest = hashlib.sha256(_canonical_inventory_bytes(part)).hexdigest()
            require(value[name] == digest, 'PORTABLE_REARM_ROOT_BINDING')
            object.__setattr__(self, name, digest)

    @property
    def authority(self):
        return 'NONE'

    @property
    def digest(self):
        return hashlib.sha256(self.canonical_input).hexdigest()

    def to_dict(self):
        return json.loads(self.canonical_input)


@dataclass(frozen=True, slots=True)
class PortableRearmRequest:
    """Exact immutable owner-request facts, separate from release domain records."""
    canonical_request: bytes = field(repr=False)

    def __post_init__(self):
        value = _rearm_bytes(self.canonical_request, PORTABLE_REARM_REQUEST, {
            'schema', 'domain_digest', 'request_id', 'run_id', 'actor_session_id',
            'assignment_revision', 'decision_nonce_hash', 'requested_at', 'expires_at'}, 4096)
        for name in ('domain_digest', 'actor_session_id', 'decision_nonce_hash'):
            _rearm_root(value[name])
        opaque_id(value['request_id'], 'rearm request')
        require(type(value['run_id']) is str, 'PORTABLE_REARM_RUN')
        try:
            run = UUID(value['run_id'])
        except ValueError:
            require(False, 'PORTABLE_REARM_RUN')
        require(run.version == 7 and str(run) == value['run_id'], 'PORTABLE_REARM_RUN')
        require(type(value['assignment_revision']) is int and value['assignment_revision'] >= 1,
                'PORTABLE_REARM_OWNER_ASSIGNMENT')
        start, end = _rearm_time(value['requested_at']), _rearm_time(value['expires_at'])
        require(timedelta(0) < end - start <= timedelta(seconds=300), 'PORTABLE_REARM_REQUEST_LIFETIME')

    @classmethod
    def create(cls, *, domain_input, request_id, run_id, actor_session_id, assignment_revision,
               decision_nonce_hash, requested_at, expires_at):
        require(type(domain_input) is PortableRearmDomainInput and type(requested_at) is datetime
                and type(expires_at) is datetime, 'PORTABLE_REARM_REQUEST_FACTS')
        return cls(canonical_json_bytes({'schema': PORTABLE_REARM_REQUEST, 'domain_digest': domain_input.digest,
            'request_id': request_id, 'run_id': run_id, 'actor_session_id': actor_session_id,
            'assignment_revision': assignment_revision, 'decision_nonce_hash': decision_nonce_hash,
            'requested_at': requested_at.isoformat(), 'expires_at': expires_at.isoformat()}))

    @property
    def digest(self):
        return hashlib.sha256(self.canonical_request).hexdigest()

    @property
    def authority(self):
        return 'NONE'

    def to_dict(self):
        return json.loads(self.canonical_request)


@dataclass(frozen=True, slots=True)
class PortableRearmOperation:
    """Closed policy5 input; the same Core exact-owner warrant still decides."""
    canonical_operation: bytes = field(repr=False)

    def __post_init__(self):
        raw = self.canonical_operation
        require(type(raw) is bytes and 0 < len(raw) <= 65536, 'PORTABLE_REARM_OPERATION_BYTES')
        try:
            value = json.loads(raw)
            require(canonical_json_bytes(value) == raw, 'PORTABLE_REARM_OPERATION_CANONICAL')
        except (TypeError, ValueError, RecursionError):
            require(False, 'PORTABLE_REARM_OPERATION_CANONICAL')
        require(type(value) is dict and set(value) == {'operation_class', 'target_fingerprint',
                'expected_target_revision', 'payload'} and value['operation_class'] == PORTABLE_REARM_CLASS,
                'PORTABLE_REARM_OPERATION_SHAPE')
        payload = value['payload']
        require(type(payload) is dict and set(payload) == {'schema', 'tool', 'workspace', 'task_id', 'session_id',
                'principal_session_id', 'policy_epoch', 'target_binding_digest', 'domain_input', 'request'}
                and payload['schema'] == PORTABLE_REARM_SCHEMA and payload['tool'] == 'rearm_demo',
                'PORTABLE_REARM_OPERATION_SHAPE')
        for name in ('workspace', 'task_id', 'session_id'):
            opaque_id(payload[name], 'rearm ' + name)
        for name in ('principal_session_id', 'target_binding_digest'):
            _rearm_root(payload[name])
        domain = PortableRearmDomainInput(canonical_json_bytes(payload['domain_input']))
        facts = domain.to_dict()
        request = PortableRearmRequest(canonical_json_bytes(payload['request']))
        owner = request.to_dict()
        binding = facts['binding']
        fixed = TargetBinding(**{**binding, 'scope': OwnerScope(**binding['scope'])})
        require(payload['workspace'] == binding['workspace']
                and payload['target_binding_digest'] == fixed.digest()
                and value['target_fingerprint'] == 'sha256:' + domain.state_root
                and value['expected_target_revision'] == facts['target_revision']
                and type(payload['policy_epoch']) is int and payload['policy_epoch'] == facts['epoch'],
                'PORTABLE_REARM_OPERATION_BINDING')
        require(owner['domain_digest'] == domain.digest
                and owner['actor_session_id'] == payload['principal_session_id']
                and owner['run_id'] not in {receipt['run_id'] for receipt in facts['inventory']['receipts']},
                'PORTABLE_REARM_REQUEST_BINDING')

    @classmethod
    def parse(cls, value):
        require(type(value) is dict, 'PORTABLE_REARM_OPERATION_SHAPE')
        return cls(canonical_json_bytes(value))

    @classmethod
    def create(cls, *, workspace, task_id, session_id, principal_session_id, policy_epoch,
               target_binding_digest, target_revision, domain_input, request):
        require(type(domain_input) is PortableRearmDomainInput and type(request) is PortableRearmRequest,
                'PORTABLE_REARM_TYPED_FACTS')
        return cls.parse({'operation_class': PORTABLE_REARM_CLASS,
            'target_fingerprint': 'sha256:' + domain_input.state_root, 'expected_target_revision': target_revision,
            'payload': {'schema': PORTABLE_REARM_SCHEMA, 'tool': 'rearm_demo', 'workspace': workspace,
                'task_id': task_id, 'session_id': session_id, 'principal_session_id': principal_session_id,
                'policy_epoch': policy_epoch, 'target_binding_digest': target_binding_digest,
                'domain_input': domain_input.to_dict(), 'request': request.to_dict()}})

    @property
    def domain_input(self):
        return PortableRearmDomainInput(canonical_json_bytes(self.to_dict()['payload']['domain_input']))

    @property
    def request(self):
        return PortableRearmRequest(canonical_json_bytes(self.to_dict()['payload']['request']))

    @property
    def digest(self):
        return 'sha256:' + hashlib.sha256(self.canonical_operation).hexdigest()

    @property
    def authority(self):
        return 'NONE'

    def to_dict(self):
        return json.loads(self.canonical_operation)


def _portable_operation(value):
    require(type(value) is dict and type(value.get('operation_class')) is str, 'PORTABLE_OPERATION_SHAPE')
    codec = {PORTABLE_OPERATION_CLASS: PortableOperation, PORTABLE_REARM_CLASS: PortableRearmOperation}.get(value.get('operation_class'))
    require(codec is not None, 'PORTABLE_OPERATION_CLASS_DENIED')
    return codec.parse(value)


class CorePortableTarget:
    """One host-bound storage bridge; execution stays in the existing executor.

    No principal is issued here. The host supplies READ authority from the same
    Core. A fresh COMMIT acknowledgment from CoreToolRoute is separately needed
    for one synchronous attempt. Existing files must already be adopted.
    """
    def __init__(self, projection, store, *, executor, read_principal, clock):
        require(type(projection) is CoreTargetProjection and type(store) is PortableStateStore
                and type(executor) is PortableExecutor and executor._state is store
                and callable(clock), 'PORTABLE_CORE_ADAPTER_BINDING')
        projection.core.require(read_principal, Capability.READ, scope=projection.scope)
        layout = store._managed_layout
        require(type(layout) is tuple and len(layout) == 3
                and layout[1:] == (canonical_sha256(projection.scope), projection.registration_key),
                'PORTABLE_MANAGED_NAMESPACE_REQUIRED')
        self.projection, self.store, self.executor = projection, store, executor
        self._read_principal, self._clock = read_principal, clock
        self._projection, self._store, self._executor = projection, store, executor
        self._binding = projection.binding
        self._path, self._lock_path, self._layout = store._path, store._lock_path, layout

    def _require_config(self):
        # Pure configuration checks: this method may run inside a Core retry.
        require(self.projection is self._projection and self.store is self._store
                and self.executor is self._executor and self.executor._state is self.store
                and self.projection.binding == self._binding
                and self.store._path == self._path and self.store._lock_path == self._lock_path
                and self.store._managed_layout == self._layout
                and self._layout[1:] == (canonical_sha256(self.projection.scope), self.projection.registration_key),
                'PORTABLE_CORE_ADAPTER_BINDING')
        self.projection.core.require(self._read_principal, Capability.READ, scope=self.projection.scope)

    def require_route_binding(self, route):
        self._require_config()
        require(route.target_settlement is self.projection and route.executor is self
                and route.core is self.projection.core and route.runner is self.projection.runner
                and route.journal is self.projection.journal and route.liability is self.projection.liability
                and route.workspace == self.projection.workspace, 'PORTABLE_CORE_ADAPTER_BINDING')
        for name in ('probe', 'target_guard', 'verifier'):
            method = getattr(route, name)
            expected = CorePortableTarget.verify if name == 'verifier' else getattr(CorePortableTarget, name)
            require(type(method) is MethodType and method.__self__ is self and method.__func__ is expected,
                    'PORTABLE_CORE_ADAPTER_BINDING')

    def _read(self, callback):
        self._require_config()
        return self.projection.runner.run(TransactionContext(self._read_principal, Capability.READ), callback)

    def _now(self):
        now = self._clock()
        require(type(now) is datetime and now.tzinfo is not None and now.utcoffset() == timedelta(0),
                'PORTABLE_CLOCK_INVALID')
        return now

    @contextmanager
    def target_guard(self):
        self._require_config()
        with self.store.target_guard():
            entry = self.store._current_guard_entry()
            capture = self._capture_guard(entry) if entry.owns_outer_lock else None
            previous = getattr(self.store._held_lock, 'core_no_release_capture', None)
            self.store._held_lock.core_no_release_capture = capture
            try:
                yield
            finally:
                if previous is None:
                    del self.store._held_lock.core_no_release_capture
                else:
                    self.store._held_lock.core_no_release_capture = previous

    def _capture_guard(self, entry):
        entry.require_outer_owner(self.store)
        def read(tx):
            row, state = self.projection.load(tx)
            flight = state['in_flight']
            intent_revision, intent_bytes, consumption_digest, liability_id = 0, b'', '', ''
            if flight is not None:
                warrant = EffectWarrant.from_dict(flight['warrant'])
                intent_row, intent = self.projection.journal._load(tx, warrant)
                require(intent_row is not None, 'NO_RELEASE_CAPTURE_INTENT_REQUIRED')
                intent_revision, intent_bytes = intent_row.revision, canonical_json_bytes(intent)
                consumption_digest = canonical_sha256(self.projection.journal.ledger._receipt(warrant))
                liability_id = self.projection._liability_entry(tx, warrant, None)
            return _PortableGuardCapture(self, entry, row.revision, canonical_json_bytes(state),
                intent_revision, intent_bytes, consumption_digest, liability_id, _NO_RELEASE_ISSUER)
        return self._read(read)

    def probe(self):
        self._require_config()
        observed = self.store.observe_guarded_inventory()
        require(observed.guard_fingerprint == self._binding.guard_fingerprint, 'PORTABLE_TARGET_GUARD_BINDING')
        def read(tx):
            from runtime.mission.tools import TargetSnapshot
            _row, state = self.projection.load(tx)
            require(state['schema'] == REGISTERED_HEAD, 'TARGET_PHYSICAL_ADOPTION_REQUIRED')
            require((state['state_root'], state['resources_root'], state['receipts_root'])
                    == (observed.state_root, observed.resources_root, observed.receipts_root), 'PORTABLE_TARGET_STATE_DRIFT')
            return TargetSnapshot('sha256:' + observed.state_root, state['target_revision'],
                                  DecisionDependencyRoot((self._binding.evidence(),)))
        return self._read(read)

    def __call__(self, *args, **kwargs):
        require(False, 'PORTABLE_RELEASE_PORT_REQUIRED')

    def _rearm_snapshot(self, query, *, flight_warrant=None):
        self._require_config()
        template = _rearm_template(query)
        require(self.store._initial_resources == default_mock_resources(), 'PORTABLE_REARM_FIXED_TEMPLATE')
        observed = self.store.observe_guarded_inventory()
        require(observed.guard_fingerprint == self._binding.guard_fingerprint, 'PORTABLE_TARGET_GUARD_BINDING')
        inventory = json.loads(observed.canonical_state)
        resources, receipts = _inventory(inventory)
        relevant = _rearm_consumed(query, resources, receipts)
        def read(tx):
            row, state, histories = self.projection._details(tx)
            require(state['schema'] == REGISTERED_HEAD, 'TARGET_PHYSICAL_ADOPTION_REQUIRED')
            flight = state['in_flight']
            if flight_warrant is None:
                require(flight is None, 'PORTABLE_REARM_UNSETTLED_TARGET')
            else:
                require(type(flight_warrant) is EffectWarrant and type(flight) is dict
                        and flight['phase'] == 'STARTED' and flight['warrant'] == flight_warrant.to_dict()
                        and flight['warrant_digest'] == flight_warrant.digest()
                        and flight['write_observation'] is None and flight['ack'] is None,
                        'PORTABLE_REARM_CURRENT_START')
            governor = self.projection.journal.governor
            current = governor._load(tx)
            governor._epoch(current, current['epoch'])
            governor._clock(current, governor._now())
            require(current['kill'] is False, 'KILL_SWITCH')
            allowed = set() if flight_warrant is None else {flight_warrant.risk_reservation_id}
            require({key for key, entry in current['reservations'].items() if entry['state'] == 'UNKNOWN'} <= allowed,
                    'UNRESOLVED_INTENT')
            rows = tx.scan(RecordKind.OPERATION, limit=1024)
            require(len(rows) < 1024, 'TARGET_HISTORY_SCAN_QUOTA')
            unknown = [entry.payload for entry in rows if entry.payload.get('schema') in INTENT_KINDS
                       and entry.payload.get('resolution') is None]
            require(all(flight_warrant is not None and entry.get('warrant_digest') == flight_warrant.digest()
                        for entry in unknown), 'UNRESOLVED_INTENT')
            require((state['state_root'], state['resources_root'], state['receipts_root'])
                    == (observed.state_root, observed.resources_root, observed.receipts_root), 'PORTABLE_TARGET_STATE_DRIFT')
            releases = {}
            for history in histories.values():
                if history['schema'] != PHYSICAL_HISTORY:
                    continue
                warrant = EffectWarrant.from_dict(history['warrant'])
                _intent_row, intent = self.projection.journal._load(tx, warrant)
                operation = PortableOperation.parse(intent['operation'])
                pack = operation.domain_input.to_dict()
                proposal, evidence = pack['proposal'], pack['evidence']['resource']
                if (proposal['target_resource_type'], proposal['target_resource_id'], evidence['region']) == (
                        str(query.resource_type), query.resource_id, query.region):
                    digest = history['write_observation']['receipt_digest']
                    require(digest not in releases, 'PORTABLE_REARM_RELEASE_HISTORY')
                    releases[digest] = (warrant, operation.to_dict(), history['write_observation'])
            require(set(releases) == {receipt.receipt_hash for receipt in relevant}
                    and len(releases) == len(relevant), 'PORTABLE_REARM_COMPLETE_CORE_HISTORY')
            return row.revision - (flight_warrant is not None), state, current['epoch'], releases
        revision, state, epoch, releases = self._read(read)
        proofs = []
        for receipt in relevant:
            warrant, operation, historical_write = releases[receipt.receipt_hash]
            original = PortableOperation.parse(operation).domain_input.to_dict()['inventory']
            before_resources, before_receipts = _inventory(original)
            require(before_resources.pop((query.resource_type, query.resource_id, query.region), None) == template
                    and receipt.idempotency_key not in before_receipts, 'PORTABLE_REARM_RELEASE_HISTORY')
            before_receipts[receipt.idempotency_key] = receipt
            candidate = _canonical_inventory_bytes(self.store._payload(before_resources, before_receipts))
            checked = self.candidate_observation(operation, warrant, candidate, observed.guard_fingerprint)
            require(checked.to_dict() == historical_write, 'PORTABLE_REARM_RELEASE_HISTORY')
            proofs.append(self.store.verify(receipt, verified_at=self._now()))
        domain = PortableRearmDomainInput(canonical_json_bytes({
            'schema': PORTABLE_REARM_INPUT, 'binding': asdict(self._binding), 'head_revision': revision,
            'generation': state['generation'], 'target_revision': state['target_revision'],
            'history_digest': state['history_digest'], 'epoch': epoch, 'query': query.model_dump(mode='json'),
            'template_version': PORTABLE_REARM_TEMPLATE, 'template': template.model_dump(mode='json'),
            'template_digest': canonical_sha256({'schema': PORTABLE_REARM_TEMPLATE, 'resource': template.model_dump(mode='json')}),
            'release_receipt_hashes': sorted(receipt.receipt_hash for receipt in relevant), 'inventory': inventory,
            'state_root': observed.state_root, 'resources_root': observed.resources_root, 'receipts_root': observed.receipts_root}))
        return domain, tuple(proofs)

    def prepare_rearm(self, query):
        """Read-only host preparation under the existing named target guard."""
        return self._rearm_snapshot(query)[0]

    def _domain_projection(self, operation, warrant):
        parsed = PortableOperation.parse(operation)
        require(type(warrant) is EffectWarrant and parsed.digest == warrant.operation_hash
                and warrant.operation_class == PORTABLE_OPERATION_CLASS
                and warrant.target_fingerprint == operation['target_fingerprint']
                and warrant.expected_target_revision == operation['expected_target_revision']
                and warrant.authority_scope.monetary_ceiling.amount == 0
                and warrant.authority_scope.monetary_ceiling.currency == 'USD'
                and warrant.money_reservation_id == 'NONE' and warrant.risk_reservation_id != 'NONE',
                'PORTABLE_WARRANT_BINDING')
        pack = parsed.domain_input.to_dict()
        proposal = RemediationProposal.model_validate(pack['proposal'])
        evidence = ResourceEvidence.model_validate(pack['evidence'])
        request = LocalApprovalRequestRecord.model_validate(pack['request'])
        # A deterministic domain projection of the same Core decision. These
        # values do not authorize a managed Store without its live Core port.
        approval = LocalApprovalDecisionRecord.create(request, decision=ApprovalDecision.APPROVED,
                                                       decided_at=warrant.issued_at)
        intent = LocalExecutionIntent.create(proposal, approval, registered_at=warrant.issued_at)
        return parsed, proposal, evidence, approval, intent

    def candidate_observation(self, operation, warrant, candidate, guard_fingerprint):
        self._require_config()
        if operation.get('operation_class') == PORTABLE_REARM_CLASS:
            return self._rearm_candidate_observation(operation, warrant, candidate, guard_fingerprint)
        parsed, proposal, evidence, approval, intent = self._domain_projection(operation, warrant)
        require(type(candidate) is bytes and 0 < len(candidate) <= 65536, 'PORTABLE_WRITE_CANDIDATE_BYTES')
        try:
            value = json.loads(candidate)
            require(_canonical_inventory_bytes(value) == candidate, 'PORTABLE_WRITE_CANDIDATE_CANONICAL')
            resources, receipts = _inventory(value)
        except (TypeError, ValueError, RecursionError):
            require(False, 'PORTABLE_WRITE_CANDIDATE_INVALID')
        original = parsed.domain_input
        before = original.to_dict()['inventory']
        before_resources, before_receipts = _inventory(before)
        key = (proposal.target_resource_type, proposal.target_resource_id, evidence.resource.region)
        expected_resources = dict(before_resources)
        require(expected_resources.pop(key, None) == evidence.resource, 'PORTABLE_WRITE_TARGET_BINDING')
        require(resources == expected_resources and set(receipts) == set(before_receipts) | {intent.idempotency_key}
                and all(receipts[identity] == receipt for identity, receipt in before_receipts.items()),
                'PORTABLE_WRITE_FULL_STATE_BINDING')
        receipt = receipts.get(intent.idempotency_key)
        require(receipt is not None, 'PORTABLE_WRITE_RECEIPT_REQUIRED')
        PortableStateStore._validate_execution_binding(proposal, evidence, approval, intent)
        require(receipt.run_id == intent.run_id and receipt.proposal_id == intent.proposal_id
                and receipt.proposal_hash == intent.proposal_hash and receipt.evidence_hash == intent.evidence_hash
                and receipt.decision_hash == approval.decision_hash and receipt.intent_hash == intent.intent_hash
                and receipt.operation_type is proposal.operation_type
                and receipt.target_resource_type is proposal.target_resource_type
                and receipt.target_resource_id == proposal.target_resource_id
                and receipt.before_resource == evidence.resource and receipt.after_resource is None
                and warrant.issued_at <= receipt.executed_at <= self._now()
                and receipt.executed_at < warrant.expires_at, 'PORTABLE_WRITE_RECEIPT_BINDING')
        require(guard_fingerprint == self._binding.guard_fingerprint, 'PORTABLE_TARGET_GUARD_BINDING')
        return TargetWriteObservation(self._binding.digest(), warrant.operation_hash, warrant.digest(),
            guard_fingerprint, original.state_root, original.resources_root, original.receipts_root,
            hashlib.sha256(candidate).hexdigest(), hashlib.sha256(_canonical_inventory_bytes(value['resources'])).hexdigest(),
            hashlib.sha256(_canonical_inventory_bytes(value['receipts'])).hexdigest(),
            canonical_sha256(intent.idempotency_key), receipt.receipt_hash)

    def _rearm_projection(self, operation, warrant):
        parsed = PortableRearmOperation.parse(operation)
        require(type(warrant) is EffectWarrant and parsed.digest == warrant.operation_hash
                and warrant.operation_class == PORTABLE_REARM_CLASS
                and warrant.target_fingerprint == operation['target_fingerprint']
                and warrant.expected_target_revision == operation['expected_target_revision']
                and warrant.authority_scope.monetary_ceiling.amount == 0
                and warrant.authority_scope.monetary_ceiling.currency == 'USD'
                and warrant.money_reservation_id == 'NONE' and warrant.risk_reservation_id != 'NONE',
                'PORTABLE_REARM_WARRANT_BINDING')
        request, domain = parsed.request.to_dict(), parsed.domain_input.to_dict()
        require(domain['binding'] == asdict(self._binding)
                and request['decision_nonce_hash'] == canonical_sha256(warrant.nonce)
                and _rearm_time(request['requested_at']) <= warrant.issued_at < _rearm_time(request['expires_at'])
                and warrant.expires_at <= _rearm_time(request['expires_at']), 'PORTABLE_REARM_WARRANT_REQUEST_BINDING')
        return parsed

    def _rearm_candidate_observation(self, operation, warrant, candidate, guard_fingerprint):
        parsed = self._rearm_projection(operation, warrant)
        require(type(candidate) is bytes and 0 < len(candidate) <= 65536, 'PORTABLE_REARM_CANDIDATE_BYTES')
        try:
            value = json.loads(candidate)
            require(_canonical_inventory_bytes(value) == candidate, 'PORTABLE_REARM_CANDIDATE_CANONICAL')
            resources, receipts = _inventory(value)
        except (TypeError, ValueError, RecursionError):
            require(False, 'PORTABLE_REARM_CANDIDATE_INVALID')
        domain = parsed.domain_input
        facts = domain.to_dict()
        before_resources, before_receipts = _inventory(facts['inventory'])
        query = ResourceQuery.model_validate(facts['query'])
        template = _rearm_template(query)
        key = (query.resource_type, query.resource_id, query.region)
        require(key not in before_resources, 'PORTABLE_REARM_RESOURCE_PRESENT')
        expected = {**before_resources, key: template}
        require(resources == expected and receipts == before_receipts
                and value['receipts'] == facts['inventory']['receipts'], 'PORTABLE_REARM_EXACT_RESOURCE_ONLY_DELTA')
        require(guard_fingerprint == self._binding.guard_fingerprint, 'PORTABLE_TARGET_GUARD_BINDING')
        return TargetRearmWriteObservation(self._binding.digest(), warrant.operation_hash, warrant.digest(),
            guard_fingerprint, domain.state_root, domain.resources_root, domain.receipts_root,
            hashlib.sha256(candidate).hexdigest(), hashlib.sha256(_canonical_inventory_bytes(value['resources'])).hexdigest(),
            hashlib.sha256(_canonical_inventory_bytes(value['receipts'])).hexdigest(), domain.digest,
            parsed.request.digest, facts['template_digest'])

    def dispatch(self, operation, warrant, limits, release):
        self._require_config()
        parsed = _portable_operation(operation)
        require(type(release) is CorePortableWriteRelease and release.adapter is self
                and release.warrant == warrant and release.operation == parsed
                and release.limits == limits, 'PORTABLE_RELEASE_PORT_REQUIRED')
        if type(parsed) is PortableRearmOperation:
            self._rearm_projection(operation, warrant)
            domain, proofs = self._rearm_snapshot(ResourceQuery.model_validate(parsed.domain_input.to_dict()['query']),
                                                 flight_warrant=warrant)
            require(domain == parsed.domain_input, 'PORTABLE_REARM_PREPARATION_CHANGED')
            with self.store._core_write_lifetime(release):
                applied = self.executor.rearm(ResourceQuery.model_validate(domain.to_dict()['query']), verifications=proofs)
            require(applied is True, 'PORTABLE_REARM_EXECUTOR_NO_EFFECT')
            candidate = release._write_observation
            require(type(candidate) is TargetRearmWriteObservation and release._consumed, 'PORTABLE_REARM_WRITE_ACK_REQUIRED')
            observed = self.store.observe_guarded_inventory()
            require((observed.state_root, observed.resources_root, observed.receipts_root, observed.guard_fingerprint)
                    == (candidate.after_root, candidate.resources_root, candidate.receipts_root, candidate.guard_fingerprint),
                    'PORTABLE_REARM_EXECUTION_READBACK')
            digest = candidate.ack_digest()
            return TargetExecutionAck(warrant.operation_hash, warrant.digest(), self._binding.digest(),
                observed.state_root, 'portable-rearm-ack-' + digest, digest)
        _parsed, proposal, evidence, approval, intent = self._domain_projection(operation, warrant)
        with self.store._core_write_lifetime(release):
            receipt = self.executor.execute(proposal=proposal, evidence=evidence, approval=approval, intent=intent)
        observed = self.store.observe_guarded_inventory()
        digest = canonical_sha256({'schema': 'aioa.portable-executor-ack.v1', 'receipt': receipt.receipt_hash,
                                   'state_root': observed.state_root, 'warrant': warrant.digest()})
        return TargetExecutionAck(warrant.operation_hash, warrant.digest(), self._binding.digest(),
                                 observed.state_root, 'portable-ack-' + digest, digest)

    def verify(self, operation, warrant):
        self._require_config()
        if operation.get('operation_class') == PORTABLE_REARM_CLASS:
            return self._verify_rearm(operation, warrant)
        _parsed, _proposal, _evidence, _approval, intent = self._domain_projection(operation, warrant)
        receipt = self.executor.get_receipt(intent.idempotency_key)
        if receipt is None:
            return self._verify_no_release(operation, warrant)
        require(type(receipt) is LocalExecutionReceipt, 'PORTABLE_DURABLE_RECEIPT_REQUIRED')
        verified = self.store.verify(receipt, verified_at=self._now())
        observed = self.store.observe_guarded_inventory()
        candidate = self.candidate_observation(operation, warrant, observed.canonical_state, observed.guard_fingerprint)
        require(candidate.receipt_digest == receipt.receipt_hash, 'PORTABLE_READBACK_RECEIPT_BINDING')
        readback = canonical_sha256({'schema': 'aioa.portable-complete-readback.v1',
            'write_observation': candidate.to_dict(), 'verification': verified.model_dump(mode='json')})
        receipt_id = 'portable-receipt-' + receipt.receipt_hash
        resolution = Reconciliation(warrant.operation_hash, Applied(receipt_id),
            EvidenceRef(receipt_id, 'receipt', 'sha256:' + receipt.receipt_hash, 'portable-v1'),
            EvidenceRef('portable-readback-' + readback, 'independent-readback', 'sha256:' + readback, 'portable-v1'))
        def read(tx):
            row, state = self.projection.load(tx)
            flight = state['in_flight']
            require(flight is not None and flight['phase'] == 'RELEASED'
                    and flight['warrant_digest'] == warrant.digest()
                    and flight['write_observation'] == candidate.to_dict(), 'PORTABLE_READBACK_RELEASE_BINDING')
            target = TargetObservation(self.projection.scope, self.projection.workspace,
                self._binding.target_id, self._binding.incarnation, row.revision, state['generation'],
                warrant.operation_hash, candidate.before_root, candidate.after_root, candidate.resources_root,
                candidate.receipts_root, candidate.guard_fingerprint, receipt_id, receipt.receipt_hash, readback)
            return VerifiedTargetSettlement(resolution, target)
        return self._read(read)


    def _verify_rearm(self, operation, warrant):
        self._rearm_projection(operation, warrant)
        def read(tx):
            row, state = self.projection._flight(tx, warrant)
            flight = state['in_flight']
            require(flight['phase'] == 'RELEASED' and flight['ack'] is not None,
                    'PORTABLE_REARM_DURABLE_EXECUTION_ACK_REQUIRED')
            return row.revision, state['generation'], flight['write_observation'], flight['ack']
        revision, generation, write, durable_ack = self._read(read)
        acknowledgment = TargetExecutionAck(**durable_ack)
        observed = self.store.observe_guarded_inventory()
        candidate = self._rearm_candidate_observation(operation, warrant, observed.canonical_state, observed.guard_fingerprint)
        require(candidate.to_dict() == write, 'PORTABLE_REARM_READBACK_RELEASE_BINDING')
        candidate.require_ack(acknowledgment)
        receipt = EvidenceRef(acknowledgment.ack_id, 'receipt', 'sha256:' + acknowledgment.ack_digest, 'portable-rearm-core-ack-v1')
        readback = EvidenceRef('portable-rearm-readback-' + candidate.readback_digest(),
                              'independent-readback', 'sha256:' + candidate.readback_digest(), 'portable-rearm-v1')
        resolution = Reconciliation(warrant.operation_hash, Applied(acknowledgment.ack_id), receipt, readback)
        target = TargetObservation(self.projection.scope, self.projection.workspace, self._binding.target_id,
            self._binding.incarnation, revision, generation, warrant.operation_hash, candidate.before_root,
            candidate.after_root, candidate.resources_root, candidate.receipts_root, candidate.guard_fingerprint,
            acknowledgment.ack_id, acknowledgment.ack_digest, candidate.readback_digest())
        return VerifiedRearmTargetSettlement(resolution, target, candidate, acknowledgment)

    def _verify_no_release(self, operation, warrant):
        capture = getattr(self.store._held_lock, 'core_no_release_capture', None)
        require(type(capture) is _PortableGuardCapture, 'NO_RELEASE_FRESH_GUARD_REQUIRED')
        capture.require_live(self)
        state = json.loads(capture.head_bytes)
        flight = state['in_flight']
        require(state['schema'] == REGISTERED_HEAD and type(flight) is dict
                and flight['phase'] == 'STARTED' and flight['write_observation'] is None
                and flight['ack'] is None and flight['warrant_digest'] == warrant.digest()
                and flight['warrant'] == warrant.to_dict(), 'NO_RELEASE_CAPTURED_START_REQUIRED')
        def checked(tx):
            row, current = self.projection.load(tx)
            intent_row, intent = self.projection.journal._load(tx, warrant)
            require(row.revision == capture.head_revision and canonical_json_bytes(current) == capture.head_bytes
                    and intent_row is not None and intent_row.revision == capture.intent_revision
                    and canonical_json_bytes(intent) == capture.intent_bytes,
                    'NO_RELEASE_CAPTURE_CHANGED')
        self._read(checked)
        observed = self.store.observe_guarded_inventory()
        require(observed.guard_fingerprint == self._binding.guard_fingerprint
                and (observed.state_root, observed.resources_root, observed.receipts_root)
                == (state['state_root'], state['resources_root'], state['receipts_root']),
                'NO_RELEASE_COMPLETE_ROOT_DRIFT')
        certificate = FencedNoReleaseCertificate(self._binding.digest(), warrant.operation_hash,
            warrant.digest(), capture.head_revision, state['generation'], capture.intent_revision,
            state['history_digest'], hashlib.sha256(capture.head_bytes).hexdigest(),
            hashlib.sha256(capture.intent_bytes).hexdigest(), capture.consumption_digest, capture.liability_id,
            observed.state_root, observed.resources_root, observed.receipts_root, observed.guard_fingerprint)
        resolution = Reconciliation(warrant.operation_hash, NotApplied(), certificate.receipt(), certificate.readback())
        target = TargetObservation(self.projection.scope, self.projection.workspace,
            self._binding.target_id, self._binding.incarnation, capture.head_revision, state['generation'],
            warrant.operation_hash, observed.state_root, observed.state_root, observed.resources_root,
            observed.receipts_root, observed.guard_fingerprint, certificate.receipt().evidence_id,
            certificate.digest(), certificate.readback_digest())
        witness = _PortableNoReleaseWitness(capture, certificate, _NO_RELEASE_ISSUER)
        return VerifiedNoReleaseSettlement(resolution, target, certificate, witness)


_START_ACK_ISSUER = object()
_WRITE_ACK_ISSUER = object()


class _PortableStartAck:
    """An in-memory return value, issued only in the Core route's fresh START.

    The transaction runner returns it only after COMMIT acknowledgment. It is
    never stored or reconstructed from STARTED. A lost ACK loses this value.
    Private constructors assume sealed host code, not a hostile Python owner.
    """
    __slots__ = ('route', 'taken', 'warrant_digest')

    def __init__(self, route, warrant_digest, issuer):
        require(issuer is _START_ACK_ISSUER, 'PORTABLE_START_ACK_ISSUER')
        self.route, self.warrant_digest, self.taken = route, warrant_digest, False

    @classmethod
    def issue_in_transaction(cls, route, tx, warrant):
        require(cls is _PortableStartAck and tx.context.purpose is Capability.COMMIT,
                'PORTABLE_START_ACK_CONTEXT')
        route.core.require(tx.context.principal, Capability.COMMIT, scope=route.scope)
        require(type(route.executor) is CorePortableTarget, 'PORTABLE_START_ACK_CONTEXT')
        _row, state = route.target_settlement._flight(tx, warrant)
        require(state['in_flight']['phase'] == 'STARTED'
                and state['in_flight']['write_observation'] is None, 'PORTABLE_START_ACK_CONTEXT')
        return cls(route, warrant.digest(), _START_ACK_ISSUER)

    def take(self, route, warrant):
        require(not self.taken and self.route is route and self.warrant_digest == warrant.digest(),
                'PORTABLE_START_ACK_REQUIRED')
        self.taken = True


class _PortableWriteAck:
    __slots__ = ('consumed', 'observation', 'release')

    def __init__(self, release, observation, issuer):
        require(issuer is _WRITE_ACK_ISSUER and type(observation) in (TargetWriteObservation, TargetRearmWriteObservation),
                'PORTABLE_WRITE_ACK_ISSUER')
        self.release, self.observation, self.consumed = release, observation, False


class CorePortableWriteRelease:
    """One synchronous, thread/guard-bound bridge to the SAME Core decision.

    No callable/boolean/serialized receipt is accepted as a permit. The
    in-memory start and write ACKs never survive restart or grant replay.
    """
    def __init__(self, route, principal, session_id, warrant, operation, completion, limits, ack, cancel):
        require(type(ack) is _PortableStartAck, 'PORTABLE_START_ACK_REQUIRED')
        route.core.require(principal, Capability.COMMIT, scope=route.scope)
        require(type(route.executor) is CorePortableTarget, 'PORTABLE_CORE_ADAPTER_REQUIRED')
        route.executor.require_route_binding(route)
        ack.take(route, warrant)
        self.route, self.principal, self.session_id = route, principal, session_id
        self.warrant, self.operation = warrant, _portable_operation(operation)
        require(route.bound_variant.operation_class == self.operation.to_dict()['operation_class'],
                'PORTABLE_WRITE_PORT_OPERATION_BINDING')
        self.completion, self.limits, self.adapter = completion, limits, route.executor
        self.cancel = cancel
        self._thread, self._pid = get_ident(), getpid()
        self._lock_lifetime = self.adapter.store._current_guard_entry()._lifetime
        self._guard = getattr(self.adapter.store._held_lock, 'target_binding', None)
        self._active, self._attempted, self._consumed = True, False, False
        self._write_observation = None
        self.require_store(self.adapter.store)

    @classmethod
    def from_live_ack(cls, route, principal, session_id, warrant, operation, completion, limits, ack, *, cancel=None):
        require(cls is CorePortableWriteRelease, 'PORTABLE_RELEASE_PORT_REQUIRED')
        return cls(route, principal, session_id, warrant, operation, completion, limits, ack, cancel)

    def require_live_binding(self, store):
        """Pure binding check; never read the filesystem inside a Core retry."""
        require(self._active and get_ident() == self._thread and getpid() == self._pid
                and store is self.adapter.store and type(self._guard) is dict
                and getattr(store._held_lock, 'target_binding', None) is self._guard
                and getattr(store._held_lock, 'exclusive', None) is True
                and self._guard.get('failed') is False
                and self._guard.get('identity') == self._lock_lifetime._identity,
                'PORTABLE_LIVE_WRITE_PORT_REQUIRED')
        self._lock_lifetime.require_live(store)
        self.adapter.require_route_binding(self.route)
        self.route.core.require(self.principal, Capability.COMMIT, scope=self.route.scope)

    def require_store(self, store):
        self.require_live_binding(store)
        store._check_target_guard()

    def _cancel_check(self):
        require(self.cancel is None or self.cancel.cancelled is False, 'PORTABLE_CANCELLED')

    def authorize_write(self, store, before, candidate):
        self.require_store(store)
        require(not self._attempted and type(before) is PortableInventoryObservation,
                'PORTABLE_WRITE_ALREADY_ATTEMPTED')
        self._attempted = True
        self._cancel_check()
        pack = self.operation.domain_input
        require(before.canonical_state == _canonical_inventory_bytes(pack.to_dict()['inventory'])
                and before.guard_fingerprint == self.adapter._binding.guard_fingerprint,
                'PORTABLE_WRITE_PRESTATE_BINDING')
        observed = self.adapter.candidate_observation(self.operation.to_dict(), self.warrant,
                                                       candidate, before.guard_fingerprint)
        from runtime.mission.tools import TargetSnapshot, ToolDispatchLimits
        snapshot = TargetSnapshot('sha256:' + before.state_root,
            self.operation.to_dict()['expected_target_revision'],
            DecisionDependencyRoot((self.adapter._binding.evidence(),)))
        operation = self.operation.to_dict()
        def release(tx):
            grant, _context, _graph, _trace = self.route._check(tx, self.session_id, self.warrant,
                                                              operation, self.completion, snapshot)
            require(ToolDispatchLimits(grant.deadline_seconds, grant.output_bytes, grant.egress) == self.limits,
                    'PORTABLE_RESOURCE_GRANT_MISMATCH')
            self.route.target_settlement.before_release_in_transaction(
                tx, self.warrant, operation, snapshot, write_observation=observed)
            return _PortableWriteAck(self, observed, _WRITE_ACK_ISSUER)
        return self.route._run(self.principal, Capability.COMMIT, release)

    def consume_write_ack(self, acknowledgment, store, before, candidate):
        self.require_store(store)
        self._cancel_check()
        require(self._attempted and not self._consumed and type(acknowledgment) is _PortableWriteAck
                and acknowledgment.release is self and not acknowledgment.consumed
                and acknowledgment.observation.before_root == before.state_root
                and acknowledgment.observation.after_root == hashlib.sha256(candidate).hexdigest(),
                'PORTABLE_FRESH_WRITE_ACK_REQUIRED')
        acknowledgment.consumed = True
        self._consumed = True
        self._write_observation = acknowledgment.observation

    def close(self):
        self._active = False


_NO_RELEASE_ISSUER = object()


@dataclass(frozen=True, slots=True)
class _PortableGuardCapture(_NonTransferableGuardValue):
    adapter: object
    entry: _PortableGuardEntry
    head_revision: int
    head_bytes: bytes
    intent_revision: int
    intent_bytes: bytes
    consumption_digest: str
    liability_id: str
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self):
        require(self._issuer is _NO_RELEASE_ISSUER and type(self.adapter) is CorePortableTarget
                and type(self.entry) is _PortableGuardEntry, 'NO_RELEASE_CAPTURE_ISSUER')

    def require_live(self, adapter):
        require(adapter is self.adapter and getattr(adapter.store._held_lock, 'core_no_release_capture', None) is self,
                'NO_RELEASE_CURRENT_CAPTURE_REQUIRED')
        self.entry.require_outer_owner(adapter.store)
        require(getattr(adapter.store._held_lock, 'write_release', None) is None, 'NO_RELEASE_ACTIVE_WRITE_PORT')
        adapter._require_config()


@dataclass(frozen=True, slots=True)
class _PortableNoReleaseWitness(_NonTransferableGuardValue):
    capture: _PortableGuardCapture
    certificate: FencedNoReleaseCertificate
    _issuer: object = field(repr=False, compare=False)

    def __post_init__(self):
        require(self._issuer is _NO_RELEASE_ISSUER and type(self.capture) is _PortableGuardCapture
                and type(self.certificate) is FencedNoReleaseCertificate, 'NO_RELEASE_WITNESS_ISSUER')

    def require_live(self, verified, *, projection=None, warrant=None):
        # Pure reference/process/configuration checks only; no imports or I/O.
        capture, certificate = self.capture, self.certificate
        adapter = capture.adapter
        capture.require_live(adapter)
        require(verified.certificate is certificate
                and certificate.binding_digest == adapter._binding.digest()
                and certificate.head_digest == hashlib.sha256(capture.head_bytes).hexdigest()
                and certificate.intent_digest == hashlib.sha256(capture.intent_bytes).hexdigest()
                and certificate.expected_head_revision == capture.head_revision
                and certificate.intent_revision == capture.intent_revision
                and certificate.consumption_digest == capture.consumption_digest
                and certificate.liability_id == capture.liability_id, 'NO_RELEASE_LIVE_PROOF_BINDING')
        if projection is not None:
            require(projection is adapter.projection and type(warrant) is EffectWarrant
                    and certificate.warrant_digest == warrant.digest()
                    and certificate.operation_digest == warrant.operation_hash, 'NO_RELEASE_CORE_BINDING')
