"""Deny-by-default policy for tasks crossing from ChatGPT/MCP into AIOA."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .contracts import RiskClass, TaskEnvelope


class PolicyEffect(str, Enum):
    ALLOW = "ALLOW"
    REQUIRE_HUMAN = "REQUIRE_HUMAN"
    DENY = "DENY"


@dataclass(frozen=True)
class PolicyDecision:
    effect: PolicyEffect
    reason: str
    operation: str
    risk: RiskClass

    @property
    def may_execute_without_human(self) -> bool:
        return self.effect is PolicyEffect.ALLOW


_OPERATION_RISK: dict[str, RiskClass] = {
    "system.status": RiskClass.READ,
    "fs.list": RiskClass.READ,
    "fs.stat": RiskClass.READ,
    "fs.read": RiskClass.READ,
    "fs.search": RiskClass.READ,
    "git.status": RiskClass.READ,
    "git.diff": RiskClass.READ,
    "git.log": RiskClass.READ,
    "git.branches": RiskClass.READ,
    "artifact.list": RiskClass.READ,
    "artifact.get": RiskClass.READ,
    "approval.status": RiskClass.READ,
    "patch.propose": RiskClass.READ,
    "provider.status": RiskClass.READ,
    "provider.models": RiskClass.READ,
    "patch.request_apply": RiskClass.WRITE_LOCAL,
    "recipe.request": RiskClass.EXEC_LOCAL,
}


def expected_risk(operation: str) -> RiskClass | None:
    return _OPERATION_RISK.get(operation)


def evaluate_task(task: TaskEnvelope) -> PolicyDecision:
    expected = expected_risk(task.operation)
    if expected is None:
        return PolicyDecision(
            PolicyEffect.DENY,
            "unknown operation: deny by default",
            task.operation,
            task.risk,
        )

    if task.risk is not expected:
        return PolicyDecision(
            PolicyEffect.DENY,
            f"risk mismatch: operation requires {expected.value}",
            task.operation,
            task.risk,
        )

    if expected is RiskClass.READ:
        return PolicyDecision(
            PolicyEffect.ALLOW,
            "registered bounded read operation",
            task.operation,
            task.risk,
        )

    if expected in {RiskClass.WRITE_LOCAL, RiskClass.EXEC_LOCAL}:
        return PolicyDecision(
            PolicyEffect.REQUIRE_HUMAN,
            "effectful local operation requires out-of-band human approval",
            task.operation,
            task.risk,
        )

    return PolicyDecision(
        PolicyEffect.DENY,
        "risk class not enabled in the MCP bridge MVP",
        task.operation,
        task.risk,
    )
