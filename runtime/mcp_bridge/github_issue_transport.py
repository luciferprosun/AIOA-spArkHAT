"""Pure GitHub Issue transport helpers for MCP Commander.

This module performs no network I/O. GitHub is treated as an untrusted
mailbox only; policy and human approval remain outside the transport.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .contracts import ContractError, TaskEnvelope, TaskResult
from .task_bus import encode_result, encode_task, parse_result, parse_task

TASK_TITLE_PREFIX = "[MCP-TASK]"
RESULT_TITLE_PREFIX = "[MCP-RESULT]"
LABEL_NEW = "mcp:new"
LABEL_CLAIMED = "mcp:claimed"
LABEL_WAITING_HUMAN = "mcp:waiting-human"
LABEL_DONE = "mcp:done"
LABEL_FAILED = "mcp:failed"

_TASK_TITLE_RE = re.compile(r"^\[MCP-TASK\]\s+(?P<task_id>[^\s]+)\s+::\s+(?P<operation>.+)$")


@dataclass(frozen=True)
class IssueTask:
    issue_number: int
    title: str
    body: str
    task: TaskEnvelope


def build_issue_title(task: TaskEnvelope) -> str:
    return f"{TASK_TITLE_PREFIX} {task.task_id} :: {task.operation}"


def build_issue_body(task: TaskEnvelope) -> str:
    return encode_task(task)


def parse_issue(issue_number: int, title: str, body: str) -> IssueTask:
    if type(issue_number) is not int or issue_number <= 0:
        raise ContractError("issue_number must be a positive integer")
    if type(title) is not str or type(body) is not str:
        raise ContractError("issue title/body must be text")
    match = _TASK_TITLE_RE.match(title.strip())
    if match is None:
        raise ContractError("issue title does not match MCP task format")
    task = parse_task(body)
    if match.group("task_id") != task.task_id:
        raise ContractError("issue title task_id does not match envelope")
    if match.group("operation").strip() != task.operation:
        raise ContractError("issue title operation does not match envelope")
    return IssueTask(issue_number=issue_number, title=title, body=body, task=task)


def build_result_comment(result: TaskResult) -> str:
    return encode_result(result)


def parse_result_comment(comment: str) -> TaskResult:
    return parse_result(comment)
