import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from strands.session import SnapshotSessionManager
from strands.storage import InMemoryStorage

from aioa_cloudops_agent.cloudops import SandboxTarget
from aioa_cloudops_agent.config import (
    BedrockSettings,
    DynamoDbSettings,
    IdlePolicySettings,
)
from aioa_cloudops_agent.deployment import (
    DynamoDbJudgeQuotaRepository,
    DynamoDbStatusObservationLimiter,
    JudgeInvestigationRequest,
    JudgeRuntimeSettings,
)
from aioa_cloudops_agent.judge import (
    JudgeErrorCode,
    JudgeInvestigationRuntime,
    JudgeOutcomeClass,
    JudgeRuntimeDependencies,
)
from aioa_cloudops_agent.judge.composition import (
    BoundedReadinessProbe,
    JudgeProcessResources,
    build_request_services,
)
from aioa_cloudops_agent.judge.control_plane import JudgePrivateControlPlane
from aioa_cloudops_agent.judge.quota import (
    DynamoDbReadinessProbeQuotaRepository,
    DynamoDbStatusRequestQuotaRepository,
)
from aioa_cloudops_agent.judge.telemetry import SanitizedXRaySpanExporter
from aioa_cloudops_agent.nz import (
    ControlResult,
    FailureDetail,
    FailureKind,
    ResultStatus,
    WorkflowState,
)
from aioa_cloudops_agent.recovery import RecoveryCoordinator
from aioa_cloudops_agent.remediation import StopSandboxInstanceCoordinator
from aioa_cloudops_agent.safety import DependencyCircuitBreaker
from aioa_cloudops_agent.verification import BoundedVerificationCoordinator

NOW = datetime(2026, 8, 24, 14, 0, tzinfo=UTC)
IDS = tuple(
    UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{value:02x}")
    for value in range(48, 80)
)


def _settings() -> JudgeRuntimeSettings:
    account_id = "1" * 12
    return JudgeRuntimeSettings(
        stage="hackathon",
        state_table=DynamoDbSettings(table_name="aioa-state"),
        target=SandboxTarget(instance_id="i-0123456789abcdef0"),
        bedrock=BedrockSettings(),
        idle_policy=IdlePolicySettings(),
        private_executor_alias_arn=(
            f"arn:aws:lambda:eu-central-1:{account_id}:function:private-executor:live"
        ),
        judge_token_secret_arn=(
            f"arn:aws:secretsmanager:eu-central-1:{account_id}:secret:judge"
        ),
        judge_token_not_after=NOW + timedelta(hours=1),
    )


class IdFactory:
    def __init__(self, values: tuple[UUID, ...]) -> None:
        self.values = iter(values)

    def __call__(self) -> UUID:
        return next(self.values)


class Flow:
    def __init__(self, proposal_id: UUID) -> None:
        self.proposal_id = proposal_id
        self.runs: list[object] = []

    def execute(self, run: object) -> object:
        self.runs.append(run)
        return SimpleNamespace(
            status=ResultStatus.SUCCESS,
            value=SimpleNamespace(
                final_state=WorkflowState.REMEDIATION_PROPOSED,
                proposal=SimpleNamespace(
                    proposal_id=self.proposal_id,
                    evidence_hash="a" * 64,
                ),
            ),
        )


