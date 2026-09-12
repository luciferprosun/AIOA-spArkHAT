from __future__ import annotations

import hashlib
import json
import socket
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.phase3 import build_verifier_contract as builder
from scripts.phase3.run_post_deploy_verifier import (
    DEFAULT_CONTRACT,
    DEFAULT_RECEIPT,
    _atomic_write,
)

from aioa_cloudops_agent.release.deployment_contract import canonical_json, load_deployment_contract
from aioa_cloudops_agent.release.post_deploy_verifier import (
    FailureProbeId,
    PostDeployVerificationReceipt,
    PostDeployVerifierError,
    VerificationStepId,
    VerifierFixture,
    VerifierMode,
    _ensure_public_safe,
    load_verifier_fixture,
    render_verifier_fixture_schema,
    render_verifier_markdown,
    render_verifier_receipt_schema,
    run_post_deploy_verifier,
    validate_verification_receipt,
)


def _fixture() -> VerifierFixture:
    return load_verifier_fixture(builder.DEFAULT_FIXTURE)


def _run(workspace: Path):
    return run_post_deploy_verifier(
        mode=VerifierMode.OFFLINE_LOCAL_FIXTURE,
        fixture=_fixture(),
        deployment_contract=load_deployment_contract(DEFAULT_CONTRACT),
        workspace=workspace,
    )


def test_complete_offline_chain_proves_approve_deny_replay_recovery_and_fail_closed(
    tmp_path: Path,
) -> None:
    receipt = _run(tmp_path / "verification")

    assert receipt.status == "PASS_OFFLINE"
    assert tuple(step.step_id for step in receipt.steps) == tuple(VerificationStepId)
    assert tuple(probe.probe_id for probe in receipt.failure_probes) == tuple(FailureProbeId)
    assert receipt.approved_path.final_state == "SUCCESS_WITH_EVIDENCE"
    assert receipt.approved_path.mock_mutation_count == 1
    assert receipt.approved_path.mock_mutations_before_explicit_decision == 0
    assert receipt.approved_path.pending_approval_recovered_after_restart is True
    assert receipt.approved_path.replay_rejected is True
    assert receipt.approved_path.replay_mutation_delta == 0
    assert receipt.approved_path.recovery_reconciled is True
    assert receipt.approved_path.recovery_mock_mutation_count == 0
    assert receipt.deny_path.final_state == "DENIED_BY_HUMAN"
    assert receipt.deny_path.mock_mutation_count == 0
    assert receipt.deny_path.execution_receipt_absent is True
    assert receipt.deny_path.independent_verification_absent is True
    assert all(probe.outcome == "REJECTED_FAIL_CLOSED" for probe in receipt.failure_probes)
    assert receipt.external_network_connections == receipt.provider_network_calls == 0
    assert receipt.aws_mutations == receipt.live_receipts == 0
    assert receipt.mock_mutations == 1
    assert validate_verification_receipt(receipt.model_dump(mode="json")) == receipt


def test_offline_receipt_is_byte_deterministic_across_fresh_workspaces(tmp_path: Path) -> None:
    first = _run(tmp_path / "first")
    second = _run(tmp_path / "second")

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8")) == first.model_dump(mode="json")


def test_receipt_contains_hashes_and_identifiers_but_no_authorization_material(
    tmp_path: Path,
) -> None:
    receipt = _run(tmp_path / "redaction")
    rendered = canonical_json(receipt.model_dump(mode="json"))

    assert receipt.approved_path.trace_id in rendered
    assert receipt.approved_path.correlation_id in rendered
    assert receipt.approved_path.execution_receipt_sha256 in rendered
    assert "decision_nonce" not in rendered
    assert "Bearer " not in rendered
    assert "offline-verifier-token" not in rendered
    assert "eipalloc-" not in rendered
    assert "sg-" not in rendered
    assert "123456789012" not in rendered


