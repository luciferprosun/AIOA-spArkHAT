"""Strict, dependency-free contracts for the MCP Commander bridge."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Mapping


PROTOCOL_VERSION = "aioa.mcp-commander.v1"
MAX_TASK_ID = 128
MAX_OPERATION = 96
MAX_PROJECT = 96
MAX_IDEMPOTENCY = 160
MAX_SUMMARY = 2048
MAX_LIST_ITEMS = 64
MAX_REF = 512

# These names are authority-shaped and are never accepted from an untrusted
# task payload. Human approval travels on a separate channel.
_RESERVED_AUTHORITY_KEYS = {
    "approval",
    "approved",
    "authorize",
    "authorized",
    "authorization",
    "human_approved",
    "human_approval",
    "permission",
    "policy_override",
}


class ContractError(ValueError):
    """Raised when untrusted task/result data violates the bridge contract."""


class TransitionError(ContractError):
    """Raised when a task lifecycle transition is invalid."""


class RiskClass(str, Enum):
    READ = "READ"
    WRITE_LOCAL = "WRITE_LOCAL"
    EXEC_LOCAL = "EXEC_LOCAL"
    DESTRUCTIVE = "DESTRUCTIVE"
    OPEN_WORLD = "OPEN_WORLD"


class TaskState(str, Enum):
    NEW = "NEW"
    CLAIMED = "CLAIMED"
    RUNNING = "RUNNING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


_ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.NEW: frozenset({TaskState.CLAIMED, TaskState.CANCELLED, TaskState.EXPIRED}),
    TaskState.CLAIMED: frozenset({TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED, TaskState.EXPIRED}),
    TaskState.RUNNING: frozenset({
        TaskState.WAITING_FOR_HUMAN,
        TaskState.DONE,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
    }),
    TaskState.WAITING_FOR_HUMAN: frozenset({
        TaskState.RUNNING,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
    }),
    TaskState.DONE: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
    TaskState.EXPIRED: frozenset(),
}


def _require_text(name: str, value: Any, *, limit: int, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise ContractError(f"{name} must be a string")
    if not allow_empty and not value.strip():
        raise ContractError(f"{name} must not be empty")
    if len(value) > limit:
        raise ContractError(f"{name} exceeds {limit} characters")
    return value


def _require_json_value(value: Any, *, path: str = "payload") -> None:
    if value is None or type(value) in {bool, int, float, str}:
        return
    if type(value) is list:
        if len(value) > 256:
            raise ContractError(f"{path} list is too large")
        for index, item in enumerate(value):
            _require_json_value(item, path=f"{path}[{index}]")
        return
    if type(value) is dict:
        if len(value) > 256:
            raise ContractError(f"{path} object is too large")
        for key, item in value.items():
            if type(key) is not str:
                raise ContractError(f"{path} keys must be strings")
            normalized = key.strip().lower()
            if normalized in _RESERVED_AUTHORITY_KEYS:
                raise ContractError(f"{path}.{key} is reserved for out-of-band authority")
            _require_json_value(item, path=f"{path}.{key}")
        return
    raise ContractError(f"{path} contains unsupported type {type(value).__name__}")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError("value is not canonical JSON") from exc


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    target_project: str
    operation: str
    risk: RiskClass
    payload: Mapping[str, Any]
    idempotency_key: str
    created_at: str = field(default_factory=utc_now_iso)
    protocol_version: str = PROTOCOL_VERSION
    source: str = "chatgpt"

    def __post_init__(self) -> None:
        _require_text("task_id", self.task_id, limit=MAX_TASK_ID)
        _require_text("target_project", self.target_project, limit=MAX_PROJECT)
        _require_text("operation", self.operation, limit=MAX_OPERATION)
        _require_text("idempotency_key", self.idempotency_key, limit=MAX_IDEMPOTENCY)
        _require_text("created_at", self.created_at, limit=64)
        _require_text("source", self.source, limit=64)
        if self.protocol_version != PROTOCOL_VERSION:
            raise ContractError(f"unsupported protocol_version: {self.protocol_version}")
        if type(self.payload) is not dict:
            raise ContractError("payload must be a plain JSON object")
        _require_json_value(self.payload)

    @property
    def fingerprint(self) -> str:
        authority_free = {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "target_project": self.target_project,
            "operation": self.operation,
            "risk": self.risk.value,
            "payload": self.payload,
            "idempotency_key": self.idempotency_key,
            "source": self.source,
        }
        return hashlib.sha256(_canonical_json(authority_free).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "created_at": self.created_at,
            "target_project": self.target_project,
            "operation": self.operation,
            "risk": self.risk.value,
            "payload": dict(self.payload),
            "idempotency_key": self.idempotency_key,
            "source": self.source,
            "fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    state: TaskState
    summary: str
    artifact_ids: tuple[str, ...] = ()
    audit_refs: tuple[str, ...] = ()
    changed_files: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _require_text("task_id", self.task_id, limit=MAX_TASK_ID)
        _require_text("summary", self.summary, limit=MAX_SUMMARY, allow_empty=True)
        if self.protocol_version != PROTOCOL_VERSION:
            raise ContractError(f"unsupported protocol_version: {self.protocol_version}")
        for name, values in (
            ("artifact_ids", self.artifact_ids),
            ("audit_refs", self.audit_refs),
            ("changed_files", self.changed_files),
        ):
            if type(values) is not tuple or len(values) > MAX_LIST_ITEMS:
                raise ContractError(f"{name} must be a bounded tuple")
            for value in values:
                _require_text(name, value, limit=MAX_REF)
        if type(self.metadata) is not dict:
            raise ContractError("metadata must be a plain JSON object")
        _require_json_value(self.metadata, path="metadata")

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "task_id": self.task_id,
            "state": self.state.value,
            "summary": self.summary,
            "artifact_ids": list(self.artifact_ids),
            "audit_refs": list(self.audit_refs),
            "changed_files": list(self.changed_files),
            "metadata": dict(self.metadata),
        }


def ensure_transition(current: TaskState, nxt: TaskState) -> None:
    if nxt not in _ALLOWED_TRANSITIONS[current]:
        raise TransitionError(f"invalid task transition: {current.value} -> {nxt.value}")
