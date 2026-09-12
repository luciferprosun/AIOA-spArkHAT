from __future__ import annotations

import json
import socket
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from aioa_cloudops_agent.agent import BoundedInvestigationFlow, create_primary_agent
from aioa_cloudops_agent.cloudops import (
    MOCK_CLEAN_INSTANCE_ID,
    InvestigationIdentity,
    MockAwsAdapter,
    SandboxTarget,
)
from aioa_cloudops_agent.config import (
    BedrockSettings,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)
from aioa_cloudops_agent.nz import (
    BudgetCounters,
    ResultStatus,
    Run,
    WorkflowState,
    generate_event_id,
)
from aioa_cloudops_agent.persistence.memory import InMemoryTestDurableTruthRepository
from aioa_cloudops_agent.portable import (
    PortableDemoError,
    PortableDemoReceipt,
    render_portable_receipt,
    run_portable_demo,
    write_portable_receipt,
)
from aioa_cloudops_agent.providers import MockModelFailure, MockModelProvider
from aioa_cloudops_agent.release.deployment_contract import canonical_json
from aioa_cloudops_agent.release.post_deploy_verifier import FailureProbeId
from aioa_cloudops_agent.safety import workflow_state_for_failure

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4c")
PROPOSAL_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b4d")
NOW = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _portable() -> RuntimeSettings:
    return RuntimeSettings(
        mode=RuntimeMode.PORTABLE,
        model_provider=ModelProviderName.MOCK,
        aws_integration_enabled=False,
    )


def _clear_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def test_portable_demo_runs_strands_and_all_golden_scenarios_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_credentials(monkeypatch)

    receipt = run_portable_demo(settings=_portable(), workspace=tmp_path / "portable")
    verification = receipt.nonzero_verification

    assert receipt.status == "PASS"
    assert receipt.runtime_mode == "portable"
    assert receipt.provider == "mock"
    assert receipt.provider_selection_explicit is True
    assert receipt.secrets_required is False
    assert receipt.strands_agent.framework == "strands-agents"
    assert receipt.strands_agent.final_state == "REMEDIATION_PROPOSED"
    assert receipt.strands_agent.proposal_authorizes_execution is False
    assert receipt.strands_agent.model_calls == 4
    assert receipt.strands_agent.aws_calls == receipt.strands_agent.aws_mutations == 0
    assert verification.approved_path.final_state == "SUCCESS_WITH_EVIDENCE"
    assert verification.approved_path.mock_mutations_before_explicit_decision == 0
    assert verification.approved_path.mock_mutation_count == 1
    assert verification.deny_path.final_state == "DENIED_BY_HUMAN"
    assert verification.deny_path.mock_mutation_count == 0
    assert verification.deny_path.execution_receipt_absent is True
    assert verification.deny_path.independent_verification_absent is True
    assert receipt.aws_calls == receipt.aws_mutations == 0
    assert receipt.external_network_connections == receipt.provider_network_calls == 0


def test_portable_demo_proves_binding_replay_and_restart_recovery(tmp_path: Path) -> None:
    receipt = run_portable_demo(settings=_portable(), workspace=tmp_path / "portable")
    approved = receipt.nonzero_verification.approved_path
    binding_probe = next(
        probe
        for probe in receipt.nonzero_verification.failure_probes
        if probe.probe_id is FailureProbeId.RESOURCE_BINDING_MISMATCH
    )

    assert binding_probe.outcome == "REJECTED_FAIL_CLOSED"
    assert binding_probe.mock_mutation_delta == 0
    assert approved.pending_approval_recovered_after_restart is True
    assert approved.replay_rejected is True
    assert approved.replay_mutation_delta == 0
    assert approved.recovery_reconciled is True
    assert approved.recovery_receipt_hash_match is True
    assert approved.recovery_mock_mutation_count == 0