def test_runtime_emits_real_allowlisted_operation_span_without_sensitive_values() -> None:
    memory_exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory_exporter))
    tracer = provider.get_tracer("day15-runtime-test")
    xray_calls: list[dict[str, object]] = []

    class XRayClient:
        def put_trace_segments(self, **kwargs: object) -> dict[str, object]:
            xray_calls.append(kwargs)
            return {}

    runtime = JudgeInvestigationRuntime(
        JudgeRuntimeDependencies(
            settings=_settings(),
            repository=object(),
            snapshot_storage=InMemoryStorage(),
            ec2_client=object(),
            cloudwatch_client=object(),
            bedrock_session=object(),
            dependency_circuit=DependencyCircuitBreaker(),
            stop_request_handler=lambda _proposal_id: {},
            verification_request_handler=lambda _proposal_id: {},
        ),
        clock=lambda: NOW,
        run_id_factory=IdFactory(IDS[0:1]),
        trace_id_factory=IdFactory(IDS[1:2]),
        correlation_id_factory=IdFactory(IDS[2:3]),
        proposal_id_factory=IdFactory(IDS[3:4]),
        event_id_factory=IdFactory(IDS[8:]),
        session_manager_factory=lambda _session_id, _storage: object(),
        model_factory=lambda _settings, _session: object(),
        agent_factory=lambda **_kwargs: SimpleNamespace(agent=object()),
        flow_factory=lambda *_args, **_kwargs: Flow(IDS[3]),
        tracer=tracer,
    )

    try:
        outcome = runtime.investigate(
            JudgeInvestigationRequest(intent="investigate_idle_sandbox")
        )
        spans = memory_exporter.get_finished_spans()

        assert outcome.succeeded is True
        assert len(spans) == 1
        assert spans[0].attributes == {
            "aioa.run_id": str(IDS[0]),
            "aioa.trace_id": str(IDS[1]),
            "aioa.correlation_id": str(IDS[2]),
            "aioa.route": "/judge/investigate",
            "aioa.outcome": "remediation_proposed",
            "aioa.dependency": "BEDROCK_MODEL",
        }
        assert SanitizedXRaySpanExporter(XRayClient()).export(spans) is (
            SpanExportResult.SUCCESS
        )
        documents = xray_calls[0]["TraceSegmentDocuments"]
        assert isinstance(documents, list) and len(documents) == 1
        rendered = documents[0]
        assert isinstance(rendered, str)
        assert json.loads(rendered)["annotations"] == {
            "correlation_id": str(IDS[2]),
            "dependency": "BEDROCK_MODEL",
            "outcome": "remediation_proposed",
            "route": "/judge/investigate",
            "run_id": str(IDS[0]),
            "trace_id": str(IDS[1]),
        }
        for sensitive in (
            _settings().target.instance_id,
            "authorization",
            "nonce",
            "prompt",
            "provider",
            "secret",
        ):
            assert sensitive not in rendered.casefold()
    finally:
        provider.shutdown()


