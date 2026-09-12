from __future__ import annotations

import base64
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.day15 import change_set_review as review
from scripts.day15 import run_g10_closure as closure
from scripts.day15.g10_candidate import COMPONENT_KEYS, derive_candidate_digest
from scripts.day15.validate_template import DEFAULT_TEMPLATE, canonical_json, load_template
from tests.day15_g10_receipt_fixture import valid_private_contract, valid_private_receipt

NOW = datetime(2026, 8, 24, 12, 5, tzinfo=UTC)
ROLE_ARN = "arn:aws:iam::" + "1" * 12 + ":role/AIOANonZeroCloudOpsDay15DeploymentRole"
BUCKET = "private-day15-artifacts"
INSTANCE = "i-" + "a" * 17


def _rendered_template() -> dict[str, object]:
    template = copy.deepcopy(load_template(DEFAULT_TEMPLATE))
    template.pop("Transform", None)
    resources = template["Resources"]
    assert isinstance(resources, dict)
    for resource in resources.values():
        if resource.get("Type") == "AWS::Serverless::Function":
            resource["Type"] = "AWS::Lambda::Function"
    return template


def _candidate(rendered_raw: bytes) -> dict[str, object]:
    components = {name: hashlib.sha256(name.encode("utf-8")).hexdigest() for name in COMPONENT_KEYS}
    components["artifact_sha256"] = "a" * 64
    components["lambda_configuration_sha256"] = "b" * 64
    components["rendered_template_sha256"] = hashlib.sha256(rendered_raw).hexdigest()
    source_commit = "c" * 40
    digest = derive_candidate_digest(
        source_commit=source_commit,
        region=review.EXPECTED_REGION,
        components=components,
    )
    return {
        "candidate_digest": digest,
        "components": {name: components[name] for name in sorted(components)},
        "region": review.EXPECTED_REGION,
        "schema_version": 1,
        "source_commit": source_commit,
    }


