from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.day15 import build_lambda_artifact
from scripts.day15 import run_day15_gate as gate
from scripts.day15.validate_template import (
    DEFAULT_TEMPLATE,
    lambda_configuration_sha256,
    load_template,
)


def _context(
    tmp_path: Path,
    template: dict[str, object],
    **changes: object,
) -> gate.GateContext:
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
        "external_receipt": tmp_path / "missing.external.json",
        "external_attestation_key": None,
        "region": "eu-central-1",
        "judge_token_not_after": "2026-08-25T00:00:00Z",
        "lambda_configuration_sha256": lambda_configuration_sha256(template),
        "clock": lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    }
    values.update(changes)
    return gate.GateContext(**values)


def test_deployment_decision_requires_all_ten_gates_to_pass() -> None:
    passing = tuple(gate._result(definition, "PASS") for definition in gate.GATES)
    ready = gate._payload(passing, mode="full")
    assert ready["ready_for_change_set"] is True
    assert ready["predeploy_change_set_review_required"] is True
    assert ready["ready_for_deployment"] is False
    assert ready["deployment_authorized"] is False

    for status in ("FAIL", "PARTIAL", "BLOCKED"):
        changed = (gate._result(gate.GATES[0], status, (f"TEST_{status}",)), *passing[1:])
        decision = gate._payload(changed, mode="full")
        assert decision["status"] == status
        assert decision["ready_for_change_set"] is False
        assert decision["ready_for_deployment"] is False

    assert gate._payload(passing, mode="validate-only")["ready_for_deployment"] is False
    assert gate._payload(passing, mode="validate-only")["ready_for_change_set"] is False


def test_local_gate_never_performs_aws_api_calls_and_only_probes_cli_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[str, ...]] = []

    def bounded_subprocess(command: object, **_kwargs: object) -> SimpleNamespace:
        arguments = tuple(command)  # type: ignore[arg-type]
        commands.append(arguments)
        if arguments[-1:] == ("--version",) and Path(arguments[0]).name == "aws":
            return SimpleNamespace(
                returncode=0,
                stdout="aws-cli/2.36.11 Python/3.14 Linux\n",
                stderr="",
            )
        raise AssertionError("the local deployment gate must not start AWS API commands")

    monkeypatch.setattr(build_lambda_artifact.subprocess, "run", bounded_subprocess)
    template = load_template(DEFAULT_TEMPLATE)
    payload = gate.run_gate(
        artifact=tmp_path / "missing.zip",
        manifest=tmp_path / "missing.manifest.json",
        scan_report=tmp_path / "missing.scan.json",
        external_receipt=tmp_path / "missing.external.json",
        region="eu-central-1",
        judge_token_not_after="2026-08-25T00:00:00Z",
        lambda_configuration_sha256=lambda_configuration_sha256(template),
        clock=lambda: datetime(2026, 8, 24, 12, 0, tzinfo=UTC),
    )

    assert payload["aws_calls_performed"] is False
    assert payload["deployment_performed"] is False
    assert payload["ready_for_deployment"] is False
    assert len(commands) == 1


def test_g01_current_handlers_routes_resume_and_server_budgets_are_frozen(
    tmp_path: Path,
) -> None:
    result = gate._gate_runtime(_context(tmp_path, load_template(DEFAULT_TEMPLATE)))

    assert result.status == "PASS"
    assert result.reasons == ()


def test_g01_rejects_declared_handler_that_does_not_exist(tmp_path: Path) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    functions = gate._functions(template)
    orchestrator = next(
        resource for name, resource in functions.items() if gate._is_orchestrator(name, resource)
    )
    orchestrator["Properties"]["Handler"] = (
        "aioa_cloudops_agent.judge.lambda_handler.nonexistent_handler"
    )

    result = gate._gate_runtime(_context(tmp_path, template))

    assert result.status == "FAIL"
    assert "LAMBDA_HANDLER_CONTRACT_INVALID" in result.reasons


