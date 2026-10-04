"""Deterministic UTF-8 JSON and domain-separated fixture hashes."""
from datetime import datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json

from .contracts import Contract, ContractValidationError, identifier, utc_time


def decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise ContractValidationError('decimal', 'finite_required')
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def canonical_value(value):
    if isinstance(value, Contract):
        return value.to_dict()
    if isinstance(value, Enum):
        return canonical_value(value.value)
    if isinstance(value, datetime):
        value = utc_time(value, 'timestamp')
        return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')
    if isinstance(value, Decimal):
        return decimal_text(value)
    if value is None or type(value) in (str, bool, int):
        if isinstance(value, str):
            try:
                value.encode('utf-8')
            except UnicodeError:
                raise ContractValidationError('string', 'invalid_utf8') from None
        return value
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise ContractValidationError('json', 'string_keys_required')
        return {canonical_value(key): canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    raise ContractValidationError('json', 'unsupported_type')


def canonical_json(value) -> str:
    try:
        return json.dumps(canonical_value(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    except RecursionError:
        raise ContractValidationError('json', 'nesting_or_cycle') from None


def canonical_digest(domain: str, value) -> str:
    identifier(domain, 'domain')
    data = domain.encode('utf-8') + b'\x00' + canonical_json(value).encode('utf-8')
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def parse_json(value: str):
    def reject_number(_):
        raise ContractValidationError('json', 'invalid_number')

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ContractValidationError('json', 'duplicate_field')
            result[key] = item
        return result

    if not isinstance(value, str):
        raise ContractValidationError('json', 'string_required')
    try:
        return json.loads(value, object_pairs_hook=unique_pairs, parse_float=reject_number, parse_constant=reject_number)
    except ContractValidationError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise ContractValidationError('json', 'invalid_json') from None
