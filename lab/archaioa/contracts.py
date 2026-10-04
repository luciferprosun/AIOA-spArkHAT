"""Shared strict validation and versioned wire contract interface."""
from dataclasses import fields
from datetime import datetime, timedelta, timezone
import re
from typing import ClassVar, Self


class ContractValidationError(ValueError):
    """Stable error metadata; never echo untrusted field values."""
    def __init__(self, field: str, code: str):
        self.field = field
        self.code = code
        super().__init__(f'{field}: {code}')


def identifier(value, field):
    if not isinstance(value, str) or not value or value != value.strip() or any(ord(c) < 32 for c in value):
        raise ContractValidationError(field, 'invalid_identifier')
    try:
        value.encode('utf-8')
    except UnicodeError:
        raise ContractValidationError(field, 'invalid_utf8') from None
    return value


def digest_id(value, field):
    if not isinstance(value, str) or re.fullmatch(r'sha256:[0-9a-f]{64}', value) is None:
        raise ContractValidationError(field, 'invalid_digest')
    return value


def utc_time(value, field):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ContractValidationError(field, 'utc_required')
    return datetime(value.year, value.month, value.day, value.hour, value.minute, value.second, value.microsecond, tzinfo=timezone.utc, fold=value.fold)


def decode_time(value, field, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', value) is None:
        raise ContractValidationError(field, 'invalid_timestamp')
    try:
        return utc_time(datetime.fromisoformat(value.replace('Z', '+00:00')), field)
    except ValueError:
        raise ContractValidationError(field, 'invalid_timestamp') from None


def frozen_refs(value, field):
    from .evidence import EvidenceRef
    if not isinstance(value, (list, tuple)) or any(type(item) is not EvidenceRef for item in value):
        raise ContractValidationError(field, 'invalid_evidence_refs')
    by_id = {}
    for item in value:
        if item.evidence_id in by_id and by_id[item.evidence_id] != item:
            raise ContractValidationError(field, 'conflicting_evidence_id')
        by_id[item.evidence_id] = item
    return tuple(sorted(by_id.values(), key=lambda item: item.to_json()))


def decode_refs(value, field):
    from .evidence import EvidenceRef
    if not isinstance(value, list):
        raise ContractValidationError(field, 'invalid_evidence_refs')
    return tuple(EvidenceRef.from_dict(item) for item in value)


class Contract:
    """Value semantics only; serialization and hashing never create authority."""
    SCHEMA_VERSION: ClassVar[int] = 1
    TYPE: ClassVar[str]
    TIME_FIELDS: ClassVar[tuple[str, ...]] = ()
    OPTIONAL_TIME_FIELDS: ClassVar[tuple[str, ...]] = ()
    REF_FIELDS: ClassVar[tuple[str, ...]] = ()

    def __hash__(self) -> int:
        # A portable 31-bit value hash; full digests remain the wire identity.
        return int(self.contract_digest().split(':', 1)[1][:8], 16) & 0x7fffffff

    def to_dict(self) -> dict:
        from .canonical import canonical_value
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        return canonical_value(payload | {'contract_type': self.TYPE, 'schema_version': self.SCHEMA_VERSION})

    def to_json(self) -> str:
        from .canonical import canonical_json
        return canonical_json(self.to_dict())

    def contract_digest(self) -> str:
        from .canonical import canonical_digest
        return canonical_digest(f'PCAF/{self.TYPE}/v{self.SCHEMA_VERSION}', self.to_dict())

    def digest(self) -> str:
        return self.contract_digest()

    @classmethod
    def from_dict(cls, value: dict) -> Self:
        expected = {field.name for field in fields(cls)} | {'contract_type', 'schema_version'}
        if not isinstance(value, dict) or set(value) != expected:
            raise ContractValidationError('wire', 'invalid_fields')
        if type(value['schema_version']) is not int or value['schema_version'] != cls.SCHEMA_VERSION:
            raise ContractValidationError('schema_version', 'unsupported_version')
        if value['contract_type'] != cls.TYPE:
            raise ContractValidationError('contract_type', 'wrong_type')
        payload = {key: item for key, item in value.items() if key not in ('schema_version', 'contract_type')}
        for field in cls.TIME_FIELDS:
            payload[field] = decode_time(payload[field], field)
        for field in cls.OPTIONAL_TIME_FIELDS:
            payload[field] = decode_time(payload[field], field, optional=True)
        for field in cls.REF_FIELDS:
            payload[field] = decode_refs(payload[field], field)
        return cls(**cls._decode(payload))

    @classmethod
    def _decode(cls, payload: dict) -> dict:
        return payload

    @classmethod
    def from_json(cls, value: str) -> Self:
        from .canonical import parse_json
        return cls.from_dict(parse_json(value))