@pytest.mark.parametrize(
    ("source_attribute", "reason"),
    (
        ("JUDGE_ROUTER_SOURCES", "JUDGE_ROUTE_METHOD_CONTRACT_INVALID"),
        ("JUDGE_CONFIG_SOURCE", "SERVER_OWNED_BUDGET_CONTRACT_INVALID"),
        ("JUDGE_RUNTIME_SOURCE", "FRESH_REQUEST_RUNTIME_CONTRACT_INVALID"),
        ("APPROVAL_RESUME_SOURCE", "COLD_START_RESUME_CONTRACT_INVALID"),
        ("RUNTIME_PROOF_CONTRACTS", "RUNTIME_PROOF_CONTRACT_MISSING"),
    ),
)
def test_g01_rejects_missing_authority_or_proof_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_attribute: str,
    reason: str,
) -> None:
    missing = tmp_path / "missing.py"
    if source_attribute == "JUDGE_ROUTER_SOURCES":
        monkeypatch.setattr(
            gate,
            source_attribute,
            (missing, gate.JUDGE_ROUTER_SOURCES[1]),
        )
    elif source_attribute == "RUNTIME_PROOF_CONTRACTS":
        monkeypatch.setattr(gate, source_attribute, ((missing, ("test_missing",)),))
    else:
        monkeypatch.setattr(gate, source_attribute, missing)

    result = gate._gate_runtime(_context(tmp_path, load_template(DEFAULT_TEMPLATE)))

    assert result.status == "FAIL"
    assert reason in result.reasons


@pytest.mark.parametrize(
    ("source_attribute", "original", "changed", "reason"),
    (
        (
            "JUDGE_ROUTER_SOURCES",
            'request.path == "/ready"',
            'request.path == "/unreviewed"',
            "JUDGE_ROUTE_METHOD_CONTRACT_INVALID",
        ),
        (
            "JUDGE_CONFIG_SOURCE",
            "JUDGE_MAX_TURNS: Final = 8",
            "JUDGE_MAX_TURNS: Final = 9",
            "SERVER_OWNED_BUDGET_CONTRACT_INVALID",
        ),
        (
            "JUDGE_RUNTIME_SOURCE",
            "self._agent_factory(",
            "self._unreviewed_factory(",
            "FRESH_REQUEST_RUNTIME_CONTRACT_INVALID",
        ),
        (
            "APPROVAL_RESUME_SOURCE",
            "class AuthenticatedApprovalResumeService:",
            "class UnreviewedApprovalResumeService:",
            "COLD_START_RESUME_CONTRACT_INVALID",
        ),
    ),
)
def test_g01_rejects_semantic_runtime_contract_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_attribute: str,
    original: str,
    changed: str,
    reason: str,
) -> None:
    configured = getattr(gate, source_attribute)
    source = configured[0] if source_attribute == "JUDGE_ROUTER_SOURCES" else configured
    assert isinstance(source, Path)
    text = source.read_text(encoding="utf-8")
    assert original in text
    changed_source = tmp_path / source.name
    changed_source.write_text(text.replace(original, changed, 1), encoding="utf-8")
    if source_attribute == "JUDGE_ROUTER_SOURCES":
        monkeypatch.setattr(gate, source_attribute, (changed_source, configured[1]))
    else:
        monkeypatch.setattr(gate, source_attribute, changed_source)

    result = gate._gate_runtime(_context(tmp_path, load_template(DEFAULT_TEMPLATE)))

    assert result.status == "FAIL"
    assert reason in result.reasons


def test_g02_requires_authenticated_render_and_exact_closed_role_allowlists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    rendered.pop("Transform", None)
    rendered_path = tmp_path / "rendered-template.yaml"
    monkeypatch.setattr(
        gate,
        "verify_rendered_template",
        lambda **_kwargs: (rendered, {"status": "PASS"}),
    )
    context = _context(
        tmp_path,
        load_template(DEFAULT_TEMPLATE),
        rendered_template=rendered,
        rendered_template_path=rendered_path,
    )
    assert gate._gate_iam(context).status == "PASS"

    policies = rendered["Resources"]["OrchestratorRole"]["Properties"]["Policies"]
    policies.append(
        {
            "PolicyName": "DeceptivelyScopedExtraWrite",
            "PolicyDocument": {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": ["s3:DeleteObject"],
                        "Resource": "arn:aws:s3:::one-reviewed-bucket/one-key",
                    }
                ],
            },
        }
    )
    result = gate._gate_iam(context)
    assert result.status == "FAIL"
    assert "IAM_ROLE_POLICY_ALLOWLIST_INVALID" in result.reasons


