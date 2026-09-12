"""Fail-closed CloudWatch CPU utilization collection for one sandbox instance."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from math import isfinite
from typing import Final

from aioa_cloudops_agent.config import IdlePolicySettings
from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass, ContractValidationError
from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind
from aioa_cloudops_agent.safety import CircuitOpenError, CircuitStateUnavailableError
from aioa_cloudops_agent.safety.retry import BoundedReadRetry, is_known_transient_read_error

from .cloudwatch_readonly import CloudWatchGetMetricStatisticsClient
from .metrics_models import (
    MetricDatapoint,
    ReadUtilizationResult,
    UtilizationEvidence,
)
from .models import InstanceInspection, InvestigationIdentity, SandboxTarget

READ_UTILIZATION_AWS_API: Final = "cloudwatch:GetMetricStatistics"


class UtilizationScopeError(ValueError):
    """Raised when metrics are requested outside the proven sandbox target."""


class UtilizationDependencyError(RuntimeError):
    """Raised when CloudWatch cannot provide the requested observation."""

    def __init__(
        self,
        message: str,
        *,
        failure_code: str = "CLOUDWATCH_UNAVAILABLE",
        retryable: bool = True,
    ) -> None:
        self.message = message
        self.failure_code = failure_code
        self.retryable = retryable
        super().__init__(message)


class UtilizationEvidenceError(ValueError):
    """Raised when provider evidence is malformed, stale, or ambiguous."""


def _utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ContractValidationError(f"{name} must be a timezone-aware UTC datetime")
    if value.utcoffset() != timedelta(0):
        raise ContractValidationError(f"{name} must use UTC")
    return value


class ReadUtilizationMetricsService:
    """Read one fixed CloudWatch metric after exact inspection proof."""

    def __init__(
        self,
        client: CloudWatchGetMetricStatisticsClient,
        target: SandboxTarget,
        policy: IdlePolicySettings,
        *,
        retry: BoundedReadRetry | None = None,
    ) -> None:
        if not isinstance(target, SandboxTarget):
            raise ContractValidationError("target must be a SandboxTarget")
        if not isinstance(policy, IdlePolicySettings):
            raise ContractValidationError("policy must be IdlePolicySettings")
        self._client = client
        self._target = target
        self._policy = policy
        self._retry = retry or BoundedReadRetry()

    def read(
        self,
        *,
        inspection: InstanceInspection,
        identity: InvestigationIdentity,
        collected_at: datetime,
    ) -> UtilizationEvidence:
        """Return normalized CPU evidence without allowing metric or target expansion."""

        if not isinstance(inspection, InstanceInspection):
            raise ContractValidationError("inspection must be an InstanceInspection")
        if not isinstance(identity, InvestigationIdentity):
            raise ContractValidationError("identity must be an InvestigationIdentity")
        if (
            inspection.run_id != identity.run_id
            or inspection.trace_id != identity.trace_id
            or inspection.correlation_id != identity.correlation_id
        ):
            raise UtilizationScopeError("inspection identity does not match this run")
        if (
            inspection.instance_id != self._target.instance_id
            or inspection.region != self._target.region
            or inspection.sandbox_tag_key != self._target.required_tag_key
            or inspection.sandbox_tag_value != self._target.required_tag_value
        ):
            raise UtilizationScopeError("inspection does not prove the configured sandbox")
        end_time = _utc("collected_at", collected_at)
        start_time = end_time - timedelta(minutes=self._policy.observation_window_minutes)
        try:
            response = self._retry.run(
                lambda: self._client.get_metric_statistics(
                    Namespace="AWS/EC2",
                    MetricName="CPUUtilization",
                    Dimensions=[{"Name": "InstanceId", "Value": inspection.instance_id}],
                    StartTime=start_time,
                    EndTime=end_time,
                    Period=self._policy.period_seconds,
                    Statistics=["Average"],
                    Unit="Percent",
                )
            )
        except CircuitOpenError as error:
            raise UtilizationDependencyError(
                "CloudWatch read is suppressed by the dependency circuit",
                failure_code="CLOUDWATCH_READ_CIRCUIT_OPEN",
                retryable=False,
            ) from error
        except CircuitStateUnavailableError as error:
            raise UtilizationDependencyError(
                "CloudWatch dependency circuit state is unavailable",
                failure_code="CLOUDWATCH_READ_CIRCUIT_UNAVAILABLE",
                retryable=False,
            ) from error
        except Exception as error:
            raise UtilizationDependencyError(
                "CloudWatch utilization dependency is unavailable",
                retryable=is_known_transient_read_error(error),
            ) from error
        datapoints = self._normalize_datapoints(
            response,
            window_start=start_time,
            window_end=end_time,
        )
        return UtilizationEvidence.create(
            identity=identity,
            instance_id=inspection.instance_id,
            window_start=start_time,
            window_end=end_time,
            period_seconds=self._policy.period_seconds,
            minimum_datapoints=self._policy.minimum_datapoints,
            idle_threshold_percent=self._policy.cpu_idle_threshold_percent,
            datapoints=datapoints,
            collected_at=end_time,
        )

    def read_result(
        self,
        *,
        inspection: InstanceInspection,
        identity: InvestigationIdentity,
        collected_at: datetime,
    ) -> ReadUtilizationResult:
        """Return explicit policy/dependency/ambiguity failures to Strands."""

        try:
            evidence = self.read(
                inspection=inspection,
                identity=identity,
                collected_at=collected_at,
            )
        except UtilizationScopeError as error:
            return ControlResult[UtilizationEvidence].failed(
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="METRIC_SCOPE_DENIED",
                    message=str(error),
                    retryable=False,
                )
            )
        except UtilizationDependencyError as error:
            return ControlResult[UtilizationEvidence].failed(
                FailureDetail(
                    kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                    code=error.failure_code,
                    message=str(error),
                    retryable=error.retryable,
                )
            )
        except (ContractValidationError, UtilizationEvidenceError) as error:
            return ControlResult[UtilizationEvidence].failed(
                FailureDetail(
                    kind=FailureKind.AMBIGUOUS_RESULT,
                    code="METRIC_EVIDENCE_INVALID",
                    message=str(error),
                    retryable=False,
                )
            )
        return ControlResult[UtilizationEvidence].succeeded(evidence)

    @staticmethod
    def _normalize_datapoints(
        response: object,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[MetricDatapoint, ...]:
        if not isinstance(response, Mapping):
            raise UtilizationEvidenceError("CloudWatch response is malformed")
        raw_points = response.get("Datapoints")
        if not isinstance(raw_points, list):
            raise UtilizationEvidenceError("CloudWatch Datapoints is missing or malformed")
        normalized: list[MetricDatapoint] = []
        for raw_point in raw_points:
            if not isinstance(raw_point, Mapping):
                raise UtilizationEvidenceError("CloudWatch datapoint is malformed")
            timestamp = raw_point.get("Timestamp")
            value = raw_point.get("Average")
            unit = raw_point.get("Unit")
            if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
                raise UtilizationEvidenceError("CloudWatch datapoint timestamp is malformed")
            if timestamp.utcoffset() != timedelta(0):
                raise UtilizationEvidenceError("CloudWatch datapoint timestamp must use UTC")
            if not window_start <= timestamp <= window_end:
                raise UtilizationEvidenceError(
                    "CloudWatch datapoint is outside the requested window"
                )
            if unit != "Percent":
                raise UtilizationEvidenceError("CloudWatch datapoint unit is not Percent")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not isfinite(float(value))
            ):
                raise UtilizationEvidenceError("CloudWatch CPU value is malformed")
            try:
                normalized.append(MetricDatapoint(timestamp=timestamp, value_percent=float(value)))
            except ValueError as error:
                raise UtilizationEvidenceError("CloudWatch CPU value is outside bounds") from error
        normalized.sort(key=lambda point: point.timestamp)
        timestamps = [point.timestamp for point in normalized]
        if len(set(timestamps)) != len(timestamps):
            raise UtilizationEvidenceError("CloudWatch datapoints contain duplicate timestamps")
        return tuple(normalized)


def utilization_boundary() -> tuple[AuthorityGate, AwsOperationClass]:
    """Expose the immutable authority classification for static verification."""

    return AuthorityGate.AUTO, AwsOperationClass.READ_ONLY