def test_each_investigation_builds_fresh_snapshot_session_agent_and_server_budget() -> None:
    storage = InMemoryStorage()
    repository = object()
    agent_calls: list[dict[str, Any]] = []
    sessions: list[tuple[str, object]] = []
    flows: list[Flow] = []
    model_calls: list[tuple[object, object]] = []
    run_ids = (IDS[0], IDS[4])
    trace_ids = (IDS[1], IDS[5])
    correlation_ids = (IDS[2], IDS[6])
    proposal_ids = (IDS[3], IDS[7])

    def session_manager_factory(session_id: str, actual_storage: object) -> object:
        session = SimpleNamespace(session_id=session_id)
        sessions.append((session_id, session))
        assert actual_storage is storage
        return session

    def model_factory(settings: object, session: object) -> object:
        model_calls.append((settings, session))
        return object()

    def agent_factory(**kwargs: Any) -> object:
        agent_calls.append(kwargs)
        return SimpleNamespace(agent=object())

    def flow_factory(runtime: object, actual_repository: object, **kwargs: Any) -> Flow:
        assert actual_repository is repository
        assert runtime is not None
        assert set(kwargs) == {"clock", "event_id_factory"}
        flow = Flow(agent_calls[-1]["proposal_id"])
        flows.append(flow)
        return flow

    bedrock_session = object()
    dependency_circuit = DependencyCircuitBreaker()

    def stop_handler(_proposal_id: UUID) -> dict[str, object]:
        return {"status": "denied"}

    def verification_handler(_proposal_id: UUID) -> dict[str, object]:
        return {"status": "denied"}

    runtime = JudgeInvestigationRuntime(
        JudgeRuntimeDependencies(
            settings=_settings(),
            repository=repository,
            snapshot_storage=storage,
            ec2_client=object(),
            cloudwatch_client=object(),
            bedrock_session=bedrock_session,
            dependency_circuit=dependency_circuit,
            stop_request_handler=stop_handler,
            verification_request_handler=verification_handler,
        ),
        clock=lambda: NOW,
        run_id_factory=IdFactory(run_ids),
        trace_id_factory=IdFactory(trace_ids),
        correlation_id_factory=IdFactory(correlation_ids),
        proposal_id_factory=IdFactory(proposal_ids),
        event_id_factory=IdFactory(IDS[8:]),
        session_manager_factory=session_manager_factory,
        model_factory=model_factory,
        agent_factory=agent_factory,
        flow_factory=flow_factory,
    )
    request = JudgeInvestigationRequest(intent="investigate_idle_sandbox")

    first = runtime.investigate(request)
    second = runtime.investigate(request)

    assert first.succeeded and second.succeeded
    assert len(agent_calls) == len(sessions) == len(model_calls) == len(flows) == 2
    assert sessions[0][1] is not sessions[1][1]
    assert sessions[0][0] == f"judge-{run_ids[0]}"
    assert sessions[1][0] == f"judge-{run_ids[1]}"
    for index, call in enumerate(agent_calls):
        context = call["context"]
        identity = call["identity"]
        assert (context.budget.max_turns, context.budget.max_tokens) == (8, 8192)
        assert context.correlation_id == identity.correlation_id == correlation_ids[index]
        assert call["target"] == _settings().target
        assert call["model_settings"].model_id == "eu.amazon.nova-2-lite-v1:0"
        assert call["model_settings"].region == "eu-central-1"
        assert call["session_manager"] is sessions[index][1]
        assert call["dependency_circuit"] is dependency_circuit
        assert call["stop_request_handler"] is stop_handler
        assert call["verification_request_handler"] is verification_handler
        run = flows[index].runs[0]
        assert run.budget.max_turns == 8
        assert run.budget.max_tokens == 8192
        assert run.budget.max_elapsed_seconds == 60
    assert all(session is bedrock_session for _, session in model_calls)


def test_default_session_factory_is_snapshot_manager_with_no_agent_reuse() -> None:
    agent_sessions: list[object] = []

    def agent_factory(**kwargs: Any) -> object:
        agent_sessions.append(kwargs["session_manager"])
        return SimpleNamespace(agent=object())

    def flow_factory(_runtime: object, _repository: object, **_kwargs: Any) -> Flow:
        return Flow(IDS[3])

    runtime = JudgeInvestigationRuntime(
        JudgeRuntimeDependencies(
            settings=_settings(),
            repository=object(),
            snapshot_storage=InMemoryStorage(),
            ec2_client=object(),
            cloudwatch_client=object(),
            bedrock_session=object(),
            dependency_circuit=DependencyCircuitBreaker(),
            stop_request_handler=lambda _proposal_id: {},
            verification_request_handler=lambda _proposal_id: {},
        ),
        clock=lambda: NOW,
        run_id_factory=IdFactory(IDS[0:1]),
        trace_id_factory=IdFactory(IDS[1:2]),
        correlation_id_factory=IdFactory(IDS[2:3]),
        proposal_id_factory=IdFactory(IDS[3:4]),
        event_id_factory=IdFactory(IDS[8:]),
        model_factory=lambda _settings, _session: object(),
        agent_factory=agent_factory,
        flow_factory=flow_factory,
    )

    result = runtime.investigate(
        JudgeInvestigationRequest(intent="investigate_idle_sandbox")
    )

    assert result.succeeded
    assert len(agent_sessions) == 1
    assert isinstance(agent_sessions[0], SnapshotSessionManager)


