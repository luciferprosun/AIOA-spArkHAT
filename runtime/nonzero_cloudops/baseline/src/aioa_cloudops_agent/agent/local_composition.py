"""Safe local composition using the same NZ contracts and adapter interfaces."""

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from aioa_cloudops_agent.cloudops import (
    LocalMockRemediationExecutor,
    LocalMockStateStore,
    MockAwsAdapter,
    PersistentMockAwsAdapter,
    PlanRemediation,
    QueryResource,
)
from aioa_cloudops_agent.config import (
    LocalFirstMode,
    LocalFirstSettings,
    LocalHitlSettings,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.nz import generate_event_id, generate_proposal_id
from aioa_cloudops_agent.persistence import LocalFileDurableTruthRepository
from aioa_cloudops_agent.providers import (
    MockModelProvider,
    ModelProviderRuntime,
    create_model_provider,
)

from .local_first import LocalFirstPhaseOneFlow
from .local_hitl import LocalHitlExecutionFlow


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class LocalFirstRuntime:
    """Inspectable dependencies for one credential-free local composition."""

    flow: LocalFirstPhaseOneFlow
    repository: LocalFileDurableTruthRepository
    cloud_provider: MockAwsAdapter
    model_provider: MockModelProvider
    provider_runtime: ModelProviderRuntime
    runtime_settings: RuntimeSettings


@dataclass(frozen=True, slots=True)
class LocalHitlRuntime:
    """Inspectable Local-1 + Local-2 composition with separated write authority."""

    phase_one: LocalFirstPhaseOneFlow
    phase_two: LocalHitlExecutionFlow
    repository: LocalFileDurableTruthRepository
    cloud_provider: PersistentMockAwsAdapter
    model_provider: MockModelProvider
    provider_runtime: ModelProviderRuntime
    executor: LocalMockRemediationExecutor
    cloud_state: LocalMockStateStore
    runtime_settings: RuntimeSettings


def _portable_runtime_settings(settings: RuntimeSettings | None) -> RuntimeSettings:
    selected = settings or RuntimeSettings()
    if not isinstance(selected, RuntimeSettings):
        raise ContractValidationError("runtime_settings must be RuntimeSettings")
    if (
        selected.mode is not RuntimeMode.PORTABLE
        or selected.model_provider is not ModelProviderName.MOCK
        or selected.aws_calls_allowed
    ):
        raise ContractValidationError(
            "local composition requires portable runtime with the mock provider"
        )
    return selected


def create_local_first_runtime(
    settings: LocalFirstSettings | None = None,
    *,
    runtime_settings: RuntimeSettings | None = None,
    clock: Callable[[], datetime] = _utc_now,
    proposal_id_factory: Callable[[], UUID] = generate_proposal_id,
    event_id_factory: Callable[[], UUID] = generate_event_id,
) -> LocalFirstRuntime:
    """Compose mock mode or fail explicitly when unavailable live mode is requested."""

    selected = settings or LocalFirstSettings()
    selected_runtime = _portable_runtime_settings(runtime_settings)
    if not isinstance(selected, LocalFirstSettings):
        raise ContractValidationError("settings must be LocalFirstSettings")
    if selected.mode is not LocalFirstMode.MOCK:
        raise ContractValidationError(
            "live Local-First composition is unavailable; no mock fallback was selected"
        )
    cloud_provider = MockAwsAdapter()
    provider_runtime = create_model_provider(selected_runtime)
    model_provider = provider_runtime.model
    if not isinstance(model_provider, MockModelProvider):
        raise ContractValidationError("portable model factory did not return the mock provider")
    repository = LocalFileDurableTruthRepository(selected.state_path)
    flow = LocalFirstPhaseOneFlow(
        query_resource=QueryResource(cloud_provider),
        plan_remediation=PlanRemediation(),
        model_provider=model_provider,
        repository=repository,
        clock=clock,
        proposal_id_factory=proposal_id_factory,
        event_id_factory=event_id_factory,
    )
    return LocalFirstRuntime(
        flow=flow,
        repository=repository,
        cloud_provider=cloud_provider,
        model_provider=model_provider,
        provider_runtime=provider_runtime,
        runtime_settings=selected_runtime,
    )


def create_local_hitl_runtime(
    settings: LocalHitlSettings | None = None,
    *,
    runtime_settings: RuntimeSettings | None = None,
    clock: Callable[[], datetime] = _utc_now,
    proposal_id_factory: Callable[[], UUID] = generate_proposal_id,
    request_id_factory: Callable[[], UUID] = generate_event_id,
    event_id_factory: Callable[[], UUID] = generate_event_id,
    nonce_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
) -> LocalHitlRuntime:
    """Compose the complete local HITL path without any ambient AWS discovery."""

    selected = settings or LocalHitlSettings()
    selected_runtime = _portable_runtime_settings(runtime_settings)
    if not isinstance(selected, LocalHitlSettings):
        raise ContractValidationError("settings must be LocalHitlSettings")
    cloud_state = LocalMockStateStore(selected.inventory_path)
    cloud_provider = PersistentMockAwsAdapter(cloud_state)
    provider_runtime = create_model_provider(selected_runtime)
    model_provider = provider_runtime.model
    if not isinstance(model_provider, MockModelProvider):
        raise ContractValidationError("portable model factory did not return the mock provider")
    repository = LocalFileDurableTruthRepository(selected.state_path)
    executor = LocalMockRemediationExecutor(cloud_state, clock=clock)
    phase_one = LocalFirstPhaseOneFlow(
        query_resource=QueryResource(cloud_provider),
        plan_remediation=PlanRemediation(),
        model_provider=model_provider,
        repository=repository,
        clock=clock,
        proposal_id_factory=proposal_id_factory,
        event_id_factory=event_id_factory,
    )
    phase_two = LocalHitlExecutionFlow(
        repository,
        executor,
        clock=clock,
        request_id_factory=request_id_factory,
        event_id_factory=event_id_factory,
        nonce_factory=nonce_factory,
        request_ttl_seconds=selected.request_ttl_seconds,
    )
    return LocalHitlRuntime(
        phase_one=phase_one,
        phase_two=phase_two,
        repository=repository,
        cloud_provider=cloud_provider,
        model_provider=model_provider,
        provider_runtime=provider_runtime,
        executor=executor,
        cloud_state=cloud_state,
        runtime_settings=selected_runtime,
    )
