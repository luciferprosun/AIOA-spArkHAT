"""Native Strands tool registration for canonical EC2 inspection."""

from collections.abc import Callable
from typing import Final

from opentelemetry import trace
from opentelemetry.trace import Tracer
from strands import tool
from strands.tools.decorator import DecoratedFunctionTool

from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.nz import ResultStatus

from .inspect_instance import InspectInstanceService
from .models import InspectInstanceResult, InvestigationIdentity

INSPECT_INSTANCE_TOOL_NAME: Final = "inspect_instance"


def create_inspect_instance_tool(
    service: InspectInstanceService,
    identity: InvestigationIdentity,
    *,
    tracer: Tracer | None = None,
    on_result: Callable[[InspectInstanceResult], None] | None = None,
) -> DecoratedFunctionTool:
    """Bind one execution correlation ID to the only active Strands tool."""

    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    active_tracer = tracer or trace.get_tracer("aioa_cloudops_agent.cloudops")

    @tool(name=INSPECT_INSTANCE_TOOL_NAME)
    def inspect_instance(instance_id: str) -> dict[str, object]:
        """Inspect exactly one configured sandbox EC2 instance using read-only evidence."""

        with active_tracer.start_as_current_span("cloudops.inspect_instance") as span:
            span.set_attribute("aioa.run_id", str(identity.run_id))
            span.set_attribute("aioa.trace_id", str(identity.trace_id))
            span.set_attribute("aioa.correlation_id", str(identity.correlation_id))
            span.set_attribute("aioa.tool_name", INSPECT_INSTANCE_TOOL_NAME)
            span.set_attribute("aioa.authority_gate", "AUTO")
            span.set_attribute("aioa.operation_class", "READ_ONLY")
            result = service.inspect_result(
                instance_id=instance_id,
                identity=identity,
            )
            span.set_attribute("aioa.result_status", result.status.value)
            if result.status is ResultStatus.SUCCESS and result.value is not None:
                span.set_attribute("aioa.evidence_digest", result.value.evidence_digest)
                span.set_attribute("aws.region", result.value.region)
            elif result.failure is not None:
                span.set_attribute("aioa.failure_kind", result.failure.kind.value)
                span.set_attribute("aioa.failure_code", result.failure.code)
            if on_result is not None:
                on_result(result)
            return result.model_dump(mode="json")

    return inspect_instance
