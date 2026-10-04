"""Explicit uncertainty record schema, without ledger or taint propagation."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar

from .authority import Money, decode_enum
from .contracts import Contract, ContractValidationError, frozen_refs, identifier, utc_time
from .evidence import EvidenceRef


class LiabilityStatus(Enum):
    OPEN = 'OPEN'
    CLOSED = 'CLOSED'
    ESCALATED = 'ESCALATED'


@dataclass(frozen=True, kw_only=True)
class LiabilityRecord(Contract):
    TYPE: ClassVar[str] = 'LiabilityRecord'
    __hash__ = Contract.__hash__
    TIME_FIELDS: ClassVar[tuple[str, ...]] = ('opened_at',)
    OPTIONAL_TIME_FIELDS: ClassVar[tuple[str, ...]] = ('closed_at',)
    REF_FIELDS: ClassVar[tuple[str, ...]] = ('evidence_refs', 'dependency_refs')
    liability_id: str
    task_id: str
    request_ref: str
    kind: str
    status: LiabilityStatus
    opened_at: datetime
    closed_at: datetime | None = None
    max_cost_exposure: Money | None = None
    evidence_refs: tuple[EvidenceRef, ...] = ()
    dependency_refs: tuple[EvidenceRef, ...] = ()
    resolution_ref: str | None = None

    def __post_init__(self):
        for field in ('liability_id', 'task_id', 'request_ref', 'kind'):
            identifier(getattr(self, field), field)
        if type(self.status) is not LiabilityStatus:
            raise ContractValidationError('status', 'invalid_status')
        object.__setattr__(self, 'opened_at', utc_time(self.opened_at, 'opened_at'))
        if self.closed_at is not None:
            object.__setattr__(self, 'closed_at', utc_time(self.closed_at, 'closed_at'))
        if self.resolution_ref is not None:
            identifier(self.resolution_ref, 'resolution_ref')
        if self.status is LiabilityStatus.CLOSED:
            if self.closed_at is None or self.resolution_ref is None:
                raise ContractValidationError('closure', 'resolution_and_time_required')
            if self.closed_at < self.opened_at:
                raise ContractValidationError('closed_at', 'before_opened_at')
        elif self.closed_at is not None or self.resolution_ref is not None:
            raise ContractValidationError('closure', 'unclosed_status_has_closure')
        if self.max_cost_exposure is not None and type(self.max_cost_exposure) is not Money:
            raise ContractValidationError('max_cost_exposure', 'money_required')
        for field in self.REF_FIELDS:
            object.__setattr__(self, field, frozen_refs(getattr(self, field), field))

    @classmethod
    def _decode(cls, payload):
        payload['status'] = decode_enum(LiabilityStatus, payload['status'], 'status')
        if payload['max_cost_exposure'] is not None:
            payload['max_cost_exposure'] = Money.from_dict(payload['max_cost_exposure'])
        return payload
