"""Exact, canonical dependencies of a future human decision."""
from dataclasses import dataclass
from typing import ClassVar

from .contracts import Contract, frozen_refs
from .evidence import EvidenceRef


@dataclass(frozen=True)
class DecisionDependencyRoot(Contract):
    TYPE: ClassVar[str] = 'DecisionDependencyRoot'
    __hash__ = Contract.__hash__
    REF_FIELDS: ClassVar[tuple[str, ...]] = ('evidence_refs',)
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'evidence_refs', frozen_refs(self.evidence_refs, 'evidence_refs'))

    @property
    def root_digest(self) -> str:
        return self.contract_digest()
