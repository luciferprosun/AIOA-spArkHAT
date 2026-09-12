import json
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from strands.models import Model
from strands.session import SnapshotSessionManager
from strands.storage import LocalFileStorage

from aioa_cloudops_agent.agent import (
    ApprovalInterrupt,
    ApprovalResumeRequest,
    DurableApprovalFlow,
    create_primary_agent,
)
from aioa_cloudops_agent.cloudops import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.deployment import (
    AuthenticatedApprovalResumeService,
    AuthenticatedJudgePrincipal,
)
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionTarget,
    ApprovalDecision,
    AuditEventType,
    BudgetCounters,
    Capability,
    Checkpoint,
    ExpectedPrecondition,
    ObservedInstanceState,
    ProposalState,
    ResultStatus,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository

INSTANCE_ID = "i-0123456789abcdef0"
OTHER_INSTANCE_ID = "i-0fedcba9876543210"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3d")
EVENT_IDS = tuple(
    UUID(f"01890f6c-3311-7abc-8f4a-6e4f7f0b9b{value:02x}")
    for value in range(80, 100)
)
NOW = datetime(2026, 8, 23, 18, 0, tzinfo=UTC)
DIGEST = "a" * 64


class ScriptedApprovalModel(Model):
    """Request the canonical stop once, then finish after native resume."""

    def __init__(self, proposal_id: UUID = PROPOSAL_ID, *, initial_calls: int = 0) -> None:
        self.proposal_id = proposal_id
        self.calls = initial_calls
        self.config: dict[str, object] = {}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        if False:
            yield {}

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if self.calls == 1:
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": "stop-approval-1",
                            "name": "stop_sandbox_instance",
                        }
                    },
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {
                        "toolUse": {
                            "input": json.dumps({"proposal_id": str(self.proposal_id)})
                        }
                    },
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"text": "Native approval resume completed."},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 5, "outputTokens": 5, "totalTokens": 10},
                "metrics": {"latencyMs": 1},
            }
        }


class NonCallingEc2Client:
    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        raise AssertionError(f"unexpected EC2 call: {InstanceIds!r}")


class NonCallingCloudWatchClient:
    def get_metric_statistics(self, **kwargs: object) -> dict[str, object]:
        raise AssertionError(f"unexpected CloudWatch call: {kwargs!r}")


class EventIdFactory:
    def __init__(self, start: int = 0) -> None:
        self.index = start

    def __call__(self) -> UUID:
        value = EVENT_IDS[self.index]
        self.index += 1
        return value


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class ApprovalFailingRepository(InMemoryTestDurableTruthRepository):
    def create_approval(self, approval: object) -> object:
        raise StorageDependencyError("simulated durable approval outage")


def _proposal() -> ActionProposal:
    return ActionProposal(
        proposal_id=PROPOSAL_ID,
        run_id=RUN_ID,
        action=Capability.STOP_SANDBOX_INSTANCE,
        target=ActionTarget(
            resource_id=INSTANCE_ID,
            sandbox_scope="hackathon-sandbox",
        ),
        expected_precondition=ExpectedPrecondition(
            instance_state=ObservedInstanceState.RUNNING,
            observed_at=NOW,
            evidence_hash=DIGEST,
        ),
        authority=AuthorityGate.PLAN_AND_CONFIRM,
        state=ProposalState.PROPOSED,
        evidence_hash=DIGEST,
        created_at=NOW,
    )


