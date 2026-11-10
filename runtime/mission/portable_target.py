"""Exact managed Portable operations through the existing Core and executor.

Fact codecs grant no authority. One live CoreToolRoute acknowledgment, current
owner approval, an adopted target and its held guard bind the synchronous write.
No provider, product INIT/rearm or production Native activation occurs here.
"""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import get_ident
from types import MethodType

from nonzero_cloudops.adapters.portable import (
    _RESOURCE_ADAPTER,
    PortableExecutor,
    PortableInventoryObservation,
    PortableStateStore,
    _canonical_inventory_bytes,
)
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
)
from nonzero_cloudops.models.public_enums import AuthorityGate

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import opaque_id
from lab.archaioa.outcome import Applied
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import TransactionContext
from runtime.mission.liability import Reconciliation
from runtime.mission.target_projection import REGISTERED_HEAD, CoreTargetProjection
from runtime.mission.target_settlement import (
    TargetExecutionAck,
    TargetObservation,
    TargetWriteObservation,
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
            yield

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

    def dispatch(self, operation, warrant, limits, release):
        self._require_config()
        require(type(release) is CorePortableWriteRelease and release.adapter is self
                and release.warrant == warrant and release.operation == PortableOperation.parse(operation)
                and release.limits == limits, 'PORTABLE_RELEASE_PORT_REQUIRED')
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
        _parsed, _proposal, _evidence, _approval, intent = self._domain_projection(operation, warrant)
        receipt = self.executor.get_receipt(intent.idempotency_key)
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
        require(issuer is _WRITE_ACK_ISSUER and type(observation) is TargetWriteObservation,
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
        self.warrant, self.operation = warrant, PortableOperation.parse(operation)
        self.completion, self.limits, self.adapter = completion, limits, route.executor
        self.cancel = cancel
        self._thread = get_ident()
        self._guard = getattr(self.adapter.store._held_lock, 'target_binding', None)
        self._active, self._attempted, self._consumed = True, False, False
        self.require_store(self.adapter.store)

    @classmethod
    def from_live_ack(cls, route, principal, session_id, warrant, operation, completion, limits, ack, *, cancel=None):
        require(cls is CorePortableWriteRelease, 'PORTABLE_RELEASE_PORT_REQUIRED')
        return cls(route, principal, session_id, warrant, operation, completion, limits, ack, cancel)

    def require_store(self, store):
        require(self._active and get_ident() == self._thread and store is self.adapter.store
                and type(self._guard) is dict
                and getattr(store._held_lock, 'target_binding', None) is self._guard
                and getattr(store._held_lock, 'exclusive', None) is True, 'PORTABLE_LIVE_WRITE_PORT_REQUIRED')
        self.adapter.require_route_binding(self.route)
        self.route.core.require(self.principal, Capability.COMMIT, scope=self.route.scope)
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

    def close(self):
        self._active = False
