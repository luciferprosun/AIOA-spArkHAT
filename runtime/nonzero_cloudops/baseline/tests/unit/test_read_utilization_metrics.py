from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    Ec2MonitoringState,
    InstanceInspection,
    InvestigationIdentity,
    MetricStatistic,
    ReadUtilizationMetricsService,
    SandboxTarget,
    UtilizationClassification,
    UtilizationEvidence,
    create_read_utilization_metrics_tool,
    utilization_boundary,
)
from aioa_cloudops_agent.config import IdlePolicySettings
from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass, ContractValidationError
from aioa_cloudops_agent.nz import FailureKind, ResultStatus

INSTANCE_ID = "i-0123456789abcdef0"
OTHER_INSTANCE_ID = "i-0fedcba9876543210"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
COLLECTED_AT = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )


def _inspection(
    *,
    identity: InvestigationIdentity | None = None,
    instance_id: str = INSTANCE_ID,
    sandbox_tag_value: str = "true",
) -> InstanceInspection:
    return InstanceInspection.create(
        identity=identity or _identity(),
        instance_id=instance_id,
        region="eu-central-1",
        state=Ec2InstanceState.RUNNING,
        instance_type="t3.micro",
        launch_time=datetime(2026, 8, 23, 8, 0, tzinfo=UTC),
        monitoring_state=Ec2MonitoringState.DISABLED,
        availability_zone="eu-central-1a",
        sandbox_tag_key="AIOACloudOpsSandbox",
        sandbox_tag_value=sandbox_tag_value,
    )


def _datapoints(*values: object) -> list[dict[str, object]]:
    return [
        {
            "Timestamp": COLLECTED_AT - timedelta(minutes=5 * (index + 1)),
            "Average": value,
            "Unit": "Percent",
        }
        for index, value in enumerate(values)
    ]