def _repository(
    repository: InMemoryTestDurableTruthRepository | None = None,
) -> InMemoryTestDurableTruthRepository:
    actual = repository or InMemoryTestDurableTruthRepository()
    run = actual.create_run(
        Run.new(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:0001",
            created_at=NOW,
            budget=BudgetCounters(max_turns=8, max_tokens=8_192),
        )
    )
    for offset, state in enumerate(
        (
            WorkflowState.INVESTIGATING,
            WorkflowState.EVIDENCE_READY,
            WorkflowState.REMEDIATION_PROPOSED,
        ),
        start=1,
    ):
        run = actual.transition_run(
            RUN_ID,
            state,
            expected_state=run.state,
            expected_version=run.version,
            updated_at=NOW + timedelta(seconds=offset),
        )
    actual.create_proposal(_proposal())
    actual.save_checkpoint(
        Checkpoint(
            run_id=RUN_ID,
            last_safe_state=WorkflowState.REMEDIATION_PROPOSED,
            resume_metadata={"proposal_id": str(PROPOSAL_ID)},
            tool_result_hashes={"build_remediation_evidence": DIGEST},
            created_at=NOW + timedelta(seconds=3),
            version=1,
        ),
        expected_version=None,
    )
    return actual


def _flow(
    *,
    repository: InMemoryTestDurableTruthRepository | None = None,
    decision_clock: Callable[[], datetime] | None = None,
    repository_prepared: bool = False,
    model: ScriptedApprovalModel | None = None,
    session_manager: SnapshotSessionManager | None = None,
    event_id_start: int = 0,
) -> tuple[
    DurableApprovalFlow,
    InMemoryTestDurableTruthRepository,
    ScriptedApprovalModel,
    list[UUID],
]:
    actual_repository = (
        repository
        if repository_prepared and repository is not None
        else _repository(repository)
    )
    assert actual_repository is not None
    actual_model = model or ScriptedApprovalModel()
    stop_calls: list[UUID] = []

    def approval_only_boundary(proposal_id: UUID) -> dict[str, object]:
        approval = actual_repository.get_approval(proposal_id)
        run = actual_repository.get_run(RUN_ID)
        assert approval is not None
        assert approval.decision is ApprovalDecision.APPROVED
        assert run is not None and run.state is WorkflowState.APPROVED
        stop_calls.append(proposal_id)
        return {
            "status": "SUCCESS",
            "value": {
                "proposal_id": str(proposal_id),
                "execution": "NOT_IMPLEMENTED_IN_DAY_8",
            },
            "failure": None,
        }

    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key="request:idle-ec2:0001",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=InvestigationIdentity(
            run_id=RUN_ID,
            trace_id=TRACE_ID,
            correlation_id=CORRELATION_ID,
        ),
        target=SandboxTarget(instance_id=INSTANCE_ID),
        ec2_client=NonCallingEc2Client(),
        cloudwatch_client=NonCallingCloudWatchClient(),
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
        model=actual_model,
        durable_repository=actual_repository,
        session_manager=session_manager,
        stop_request_handler=approval_only_boundary,
    )
    return (
        DurableApprovalFlow(
            runtime,
            actual_repository,
            clock=decision_clock or (lambda: NOW + timedelta(seconds=10)),
            event_id_factory=EventIdFactory(event_id_start),
        ),
        actual_repository,
        actual_model,
        stop_calls,
    )


def _resume(request: object, decision: ApprovalDecision) -> ApprovalResumeRequest:
    assert hasattr(request, "payload")
    payload = request.payload
    return ApprovalResumeRequest(
        interrupt_id=request.interrupt_id,
        proposal_id=payload.proposal_id,
        run_id=payload.run_id,
        action=payload.action,
        target=payload.target,
        evidence_hash=payload.evidence_hash,
        request_hash=request.request_hash,
        decision=decision,
        actor_session_id="human-session-001",
        decision_nonce="decision-nonce-0001",
    )


def _restore_cold_start_repository(
    payload: dict[str, object],
) -> InMemoryTestDurableTruthRepository:
    """Restore typed durable fake records without retaining parent-process objects."""

    run = Run.model_validate(payload["run"])
    proposal = ActionProposal.model_validate(payload["proposal"])
    checkpoint = Checkpoint.model_validate(payload["checkpoint"])
    repository = InMemoryTestDurableTruthRepository()
    repository._runs[run.run_id] = run
    repository._proposals[proposal.proposal_id] = proposal
    repository._checkpoints[checkpoint.run_id] = checkpoint
    return repository


