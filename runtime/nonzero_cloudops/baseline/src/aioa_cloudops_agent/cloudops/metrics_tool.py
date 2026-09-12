"""Native Strands tool for scoped CloudWatch utilization evidence."""

from collections.abc import Callable
from datetime import datetime
from typing import Final

from opentelemetry import trace
from opentelemetry.trace import Tracer
from strands import tool
from strands.tools.decorator import DecoratedFunctionTool

from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind, ResultStatus

from .metrics_models import UtilizationEvidence
from .models import InstanceInspection, InvestigationIdentity, validate_instance_id
from .read_utilization import ReadUtilizationMetricsService

READ_UTILIZATION_TOOL_NAME: Final = "read_utilization_metrics"


def create_read_utilization_metrics_tool(
    service: ReadUtilizationMetricsService,
    inspection: InstanceInspection | Callable[[], InstanceInspection | None],
    identity: InvestigationIdentity,
    *,
    clock: Callable[[], datetime],
    tracer: Tracer | None = None,
    on_result: Callable[[ControlResult[UtilizationEvidence]], None] | None = None,
) -> DecoratedFunctionTool:
    """Bind validated inspection proof and identity to the CloudWatch tool."""

    if not isinstance(service, ReadUtilizationMetricsService):
        raise ContractValidationError("service must be ReadUtilizationMetricsService")
    if not isinstance(inspection, InstanceInspection) and not callable(inspection):
        raise ContractValidationError("inspection must be evidence or a callable provider")
    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    if not callable(clock):
        raise ContractValidationError("clock must be callable")
    active_tracer = tracer or trace.get_tracer("aioa_cloudops_agent.cloudops")

    @tool(name=READ_UTILIZATION_TOOL_NAME)
    def read_utilization_metrics(instance_id: str) -> dict[str, object]:
        """Read fixed CPU evidence for the previously validated sandbox instance."""

        with active_tracer.start_as_current_span("cloudops.read_utilization_metrics") as span:
            span.set_attribute("aioa.run_id", str(identity.run_id))
            span.set_attribute("aioa.trace_id", str(identity.trace_id))
            span.set_attribute("aioa.correlation_id", str(identity.correlation_id))
            span.set_attribute("aioa.tool_name", READ_UTILIZATION_TOOL_NAME)
            span.set_attribute("aioa.authority_gate", "AUTO")
            span.set_attribute("aioa.operation_class", "READ_ONLY")
            try:
                requested_id = validate_instance_id(instance_id)
            except ContractValidationError as error:
                result = ControlResult[UtilizationEvidence].failed(
                    FailureDetail(
                        kind=FailureKind.VALIDATION_FAILURE,
                        code="METRIC_INPUT_INVALID",
                        message=error.message,
                        retryable=False,
                    )
                )
            else:
                active_inspection = inspection() if callable(inspection) else inspection
                if active_inspection is None:
                    result = ControlResult[UtilizationEvidence].failed(
                        FailureDetail(
                            kind=FailureKind.VALIDATION_FAILURE,
                            code="INSPECTION_REQUIRED",
                            message="Validated instance evidence is required before metrics",
                            retryable=False,
                        )
                    )
                elif not isinstance(active_inspection, InstanceInspection):
                    result = ControlResult[UtilizationEvidence].failed(
                        FailureDetail(
                            kind=FailureKind.VALIDATION_FAILURE,
                            code="INSPECTION_INVALID",
                            message="Inspection provider returned an invalid contract",
                            retryable=False,
                        )
                    )
                elif requested_id != active_inspection.instance_id:
                    result = ControlResult[UtilizationEvidence].failed(
                        FailureDetail(
                            kind=FailureKind.POLICY_DENIAL,
                            code="METRIC_SCOPE_DENIED",
                            message="Requested metric target is outside the validated sandbox",
                            retryable=False,
                        )
                    )
                else:
                    result = service.read_result(
                        inspection=active_inspection,
                        identity=identity,
                        collected_at=clock(),
                    )
            span.set_attribute("aioa.result_status", result.status.value)
            if result.status is ResultStatus.SUCCESS and result.value is not None:
                span.set_attribute("aioa.evidence_digest", result.value.evidence_digest)
                span.set_attribute("aioa.classification", result.value.classification.value)
            elif result.failure is not None:
                span.set_attribute("aioa.failure_kind", result.failure.kind.value)
                span.set_attribute("aioa.failure_code", result.failure.code)
            if on_result is not None:
                on_result(result)
            return result.model_dump(mode="json")

    return read_utilization_metrics