@pytest.mark.parametrize(
    ("field", "reason"),
    (
        ("authorized_identity", "VERIFIER_IDENTITY_NOT_AUTHORIZED"),
        ("expected_account_match", "VERIFIER_ACCOUNT_REGION_MISMATCH"),
        ("expected_region_match", "VERIFIER_ACCOUNT_REGION_MISMATCH"),
        ("api_contract_match", "VERIFIER_API_CONTRACT_MISMATCH"),
        ("model_access_contract_match", "VERIFIER_MODEL_ACCESS_INVALID"),
        ("resource_binding_contract_match", "VERIFIER_RESOURCE_BINDING_INVALID"),
        (
            "verification_evidence_contract_match",
            "VERIFIER_EVIDENCE_CONTRACT_INVALID",
        ),
    ),
)
def test_invalid_future_preconditions_block_before_any_local_execution(
    tmp_path: Path,
    field: str,
    reason: str,
) -> None:
    value = _fixture().model_dump(mode="json")
    value[field] = False
    fixture = VerifierFixture.model_validate_json(json.dumps(value))
    workspace = tmp_path / field

    with pytest.raises(PostDeployVerifierError, match=reason):
        run_post_deploy_verifier(
            mode=VerifierMode.OFFLINE_LOCAL_FIXTURE,
            fixture=fixture,
            deployment_contract=load_deployment_contract(DEFAULT_CONTRACT),
            workspace=workspace,
        )
    assert not workspace.exists()


def test_live_mode_is_disabled_before_adapter_use(tmp_path: Path) -> None:
    class ForbiddenAdapter:
        calls = 0

        def verify_read_only_prerequisites(self, _binding_sha256: str) -> object:
            self.calls += 1
            raise AssertionError("live adapter must not run")

    adapter = ForbiddenAdapter()
    contract = load_deployment_contract(DEFAULT_CONTRACT)
    with pytest.raises(PostDeployVerifierError, match="LIVE_POST_DEPLOY_VERIFIER_DISABLED"):
        run_post_deploy_verifier(
            mode=VerifierMode.LIVE_AWS,
            fixture=None,
            deployment_contract=contract,
            workspace=tmp_path / "disabled",
            live_adapter=adapter,
        )
    with pytest.raises(
        PostDeployVerifierError,
        match="LIVE_POST_DEPLOY_IMPLEMENTATION_NOT_SHIPPED",
    ):
        run_post_deploy_verifier(
            mode=VerifierMode.LIVE_AWS,
            fixture=None,
            deployment_contract=contract,
            workspace=tmp_path / "unavailable",
            live_adapter=adapter,
            enable_live=True,
        )
    assert adapter.calls == 0


def test_live_options_are_forbidden_in_offline_mode(tmp_path: Path) -> None:
    with pytest.raises(
        PostDeployVerifierError,
        match="LIVE_POST_DEPLOY_OPTIONS_FORBIDDEN_OFFLINE",
    ):
        run_post_deploy_verifier(
            mode=VerifierMode.OFFLINE_LOCAL_FIXTURE,
            fixture=_fixture(),
            deployment_contract=load_deployment_contract(DEFAULT_CONTRACT),
            workspace=tmp_path,
            enable_live=True,
        )


def test_fixture_loader_rejects_duplicate_extra_nonfinite_and_secret_material(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_FIXTURE_INVALID"):
        load_verifier_fixture(duplicate)

    value = _fixture().model_dump(mode="json")
    value["extra"] = True
    extra = tmp_path / "extra.json"
    extra.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_FIXTURE_INVALID"):
        load_verifier_fixture(extra)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"schema_version":NaN}', encoding="utf-8")
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_FIXTURE_INVALID"):
        load_verifier_fixture(nonfinite)

    for sensitive in (
        "AKIA" + "ABCDEFGHIJKLMNOP",
        "Bearer secret-token-value",
        "123456789012",
        "arn:aws:iam::123456789012:role/private",
        "i-0123456789abcdef0",
    ):
        with pytest.raises(
            PostDeployVerifierError,
            match="VERIFIER_RECEIPT_SECRET_MATERIAL_FORBIDDEN",
        ):
            _ensure_public_safe({"value": sensitive})


