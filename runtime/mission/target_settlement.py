"""Immutable target observations and a host-bound, DB-only settlement port.

These values carry facts, never authority. The registered implementation must
verify complete target roots, held guard, incarnation and canonical Core CAS.
This protocol itself is not a physical target adapter or an INIT/rearm service.
"""
from dataclasses import asdict, dataclass, field
from typing import Protocol, runtime_checkable

from lab.archaioa.contracts import digest_id
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import opaque_id
from lab.archaioa.outcome import Applied, NotApplied

from runtime.core_admission import CoreAdmission, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.liability import Reconciliation
from runtime.mission.warrant import require

TARGET_SETTLEMENT_PROFILE = 'aioa.target-settlement.v1'


def _root(value):
    require(type(value) is str and len(value) == 64
            and all(character in '0123456789abcdef' for character in value), 'TARGET_OBSERVATION_DIGEST')


TARGET_BINDING_KIND = 'core-target-settlement-binding'


@dataclass(frozen=True, slots=True)
class TargetBinding:
    """Fixed host registration identity, committed by the existing warrant DDR.

    This only binds protocol participation. It is not a state high-water, proof
    of a held guard, approval, physical INIT or permission to execute.
    """
    scope: OwnerScope
    workspace: str
    target_id: str
    incarnation: str
    guard_fingerprint: str

    def __post_init__(self):
        require(type(self.scope) is OwnerScope, 'TARGET_BINDING_SCOPE')
        for value in (self.workspace, self.target_id, self.incarnation):
            opaque_id(value, 'target binding identity')
        _root(self.guard_fingerprint)

    def digest(self):
        return canonical_sha256({'schema': TARGET_SETTLEMENT_PROFILE, 'scope': self.scope.binding(),
            'workspace': self.workspace, 'target_id': self.target_id, 'incarnation': self.incarnation,
            'guard_fingerprint': self.guard_fingerprint})

    def evidence(self):
        return EvidenceRef('core-target-binding', TARGET_BINDING_KIND,
                           'sha256:' + self.digest(), 'target-binding-v1')

    def require_observation(self, observation):
        require(type(observation) is TargetObservation
                and observation.scope == self.scope and observation.workspace == self.workspace
                and observation.target_id == self.target_id and observation.incarnation == self.incarnation
                and observation.guard_fingerprint == self.guard_fingerprint, 'TARGET_OBSERVATION_BINDING')

    def require_ack(self, warrant, acknowledgment):
        require(type(acknowledgment) is TargetExecutionAck
                and acknowledgment.operation_digest == warrant.operation_hash
                and acknowledgment.warrant_digest == warrant.digest()
                and acknowledgment.binding_digest == self.digest(), 'TARGET_EXECUTION_ACK_BINDING')

    def require_write(self, warrant, observation):
        require(type(observation) is TargetWriteObservation
                and observation.binding_digest == self.digest()
                and observation.guard_fingerprint == self.guard_fingerprint
                and observation.operation_digest == warrant.operation_hash
                and observation.warrant_digest == warrant.digest(), 'TARGET_WRITE_OBSERVATION_BINDING')


    def require_rearm_write(self, warrant, observation):
        require(type(observation) is TargetRearmWriteObservation
                and observation.binding_digest == self.digest()
                and observation.guard_fingerprint == self.guard_fingerprint
                and observation.operation_digest == warrant.operation_hash
                and observation.warrant_digest == warrant.digest(), 'TARGET_REARM_WRITE_BINDING')


