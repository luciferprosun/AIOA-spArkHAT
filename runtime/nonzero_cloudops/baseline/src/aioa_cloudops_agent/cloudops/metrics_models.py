"""Typed CloudWatch utilization evidence and deterministic idle classification."""

from datetime import datetime, timedelta
from enum import StrEnum
from math import fsum, isclose
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass
from aioa_cloudops_agent.nz import ControlResult
from aioa_cloudops_agent.nz.identifiers import Sha256Digest, Uuid7Identifier
from aioa_cloudops_agent.persistence.models import compute_evidence_digest

from .models import CloudOpsContract, InvestigationIdentity, validate_instance_id


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value


class UtilizationClassification(StrEnum):
    """Deterministic outcome of the configured demo idle policy."""

    ELIGIBLE_CANDIDATE = "ELIGIBLE_CANDIDATE"
    NOT_IDLE = "NOT_IDLE"
    AMBIGUOUS = "AMBIGUOUS"


class MetricStatistic(StrEnum):
    """Only the currently justified CloudWatch statistic."""

    AVERAGE = "Average"


class MetricDatapoint(CloudOpsContract):
    """One normalized CPU utilization observation."""

    timestamp: datetime
    value_percent: float = Field(ge=0, le=100, allow_inf_nan=False)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _utc("datapoint timestamp", value)


