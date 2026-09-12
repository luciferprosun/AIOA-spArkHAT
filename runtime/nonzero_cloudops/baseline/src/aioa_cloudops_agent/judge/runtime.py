"""Fresh-agent composition for one bounded public judge investigation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer
from strands.models import Model
from strands.session import SessionManager, SnapshotSessionManager

from aioa_cloudops_agent.agent import BoundedInvestigationFlow, create_primary_agent
from aioa_cloudops_agent.agent.factory import PrimaryAgentRuntime, create_bedrock_model
from aioa_cloudops_agent.cloudops import InvestigationIdentity
from aioa_cloudops_agent.deployment.config import (
    JUDGE_MAX_TOKENS,
    JUDGE_MAX_TURNS,
    JudgeInvestigationRequest,
    JudgeRuntimeSettings,
    new_judge_budget,
)
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.domain.identifiers import generate_correlation_id
from aioa_cloudops_agent.nz import (
    FailureKind,
    ResultStatus,
    Run,
    generate_event_id,
    generate_proposal_id,
    generate_run_id,
    generate_trace_id,
)
from aioa_cloudops_agent.persistence import DurableTruthRepository
from aioa_cloudops_agent.remediation import StopRequestHandler
from aioa_cloudops_agent.safety import DependencyCircuitBreaker
from aioa_cloudops_agent.verification import VerificationRequestHandler

from .contracts import (
    JudgeErrorCode,
    JudgeInvestigationOutcome,
    JudgeOutcomeClass,
)


class _Flow(Protocol):
    def execute(self, run: Run) -> object: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _session_manager(session_id: str, storage: object) -> SessionManager:
    return SnapshotSessionManager(
        session_id,
        storage=storage,
        save_latest_on="invocation",
    )


def _model(settings: object, boto_session: object) -> Model:
    return create_bedrock_model(settings, boto_session=boto_session)


@dataclass(frozen=True, slots=True)
class JudgeRuntimeDependencies:
    """Process-safe clients/config used to construct fresh request authority."""

    settings: JudgeRuntimeSettings
    repository: DurableTruthRepository
    snapshot_storage: object
    ec2_client: object
    cloudwatch_client: object
    bedrock_session: object
    dependency_circuit: DependencyCircuitBreaker
    stop_request_handler: StopRequestHandler
    verification_request_handler: VerificationRequestHandler


class JudgeInvestigationRuntime:
    """Create a new SnapshotSessionManager and Agent for every invocation."""

    def __init__(
        self,
        dependencies: JudgeRuntimeDependencies,
        *,
        clock: Callable[[], datetime] = _utc_now,
        run_id_factory: Callable[[], UUID] = generate_run_id,
        trace_id_factory: Callable[[], UUID] = generate_trace_id,
        correlation_id_factory: Callable[[], UUID] = generate_correlation_id,
        proposal_id_factory: Callable[[], UUID] = generate_proposal_id,
        event_id_factory: Callable[[], UUID] = generate_event_id,
        session_manager_factory: Callable[[str, object], SessionManager] = _session_manager,
        model_factory: Callable[[object, object], Model] = _model,
        agent_factory: Callable[..., PrimaryAgentRuntime] = create_primary_agent,
        flow_factory: Callable[..., _Flow] = BoundedInvestigationFlow,
        tracer: Tracer | None = None,
    ) -> None:
        if not isinstance(dependencies, JudgeRuntimeDependencies):
            raise TypeError("dependencies must be JudgeRuntimeDependencies")
        factories = (
            clock,
            run_id_factory,
            trace_id_factory,
            correlation_id_factory,
            proposal_id_factory,
            event_id_factory,
            session_manager_factory,
            model_factory,
            agent_factory,
            flow_factory,
        )
        if not all(callable(factory) for factory in factories):
            raise TypeError("runtime factories must be callable")
        if tracer is not None and not callable(
            getattr(tracer, "start_as_current_span", None)
        ):
            raise TypeError("tracer must expose start_as_current_span")
        self._dependencies = dependencies
        self._clock = clock
        self._run_id_factory = run_id_factory
        self._trace_id_factory = trace_id_factory
        self._correlation_id_factory = correlation_id_factory
        self._proposal_id_factory = proposal_id_factory
        self._event_id_factory = event_id_factory
        self._session_manager_factory = session_manager_factory
        self._model_factory = model_factory
        self._agent_factory = agent_factory
        self._flow_factory = flow_factory
        self._tracer = tracer or trace.get_tracer("aioa_cloudops_agent.judge")

    def investigate(self, request: JudgeInvestigationRequest) -> JudgeInvestigationOutcome:
        """Execute only the canonical server-owned investigation intent."""

        if not isinstance(request, JudgeInvestigationRequest):
            raise TypeError("request must be JudgeInvestigationRequest")
        run_id = self._run_id_factory()
        try:
            run = Run.new(
                run_id=run_id,
                trace_id=self._trace_id_factory(),
                correlation_id=self._correlation_id_factory(),
                idempotency_key=f"judge:{run_id}",
                created_at=self._clock(),
                budget=new_judge_budget(),
            )
        except Exception:
            return self._failed(
                run_id,
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                JudgeOutcomeClass.DEPENDENCY_UNAVAILABLE,
                retryable=True,
            )

        with self._tracer.start_as_current_span("aioa.judge.operation") as span:
            self._set_operation_span_identity(span, run)
            return self._investigate_run(run, span)

    def _investigate_run(self, run: Run, span: Span) -> JudgeInvestigationOutcome:
        """Execute one already-identified run and close its redacted telemetry span."""

        run_id = run.run_id
        try:
            identity = InvestigationIdentity.from_run(run)
            context = ExecutionContext(
                correlation_id=run.correlation_id,
                idempotency_key=run.idempotency_key,
                state=ExecutionState.INIT,
                authority_gate=AuthorityGate.AUTO,
                budget=ExecutionBudget(
                    max_turns=JUDGE_MAX_TURNS,
                    max_tokens=JUDGE_MAX_TOKENS,
                ),
            )
            dependencies = self._dependencies
            session_manager = self._session_manager_factory(
                f"judge-{run.run_id}",
                dependencies.snapshot_storage,
            )
            model = self._model_factory(
                dependencies.settings.bedrock,
                dependencies.bedrock_session,
            )
            agent_runtime = self._agent_factory(
                context=context,
                identity=identity,
                target=dependencies.settings.target,
                ec2_client=dependencies.ec2_client,
                cloudwatch_client=dependencies.cloudwatch_client,
                proposal_id=self._proposal_id_factory(),
                clock=self._clock,
                idle_policy=dependencies.settings.idle_policy,
                model_settings=dependencies.settings.bedrock,
                model=model,
                durable_repository=dependencies.repository,
                dependency_circuit=dependencies.dependency_circuit,
                session_manager=session_manager,
                tracer=self._tracer,
                stop_request_handler=dependencies.stop_request_handler,
                verification_request_handler=(
                    dependencies.verification_request_handler
                ),
            )
            flow = self._flow_factory(
                agent_runtime,
                dependencies.repository,
                clock=self._clock,
                event_id_factory=self._event_id_factory,
            )
            result = flow.execute(run)
        except Exception:
            return self._record_outcome(
                span,
                self._failed(
                    run_id,
                    JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                    JudgeOutcomeClass.DEPENDENCY_UNAVAILABLE,
                    retryable=True,
                ),
            )

        if getattr(result, "status", None) is ResultStatus.SUCCESS:
            completion = getattr(result, "value", None)
            proposal = getattr(completion, "proposal", None)
            proposal_id = getattr(proposal, "proposal_id", None)
            evidence_hash = getattr(proposal, "evidence_hash", None)
            final_state = getattr(completion, "final_state", None)
            try:
                return self._record_outcome(
                    span,
                    JudgeInvestigationOutcome(
                        run_id=run_id,
                        succeeded=True,
                        state=final_state,
                        outcome_class=JudgeOutcomeClass.REMEDIATION_PROPOSED,
                        proposal_id=proposal_id,
                        evidence_hash=evidence_hash,
                    ),
                )
            except Exception:
                return self._record_outcome(
                    span,
                    self._failed(
                        run_id,
                        JudgeErrorCode.INTERNAL_ERROR,
                        JudgeOutcomeClass.CLOSED_NON_SUCCESS,
                        retryable=False,
                    ),
                )

        failure = getattr(result, "failure", None)
        kind = getattr(failure, "kind", None)
        retryable = kind is FailureKind.DEPENDENCY_UNAVAILABLE and bool(
            getattr(failure, "retryable", False)
        )
        code, outcome = self._public_failure(kind)
        return self._record_outcome(
            span,
            self._failed(run_id, code, outcome, retryable=retryable),
        )

    @staticmethod
    def _set_operation_span_identity(span: Span, run: Run) -> None:
        """Attach only canonical identifiers and the reviewed route/dependency."""

        span.set_attribute("aioa.run_id", str(run.run_id))
        span.set_attribute("aioa.trace_id", str(run.trace_id))
        span.set_attribute("aioa.correlation_id", str(run.correlation_id))
        span.set_attribute("aioa.route", "/judge/investigate")
        span.set_attribute("aioa.dependency", "BEDROCK_MODEL")

    @staticmethod
    def _record_outcome(
        span: Span,
        outcome: JudgeInvestigationOutcome,
    ) -> JudgeInvestigationOutcome:
        """Record the closed public outcome class without provider or target detail."""

        span.set_attribute("aioa.outcome", outcome.outcome_class.value)
        return outcome

    @staticmethod
    def _public_failure(kind: object) -> tuple[JudgeErrorCode, JudgeOutcomeClass]:
        if kind is FailureKind.DEPENDENCY_UNAVAILABLE:
            return (
                JudgeErrorCode.DEPENDENCY_UNAVAILABLE,
                JudgeOutcomeClass.DEPENDENCY_UNAVAILABLE,
            )
        if kind is FailureKind.BUDGET_EXHAUSTION:
            return JudgeErrorCode.BUDGET_EXHAUSTED, JudgeOutcomeClass.BUDGET_EXHAUSTED
        if kind is FailureKind.RECOVERY_REQUIREMENT:
            return JudgeErrorCode.RECOVERY_REQUIRED, JudgeOutcomeClass.RECOVERY_REQUIRED
        if kind is FailureKind.VALIDATION_FAILURE:
            return JudgeErrorCode.INVESTIGATION_INVALID, JudgeOutcomeClass.CLOSED_NON_SUCCESS
        if kind is FailureKind.AMBIGUOUS_RESULT:
            return (
                JudgeErrorCode.EVIDENCE_AMBIGUOUS,
                JudgeOutcomeClass.EVIDENCE_AMBIGUOUS,
            )
        return JudgeErrorCode.INVESTIGATION_DENIED, JudgeOutcomeClass.CLOSED_NON_SUCCESS

    @staticmethod
    def _failed(
        run_id: UUID,
        code: JudgeErrorCode,
        outcome: JudgeOutcomeClass,
        *,
        retryable: bool,
    ) -> JudgeInvestigationOutcome:
        return JudgeInvestigationOutcome(
            run_id=run_id,
            succeeded=False,
            outcome_class=outcome,
            error_code=code,
            retryable=retryable,
        )