@dataclass(frozen=True, slots=True)
class TargetExecutionAck:
    """A synchronous executor ACK fact, never independent Applied evidence.

    The trusted host adapter constructs this outside SQL after executor return.
    Absence or ACK loss never grants another target attempt.
    """
    operation_digest: str
    warrant_digest: str
    binding_digest: str
    target_root: str
    ack_id: str
    ack_digest: str

    def __post_init__(self):
        digest_id(self.operation_digest, 'ack operation')
        digest_id(self.warrant_digest, 'ack warrant')
        for value in (self.binding_digest, self.target_root, self.ack_digest):
            _root(value)
        opaque_id(self.ack_id, 'ack identity')

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetObservation:
    """A per-call verifier observation; no mutable last-observation cache.

    expected_head_revision covers the whole current target record, including
    in-flight release/ACK changes; generation is the settled Core sequence.
    Root fields are commitments to complete collections, not resource samples.
    Their independent derivation and active-guard binding belong to the port.
    """
    scope: OwnerScope
    workspace: str
    target_id: str
    incarnation: str
    expected_head_revision: int
    generation: int
    operation_digest: str
    before_root: str
    after_root: str
    resources_root: str
    receipts_root: str
    guard_fingerprint: str
    receipt_id: str
    receipt_digest: str
    readback_digest: str

    def __post_init__(self):
        require(type(self.scope) is OwnerScope, 'TARGET_OBSERVATION_SCOPE')
        for value in (self.workspace, self.target_id, self.incarnation, self.receipt_id):
            opaque_id(value, 'target observation identity')
        require(type(self.expected_head_revision) is int and self.expected_head_revision >= 1
                and type(self.generation) is int and self.generation >= 0, 'TARGET_OBSERVATION_REVISION')
        digest_id(self.operation_digest, 'target operation')
        for value in (self.before_root, self.after_root, self.resources_root, self.receipts_root,
                      self.guard_fingerprint, self.receipt_digest, self.readback_digest):
            _root(value)


@dataclass(frozen=True, slots=True)
class VerifiedTargetSettlement:
    resolution: Reconciliation
    target: TargetObservation

    def __post_init__(self):
        require(type(self.resolution) is Reconciliation and type(self.target) is TargetObservation,
                'VERIFIED_TARGET_OBSERVATION_REQUIRED')
        require(self.target.operation_digest == self.resolution.operation_digest
                and self.target.receipt_id == self.resolution.receipt.evidence_id
                and self.target.receipt_digest == self.resolution.receipt.digest.removeprefix('sha256:')
                and self.target.readback_digest == self.resolution.readback.digest.removeprefix('sha256:'),
                'TARGET_RESOLUTION_EVIDENCE_BINDING')


@dataclass(frozen=True, slots=True)
class TargetWriteObservation:
    """Frozen complete pre/candidate roots at a physical write boundary.

    These host-observed facts are not a release permit. The existing Core must
    join them to its current owner, intent, target, job and one live attempt.
    No target I/O occurs while this value is used in a retried transaction.
    """
    binding_digest: str
    operation_digest: str
    warrant_digest: str
    guard_fingerprint: str
    before_root: str
    before_resources_root: str
    before_receipts_root: str
    after_root: str
    resources_root: str
    receipts_root: str
    receipt_key_digest: str
    receipt_digest: str

    def __post_init__(self):
        digest_id(self.operation_digest, 'physical operation')
        digest_id(self.warrant_digest, 'physical warrant')
        for name in ('binding_digest', 'guard_fingerprint', 'before_root', 'before_resources_root',
                     'before_receipts_root', 'after_root', 'resources_root', 'receipts_root',
                     'receipt_key_digest', 'receipt_digest'):
            _root(getattr(self, name))
        require(self.before_root != self.after_root
                and self.before_resources_root != self.resources_root
                and self.before_receipts_root != self.receipts_root, 'TARGET_WRITE_EFFECT_REQUIRED')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__),
                'TARGET_WRITE_OBSERVATION_SHAPE')
        return cls(**value)


