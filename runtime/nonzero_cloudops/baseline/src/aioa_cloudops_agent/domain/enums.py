"""Canonical execution and authority states."""

from enum import StrEnum


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
