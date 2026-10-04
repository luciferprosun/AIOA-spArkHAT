"""Immutable evidence metadata; contains no evidence payload."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from .contracts import Contract, digest_id, identifier, utc_time


@dataclass(frozen=True)
class EvidenceRef(Contract):
    TYPE: ClassVar[str] = 'EvidenceRef'
    __hash__ = Contract.__hash__
    OPTIONAL_TIME_FIELDS: ClassVar[tuple[str, ...]] = ('valid_time', 'transaction_time')
    evidence_id: str
    kind: str
    digest: str = field()
    source_version: str
    valid_time: datetime | None = None
    transaction_time: datetime | None = None

    def __post_init__(self):
        for field in ('evidence_id', 'kind', 'source_version'):
            identifier(getattr(self, field), field)
        digest_id(self.digest, 'digest')
        for field in self.OPTIONAL_TIME_FIELDS:
            if getattr(self, field) is not None:
                object.__setattr__(self, field, utc_time(getattr(self, field), field))
