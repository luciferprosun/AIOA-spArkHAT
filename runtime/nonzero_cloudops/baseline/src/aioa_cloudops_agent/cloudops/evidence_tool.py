"""Native Strands tool for deterministic local remediation evidence."""

from collections.abc import Callable
from datetime import datetime
from typing import Final
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Tracer
from strands import tool
from strands.tools.decorator import DecoratedFunctionTool

from aioa_cloudops_agent.domain import ContractValidationError
from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind, ResultStatus

from .build_evidence import BuildRemediationEvidenceService
from .evidence_models import EvidenceBuildOutcome, EvidenceBuildResult
from .metrics_models import UtilizationEvidence
from .models import InstanceInspection, InvestigationIdentity, SandboxTarget, validate_instance_id

BUILD_REMEDIATION_EVIDENCE_TOOL_NAME: Final = "build_remediation_evidence"


def create_build_remediation_evidence_tool(
    service: BuildRemediationEvidenceService,
    inspection_provider: Callable[[], InstanceInspection | None],
    utilization_provider: Callable[[], UtilizationEvidence | None],
    identity: InvestigationIdentity,
    target: SandboxTarget,
    proposal_id: UUID,
    *,
    clock: Callable[[], datetime],
    tracer: Tracer | None = None,
    on_result: Callable[[EvidenceBuildResult], None] | None = None,
) -> DecoratedFunctionTool:
    """Bind typed evidence providers so model input cannot supply action arguments."""

    if not isinstance(service, BuildRemediationEvidenceService):
        raise ContractValidationError("service must be BuildRemediationEvidenceService")
    if not callable(inspection_provider) or not callable(utilization_provider):
        raise ContractValidationError("evidence providers must be callable")
    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    if not isinstance(target, SandboxTarget):
        raise ContractValidationError("target must be a SandboxTarget")
    if not isinstance(proposal_id, UUID) or proposal_id.version != 7:
        raise ContractValidationError("proposal_id must be UUIDv7")
    if not callable(clock):
        raise ContractValidationError("clock must be callable")
    active_tracer = tracer or trace.get_tracer("aioa_cloudops_agent.cloudops")

    @tool(name=BUILD_REMEDIATION_EVIDENCE_TOOL_NAME)
    def build_remediation_evidence(instance_id: str) -> dict[str, object]:
        """Build typed local evidence for the validated instance; never execute it."""

        with active_tracer.start_as_current_span("cloudops.build_remediation_evidence") as span:
            span.set_attribute("aioa.run_id", str(identity.run_id))
            span.set_attribute("aioa.trace_id", str(identity.trace_id))
            span.set_attribute("aioa.correlation_id", str(identity.correlation_id))
            span.set_attribute("aioa.tool_name", BUILD_REMEDIATION_EVIDENCE_TOOL_NAME)
            span.set_attribute("aioa.authority_gate", "AUTO")
            span.set_attribute("aioa.operation_class", "READ_ONLY")
            try:
                requested_id = validate_instance_id(instance_id)
            except ContractValidationError as error:
                result = ControlResult[EvidenceBuildOutcome].failed(
                    FailureDetail(
                        kind=FailureKind.VALIDATION_FAILURE,
                        code="EVIDENCE_INPUT_INVALID",
                        message=error.message,
                        retryable=False,
                    )
                )
            else:
                inspection = inspection_provider()
                utilization = utilization_provider()
                if requested_id != target.instance_id:
                    result = ControlResult[EvidenceBuildOutcome].failed(
                        FailureDetail(
                            kind=FailureKind.POLICY_DENIAL,
                            code="EVIDENCE_SCOPE_DENIED",
                            message="Requested evidence target is outside the sandbox",
                            retryable=False,
                        )
                    )
                elif inspection is None or utilization is None:
                    result = ControlResult[EvidenceBuildOutcome].failed(
                        FailureDetail(
                            kind=FailureKind.VALIDATION_FAILURE,
                            code="EVIDENCE_SEQUENCE_INVALID",
                            message="Inspection and utilization evidence are required first",
                            retryable=False,
                        )
                    )
                else:
                    result = service.build_result(
                        inspection=inspection,
                        utilization=utilization,
                        identity=identity,
                        proposal_id=proposal_id,
                        built_at=clock(),
                    )
            span.set_attribute("aioa.result_status", result.status.value)
            if result.status is ResultStatus.SUCCESS and result.value is not None:
                span.set_attribute("aioa.evidence_digest", result.value.evidence.evidence_hash)
                span.set_attribute("aioa.evidence_decision", result.value.decision.value)
            elif result.failure is not None:
                span.set_attribute("aioa.failure_kind", result.failure.kind.value)
            if on_result is not None:
                on_result(result)
            return result.model_dump(mode="json")

    return build_remediation_evidence
