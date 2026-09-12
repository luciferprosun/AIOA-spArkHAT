"""Native Strands AUTO/read-only verification tool."""

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

VERIFY_INSTANCE_STATE_TOOL_NAME: Final = "verify_instance_state"
VerificationRequestHandler = Callable[[UUID], dict[str, object]]


def unavailable_verification_request(proposal_id: UUID) -> dict[str, object]:
    """Fail closed when no durable verification coordinator is injected."""

    del proposal_id
    return ControlResult[str].failed(
        FailureDetail(
            kind=FailureKind.DEPENDENCY_UNAVAILABLE,
            code="VERIFICATION_COORDINATOR_UNAVAILABLE",
            message="Independent verification is not configured",
            retryable=False,
        )
    ).model_dump(mode="json")


def create_verify_instance_state_tool(
    handler: VerificationRequestHandler,
    identity: InvestigationIdentity,
    *,
    tracer: Tracer | None = None,
) -> DecoratedFunctionTool:
    """Expose only a durable proposal reference; target selection remains application-owned."""

    if not callable(handler):
        raise ContractValidationError("verification request handler must be callable")
    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    active_tracer = tracer or trace.get_tracer("aioa_cloudops_agent.verification")

    @tool(name=VERIFY_INSTANCE_STATE_TOOL_NAME)
    def verify_instance_state(proposal_id: str) -> dict[str, object]:
        """Read back the exact approved sandbox state and persist typed proof."""

        with active_tracer.start_as_current_span("cloudops.verify_instance_state") as span:
            span.set_attribute("aioa.run_id", str(identity.run_id))
            span.set_attribute("aioa.trace_id", str(identity.trace_id))
            span.set_attribute("aioa.correlation_id", str(identity.correlation_id))
            span.set_attribute("aioa.tool_name", VERIFY_INSTANCE_STATE_TOOL_NAME)
            span.set_attribute("aioa.authority_gate", "AUTO")
            span.set_attribute("aioa.operation_class", "READ_ONLY")
            try:
                parsed = UUID(proposal_id)
                validate_correlation_id(parsed)
            except (ValueError, ContractValidationError):
                return ControlResult[str].failed(
                    FailureDetail(
                        kind=FailureKind.VALIDATION_FAILURE,
                        code="VERIFICATION_PROPOSAL_INVALID",
                        message="proposal_id must be a UUIDv7 durable reference",
                        retryable=False,
                    )
                ).model_dump(mode="json")
            span.set_attribute("aioa.proposal_id", str(parsed))
            return handler(parsed)

    return verify_instance_state
