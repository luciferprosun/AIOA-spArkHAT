import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from uuid import UUID

import pytest

from aioa_cloudops_agent.agent import (
    LocalDecisionRequest,
    LocalFirstPhaseOneFlow,
    LocalHitlExecutionFlow,
    LocalOperatorPrincipal,
)
from aioa_cloudops_agent.cloudops import (
    MOCK_UNATTACHED_EIP_ID,
    MOCK_UNSAFE_SECURITY_GROUP_ID,
    CloudAdapterUnavailableError,
    CloudResourceNotFoundError,
    LocalMockPolicyError,
    LocalMockRemediationExecutor,
    LocalMockStateStore,
    PersistentMockAwsAdapter,
    PlanRemediation,
    QueryResource,
)
from aioa_cloudops_agent.nz import (
    ApprovalDecision,
    BudgetCounters,
    Checkpoint,
    CloudResourceType,
    FailureKind,
    LocalApprovalRequestRecord,
    LocalExecutionIntent,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    RemediationOperation,
    ResourceQuery,
    ResultStatus,
    Run,
    SecurityGroupResource,
    WorkflowState,
    generate_event_id,
)
from aioa_cloudops_agent.nz.errors import StorageDependencyError
from aioa_cloudops_agent.persistence import (
    LocalFileDurableTruthRepository,
    compute_evidence_digest,
)
from aioa_cloudops_agent.providers import MockModelProvider

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b80")
REQUEST_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b81")
NOW = datetime(2026, 8, 26, 14, 0, tzinfo=UTC)
NONCE = "local2-decision-nonce-000000000001"
PRINCIPAL = LocalOperatorPrincipal(actor_session_id="operator-session-1")
OTHER_RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b82")
OTHER_PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b83")
OTHER_REQUEST_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b84")


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def _run(run_id: UUID = RUN_ID) -> Run:
    return Run.new(
        run_id=run_id,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key=f"local/hitl/{run_id}",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=2_048),
    )


def _runtime(
    tmp_path: Path,
    *,
    clock: Clock | None = None,
) -> tuple[
    LocalFirstPhaseOneFlow,
    LocalHitlExecutionFlow,
    LocalFileDurableTruthRepository,
    LocalMockStateStore,
    LocalMockRemediationExecutor,
]:
    selected_clock = clock or Clock()
    repository = LocalFileDurableTruthRepository(tmp_path / "truth.json")
    cloud_state = LocalMockStateStore(tmp_path / "inventory.json")
    adapter = PersistentMockAwsAdapter(cloud_state)
    executor = LocalMockRemediationExecutor(cloud_state, clock=selected_clock)
    phase_one = LocalFirstPhaseOneFlow(
        query_resource=QueryResource(adapter),
        plan_remediation=PlanRemediation(),
        model_provider=MockModelProvider(),
        repository=repository,
        clock=selected_clock,
        proposal_id_factory=lambda: PROPOSAL_ID,
        event_id_factory=generate_event_id,
    )
    phase_two = LocalHitlExecutionFlow(
        repository,
        executor,
        clock=selected_clock,
        request_id_factory=lambda: REQUEST_ID,
        event_id_factory=generate_event_id,
        nonce_factory=lambda: NONCE,
    )
    return phase_one, phase_two, repository, cloud_state, executor


def _prepare(
    tmp_path: Path,
    resource_type: CloudResourceType = CloudResourceType.ELASTIC_IP,
    resource_id: str = MOCK_UNATTACHED_EIP_ID,
    *,
    clock: Clock | None = None,
):
    phase_one, phase_two, repository, cloud_state, executor = _runtime(
        tmp_path,
        clock=clock,
    )
    result = phase_one.execute(
        _run(),
        ResourceQuery(resource_type=resource_type, resource_id=resource_id),
    )
    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.value.final_state is WorkflowState.AWAITING_APPROVAL
    return phase_two, repository, cloud_state, executor


