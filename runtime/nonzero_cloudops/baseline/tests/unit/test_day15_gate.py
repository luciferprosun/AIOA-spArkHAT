from __future__ import annotations

import copy
import hashlib
import hmac
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.day15 import alias_rollback
from scripts.day15 import external_preflight_attestation as attestation
from scripts.day15 import run_day15_gate as gate
from scripts.day15.preflight_region import (
    run_preflight,
    validate_judge_token_not_after,
    validate_region,
)
from scripts.day15.validate_template import (
    DEFAULT_TEMPLATE,
    canonical_json,
    compare_lambda_configuration_sha256,
    lambda_configuration_sha256,
    load_template,
)

NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def _clock() -> datetime:
    return NOW


def _context(tmp_path: Path, **changes: object) -> gate.GateContext:
    template = load_template(DEFAULT_TEMPLATE)
    values: dict[str, object] = {
        "template": template,
        "template_path": DEFAULT_TEMPLATE,
        "rendered_template": None,
        "rendered_template_path": None,
        "template_has_sam": True,
        "artifact": tmp_path / "missing.zip",
        "lock": gate.DEFAULT_LOCK,
        "manifest": tmp_path / "missing.manifest.json",
        "scan_report": tmp_path / "missing.scan.json",
        "toolchain": gate.DEFAULT_TOOLCHAIN,
        "external_receipt": tmp_path / "missing.receipt.json",
        "external_attestation_key": None,
        "region": "eu-central-1",
        "judge_token_not_after": "2026-08-25T00:00:00Z",
        "lambda_configuration_sha256": lambda_configuration_sha256(template),
        "clock": _clock,
    }
    values.update(changes)
    return gate.GateContext(**values)


def test_gate_matrix_has_exact_stable_ids_status_vocabulary_and_validate_only_output() -> None:
    assert tuple(item.gate_id for item in gate.GATES) == tuple(
        f"D15-G{index:02d}" for index in range(1, 11)
    )

    first = gate.validate_only()
    second = gate.validate_only()

    assert canonical_json(first) == canonical_json(second)
    assert first["gate_count"] == 10
    assert first["status"] == "PASS"
    assert first["ready_for_deployment"] is False
    assert first["aws_calls_performed"] is False
    assert first["deployment_performed"] is False
    assert {item["status"] for item in first["gates"]} <= gate.STATUS_VALUES


def test_region_is_explicit_and_never_inferred_from_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")

    assert validate_region(None).status == "BLOCKED"
    assert validate_region("").status == "BLOCKED"
    assert validate_region("us-east-1").status == "FAIL"
    assert validate_region("eu-central-1").status == "PASS"


@pytest.mark.parametrize(
    "value,status,reason",
    [
        (None, "BLOCKED", "JUDGE_TOKEN_NOT_AFTER_REQUIRED"),
        ("2026-08-24T12:00:00", "FAIL", "JUDGE_TOKEN_NOT_AFTER_NOT_UTC"),
        ("2026-08-24T13:00:00+01:00", "FAIL", "JUDGE_TOKEN_NOT_AFTER_NOT_UTC"),
        ("2026-08-24T12:00:00Z", "FAIL", "JUDGE_TOKEN_NOT_AFTER_NOT_FUTURE"),
        ("2026-08-25T12:00:01Z", "FAIL", "JUDGE_TOKEN_NOT_AFTER_EXCEEDS_24H"),
        ("2026-08-25T12:00:00Z", "PASS", None),
        ("2026-08-24T12:00:01+00:00", "PASS", None),
    ],
)
def test_judge_token_expiry_is_utc_future_and_at_most_24_hours(
    value: str | None,
    status: str,
    reason: str | None,
) -> None:
    result = validate_judge_token_not_after(value, clock=_clock)

    assert result.status == status
    if reason is not None:
        assert result.reasons == (reason,)


def test_judge_token_expiry_rejects_non_utc_injected_clock() -> None:
    result = validate_judge_token_not_after(
        "2026-08-24T13:00:00Z",
        clock=lambda: datetime(2026, 8, 24, 12, 0),
    )

    assert result.status == "BLOCKED"
    assert result.reasons == ("UTC_CLOCK_UNAVAILABLE",)