@pytest.mark.parametrize(
    ("kind", "code", "outcome"),
    (
        (
            FailureKind.DEPENDENCY_UNAVAILABLE,
            JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
            JudgeOutcomeClass.DEPENDENCY_UNAVAILABLE,
        ),
        (
            FailureKind.BUDGET_EXHAUSTION,
            JudgeErrorCode.BUDGET_EXHAUSTED,
            JudgeOutcomeClass.BUDGET_EXHAUSTED,
        ),
        (
            FailureKind.RECOVERY_REQUIREMENT,
            JudgeErrorCode.RECOVERY_REQUIRED,
            JudgeOutcomeClass.RECOVERY_REQUIRED,
        ),
        (
            FailureKind.VALIDATION_FAILURE,
            JudgeErrorCode.INVESTIGATION_INVALID,
            JudgeOutcomeClass.CLOSED_NON_SUCCESS,
        ),
        (
            FailureKind.AMBIGUOUS_RESULT,
            JudgeErrorCode.EVIDENCE_AMBIGUOUS,
            JudgeOutcomeClass.EVIDENCE_AMBIGUOUS,
        ),
        (
            FailureKind.POLICY_DENIAL,
            JudgeErrorCode.INVESTIGATION_DENIED,
            JudgeOutcomeClass.CLOSED_NON_SUCCESS,
        ),
    ),
)
def test_runtime_maps_internal_failure_to_stable_redacted_taxonomy(
    kind: FailureKind,
    code: JudgeErrorCode,
    outcome: JudgeOutcomeClass,
) -> None:
    class FailedFlow:
        def execute(self, _run: object) -> object:
            return ControlResult.failed(
                FailureDetail(
                    kind=kind,
                    code="INTERNAL_PROVIDER_DETAIL",
                    message="raw provider detail that must not cross HTTP",
                    retryable=kind is FailureKind.DEPENDENCY_UNAVAILABLE,
                )
            )

    runtime = JudgeInvestigationRuntime(
        JudgeRuntimeDependencies(
            settings=_settings(),
            repository=object(),
            snapshot_storage=object(),
            ec2_client=object(),
            cloudwatch_client=object(),
            bedrock_session=object(),
            dependency_circuit=DependencyCircuitBreaker(),
            stop_request_handler=lambda _proposal_id: {},
            verification_request_handler=lambda _proposal_id: {},
        ),
        clock=lambda: NOW,
        run_id_factory=IdFactory(IDS[0:1]),
        trace_id_factory=IdFactory(IDS[1:2]),
        correlation_id_factory=IdFactory(IDS[2:3]),
        proposal_id_factory=IdFactory(IDS[3:4]),
        event_id_factory=IdFactory(IDS[8:]),
        session_manager_factory=lambda _session_id, _storage: object(),
        model_factory=lambda _settings, _session: object(),
        agent_factory=lambda **_kwargs: object(),
        flow_factory=lambda *_args, **_kwargs: FailedFlow(),
    )

    result = runtime.investigate(
        JudgeInvestigationRequest(intent="investigate_idle_sandbox")
    )

    assert not result.succeeded
    assert result.error_code is code
    assert result.outcome_class is outcome
    assert "PROVIDER" not in result.model_dump_json()
    assert "raw" not in result.model_dump_json()


