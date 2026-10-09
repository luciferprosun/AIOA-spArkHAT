"""Planner-side payload validation for verified bounded READ operations.

This is deliberately stricter than the wire envelope. It prevents the planner
from emitting malformed or unverified READ tasks into the GitHub mailbox.
Local Commander policy remains authoritative for execution admission.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
import uuid

from .contracts import ContractError


VERIFIED_READ_OPERATIONS = frozenset({
    "system.status",
    "git.status",
    "git.diff",
    "git.log",
    "git.branches",
    "fs.list",
    "fs.stat",
    "fs.read",
    "fs.search",
    "artifact.list",
    "artifact.get",
})

UNVERIFIED_READ_OPERATIONS = frozenset({
    "approval.status",
    "patch.propose",
    "provider.status",
    "provider.models",
})


def _exact_keys(
    operation: str,
    payload: dict[str, Any],
    *,
    allowed: frozenset[str],
    required: frozenset[str] = frozenset(),
) -> None:
    keys = set(payload)
    missing = required - keys
    extra = keys - allowed
    if missing:
        raise ContractError(
            f"{operation} missing required payload keys: {sorted(missing)}"
        )
    if extra:
        raise ContractError(
            f"{operation} has unsupported payload keys: {sorted(extra)}"
        )


def _bounded_int(
    operation: str,
    name: str,
    value: Any,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ContractError(
            f"{operation}.{name} must be an integer in [{minimum}, {maximum}]"
        )
    return value


def _relative_path(operation: str, value: Any) -> str:
    if type(value) is not str or not value.strip():
        raise ContractError(f"{operation}.path must be a non-empty string")
    if len(value) > 512 or "\x00" in value:
        raise ContractError(f"{operation}.path is invalid")
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ContractError(f"{operation}.path must stay inside the project root")
    return value


def _query(operation: str, value: Any) -> str:
    if type(value) is not str or not value.strip() or len(value) > 256:
        raise ContractError(f"{operation}.query must be 1..256 characters")
    return value


def _artifact_id(operation: str, value: Any) -> str:
    if type(value) is not str:
        raise ContractError(f"{operation}.artifact_id must be a UUID string")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ContractError(
            f"{operation}.artifact_id must be a UUID string"
        ) from exc
    return value


def validate_read_payload(operation: str, payload: dict[str, Any]) -> None:
    """Validate planner-generated payloads for READ operations.

    Operations that local policy classifies as READ but whose payload contract
    has not yet been verified are blocked rather than guessed.
    """

    if type(payload) is not dict:
        raise ContractError("READ payload must be a plain JSON object")

    if operation in UNVERIFIED_READ_OPERATIONS:
        raise ContractError(
            f"{operation} READ schema is not verified; do not emit this task"
        )

    if operation not in VERIFIED_READ_OPERATIONS:
        raise ContractError(
            f"{operation} is not in the planner verified READ registry"
        )

    if operation in {"system.status", "git.branches", "artifact.list"}:
        _exact_keys(operation, payload, allowed=frozenset())
        return

    if operation == "git.status":
        _exact_keys(operation, payload, allowed=frozenset({"short"}))
        if "short" in payload and type(payload["short"]) is not bool:
            raise ContractError("git.status.short must be a boolean")
        return

    if operation == "git.diff":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"max_bytes", "max_lines"}),
        )
        if "max_bytes" in payload:
            _bounded_int(operation, "max_bytes", payload["max_bytes"], minimum=1, maximum=8192)
        if "max_lines" in payload:
            _bounded_int(operation, "max_lines", payload["max_lines"], minimum=1, maximum=200)
        return

    if operation == "git.log":
        _exact_keys(operation, payload, allowed=frozenset({"limit"}))
        if "limit" in payload:
            _bounded_int(operation, "limit", payload["limit"], minimum=1, maximum=20)
        return

    if operation == "fs.list":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"path", "limit"}),
            required=frozenset({"path"}),
        )
        _relative_path(operation, payload["path"])
        if "limit" in payload:
            _bounded_int(operation, "limit", payload["limit"], minimum=1, maximum=64)
        return

    if operation == "fs.stat":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"path"}),
            required=frozenset({"path"}),
        )
        _relative_path(operation, payload["path"])
        return

    if operation == "fs.read":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"path", "bytes", "lines"}),
            required=frozenset({"path"}),
        )
        _relative_path(operation, payload["path"])
        if "bytes" in payload:
            _bounded_int(operation, "bytes", payload["bytes"], minimum=1, maximum=8192)
        if "lines" in payload:
            _bounded_int(operation, "lines", payload["lines"], minimum=1, maximum=200)
        return

    if operation == "fs.search":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"query", "max_hits"}),
            required=frozenset({"query"}),
        )
        _query(operation, payload["query"])
        if "max_hits" in payload:
            _bounded_int(operation, "max_hits", payload["max_hits"], minimum=1, maximum=20)
        return

    if operation == "artifact.get":
        _exact_keys(
            operation,
            payload,
            allowed=frozenset({"artifact_id", "max_bytes", "max_lines"}),
            required=frozenset({"artifact_id"}),
        )
        _artifact_id(operation, payload["artifact_id"])
        if "max_bytes" in payload:
            _bounded_int(operation, "max_bytes", payload["max_bytes"], minimum=1, maximum=400)
        if "max_lines" in payload:
            _bounded_int(operation, "max_lines", payload["max_lines"], minimum=1, maximum=12)
        return

    raise ContractError(f"{operation} READ payload validation is incomplete")
