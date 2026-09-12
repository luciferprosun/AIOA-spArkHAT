"""Bounded invocation request construction for the primary agent."""

from aioa_cloudops_agent.cloudops.models import SandboxTarget
from aioa_cloudops_agent.domain.errors import ContractValidationError


def build_inspection_request(target: SandboxTarget) -> str:
    """Require one canonical tool call before an evidence-based conclusion."""

    if not isinstance(target, SandboxTarget):
        raise ContractValidationError("target must be a SandboxTarget")
    return (
        "Use inspect_instance exactly once for instance_id "
        f"{target.instance_id}. Base the conclusion only on the returned evidence. "
        "Do not claim or propose any mutation."
    )


def build_investigation_request(target: SandboxTarget) -> str:
    """Request the complete bounded read-only sequence for one sandbox target."""

    if not isinstance(target, SandboxTarget):
        raise ContractValidationError("target must be a SandboxTarget")
    return (
        "Investigate only configured instance_id "
        f"{target.instance_id}. Use inspect_instance, read_utilization_metrics, and "
        "build_remediation_evidence in that order, each once. Treat ambiguous or missing "
        "evidence as a failure. Report only the resulting run, trace, correlation, evidence, "
        "and proposal identifiers. Do not request, approve, or claim any AWS mutation."
    )
