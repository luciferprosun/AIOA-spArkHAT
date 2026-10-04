"""Explicit effect outcome algebra, with no retries or implicit success."""
from dataclasses import dataclass
from typing import ClassVar

from .contracts import Contract, frozen_refs, identifier
from .evidence import EvidenceRef


class Outcome(Contract):
    REF_FIELDS: ClassVar[tuple[str, ...]] = ('evidence_refs',)

    def __bool__(self):
        raise TypeError('Outcome requires explicit variant inspection')


@dataclass(frozen=True)
class Applied(Outcome):
    TYPE: ClassVar[str] = 'Applied'
    __hash__ = Contract.__hash__
    receipt_ref: str
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self):
        identifier(self.receipt_ref, 'receipt_ref')
        object.__setattr__(self, 'evidence_refs', frozen_refs(self.evidence_refs, 'evidence_refs'))


@dataclass(frozen=True)
class NotApplied(Outcome):
    TYPE: ClassVar[str] = 'NotApplied'
    __hash__ = Contract.__hash__
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'evidence_refs', frozen_refs(self.evidence_refs, 'evidence_refs'))


@dataclass(frozen=True)
class Unknown(Outcome):
    TYPE: ClassVar[str] = 'Unknown'
    __hash__ = Contract.__hash__
    liability_id: str
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self):
        identifier(self.liability_id, 'liability_id')
        object.__setattr__(self, 'evidence_refs', frozen_refs(self.evidence_refs, 'evidence_refs'))
