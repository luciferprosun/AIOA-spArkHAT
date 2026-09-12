from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.phase3 import validate_iac as builder

from aioa_cloudops_agent.release.deployment_contract import load_deployment_contract
from aioa_cloudops_agent.release.iac import (
    ExpectedResourceManifest,
    IacCheckStatus,
    IacValidationError,
    ResourceAuthority,
    ResourceLifecycle,
    build_expected_resource_manifest,
    load_iac_template,
    render_iac_manifest_markdown,
    render_iac_manifest_schema,
    validate_iac,
)


def _contract():
    return load_deployment_contract(builder.DEFAULT_CONTRACT)


def _template() -> dict[str, object]:
    return load_iac_template(builder.DEFAULT_TEMPLATE)


def _manifest() -> ExpectedResourceManifest:
    return build_expected_resource_manifest(
        _template(),
        _contract(),
        template_bytes=builder.DEFAULT_TEMPLATE.read_bytes(),
    )


def _reasons(template: dict[str, object]) -> set[str]:
    return {
        reason
        for check in validate_iac(template, _contract())
        for reason in check.reasons
    }


def test_canonical_sam_path_passes_all_offline_checks_and_covers_every_resource() -> None:
    manifest = _manifest()

    assert len(manifest.checks) == 11
    assert all(check.status is IacCheckStatus.PASS for check in manifest.checks)
    assert manifest.resource_count == 22
    assert manifest.tagged_resource_count == 15
    assert manifest.retained_resource_count == 3
    assert manifest.conditional_public_resource_count == 3
    assert {item.logical_id for item in manifest.resources} == set(
        _template()["Resources"]  # type: ignore[arg-type]
    )
    assert manifest.network_connections == manifest.aws_mutations == manifest.live_receipts == 0


def test_manifest_records_authority_lifecycle_ownership_and_request_boundaries() -> None:
    manifest = _manifest()
    resources = {item.logical_id: item for item in manifest.resources}

    assert resources["OrchestratorRole"].authority is ResourceAuthority.READ_PLAN
    assert (
        resources["RemediationExecutorRole"].authority
        is ResourceAuthority.EXACT_PLAN_AND_CONFIRM_WRITE
    )
    assert resources["StateTable"].lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION
    assert (
        resources["OrchestratorFunctionUrl"].authority
        is ResourceAuthority.CONDITIONAL_PUBLIC_READ_INGRESS
    )
    assert resources["OrchestratorFunctionUrl"].condition == "PublicIngressEnabledCondition"
    assert resources["OrchestratorAlias"].dependencies == (
        "OrchestratorFunction",
        "OrchestratorVersion",
    )
    assert [item.default_enabled for item in manifest.future_requests] == [False] * 4
    assert [item.request_class.value for item in manifest.future_requests] == [
        "LOCAL",
        "REQUIRES_EXPLICIT_MUTATION_APPROVAL",
        "REQUIRES_EXPLICIT_MUTATION_APPROVAL",
        "REQUIRES_EXPLICIT_MUTATION_APPROVAL",
    ]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda value: value["Parameters"]["AppStage"].pop("AllowedValues"),  # type: ignore[index,union-attr]
            "STAGE_NOT_FROZEN",
        ),
        (
            lambda value: value["Resources"]["OrchestratorRole"]["Properties"][  # type: ignore[index]
                "Policies"
            ].append(
                {
                    "PolicyName": "PrivilegeExpansion",
                    "PolicyDocument": {
                        "Statement": [{"Action": ["ec2:TerminateInstances"], "Effect": "Allow"}]
                    },
                }
            ),
            "ORCHESTRATOR_ACTION_ALLOWLIST_MISMATCH",
        ),
        (
            lambda value: value["Resources"]["RemediationExecutorRole"]["Properties"][  # type: ignore[index]
                "Policies"
            ][0]["PolicyDocument"]["Statement"][0].update({"Action": ["logs:*"]}),
            "IAM_ACTION_WILDCARD_FORBIDDEN",
        ),
        (
            lambda value: value["Resources"]["OrchestratorFunctionUrl"].pop("Condition"),  # type: ignore[index,union-attr]
            "PUBLIC_RESOURCE_NOT_CONDITIONED",
        ),
        (
            lambda value: value["Resources"]["StateTable"]["Properties"].update(  # type: ignore[index,union-attr]
                {"SSESpecification": {"SSEEnabled": False}}
            ),
            "DYNAMODB_SAFETY_SETTINGS_INVALID",
        ),
        (
            lambda value: value["Resources"]["OrchestratorErrorsAlarm"][  # type: ignore[index]
                "Properties"
            ].pop("Tags"),
            "OWNERSHIP_TAGS_MISSING_OR_INVALID",
        ),
        (
            lambda value: value["Resources"].update(  # type: ignore[union-attr]
                {"UnexpectedDatabase": {"Type": "AWS::RDS::DBInstance", "Properties": {}}}
            ),
            "UNREVIEWED_RESOURCE_TYPE",
        ),
        (
            lambda value: value["Resources"]["StateTable"].pop("DeletionPolicy"),  # type: ignore[index,union-attr]
            "DYNAMODB_RETENTION_INVALID",
        ),
    ),
)
def test_iac_validation_fails_closed_on_security_and_lifecycle_drift(
    mutation,
    reason: str,
) -> None:
    template = copy.deepcopy(_template())
    mutation(template)

    assert reason in _reasons(template)
    with pytest.raises(IacValidationError, match="IAC_DRY_RUN_VALIDATION_FAILED"):
        build_expected_resource_manifest(
            template,
            _contract(),
            template_bytes=b"tampered",
        )