def test_configuration_digest_is_order_stable_and_changes_for_same_code_config_update() -> None:
    template = load_template(DEFAULT_TEMPLATE)
    reordered = {name: template[name] for name in reversed(tuple(template))}
    changed = copy.deepcopy(template)
    functions = gate._functions(changed)
    orchestrator = next(
        item for name, item in functions.items() if gate._is_orchestrator(name, item)
    )
    assert orchestrator["Properties"]["CodeUri"] == "../../dist/day15/aioa-lambda.zip"
    orchestrator["Properties"]["MemorySize"] += 128

    original_digest = lambda_configuration_sha256(template)
    assert lambda_configuration_sha256(reordered) == original_digest
    assert lambda_configuration_sha256(changed) != original_digest
    assert orchestrator["Properties"]["CodeUri"] == "../../dist/day15/aioa-lambda.zip"


def test_configuration_digest_preflight_requires_exact_supplied_value_and_never_echoes_expiry() -> (
    None
):
    template = load_template(DEFAULT_TEMPLATE)
    digest = lambda_configuration_sha256(template)
    status, reasons, computed = compare_lambda_configuration_sha256(template, digest)
    assert (status, reasons, computed) == ("PASS", (), digest)
    assert compare_lambda_configuration_sha256(template, "0" * 64)[0:2] == (
        "FAIL",
        ("LAMBDA_CONFIGURATION_SHA256_MISMATCH",),
    )

    expiry = "2026-08-25T00:00:00Z"
    payload = run_preflight(
        region="eu-central-1",
        judge_token_not_after=expiry,
        lambda_configuration_sha256=digest,
        clock=_clock,
    )
    rendered = canonical_json(payload)
    assert payload["status"] == "PASS"
    assert payload["computed_lambda_configuration_sha256"] == digest
    assert expiry not in rendered


def test_current_explicit_versions_aliases_and_public_url_are_locally_valid(tmp_path: Path) -> None:
    context = _context(tmp_path)

    version_result = gate._gate_versions(context)
    public_result = gate._gate_public_surface(context)
    iam_result = gate._gate_iam(context)

    assert version_result.status == "PASS"
    assert public_result.status == "PASS"
    assert iam_result.status == "BLOCKED"
    assert iam_result.reasons == ("RENDERED_IAM_TEMPLATE_REQUIRED",)


def test_missing_or_wrong_configuration_digest_blocks_or_fails_g07(tmp_path: Path) -> None:
    missing = gate._gate_versions(_context(tmp_path, lambda_configuration_sha256=None))
    mismatch = gate._gate_versions(_context(tmp_path, lambda_configuration_sha256="0" * 64))

    assert missing.status == "BLOCKED"
    assert missing.reasons == ("LAMBDA_CONFIGURATION_SHA256_REQUIRED",)
    assert mismatch.status == "FAIL"
    assert mismatch.reasons == ("LAMBDA_CONFIGURATION_SHA256_MISMATCH",)


def test_public_surface_rejects_api_gateway_and_mutation_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    template["Resources"]["UnexpectedApi"] = {"Type": "AWS::Serverless::HttpApi", "Properties": {}}
    context = _context(tmp_path, template=template)
    assert gate._gate_public_surface(context).status == "FAIL"

    clean = _context(tmp_path)
    router = tmp_path / "application.py"
    router.write_text("ROUTE = '/judge/approve'\n", encoding="utf-8")
    lambda_handler = tmp_path / "lambda_handler.py"
    lambda_handler.write_text("def lambda_handler(event, context): return None\n", encoding="utf-8")
    monkeypatch.setattr(gate, "JUDGE_ROUTER_SOURCES", (router, lambda_handler))
    result = gate._gate_public_surface(clean)
    assert result.status == "FAIL"
    assert "PUBLIC_MUTATION_OR_APPROVAL_ROUTE_FORBIDDEN" in result.reasons


def _binding_payload() -> dict[str, str]:
    return {
        "artifact_manifest_sha256": "a" * 64,
        "artifact_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "generator_sha256": "d" * 64,
        "judge_token_not_after_sha256": "e" * 64,
        "rendered_template_sha256": "f" * 64,
        "repository_commit_oid": "1" * 40,
        "template_sha256": "2" * 64,
    }


