"""Native Strands mutation-facing tool with no direct AWS client ownership."""

from collections.abc import Callable
from typing import Final
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Tracer
from strands import tool
from strands.tools.decorator import DecoratedFunctionTool

from aioa_cloudops_agent.cloudops import InvestigationIdentity
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind

STOP_SANDBOX_INSTANCE_TOOL_NAME: Final = "stop_sandbox_instance"
StopRequestHandler = Callable[[UUID], dict[str, object]]


def unavailable_stop_request(proposal_id: UUID) -> dict[str, object]:
    """Fail closed when no private remediation boundary has been injected."""

    del proposal_id
    return ControlResult[str].failed(
        FailureDetail(
            kind=FailureKind.DEPENDENCY_UNAVAILABLE,
            code="REMEDIATION_EXECUTOR_UNAVAILABLE",
            message="Private remediation execution is not configured",
            retryable=False,
        )
    ).model_dump(mode="json")


def create_stop_sandbox_instance_tool(
    handler: StopRequestHandler,
    identity: InvestigationIdentity,
    *,
    tracer: Tracer | None = None,
) -> DecoratedFunctionTool:
    """Expose only a proposal reference; the injected boundary owns all validation."""

    if not callable(handler):
        raise ContractValidationError("stop request handler must be callable")
    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    active_tracer = tracer or trace.get_tracer("aioa_cloudops_agent.remediation")

    @tool(name=STOP_SANDBOX_INSTANCE_TOOL_NAME)
    def stop_sandbox_instance(proposal_id: str) -> dict[str, object]:
        """Request the approval-bound sandbox stop using one durable proposal reference."""

        with active_tracer.start_as_current_span("cloudops.stop_sandbox_instance") as span:
            span.set_attribute("aioa.run_id", str(identity.run_id))
            span.set_attribute("aioa.trace_id", str(identity.trace_id))
            span.set_attribute("aioa.correlation_id", str(identity.correlation_id))
            span.set_attribute("aioa.tool_name", STOP_SANDBOX_INSTANCE_TOOL_NAME)
            span.set_attribute("aioa.authority_gate", "PLAN_AND_CONFIRM")
            span.set_attribute("aioa.operation_class", "MUTATION")
            try:
                parsed_proposal_id = UUID(proposal_id)
                validate_correlation_id(parsed_proposal_id)
            except (ValueError, ContractValidationError):
                return ControlResult[str].failed(
                    FailureDetail(
                        kind=FailureKind.VALIDATION_FAILURE,
                        code="PROPOSAL_REFERENCE_INVALID",
                        message="proposal_id must be a UUIDv7 durable reference",
                        retryable=False,
                    )
                ).model_dump(mode="json")
            span.set_attribute("aioa.proposal_id", str(parsed_proposal_id))
            return handler(parsed_proposal_id)

    return stop_sandbox_instance