@dataclass(frozen=True, slots=True)
class TargetRearmWriteObservation:
    """Closed resource-only delta; the receipt collection is byte-identical."""
    binding_digest: str
    operation_digest: str
    warrant_digest: str
    guard_fingerprint: str
    before_root: str
    before_resources_root: str
    before_receipts_root: str
    after_root: str
    resources_root: str
    receipts_root: str
    domain_digest: str
    request_digest: str
    template_digest: str

    def __post_init__(self):
        digest_id(self.operation_digest, 'rearm operation')
        digest_id(self.warrant_digest, 'rearm warrant')
        for name in ('binding_digest', 'guard_fingerprint', 'before_root', 'before_resources_root',
                     'before_receipts_root', 'after_root', 'resources_root', 'receipts_root',
                     'domain_digest', 'request_digest', 'template_digest'):
            _root(getattr(self, name))
        require(self.before_root != self.after_root and self.before_resources_root != self.resources_root
                and self.before_receipts_root == self.receipts_root, 'TARGET_REARM_RESOURCE_ONLY_DELTA')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__), 'TARGET_REARM_WRITE_SHAPE')
        return cls(**value)

    def ack_digest(self):
        return canonical_sha256({'schema': 'aioa.portable-rearm-executor-ack.v1', 'write_observation': self.to_dict()})

    def require_ack(self, acknowledgment):
        require(type(acknowledgment) is TargetExecutionAck
                and acknowledgment.operation_digest == self.operation_digest
                and acknowledgment.warrant_digest == self.warrant_digest
                and acknowledgment.binding_digest == self.binding_digest
                and acknowledgment.target_root == self.after_root
                and acknowledgment.ack_digest == self.ack_digest()
                and acknowledgment.ack_id == 'portable-rearm-ack-' + acknowledgment.ack_digest,
                'TARGET_REARM_EXECUTION_ACK_REQUIRED')

    def readback_digest(self):
        return canonical_sha256({'schema': 'aioa.portable-rearm-complete-readback.v1',
            'write_observation': self.to_dict(), 'state_root': self.after_root,
            'resources_root': self.resources_root, 'receipts_root': self.receipts_root})


@dataclass(frozen=True, slots=True)
class VerifiedRearmTargetSettlement:
    """Independently read complete state plus the previously durable Core ACK."""
    resolution: Reconciliation
    target: TargetObservation
    write_observation: TargetRearmWriteObservation
    execution_ack: TargetExecutionAck

    def __post_init__(self):
        require(type(self.write_observation) is TargetRearmWriteObservation
                and type(self.target) is TargetObservation and type(self.resolution) is Reconciliation
                and type(self.resolution.outcome) is Applied, 'VERIFIED_REARM_TARGET_REQUIRED')
        observed, target, resolution, acknowledgment = self.write_observation, self.target, self.resolution, self.execution_ack
        observed.require_ack(acknowledgment)
        require((target.operation_digest, target.before_root, target.after_root, target.resources_root,
                 target.receipts_root, target.guard_fingerprint) == (observed.operation_digest,
                    observed.before_root, observed.after_root, observed.resources_root,
                    observed.receipts_root, observed.guard_fingerprint), 'TARGET_REARM_READBACK_BINDING')
        receipt = EvidenceRef(acknowledgment.ack_id, 'receipt', 'sha256:' + acknowledgment.ack_digest, 'portable-rearm-core-ack-v1')
        readback = EvidenceRef('portable-rearm-readback-' + observed.readback_digest(),
                              'independent-readback', 'sha256:' + observed.readback_digest(), 'portable-rearm-v1')
        require(resolution.operation_digest == observed.operation_digest
                and resolution.receipt == receipt and resolution.readback == readback
                and target.receipt_id == acknowledgment.ack_id and target.receipt_digest == acknowledgment.ack_digest
                and target.readback_digest == observed.readback_digest(), 'TARGET_REARM_EVIDENCE_BINDING')


@runtime_checkable
class TargetSettlementPort(Protocol):
    """Trusted host implementation on the SAME Core/runner/scope/workspace.

    Only deterministic DB computation may run in these methods. Implementations
    must not execute/read a target, sign, open another runner, perform network I/O
    or mutate counters outside the transaction. A retry reuses one observation.
    No JSON/HTTP/model registration path exists. Protocol typing is not a sandbox
    against a malicious host; the concrete registered adapter remains sealed TCB.
    """
    profile: str
    core: CoreAdmission
    runner: TransactionRunner
    scope: OwnerScope
    workspace: str
    binding: TargetBinding

    def start_in_transaction(self, tx, warrant, operation, snapshot): ...
    def before_release_in_transaction(self, tx, warrant, operation, snapshot, *, write_observation=None): ...
    def record_ack_in_transaction(self, tx, warrant, acknowledgment: TargetExecutionAck): ...
    def apply_resolution_in_transaction(self, tx, warrant, epoch, verified): ...
    def check_history_in_transaction(self, tx, warrant, intent): ...