def test_default_composition_uses_only_durable_dynamodb_quota_and_status_limiter() -> None:
    class DynamoClient:
        def get_item(self, **_kwargs: object) -> dict[str, object]:
            return {}

        def update_item(self, **_kwargs: object) -> dict[str, object]:
            return {}

    dynamodb = DynamoClient()
    lambda_calls = 0

    class LambdaClient:
        def invoke(self, **_kwargs: object) -> dict[str, object]:
            nonlocal lambda_calls
            lambda_calls += 1
            return {}

    token_provider = SimpleNamespace(get_token=lambda: "x" * 32)
    readiness_probe = SimpleNamespace(check=lambda: True)
    resources = JudgeProcessResources(
        settings=_settings(),
        ec2_client=object(),
        cloudwatch_client=object(),
        dynamodb_client=dynamodb,
        secrets_client=object(),
        bedrock_session=object(),
        lambda_client=LambdaClient(),
        token_provider=token_provider,
        dependency_circuit=DependencyCircuitBreaker(),
        readiness_probe=readiness_probe,
        readiness_dependency_circuit=DependencyCircuitBreaker(),
        telemetry=SimpleNamespace(
            force_flush=lambda *_args, **_kwargs: True,
            tracer=TracerProvider().get_tracer("day15-composition-test"),
        ),
    )

    services = build_request_services(resources)

    assert isinstance(services.investigation_quota, DynamoDbJudgeQuotaRepository)
    assert isinstance(services.status_quota, DynamoDbStatusRequestQuotaRepository)
    assert isinstance(
        services.status._observation_limiter,
        DynamoDbStatusObservationLimiter,
    )
    assert services.authorizer._token_provider is token_provider
    assert services.investigation._dependencies.dependency_circuit is (
        resources.dependency_circuit
    )
    assert resources.readiness_dependency_circuit is not resources.dependency_circuit
    stop_handler = services.investigation._dependencies.stop_request_handler
    verification_handler = (
        services.investigation._dependencies.verification_request_handler
    )
    private_controls = stop_handler.__self__
    assert isinstance(private_controls, JudgePrivateControlPlane)
    assert isinstance(private_controls.remediation, StopSandboxInstanceCoordinator)
    assert isinstance(private_controls.verification, BoundedVerificationCoordinator)
    assert isinstance(private_controls.recovery, RecoveryCoordinator)
    assert private_controls.remediation._executor._function_name == (
        resources.settings.private_executor_alias_arn
    )
    assert verification_handler.__self__ is private_controls
    assert stop_handler(IDS[3])["failure"]["code"] == "PUBLIC_MUTATION_UNAVAILABLE"
    assert verification_handler(IDS[3])["failure"]["code"] == (
        "PUBLIC_VERIFICATION_UNAVAILABLE"
    )
    assert lambda_calls == 0
    assert services.readiness() is True

    second = build_request_services(resources)

    assert second is not services
    assert second.investigation is not services.investigation
    assert second.authorizer._token_provider is token_provider
    assert second.investigation._dependencies.dependency_circuit is (
        resources.dependency_circuit
    )


def test_lambda_handler_module_is_lazy_and_reuses_only_process_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from aioa_cloudops_agent.judge import lambda_handler as handler_module

    resources = JudgeProcessResources(
        settings=_settings(),
        ec2_client=object(),
        cloudwatch_client=object(),
        dynamodb_client=object(),
        secrets_client=object(),
        bedrock_session=object(),
        lambda_client=object(),
        token_provider=SimpleNamespace(get_token=lambda: "x" * 32),
        dependency_circuit=DependencyCircuitBreaker(),
        readiness_probe=SimpleNamespace(check=lambda: True),
        readiness_dependency_circuit=DependencyCircuitBreaker(),
        telemetry=SimpleNamespace(
            force_flush=lambda *_args, **_kwargs: True,
            tracer=TracerProvider().get_tracer("day15-handler-test"),
        ),
    )
    calls = 0

    def build() -> JudgeProcessResources:
        nonlocal calls
        calls += 1
        return resources

    monkeypatch.setattr(handler_module, "_PROCESS_RESOURCES", None)
    monkeypatch.setattr(handler_module, "build_process_resources", build)

    assert handler_module._resources() is resources
    assert handler_module._resources() is resources
    assert calls == 1
    assert handler_module.lambda_handler.__module__ == (
        "aioa_cloudops_agent.judge.lambda_handler"
    )