def test_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    template = tmp_path / "duplicate.yaml"
    template.write_text(
        'Transform: "AWS::Serverless-2016-10-31"\nTransform: other\n',
        encoding="utf-8",
    )

    with pytest.raises(IacValidationError, match="IAC_TEMPLATE_DUPLICATE_KEY"):
        load_iac_template(template)


def test_manifest_schema_and_projection_are_deterministic_and_strict() -> None:
    first = _manifest()
    second = _manifest()

    assert first == second
    assert render_iac_manifest_schema() == render_iac_manifest_schema()
    document = render_iac_manifest_markdown(first)
    assert "No AWS account was contacted" in document
    assert "Creating a change set is treated as a cloud mutation" in document

    value = first.model_dump(mode="json")
    value["unexpected"] = True
    with pytest.raises(ValidationError):
        ExpectedResourceManifest.model_validate_json(json.dumps(value))


def test_builder_writes_and_checks_exact_generated_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "manifest.json"
    document_path = tmp_path / "manifest.md"
    schema_path = tmp_path / "schema.json"
    monkeypatch.setattr(builder, "DEFAULT_MANIFEST", manifest_path)
    monkeypatch.setattr(builder, "DEFAULT_DOCUMENT", document_path)
    monkeypatch.setattr(builder, "DEFAULT_SCHEMA", schema_path)

    assert builder.build()["status"] == "PASS"
    assert builder.build(check=True)["status"] == "PASS"
    assert manifest_path.stat().st_mode & 0o777 == 0o600

    document_path.write_text("drift", encoding="utf-8")
    with pytest.raises(IacValidationError, match="IAC_GENERATED_ARTIFACT_DRIFT"):
        builder.build(check=True)


def test_builder_refuses_symlink_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.json"
    target.write_text("do not replace", encoding="utf-8")
    link = tmp_path / "manifest.json"
    link.symlink_to(target)
    monkeypatch.setattr(builder, "DEFAULT_MANIFEST", link)
    monkeypatch.setattr(builder, "DEFAULT_DOCUMENT", tmp_path / "manifest.md")
    monkeypatch.setattr(builder, "DEFAULT_SCHEMA", tmp_path / "schema.json")

    with pytest.raises(IacValidationError, match="IAC_OUTPUT_SYMLINK_FORBIDDEN"):
        builder.build()
    assert target.read_text(encoding="utf-8") == "do not replace"


def test_offline_iac_path_opens_no_network_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("offline IaC validation attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    assert _manifest().network_connections == 0
