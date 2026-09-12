import json
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from strands.models import Model

from aioa_cloudops_agent.agent import (
    ApprovalResumeRequest,
    BoundedInvestigationFlow,
    DurableApprovalFlow,
    PrimaryAgentRuntime,
    create_primary_agent,
)
from aioa_cloudops_agent.cloudops import (
    InspectInstanceService,
    InvestigationIdentity,
    SandboxTarget,
)
from aioa_cloudops_agent.config import VerificationSettings
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    ApprovalDecision,
    AuditEvent,
    BudgetCounters,
    ExecutionAcknowledgement,
    IdempotencyStatus,
    ObservedInstanceState,
    ResultStatus,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.persistence import derive_idempotency_key
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.remediation import (
    StopExecutionCommand,
    StopSandboxInstanceCoordinator,
)
from aioa_cloudops_agent.safety import (
    BoundedReadRetry,
    CircuitDependency,
    DependencyCircuitBreaker,
)
from aioa_cloudops_agent.verification import (
    BoundedVerificationCoordinator,
    VerifyInstanceStateService,
)

INSTANCE_ID = "i-0123456789abcdef0"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVIDENCE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9bdc")
NOW = datetime(2026, 8, 23, 21, 0, tzinfo=UTC)


class UuidFactory:
    def __init__(self, start: int) -> None:
        self.value = start

    def __call__(self) -> UUID:
        result = UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{self.value:02x}")
        self.value += 1
        return result


class FullWorkflowModel(Model):
    """Drive the real Strands loop while every provider boundary remains synthetic."""

    def __init__(self) -> None:
        self.calls = 0
        self.denial_resume = False
        self.config: dict[str, object] = {}
        self.tool_specs_seen: list[tuple[str, ...]] = []

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        if False:
            yield {}

    async def stream(
        self,
        messages: object,
        tool_specs: list[dict[str, object]] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> Any:
        del messages, system_prompt, kwargs
        self.calls += 1
        self.tool_specs_seen.append(tuple(spec["name"] for spec in (tool_specs or [])))
        plan: dict[int, tuple[str, dict[str, object]]] = {
            1: ("inspect_instance", {"instance_id": INSTANCE_ID}),
            2: ("read_utilization_metrics", {"instance_id": INSTANCE_ID}),
            3: ("build_remediation_evidence", {"instance_id": INSTANCE_ID}),
            5: ("stop_sandbox_instance", {"proposal_id": str(PROPOSAL_ID)}),
        }
        if not self.denial_resume:
            plan[6] = ("verify_instance_state", {"proposal_id": str(PROPOSAL_ID)})

        yield {"messageStart": {"role": "assistant"}}
        if self.calls in plan:
            name, tool_input = plan[self.calls]
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": f"workflow-tool-{self.calls}",
                            "name": name,
                        }
                    },
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": json.dumps(tool_input)}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            final = (
                "Evidence-backed investigation complete; human approval is still absent."
                if self.calls == 4
                else "Durable workflow processing complete; state remains application-owned."
            )
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"text": final},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
                "metrics": {"latencyMs": 1},
            }
        }


class SequencedEc2Client:
    def __init__(self) -> None:
        self.states = ["running", "stopped"]
        self.calls: list[list[str]] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        self.calls.append(InstanceIds)
        state = self.states.pop(0)
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE_ID,
                            "State": {"Name": state},
                            "InstanceType": "t3.micro",
                            "LaunchTime": NOW - timedelta(hours=2),
                            "Monitoring": {"State": "disabled"},
                            "Placement": {"AvailabilityZone": "eu-central-1a"},
                            "Tags": [
                                {
                                    "Key": "AIOACloudOpsSandbox",
                                    "Value": "true",
                                }
                            ],
                        }
                    ]
                }
            ]
        }


class IdleCloudWatchClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        return {
            "Datapoints": [
                {
                    "Timestamp": NOW - timedelta(minutes=5 * (index + 1)),
                    "Average": float(index + 1),
                    "Unit": "Percent",
                }
                for index in range(6)
            ]
        }


class RecordingPrivateExecutor:
    def __init__(self) -> None:
        self.commands: list[StopExecutionCommand] = []

    def execute(self, command: StopExecutionCommand) -> ExecutionAcknowledgement:
        self.commands.append(command)
        return ExecutionAcknowledgement(
            proposal_id=command.proposal_id,
            run_id=command.run_id,
            target=command.target,
            current_state=ObservedInstanceState.STOPPING,
            request_reference="request-safe-e2e",
            acknowledged_at=NOW + timedelta(seconds=20),
            acknowledgement_hash="c" * 64,
        )


class RecordingRepository(InMemoryTestDurableTruthRepository):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[AuditEvent] = []

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self.events.append(event)
        return super().append_audit_event(event)


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
        self.span_names: list[str] = []
        self.spans: list[RecordingSpan] = []

    def start_as_current_span(self, name: str) -> SpanContext:
        self.span_names.append(name)
        span = RecordingSpan()
        self.spans.append(span)
        return SpanContext(span)