class _ReadinessTokenProvider:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return "x" * 32


class _ReadinessDynamoDb:
    def __init__(self) -> None:
        self.calls = 0

    def get_item(self, **_kwargs: object) -> dict[str, object]:
        self.calls += 1
        return {}


class _ReadinessQuota:
    def __init__(self, *, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls = 0

    def reserve(self) -> object | None:
        self.calls += 1
        return object() if self.accepted else None


class _BlockingReadinessQuota(_ReadinessQuota):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.release = Event()

    def reserve(self) -> object | None:
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=2):
            raise RuntimeError("test readiness release unavailable")
        return object()


class _ReadinessEc2:
    def __init__(self, *, returned_instance_id: str | None = None) -> None:
        self.calls = 0
        self.returned_instance_id = returned_instance_id or _settings().target.instance_id

    def describe_instances(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        assert kwargs == {"InstanceIds": [_settings().target.instance_id]}
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": self.returned_instance_id,
                            "InstanceType": "t3.micro",
                            "LaunchTime": NOW - timedelta(days=1),
                            "Monitoring": {"State": "enabled"},
                            "Placement": {"AvailabilityZone": "eu-central-1a"},
                            "State": {"Name": "running"},
                            "Tags": [
                                {
                                    "Key": _settings().target.required_tag_key,
                                    "Value": _settings().target.required_tag_value,
                                }
                            ],
                        }
                    ]
                }
            ]
        }


class _ReadinessCloudWatch:
    def __init__(self, *, malformed: bool = False) -> None:
        self.calls = 0
        self.malformed = malformed

    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        self.calls += 1
        assert kwargs["Namespace"] == "AWS/EC2"
        assert kwargs["MetricName"] == "CPUUtilization"
        assert kwargs["Dimensions"] == [
            {"Name": "InstanceId", "Value": _settings().target.instance_id}
        ]
        unit = "Bytes" if self.malformed else "Percent"
        return {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5 * index),
                    "Average": 2.0,
                    "Unit": unit,
                }
                for index in range(1, 7)
            ]
        }


def _readiness_probe(
    *,
    clock: list[float],
    ec2: _ReadinessEc2 | None = None,
    cloudwatch: _ReadinessCloudWatch | None = None,
    quota_accepted: bool = True,
    quota: _ReadinessQuota | None = None,
) -> tuple[
    BoundedReadinessProbe,
    _ReadinessTokenProvider,
    _ReadinessDynamoDb,
    _ReadinessEc2,
    _ReadinessCloudWatch,
    _ReadinessQuota,
]:
    token = _ReadinessTokenProvider()
    dynamodb = _ReadinessDynamoDb()
    quota = quota or _ReadinessQuota(accepted=quota_accepted)
    ec2 = ec2 or _ReadinessEc2()
    cloudwatch = cloudwatch or _ReadinessCloudWatch()
    settings = _settings()
    return (
        BoundedReadinessProbe(
            dynamodb,
            settings.state_table.table_name,
            token,
            ec2,
            cloudwatch,
            settings.target,
            settings.idle_policy,
            DependencyCircuitBreaker(),
            quota,
            ttl_seconds=5,
            clock=lambda: clock[0],
            utc_clock=lambda: NOW,
        ),
        token,
        dynamodb,
        ec2,
        cloudwatch,
        quota,
    )


def test_readiness_is_singleflight_cached_and_reads_each_dependency_once_per_ttl() -> None:
    clock = [0.0]
    probe, token, dynamodb, ec2, cloudwatch, quota = _readiness_probe(clock=clock)

    assert probe.check() is True
    assert probe.check() is True
    assert (quota.calls, token.calls, dynamodb.calls, ec2.calls, cloudwatch.calls) == (
        1,
        1,
        1,
        1,
        1,
    )

    clock[0] = 5.0

    assert probe.check() is True
    assert (quota.calls, token.calls, dynamodb.calls, ec2.calls, cloudwatch.calls) == (
        2,
        2,
        2,
        2,
        2,
    )


