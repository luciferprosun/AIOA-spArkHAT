"""Typed local evidence bundle for a future human-confirmed remediation."""

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass, ContractValidationError
from aioa_cloudops_agent.nz import ActionProposal, ControlResult
from aioa_cloudops_agent.nz.identifiers import Sha256Digest, Uuid7Identifier
from aioa_cloudops_agent.persistence import compute_evidence_digest

from .metrics_models import UtilizationClassification
from .models import CloudOpsContract, Ec2InstanceState, validate_instance_id


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value


class EvidenceDecision(StrEnum):
    """Deterministic proposal outcome from validated read-only evidence."""

    PROPOSAL_READY = "PROPOSAL_READY"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class RemediationEvidenceBundle(CloudOpsContract):
    """Canonical decision evidence without raw provider responses or secrets."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    instance_id: str
    region: Literal["eu-central-1"]
    instance_state: Ec2InstanceState
    instance_evidence_digest: Sha256Digest
    utilization_evidence_digest: Sha256Digest
    utilization_classification: UtilizationClassification
    observation_window_start: datetime
    observation_window_end: datetime
    datapoint_count: int = Field(ge=0)
    average_cpu_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    idle_threshold_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    summary: str = Field(min_length=1, max_length=512)
    created_at: datetime
    evidence_hash: Sha256Digest
    authority_gate: AuthorityGate = AuthorityGate.AUTO
    operation_class: AwsOperationClass = AwsOperationClass.READ_ONLY

    @field_validator("instance_id")
    @classmethod
    def validate_bundle_instance_id(cls, value: object) -> str:
        try:
            return validate_instance_id(value)
        except ContractValidationError as error:
            raise ValueError("instance_id is invalid") from error

    @field_validator(
        "observation_window_start",
        "observation_window_end",
        "created_at",
    )
    @classmethod
    def validate_timestamp(cls, value: datetime, info: object) -> datetime:
        return _utc(getattr(info, "field_name", "timestamp"), value)

    @model_validator(mode="after")
    def validate_bundle_integrity(self) -> Self:
        if self.observation_window_start >= self.observation_window_end:
            raise ValueError("observation window is invalid")
        if self.created_at < self.observation_window_end:
            raise ValueError("evidence cannot predate the observation window")
        if self.utilization_classification is UtilizationClassification.AMBIGUOUS:
            raise ValueError("ambiguous utilization cannot form remediation evidence")
        if self.authority_gate is not AuthorityGate.AUTO:
            raise ValueError("evidence construction authority must be AUTO")
        if self.operation_class is not AwsOperationClass.READ_ONLY:
            raise ValueError("evidence construction must have no external side effect")
        if self.evidence_hash != compute_evidence_digest(self.evidence_payload()):
            raise ValueError("evidence_hash does not match canonical evidence")
        return self

    def evidence_payload(self) -> dict[str, object]:
        """Return the stable JSON-compatible evidence used for SHA-256 hashing."""

        return {
            "authority_gate": self.authority_gate.value,
            "average_cpu_percent": self.average_cpu_percent,
            "correlation_id": str(self.correlation_id),
            "datapoint_count": self.datapoint_count,
            "idle_threshold_percent": self.idle_threshold_percent,
            "instance_evidence_digest": self.instance_evidence_digest,
            "instance_id": self.instance_id,
            "instance_state": self.instance_state.value,
            "observation_window_end": self.observation_window_end.isoformat(),
            "observation_window_start": self.observation_window_start.isoformat(),
            "operation_class": self.operation_class.value,
            "region": self.region,
            "run_id": str(self.run_id),
            "summary": self.summary,
            "trace_id": str(self.trace_id),
            "utilization_classification": self.utilization_classification.value,
            "utilization_evidence_digest": self.utilization_evidence_digest,
        }


class EvidenceBuildOutcome(CloudOpsContract):
    """Explicit proposal/non-proposal result from deterministic evidence policy."""

    decision: EvidenceDecision
    evidence: RemediationEvidenceBundle
    proposal: ActionProposal | None = None

    @model_validator(mode="after")
    def validate_proposal_boundary(self) -> Self:
        if self.decision is EvidenceDecision.PROPOSAL_READY:
            if self.proposal is None:
                raise ValueError("proposal-ready evidence requires a typed proposal")
            if self.proposal.evidence_hash != self.evidence.evidence_hash:
                raise ValueError("proposal must reference the exact evidence hash")
            if self.proposal.authorizes_execution:
                raise ValueError("proposal must never authorize execution")
        elif self.proposal is not None:
            raise ValueError("non-eligible evidence must not contain a proposal")
        return self


EvidenceBuildResult = ControlResult[EvidenceBuildOutcome]
