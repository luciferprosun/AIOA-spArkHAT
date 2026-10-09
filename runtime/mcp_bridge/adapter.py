"""Adapters between the external Commander protocol and AIOA observations."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping
import uuid

from .contracts import PROTOCOL_VERSION, RiskClass, TaskEnvelope, TaskResult
from .policy import expected_risk
from .read_ops import validate_read_payload


@dataclass(frozen=True)
class AIOAObservation:
    """A non-authoritative observation derived from a Commander result."""

    schema: str
    source: str
    authority: str
    can_authorize_effects: bool
    task_id: str
    state: str
    summary: str
    artifact_refs: tuple[str, ...]
    audit_refs: tuple[str, ...]
    changed_files: tuple[str, ...]
    metadata: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source": self.source,
            "authority": self.authority,
            "can_authorize_effects": self.can_authorize_effects,
            "task_id": self.task_id,
            "state": self.state,
            "summary": self.summary,
            "artifact_refs": list(self.artifact_refs),
            "audit_refs": list(self.audit_refs),
            "changed_files": list(self.changed_files),
            "metadata": dict(self.metadata),
        }


def build_task(
    operation: str,
    payload: dict[str, Any],
    *,
    target_project: str = "commander",
    task_id: str | None = None,
    idempotency_key: str | None = None,
    source: str = "chatgpt",
) -> TaskEnvelope:
    risk = expected_risk(operation)
    if risk is RiskClass.READ:
        validate_read_payload(operation, payload)
    if risk is None:
        # Unknown operations are still representable only at an explicitly
        # dangerous risk class so policy cannot accidentally treat them as READ.
        risk = RiskClass.OPEN_WORLD

    effective_task_id = task_id or f"task-{uuid.uuid4()}"
    effective_key = idempotency_key
    if effective_key is None:
        seed = f"{PROTOCOL_VERSION}:{effective_task_id}:{operation}".encode("utf-8")
        effective_key = hashlib.sha256(seed).hexdigest()

    return TaskEnvelope(
        task_id=effective_task_id,
        target_project=target_project,
        operation=operation,
        risk=risk,
        payload=payload,
        idempotency_key=effective_key,
        source=source,
    )


def admit_commander_result(result: TaskResult) -> AIOAObservation:
    """Convert a tool result to evidence-like data without granting authority."""

    return AIOAObservation(
        schema="aioa.mcp-observation.v1",
        source="mcp_commander",
        authority="ADVISORY_ONLY",
        can_authorize_effects=False,
        task_id=result.task_id,
        state=result.state.value,
        summary=result.summary,
        artifact_refs=result.artifact_ids,
        audit_refs=result.audit_refs,
        changed_files=result.changed_files,
        metadata=dict(result.metadata),
    )