TARGET_HEAD_KIND = 'aioa-core-target-head.v1'
TARGET_ADOPTION_KIND = 'core-target-existing-adoption'
TARGET_ADOPTION_CLASS = 'TARGET_ADOPT_EXISTING'
ADOPTION_REQUEST = 'aioa.target-adopt-existing-request.v1'


@dataclass(frozen=True, slots=True)
class ExistingTargetAdoption:
    """Immutable host observations for exact adoption, never effect permission.

    The Core preparation route issues the incarnation and retains these facts
    before owner approval. A physical adapter must still supply fresh roots
    under its held guard; this data type cannot prove that a guard is held.
    """
    binding: TargetBinding
    state_root: str
    resources_root: str
    receipts_root: str
    epoch: int
    owner_session_digest: str

    def __post_init__(self):
        require(type(self.binding) is TargetBinding, 'TARGET_ADOPTION_REQUEST_BINDING')
        for value in (self.state_root, self.resources_root, self.receipts_root, self.owner_session_digest):
            _root(value)
        require(type(self.epoch) is int and self.epoch > 0, 'TARGET_ADOPTION_EPOCH')

    @property
    def target_revision(self):
        return 'core-target-' + self.binding.digest()[:16] + '-00000000'

    @property
    def target_key(self):
        # Stable named target, deliberately excluding the issued incarnation.
        return canonical_sha256((TARGET_HEAD_KIND, self.binding.scope,
                                 self.binding.workspace, self.binding.target_id))

    def to_dict(self):
        return {'schema': ADOPTION_REQUEST, **asdict(self)}

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict and set(value) == {'schema', 'binding', 'state_root',
                'resources_root', 'receipts_root', 'epoch', 'owner_session_digest'}
                and value['schema'] == ADOPTION_REQUEST, 'TARGET_ADOPTION_REQUEST_BINDING')
        binding = value['binding']
        require(type(binding) is dict and set(binding) == {'scope', 'workspace', 'target_id',
                'incarnation', 'guard_fingerprint'}, 'TARGET_ADOPTION_REQUEST_BINDING')
        scope = binding['scope']
        require(type(scope) is dict and set(scope) == {'tenant_id', 'owner_id', 'space_id', 'slot_id'},
                'TARGET_ADOPTION_REQUEST_BINDING')
        fixed = TargetBinding(**{**binding, 'scope': OwnerScope(**scope)})
        return cls(fixed, value['state_root'], value['resources_root'], value['receipts_root'],
                   value['epoch'], value['owner_session_digest'])

    def digest(self):
        return canonical_sha256(self.to_dict())

    def evidence(self):
        return EvidenceRef(self.target_key, TARGET_ADOPTION_KIND,
                           'sha256:' + self.digest(), 'adopt-existing-v1')

    def operation(self):
        return {'operation_class': TARGET_ADOPTION_CLASS,
                'target_fingerprint': 'sha256:' + self.state_root,
                'expected_target_revision': self.target_revision, 'payload': self.to_dict()}


FENCED_NO_RELEASE_PROFILE = 'aioa.portable-fenced-no-release.v1'


