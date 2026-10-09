"""AIOA-facing boundary for the external MCP Commander.

This package intentionally contains contracts and policy only.  It does not
open sockets, execute shell commands, or grant effect authority.
"""

from .adapter import AIOAObservation, admit_commander_result, build_task
from .authority import AuthorityProjection, project_authority
from .claim import TransportClaim, parse_claim_comment
from .contracts import (
    RiskClass,
    TaskEnvelope,
    TaskResult,
    TaskState,
    TransitionError,
)
from .policy import PolicyDecision, PolicyEffect, evaluate_task
from .read_ops import VERIFIED_READ_OPERATIONS, validate_read_payload
from .task_bus import encode_result, encode_task, parse_result, parse_task

__all__ = [
    "AIOAObservation",
    "AuthorityProjection",
    "PolicyDecision",
    "PolicyEffect",
    "RiskClass",
    "TaskEnvelope",
    "TaskResult",
    "TaskState",
    "TransportClaim",
    "VERIFIED_READ_OPERATIONS",
    "TransitionError",
    "admit_commander_result",
    "build_task",
    "evaluate_task",
    "project_authority",
    "encode_task",
    "parse_task",
    "encode_result",
    "parse_result",
    "parse_claim_comment",
    "validate_read_payload",
]