def _decision(challenge: object, decision: ApprovalDecision) -> LocalDecisionRequest:
    from aioa_cloudops_agent.agent import LocalApprovalChallenge

    assert isinstance(challenge, LocalApprovalChallenge)
    request = challenge.request
    return LocalDecisionRequest(
        request_id=request.request_id,
        run_id=request.run_id,
        proposal_id=request.proposal_id,
        request_hash=request.request_hash,
        proposal_hash=request.proposal_hash,
        evidence_hash=request.evidence_hash,
        proposal_version=request.proposal_version,
        decision=decision,
        decision_nonce=challenge.decision_nonce,
    )


def test_approved_eip_executes_once_verifies_and_reconciles_after_restart(
    tmp_path: Path,
) -> None:
    flow, repository, cloud_state, executor = _prepare(tmp_path)
    challenge_result = flow.request_approval(RUN_ID, PRINCIPAL)
    assert challenge_result.value is not None

    resolution = flow.decide(
        _decision(challenge_result.value, ApprovalDecision.APPROVED),
        PRINCIPAL,
    )
    completion = flow.resume(RUN_ID, PRINCIPAL)

    assert resolution.value is not None
    assert resolution.value.final_state is WorkflowState.APPROVED
    assert completion.value is not None
    assert completion.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert completion.value.receipt is not None
    assert completion.value.verification is not None
    assert completion.value.verification.observed_absent is True
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert executor.mutation_calls == 1
    with pytest.raises(CloudResourceNotFoundError):
        cloud_state.get_resource(
            ResourceQuery(
                resource_type=CloudResourceType.ELASTIC_IP,
                resource_id=MOCK_UNATTACHED_EIP_ID,
            )
        )

    restarted = _runtime(tmp_path)[1]
    reconciled = restarted.resume(RUN_ID, PRINCIPAL)
    assert reconciled.value is not None
    assert reconciled.value.reconciled is True
    assert reconciled.value.receipt == completion.value.receipt
    assert executor.mutation_calls == 1


def test_denial_is_terminal_and_never_calls_executor(tmp_path: Path) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None

    resolution = flow.decide(_decision(challenge, ApprovalDecision.DENIED), PRINCIPAL)
    completion = flow.resume(RUN_ID, PRINCIPAL)

    assert resolution.value is not None
    assert resolution.value.final_state is WorkflowState.DENIED_BY_HUMAN
    assert completion.value is not None
    assert completion.value.final_state is WorkflowState.DENIED_BY_HUMAN
    assert completion.value.receipt is None
    assert repository.get_run(RUN_ID).state is WorkflowState.DENIED_BY_HUMAN
    assert executor.execute_calls == executor.mutation_calls == 0


