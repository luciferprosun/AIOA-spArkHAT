"""Deterministic evidence evaluation for a future sandbox stop proposal."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from aioa_cloudops_agent.domain import AuthorityGate, ContractValidationError
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionTarget,
    Capability,
    ControlResult,
    ExpectedPrecondition,
    FailureDetail,
    FailureKind,
    ObservedInstanceState,
)
from aioa_cloudops_agent.persistence import compute_evidence_digest

from .evidence_models import (
    EvidenceBuildOutcome,
    EvidenceBuildResult,
    EvidenceDecision,
    RemediationEvidenceBundle,
)
from .metrics_models import UtilizationClassification, UtilizationEvidence
from .models import Ec2InstanceState, InstanceInspection, InvestigationIdentity, SandboxTarget


class EvidenceScopeError(ValueError):
    """Raised when evidence does not prove the configured sandbox and run."""


class EvidenceAmbiguousError(ValueError):
    """Raised when deterministic policy lacks sufficient decision evidence."""


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractValidationError("built_at must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ContractValidationError("built_at must use UTC")
    return value


class BuildRemediationEvidenceService:
    """Build local evidence and a non-authorizing proposal from typed tool results."""

    def __init__(self, target: SandboxTarget, *, sandbox_scope: str = "hackathon-sandbox") -> None:
        if not isinstance(target, SandboxTarget):
            raise ContractValidationError("target must be a SandboxTarget")
        if not isinstance(sandbox_scope, str) or not sandbox_scope:
            raise ContractValidationError("sandbox_scope must be a non-empty string")
        self._target = target
        self._sandbox_scope = sandbox_scope

    def build(
        self,
        *,
        inspection: InstanceInspection,
        utilization: UtilizationEvidence,
        identity: InvestigationIdentity,
        proposal_id: UUID,
        built_at: datetime,
    ) -> EvidenceBuildOutcome:
        """Return a fixed-action proposal only for deterministic eligible evidence."""

        if not isinstance(inspection, InstanceInspection):
            raise ContractValidationError("inspection must be typed evidence")
        if not isinstance(utilization, UtilizationEvidence):
            raise ContractValidationError("utilization must be typed evidence")
        if not isinstance(identity, InvestigationIdentity):
            raise ContractValidationError("identity must be an InvestigationIdentity")
        if not isinstance(proposal_id, UUID):
            raise ContractValidationError("proposal_id must be UUIDv7")
        validate_correlation_id(proposal_id)
        identity_values = (identity.run_id, identity.trace_id, identity.correlation_id)
        if (
            (inspection.run_id, inspection.trace_id, inspection.correlation_id)
            != identity_values
            or (utilization.run_id, utilization.trace_id, utilization.correlation_id)
            != identity_values
        ):
            raise EvidenceScopeError("evidence identity does not match the active run")
        if (
            inspection.instance_id != self._target.instance_id
            or utilization.instance_id != self._target.instance_id
            or inspection.region != self._target.region
            or utilization.region != self._target.region
            or inspection.sandbox_tag_key != self._target.required_tag_key
            or inspection.sandbox_tag_value != self._target.required_tag_value
        ):
            raise EvidenceScopeError("evidence does not prove the configured sandbox")
        if utilization.classification is UtilizationClassification.AMBIGUOUS:
            raise EvidenceAmbiguousError("utilization evidence is insufficient or ambiguous")

        created_at = _utc(built_at)
        proposal_ready = (
            utilization.classification is UtilizationClassification.ELIGIBLE_CANDIDATE
            and inspection.state is Ec2InstanceState.RUNNING
        )
        decision = (
            EvidenceDecision.PROPOSAL_READY
            if proposal_ready
            else EvidenceDecision.NOT_ELIGIBLE
        )
        summary = self._summary(inspection, utilization, decision)
        values: dict[str, object] = {
            "run_id": identity.run_id,
            "trace_id": identity.trace_id,
            "correlation_id": identity.correlation_id,
            "instance_id": inspection.instance_id,
            "region": inspection.region,
            "instance_state": inspection.state,
            "instance_evidence_digest": inspection.evidence_digest,
            "utilization_evidence_digest": utilization.evidence_digest,
            "utilization_classification": utilization.classification,
            "observation_window_start": utilization.window_start,
            "observation_window_end": utilization.window_end,
            "datapoint_count": utilization.datapoint_count,
            "average_cpu_percent": utilization.average_cpu_percent,
            "idle_threshold_percent": utilization.idle_threshold_percent,
            "summary": summary,
            "created_at": created_at,
        }
        provisional = RemediationEvidenceBundle.model_construct(
            **values,
            evidence_hash="0" * 64,
        )
        values["evidence_hash"] = compute_evidence_digest(provisional.evidence_payload())
        evidence = RemediationEvidenceBundle.model_validate(values)
        proposal = None
        if proposal_ready:
            proposal = ActionProposal(
                proposal_id=proposal_id,
                run_id=identity.run_id,
                action=Capability.STOP_SANDBOX_INSTANCE,
                target=ActionTarget(
                    resource_id=inspection.instance_id,
                    region=inspection.region,
                    sandbox_scope=self._sandbox_scope,
                    required_tag_key=inspection.sandbox_tag_key,
                    required_tag_value=inspection.sandbox_tag_value,
                ),
                expected_precondition=ExpectedPrecondition(
                    instance_state=ObservedInstanceState.RUNNING,
                    observed_at=utilization.collected_at,
                    evidence_hash=evidence.evidence_hash,
                ),
                authority=AuthorityGate.PLAN_AND_CONFIRM,
                evidence_hash=evidence.evidence_hash,
                created_at=created_at,
            )
        return EvidenceBuildOutcome(
            decision=decision,
            evidence=evidence,
            proposal=proposal,
        )

    def build_result(
        self,
        **kwargs: object,
    ) -> EvidenceBuildResult:
        """Map deterministic evidence failures into explicit control results."""

        try:
            outcome = self.build(**kwargs)  # type: ignore[arg-type]
        except EvidenceScopeError as error:
            return ControlResult[EvidenceBuildOutcome].failed(
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="EVIDENCE_SCOPE_DENIED",
                    message=str(error),
                    retryable=False,
                )
            )
        except EvidenceAmbiguousError as error:
            return ControlResult[EvidenceBuildOutcome].failed(
                FailureDetail(
                    kind=FailureKind.AMBIGUOUS_RESULT,
                    code="EVIDENCE_AMBIGUOUS",
                    message=str(error),
                    retryable=False,
                )
            )
        except (ContractValidationError, TypeError, ValidationError, ValueError):
            return ControlResult[EvidenceBuildOutcome].failed(
                FailureDetail(
                    kind=FailureKind.VALIDATION_FAILURE,
                    code="EVIDENCE_INVALID",
                    message="Evidence contracts are invalid",
                    retryable=False,
                )
            )
        return ControlResult[EvidenceBuildOutcome].succeeded(outcome)

    @staticmethod
    def _summary(
        inspection: InstanceInspection,
        utilization: UtilizationEvidence,
        decision: EvidenceDecision,
    ) -> str:
        average = (
            "unavailable"
            if utilization.average_cpu_percent is None
            else f"{utilization.average_cpu_percent:.6f}%"
        )
        return (
            f"{decision.value}: sandbox instance {inspection.instance_id} is "
            f"{inspection.state.value}; average CPU {average} across "
            f"{utilization.datapoint_count} datapoints with configured threshold "
            f"{utilization.idle_threshold_percent:.6f}%."
        )
