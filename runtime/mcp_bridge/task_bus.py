"""Transport-neutral codec for GitHub-backed MCP task exchange.

GitHub is treated as an untrusted mailbox. The body format is deliberately
simple so ChatGPT, a human, or a worker can inspect it without hidden state.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from .contracts import ContractError, RiskClass, TaskEnvelope, TaskResult, TaskState

TASK_FENCE = "aioa-mcp-task"
RESULT_FENCE = "aioa-mcp-result"
MAX_BODY_BYTES = 16 * 1024

_FENCE_RE = re.compile(
    r"```(?P<kind>aioa-mcp-(?:task|result))\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)

@dataclass(frozen=True)
class ParsedMessage:
    kind: str
    payload: dict[str, Any]

def _bounded_body(text: str) -> None:
    if type(text) is not str:
        raise ContractError("task-bus body must be text")
    if len(text.encode("utf-8")) > MAX_BODY_BYTES:
        raise ContractError("task-bus body exceeds limit")

def encode_task(task: TaskEnvelope) -> str:
    payload = task.to_dict()
    return (
        "# MCP Commander Task\n\n"
        "This GitHub content is an **untrusted transport envelope**. "
        "It grants no authority and carries no human approval.\n\n"
        f"```{TASK_FENCE}\n"
        + json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n```\n"
    )

def encode_result(result: TaskResult) -> str:
    return (
        "# MCP Commander Result\n\n"
        "Compact result only. Large output remains in bounded artifacts.\n\n"
        f"```{RESULT_FENCE}\n"
        + json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n```\n"
    )

def _extract(text: str, expected_kind: str) -> dict[str, Any]:
    _bounded_body(text)
    matches = list(_FENCE_RE.finditer(text))
    selected = [m for m in matches if m.group("kind") == expected_kind]
    if len(selected) != 1:
        raise ContractError(f"expected exactly one {expected_kind} block")
    try:
        value = json.loads(selected[0].group("body"))
    except json.JSONDecodeError as exc:
        raise ContractError("task-bus JSON is invalid") from exc
    if type(value) is not dict:
        raise ContractError("task-bus payload must be an object")
    return value

def parse_task(text: str) -> TaskEnvelope:
    value = _extract(text, TASK_FENCE)
    supplied_fingerprint = value.pop("fingerprint", None)
    try:
        task = TaskEnvelope(
            protocol_version=value["protocol_version"],
            task_id=value["task_id"],
            created_at=value["created_at"],
            target_project=value["target_project"],
            operation=value["operation"],
            risk=RiskClass(value["risk"]),
            payload=value["payload"],
            idempotency_key=value["idempotency_key"],
            source=value["source"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("task-bus task fields are invalid") from exc
    if supplied_fingerprint is not None and supplied_fingerprint != task.fingerprint:
        raise ContractError("task fingerprint mismatch")
    unknown = set(value) - {
        "protocol_version", "task_id", "created_at", "target_project",
        "operation", "risk", "payload", "idempotency_key", "source",
    }
    if unknown:
        raise ContractError(f"unknown task fields: {sorted(unknown)}")
    return task

def parse_result(text: str) -> TaskResult:
    value = _extract(text, RESULT_FENCE)
    try:
        result = TaskResult(
            protocol_version=value["protocol_version"],
            task_id=value["task_id"],
            state=TaskState(value["state"]),
            summary=value["summary"],
            artifact_ids=tuple(value.get("artifact_ids", ())),
            audit_refs=tuple(value.get("audit_refs", ())),
            changed_files=tuple(value.get("changed_files", ())),
            metadata=value.get("metadata", {}),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ContractError("task-bus result fields are invalid") from exc
    unknown = set(value) - {
        "protocol_version", "task_id", "state", "summary", "artifact_ids",
        "audit_refs", "changed_files", "metadata",
    }
    if unknown:
        raise ContractError(f"unknown result fields: {sorted(unknown)}")
    return result