def test_wrong_nonce_and_wrong_actor_fail_without_consuming_challenge(
    tmp_path: Path,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    valid = _decision(challenge, ApprovalDecision.APPROVED)

    wrong_nonce = valid.model_copy(update={"decision_nonce": "wrong-nonce-0000000000000000"})
    denied_nonce = flow.decide(wrong_nonce, PRINCIPAL)
    denied_actor = flow.decide(
        valid,
        LocalOperatorPrincipal(actor_session_id="other-operator-session"),
    )

    assert denied_nonce.failure is not None
    assert denied_nonce.failure.code == "LOCAL_APPROVAL_BINDING_MISMATCH"
    assert denied_actor.failure is not None
    assert denied_actor.failure.kind is FailureKind.POLICY_DENIAL
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert repository.get_checkpoint(RUN_ID).local_approval is None
    assert executor.mutation_calls == 0


def test_identical_decision_reconciles_but_conflicting_replay_is_rejected(
    tmp_path: Path,
) -> None:
    flow, repository, _, _ = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    approved = _decision(challenge, ApprovalDecision.APPROVED)

    first = flow.decide(approved, PRINCIPAL)
    replay = flow.decide(approved, PRINCIPAL)
    conflict = flow.decide(
        approved.model_copy(update={"decision": ApprovalDecision.DENIED}),
        PRINCIPAL,
    )

    assert first.value is not None and first.value.reconciled is False
    assert replay.value is not None and replay.value.reconciled is True
    assert conflict.failure is not None
    assert conflict.failure.code == "LOCAL_APPROVAL_REPLAY_CONFLICT"
    assert repository.get_run(RUN_ID).state is WorkflowState.APPROVED


def test_identical_recorded_decision_reconciles_after_challenge_expiry(
    tmp_path: Path,
) -> None:
    clock = Clock()
    flow, repository, _, _ = _prepare(tmp_path, clock=clock)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    approved = _decision(challenge, ApprovalDecision.APPROVED)
    first = flow.decide(approved, PRINCIPAL)
    assert first.value is not None

    clock.now = challenge.request.expires_at + timedelta(seconds=1)
    replay = flow.decide(approved, PRINCIPAL)

    assert replay.value is not None
    assert replay.value.reconciled is True
    assert repository.get_run(RUN_ID).state is WorkflowState.APPROVED


def test_identical_decision_reconciles_after_verified_execution(
    tmp_path: Path,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    approved = _decision(challenge, ApprovalDecision.APPROVED)
    assert flow.decide(approved, PRINCIPAL).value is not None
    assert flow.resume(RUN_ID, PRINCIPAL).value is not None

    replay = flow.decide(approved, PRINCIPAL)

    assert replay.value is not None
    assert replay.value.final_state is WorkflowState.APPROVED
    assert replay.value.reconciled is True
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert repository.get_checkpoint(RUN_ID).last_safe_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert executor.mutation_calls == 1


def test_restart_reconciles_success_transition_before_final_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(
        _decision(challenge, ApprovalDecision.APPROVED),
        PRINCIPAL,
    ).value is not None
    original_save = repository.save_checkpoint

    def fail_final_checkpoint(checkpoint: Checkpoint, *, expected_version: int | None):
        if checkpoint.last_safe_state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            raise StorageDependencyError("injected final checkpoint outage")
        return original_save(checkpoint, expected_version=expected_version)

    monkeypatch.setattr(repository, "save_checkpoint", fail_final_checkpoint)
    interrupted = flow.resume(RUN_ID, PRINCIPAL)
    assert interrupted.failure is not None
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert repository.get_checkpoint(RUN_ID).last_safe_state is WorkflowState.APPROVED

    monkeypatch.setattr(repository, "save_checkpoint", original_save)
    recovered = flow.resume(RUN_ID, PRINCIPAL)

    assert recovered.value is not None
    assert recovered.value.reconciled is True
    assert repository.get_checkpoint(RUN_ID).last_safe_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert executor.mutation_calls == 1


def test_unavailable_inventory_closes_as_typed_dependency_failure(
    tmp_path: Path,
) -> None:
    flow, repository, cloud_state, _ = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(
        _decision(challenge, ApprovalDecision.APPROVED),
        PRINCIPAL,
    ).value is not None
    cloud_state.path.write_text("{corrupt", encoding="utf-8")

    result = flow.resume(RUN_ID, PRINCIPAL)

    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert result.failure.code == "LOCAL_MOCK_STATE_UNAVAILABLE"
    assert repository.get_run(RUN_ID).state is WorkflowState.DEPENDENCY_UNAVAILABLE


def test_unavailable_verification_readback_closes_without_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(
        _decision(challenge, ApprovalDecision.APPROVED),
        PRINCIPAL,
    ).value is not None

    def unavailable(_receipt: object) -> object:
        raise CloudAdapterUnavailableError("injected read-back outage")

    monkeypatch.setattr(executor, "verify", unavailable)
    result = flow.resume(RUN_ID, PRINCIPAL)

    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert result.failure.code == "LOCAL_MOCK_STATE_UNAVAILABLE"
    assert executor.mutation_calls == 1
    assert repository.get_run(RUN_ID).state is WorkflowState.DEPENDENCY_UNAVAILABLE


def test_expired_challenge_fails_closed_without_mutation(tmp_path: Path) -> None:
    clock = Clock()
    flow, repository, _, executor = _prepare(tmp_path, clock=clock)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    clock.now += timedelta(minutes=11)

    result = flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL)

    assert result.failure is not None
    assert result.failure.code == "LOCAL_APPROVAL_EXPIRED"
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert executor.mutation_calls == 0


def test_security_group_execution_removes_only_approved_ingress_and_verifies(
    tmp_path: Path,
) -> None:
    flow, _, cloud_state, executor = _prepare(
        tmp_path,
        CloudResourceType.SECURITY_GROUP,
        MOCK_UNSAFE_SECURITY_GROUP_ID,
    )
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value

    completion = flow.resume(RUN_ID, PRINCIPAL)

    assert completion.value is not None
    assert completion.value.verification is not None
    observed = cloud_state.get_resource(
        ResourceQuery(
            resource_type=CloudResourceType.SECURITY_GROUP,
            resource_id=MOCK_UNSAFE_SECURITY_GROUP_ID,
        )
    )
    assert observed == completion.value.receipt.after_resource
    assert len(observed.inbound_rules) == 0
    assert executor.mutation_calls == 1


def test_resume_without_decision_is_denied_and_never_executes(tmp_path: Path) -> None:
    flow, repository, _, executor = _prepare(tmp_path)

    result = flow.resume(RUN_ID, PRINCIPAL)

    assert result.failure is not None
    assert result.failure.code == "LOCAL_APPROVAL_REQUIRED"
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL
    assert executor.execute_calls == 0


def test_checkpoint_rejects_rehashed_request_with_substituted_operation(
    tmp_path: Path,
) -> None:
    flow, repository, _, _ = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    request_values = {
        name: getattr(challenge.request, name)
        for name in LocalApprovalRequestRecord.model_fields
        if name != "request_hash"
    }
    request_values.update(
        {
            "operation_type": RemediationOperation.REVOKE_PUBLIC_INGRESS,
            "target_resource_type": CloudResourceType.SECURITY_GROUP,
            "target_resource_id": MOCK_UNSAFE_SECURITY_GROUP_ID,
        }
    )
    provisional = LocalApprovalRequestRecord.model_construct(
        **request_values,
        request_hash="0" * 64,
    )
    tampered = LocalApprovalRequestRecord(
        **request_values,
        request_hash=compute_evidence_digest(provisional.binding_payload()),
    )

    with pytest.raises(ValueError, match="request is not proposal-bound"):
        Checkpoint.model_validate(
            {
                **checkpoint.model_dump(),
                "local_approval_request": tampered,
            }
        )


def test_receipt_and_verification_reconstruction_reject_semantic_substitution(
    tmp_path: Path,
) -> None:
    flow, repository, _, _ = _prepare(
        tmp_path,
        CloudResourceType.SECURITY_GROUP,
        MOCK_UNSAFE_SECURITY_GROUP_ID,
    )
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value
    completion = flow.resume(RUN_ID, PRINCIPAL).value
    assert completion is not None
    receipt = completion.receipt
    verification = completion.verification
    assert receipt is not None
    assert isinstance(receipt.after_resource, SecurityGroupResource)
    assert verification is not None
    assert isinstance(verification.observed_resource, SecurityGroupResource)

    receipt_values = {
        name: getattr(receipt, name)
        for name in LocalExecutionReceipt.model_fields
        if name != "receipt_hash"
    }
    substituted_after = receipt.after_resource.model_copy(
        update={"tags": {"Environment": "substituted"}}
    )
    receipt_values["after_resource"] = substituted_after
    provisional_receipt = LocalExecutionReceipt.model_construct(
        **receipt_values,
        receipt_hash="0" * 64,
    )
    with pytest.raises(ValueError, match="bounded rule removal"):
        LocalExecutionReceipt(
            **receipt_values,
            receipt_hash=compute_evidence_digest(
                provisional_receipt.receipt_payload()
            ),
        )

    other_id = "sg-0fedcba9876543210"
    verification_values = {
        name: getattr(verification, name)
        for name in LocalVerificationEvidence.model_fields
        if name != "verification_hash"
    }
    verification_values.update(
        {
            "target_resource_id": other_id,
            "observed_resource": verification.observed_resource.model_copy(
                update={"resource_id": other_id}
            ),
        }
    )
    provisional_verification = LocalVerificationEvidence.model_construct(
        **verification_values,
        verification_hash="0" * 64,
    )
    substituted_verification = LocalVerificationEvidence(
        **verification_values,
        verification_hash=compute_evidence_digest(
            provisional_verification.verification_payload()
        ),
    )
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    with pytest.raises(ValueError, match="verification is not receipt-bound"):
        Checkpoint.model_validate(
            {
                **checkpoint.model_dump(),
                "local_verification": substituted_verification,
            }
        )


@pytest.mark.parametrize(
    "update",
    [
        {"request_id": OTHER_REQUEST_ID},
        {"run_id": OTHER_RUN_ID},
        {"proposal_id": OTHER_PROPOSAL_ID},
        {"request_hash": "0" * 64},
        {"proposal_hash": "0" * 64},
        {"evidence_hash": "0" * 64},
        {"proposal_version": 3},
        {"decision_nonce": "different-decision-nonce-000000001"},
    ],
)
def test_every_decision_binding_tamper_fails_closed(
    tmp_path: Path,
    update: dict[str, object],
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    tampered = _decision(challenge, ApprovalDecision.APPROVED).model_copy(update=update)

    result = flow.decide(tampered, PRINCIPAL)

    assert result.failure is not None
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None and checkpoint.local_approval is None
    assert executor.mutation_calls == 0


def test_canonical_binding_is_order_independent_but_content_sensitive(
    tmp_path: Path,
) -> None:
    flow, _, _, _ = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    request_payload = challenge.request.binding_payload()
    proposal_payload = challenge.proposal.action_payload()

    assert compute_evidence_digest(dict(reversed(tuple(request_payload.items())))) == (
        challenge.request.request_hash
    )
    assert compute_evidence_digest(dict(reversed(tuple(proposal_payload.items())))) == (
        challenge.proposal.proposal_hash
    )
    changed = dict(proposal_payload)
    changed["target_resource_id"] = "eipalloc-0fedcba9876543210"
    assert compute_evidence_digest(changed) != challenge.proposal.proposal_hash


def _forged_intent(
    intent: LocalExecutionIntent,
    update: dict[str, object],
) -> LocalExecutionIntent:
    values = {
        name: getattr(intent, name)
        for name in LocalExecutionIntent.model_fields
        if name != "intent_hash"
    }
    values.update(update)
    provisional = LocalExecutionIntent.model_construct(
        **values,
        intent_hash="0" * 64,
    )
    return LocalExecutionIntent(
        **values,
        intent_hash=compute_evidence_digest(provisional.binding_payload()),
    )


@pytest.mark.parametrize(
    "update",
    [
        {"run_id": OTHER_RUN_ID},
        {"target_resource_id": "eipalloc-0fedcba9876543210"},
        {"idempotency_key": "local-exec:" + "0" * 64},
        {
            "operation_type": RemediationOperation.REVOKE_PUBLIC_INGRESS,
            "target_resource_type": CloudResourceType.SECURITY_GROUP,
            "target_resource_id": MOCK_UNSAFE_SECURITY_GROUP_ID,
        },
        {"decision_hash": "0" * 64},
    ],
)
def test_executor_rejects_rehashed_intent_tampering(
    tmp_path: Path,
    update: dict[str, object],
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None
    proposal = checkpoint.remediation_proposal
    evidence = checkpoint.resource_evidence
    approval = checkpoint.local_approval
    assert proposal is not None and evidence is not None and approval is not None
    intent = LocalExecutionIntent.create(proposal, approval, registered_at=NOW)

    with pytest.raises(LocalMockPolicyError, match="exactly approval-bound"):
        executor.execute(
            proposal=proposal,
            evidence=evidence,
            approval=approval,
            intent=_forged_intent(intent, update),
        )
    assert executor.mutation_calls == 0


def test_concurrent_identical_resume_requests_mutate_at_most_once(
    tmp_path: Path,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value
    concurrent_requests = 16
    barrier = Barrier(concurrent_requests + 1)

    def resume() -> object:
        barrier.wait()
        return flow.resume(RUN_ID, PRINCIPAL)

    with ThreadPoolExecutor(max_workers=concurrent_requests) as pool:
        futures = tuple(pool.submit(resume) for _ in range(concurrent_requests))
        barrier.wait()
        results = tuple(future.result(timeout=20) for future in futures)

    assert executor.mutation_calls == 1
    assert any(getattr(result, "value", None) is not None for result in results)
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    reconciled = _runtime(tmp_path)[1].resume(RUN_ID, PRINCIPAL)
    assert reconciled.value is not None and reconciled.value.reconciled is True


def test_restart_recovers_after_mutation_before_receipt_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, repository, cloud_state, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value
    original_save = repository.save_checkpoint
    failed = False

    def fail_receipt_once(checkpoint: Checkpoint, *, expected_version: int | None):
        nonlocal failed
        if checkpoint.local_execution_receipt is not None and not failed:
            failed = True
            raise StorageDependencyError("injected post-mutation receipt outage")
        return original_save(checkpoint, expected_version=expected_version)

    monkeypatch.setattr(repository, "save_checkpoint", fail_receipt_once)
    interrupted = flow.resume(RUN_ID, PRINCIPAL)

    assert interrupted.failure is not None
    assert interrupted.failure.code == "LOCAL_RECEIPT_DURABILITY_FAILED"
    assert repository.get_run(RUN_ID).state is WorkflowState.EXECUTING
    checkpoint = repository.get_checkpoint(RUN_ID)
    assert checkpoint is not None and checkpoint.local_execution_intent is not None
    assert cloud_state.get_receipt(checkpoint.local_execution_intent.idempotency_key) is not None
    assert executor.mutation_calls == 1

    _, recovered_flow, _, _, recovered_executor = _runtime(tmp_path)
    recovered = recovered_flow.resume(RUN_ID, PRINCIPAL)

    assert recovered.value is not None
    assert recovered.value.final_state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
    assert recovered_executor.mutation_calls == 0


def test_retry_recovers_approval_persisted_before_state_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flow, repository, _, executor = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    decision = _decision(challenge, ApprovalDecision.APPROVED)
    original_transition = repository.transition_run
    failed = False

    def fail_approved_once(*args: object, **kwargs: object):
        nonlocal failed
        if kwargs.get("expected_state") is WorkflowState.AWAITING_APPROVAL and not failed:
            failed = True
            raise StorageDependencyError("injected decision transition outage")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(repository, "transition_run", fail_approved_once)
    interrupted = flow.decide(decision, PRINCIPAL)
    assert interrupted.failure is not None
    assert repository.get_checkpoint(RUN_ID).local_approval is not None
    assert repository.get_run(RUN_ID).state is WorkflowState.AWAITING_APPROVAL

    monkeypatch.setattr(repository, "transition_run", original_transition)
    recovered = flow.decide(decision, PRINCIPAL)

    assert recovered.value is not None and recovered.value.reconciled is True
    assert repository.get_run(RUN_ID).state is WorkflowState.APPROVED
    assert executor.mutation_calls == 0


@pytest.mark.parametrize(
    "tamper",
    ["edit_resource", "edit_receipt", "delete_receipt", "reorder_resources", "inject_field"],
)
def test_sandbox_inventory_tampering_is_detected(
    tmp_path: Path,
    tamper: str,
) -> None:
    flow, repository, cloud_state, _ = _prepare(tmp_path)
    challenge = flow.request_approval(RUN_ID, PRINCIPAL).value
    assert challenge is not None
    assert flow.decide(_decision(challenge, ApprovalDecision.APPROVED), PRINCIPAL).value
    completion = flow.resume(RUN_ID, PRINCIPAL).value
    assert completion is not None and completion.receipt is not None
    raw = json.loads(cloud_state.path.read_text(encoding="utf-8"))
    payload = raw["payload"]
    if tamper == "edit_resource":
        payload["resources"][0]["region"] = "us-east-1"
    elif tamper == "edit_receipt":
        payload["receipts"][0]["decision_hash"] = "0" * 64
    elif tamper == "delete_receipt":
        payload["receipts"].clear()
    elif tamper == "reorder_resources":
        payload["resources"].reverse()
    else:
        payload["unexpected"] = True
    cloud_state.path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(CloudAdapterUnavailableError, match="corrupt or unreadable"):
        cloud_state.get_receipt(completion.receipt.idempotency_key)
    assert repository.get_run(RUN_ID).state is WorkflowState.SUCCESS_WITH_EVIDENCE