def _cold_start_resume_worker(
    state_path: Path,
    result_path: Path,
    storage_path: Path,
) -> None:
    """Resume in a fresh interpreter using only typed files and local fakes."""

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError("cold-start state must be an object")
    repository = _restore_cold_start_repository(payload)
    interrupt = ApprovalInterrupt.model_validate(payload["interrupt"])
    principal = AuthenticatedJudgePrincipal.model_validate(payload["principal"])
    challenge = sys.stdin.read()
    if len(challenge) < 32 or challenge != challenge.strip():
        raise TypeError("cold-start challenge must be an exact bounded string")
    manager = SnapshotSessionManager(
        str(RUN_ID),
        storage=LocalFileStorage(str(storage_path)),
        save_latest_on="invocation",
    )
    flow, _, model, stop_calls = _flow(
        repository=repository,
        repository_prepared=True,
        model=ScriptedApprovalModel(initial_calls=1),
        session_manager=manager,
        event_id_start=1,
    )
    authority = AuthenticatedApprovalResumeService(
        flow,
        repository,
        clock=lambda: NOW + timedelta(seconds=11),
        challenge_factory=lambda: "unused-server-placeholder-0000000000",
    )

    result = authority.resume(
        interrupt=interrupt,
        decision=ApprovalDecision.APPROVED,
        principal=principal,
        challenge=challenge,
    )
    replay_rejected = False
    try:
        authority.resume(
            interrupt=interrupt,
            decision=ApprovalDecision.APPROVED,
            principal=principal,
            challenge=challenge,
        )
    except StorageConflictError as error:
        replay_rejected = "challenge was rejected" in str(error)
    run = repository.get_run(RUN_ID)
    approval = repository.get_approval(PROPOSAL_ID)
    result_path.write_text(
        json.dumps(
            {
                "approval_count": int(approval is not None),
                "model_calls": model.calls,
                "native_resume_completed": bool(
                    result.value is not None and result.value.native_resume_completed
                ),
                "pid": os.getpid(),
                "replay_rejected": replay_rejected,
                "run_state": run.state.value if run is not None else None,
                "status": result.status.value,
                "stop_calls": [str(proposal_id) for proposal_id in stop_calls],
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_native_interrupt_is_durable_and_payload_comes_from_proposal() -> None:
    flow, repository, model, stop_calls = _flow()

    result = flow.request(PROPOSAL_ID)

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.interrupt_id.startswith("v1:before_tool_call:")
    assert result.value.payload.target.resource_id == INSTANCE_ID
    assert result.value.payload.action is Capability.STOP_SANDBOX_INSTANCE
    assert result.value.payload.authority is AuthorityGate.PLAN_AND_CONFIRM
    assert result.value.payload.evidence_hash == DIGEST
    assert "reversible" in result.value.payload.impact_summary
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert repository.get_proposal(PROPOSAL_ID).state is ProposalState.AWAITING_APPROVAL
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    assert checkpoint.resume_metadata["approval_interrupt_id"] == result.value.interrupt_id
    assert checkpoint.resume_metadata["approval_request_hash"] == result.value.request_hash
    assert repository.get_approval(PROPOSAL_ID) is None
    assert model.calls == 1
    assert stop_calls == []


def test_positive_native_resume_persists_approval_before_safe_tool_boundary() -> None:
    flow, repository, model, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None

    result = flow.resume(_resume(interrupt, ApprovalDecision.APPROVED))

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.APPROVED
    assert result.value.native_resume_completed is True
    approval = repository.get_approval(PROPOSAL_ID)
    assert approval is not None
    assert approval.run_id == RUN_ID
    assert approval.target.resource_id == INSTANCE_ID
    assert approval.evidence_hash == DIGEST
    assert approval.request_hash == interrupt.request_hash
    assert stop_calls == [PROPOSAL_ID]
    assert model.calls == 2


def test_fresh_process_restores_native_interrupt_with_trusted_one_time_freshness(
    tmp_path: Path,
) -> None:
    repository = _repository()
    storage_path = tmp_path / "strands"
    storage = LocalFileStorage(str(storage_path))
    first_manager = SnapshotSessionManager(
        str(RUN_ID),
        storage=storage,
        save_latest_on="invocation",
    )
    first_flow, _, first_model, _ = _flow(
        repository=repository,
        repository_prepared=True,
        session_manager=first_manager,
    )
    interrupt = first_flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    principal = AuthenticatedJudgePrincipal()
    first_authority = AuthenticatedApprovalResumeService(
        first_flow,
        repository,
        clock=lambda: NOW + timedelta(seconds=10),
        challenge_factory=lambda: "server-issued-freshness-placeholder-0001",
    )
    issued = first_authority.issue(interrupt, principal)
    challenge = issued.value.get_secret_value()
    assert first_model.calls == 1
    run = repository.get_run(RUN_ID)
    proposal = repository.get_proposal(PROPOSAL_ID)
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert run is not None and proposal is not None and checkpoint is not None
    state_path = tmp_path / "durable-state.json"
    result_path = tmp_path / "cold-start-result.json"
    state_path.write_text(
        json.dumps(
            {
                "checkpoint": checkpoint.model_dump(mode="json"),
                "interrupt": interrupt.model_dump(mode="json"),
                "principal": principal.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
                "run": run.model_dump(mode="json"),
            },
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    del first_flow, first_manager, first_model, first_authority, repository, storage
    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--cold-start-resume-worker",
            str(state_path),
            str(result_path),
            str(storage_path),
        ],
        cwd=Path(__file__).parents[2],
        check=False,
        capture_output=True,
        input=challenge,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr
    child = json.loads(result_path.read_text(encoding="utf-8"))
    assert child == {
        "approval_count": 1,
        "model_calls": 2,
        "native_resume_completed": True,
        "pid": child["pid"],
        "replay_rejected": True,
        "run_state": WorkflowState.APPROVED.value,
        "status": ResultStatus.SUCCESS.value,
        "stop_calls": [str(PROPOSAL_ID)],
    }
    assert isinstance(child["pid"], int)
    assert child["pid"] != os.getpid()


def test_negative_native_resume_is_terminal_and_never_calls_stop_boundary() -> None:
    flow, repository, model, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None

    result = flow.resume(_resume(interrupt, ApprovalDecision.DENIED))

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.DENIED_BY_HUMAN
    assert repository.get_approval(PROPOSAL_ID).decision is ApprovalDecision.DENIED
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_HUMAN
    assert stop_calls == []
    assert model.calls == 2


@pytest.mark.parametrize(
    "field_update",
    [
        {"evidence_hash": "b" * 64},
        {
            "target": ActionTarget(
                resource_id=OTHER_INSTANCE_ID,
                sandbox_scope="hackathon-sandbox",
            )
        },
        {"action": Capability.VERIFY_INSTANCE_STATE},
        {"request_hash": "c" * 64},
        {"interrupt_id": "v1:before_tool_call:tampered"},
    ],
)
def test_tampered_resume_fails_closed_without_decision_or_tool_call(
    field_update: dict[str, object],
) -> None:
    flow, repository, _, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    response = _resume(interrupt, ApprovalDecision.APPROVED).model_copy(
        update=field_update
    )

    result = flow.resume(response)

    assert result.status is ResultStatus.FAILURE
    assert repository.get_approval(PROPOSAL_ID) is None
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert stop_calls == []
    denial = repository.get_audit_event(RUN_ID, EVENT_IDS[1])
    assert denial is not None
    assert denial.type is AuditEventType.POLICY_DENIED
    assert denial.metadata["policy_code"] == "APPROVAL_BINDING_MISMATCH"


def test_duplicate_identical_resume_reconciles_without_second_tool_call() -> None:
    flow, repository, _, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    response = _resume(interrupt, ApprovalDecision.APPROVED)

    first = flow.resume(response)
    duplicate = flow.resume(response)

    assert first.status is ResultStatus.SUCCESS
    assert duplicate.status is ResultStatus.SUCCESS
    assert duplicate.value is not None and duplicate.value.reconciled is True
    assert repository.get_approval(PROPOSAL_ID) is not None
    assert stop_calls == [PROPOSAL_ID]


def test_duplicate_resume_after_lost_response_keeps_original_decision_timestamp() -> None:
    clock = MutableClock(NOW + timedelta(seconds=10))
    flow, repository, model, stop_calls = _flow(decision_clock=clock)
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    response = _resume(interrupt, ApprovalDecision.APPROVED)
    first = flow.resume(response)
    persisted = repository.get_approval(PROPOSAL_ID)
    assert first.status is ResultStatus.SUCCESS
    assert persisted is not None

    clock.value = NOW + timedelta(hours=1)
    duplicate = flow.resume(response)

    assert duplicate.status is ResultStatus.SUCCESS
    assert duplicate.value is not None and duplicate.value.reconciled is True
    assert repository.get_approval(PROPOSAL_ID).decided_at == persisted.decided_at
    assert stop_calls == [PROPOSAL_ID]
    assert model.calls == 2


def test_changed_decision_nonce_replay_is_rejected_without_second_tool_call() -> None:
    flow, repository, _, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    response = _resume(interrupt, ApprovalDecision.APPROVED)
    first = flow.resume(response)

    replay = flow.resume(
        response.model_copy(update={"decision_nonce": "decision-nonce-replayed"})
    )

    assert first.status is ResultStatus.SUCCESS
    assert replay.status is ResultStatus.FAILURE
    assert replay.failure is not None
    assert replay.failure.code == "APPROVAL_DECISION_CONFLICT"
    assert repository.get_approval(PROPOSAL_ID).decision_nonce == "decision-nonce-0001"
    assert stop_calls == [PROPOSAL_ID]


def test_conflicting_second_decision_is_rejected() -> None:
    flow, repository, _, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    flow.resume(_resume(interrupt, ApprovalDecision.APPROVED))

    conflict = flow.resume(_resume(interrupt, ApprovalDecision.DENIED))

    assert conflict.status is ResultStatus.FAILURE
    assert repository.get_approval(PROPOSAL_ID).decision is ApprovalDecision.APPROVED
    assert stop_calls == [PROPOSAL_ID]


def test_approval_persistence_failure_blocks_approved_transition() -> None:
    flow, repository, _, stop_calls = _flow(repository=ApprovalFailingRepository())
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None

    result = flow.resume(_resume(interrupt, ApprovalDecision.APPROVED))

    assert result.status is ResultStatus.FAILURE
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert stop_calls == []


def test_malformed_or_model_like_approval_cannot_become_a_decision() -> None:
    flow, repository, _, stop_calls = _flow()
    interrupt = flow.request(PROPOSAL_ID).value
    assert interrupt is not None
    payload = _resume(interrupt, ApprovalDecision.APPROVED).model_dump(mode="json")
    payload["approval"] = True

    with pytest.raises(ValidationError):
        ApprovalResumeRequest.model_validate(payload)
    result = flow.resume(payload)  # type: ignore[arg-type]
    assert result.status is ResultStatus.FAILURE
    assert repository.get_approval(PROPOSAL_ID) is None
    assert stop_calls == []


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--cold-start-resume-worker":
        raise SystemExit("unsupported test helper invocation")
    _cold_start_resume_worker(
        Path(sys.argv[2]),
        Path(sys.argv[3]),
        Path(sys.argv[4]),
    )
