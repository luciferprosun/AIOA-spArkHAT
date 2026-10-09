"""Project MCP policy decisions into AIOA/NonZero authority semantics.

This module deliberately imports no optional NonZero dependencies. It exposes
plain strings compatible with the existing authority vocabulary and never
upgrades MCP/tool output into execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from .policy import PolicyDecision, PolicyEffect


@dataclass(frozen=True)
class AuthorityProjection:
    authority_gate: str
    executable: bool
    requires_human: bool
    source_authority: str = "ADVISORY_ONLY"


def project_authority(decision: PolicyDecision) -> AuthorityProjection:
    if decision.effect is PolicyEffect.ALLOW:
        return AuthorityProjection(
            authority_gate="AUTO_READ_ONLY",
            executable=True,
            requires_human=False,
        )
    if decision.effect is PolicyEffect.REQUIRE_HUMAN:
        return AuthorityProjection(
            authority_gate="PLAN_AND_CONFIRM",
            executable=False,
            requires_human=True,
        )
    return AuthorityProjection(
        authority_gate="NEVER_AUTONOMOUS",
        executable=False,
        requires_human=False,
    )