class UtilizationEvidence(CloudOpsContract):
    """Auditable CloudWatch evidence with an application-owned classification."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    instance_id: str
    region: Literal["eu-central-1"]
    namespace: Literal["AWS/EC2"] = "AWS/EC2"
    metric_name: Literal["CPUUtilization"] = "CPUUtilization"
    statistic: MetricStatistic = MetricStatistic.AVERAGE
    unit: Literal["Percent"] = "Percent"
    window_start: datetime
    window_end: datetime
    period_seconds: int = Field(ge=60, le=3_600)
    minimum_datapoints: int = Field(gt=0)
    idle_threshold_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    datapoints: tuple[MetricDatapoint, ...]
    datapoint_count: int = Field(ge=0)
    average_cpu_percent: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    classification: UtilizationClassification
    collected_at: datetime
    evidence_digest: Sha256Digest
    authority_gate: AuthorityGate = AuthorityGate.AUTO
    operation_class: AwsOperationClass = AwsOperationClass.READ_ONLY

    @field_validator("instance_id")
    @classmethod
    def validate_metric_instance_id(cls, value: object) -> str:
        return validate_instance_id(value)

    @field_validator("window_start", "window_end", "collected_at")
    @classmethod
    def validate_timestamp(cls, value: datetime, info: object) -> datetime:
        return _utc(getattr(info, "field_name", "timestamp"), value)

    @model_validator(mode="after")
    def validate_evidence_integrity(self) -> Self:
        if self.window_start >= self.window_end:
            raise ValueError("metric window_start must precede window_end")
        if self.collected_at < self.window_end:
            raise ValueError("collected_at must not precede window_end")
        if self.datapoint_count != len(self.datapoints):
            raise ValueError("datapoint_count does not match datapoints")
        timestamps = tuple(point.timestamp for point in self.datapoints)
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            raise ValueError("datapoints must be uniquely and chronologically ordered")
        if any(not self.window_start <= point.timestamp <= self.window_end for point in self.datapoints):
            raise ValueError("datapoint is outside the requested metric window")
        expected_average = _average(self.datapoints)
        if expected_average is None:
            if self.average_cpu_percent is not None:
                raise ValueError("empty evidence cannot contain an average")
        elif self.average_cpu_percent is None or not isclose(
            self.average_cpu_percent,
            expected_average,
            abs_tol=1e-9,
        ):
            raise ValueError("average_cpu_percent does not match datapoints")
        expected_classification = _classification(
            datapoint_count=self.datapoint_count,
            minimum_datapoints=self.minimum_datapoints,
            average_cpu_percent=expected_average,
            threshold=self.idle_threshold_percent,
        )
        if self.classification is not expected_classification:
            raise ValueError("classification does not match deterministic idle policy")
        if self.authority_gate is not AuthorityGate.AUTO:
            raise ValueError("read_utilization_metrics authority must be AUTO")
        if self.operation_class is not AwsOperationClass.READ_ONLY:
            raise ValueError("read_utilization_metrics must be READ_ONLY")
        if self.evidence_digest != compute_evidence_digest(self.evidence_payload()):
            raise ValueError("evidence_digest does not match utilization evidence")
        return self

    @classmethod
    def create(
        cls,
        *,
        identity: InvestigationIdentity,
        instance_id: str,
        window_start: datetime,
        window_end: datetime,
        period_seconds: int,
        minimum_datapoints: int,
        idle_threshold_percent: float,
        datapoints: tuple[MetricDatapoint, ...],
        collected_at: datetime,
    ) -> "UtilizationEvidence":
        """Normalize points and apply the deterministic configured demo policy."""

        ordered = tuple(sorted(datapoints, key=lambda point: point.timestamp))
        average = _average(ordered)
        classification = _classification(
            datapoint_count=len(ordered),
            minimum_datapoints=minimum_datapoints,
            average_cpu_percent=average,
            threshold=idle_threshold_percent,
        )
        values: dict[str, object] = {
            "run_id": identity.run_id,
            "trace_id": identity.trace_id,
            "correlation_id": identity.correlation_id,
            "instance_id": instance_id,
            "region": "eu-central-1",
            "window_start": window_start,
            "window_end": window_end,
            "period_seconds": period_seconds,
            "minimum_datapoints": minimum_datapoints,
            "idle_threshold_percent": float(idle_threshold_percent),
            "datapoints": ordered,
            "datapoint_count": len(ordered),
            "average_cpu_percent": average,
            "classification": classification,
            "collected_at": collected_at,
        }
        provisional = cls.model_construct(**values, evidence_digest="0" * 64)
        values["evidence_digest"] = compute_evidence_digest(provisional.evidence_payload())
        return cls.model_validate(values)

    def evidence_payload(self) -> dict[str, object]:
        """Return canonical decision-relevant evidence for SHA-256 hashing."""

        return {
            "authority_gate": self.authority_gate.value,
            "average_cpu_percent": self.average_cpu_percent,
            "classification": self.classification.value,
            "collected_at": self.collected_at.isoformat(),
            "correlation_id": str(self.correlation_id),
            "datapoints": [
                {
                    "timestamp": point.timestamp.isoformat(),
                    "value_percent": point.value_percent,
                }
                for point in self.datapoints
            ],
            "idle_threshold_percent": self.idle_threshold_percent,
            "instance_id": self.instance_id,
            "metric_name": self.metric_name,
            "minimum_datapoints": self.minimum_datapoints,
            "namespace": self.namespace,
            "operation_class": self.operation_class.value,
            "period_seconds": self.period_seconds,
            "region": self.region,
            "run_id": str(self.run_id),
            "statistic": self.statistic.value,
            "trace_id": str(self.trace_id),
            "unit": self.unit,
            "window_end": self.window_end.isoformat(),
            "window_start": self.window_start.isoformat(),
        }


def _average(datapoints: tuple[MetricDatapoint, ...]) -> float | None:
    if not datapoints:
        return None
    return round(fsum(point.value_percent for point in datapoints) / len(datapoints), 6)


def _classification(
    *,
    datapoint_count: int,
    minimum_datapoints: int,
    average_cpu_percent: float | None,
    threshold: float,
) -> UtilizationClassification:
    if datapoint_count < minimum_datapoints or average_cpu_percent is None:
        return UtilizationClassification.AMBIGUOUS
    if average_cpu_percent <= threshold:
        return UtilizationClassification.ELIGIBLE_CANDIDATE
    return UtilizationClassification.NOT_IDLE


ReadUtilizationResult = ControlResult[UtilizationEvidence]