def _trusted_external_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bindings: dict[str, str],
) -> tuple[dict[str, object], Path, bytes]:
    key = b"reviewed-operator-key-material-" + (b"x" * 32)
    key_path = tmp_path / "operator.key"
    key_path.write_bytes(key)
    key_path.chmod(0o600)
    policy = tmp_path / "trust-policy.json"
    policy.write_text(
        canonical_json(
            {
                "algorithm": "HMAC-SHA256",
                "operator_hmac_key_sha256": hashlib.sha256(key).hexdigest(),
                "schema_version": 1,
                "status": "PASS",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(attestation, "DEFAULT_TRUST_POLICY", policy)
    account = "".join(("123456", "789012"))
    raw = {
        "checks": {name: "PASS" for name in attestation.CHECK_NAMES},
        "identities": {
            "artifact_bucket": "aioa-day15-private-artifacts",
            "artifact_path": "day15/reviewed/aioa-lambda.zip",
            "aws_account_id": account,
            "change_set_name": "day15-reviewed-release",
            "cloudwatch_evidence_digest": "4" * 64,
            "cost_notification_owner": "owner" + "@example.invalid",
            "deployment_profile": "aioa-day15-deployer",
            "deployment_role_arn": (
                f"arn:aws:iam::{account}:role/AIOANonZeroCloudOpsDay15DeploymentRole"
            ),
            "judge_secret_id": "aioa/day15/judge-token",
            "nova_inference_profile_id": "eu.amazon.nova-2-lite-v1:0",
            "sandbox_instance_id": "i-" + ("a" * 17),
            "sandbox_region": "eu-central-1",
            "sandbox_tag_key": "AIOACloudOpsSandbox",
            "sandbox_tag_value": "true",
            "stack_name": "aioa-nonzero-cloudops-day15",
        },
        "schema_version": 2,
    }
    raw_path = tmp_path / "external-bindings.json"
    raw_path.write_text(canonical_json(raw) + "\n", encoding="utf-8")
    raw_path.chmod(0o600)
    external = attestation.external_identity_bindings(raw_path)
    return (
        attestation.create_receipt(
            bindings,
            key,
            external,
            trust_policy=policy,
        ),
        key_path,
        key,
    )


def test_external_receipt_is_candidate_bound_closed_and_hmac_authenticated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = tmp_path / "receipt.json"
    bindings = _binding_payload()
    payload, key_path, _ = _trusted_external_receipt(tmp_path, monkeypatch, bindings)
    receipt.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    assert (
        gate._receipt_result(
            receipt,
            expected_bindings=bindings,
            attestation_key=key_path,
        ).status
        == "PASS"
    )

    changed = dict(bindings)
    changed["artifact_sha256"] = "9" * 64
    rebound = gate._receipt_result(
        receipt,
        expected_bindings=changed,
        attestation_key=key_path,
    )
    assert rebound.status == "FAIL"
    assert rebound.reasons == ("EXTERNAL_ATTESTATION_SCHEMA_OR_BINDING_INVALID",)

    payload["checks"]["nova_profile_access_ready"] = "BLOCKED"
    receipt.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    assert (
        gate._receipt_result(
            receipt,
            expected_bindings=bindings,
            attestation_key=key_path,
        ).status
        == "FAIL"
    )


@pytest.mark.parametrize(
    "mutation_kind",
    ("changed-threshold", "removed-thresholds", "extra-field"),
)
def test_external_receipt_rejects_resigned_cost_notification_threshold_drift(
    tmp_path: Path,
    mutation_kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = tmp_path / "receipt.json"
    bindings = _binding_payload()
    payload, key_path, key = _trusted_external_receipt(tmp_path, monkeypatch, bindings)

    assert payload["cost_notifications"] == {
        "currency": "USD",
        "thresholds": [10, 25, 40],
    }
    cost_notifications = payload["cost_notifications"]
    assert isinstance(cost_notifications, dict)
    if mutation_kind == "changed-threshold":
        cost_notifications["thresholds"] = [10, 25, 41]
    elif mutation_kind == "removed-thresholds":
        cost_notifications.pop("thresholds")
    else:
        payload["unreviewed_field"] = "PASS"
    unsigned = {name: value for name, value in payload.items() if name != "attestation_hmac_sha256"}
    payload["attestation_hmac_sha256"] = hmac.new(
        key,
        canonical_json(unsigned).encode(),
        hashlib.sha256,
    ).hexdigest()
    receipt_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")

    result = gate._receipt_result(
        receipt_path,
        expected_bindings=bindings,
        attestation_key=key_path,
    )
    assert result.status == "FAIL"
    assert result.reasons == ("EXTERNAL_ATTESTATION_SCHEMA_OR_BINDING_INVALID",)


def test_external_attestation_key_must_be_private_trusted_and_outside_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = tmp_path / "operator.key"
    key.write_bytes(b"k" * 32)
    key.chmod(0o644)
    with pytest.raises(attestation.AttestationFailure) as unsafe:
        attestation.read_attestation_key(key)
    assert unsafe.value.reason == "EXTERNAL_ATTESTATION_KEY_PERMISSIONS_UNSAFE"

    key.chmod(0o600)
    policy = tmp_path / "trust-policy.json"
    policy.write_text(
        canonical_json(
            {
                "algorithm": "HMAC-SHA256",
                "operator_hmac_key_sha256": hashlib.sha256(b"k" * 32).hexdigest(),
                "schema_version": 1,
                "status": "PASS",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(attestation, "DEFAULT_TRUST_POLICY", policy)
    assert attestation.read_attestation_key(key) == b"k" * 32


def test_external_attestation_bindings_cover_artifact_manifest_config_rendering_commit_and_expiry(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "aioa-lambda.zip"
    artifact_path.write_bytes(b"reviewed-artifact")
    artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    manifest_path = tmp_path / "aioa-lambda.manifest.json"
    manifest = {
        "artifact": {"sha256": artifact_sha},
        "repository": {"commit_oid": "a" * 40},
    }
    manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
    template = load_template(DEFAULT_TEMPLATE)
    rendered = copy.deepcopy(template)
    rendered.pop("Transform", None)
    rendered_path = tmp_path / "rendered-template.yaml"
    rendered_path.write_text(canonical_json(rendered) + "\n", encoding="utf-8")
    digest = lambda_configuration_sha256(template)

    first = attestation.candidate_bindings(
        artifact=artifact_path,
        manifest=manifest_path,
        template=DEFAULT_TEMPLATE,
        rendered_template=rendered_path,
        configuration_sha256=digest,
        judge_token_not_after="2026-08-25T00:00:00Z",
    )
    second = attestation.candidate_bindings(
        artifact=artifact_path,
        manifest=manifest_path,
        template=DEFAULT_TEMPLATE,
        rendered_template=rendered_path,
        configuration_sha256=digest,
        judge_token_not_after="2026-08-25T00:00:01Z",
    )

    assert set(first) == attestation.BINDING_NAMES
    assert first["artifact_sha256"] == artifact_sha
    assert first["configuration_sha256"] == digest
    assert first["repository_commit_oid"] == "a" * 40
    assert first["judge_token_not_after_sha256"] != second["judge_token_not_after_sha256"]
    assert "2026-08-25" not in canonical_json(first)


def test_missing_artifact_and_external_prerequisites_are_reported_as_blocked(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path)

    artifact_result = gate._gate_artifact(context)
    external_result = gate._gate_external(context)

    assert artifact_result.status == "BLOCKED"
    assert set(artifact_result.reasons) == {
        "ARTIFACT_MANIFEST_REQUIRED",
        "DEPENDENCY_SCAN_REPORT_REQUIRED",
        "LAMBDA_ARTIFACT_REQUIRED",
    }
    assert external_result.status == "BLOCKED"
    assert external_result.reasons == ("G10_SANITIZED_RECEIPT_REQUIRED",)


def _rollback_request() -> alias_rollback.RollbackRequest:
    return alias_rollback.RollbackRequest(
        stack_name="aioa-day15",
        orchestrator_function_name="aioa-orchestrator",
        executor_function_name="aioa-executor",
        orchestrator_previous_version="8",
        executor_previous_version="6",
        profile="day15-deployer",
        region="eu-central-1",
    )


def test_alias_rollback_plan_is_read_first_stable_and_alias_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _rollback_request()
    current = {"aioa-orchestrator": "9", "aioa-executor": "7"}
    checked: list[tuple[str, str]] = []
    monkeypatch.setattr(
        alias_rollback,
        "_stack_functions",
        lambda _request: {"aioa-orchestrator", "aioa-executor"},
    )
    monkeypatch.setattr(
        alias_rollback,
        "_alias_version",
        lambda function_name, _request: current[function_name],
    )
    monkeypatch.setattr(
        alias_rollback,
        "_validate_version_exists",
        lambda function_name, version, _request: checked.append((function_name, version)),
    )

    first = alias_rollback.build_plan(request)
    second = alias_rollback.build_plan(request)

    assert canonical_json(first) == canonical_json(second)
    assert first["operation"] == "alias-only-rollback-no-rebuild"
    assert [item["role"] for item in first["aliases"]] == ["executor", "orchestrator"]
    assert all(item["alias"] == "live" and item["pending"] for item in first["aliases"])
    assert checked


def test_alias_rollback_requires_reviewed_hash_then_reconciles_both_aliases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _rollback_request()
    current = {"aioa-orchestrator": "9", "aioa-executor": "7"}
    monkeypatch.setattr(
        alias_rollback,
        "_stack_functions",
        lambda _request: {"aioa-orchestrator", "aioa-executor"},
    )
    monkeypatch.setattr(
        alias_rollback,
        "_alias_version",
        lambda function_name, _request: current[function_name],
    )
    monkeypatch.setattr(alias_rollback, "_validate_version_exists", lambda *_args: None)

    def update(function_name: str, version: str, _request: object) -> None:
        current[function_name] = version

    monkeypatch.setattr(alias_rollback, "_update_alias", update)
    plan = alias_rollback.build_plan(request)
    with pytest.raises(alias_rollback.RollbackFailure) as unconfirmed:
        alias_rollback.execute_plan(request, plan, confirmed_sha256=None)
    assert unconfirmed.value.status == "BLOCKED"
    assert current == {"aioa-orchestrator": "9", "aioa-executor": "7"}

    result = alias_rollback.execute_plan(
        request,
        plan,
        confirmed_sha256=str(plan["plan_sha256"]),
    )
    assert result["status"] == "PASS"
    assert current == {"aioa-orchestrator": "8", "aioa-executor": "6"}


def test_alias_partial_update_reports_explicit_reconciliation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _rollback_request()
    monkeypatch.setattr(
        alias_rollback,
        "_stack_functions",
        lambda _request: {"aioa-orchestrator", "aioa-executor"},
    )
    monkeypatch.setattr(alias_rollback, "_alias_version", lambda *_args: "9")
    monkeypatch.setattr(alias_rollback, "_validate_version_exists", lambda *_args: None)
    monkeypatch.setattr(
        alias_rollback,
        "_update_alias",
        lambda *_args: (_ for _ in ()).throw(alias_rollback.RollbackFailure("WRITE_FAILED")),
    )
    plan = alias_rollback.build_plan(request)

    with pytest.raises(alias_rollback.RollbackFailure) as partial:
        alias_rollback.execute_plan(
            request,
            plan,
            confirmed_sha256=str(plan["plan_sha256"]),
        )
    assert partial.value.status == "PARTIAL"
    assert partial.value.reason == "ALIAS_RECONCILIATION_REQUIRED"


def test_alias_aws_command_uses_explicit_profile_region_and_no_ambient_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-propagate")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-propagate")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://redirect.invalid")
    monkeypatch.setenv("AWS_ENDPOINT_URL_LAMBDA", "https://redirect.invalid")
    monkeypatch.setattr(alias_rollback.shutil, "which", lambda _name: "/usr/bin/aws")

    def fake_run(command: tuple[str, ...], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="{}")

    monkeypatch.setattr(alias_rollback.subprocess, "run", fake_run)
    alias_rollback._aws_json(
        ("lambda", "get-alias", "--function-name", "aioa", "--name", "live"),
        profile="day15-deployer",
        region="eu-central-1",
    )

    command = captured["command"]
    environment = captured["environment"]
    assert command[-7:] == (
        "--profile",
        "day15-deployer",
        "--region",
        "eu-central-1",
        "--no-cli-pager",
        "--output",
        "json",
    )
    assert "AWS_ACCESS_KEY_ID" not in environment
    assert "AWS_SECRET_ACCESS_KEY" not in environment
    assert "AWS_ENDPOINT_URL" not in environment
    assert "AWS_ENDPOINT_URL_LAMBDA" not in environment
    assert environment["AWS_IGNORE_CONFIGURED_ENDPOINT_URLS"] == "true"