def _g10_receipts(
    candidate: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    private_contract = valid_private_contract(candidate)
    observed = valid_private_receipt(candidate, private_contract)
    private = observed.private_mapping()
    public = closure.sanitized_receipt(
        candidate,
        private_contract,
        observed,
        selection_source="PRIVATE_CONTRACT",
    )
    return public, private


def _document(
    template: dict[str, object],
    rendered_raw: bytes,
    candidate: dict[str, object],
) -> dict[str, object]:
    resources = template["Resources"]
    assert isinstance(resources, dict)
    changes = [
        {
            "action": "Add",
            "logical_resource_id": logical_id,
            "replacement": "False",
            "resource_type": resource["Type"],
            "scope": [],
        }
        for logical_id, resource in sorted(resources.items())
    ]
    change_set = {
        "capabilities": ["CAPABILITY_IAM"],
        "changes": changes,
        "execution_status": "AVAILABLE",
        "status": "CREATE_COMPLETE",
    }
    components = candidate["components"]
    assert isinstance(components, dict)
    parameters = {
        "AllowLiveSandboxStop": "false",
        "AppStage": "hackathon",
        "AwsMutationsEnabled": "false",
        "Day15ArtifactBucketName": BUCKET,
        "Day15ArtifactObjectKey": "day15/reviewed/aioa-lambda.zip",
        "DeploymentRegion": review.EXPECTED_REGION,
        "EmergencyExecutionDisabled": "true",
        "JudgeTokenNotAfter": "2026-08-24T13:00:00Z",
        "LambdaArtifactSha256Base64": base64.b64encode(bytes.fromhex("a" * 64)).decode(),
        "LambdaConfigurationSha256": components["lambda_configuration_sha256"],
        "PublicIngressEnabled": "false",
        "SandboxInstanceId": INSTANCE,
    }
    return {
        "candidate_digest": candidate["candidate_digest"],
        "capture_operations": review.CAPTURE_OPERATIONS,
        "captured_at": "2026-08-24T12:04:00Z",
        "change_set": change_set,
        "change_set_digest": review._canonical_sha256(change_set),
        "change_set_id": (
            "arn:aws:cloudformation:eu-central-1:"
            + "1" * 12
            + ":changeSet/day15-reviewed-release/fixture-id"
        ),
        "change_set_name": review.EXPECTED_CHANGE_SET_NAME,
        "change_set_type": "CREATE",
        "deployment_role_arn_sha256": hashlib.sha256(ROLE_ARN.encode()).hexdigest(),
        "parameters": parameters,
        "processed_template_sha256": review._canonical_sha256(template),
        "region": review.EXPECTED_REGION,
        "rendered_template_sha256": hashlib.sha256(rendered_raw).hexdigest(),
        "schema_version": 3,
        "stack_name": review.EXPECTED_STACK_NAME,
    }


def _bundle(
    template: dict[str, object] | None = None,
) -> tuple[
    dict[str, object],
    bytes,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    rendered = _rendered_template() if template is None else template
    raw = (canonical_json(rendered) + "\n").encode()
    candidate = _candidate(raw)
    public, private = _g10_receipts(candidate)
    document = _document(rendered, raw, candidate)
    return rendered, raw, candidate, public, private | {"_document": document}


def _result(
    template: dict[str, object] | None = None,
    mutate_document=None,
) -> dict[str, object]:
    rendered, raw, candidate, public, private_with_document = _bundle(template)
    private = dict(private_with_document)
    document = private.pop("_document")
    assert isinstance(document, dict)
    if mutate_document is not None:
        mutate_document(document)
    return review.review_change_set(
        document,
        rendered,
        rendered_template_raw=raw,
        candidate_descriptor=candidate,
        g10_sanitized_receipt=public,
        g10_private_receipt=private,
        clock=lambda: NOW,
    )


def test_review_passes_exact_initial_candidate_but_never_authorizes_execution() -> None:
    result = _result()

    assert result["status"] == "PASS"
    assert result["predeploy_review_pass"] is True
    assert result["deployment_authorized"] is False
    assert result["aws_calls_performed"] is False
    assert result["public_ingress_enabled"] is False
    assert result["wildcard_write_iam"] is False
    assert len(result["change_set_export_sha256"]) == 64
    assert len(result["change_set_id_sha256"]) == 64
    assert all(value == "PASS" for value in result["checks"].values())


def test_one_change_record_cannot_masquerade_as_complete_initial_change_set() -> None:
    def only_one(document: dict[str, object]) -> None:
        change_set = document["change_set"]
        assert isinstance(change_set, dict)
        change_set["changes"] = change_set["changes"][:1]
        document["change_set_digest"] = review._canonical_sha256(change_set)

    result = _result(mutate_document=only_one)

    assert result["status"] == "FAIL"
    assert "INITIAL_CHANGE_SET_NOT_COMPLETE" in result["reasons"]


def test_wildcard_iam_resource_and_trust_principal_are_rejected() -> None:
    for mutation, expected in (
        ("resource", "IAM_POLICY_DOCUMENTS_NOT_EXACT"),
        ("trust", "IAM_ROLE_TRUST_OR_PROPERTIES_INVALID"),
    ):
        template = _rendered_template()
        role = template["Resources"]["OrchestratorRole"]
        if mutation == "resource":
            role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"][0]["Resource"] = "*"
        else:
            role["Properties"]["AssumeRolePolicyDocument"]["Statement"][0]["Principal"] = {
                "AWS": "*"
            }

        result = _result(template)

        assert result["status"] == "FAIL"
        assert expected in result["reasons"]


@pytest.mark.parametrize(
    "tags",
    (
        [],
        [{"Key": "AIOAProject", "Value": "ForeignProject"}],
        [
            {"Key": "AIOAStage", "Value": "hackathon"},
            {"Key": "AIOAProject", "Value": "NonZeroCloudOps"},
            {"Key": "ManagedBy", "Value": "CloudFormation"},
        ],
    ),
)
def test_iam_role_ownership_tags_are_exact_and_ordered(tags: list[dict[str, str]]) -> None:
    template = _rendered_template()
    template["Resources"]["OrchestratorRole"]["Properties"]["Tags"] = tags

    result = _result(template)

    assert result["status"] == "FAIL"
    assert "IAM_ROLE_TRUST_OR_PROPERTIES_INVALID" in result["reasons"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    (
        (
            lambda document: document.__setitem__("candidate_digest", "f" * 64),
            "CANDIDATE_DIGEST_BINDING_INVALID",
        ),
        (
            lambda document: document.__setitem__("processed_template_sha256", "f" * 64),
            "PROCESSED_TEMPLATE_BINDING_INVALID",
        ),
        (
            lambda document: document["parameters"].__setitem__("PublicIngressEnabled", "true"),
            "CHANGE_SET_PARAMETER_BINDING_INVALID",
        ),
        (
            lambda document: document.__setitem__("change_set_type", "UPDATE"),
            "CHANGE_SET_IDENTITY_INVALID",
        ),
        (
            lambda document: document.__setitem__("capture_operations", ["manual-assertion"]),
            "CHANGE_SET_CAPTURE_OPERATIONS_INVALID",
        ),
        (
            lambda document: document.__setitem__("captured_at", "2026-08-24T11:00:00Z"),
            "CHANGE_SET_CAPTURE_STALE",
        ),
        (
            lambda document: document.__setitem__("change_set_id", "not-an-aws-change-set-arn"),
            "CHANGE_SET_IDENTITY_INVALID",
        ),
    ),
)
def test_candidate_template_parameters_and_identity_are_closed(mutation, reason: str) -> None:
    result = _result(mutate_document=mutation)

    assert result["status"] == "FAIL"
    assert reason in result["reasons"]


def test_dynamodb_and_provisioned_concurrency_drift_are_rejected() -> None:
    table_drift = _rendered_template()
    table_drift["Resources"]["StateTable"]["Properties"]["DeletionProtectionEnabled"] = False
    assert "DYNAMODB_SAFETY_DRIFT" in _result(table_drift)["reasons"]

    concurrency = _rendered_template()
    concurrency["Resources"]["OrchestratorAlias"]["Properties"]["ProvisionedConcurrencyConfig"] = {
        "ProvisionedConcurrentExecutions": 1
    }
    assert "PROVISIONED_CONCURRENCY_FORBIDDEN" in _result(concurrency)["reasons"]


def test_protected_change_set_export_requires_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "change-set.json"
    path.write_text("{}\n", encoding="utf-8")
    path.chmod(0o640)

    with pytest.raises(review.ReviewFailure, match="PROTECTION_INVALID"):
        review._read_protected_document(path, "CHANGE_SET_EXPORT_REQUIRED")


def test_change_set_export_example_is_canonical_closed_and_non_authorizing() -> None:
    path = review.ROOT / "docs" / "operations" / "day15-change-set-export.example.json"
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw)

    assert raw == canonical_json(value) + "\n"
    assert set(value) == review.CHANGE_SET_EXPORT_KEYS
    assert value["schema_version"] == 3
    assert value["capture_operations"] == review.CAPTURE_OPERATIONS


def test_review_implementation_has_no_aws_or_subprocess_execution_surface() -> None:
    source = Path(review.__file__).read_text(encoding="utf-8")
    assert "import boto3" not in source
    assert "import botocore" not in source
    assert "import subprocess" not in source
    assert '"aws_calls_performed": False' in source