class RecordingCloudWatchClient:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get_metric_statistics(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _service(
    response: object,
    *,
    policy: IdlePolicySettings | None = None,
) -> tuple[ReadUtilizationMetricsService, RecordingCloudWatchClient]:
    client = RecordingCloudWatchClient(response)
    return (
        ReadUtilizationMetricsService(
            client,
            SandboxTarget(instance_id=INSTANCE_ID),
            policy or IdlePolicySettings(),
        ),
        client,
    )


def test_sufficient_low_cpu_returns_typed_candidate_evidence() -> None:
    service, client = _service({"Datapoints": _datapoints(2, 4, 6, 8, 3, 5)})

    result = service.read_result(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.classification is UtilizationClassification.ELIGIBLE_CANDIDATE
    assert result.value.average_cpu_percent == pytest.approx(4.666667)
    assert result.value.datapoint_count == 6
    assert result.value.statistic is MetricStatistic.AVERAGE
    assert result.value.authority_gate is AuthorityGate.AUTO
    assert result.value.operation_class is AwsOperationClass.READ_ONLY
    assert client.calls == [
        {
            "Namespace": "AWS/EC2",
            "MetricName": "CPUUtilization",
            "Dimensions": [{"Name": "InstanceId", "Value": INSTANCE_ID}],
            "StartTime": COLLECTED_AT - timedelta(minutes=60),
            "EndTime": COLLECTED_AT,
            "Period": 300,
            "Statistics": ["Average"],
            "Unit": "Percent",
        }
    ]


def test_sufficient_high_cpu_returns_not_idle() -> None:
    service, _ = _service({"Datapoints": _datapoints(20, 15, 18, 21, 14, 12)})

    evidence = service.read(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert evidence.classification is UtilizationClassification.NOT_IDLE
    assert evidence.average_cpu_percent == pytest.approx(16.666667)


@pytest.mark.parametrize(
    ("values", "expected_count"),
    [
        ((), 0),
        ((1, 2, 3, 4, 5), 5),
    ],
)
def test_empty_or_insufficient_data_remains_ambiguous(
    values: tuple[int, ...],
    expected_count: int,
) -> None:
    service, _ = _service({"Datapoints": _datapoints(*values)})

    result = service.read_result(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.classification is UtilizationClassification.AMBIGUOUS
    assert result.value.datapoint_count == expected_count
    if expected_count == 0:
        assert result.value.average_cpu_percent is None


def test_out_of_window_or_duplicate_datapoints_fail_as_ambiguous_evidence() -> None:
    stale = {
        "Datapoints": [
            {
                "Timestamp": COLLECTED_AT - timedelta(hours=2),
                "Average": 1.0,
            }
        ]
    }
    duplicate_time = COLLECTED_AT - timedelta(minutes=5)
    duplicate = {
        "Datapoints": [
            {"Timestamp": duplicate_time, "Average": 1.0},
            {"Timestamp": duplicate_time, "Average": 2.0},
        ]
    }

    for response in (stale, duplicate):
        service, _ = _service(response)
        result = service.read_result(
            inspection=_inspection(),
            identity=_identity(),
            collected_at=COLLECTED_AT,
        )

        assert result.status is ResultStatus.FAILURE
        assert result.failure is not None
        assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
        assert result.value is None


@pytest.mark.parametrize("value", ["1.0", float("nan"), float("inf"), -1, 101, True])
def test_malformed_numeric_data_fails_explicitly(value: object) -> None:
    service, _ = _service({"Datapoints": _datapoints(value)})

    result = service.read_result(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT


def test_wrong_or_missing_cloudwatch_unit_fails_explicitly() -> None:
    for unit in (None, "Bytes"):
        response = {"Datapoints": _datapoints(1)}
        if unit is None:
            response["Datapoints"][0].pop("Unit")
        else:
            response["Datapoints"][0]["Unit"] = unit
        service, _ = _service(response)

        result = service.read_result(
            inspection=_inspection(),
            identity=_identity(),
            collected_at=COLLECTED_AT,
        )

        assert result.status is ResultStatus.FAILURE
        assert result.failure is not None
        assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT


@pytest.mark.parametrize(
    "response",
    [
        {"Datapoints": []},
        {
            "Datapoints": [
                {
                    "Timestamp": COLLECTED_AT - timedelta(minutes=5),
                    "Unit": "Percent",
                }
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": COLLECTED_AT - timedelta(hours=2),
                    "Average": 0.0,
                    "Unit": "Percent",
                }
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": COLLECTED_AT - timedelta(minutes=5),
                    "Average": 0.0,
                    "Unit": "Percent",
                },
                {
                    "Timestamp": COLLECTED_AT - timedelta(minutes=10),
                    "Average": 0.0,
                    "Unit": "Bytes",
                },
            ]
        },
        {
            "Datapoints": [
                {
                    "Timestamp": COLLECTED_AT - timedelta(minutes=5),
                    "Average": 0.0,
                    "Unit": "Percent",
                },
                {
                    "Timestamp": COLLECTED_AT - timedelta(minutes=5),
                    "Average": 99.0,
                    "Unit": "Percent",
                },
            ]
        },
    ],
    ids=("empty", "missing-average", "stale", "mixed-units", "contradictory"),
)
def test_cloudwatch_ambiguity_matrix_never_guesses_zero(
    response: dict[str, object],
) -> None:
    service, _ = _service(response)

    result = service.read_result(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    if result.status is ResultStatus.SUCCESS:
        assert result.value is not None
        assert result.value.classification is UtilizationClassification.AMBIGUOUS
        assert result.value.average_cpu_percent is None
        assert result.value.datapoint_count == 0
    else:
        assert result.failure is not None
        assert result.failure.kind is FailureKind.AMBIGUOUS_RESULT
        assert result.failure.code == "METRIC_EVIDENCE_INVALID"
        assert result.value is None


def test_cloudwatch_failure_is_sanitized_dependency_failure() -> None:
    service, _ = _service(RuntimeError("provider-secret-detail"))

    result = service.read_result(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert result.failure.retryable is False
    assert "provider-secret-detail" not in result.model_dump_json()


def test_target_or_identity_mismatch_fails_before_cloudwatch() -> None:
    service, client = _service({"Datapoints": []})
    other_identity = InvestigationIdentity(
        run_id=UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4a"),
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )

    identity_result = service.read_result(
        inspection=_inspection(),
        identity=other_identity,
        collected_at=COLLECTED_AT,
    )
    scope_result = service.read_result(
        inspection=_inspection(instance_id=OTHER_INSTANCE_ID),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    assert identity_result.failure is not None
    assert identity_result.failure.kind is FailureKind.POLICY_DENIAL
    assert scope_result.failure is not None
    assert scope_result.failure.kind is FailureKind.POLICY_DENIAL
    assert client.calls == []


def test_policy_defaults_and_environment_overrides_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    defaults = IdlePolicySettings()
    monkeypatch.setenv("IDLE_OBSERVATION_WINDOW_MINUTES", "30")
    monkeypatch.setenv("IDLE_METRIC_PERIOD_SECONDS", "300")
    monkeypatch.setenv("IDLE_MINIMUM_DATAPOINTS", "4")
    monkeypatch.setenv("IDLE_CPU_THRESHOLD_PERCENT", "7.5")

    override = IdlePolicySettings.from_environment()

    assert defaults == IdlePolicySettings(
        observation_window_minutes=60,
        period_seconds=300,
        minimum_datapoints=6,
        cpu_idle_threshold_percent=10.0,
    )
    assert override == IdlePolicySettings(
        observation_window_minutes=30,
        period_seconds=300,
        minimum_datapoints=4,
        cpu_idle_threshold_percent=7.5,
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"observation_window_minutes": 0},
        {"period_seconds": 30},
        {"minimum_datapoints": 13},
        {"cpu_idle_threshold_percent": -0.1},
        {"cpu_idle_threshold_percent": float("nan")},
    ],
)
def test_invalid_policy_configuration_fails_explicitly(settings: dict[str, object]) -> None:
    with pytest.raises(ContractValidationError):
        IdlePolicySettings(**settings)


def test_utilization_round_trip_preserves_ids_evidence_and_enums() -> None:
    service, _ = _service({"Datapoints": _datapoints(1, 2, 3, 4, 5, 6)})
    evidence = service.read(
        inspection=_inspection(),
        identity=_identity(),
        collected_at=COLLECTED_AT,
    )

    restored = UtilizationEvidence.model_validate_json(evidence.model_dump_json())

    assert restored == evidence
    assert restored.run_id == RUN_ID
    assert restored.trace_id == TRACE_ID
    assert restored.correlation_id == CORRELATION_ID
    assert restored.classification is UtilizationClassification.ELIGIBLE_CANDIDATE
    assert restored.statistic is MetricStatistic.AVERAGE
    assert len(restored.evidence_digest) == 64


class RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value


class SpanContext(AbstractContextManager[RecordingSpan]):
    def __init__(self, span: RecordingSpan) -> None:
        self.span = span

    def __enter__(self) -> RecordingSpan:
        return self.span

    def __exit__(self, *args: object) -> None:
        return None


class RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[RecordingSpan] = []

    def start_as_current_span(self, name: str) -> SpanContext:
        assert name == "cloudops.read_utilization_metrics"
        span = RecordingSpan()
        self.spans.append(span)
        return SpanContext(span)


def test_native_metrics_tool_has_minimal_schema_and_propagates_trace() -> None:
    service, _ = _service({"Datapoints": _datapoints(1, 2, 3, 4, 5, 6)})
    tracer = RecordingTracer()
    tool = create_read_utilization_metrics_tool(
        service,
        _inspection(),
        _identity(),
        clock=lambda: COLLECTED_AT,
        tracer=tracer,
    )

    result = tool(instance_id=INSTANCE_ID)
    schema = tool.tool_spec["inputSchema"]["json"]

    assert tool.tool_name == "read_utilization_metrics"
    assert schema["type"] == "object"
    assert set(schema["properties"]) == {"instance_id"}
    assert schema["required"] == ["instance_id"]
    assert result["status"] == "SUCCESS"
    assert result["value"]["run_id"] == str(RUN_ID)
    assert result["value"]["trace_id"] == str(TRACE_ID)
    assert result["value"]["correlation_id"] == str(CORRELATION_ID)
    assert tracer.spans[0].attributes["aioa.evidence_digest"] == result["value"][
        "evidence_digest"
    ]


def test_model_cannot_expand_metrics_scope_or_target() -> None:
    service, client = _service({"Datapoints": []})
    tool = create_read_utilization_metrics_tool(
        service,
        _inspection(),
        _identity(),
        clock=lambda: COLLECTED_AT,
    )

    denied = tool(instance_id=OTHER_INSTANCE_ID)
    with pytest.raises(TypeError):
        tool(
            instance_id=INSTANCE_ID,
            namespace="Custom/Attacker",
            region="us-east-1",
            statistic="Maximum",
        )

    assert denied["failure"]["kind"] == FailureKind.POLICY_DENIAL.value
    assert client.calls == []


def test_utilization_boundary_is_auto_read_only() -> None:
    assert utilization_boundary() == (AuthorityGate.AUTO, AwsOperationClass.READ_ONLY)


def test_cloudwatch_client_surface_has_no_write_capability() -> None:
    assert not hasattr(RecordingCloudWatchClient({}), "put_metric_data")
    assert not hasattr(RecordingCloudWatchClient({}), "put_metric_alarm")
    assert not hasattr(RecordingCloudWatchClient({}), "delete_alarms")
