"""AIOA-facing boundary for the external MCP Commander.

This package intentionally contains contracts and policy only.  It does not
open sockets, execute shell commands, or grant effect authority.
"""

from .adapter import AIOAObservation, admit_commander_result, build_task
from .contracts import (
    RiskClass,
    TaskEnvelope,
    TaskResult,
    TaskState,
    TransitionError,
)
from .policy import PolicyDecision, PolicyEffect, evaluate_task

__all__ = [
    "AIOAObservation",
    "PolicyDecision",
    "PolicyEffect",
    "RiskClass",
    "TaskEnvelope",
    "TaskResult",
    "TaskState",
    "TransitionError",
    "admit_commander_result",
    "build_task",
    "evaluate_task",
]