def test_g02_rejects_unproven_rendered_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    rendered.pop("Transform", None)

    def reject(**_kwargs: object) -> None:
        raise gate.RenderFailure("RENDERED_TEMPLATE_PROVENANCE_MISMATCH")

    monkeypatch.setattr(gate, "verify_rendered_template", reject)
    result = gate._gate_iam(
        _context(
            tmp_path,
            load_template(DEFAULT_TEMPLATE),
            rendered_template=rendered,
            rendered_template_path=tmp_path / "forged.yaml",
        )
    )
    assert result.status == "FAIL"
    assert result.reasons == ("RENDERED_TEMPLATE_PROVENANCE_MISMATCH",)


def _write_json(path: Path, value: object) -> None:
    path.write_text(gate.canonical_json(value) + "\n", encoding="utf-8")


def test_g04_reexecutes_clean_import_archive_dependency_and_container_proofs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "aioa-lambda.zip"
    artifact_path.write_bytes(b"reviewed-zip")
    lock_path = tmp_path / "runtime.txt"
    lock_path.write_bytes(b"reviewed-lock")
    manifest_path = tmp_path / "manifest.json"
    scan_path = tmp_path / "scan.json"
    artifact_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    lock_sha = hashlib.sha256(lock_path.read_bytes()).hexdigest()
    archive = {
        "entry_count": 1,
        "sha256": artifact_sha,
        "status": "PASS",
        "zip_compression": "stored",
    }
    repository = {"commit_oid": "a" * 40, "status": "CLEAN"}
    handlers = ["demo.handler"]
    toolchain = json.loads(gate.DEFAULT_TOOLCHAIN.read_text(encoding="utf-8"))
    container_contract = toolchain["lambda_compatible_container"]
    image = container_contract["image"]
    container = {
        "architecture": "amd64",
        "engine": container_contract["engine"],
        "engine_version": container_contract["engine_version"],
        "image_digest": image.rsplit("@", 1)[1],
        "status": "PASS",
        "validator": "lambda-python3.12-x86_64-container",
    }
    scan = {
        "artifact_sha256": artifact_sha,
        "audited_dependency_count": 1,
        "expected_dependency_count": 1,
        "lock_sha256": lock_sha,
        "scanner": "pip-audit",
        "scanner_version": "2.10.1",
        "schema_version": 1,
        "status": "PASS",
        "vulnerabilities": [],
        "vulnerability_count": 0,
    }
    manifest = {
        "archive_scan": archive,
        "artifact": {
            "code_sha256_base64": base64.b64encode(bytes.fromhex(artifact_sha)).decode(),
            "entry_count": 1,
            "filename": "aioa-lambda.zip",
            "sha256": artifact_sha,
        },
        "builder": toolchain["artifact_builder"],
        "dependencies": [{"name": "demo", "version": "1"}],
        "deterministic_rebuild": {"sha256": artifact_sha, "status": "PASS"},
        "handlers": handlers,
        "inputs": {"lock_sha256": lock_sha},
        "lambda_compatible_container_validation": container,
        "lambda_like_clean_import": "PASS",
        "repository": repository,
        "schema_version": 1,
    }
    fresh = {
        "archive_scan": archive,
        "builder": toolchain["artifact_builder"],
        "dependencies": manifest["dependencies"],
        "handlers": handlers,
        "lambda_compatible_container_validation": container,
        "lambda_like_clean_import": "PASS",
        "scan": scan,
    }
    _write_json(manifest_path, manifest)
    _write_json(scan_path, scan)
    monkeypatch.setattr(
        gate,
        "validate_runtime_lock",
        lambda _path: (build_lambda_artifact.LockEntry("demo", "1", ("a" * 64,)),),
    )
    monkeypatch.setattr(gate, "inspect_archive", lambda _path: archive)
    monkeypatch.setattr(gate, "validate_repository_inputs", lambda _paths: repository)
    monkeypatch.setattr(gate, "discover_lambda_handlers", lambda _path: tuple(handlers))
    monkeypatch.setattr(gate, "revalidate_artifact", lambda *_args: fresh)
    context = _context(
        tmp_path,
        load_template(DEFAULT_TEMPLATE),
        artifact=artifact_path,
        lock=lock_path,
        manifest=manifest_path,
        scan_report=scan_path,
    )

    assert gate._gate_artifact(context).status == "PASS"

    fresh["scan"] = {
        "artifact_sha256": artifact_sha,
        "lock_sha256": lock_sha,
        "reasons": ["PIP_AUDIT_UNAVAILABLE"],
        "scanner": "pip-audit",
        "schema_version": 1,
        "status": "BLOCKED",
    }
    unavailable_scanner = gate._gate_artifact(context)
    assert unavailable_scanner.status == "BLOCKED"
    assert unavailable_scanner.reasons == ("FRESH_DEPENDENCY_SCAN_BLOCKED",)
    fresh["scan"] = scan

    manifest["lambda_like_clean_import"] = "FAIL"
    _write_json(manifest_path, manifest)
    fabricated_import = gate._gate_artifact(context)
    assert fabricated_import.status == "FAIL"
    assert "LAMBDA_CLEAN_IMPORT_PROOF_INVALID" in fabricated_import.reasons

    manifest["lambda_like_clean_import"] = "PASS"
    _write_json(manifest_path, manifest)
    fresh["scan"] = {**scan, "status": "FAIL", "vulnerability_count": 1}
    fabricated_scan = gate._gate_artifact(context)
    assert fabricated_scan.status == "FAIL"
    assert "FRESH_DEPENDENCY_SCAN_FAILED" in fabricated_scan.reasons


