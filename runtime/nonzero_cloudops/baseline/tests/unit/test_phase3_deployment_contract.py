from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from scripts.phase3.build_deployment_contract import (
    DEFAULT_CONTRACT,
    DEFAULT_DOCUMENT,
    DEFAULT_SCHEMA,
    build,
)

from aioa_cloudops_agent.release.deployment_contract import (
    AwsDeploymentContract,
    DeploymentContractError,
    classified_field_count,
    contract_sha256,
    load_deployment_contract,
    operator_input_blockers,
    render_contract_markdown,
    render_contract_schema,
    validate_contract_has_no_secret_material,
)


def _raw_contract() -> dict[str, object]:
    return json.loads(DEFAULT_CONTRACT.read_text(encoding="utf-8"))


def _validated(value: dict[str, object]) -> AwsDeploymentContract:
    return AwsDeploymentContract.model_validate_json(
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True)
    )


def test_canonical_contract_is_strict_classified_and_explicitly_external() -> None:
    contract = load_deployment_contract(DEFAULT_CONTRACT)

    assert contract.schema_version == 3
    assert contract.contract_id == "AIOA_PHASE3_AWS_DEPLOYMENT_CONTRACT"
    assert classified_field_count(contract) == 41
    assert operator_input_blockers(contract) == (
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.deployment_role_arn_sha256",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:identity.expected_account_id_sha256",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:infrastructure.artifact_bucket_sha256",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:operations.budget_owner_sha256",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.cloudwatch_evidence_confirmed",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.judge_secret_authority_confirmed",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.model_access_confirmed",
        "EXTERNAL_OPERATOR_INPUT_REQUIRED:runtime.sandbox_instance_id_sha256",
    )
    validate_contract_has_no_secret_material(contract)


def test_schema_and_human_document_are_deterministic_projections() -> None:
    contract = load_deployment_contract(DEFAULT_CONTRACT)

    assert DEFAULT_SCHEMA.read_text(encoding="utf-8") == render_contract_schema()
    assert DEFAULT_DOCUMENT.read_text(encoding="utf-8") == render_contract_markdown(contract)
    assert build(check=True)["status"] == "PASS"
    assert contract_sha256(contract) in DEFAULT_DOCUMENT.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("section", "field"),
    (
        ("release", "branch"),
        ("identity", "target_regions"),
        ("application", "ownership_tags"),
        ("infrastructure", "mechanism"),
        ("runtime", "iam"),
        ("operations", "rollback_policy"),
    ),
)
def test_every_reviewed_field_rejects_authority_class_drift(
    section: str,
    field: str,
) -> None:
    value = _raw_contract()
    classified = value[section][field]  # type: ignore[index]
    assert isinstance(classified, dict)
    classified["requirement"] = "EXTERNAL_OPERATOR_INPUT"

    with pytest.raises(ValidationError):
        _validated(value)


def test_contract_rejects_missing_unknown_and_non_strict_fields() -> None:
    missing = _raw_contract()
    del missing["runtime"]["model"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(missing)

    unknown = _raw_contract()
    unknown["unsafe_extension"] = {}
    with pytest.raises(ValidationError):
        _validated(unknown)

    coerced = _raw_contract()
    coerced["runtime"]["judge_token_lifetime_seconds_max"]["value"] = "86400"  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(coerced)


def test_contract_rejects_region_model_and_runtime_surface_drift() -> None:
    wrong_region = _raw_contract()
    wrong_region["identity"]["target_regions"]["value"] = ["us-east-1"]  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(wrong_region)

    functions = _raw_contract()
    functions["runtime"]["lambda_functions"]["value"].pop()  # type: ignore[index,union-attr]
    with pytest.raises(ValidationError):
        _validated(functions)

    route = _raw_contract()
    route["runtime"]["api"]["value"]["public_mutation_routes"] = [  # type: ignore[index]
        "/judge/approve"
    ]
    with pytest.raises(ValidationError):
        _validated(route)


def test_contract_rejects_privilege_merge_and_enabled_mutation_flags() -> None:
    merged = _raw_contract()
    actions = merged["runtime"]["iam"]["value"]["orchestrator_actions"]  # type: ignore[index]
    assert isinstance(actions, list)
    actions.append("ec2:StopInstances")
    actions.sort()
    with pytest.raises(ValidationError):
        _validated(merged)

    enabled = _raw_contract()
    enabled["runtime"]["feature_flags"]["value"]["AWS_MUTATIONS_ENABLED"] = "true"  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(enabled)


def test_contract_rejects_unsafe_retention_cost_and_bucket_controls() -> None:
    ttl = _raw_contract()
    ttl["runtime"]["dynamodb"]["value"]["ttl_enabled"] = True  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(ttl)

    cost = _raw_contract()
    cost["operations"]["cost"]["value"]["budget_thresholds_usd"] = [10, 25, 1000]  # type: ignore[index]
    with pytest.raises(ValidationError):
        _validated(cost)

    bucket = _raw_contract()
    bucket["infrastructure"]["artifact_bucket_controls"]["value"][  # type: ignore[index]
        "tls_only_required"
    ] = False
    with pytest.raises(ValidationError):
        _validated(bucket)


def test_contract_hash_is_canonical_and_external_hashes_never_need_raw_identity() -> None:
    first = _raw_contract()
    second = copy.deepcopy(first)
    second = dict(reversed(tuple(second.items())))

    assert contract_sha256(_validated(first)) == contract_sha256(_validated(second))
    rendered = json.dumps(first, sort_keys=True)
    assert "123456789012" not in rendered
    assert "arn:aws:iam::" not in rendered
    assert "i-0123456789abcdef0" not in rendered


def test_loader_rejects_duplicate_keys_nonfinite_values_and_secret_material(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":3,"schema_version":3}', encoding="utf-8")
    with pytest.raises(
        DeploymentContractError,
        match="DEPLOYMENT_CONTRACT_DUPLICATE_KEY",
    ):
        load_deployment_contract(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"schema_version":NaN}', encoding="utf-8")
    with pytest.raises(
        DeploymentContractError,
        match="DEPLOYMENT_CONTRACT_NONFINITE_VALUE",
    ):
        load_deployment_contract(nonfinite)

    secret = _validated(_raw_contract()).model_copy(
        update={"contract_id": "AKIA" + "ABCDEFGHIJKLMNOP"}
    )
    with pytest.raises(
        DeploymentContractError,
        match="DEPLOYMENT_CONTRACT_SECRET_MATERIAL_FORBIDDEN",
    ):
        validate_contract_has_no_secret_material(secret)


def test_historical_day15_selection_file_is_not_the_phase3_contract() -> None:
    historical = DEFAULT_CONTRACT.parents[0] / "day15-deployment-contract.json"

    assert historical.is_file()
    assert historical != DEFAULT_CONTRACT
    assert "frozen Day 15 G10 operator-selection policy" in DEFAULT_DOCUMENT.read_text(
        encoding="utf-8"
    )
