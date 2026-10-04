"""Fixed, synthetic CONTRACT / FIXTURE examples; no secrets or I/O."""
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import ClassVar

from .authority import AuthorityScope, Money, RiskLevel
from .contracts import Contract, ContractValidationError, frozen_refs
from .decision_root import DecisionDependencyRoot
from .evidence import EvidenceRef
from .liability import LiabilityRecord, LiabilityStatus
from .outcome import Unknown
from .warrant import EffectWarrant, RevisionPolicy


@dataclass(frozen=True)
class ContractBundle(Contract):
    TYPE: ClassVar[str] = 'ContractBundle'
    __hash__ = Contract.__hash__
    REF_FIELDS: ClassVar[tuple[str, ...]] = ('evidence_refs',)
    warrant: EffectWarrant
    liability: LiabilityRecord
    decision_root: DecisionDependencyRoot
    evidence_refs: tuple[EvidenceRef, ...]
    outcome: Unknown

    def __post_init__(self):
        for field, expected in (('warrant', EffectWarrant), ('liability', LiabilityRecord), ('decision_root', DecisionDependencyRoot), ('outcome', Unknown)):
            if type(getattr(self, field)) is not expected:
                raise ContractValidationError(field, 'invalid_bundle_contract')
        object.__setattr__(self, 'evidence_refs', frozen_refs(self.evidence_refs, 'evidence_refs'))
        if self.warrant.decision_dependency_root != self.decision_root:
            raise ContractValidationError('decision_root', 'bundle_root_mismatch')
        if self.outcome.liability_id != self.liability.liability_id or self.warrant.task_id != self.liability.task_id:
            raise ContractValidationError('liability', 'bundle_binding_mismatch')
        if not set(self.decision_root.evidence_refs + self.liability.evidence_refs + self.liability.dependency_refs + self.outcome.evidence_refs) <= set(self.evidence_refs):
            raise ContractValidationError('evidence_refs', 'bundle_evidence_missing')

    @classmethod
    def _decode(cls, payload):
        for field, contract in (('warrant', EffectWarrant), ('liability', LiabilityRecord), ('decision_root', DecisionDependencyRoot), ('outcome', Unknown)):
            payload[field] = contract.from_dict(payload[field])
        return payload


def contract_bundle() -> ContractBundle:
    """New immutable values from literal fixture constants on every call."""
    start = datetime(2026, 10, 4, tzinfo=timezone.utc)
    a = EvidenceRef('e1', 'fixture', 'sha256:' + 'a' * 64, 'r1')
    b = EvidenceRef('e2', 'fixture', 'sha256:' + 'b' * 64, 'r1')
    root = DecisionDependencyRoot((a, b))
    target = 'sha256:' + 'b' * 64
    money = Money(Decimal('10'), 'EUR')
    scope = AuthorityScope(('write',), target, RiskLevel.MODERATE, money, start, start + timedelta(hours=1), 'owner-1', 'task-1')
    warrant = EffectWarrant(
        warrant_id='warrant-1', task_id='task-1', owner_scope='owner-1',
        operation_class='write', operation_hash='sha256:' + 'a' * 64,
        target_fingerprint=target, expected_target_revision='revision-1',
        revision_policy=RevisionPolicy.REQUIRE, decision_dependency_root=root,
        lease_epoch=0, authority_scope=scope, approval_digest='sha256:' + 'c' * 64,
        money_reservation_id='money-1', risk_reservation_id='risk-1',
        nonce='fixture-nonce-1', issued_at=start,
        expires_at=start + timedelta(minutes=30),
    )
    liability = LiabilityRecord(
        liability_id='liability-1', task_id='task-1', request_ref='request-1',
        kind='UNKNOWN_EFFECT', status=LiabilityStatus.OPEN, opened_at=start,
        max_cost_exposure=money, evidence_refs=(a,), dependency_refs=(b,),
    )
    return ContractBundle(warrant, liability, root, (a, b), Unknown('liability-1', (a,)))