@dataclass(slots=True)
class WorkflowHarness:
    runtime: PrimaryAgentRuntime
    run: Run
    investigation: BoundedInvestigationFlow
    approval: DurableApprovalFlow
    remediation: StopSandboxInstanceCoordinator
    verification: BoundedVerificationCoordinator
    repository: RecordingRepository
    model: FullWorkflowModel
    ec2: SequencedEc2Client
    executor: RecordingPrivateExecutor
    tracer: RecordingTracer


def _build_harness() -> WorkflowHarness:
    repository = RecordingRepository()
    model = FullWorkflowModel()
    ec2 = SequencedEc2Client()
    cloudwatch = IdleCloudWatchClient()
    executor = RecordingPrivateExecutor()
    tracer = RecordingTracer()
    dependency_circuit = DependencyCircuitBreaker()
    target = SandboxTarget(instance_id=INSTANCE_ID)
    identity = InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )
    remediation = StopSandboxInstanceCoordinator(
        repository,
        executor,
        clock=lambda: NOW + timedelta(seconds=20),
        event_id_factory=UuidFactory(128),
    )
    verification = BoundedVerificationCoordinator(
        repository,
        VerifyInstanceStateService(
            InspectInstanceService(
                ec2,
                target,
                retry=BoundedReadRetry(
                    circuit_breaker=dependency_circuit,
                    dependency=CircuitDependency.VERIFICATION_READ,
                ),
            ),
            target,
        ),
        settings=VerificationSettings(max_attempts=2, interval_seconds=0),
        clock=lambda: NOW + timedelta(seconds=30),
        sleeper=lambda _: None,
        event_id_factory=UuidFactory(160),
        evidence_id_factory=lambda: EVIDENCE_ID,
    )
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:e2e",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=identity,
        target=target,
        ec2_client=ec2,
        cloudwatch_client=cloudwatch,
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
        model=model,
        durable_repository=repository,
        stop_request_handler=remediation.for_tool,
        verification_request_handler=verification.for_tool,
        dependency_circuit=dependency_circuit,
        tracer=tracer,
    )
    return WorkflowHarness(
        runtime=runtime,
        run=Run.new(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:e2e",
            created_at=NOW,
            budget=BudgetCounters(max_turns=8, max_tokens=8_192),
        ),
        investigation=BoundedInvestigationFlow(
            runtime,
            repository,
            clock=lambda: NOW,
            event_id_factory=UuidFactory(64),
        ),
        approval=DurableApprovalFlow(
            runtime,
            repository,
            clock=lambda: NOW + timedelta(seconds=10),
            event_id_factory=UuidFactory(96),
        ),
        remediation=remediation,
        verification=verification,
        repository=repository,
        model=model,
        ec2=ec2,
        executor=executor,
        tracer=tracer,
    )


def _resume_request(interrupt: object, decision: ApprovalDecision) -> ApprovalResumeRequest:
    assert hasattr(interrupt, "payload")
    payload = interrupt.payload
    return ApprovalResumeRequest(
        interrupt_id=interrupt.interrupt_id,
        proposal_id=payload.proposal_id,
        run_id=payload.run_id,
        action=payload.action,
        target=payload.target,
        evidence_hash=payload.evidence_hash,
        request_hash=interrupt.request_hash,
        decision=decision,
        actor_session_id="human-session-e2e",
        decision_nonce="decision-nonce-e2e-0001",
    )


def test_full_mocked_approved_e2e_closes_only_with_independent_durable_evidence() -> None:
    harness = _build_harness()

    investigation = harness.investigation.execute(harness.run)
    assert investigation.status is ResultStatus.SUCCESS
    interrupt = harness.approval.request(PROPOSAL_ID).value
    assert interrupt is not None
    resumed = harness.approval.resume(
        _resume_request(interrupt, ApprovalDecision.APPROVED)
    )

    assert resumed.status is ResultStatus.SUCCESS
    run = harness.repository.get_run(RUN_ID)
    proposal = harness.repository.get_proposal(PROPOSAL_ID)
    evidence = harness.repository.get_verification_evidence(RUN_ID, PROPOSAL_ID)
    assert run is not None and run.state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert proposal is not None and evidence is not None
    assert evidence.run_id == RUN_ID
    assert evidence.trace_id == TRACE_ID
    assert evidence.correlation_id == CORRELATION_ID
    assert evidence.proposal_id == PROPOSAL_ID
    assert evidence.target.resource_id == INSTANCE_ID
    idempotency = harness.repository.get_idempotency(derive_idempotency_key(proposal))
    assert idempotency is not None and idempotency.status is IdempotencyStatus.COMPLETED
    assert idempotency.action_result is not None
    assert idempotency.action_result.evidence_hash == evidence.evidence_hash
    assert len(harness.executor.commands) == 1
    assert harness.ec2.calls == [[INSTANCE_ID], [INSTANCE_ID]]
    assert harness.model.calls == 7
    assert all(
        names == harness.runtime.registered_tool_names
        for names in harness.model.tool_specs_seen
    )
    assert all(event.run_id == RUN_ID for event in harness.repository.events)
    assert all(
        event.metadata.get("trace_id") == str(TRACE_ID)
        and event.metadata.get("correlation_id") == str(CORRELATION_ID)
        for event in harness.repository.events
    )

    duplicate_stop = harness.remediation.execute(PROPOSAL_ID)
    duplicate_verify = harness.verification.verify(PROPOSAL_ID)
    assert duplicate_stop.status is ResultStatus.SUCCESS
    assert duplicate_verify.status is ResultStatus.SUCCESS
    assert duplicate_verify.value is not None and duplicate_verify.value.reconciled is True
    assert len(harness.executor.commands) == 1
    assert harness.ec2.calls == [[INSTANCE_ID], [INSTANCE_ID]]