def test_portable_demo_is_deterministic_and_opens_no_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("portable demo attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    first = run_portable_demo(settings=_portable(), workspace=tmp_path / "first")
    second = run_portable_demo(settings=_portable(), workspace=tmp_path / "second")

    assert first == second
    assert render_portable_receipt(first) == render_portable_receipt(second)
    assert PortableDemoReceipt.model_validate_json(render_portable_receipt(first)) == first


def test_portable_receipt_is_hash_bound_private_and_symlink_safe(tmp_path: Path) -> None:
    receipt = run_portable_demo(settings=_portable(), workspace=tmp_path / "portable")
    output = tmp_path / "evidence" / "receipt.json"
    write_portable_receipt(output, receipt)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert PortableDemoReceipt.model_validate_json(output.read_text(encoding="utf-8")) == receipt
    rendered = canonical_json(receipt.model_dump(mode="json"))
    assert "decision_nonce" not in rendered
    assert "Bearer " not in rendered
    assert "AWS_SECRET_ACCESS_KEY" not in rendered

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["receipt_sha256"] = "0" * 64
    with pytest.raises(ValidationError, match="portable receipt hash is invalid"):
        PortableDemoReceipt.model_validate_json(json.dumps(tampered))

    protected = tmp_path / "protected"
    protected.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(protected)
    with pytest.raises(PortableDemoError, match="PORTABLE_OUTPUT_SYMLINK_FORBIDDEN"):
        write_portable_receipt(link, receipt)
    assert protected.read_text(encoding="utf-8") == "preserve"

    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text("preserve", encoding="utf-8")
    unsafe.chmod(0o644)
    with pytest.raises(PortableDemoError, match="PORTABLE_OUTPUT_EXISTING_FILE_UNSAFE"):
        write_portable_receipt(unsafe, receipt)
    assert unsafe.read_text(encoding="utf-8") == "preserve"

    private_unrelated = tmp_path / "private-unrelated.json"
    private_unrelated.write_text('{"not":"a receipt"}', encoding="utf-8")
    private_unrelated.chmod(0o600)
    with pytest.raises(PortableDemoError, match="PORTABLE_OUTPUT_EXISTING_FILE_UNSAFE"):
        write_portable_receipt(private_unrelated, receipt)
    assert private_unrelated.read_text(encoding="utf-8") == '{"not":"a receipt"}'

    directory = tmp_path / "receipt-directory"
    directory.mkdir()
    directory_link = tmp_path / "receipt-directory-link"
    directory_link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(PortableDemoError, match="PORTABLE_OUTPUT_SYMLINK_FORBIDDEN"):
        write_portable_receipt(directory_link / "receipt.json", receipt)


def test_non_portable_runtime_is_rejected_before_any_sandbox_state(tmp_path: Path) -> None:
    workspace = tmp_path / "forbidden"
    settings = RuntimeSettings(
        mode=RuntimeMode.AWS,
        model_provider=ModelProviderName.BEDROCK,
        aws_integration_enabled=True,
        bedrock=BedrockSettings(),
    )

    with pytest.raises(
        PortableDemoError,
        match="PORTABLE_DEMO_REQUIRES_PORTABLE_MOCK_RUNTIME",
    ):
        run_portable_demo(settings=settings, workspace=workspace)
    assert not workspace.exists()


@pytest.mark.parametrize(
    "failure",
    (MockModelFailure.MALFORMED, MockModelFailure.PROVIDER_ERROR),
)
def test_untrusted_or_failed_model_cannot_mutate_through_strands(
    failure: MockModelFailure,
) -> None:
    run = Run.new(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
        idempotency_key=f"portable/failure/{failure.value.casefold()}",
        created_at=NOW,
        budget=BudgetCounters(max_turns=8, max_tokens=8_192),
    )
    adapter = MockAwsAdapter()
    model = MockModelProvider(failure=failure)
    repository = InMemoryTestDurableTruthRepository()
    runtime = create_primary_agent(
        context=ExecutionContext(
            correlation_id=CORRELATION_ID,
            idempotency_key=f"portable/failure/{failure.value.casefold()}",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=ExecutionBudget(max_turns=8, max_tokens=8_192),
        ),
        identity=InvestigationIdentity.from_run(run),
        target=SandboxTarget(instance_id=MOCK_CLEAN_INSTANCE_ID),
        ec2_client=adapter,
        cloudwatch_client=adapter,
        proposal_id=PROPOSAL_ID,
        clock=lambda: NOW,
        runtime_settings=_portable(),
        model=model,
        durable_repository=repository,
    )

    result = BoundedInvestigationFlow(
        runtime,
        repository,
        clock=lambda: NOW,
        event_id_factory=generate_event_id,
    ).execute(run)

    assert result.status is ResultStatus.FAILURE
    assert result.value is None
    assert result.failure is not None
    durable_run = repository.get_run(run.run_id)
    assert durable_run is not None
    assert durable_run.state is workflow_state_for_failure(result.failure)
    assert durable_run.state is not WorkflowState.SUCCESS_WITH_EVIDENCE
    assert adapter.network_calls == adapter.mutation_calls == 0
    assert model.network_calls == 0
