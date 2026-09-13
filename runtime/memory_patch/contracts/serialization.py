"Canonical serialization and integrity helpers.\n\nHashes in this module provide deterministic identity and mutation detection.\nThey are not signatures and do not prove semantic compliance by a model.\n"

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from collections.abc import Mapping, Set
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, TypeVar
from uuid import UUID

from ..errors import ContractValidationError, IntegrityError

_MACHINE_PATH_PATTERNS = (
    re.compile("^/home/"),
    re.compile("^/media/"),
    re.compile("^/Users/"),
    re.compile("^[A-Za-z]:[\\\\/](?:Users|Documents and Settings)[\\\\/]"),
)
_SHA256_HEX = re.compile("^[0-9a-f]{64}$")
_EnumT = TypeVar("_EnumT", bound=Enum)
CONTRACT_SCHEMA_VERSION = "1.0.0"


def require_non_empty(value: str, field_name: str) -> str:
    """Return *value* when it contains non-whitespace text, otherwise fail."""
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{field_name} must be a non-empty string")
    return value


def require_sha256_hex(value: str, field_name: str) -> str:
    """Require a lowercase 64-character SHA-256 hexadecimal digest."""
    require_non_empty(value, field_name)
    if _SHA256_HEX.fullmatch(value) is None:
        raise ContractValidationError(
            f"{field_name} must be a lowercase SHA-256 hexadecimal digest"
        )
    return value


def require_enum_member(value: Any, enum_type: type[_EnumT], field_name: str) -> _EnumT:
    """Require an actual enum member rather than a look-alike plain string."""
    if not isinstance(value, enum_type):
        raise ContractValidationError(
            f"{field_name} must be a {enum_type.__name__} member"
        )
    return value


def require_schema_version(value: str) -> str:
    """Reject missing, older, and future contract schema versions."""
    require_non_empty(value, "schema_version")
    if value != CONTRACT_SCHEMA_VERSION:
        raise ContractValidationError(f"unsupported contract schema_version {value!r}")
    return value


def freeze_typed_tuple(
    value: Any, expected_type: type[Any], field_name: str
) -> tuple[Any, ...]:
    """Copy a tuple/list and validate every nested contract element."""
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must be a tuple or list")
    frozen = tuple(value)
    if any((not isinstance(item, expected_type) for item in frozen)):
        raise ContractValidationError(
            f"{field_name} items must be {expected_type.__name__} instances"
        )
    return frozen


def freeze_string_tuple(
    value: Any, field_name: str, *, unique: bool = False
) -> tuple[str, ...]:
    """Copy a tuple/list of non-empty strings with optional uniqueness."""
    frozen = freeze_typed_tuple(value, str, field_name)
    for item in frozen:
        require_non_empty(item, f"{field_name} item")
    if unique and len(frozen) != len(set(frozen)):
        raise ContractValidationError(f"{field_name} items must be unique")
    return frozen


def ensure_utc(value: datetime, field_name: str = "timestamp") -> datetime:
    """Normalize an aware timestamp to UTC; naive timestamps fail closed."""
    if not isinstance(value, datetime):
        raise ContractValidationError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ContractValidationError(f"{field_name} must include a UTC offset")
    return value.astimezone(timezone.utc)


def normalize_utc_timestamp(value: datetime) -> str:
    """Return a stable ISO-8601 UTC representation with a ``Z`` suffix."""
    normalized = ensure_utc(value)
    text = normalized.isoformat(timespec="microseconds")
    if text.endswith("+00:00"):
        text = f"{text[:-6]}Z"
    return text


def reject_machine_specific_path(value: str) -> None:
    """Reject common user-specific absolute paths from canonical records."""
    if any((pattern.search(value) for pattern in _MACHINE_PATH_PATTERNS)):
        raise ContractValidationError(
            "canonical contract data must not contain a machine-specific absolute path"
        )


