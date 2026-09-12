"""Lazy process resources and per-request Judge service composition."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite
from threading import Lock
from time import monotonic

from botocore.config import Config

from aioa_cloudops_agent.aws_clients import (
    AWS_CONNECT_TIMEOUT_SECONDS,
    AWS_READ_TIMEOUT_SECONDS,
    AWS_TOTAL_MAX_ATTEMPTS,
    create_bedrock_runtime_client,
    create_cloudwatch_read_client,
    create_ec2_read_client,
    create_lambda_invoke_client,
)
from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    InspectInstanceService,
    InvestigationIdentity,
    ReadUtilizationMetricsService,
    SandboxTarget,
    UtilizationClassification,
)
from aioa_cloudops_agent.config import IdlePolicySettings
from aioa_cloudops_agent.config.settings import DEFAULT_AWS_REGION
from aioa_cloudops_agent.deployment import (
    DynamoDbJudgeQuotaRepository,
    DynamoDbSnapshotStorage,
    DynamoDbStatusObservationLimiter,
    JudgeRuntimeSettings,
    JudgeTokenAuthorizer,
    ReadOnlyRunStatusService,
    SecretsManagerJudgeTokenProvider,
)
from aioa_cloudops_agent.domain.identifiers import generate_correlation_id
from aioa_cloudops_agent.nz import generate_event_id, generate_run_id, generate_trace_id
from aioa_cloudops_agent.persistence import DynamoDbDurableTruthRepository
from aioa_cloudops_agent.safety import (
    BoundedReadRetry,
    CircuitDependency,
    DependencyCircuitBreaker,
)

from .application import JudgeRequestServices
from .control_plane import build_judge_private_control_plane
from .quota import (
    DynamoDbReadinessProbeQuotaRepository,
    DynamoDbStatusRequestQuotaRepository,
)
from .runtime import JudgeInvestigationRuntime, JudgeRuntimeDependencies
from .telemetry import JudgeTelemetry, initialize_judge_telemetry


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _control_client_config() -> Config:
    return Config(
        region_name=DEFAULT_AWS_REGION,
        connect_timeout=AWS_CONNECT_TIMEOUT_SECONDS,
        ignore_configured_endpoint_urls=True,
        read_timeout=AWS_READ_TIMEOUT_SECONDS,
        retries={
            "mode": "standard",
            "total_max_attempts": AWS_TOTAL_MAX_ATTEMPTS,
        },
    )


class _CachedBedrockSession:
    """Give each new BedrockModel the one reviewed process client."""

    region_name = DEFAULT_AWS_REGION

    def __init__(self, client: object) -> None:
        self._client = client

    def client(
        self,
        *,
        service_name: str,
        config: Config,
        endpoint_url: str | None,
        region_name: str,
    ) -> object:
        if (
            service_name != "bedrock-runtime"
            or endpoint_url is not None
            or region_name != DEFAULT_AWS_REGION
            or config.region_name != DEFAULT_AWS_REGION
            or config.retries.get("total_max_attempts") != 1
            or not 0 < config.connect_timeout < 60
            or not 0 < config.read_timeout < 60
        ):
            raise RuntimeError("Bedrock client construction is outside the reviewed boundary")
        return self._client


class BoundedReadinessProbe:
    """Cache one bounded prerequisite read and collapse concurrent probes."""

    def __init__(
        self,
        client: object,
        table_name: str,
        token_provider: object,
        ec2_client: object,
        cloudwatch_client: object,
        target: SandboxTarget,
        idle_policy: IdlePolicySettings,
        dependency_circuit: DependencyCircuitBreaker,
        probe_quota: object,
        *,
        ttl_seconds: float = 30.0,
        clock: Callable[[], float] = monotonic,
        utc_clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or not isfinite(float(ttl_seconds))
            or not 1 <= float(ttl_seconds) <= 30
        ):
            raise ValueError("readiness TTL must be finite and between 1 and 30 seconds")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not callable(utc_clock):
            raise TypeError("utc_clock must be callable")
        if not callable(getattr(token_provider, "get_token", None)):
            raise TypeError("token_provider must expose get_token")
        if not callable(getattr(client, "get_item", None)):
            raise TypeError("client must expose get_item")
        if not callable(getattr(ec2_client, "describe_instances", None)):
            raise TypeError("ec2_client must expose describe_instances")
        if not callable(getattr(cloudwatch_client, "get_metric_statistics", None)):
            raise TypeError("cloudwatch_client must expose get_metric_statistics")
        if not isinstance(target, SandboxTarget):
            raise TypeError("target must be SandboxTarget")
        if not isinstance(idle_policy, IdlePolicySettings):
            raise TypeError("idle_policy must be IdlePolicySettings")
        if not isinstance(dependency_circuit, DependencyCircuitBreaker):
            raise TypeError("dependency_circuit must be DependencyCircuitBreaker")
        if not callable(getattr(probe_quota, "reserve", None)):
            raise TypeError("probe_quota must expose reserve")
        self._client = client
        self._table_name = table_name
        self._token_provider = token_provider
        self._ec2_client = ec2_client
        self._cloudwatch_client = cloudwatch_client
        self._target = target
        self._idle_policy = idle_policy
        self._dependency_circuit = dependency_circuit
        self._probe_quota = probe_quota
        self._ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._utc_clock = utc_clock
        self._lock = Lock()
        self._cached_result: bool | None = None
        self._cache_expires_at = 0.0
        self._last_clock = float("-inf")

    def check(self) -> bool:
        with self._lock:
            try:
                raw_now = self._clock()
            except Exception:
                return False
            if (
                isinstance(raw_now, bool)
                or not isinstance(raw_now, (int, float))
                or not isfinite(float(raw_now))
            ):
                return False
            now = float(raw_now)
            if now < self._last_clock:
                return False
            self._last_clock = now
            if self._cached_result is not None and now < self._cache_expires_at:
                return self._cached_result
            result = self._probe_dependencies()
            expires_at = now + self._ttl_seconds
            if not isfinite(expires_at):
                return False
            self._cached_result = result
            self._cache_expires_at = expires_at
            return result

    def _probe_dependencies(self) -> bool:
        try:
            if self._probe_quota.reserve() is None:
                return False
            token = self._token_provider.get_token()
            if not isinstance(token, str) or not token:
                return False
            state_response = self._client.get_item(
                TableName=self._table_name,
                Key={
                    "PK": {"S": "SYSTEM#READINESS"},
                    "SK": {"S": "BOUNDED_READ"},
                },
                ConsistentRead=True,
                ProjectionExpression="PK",
            )
            if not isinstance(state_response, Mapping):
                return False
            identity = InvestigationIdentity(
                run_id=generate_run_id(),
                trace_id=generate_trace_id(),
                correlation_id=generate_correlation_id(),
            )
            inspection = InspectInstanceService(
                self._ec2_client,
                self._target,
                retry=BoundedReadRetry(
                    max_attempts=1,
                    circuit_breaker=self._dependency_circuit,
                    dependency=CircuitDependency.EC2_READ,
                ),
            ).inspect(
                instance_id=self._target.instance_id,
                identity=identity,
            )
            if inspection.state is not Ec2InstanceState.RUNNING:
                return False
            evidence = ReadUtilizationMetricsService(
                self._cloudwatch_client,
                self._target,
                self._idle_policy,
                retry=BoundedReadRetry(
                    max_attempts=1,
                    circuit_breaker=self._dependency_circuit,
                    dependency=CircuitDependency.CLOUDWATCH_READ,
                ),
            ).read(
                inspection=inspection,
                identity=identity,
                collected_at=self._utc_clock(),
            )
            return (
                evidence.datapoint_count >= self._idle_policy.minimum_datapoints
                and evidence.classification is not UtilizationClassification.AMBIGUOUS
            )
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class JudgeProcessResources:
    """Retain only bounded clients, config, caches, circuits, probe, and telemetry."""

    settings: JudgeRuntimeSettings
    ec2_client: object
    cloudwatch_client: object
    dynamodb_client: object
    secrets_client: object
    bedrock_session: object
    lambda_client: object
    token_provider: SecretsManagerJudgeTokenProvider
    dependency_circuit: DependencyCircuitBreaker
    readiness_probe: BoundedReadinessProbe
    readiness_dependency_circuit: DependencyCircuitBreaker
    telemetry: JudgeTelemetry


def build_process_resources() -> JudgeProcessResources:
    """Construct exact-region clients lazily; importing the handler performs no AWS work."""

    import boto3

    settings = JudgeRuntimeSettings.from_environment()
    session = boto3.Session(region_name=DEFAULT_AWS_REGION)
    creator = session.client
    dynamodb_client = creator(
        "dynamodb",
        region_name=DEFAULT_AWS_REGION,
        config=_control_client_config(),
    )
    secrets_client = creator(
        "secretsmanager",
        region_name=DEFAULT_AWS_REGION,
        config=_control_client_config(),
    )
    xray_client = creator(
        "xray",
        region_name=DEFAULT_AWS_REGION,
        config=_control_client_config(),
    )
    bedrock_client = create_bedrock_runtime_client(client_creator=creator)
    lambda_client = create_lambda_invoke_client(client_creator=creator)
    token_provider = SecretsManagerJudgeTokenProvider(
        secrets_client,
        secret_id=settings.judge_token_secret_arn,
        not_after=settings.judge_token_not_after,
        clock=_utc_now,
        cache_ttl_seconds=60,
    )
    ec2_client = create_ec2_read_client(client_creator=creator)
    cloudwatch_client = create_cloudwatch_read_client(client_creator=creator)
    dependency_circuit = DependencyCircuitBreaker()
    readiness_dependency_circuit = DependencyCircuitBreaker()
    readiness_quota = DynamoDbReadinessProbeQuotaRepository(
        dynamodb_client,
        settings.state_table.table_name,
        clock=_utc_now,
    )
    return JudgeProcessResources(
        settings=settings,
        ec2_client=ec2_client,
        cloudwatch_client=cloudwatch_client,
        dynamodb_client=dynamodb_client,
        secrets_client=secrets_client,
        bedrock_session=_CachedBedrockSession(bedrock_client),
        lambda_client=lambda_client,
        token_provider=token_provider,
        dependency_circuit=dependency_circuit,
        readiness_probe=BoundedReadinessProbe(
            dynamodb_client,
            settings.state_table.table_name,
            token_provider,
            ec2_client,
            cloudwatch_client,
            settings.target,
            settings.idle_policy,
            readiness_dependency_circuit,
            readiness_quota,
        ),
        readiness_dependency_circuit=readiness_dependency_circuit,
        telemetry=initialize_judge_telemetry(xray_client),
    )


def build_request_services(resources: JudgeProcessResources) -> JudgeRequestServices:
    """Build fresh adapters without retaining a principal, Agent, run, or session."""

    if not isinstance(resources, JudgeProcessResources):
        raise TypeError("resources must be JudgeProcessResources")
    settings = resources.settings
    repository = DynamoDbDurableTruthRepository(
        resources.dynamodb_client,
        settings.state_table,
    )
    private_controls = build_judge_private_control_plane(
        repository=repository,
        lambda_client=resources.lambda_client,
        private_executor_alias_arn=settings.private_executor_alias_arn,
        ec2_client=resources.ec2_client,
        target=settings.target,
        dependency_circuit=resources.dependency_circuit,
        clock=_utc_now,
        event_id_factory=generate_event_id,
        evidence_id_factory=generate_event_id,
        recovery_id_factory=generate_correlation_id,
    )
    runtime = JudgeInvestigationRuntime(
        JudgeRuntimeDependencies(
            settings=settings,
            repository=repository,
            snapshot_storage=DynamoDbSnapshotStorage(
                resources.dynamodb_client,
                settings.state_table.table_name,
            ),
            ec2_client=resources.ec2_client,
            cloudwatch_client=resources.cloudwatch_client,
            bedrock_session=resources.bedrock_session,
            dependency_circuit=resources.dependency_circuit,
            stop_request_handler=private_controls.public_stop_request,
            verification_request_handler=(
                private_controls.public_verification_request
            ),
        ),
        tracer=resources.telemetry.tracer,
    )
    authorizer = JudgeTokenAuthorizer(resources.token_provider)
    investigation_quota = DynamoDbJudgeQuotaRepository(
        resources.dynamodb_client,
        settings.state_table.table_name,
        clock=_utc_now,
    )
    status_quota = DynamoDbStatusRequestQuotaRepository(
        resources.dynamodb_client,
        settings.state_table.table_name,
        clock=_utc_now,
    )
    status = ReadOnlyRunStatusService(
        repository,
        observation_limiter=DynamoDbStatusObservationLimiter(
            resources.dynamodb_client,
            settings.state_table.table_name,
        ),
        clock=_utc_now,
    )
    return JudgeRequestServices(
        authorizer=authorizer,
        investigation_quota=investigation_quota,
        status_quota=status_quota,
        investigation=runtime,
        status=status,
        readiness=resources.readiness_probe.check,
    )