def test_g06_requires_explicit_cfn_rule_even_when_region_parameter_is_allowlisted(
    tmp_path: Path,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    assert template["Parameters"]["DeploymentRegion"]["AllowedValues"] == ["eu-central-1"]
    template.pop("Rules")
    template["Conditions"]["DecoyRegionCondition"] = {
        "Fn::Equals": [{"Ref": "AWS::Region"}, "eu-central-1"]
    }

    result = gate._gate_region(_context(tmp_path, template))

    assert result.status == "FAIL"
    assert result.reasons == ("TEMPLATE_REGION_GUARD_MISSING",)


def test_g07_requires_semantic_alias_only_rollback_and_executable_proofs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert gate._gate_versions(_context(tmp_path, load_template(DEFAULT_TEMPLATE))).status == "PASS"

    malicious = tmp_path / "alias_rollback.py"
    source = gate.ROLLBACK_TOOL.read_text(encoding="utf-8")
    assert '"update-alias"' in source
    malicious.write_text(
        source.replace('"update-alias"', '"update-function-code"', 1), encoding="utf-8"
    )
    monkeypatch.setattr(gate, "ROLLBACK_TOOL", malicious)

    result = gate._gate_versions(_context(tmp_path, load_template(DEFAULT_TEMPLATE)))
    assert result.status == "FAIL"
    assert "ALIAS_ONLY_ROLLBACK_CONTRACT_INVALID" in result.reasons

    monkeypatch.setattr(gate, "ROLLBACK_TOOL", Path("/bin/true"))
    inert = gate._gate_versions(_context(tmp_path, load_template(DEFAULT_TEMPLATE)))
    assert inert.status == "FAIL"
    assert "ALIAS_ONLY_ROLLBACK_CONTRACT_INVALID" in inert.reasons


@pytest.mark.parametrize(
    "resource_type",
    (
        "AWS::EC2::NatGateway",
        "AWS::RDS::DBInstance",
        "AWS::ECS::Service",
        "AWS::EKS::Cluster",
        "AWS::OpenSearchService::Domain",
        "AWS::OpenSearchServerless::Collection",
        "AWS::ElastiCache::ReplicationGroup",
        "AWS::MemoryDB::Cluster",
        "AWS::StepFunctions::StateMachine",
        "AWS::SQS::Queue",
        "AWS::Scheduler::Schedule",
    ),
)
def test_g08_rejects_every_forbidden_cost_service(
    tmp_path: Path,
    resource_type: str,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    template["Resources"]["ForbiddenCostResource"] = {
        "Type": resource_type,
        "Properties": {},
    }

    result = gate._gate_observability(_context(tmp_path, template))
    assert result.status == "FAIL"
    assert "FORBIDDEN_COST_RESOURCE_PRESENT" in result.reasons


def test_g08_rejects_provisioned_concurrency_in_any_nested_resource_property(
    tmp_path: Path,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    orchestrator = next(
        resource
        for name, resource in gate._functions(template).items()
        if gate._is_orchestrator(name, resource)
    )
    orchestrator["Properties"]["ProvisionedConcurrencyConfig"] = {
        "ProvisionedConcurrentExecutions": 1
    }

    result = gate._gate_observability(_context(tmp_path, template))
    assert result.status == "FAIL"
    assert "PROVISIONED_CONCURRENCY_FORBIDDEN" in result.reasons


def _passing_deployment_contract_and_receipt() -> tuple[dict[str, object], dict[str, object]]:
    contract = json.loads(gate.DEFAULT_DEPLOYMENT_CONTRACT.read_text(encoding="utf-8"))
    contract.update(
        {
            "artifact_bucket_sha256": "a" * 64,
            "deployment_role_arn_sha256": "c" * 64,
            "status": "PASS",
        }
    )
    receipt = {
        "checks": {name: "PASS" for name in gate.BUCKET_CONTROL_CHECKS},
        "external_identity_bindings": {
            "artifact_bucket_sha256": "a" * 64,
            "artifact_path_sha256": gate._text_sha256("day15/reviewed/aioa-lambda.zip"),
            "change_set_name_sha256": gate._text_sha256("day15-reviewed-release"),
            "deployment_profile_sha256": gate._text_sha256("aioa-day15-deployer"),
            "deployment_role_arn_sha256": "c" * 64,
            "stack_name_sha256": gate._text_sha256("aioa-nonzero-cloudops-day15"),
        },
    }
    return contract, receipt


def test_g10_deployment_contract_is_blocked_until_selected_hashes_are_reviewed(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    _write_json(receipt, {})

    result = gate._deployment_contract_result(gate.DEFAULT_DEPLOYMENT_CONTRACT, receipt)

    assert result.status == "BLOCKED"
    assert result.reasons == ("DEPLOYMENT_CONTRACT_SELECTION_REQUIRED",)


def test_current_g10_uses_tracked_policy_only_and_rejects_private_identity_hashes(
    tmp_path: Path,
) -> None:
    assert gate._deployment_policy_result(gate.DEFAULT_DEPLOYMENT_CONTRACT).status == "PASS"
    contract = json.loads(gate.DEFAULT_DEPLOYMENT_CONTRACT.read_text(encoding="utf-8"))
    contract["artifact_bucket_sha256"] = "a" * 64
    contract["deployment_role_arn_sha256"] = "b" * 64
    contract["status"] = "PASS"
    path = tmp_path / "tracked-private-hashes.json"
    _write_json(path, contract)

    result = gate._deployment_policy_result(path)

    assert result.status == "FAIL"
    assert result.reasons == ("TRACKED_DEPLOYMENT_POLICY_INVALID",)


def test_g10_deployment_contract_binds_names_prefix_hashes_and_bucket_controls(
    tmp_path: Path,
) -> None:
    contract, receipt = _passing_deployment_contract_and_receipt()
    assert "reviewed_change_set_digest" not in contract
    assert "change_set_digest_sha256" not in receipt["external_identity_bindings"]
    contract_path = tmp_path / "contract.json"
    receipt_path = tmp_path / "receipt.json"
    _write_json(contract_path, contract)
    _write_json(receipt_path, receipt)

    assert gate._deployment_contract_result(contract_path, receipt_path).status == "PASS"

    receipt["external_identity_bindings"]["artifact_path_sha256"] = "f" * 64
    _write_json(receipt_path, receipt)
    rebound = gate._deployment_contract_result(contract_path, receipt_path)
    assert rebound.status == "FAIL"
    assert rebound.reasons == ("DEPLOYMENT_CONTRACT_RECEIPT_BINDING_INVALID",)

    contract, receipt = _passing_deployment_contract_and_receipt()
    contract["stack_name"] = "unreviewed-stack"
    _write_json(contract_path, contract)
    _write_json(receipt_path, receipt)
    drift = gate._deployment_contract_result(contract_path, receipt_path)
    assert drift.status == "FAIL"
    assert drift.reasons == ("DAY15_DEPLOYMENT_CONTRACT_INVALID",)

    contract, receipt = _passing_deployment_contract_and_receipt()
    receipt["checks"]["artifact_bucket_tls_only_ready"] = "BLOCKED"
    _write_json(contract_path, contract)
    _write_json(receipt_path, receipt)
    unsafe_bucket = gate._deployment_contract_result(contract_path, receipt_path)
    assert unsafe_bucket.status == "FAIL"
    assert unsafe_bucket.reasons == ("DEPLOYMENT_BUCKET_CONTROLS_NOT_ATTESTED",)


def test_g10_executes_only_bounded_exact_aws_cli_version_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toolchain = json.loads(gate.DEFAULT_TOOLCHAIN.read_text(encoding="utf-8"))
    monkeypatch.setattr(gate.shutil, "which", lambda _name: None)
    unavailable = gate._aws_cli_tool_result(toolchain)
    assert unavailable.status == "BLOCKED"
    assert unavailable.reasons == ("PINNED_AWS_CLI_UNAVAILABLE",)

    captured: dict[str, object] = {}
    monkeypatch.setattr(gate.shutil, "which", lambda _name: "/usr/local/bin/aws")

    def fake_run(command: object, **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(
            returncode=0, stdout="aws-cli/2.36.10 Python/3.14 Linux\n", stderr=""
        )

    monkeypatch.setattr(gate.subprocess, "run", fake_run)
    mismatch = gate._aws_cli_tool_result(toolchain)
    assert mismatch.status == "FAIL"
    assert mismatch.reasons == ("AWS_CLI_VERSION_MISMATCH",)
    assert captured["command"] == ("/usr/local/bin/aws", "--version")
    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert "AWS_ACCESS_KEY_ID" not in environment
    assert environment["AWS_CONFIG_FILE"] == gate.os.devnull
    assert environment["AWS_SHARED_CREDENTIALS_FILE"] == gate.os.devnull

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="aws-cli/2.36.11 Python/3.14 Linux\n",
            stderr="",
        ),
    )
    assert gate._aws_cli_tool_result(toolchain).status == "PASS"


@pytest.mark.parametrize(
    "logical_id",
    (
        "OrchestratorFunctionUrl",
        "PublicFunctionUrlInvokePermission",
        "PublicFunctionInvokeViaUrlPermission",
    ),
)
def test_g09_requires_ingress_condition_on_url_and_both_public_permissions(
    tmp_path: Path,
    logical_id: str,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    template["Resources"][logical_id].pop("Condition")

    result = gate._gate_public_surface(_context(tmp_path, template))

    assert result.status == "FAIL"
    assert any("CONDITION" in reason for reason in result.reasons)


def test_g09_requires_exact_fail_closed_public_ingress_condition_binding(
    tmp_path: Path,
) -> None:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    template["Conditions"]["PublicIngressEnabledCondition"] = {
        "Fn::Equals": [{"Ref": "PublicIngressEnabled"}, "false"]
    }

    result = gate._gate_public_surface(_context(tmp_path, template))

    assert result.status == "FAIL"
    assert result.reasons == ("PUBLIC_INGRESS_CONDITION_BINDING_INVALID",)
