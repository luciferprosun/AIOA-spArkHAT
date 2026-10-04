"""Pure ambiguity semantics. Traces contain opaque metadata, never payloads."""
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
import re
from typing import ClassVar

from .authority import decode_enum
from .canonical import canonical_digest
from .contracts import Contract, ContractValidationError, digest_id, utc_time
from .evidence import EvidenceRef
from .liability import LiabilityRecord, LiabilityStatus
from .outcome import Applied, NotApplied, Unknown


class FaultKind(Enum):
    LOST_ACK = 'LOST_ACK'
    PROVIDER_TIMEOUT_AFTER_POSSIBLE_ACCEPT = 'PROVIDER_TIMEOUT_AFTER_POSSIBLE_ACCEPT'
    MISSING_RECEIPT_AFTER_EFFECT = 'MISSING_RECEIPT_AFTER_EFFECT'
    INCONCLUSIVE_READBACK = 'INCONCLUSIVE_READBACK'


def opaque_id(value, field):
    """Restricted metadata slot; arbitrary text is not a trace identifier."""
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value) is None:
        raise ContractValidationError(field, 'opaque_identifier_required')
    return value


@dataclass(frozen=True)
class FaultTrace(Contract):
    TYPE: ClassVar[str] = 'FaultTrace'
    __hash__ = Contract.__hash__
    kind: FaultKind
    task_id: str
    request_ref: str
    operation_digest: str

    def __post_init__(self):
        if type(self.kind) is not FaultKind:
            raise ContractValidationError('kind', 'invalid_fault_kind')
        opaque_id(self.task_id, 'task_id')
        opaque_id(self.request_ref, 'request_ref')
        digest_id(self.operation_digest, 'operation_digest')

    @classmethod
    def _decode(cls, payload):
        payload['kind'] = decode_enum(FaultKind, payload['kind'], 'kind')
        return payload


def require_trace(trace):
    if type(trace) is not FaultTrace:
        raise ContractValidationError('trace', 'fault_trace_required')


def classify_fault(trace: FaultTrace) -> Unknown:
    """All four faults are ambiguous; the fault kind cannot infer an effect."""
    require_trace(trace)
    binding = {'task_id': trace.task_id, 'request_ref': trace.request_ref,
               'operation_digest': trace.operation_digest}
    return Unknown(canonical_digest('PCAF/OperationLiability/v1', binding))


def open_liability(trace: FaultTrace, opened_at: datetime,
                   existing: LiabilityRecord | None = None) -> LiabilityRecord:
    """Return one OPEN record for this operation; do not reopen resolved records."""
    outcome = classify_fault(trace)
    opened_at = utc_time(opened_at, 'opened_at')
    if existing is not None:
        if (type(existing) is not LiabilityRecord or
                existing.liability_id != outcome.liability_id or
                existing.task_id != trace.task_id or existing.request_ref != trace.request_ref or
                existing.kind != 'UNKNOWN_EFFECT' or existing.status is not LiabilityStatus.OPEN):
            raise ContractValidationError('liability', 'open_operation_binding_required')
        return existing
    return LiabilityRecord(liability_id=outcome.liability_id, task_id=trace.task_id,
                           request_ref=trace.request_ref, kind='UNKNOWN_EFFECT',
                           status=LiabilityStatus.OPEN, opened_at=opened_at)


def liability_index(records):
    """Normalize exact duplicates; conflicting records cannot choose a winner."""
    if not isinstance(records, (tuple, list)) or any(type(r) is not LiabilityRecord for r in records):
        raise ContractValidationError('liabilities', 'liability_records_required')
    result = {}
    for record in records:
        if record.liability_id in result and result[record.liability_id] != record:
            raise ContractValidationError('liabilities', 'conflicting_liability_id')
        result[record.liability_id] = record
    return result


def ambiguity_liability(outcome, records) -> LiabilityRecord | None:
    """Validate the exact OPEN reference of a newly ambiguous event."""
    if type(outcome) not in (Applied, NotApplied, Unknown):
        raise ContractValidationError('outcome', 'outcome_variant_required')
    index = liability_index(records)
    if type(outcome) in (Applied, NotApplied):
        return None
    record = index.get(outcome.liability_id)
    if record is None or record.status is not LiabilityStatus.OPEN:
        raise ContractValidationError('liability', 'open_reference_required')
    return record


def is_blocking(record: LiabilityRecord) -> bool:
    if type(record) is not LiabilityRecord:
        raise ContractValidationError('liability', 'liability_record_required')
    return record.status in (LiabilityStatus.OPEN, LiabilityStatus.ESCALATED)


def resolve_liability(record: LiabilityRecord, evidence: EvidenceRef,
                      closed_at: datetime) -> LiabilityRecord:
    """Explicit fixture resolution only; evidence validity is contract metadata.

    No external truth verification or authorization is implied by an EvidenceRef.
    PRE-01 represents resolved state as CLOSED, with resolution_ref and closed_at.
    """
    if not is_blocking(record):
        raise ContractValidationError('liability', 'already_closed')
    if type(evidence) is not EvidenceRef:
        raise ContractValidationError('resolution', 'evidence_ref_required')
    return replace(record, status=LiabilityStatus.CLOSED, closed_at=closed_at,
                   resolution_ref=evidence.evidence_id,
                   evidence_refs=record.evidence_refs + (evidence,))
