# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: domain/enums.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Canonical execution and authority states."""

from enum import StrEnum


class ApprovalStatus(StrEnum):
    """Wire projection from source domain/approval.py, same immutable SHA."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExecutionState(StrEnum):
    """Explicit lifecycle state for a bounded execution."""

    INIT = "INIT"
    RUNNING = "RUNNING"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"


class AuthorityGate(StrEnum):
    """Maximum authority available to an operation."""

    AUTO = "AUTO"
    PLAN_AND_CONFIRM = "PLAN_AND_CONFIRM"
    NEVER_AUTONOMOUS = "NEVER_AUTONOMOUS"
