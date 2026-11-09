"""Immutable target observations and a host-bound, DB-only settlement port.

These values carry facts, never authority. The registered implementation must
verify complete target roots, held guard, incarnation and canonical Core CAS.
This protocol itself is not a physical target adapter or an INIT/rearm service.
"""
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

from lab.archaioa.contracts import digest_id
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import opaque_id
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
    def before_release_in_transaction(self, tx, warrant, operation, snapshot): ...
    def record_ack_in_transaction(self, tx, warrant, acknowledgment: TargetExecutionAck): ...
    def apply_resolution_in_transaction(self, tx, warrant, epoch, verified): ...
    def check_history_in_transaction(self, tx, warrant, intent): ...
