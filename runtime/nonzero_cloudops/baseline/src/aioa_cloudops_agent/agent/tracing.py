"""Correlation attributes shared by Strands, model, tool, and provenance spans."""

from typing import Final

from aioa_cloudops_agent.cloudops import InvestigationIdentity
from aioa_cloudops_agent.domain.errors import ContractValidationError

PRIMARY_AGENT_ID: Final = "aioa-nonzero-cloudops-primary"


def build_agent_trace_attributes(identity: InvestigationIdentity) -> dict[str, str]:
    """Return safe OpenTelemetry attributes inherited by the Strands invocation."""

    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    return {
        "aioa.agent_id": PRIMARY_AGENT_ID,
        "aioa.authority_gate": "AUTO",
        "aioa.run_id": str(identity.run_id),
        "aioa.trace_id": str(identity.trace_id),
        "aioa.correlation_id": str(identity.correlation_id),
        "aioa.operation_class": "READ_ONLY",
    }
