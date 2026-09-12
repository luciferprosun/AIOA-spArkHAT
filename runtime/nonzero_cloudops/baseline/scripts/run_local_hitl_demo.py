"""Run one complete credential-free Local-2 human authorization scenario."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from aioa_cloudops_agent.agent import (
    LocalDecisionRequest,
    LocalOperatorPrincipal,
    create_local_hitl_runtime,
)
from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
)
from aioa_cloudops_agent.config import LocalHitlSettings, RuntimeSettings
from aioa_cloudops_agent.nz import (
    ApprovalDecision,
    BudgetCounters,
    CloudResourceType,
    ResourceQuery,
    ResultStatus,
    Run,
    generate_run_id,
    generate_trace_id,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        choices=("elastic-ip", "security-group"),
        default="elastic-ip",
    )
    parser.add_argument(
        "--decision",
        choices=("approved", "denied"),
        default="approved",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".local/aioa-local2-demo"),
    )
    return parser.parse_args()


def _fail(stage: str, result: object) -> int:
    failure = getattr(result, "failure", None)
    payload = {
        "ok": False,
        "stage": stage,
        "failure": (
            failure.model_dump(mode="json", exclude_none=True)
            if failure is not None
            else {"code": "AMBIGUOUS_DEMO_FAILURE"}
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1


def main() -> int:
    started_at = time.monotonic()
    args = _arguments()
    run_id = generate_run_id()
    output_dir = args.output_dir / str(run_id)
    settings = LocalHitlSettings(
        state_path=output_dir / "durable-truth.json",
        inventory_path=output_dir / "mock-inventory.json",
    )
    runtime_settings = RuntimeSettings.from_environment()
    runtime = create_local_hitl_runtime(settings, runtime_settings=runtime_settings)
    now = datetime.now(UTC)
    run = Run.new(
        run_id=run_id,
        trace_id=generate_trace_id(),
        correlation_id=generate_trace_id(),
        idempotency_key=f"local/demo/{run_id}",
        created_at=now,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )
    target = (
        (CloudResourceType.ELASTIC_IP, MOCK_UNATTACHED_EIP_ID)
        if args.scenario == "elastic-ip"
        else (CloudResourceType.SECURITY_GROUP, MOCK_UNSAFE_SECURITY_GROUP_ID)
    )
    planned = runtime.phase_one.execute(
        run,
        ResourceQuery(resource_type=target[0], resource_id=target[1]),
    )
    if planned.status is ResultStatus.FAILURE or planned.value is None:
        return _fail("plan", planned)
    if runtime.executor.mutation_calls != 0:
        return _fail("pending_approval_mutation_guard", planned)
    runtime = create_local_hitl_runtime(settings, runtime_settings=runtime_settings)
    recovered_pending = runtime.repository.get_run(run_id)
    if recovered_pending is None or recovered_pending.state.value != "AWAITING_APPROVAL":
        return _fail("pending_approval_recovery", planned)
    principal = LocalOperatorPrincipal(actor_session_id="local-demo-operator")
    challenge = runtime.phase_two.request_approval(run_id, principal)
    if challenge.status is ResultStatus.FAILURE or challenge.value is None:
        return _fail("approval_request", challenge)
    request = challenge.value.request
    selected_decision = ApprovalDecision(args.decision.upper())
    decided = runtime.phase_two.decide(
        LocalDecisionRequest(
            request_id=request.request_id,
            run_id=request.run_id,
            proposal_id=request.proposal_id,
            request_hash=request.request_hash,
            proposal_hash=request.proposal_hash,
            evidence_hash=request.evidence_hash,
            proposal_version=request.proposal_version,
            decision=selected_decision,
            decision_nonce=challenge.value.decision_nonce,
        ),
        principal,
    )
    if decided.status is ResultStatus.FAILURE or decided.value is None:
        return _fail("decision", decided)
    completed = runtime.phase_two.resume(run_id, principal)
    if completed.status is ResultStatus.FAILURE or completed.value is None:
        return _fail("resume", completed)
    conflicting = LocalDecisionRequest(
        request_id=request.request_id,
        run_id=request.run_id,
        proposal_id=request.proposal_id,
        request_hash=request.request_hash,
        proposal_hash=request.proposal_hash,
        evidence_hash=request.evidence_hash,
        proposal_version=request.proposal_version,
        decision=(
            ApprovalDecision.DENIED
            if selected_decision is ApprovalDecision.APPROVED
            else ApprovalDecision.APPROVED
        ),
        decision_nonce=challenge.value.decision_nonce,
    )
    mutations_before_replay = runtime.executor.mutation_calls
    replay = runtime.phase_two.decide(conflicting, principal)
    replay_rejected = (
        replay.failure is not None
        and replay.failure.code == "LOCAL_APPROVAL_REPLAY_CONFLICT"
        and runtime.executor.mutation_calls == mutations_before_replay
    )
    if not replay_rejected:
        return _fail("replay_protection", replay)
    restarted = create_local_hitl_runtime(settings, runtime_settings=runtime_settings)
    recovered = restarted.phase_two.resume(run_id, principal)
    if recovered.status is ResultStatus.FAILURE or recovered.value is None:
        return _fail("recovery", recovered)
    receipt = completed.value.receipt
    verification = completed.value.verification
    elapsed = time.monotonic() - started_at
    payload = {
        "aws_mutations": 0,
        "decision": selected_decision.value,
        "demo_label": "MOCK_OFFLINE_NEVER_LIVE",
        "duration_seconds": round(elapsed, 3),
        "evidence_hash": planned.value.evidence.evidence_hash,
        "external_network_connections": 0,
        "fail_closed_probe": "CONFLICTING_APPROVAL_REPLAY_REJECTED",
        "final_state": completed.value.final_state.value,
        "live_receipts": 0,
        "mode": "MOCK_OFFLINE",
        "model_provider": runtime.runtime_settings.model_provider.value,
        "mock_mutation_count": runtime.executor.mutation_calls,
        "network_calls": runtime.cloud_provider.network_calls,
        "ok": True,
        "operation": planned.value.plan.proposal.operation_type.value,
        "output_dir": str(output_dir),
        "proposal_hash": planned.value.plan.proposal.proposal_hash,
        "recovered_pending_approval": True,
        "recovered_pending_state": recovered_pending.state.value,
        "recovery_mock_mutation_count": restarted.executor.mutation_calls,
        "recovery_reconciled": recovered.value.reconciled,
        "receipt_hash": receipt.receipt_hash if receipt is not None else None,
        "replay_failure_code": replay.failure.code if replay.failure is not None else None,
        "replay_rejected": replay_rejected,
        "run_id": str(run_id),
        "runtime_mode": runtime.runtime_settings.mode.value,
        "target_under_seconds": 300,
        "verification_hash": (
            verification.verification_hash if verification is not None else None
        ),
        "within_target": elapsed < 300,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