def freeze_json(value: Any) -> Any:
    """Recursively freeze JSON-compatible data for use in immutable records."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("NaN and infinity are not permitted")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractValidationError("canonical mapping keys must be strings")
            frozen[key] = freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple((freeze_json(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return frozenset((freeze_json(item) for item in value))
    if isinstance(value, (datetime, Enum, UUID)):
        return value
    if dataclasses.is_dataclass(value) and (not isinstance(value, type)):
        return value
    raise ContractValidationError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def _sort_canonical_values(values: Iterable[Any]) -> list[Any]:
    canonical_values = list(values)
    return sorted(
        canonical_values,
        key=lambda item: json.dumps(
            item,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ),
    )


def to_canonical_data(
    value: Any, *, exclude_fields: frozenset[str] = frozenset(), _is_root: bool = True
) -> Any:
    """Convert supported values into a deterministic JSON data structure.

    ``exclude_fields`` applies only to the root record. This prevents a nested
    record's integrity field from being silently omitted.
    """
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        reject_machine_specific_path(value)
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("NaN and infinity are not permitted")
        return value
    if isinstance(value, datetime):
        return normalize_utc_timestamp(value)
    if isinstance(value, Enum):
        return to_canonical_data(value.value, _is_root=False)
    if isinstance(value, UUID):
        return str(value)
    if dataclasses.is_dataclass(value) and (not isinstance(value, type)):
        result: dict[str, Any] = {}
        for field in dataclasses.fields(value):
            if _is_root and field.name in exclude_fields:
                continue
            result[field.name] = to_canonical_data(
                getattr(value, field.name), _is_root=False
            )
        return result
    if isinstance(value, Mapping):
        result = {}
        keys = tuple(value.keys())
        if not all((isinstance(key, str) for key in keys)):
            raise ContractValidationError("canonical mapping keys must be strings")
        for key in sorted(keys):
            if _is_root and key in exclude_fields:
                continue
            result[key] = to_canonical_data(value[key], _is_root=False)
        return result
    if isinstance(value, (list, tuple)):
        return [to_canonical_data(item, _is_root=False) for item in value]
    if isinstance(value, Set) and (not isinstance(value, (str, bytes, bytearray))):
        return _sort_canonical_values(
            (to_canonical_data(item, _is_root=False) for item in value)
        )
    raise ContractValidationError(
        f"unsupported canonical value type: {type(value).__name__}"
    )


def canonical_json(value: Any, *, exclude_fields: Iterable[str] = ()) -> str:
    """Serialize a record with stable keys, enum values, sets, and timestamps."""
    data = to_canonical_data(value, exclude_fields=frozenset(exclude_fields))
    try:
        return json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ContractValidationError(f"canonical JSON failed: {exc}") from exc


def canonical_json_bytes(value: Any, *, exclude_fields: Iterable[str] = ()) -> bytes:
    """Return canonical JSON encoded as UTF-8."""
    return canonical_json(value, exclude_fields=exclude_fields).encode("utf-8")


def sha256_hex(payload: bytes | str) -> str:
    """Return a lowercase SHA-256 digest for bytes or UTF-8 text."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    if not isinstance(payload, bytes):
        raise ContractValidationError("sha256 payload must be bytes or text")
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any, *, exclude_fields: Iterable[str] = ()) -> str:
    """Hash the canonical JSON representation of a contract record."""
    return sha256_hex(canonical_json_bytes(value, exclude_fields=exclude_fields))


def verify_canonical_hash(
    value: Any, expected_hash: str, *, exclude_fields: Iterable[str] = ()
) -> None:
    """Raise when *expected_hash* is not the current deterministic digest."""
    actual = canonical_sha256(value, exclude_fields=exclude_fields)
    require_sha256_hex(expected_hash, "expected_hash")
    if actual != expected_hash:
        raise IntegrityError(
            f"canonical hash mismatch: expected {expected_hash}, calculated {actual}"
        )


def approval_proof_hash(
    *,
    approval_id: str,
    proposal_id: str,
    proposal_hash: str,
    tenant_id: str,
    owner_user_id: str | None,
    personal_memory_space_id: str | None,
    decision: str,
    approver_type: str,
    approver_id: str,
    reason_code: str,
    decided_at: datetime,
) -> str:
    """Bind every approval identity and scope field to the proposal digest."""
    if owner_user_id is not None:
        require_non_empty(owner_user_id, "owner_user_id")
    if personal_memory_space_id is not None:
        require_non_empty(personal_memory_space_id, "personal_memory_space_id")
    return canonical_sha256(
        {
            "contract_type": "MemoryPatchApproval",
            "contract_version": CONTRACT_SCHEMA_VERSION,
            "approval_id": require_non_empty(approval_id, "approval_id"),
            "proposal_id": require_non_empty(proposal_id, "proposal_id"),
            "proposal_hash": require_sha256_hex(proposal_hash, "proposal_hash"),
            "tenant_id": require_non_empty(tenant_id, "tenant_id"),
            "owner_user_id": owner_user_id,
            "personal_memory_space_id": personal_memory_space_id,
            "decision": require_non_empty(decision, "decision"),
            "approver_type": require_non_empty(approver_type, "approver_type"),
            "approver_id": require_non_empty(approver_id, "approver_id"),
            "reason_code": require_non_empty(reason_code, "reason_code"),
            "decided_at": ensure_utc(decided_at, "decided_at"),
        }
    )
