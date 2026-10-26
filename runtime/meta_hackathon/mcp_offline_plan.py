"""Offline Meta read-plan bridge, REUSING the original AIOA MCP modules.

The existing MCP policy is the single reference for operation classification.
An ALLOW for a bounded READ operation there is NOT a grant to dispatch a
new Meta worker. This adapter intentionally exposes only a fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass

from runtime.mcp_bridge.adapter import build_task
from runtime.mcp_bridge.contracts import ContractError, RiskClass
from runtime.mcp_bridge.policy import PolicyEffect, evaluate_task

from .worktree_guard import MetaCheckoutProof, MetaIsolationError

# No paths, network requests, arbitrary tool names, WRITE or EXEC.
_META_READ_OPERATIONS = frozenset({
    "system.status", "git.status", "git.branches", "git.log", "git.diff",
})


@dataclass(frozen=True, slots=True)
class MetaReadPlan:
    operation: str
    task_fingerprint: str
    meta_source_sha: str
    schema: str = "aioa.meta.mcp-read-plan.v1"
    status: str = "PREVIEW_ONLY"
    authority: str = "NONE"

    @property
    def dispatch_allowed(self) -> bool:
        return False


def preview_mcp_read(
    proof: MetaCheckoutProof,
    *,
    operation: str,
    payload: dict,
    task_id: str,
) -> MetaReadPlan:
    """Construct a bounded task with Core's inherited policy, without sending."""
    if (type(proof) is not MetaCheckoutProof
        or proof.branch != "meta"
        or proof.evidence_level != "LOCAL_GIT_READ_ONLY"
        or proof.dispatch_allowed
        or type(operation) is not str
        or operation not in _META_READ_OPERATIONS
        or type(payload) is not dict
        or type(task_id) is not str
        or not task_id.startswith("meta-")):
        raise MetaIsolationError()
    try:
        candidate = build_task(
            operation, payload, target_project="meta",
            task_id=task_id, source="meta_hackathon",
        )
        decision = evaluate_task(candidate)
        if (decision.effect is not PolicyEffect.ALLOW
            or candidate.risk is not RiskClass.READ):
            raise MetaIsolationError()
    except (ContractError, TypeError, AttributeError, ValueError):
        raise MetaIsolationError() from None
    return MetaReadPlan(operation, candidate.fingerprint, proof.source_sha)