def test_receipt_validation_rejects_hash_order_count_and_secret_tampering(
    tmp_path: Path,
) -> None:
    receipt = _run(tmp_path / "tamper")

    value = receipt.model_dump(mode="json")
    value["aws_mutations"] = 1
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_RECEIPT_INVALID"):
        validate_verification_receipt(value)

    value = receipt.model_dump(mode="json")
    value["steps"] = list(reversed(value["steps"]))
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_RECEIPT_INVALID"):
        validate_verification_receipt(value)

    value = receipt.model_dump(mode="json")
    value["failure_probes"] = value["failure_probes"][:-1]
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_RECEIPT_INVALID"):
        validate_verification_receipt(value)

    value = receipt.model_dump(mode="json")
    value["steps"][0]["evidence_reference"] = "local:AKIA" + "ABCDEFGHIJKLMNOP"
    material = {name: item for name, item in value.items() if name != "receipt_sha256"}
    value["receipt_sha256"] = hashlib.sha256(
        canonical_json(material).encode("utf-8")
    ).hexdigest()
    with pytest.raises(
        PostDeployVerifierError,
        match="VERIFIER_RECEIPT_SECRET_MATERIAL_FORBIDDEN",
    ):
        validate_verification_receipt(value)


def test_receipt_and_fixture_schemas_are_strict() -> None:
    value = json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8"))
    value["production_deployed"] = True
    with pytest.raises(ValidationError):
        PostDeployVerificationReceipt.model_validate_json(json.dumps(value))

    fixture = _fixture().model_dump(mode="json")
    fixture["live_receipt"] = True
    with pytest.raises(ValidationError):
        VerifierFixture.model_validate_json(json.dumps(fixture))


def test_existing_nonempty_workspace_fails_without_overwrite(tmp_path: Path) -> None:
    workspace = tmp_path / "existing"
    workspace.mkdir()
    marker = workspace / "preserve.txt"
    marker.write_text("preserve", encoding="utf-8")

    with pytest.raises(PostDeployVerifierError, match="VERIFIER_WORKSPACE_NOT_EMPTY"):
        _run(workspace)
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_generated_schemas_fixture_and_document_are_exact() -> None:
    assert render_verifier_receipt_schema() == builder.DEFAULT_RECEIPT_SCHEMA.read_text(
        encoding="utf-8"
    )
    assert render_verifier_fixture_schema() == builder.DEFAULT_FIXTURE_SCHEMA.read_text(
        encoding="utf-8"
    )
    assert render_verifier_markdown() == builder.DEFAULT_DOCUMENT.read_text(encoding="utf-8")
    assert builder.build(check=True)["status"] == "PASS"


def test_private_receipt_writer_is_owner_only_and_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "receipt.json"
    _atomic_write(output, "{}\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_OUTPUT_SYMLINK_FORBIDDEN"):
        _atomic_write(link, "changed")
    assert target.read_text(encoding="utf-8") == "preserve"

    unrelated = tmp_path / "unrelated.json"
    unrelated.write_text("{}\n", encoding="utf-8")
    unrelated.chmod(0o600)
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_OUTPUT_EXISTING_FILE_UNSAFE"):
        _atomic_write(unrelated, "{}\n")

    directory = tmp_path / "receipt-directory"
    directory.mkdir()
    directory_link = tmp_path / "receipt-directory-link"
    directory_link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(PostDeployVerifierError, match="VERIFIER_OUTPUT_SYMLINK_FORBIDDEN"):
        _atomic_write(directory_link / "receipt.json", "{}\n")


def test_complete_verifier_opens_no_network_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline verifier attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    receipt = _run(tmp_path / "guarded")
    assert receipt.external_network_connections == receipt.aws_mutations == 0
