"""Factory for exactly one Strands Agent subordinate to Non-Zero authority."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from opentelemetry.trace import Tracer
from strands import Agent
from strands.models import Model
from strands.session import SessionManager
from strands.tools.decorator import DecoratedFunctionTool
from strands.vended_interventions.hitl import HumanInTheLoop

from aioa_cloudops_agent.cloudops import (
    BUILD_REMEDIATION_EVIDENCE_TOOL_NAME,
    INSPECT_INSTANCE_TOOL_NAME,
    READ_UTILIZATION_TOOL_NAME,
    BuildRemediationEvidenceService,
    CloudWatchGetMetricStatisticsClient,
    Ec2DescribeInstancesClient,
    InspectInstanceService,
    InvestigationIdentity,
    InvestigationToolContext,
    ReadUtilizationMetricsService,
    SandboxTarget,
    create_build_remediation_evidence_tool,
    create_inspect_instance_tool,
    create_read_utilization_metrics_tool,
)
from aioa_cloudops_agent.config import (
    BedrockSettings,
    IdlePolicySettings,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.domain import AuthorityGate, ContractValidationError, ExecutionContext
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.nz import generate_event_id
from aioa_cloudops_agent.persistence import DurableTruthRepository
from aioa_cloudops_agent.providers import (
    ModelProviderRuntime,
    create_model_provider,
)
from aioa_cloudops_agent.providers import create_bedrock_model as _create_bedrock_model
from aioa_cloudops_agent.remediation import (
    STOP_SANDBOX_INSTANCE_TOOL_NAME,
    StopRequestHandler,
    create_stop_sandbox_instance_tool,
    unavailable_stop_request,
)
from aioa_cloudops_agent.safety import (
    BoundedReadRetry,
    CircuitBoundedModel,
    CircuitDependency,
    DependencyCircuitBreaker,
)
from aioa_cloudops_agent.verification import (
    VERIFY_INSTANCE_STATE_TOOL_NAME,
    VerificationRequestHandler,
    create_verify_instance_state_tool,
    unavailable_verification_request,
)

from .hitl import DurableProposalHumanInTheLoop
from .prompts import SYSTEM_PROMPT
from .tracing import PRIMARY_AGENT_ID, build_agent_trace_attributes

PRIMARY_AGENT_COUNT: Final = 1
CURRENT_REGISTERED_TOOL_COUNT: Final = 5
FINAL_TOOL_CAP: Final = 5
INVESTIGATION_TOOL_NAMES: Final = (
    INSPECT_INSTANCE_TOOL_NAME,
    READ_UTILIZATION_TOOL_NAME,
    BUILD_REMEDIATION_EVIDENCE_TOOL_NAME,
)
READ_ONLY_TOOL_NAMES: Final = (*INVESTIGATION_TOOL_NAMES, VERIFY_INSTANCE_STATE_TOOL_NAME)
CURRENT_TOOL_NAMES: Final = (
    *INVESTIGATION_TOOL_NAMES,
    STOP_SANDBOX_INSTANCE_TOOL_NAME,
    VERIFY_INSTANCE_STATE_TOOL_NAME,
)


def create_bedrock_model(
    settings: BedrockSettings,
    *,
    boto_session: object | None = None,
) -> Model:
    """Compatibility export routed through the single provider implementation."""

    return _create_bedrock_model(settings, boto_session=boto_session)


@dataclass(frozen=True, slots=True)
class PrimaryAgentRuntime:
    """References required to invoke and audit the one primary agent."""

    agent: Agent
    inspect_instance_tool: DecoratedFunctionTool
    read_utilization_metrics_tool: DecoratedFunctionTool
    build_remediation_evidence_tool: DecoratedFunctionTool
    stop_sandbox_instance_tool: DecoratedFunctionTool
    verify_instance_state_tool: DecoratedFunctionTool
    human_in_the_loop: HumanInTheLoop
    tool_context: InvestigationToolContext
    identity: InvestigationIdentity
    model_settings: ModelProviderRuntime
    target: SandboxTarget
    proposal_id: UUID
    dependency_circuit: DependencyCircuitBreaker

    @property
    def registered_tool_names(self) -> tuple[str, ...]:
        """Return the active tool surface without dynamic discovery."""

        return tuple(self.agent.tool_names)


def create_human_in_the_loop(
    repository: DurableTruthRepository | None = None,
    *,
    identity: InvestigationIdentity | None = None,
    target: SandboxTarget | None = None,
    clock: Callable[[], datetime] | None = None,
    model_id: str | None = None,
) -> HumanInTheLoop:
    """Create the central default-deny hook when its exact context is available."""

    if identity is not None and target is not None and clock is not None and model_id is not None:
        return DurableProposalHumanInTheLoop(
            repository,
            allowed_tools=list(READ_ONLY_TOOL_NAMES),
            identity=identity,
            target=target,
            clock=clock,
            event_id_factory=generate_event_id,
            model_id=model_id,
        )
    return HumanInTheLoop(
        allowed_tools=list(READ_ONLY_TOOL_NAMES),
        classifier=None,
        enable_trust=False,
        ask=None,
    )


def create_primary_agent(
    *,
    context: ExecutionContext,
    identity: InvestigationIdentity,
    target: SandboxTarget,
    ec2_client: Ec2DescribeInstancesClient,
    cloudwatch_client: CloudWatchGetMetricStatisticsClient,
    proposal_id: UUID,
    clock: Callable[[], datetime],
    idle_policy: IdlePolicySettings | None = None,
    model_settings: BedrockSettings | None = None,
    runtime_settings: RuntimeSettings | None = None,
    model: Model | None = None,
    tracer: Tracer | None = None,
    durable_repository: DurableTruthRepository | None = None,
    stop_request_handler: StopRequestHandler | None = None,
    verification_request_handler: VerificationRequestHandler | None = None,
    dependency_circuit: DependencyCircuitBreaker | None = None,
    session_manager: SessionManager | None = None,
) -> PrimaryAgentRuntime:
    """Create one Strands Agent with the canonical bounded five-tool surface."""

    if not isinstance(context, ExecutionContext):
        raise ContractValidationError("context must be an ExecutionContext")
    if context.authority_gate is not AuthorityGate.AUTO:
        raise ContractValidationError("current read-only agent context must use AUTO")
    if not isinstance(identity, InvestigationIdentity):
        raise ContractValidationError("identity must be an InvestigationIdentity")
    if identity.correlation_id != context.correlation_id:
        raise ContractValidationError("identity must match the execution context")
    if not isinstance(target, SandboxTarget):
        raise ContractValidationError("target must be a SandboxTarget")
    if not isinstance(proposal_id, UUID):
        raise ContractValidationError("proposal_id must be UUIDv7")
    validate_correlation_id(proposal_id)
    if not callable(clock):
        raise ContractValidationError("clock must be callable")
    if model_settings is not None and not isinstance(model_settings, BedrockSettings):
        raise ContractValidationError("model_settings must be BedrockSettings")
    if runtime_settings is not None and not isinstance(runtime_settings, RuntimeSettings):
        raise ContractValidationError("runtime_settings must be RuntimeSettings")
    if runtime_settings is None:
        selected_runtime_settings = (
            RuntimeSettings()
            if model_settings is None
            else RuntimeSettings(
                mode=RuntimeMode.AWS,
                model_provider=ModelProviderName.BEDROCK,
                aws_integration_enabled=True,
                bedrock=model_settings,
            )
        )
    else:
        selected_runtime_settings = runtime_settings
    if (
        model_settings is not None
        and selected_runtime_settings.bedrock != model_settings
    ):
        raise ContractValidationError(
            "model_settings must match the selected runtime provider"
        )
    provider_runtime = create_model_provider(
        selected_runtime_settings,
        model_override=model,
    )
    active_circuit = (
        dependency_circuit
        if dependency_circuit is not None
        else DependencyCircuitBreaker()
    )
    if not isinstance(active_circuit, DependencyCircuitBreaker):
        raise ContractValidationError(
            "dependency_circuit must be DependencyCircuitBreaker"
        )

    inspection_service = InspectInstanceService(
        ec2_client,
        target,
        region=provider_runtime.region,
        retry=BoundedReadRetry(
            circuit_breaker=active_circuit,
            dependency=CircuitDependency.EC2_READ,
        ),
    )
    policy = idle_policy if idle_policy is not None else IdlePolicySettings()
    if not isinstance(policy, IdlePolicySettings):
        raise ContractValidationError("idle_policy must be IdlePolicySettings")
    utilization_service = ReadUtilizationMetricsService(
        cloudwatch_client,
        target,
        policy,
        retry=BoundedReadRetry(
            circuit_breaker=active_circuit,
            dependency=CircuitDependency.CLOUDWATCH_READ,
        ),
    )
    evidence_service = BuildRemediationEvidenceService(target)
    tool_context = InvestigationToolContext(identity=identity)
    inspection_tool = create_inspect_instance_tool(
        inspection_service,
        identity,
        tracer=tracer,
        on_result=tool_context.record_inspection,
    )
    utilization_tool = create_read_utilization_metrics_tool(
        utilization_service,
        tool_context.inspection,
        identity,
        clock=clock,
        tracer=tracer,
        on_result=tool_context.record_utilization,
    )
    evidence_tool = create_build_remediation_evidence_tool(
        evidence_service,
        tool_context.inspection,
        tool_context.utilization,
        identity,
        target,
        proposal_id,
        clock=clock,
        tracer=tracer,
        on_result=tool_context.record_evidence,
    )
    stop_tool = create_stop_sandbox_instance_tool(
        stop_request_handler or unavailable_stop_request,
        identity,
        tracer=tracer,
    )
    verification_tool = create_verify_instance_state_tool(
        verification_request_handler or unavailable_verification_request,
        identity,
        tracer=tracer,
    )
    intervention = create_human_in_the_loop(
        durable_repository,
        identity=identity,
        target=target,
        clock=clock,
        model_id=provider_runtime.model_id,
    )
    bounded_model = CircuitBoundedModel(
        provider_runtime.model,
        active_circuit,
    )
    primary_agent = Agent(
        agent_id=PRIMARY_AGENT_ID,
        name="AIOA Non-Zero CloudOps",
        description="Bounded read-only sandbox EC2 investigation agent",
        model=bounded_model,
        tools=[
            inspection_tool,
            utilization_tool,
            evidence_tool,
            stop_tool,
            verification_tool,
        ],
        interventions=[intervention],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,
        load_tools_from_directory=False,
        record_direct_tool_call=True,
        retry_strategy=None,
        session_manager=session_manager,
        trace_attributes=build_agent_trace_attributes(identity),
    )
    if tuple(primary_agent.tool_names) != CURRENT_TOOL_NAMES:
        raise ContractValidationError("primary agent tool surface is not canonical")
    return PrimaryAgentRuntime(
        agent=primary_agent,
        inspect_instance_tool=inspection_tool,
        read_utilization_metrics_tool=utilization_tool,
        build_remediation_evidence_tool=evidence_tool,
        stop_sandbox_instance_tool=stop_tool,
        verify_instance_state_tool=verification_tool,
        human_in_the_loop=intervention,
        tool_context=tool_context,
        identity=identity,
        model_settings=provider_runtime,
        target=target,
        proposal_id=proposal_id,
        dependency_circuit=active_circuit,
    )