def test_readiness_daily_quota_denial_is_cached_before_any_dependency_read() -> None:
    probe, token, dynamodb, ec2, cloudwatch, quota = _readiness_probe(
        clock=[0.0],
        quota_accepted=False,
    )

    assert probe.check() is False
    assert probe.check() is False
    assert quota.calls == 1
    assert (token.calls, dynamodb.calls, ec2.calls, cloudwatch.calls) == (0, 0, 0, 0)


def test_concurrent_readiness_requests_collapse_to_one_actual_probe() -> None:
    quota = _BlockingReadinessQuota()
    probe, token, dynamodb, ec2, cloudwatch, actual_quota = _readiness_probe(
        clock=[0.0],
        quota=quota,
    )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = [executor.submit(probe.check) for _ in range(8)]
        assert quota.started.wait(timeout=2)
        quota.release.set()

    assert all(result.result() is True for result in results)
    assert actual_quota is quota and quota.calls == 1
    assert (token.calls, dynamodb.calls, ec2.calls, cloudwatch.calls) == (1, 1, 1, 1)


@pytest.mark.parametrize("failure", ("target", "evidence"))
def test_readiness_fails_closed_on_malformed_scope_or_metric_evidence(
    failure: str,
) -> None:
    ec2 = _ReadinessEc2(
        returned_instance_id=(
            "i-fedcba9876543210f" if failure == "target" else None
        )
    )
    cloudwatch = _ReadinessCloudWatch(malformed=failure == "evidence")
    probe, _token, _dynamodb, actual_ec2, actual_cloudwatch, _quota = _readiness_probe(
        clock=[0.0],
        ec2=ec2,
        cloudwatch=cloudwatch,
    )

    assert probe.check() is False
    assert actual_ec2.calls == 1
    assert actual_cloudwatch.calls == (0 if failure == "target" else 1)


def test_status_quota_reserves_only_one_request_without_token_or_cost_budget() -> None:
    class DynamoDb:
        def __init__(self) -> None:
            self.call: dict[str, object] | None = None

        def update_item(self, **kwargs: object) -> dict[str, object]:
            self.call = kwargs
            return {"Attributes": {"requests": {"N": "1"}}}

    client = DynamoDb()
    quota = DynamoDbStatusRequestQuotaRepository(
        client,
        "aioa-state",
        clock=lambda: NOW,
    )

    reservation = quota.reserve()

    assert reservation is not None and reservation.requests == 1
    assert client.call is not None
    assert client.call["Key"] == {
        "PK": {"S": "JUDGE_STATUS_QUOTA#2026-08-24"},
        "SK": {"S": "DAILY_REQUESTS"},
    }
    serialized_call = str(client.call).casefold()
    assert "token" not in serialized_call
    assert "cost" not in serialized_call


def test_readiness_quota_is_durable_request_only_and_separate_from_investigation() -> None:
    class DynamoDb:
        def __init__(self) -> None:
            self.call: dict[str, object] | None = None

        def update_item(self, **kwargs: object) -> dict[str, object]:
            self.call = kwargs
            return {"Attributes": {"probes": {"N": "1"}}}

    client = DynamoDb()
    quota = DynamoDbReadinessProbeQuotaRepository(
        client,
        "aioa-state",
        clock=lambda: NOW,
    )

    reservation = quota.reserve()

    assert reservation is not None and reservation.probes == 1
    assert client.call is not None
    assert client.call["Key"] == {
        "PK": {"S": "JUDGE_READINESS_QUOTA#2026-08-24"},
        "SK": {"S": "DAILY_PROBES"},
    }
    serialized_call = str(client.call).casefold()
    assert "judge_quota#" not in serialized_call
    assert "token" not in serialized_call
    assert "cost" not in serialized_call
