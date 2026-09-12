"""Ephemeral typed tool context for one bounded Strands investigation."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from aioa_cloudops_agent.nz import FailureDetail, ResultStatus

from .metrics_models import ReadUtilizationResult, UtilizationEvidence
from .models import InspectInstanceResult, InstanceInspection, InvestigationIdentity

if TYPE_CHECKING:
    from .evidence_models import EvidenceBuildOutcome, EvidenceBuildResult


@dataclass(slots=True)
class InvestigationToolContext:
    """Transient model/tool exchange; never a production durability fallback."""

    identity: InvestigationIdentity
    inspection_result: InspectInstanceResult | None = None
    utilization_result: ReadUtilizationResult | None = None
    evidence_result: "EvidenceBuildResult | None" = None
    tool_calls: list[str] = field(default_factory=list)

    def record_inspection(self, result: InspectInstanceResult) -> None:
        self.tool_calls.append("inspect_instance")
        self.inspection_result = result

    def record_utilization(self, result: ReadUtilizationResult) -> None:
        self.tool_calls.append("read_utilization_metrics")
        self.utilization_result = result

    def record_evidence(self, result: "EvidenceBuildResult") -> None:
        self.tool_calls.append("build_remediation_evidence")
        self.evidence_result = result

    def inspection(self) -> InstanceInspection | None:
        if (
            self.inspection_result is not None
            and self.inspection_result.status is ResultStatus.SUCCESS
        ):
            return self.inspection_result.value
        return None

    def utilization(self) -> UtilizationEvidence | None:
        if (
            self.utilization_result is not None
            and self.utilization_result.status is ResultStatus.SUCCESS
        ):
            return self.utilization_result.value
        return None

    def evidence(self) -> "EvidenceBuildOutcome | None":
        if self.evidence_result is not None and self.evidence_result.status is ResultStatus.SUCCESS:
            return self.evidence_result.value
        return None

    def first_failure(self) -> FailureDetail | None:
        for result in (
            self.inspection_result,
            self.utilization_result,
            self.evidence_result,
        ):
            if result is not None and result.status is ResultStatus.FAILURE:
                return result.failure
        return None