def test_full_mocked_denied_e2e_is_terminal_with_zero_executor_calls() -> None:
    harness = _build_harness()

    investigation = harness.investigation.execute(harness.run)
    assert investigation.status is ResultStatus.SUCCESS
    interrupt = harness.approval.request(PROPOSAL_ID).value
    assert interrupt is not None
    harness.model.denial_resume = True
    resumed = harness.approval.resume(_resume_request(interrupt, ApprovalDecision.DENIED))

    assert resumed.status is ResultStatus.SUCCESS
    run = harness.repository.get_run(RUN_ID)
    assert run is not None and run.state is WorkflowState.DENIED_BY_HUMAN
    assert harness.repository.get_verification_evidence(RUN_ID, PROPOSAL_ID) is None
    assert harness.executor.commands == []
    assert harness.ec2.calls == [[INSTANCE_ID]]
    assert harness.model.calls == 6


def test_full_workflow_preserves_trace_lineage_across_agent_tools_store_execution_and_verification() -> None:
    harness = _build_harness()

    investigation = harness.investigation.execute(harness.run)
    assert investigation.value is not None
    interrupt = harness.approval.request(PROPOSAL_ID).value
    assert interrupt is not None
    resolution = harness.approval.resume(
        _resume_request(interrupt, ApprovalDecision.APPROVED)
    )

    assert resolution.status is ResultStatus.SUCCESS
    identity_attributes = {
        "aioa.run_id": str(RUN_ID),
        "aioa.trace_id": str(TRACE_ID),
        "aioa.correlation_id": str(CORRELATION_ID),
    }
    assert all(
        harness.runtime.agent.trace_attributes[name] == value
        for name, value in identity_attributes.items()
    )
    assert harness.tracer.span_names == [
        "cloudops.inspect_instance",
        "cloudops.read_utilization_metrics",
        "cloudops.build_remediation_evidence",
        "cloudops.stop_sandbox_instance",
        "cloudops.verify_instance_state",
    ]
    assert all(
        all(span.attributes[name] == value for name, value in identity_attributes.items())
        for span in harness.tracer.spans
    )

    proposal = harness.repository.get_proposal(PROPOSAL_ID)
    approval = harness.repository.get_approval(PROPOSAL_ID)
    verification = harness.repository.get_verification_evidence(RUN_ID, PROPOSAL_ID)
    run = harness.repository.get_run(RUN_ID)
    command = harness.executor.commands[0]
    assert proposal is not None and proposal.run_id == RUN_ID
    assert interrupt.payload.run_id == RUN_ID
    assert interrupt.trace_id == TRACE_ID
    assert interrupt.correlation_id == CORRELATION_ID
    assert approval is not None and approval.run_id == RUN_ID
    assert run is not None
    assert (run.run_id, run.trace_id, run.correlation_id) == (
        RUN_ID,
        TRACE_ID,
        CORRELATION_ID,
    )
    assert (command.run_id, command.trace_id, command.correlation_id) == (
        RUN_ID,
        TRACE_ID,
        CORRELATION_ID,
    )
    assert verification is not None
    assert (
        verification.run_id,
        verification.trace_id,
        verification.correlation_id,
    ) == (RUN_ID, TRACE_ID, CORRELATION_ID)
    assert all(event.run_id == RUN_ID for event in harness.repository.events)
    assert all(
        event.metadata["trace_id"] == str(TRACE_ID)
        and event.metadata["correlation_id"] == str(CORRELATION_ID)
        for event in harness.repository.events
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("run_id", UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4a")),
        ("trace_id", UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4b")),
        ("correlation_id", UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4c")),
    ],
)
def test_substituted_workflow_identity_fails_closed_without_execution(
    field: str,
    value: UUID,
) -> None:
    harness = _build_harness()
    substituted = harness.run.model_copy(update={field: value})

    result = harness.investigation.execute(substituted)

    assert result.status is ResultStatus.FAILURE
    assert result.failure is not None
    assert result.failure.kind is not None
    assert result.failure.code == "RUN_IDENTITY_INVALID"
    assert harness.repository.get_run(RUN_ID) is None
    assert harness.repository.get_proposal(PROPOSAL_ID) is None
    assert harness.repository.get_approval(PROPOSAL_ID) is None
    assert harness.model.calls == 0
    assert harness.executor.commands == []
    assert harness.ec2.calls == []