@dataclass(frozen=True, slots=True)
class FencedNoReleaseCertificate:
    """Closed durable facts; these cannot replace a current physical fence."""
    binding_digest: str
    operation_digest: str
    warrant_digest: str
    expected_head_revision: int
    generation: int
    intent_revision: int
    history_digest: str
    head_digest: str
    intent_digest: str
    consumption_digest: str
    liability_id: str
    state_root: str
    resources_root: str
    receipts_root: str
    guard_fingerprint: str

    def __post_init__(self):
        digest_id(self.operation_digest, 'no-release operation')
        digest_id(self.warrant_digest, 'no-release warrant')
        digest_id(self.liability_id, 'no-release liability')
        require(type(self.expected_head_revision) is int and self.expected_head_revision >= 2
                and type(self.generation) is int and self.generation >= 0
                and type(self.intent_revision) is int and self.intent_revision >= 1,
                'NO_RELEASE_CERTIFICATE_REVISION')
        for name in ('binding_digest', 'history_digest', 'head_digest', 'intent_digest',
                     'consumption_digest', 'state_root', 'resources_root', 'receipts_root', 'guard_fingerprint'):
            _root(getattr(self, name))

    def to_dict(self):
        return {'schema': FENCED_NO_RELEASE_PROFILE, **asdict(self)}

    @classmethod
    def parse(cls, value):
        require(type(value) is dict and set(value) == set(cls.__dataclass_fields__) | {'schema'}
                and value['schema'] == FENCED_NO_RELEASE_PROFILE, 'NO_RELEASE_CERTIFICATE_SHAPE')
        return cls(**{key: item for key, item in value.items() if key != 'schema'})

    def digest(self):
        return canonical_sha256(self.to_dict())

    def readback_digest(self):
        # Acyclic and separate from certificate/target/history commitments.
        return canonical_sha256({'schema': 'aioa.portable-no-release-readback.v1',
            'binding_digest': self.binding_digest, 'operation_digest': self.operation_digest,
            'warrant_digest': self.warrant_digest, 'guard_fingerprint': self.guard_fingerprint,
            'state_root': self.state_root, 'resources_root': self.resources_root, 'receipts_root': self.receipts_root})

    def receipt(self):
        digest = self.digest()
        return EvidenceRef('portable-no-release-' + digest, 'no-effect-certificate',
                           'sha256:' + digest, 'portable-no-release-v1')

    def readback(self):
        digest = self.readback_digest()
        return EvidenceRef('portable-no-release-readback-' + digest, 'independent-readback',
                           'sha256:' + digest, 'portable-no-release-v1')

    def require_resolution(self, target, resolution):
        require(type(target) is TargetObservation and type(resolution) is Reconciliation
                and type(resolution.outcome) is NotApplied and resolution.outcome.evidence_refs == ()
                and resolution.operation_digest == self.operation_digest
                and resolution.receipt == self.receipt() and resolution.readback == self.readback(),
                'NO_RELEASE_RESOLUTION_BINDING')
        require(target.expected_head_revision == self.expected_head_revision
                and target.generation == self.generation and target.operation_digest == self.operation_digest
                and target.before_root == target.after_root == self.state_root
                and target.resources_root == self.resources_root and target.receipts_root == self.receipts_root
                and target.guard_fingerprint == self.guard_fingerprint
                and target.receipt_id == self.receipt().evidence_id and target.receipt_digest == self.digest()
                and target.readback_digest == self.readback_digest(), 'NO_RELEASE_TARGET_BINDING')


@dataclass(frozen=True, slots=True)
class VerifiedNoReleaseSettlement:
    """Per-call live envelope. Durable history parses only the facts above."""
    resolution: Reconciliation
    target: TargetObservation
    certificate: FencedNoReleaseCertificate
    _witness: object = field(repr=False, compare=False)

    def __post_init__(self):
        require(type(self.certificate) is FencedNoReleaseCertificate, 'NO_RELEASE_CERTIFICATE_REQUIRED')
        self.certificate.require_resolution(self.target, self.resolution)
        # This constructor runs outside SQL, after the physical adapter exists.
        from runtime.mission.portable_target import _PortableNoReleaseWitness
        require(type(self._witness) is _PortableNoReleaseWitness, 'NO_RELEASE_LIVE_WITNESS_REQUIRED')
        self._witness.require_live(self)

    def require_live(self, projection, warrant):
        # No lazy imports or target I/O in this final transaction check.
        self._witness.require_live(self, projection=projection, warrant=warrant)

    def __copy__(self):
        raise TypeError('a live no-release envelope cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('a live no-release envelope cannot be copied')

    def __reduce_ex__(self, protocol):
        raise TypeError('a live no-release envelope cannot be serialized')
