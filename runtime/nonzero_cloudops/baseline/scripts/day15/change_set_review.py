#!/usr/bin/env python3
"""Offline, fail-closed review of an authenticated initial Day 15 change set.

The protected export must bind DescribeChangeSet and processed GetTemplate data to
the exact G10 candidate and private AWS receipt. This tool performs no AWS calls and
never authorizes execution by itself.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.g10_candidate import (  # noqa: E402
    ARTIFACT_PATH,
    COMPONENT_KEYS,
    REGION,
    STACK_NAME,
    CandidateFailure,
    build_candidate_descriptor,
    derive_candidate_digest,
)
from scripts.day15.preflight_region import validate_judge_token_not_after  # noqa: E402
from scripts.day15.run_day15_gate import (  # noqa: E402
    EXPECTED_ASSUME_ROLE_POLICY,
    EXPECTED_OWNERSHIP_TAGS,
    EXPECTED_ROLE_POLICIES,
)
from scripts.day15.run_g10_closure import (  # noqa: E402
    ClosureFailure,
    validate_sanitized_receipt,
)
from scripts.day15.validate_template import (  # noqa: E402
    TemplateFailure,
    canonical_json,
    load_template,
)

EXPECTED_REGION: Final = REGION
EXPECTED_STACK_NAME: Final = STACK_NAME
EXPECTED_CHANGE_SET_NAME: Final = "day15-reviewed-release"
EXPECTED_CAPABILITIES: Final = ["CAPABILITY_IAM"]
MAX_REVIEW_BYTES: Final = 2_000_000
MAX_G10_RECEIPT_AGE: Final = timedelta(hours=1)
MAX_CHANGE_SET_CAPTURE_AGE: Final = timedelta(minutes=15)
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
LOGICAL_ID_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,254}$")
CHANGE_SET_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:cloudformation:(?P<region>[a-z0-9-]+):(?P<account>\d{12}):"
    r"changeSet/(?P<name>[A-Za-z0-9][-A-Za-z0-9]*)/(?P<id>[A-Za-z0-9-]+)$"
)
CAPTURE_OPERATIONS: Final = [
    "cloudformation:DescribeChangeSet",
    "cloudformation:GetTemplate",
]
CHANGE_SET_EXPORT_KEYS: Final = frozenset(
    {
        "candidate_digest",
        "capture_operations",
        "captured_at",
        "change_set",
        "change_set_digest",
        "change_set_id",
        "change_set_name",
        "change_set_type",
        "deployment_role_arn_sha256",
        "parameters",
        "processed_template_sha256",
        "region",
        "rendered_template_sha256",
        "schema_version",
        "stack_name",
    }
)
ALLOWED_RESOURCE_COUNTS: Final = {
    "AWS::CloudWatch::Alarm": 7,
    "AWS::DynamoDB::Table": 1,
    "AWS::IAM::Role": 2,
    "AWS::Lambda::Alias": 2,
    "AWS::Lambda::Function": 2,
    "AWS::Lambda::Permission": 2,
    "AWS::Lambda::Url": 1,
    "AWS::Lambda::Version": 2,
    "AWS::Logs::LogGroup": 2,
    "AWS::SecretsManager::Secret": 1,
}
PARAMETER_NAMES: Final = frozenset(
    {
        "AllowLiveSandboxStop",
        "AppStage",
        "AwsMutationsEnabled",
        "Day15ArtifactBucketName",
        "Day15ArtifactObjectKey",
        "DeploymentRegion",
        "EmergencyExecutionDisabled",
        "JudgeTokenNotAfter",
        "LambdaArtifactSha256Base64",
        "LambdaConfigurationSha256",
        "PublicIngressEnabled",
        "SandboxInstanceId",
    }
)
CHECK_NAMES: Final = (
    "candidate_binding",
    "capture_provenance",
    "change_set_digest",
    "change_set_identity",
    "change_set_state",
    "complete_resource_diff",
    "dynamodb_safety",
    "g10_receipt_binding",
    "iam_boundary",
    "mutation_controls",
    "parameter_binding",
    "processed_template_binding",
    "provisioned_concurrency",
    "public_surface",
    "region",
    "resource_allowlist",
)


class ReviewFailure(RuntimeError):
    def __init__(self, reason: str, *, status: str = "FAIL") -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (canonical_json(value) + "\n").encode("utf-8")


def _canonical_sha256(value: object) -> str:
    return _sha256(_canonical_bytes(value))


def _read_protected_document(path: Path, reason: str) -> dict[str, object]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise ReviewFailure(reason, status="BLOCKED") from error
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > MAX_REVIEW_BYTES
    ):
        raise ReviewFailure(f"{reason}_PROTECTION_INVALID")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewFailure(f"{reason}_INVALID") from error
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise ReviewFailure(f"{reason}_NOT_CANONICAL")
    return value


def _read_public_document(path: Path, reason: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ReviewFailure(reason, status="BLOCKED")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReviewFailure(f"{reason}_INVALID") from error
    if not isinstance(value, dict) or raw != _canonical_bytes(value):
        raise ReviewFailure(f"{reason}_NOT_CANONICAL")
    return value


def _resources(template: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    resources = template.get("Resources")
    if not isinstance(resources, Mapping):
        return {}
    return {
        str(name): resource
        for name, resource in resources.items()
        if isinstance(name, str) and isinstance(resource, Mapping)
    }


def _properties(resource: Mapping[str, object]) -> Mapping[str, object]:
    properties = resource.get("Properties")
    return properties if isinstance(properties, Mapping) else {}


def _walk(value: object) -> tuple[object, ...]:
    found: list[object] = [value]
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_walk(key))
            found.extend(_walk(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk(item))
    return tuple(found)


def _validated_candidate(candidate: object) -> tuple[dict[str, object], str]:
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidate_digest",
        "components",
        "region",
        "schema_version",
        "source_commit",
    }:
        raise ReviewFailure("CANDIDATE_DESCRIPTOR_INVALID")
    components = candidate.get("components")
    source_commit = candidate.get("source_commit")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("region") != EXPECTED_REGION
        or not isinstance(source_commit, str)
        or not isinstance(components, Mapping)
        or set(components) != COMPONENT_KEYS
        or any(
            not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None
            for value in components.values()
        )
    ):
        raise ReviewFailure("CANDIDATE_DESCRIPTOR_INVALID")
    values = {str(name): str(value) for name, value in components.items()}
    try:
        digest = derive_candidate_digest(
            source_commit=source_commit,
            region=EXPECTED_REGION,
            components=values,
        )
    except CandidateFailure as error:
        raise ReviewFailure("CANDIDATE_DESCRIPTOR_INVALID") from error
    if candidate.get("candidate_digest") != digest:
        raise ReviewFailure("CANDIDATE_DIGEST_BINDING_INVALID")
    return dict(candidate), digest


def _resource_reasons(
    template: Mapping[str, object],
    change_set: Mapping[str, object] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    resources = _resources(template)
    allowlist_reasons: list[str] = []
    diff_reasons: list[str] = []
    if (
        dict(Counter(str(item.get("Type")) for item in resources.values()))
        != ALLOWED_RESOURCE_COUNTS
    ):
        allowlist_reasons.append("UNEXPECTED_RESOURCE_SET")
    changes = change_set.get("changes") if change_set is not None else None
    if not isinstance(changes, list):
        return tuple(allowlist_reasons), ("CHANGE_SET_RESOURCE_CHANGES_REQUIRED",)
    seen: set[str] = set()
    for change in changes:
        if not isinstance(change, Mapping) or set(change) != {
            "action",
            "logical_resource_id",
            "replacement",
            "resource_type",
            "scope",
        }:
            diff_reasons.append("CHANGE_SET_RESOURCE_CHANGE_INVALID")
            continue
        logical_id = change.get("logical_resource_id")
        resource_type = change.get("resource_type")
        if (
            change.get("action") != "Add"
            or change.get("replacement") not in {"False", "NotApplicable"}
            or change.get("scope") != []
            or not isinstance(logical_id, str)
            or LOGICAL_ID_PATTERN.fullmatch(logical_id) is None
            or logical_id in seen
            or logical_id not in resources
            or resources[logical_id].get("Type") != resource_type
        ):
            diff_reasons.append("INITIAL_CHANGE_SET_DIFF_INVALID")
        else:
            seen.add(logical_id)
    if seen != set(resources) or len(changes) != len(resources):
        diff_reasons.append("INITIAL_CHANGE_SET_NOT_COMPLETE")
    return tuple(allowlist_reasons), tuple(diff_reasons)


def _public_surface_reasons(template: Mapping[str, object]) -> tuple[str, ...]:
    resources = _resources(template)
    urls = [item for item in resources.values() if item.get("Type") == "AWS::Lambda::Url"]
    permissions = [
        item for item in resources.values() if item.get("Type") == "AWS::Lambda::Permission"
    ]
    reasons: list[str] = []
    if len(urls) != 1 or len(permissions) != 2:
        return ("EXACT_PUBLIC_SURFACE_REQUIRED",)
    url = urls[0]
    if url.get("Condition") != "PublicIngressEnabledCondition" or _properties(url) != {
        "AuthType": "NONE",
        "InvokeMode": "BUFFERED",
        "Qualifier": "live",
        "TargetFunctionArn": {"Ref": "OrchestratorFunction"},
    }:
        reasons.append("FUNCTION_URL_BOUNDARY_INVALID")
    properties = [_properties(item) for item in permissions]
    by_action = {str(item.get("Action")): item for item in properties}
    if (
        any(item.get("Condition") != "PublicIngressEnabledCondition" for item in permissions)
        or {item.get("Action") for item in properties}
        != {"lambda:InvokeFunction", "lambda:InvokeFunctionUrl"}
        or any(item.get("Principal") != "*" for item in properties)
        or any(item.get("FunctionName") != {"Ref": "OrchestratorAlias"} for item in properties)
        or by_action.get("lambda:InvokeFunctionUrl", {}).get("FunctionUrlAuthType") != "NONE"
        or by_action.get("lambda:InvokeFunction", {}).get("InvokedViaFunctionUrl") is not True
    ):
        reasons.append("PUBLIC_PERMISSION_BOUNDARY_INVALID")
    return tuple(reasons)


def _iam_reasons(template: Mapping[str, object]) -> tuple[str, ...]:
    roles = {
        name: item
        for name, item in _resources(template).items()
        if item.get("Type") == "AWS::IAM::Role"
    }
    if set(roles) != set(EXPECTED_ROLE_POLICIES):
        return ("EXACT_EXECUTION_ROLE_SET_REQUIRED",)
    reasons: list[str] = []
    for name, expected_policies in EXPECTED_ROLE_POLICIES.items():
        properties = _properties(roles[name])
        if (
            set(properties) != {"AssumeRolePolicyDocument", "Policies", "Tags"}
            or properties.get("AssumeRolePolicyDocument") != EXPECTED_ASSUME_ROLE_POLICY
            or properties.get("Tags") != EXPECTED_OWNERSHIP_TAGS
        ):
            reasons.append("IAM_ROLE_TRUST_OR_PROPERTIES_INVALID")
            continue
        policies = properties.get("Policies")
        if not isinstance(policies, list):
            reasons.append("IAM_INLINE_POLICIES_INVALID")
            continue
        observed: dict[str, object] = {}
        for policy in policies:
            if not isinstance(policy, Mapping) or set(policy) != {"PolicyDocument", "PolicyName"}:
                reasons.append("IAM_INLINE_POLICIES_INVALID")
                continue
            policy_name = policy.get("PolicyName")
            if not isinstance(policy_name, str) or policy_name in observed:
                reasons.append("IAM_INLINE_POLICIES_INVALID")
                continue
            observed[policy_name] = policy.get("PolicyDocument")
        expected = {
            policy_name: {"Statement": statements, "Version": "2012-10-17"}
            for policy_name, statements in expected_policies.items()
        }
        if observed != expected:
            reasons.append("IAM_POLICY_DOCUMENTS_NOT_EXACT")
    if any(
        isinstance(item, str)
        and "*" in item
        and any(marker in item.casefold() for marker in ("ec2:", "bedrock:", "lambda:"))
        for item in _walk(roles)
    ):
        reasons.append("WILDCARD_IAM_ACTION_FORBIDDEN")
    return tuple(reasons)


def _mutation_reasons(template: Mapping[str, object]) -> tuple[str, ...]:
    parameters = template.get("Parameters")
    expected_parameters = {
        "AllowLiveSandboxStop": {"AllowedValues": ["false"], "Default": "false", "Type": "String"},
        "AwsMutationsEnabled": {"AllowedValues": ["false"], "Default": "false", "Type": "String"},
        "EmergencyExecutionDisabled": {
            "AllowedValues": ["true"],
            "Default": "true",
            "Type": "String",
        },
    }
    reasons: list[str] = []
    if not isinstance(parameters, Mapping) or any(
        parameters.get(name) != value for name, value in expected_parameters.items()
    ):
        reasons.append("MUTATION_PARAMETER_BOUNDARY_INVALID")
    expected_literals = {
        "AIOA_ALLOW_LIVE_SANDBOX_STOP": "false",
        "AIOA_EMERGENCY_EXECUTION_DISABLED": "true",
        "AWS_MUTATIONS_ENABLED": "false",
    }
    expected_refs = {
        "AIOA_ALLOW_LIVE_SANDBOX_STOP": {"Ref": "AllowLiveSandboxStop"},
        "AIOA_EMERGENCY_EXECUTION_DISABLED": {"Ref": "EmergencyExecutionDisabled"},
        "AWS_MUTATIONS_ENABLED": {"Ref": "AwsMutationsEnabled"},
    }
    for name, resource in _resources(template).items():
        if resource.get("Type") != "AWS::Lambda::Function":
            continue
        environment = _properties(resource).get("Environment")
        variables = environment.get("Variables") if isinstance(environment, Mapping) else None
        expected = expected_literals if "orchestrator" in name.casefold() else expected_refs
        if not isinstance(variables, Mapping) or any(
            variables.get(key) != value for key, value in expected.items()
        ):
            reasons.append("MUTATION_ENVIRONMENT_BOUNDARY_INVALID")
    return tuple(reasons)


def _dynamodb_reasons(template: Mapping[str, object]) -> tuple[str, ...]:
    tables = [
        item for item in _resources(template).values() if item.get("Type") == "AWS::DynamoDB::Table"
    ]
    if len(tables) != 1:
        return ("EXACT_RETAINED_STATE_TABLE_REQUIRED",)
    table = tables[0]
    properties = _properties(table)
    if (
        table.get("DeletionPolicy") != "Retain"
        or table.get("UpdateReplacePolicy") != "Retain"
        or properties.get("BillingMode") != "PAY_PER_REQUEST"
        or properties.get("DeletionProtectionEnabled") is not True
        or properties.get("PointInTimeRecoverySpecification")
        != {"PointInTimeRecoveryEnabled": True}
        or properties.get("SSESpecification") != {"SSEEnabled": True}
    ):
        return ("DYNAMODB_SAFETY_DRIFT",)
    return ()


def _region_reasons(
    document: Mapping[str, object], template: Mapping[str, object]
) -> tuple[str, ...]:
    parameters = template.get("Parameters")
    rules = template.get("Rules")
    expected_rule = {
        "Assertions": [
            {
                "Assert": {"Fn::Equals": [{"Ref": "AWS::Region"}, {"Ref": "DeploymentRegion"}]},
                "AssertDescription": "The CloudFormation region must match DeploymentRegion",
            },
            {
                "Assert": {"Fn::Equals": [{"Ref": "AWS::Region"}, EXPECTED_REGION]},
                "AssertDescription": "The CloudFormation region must be eu-central-1",
            },
        ]
    }
    region_parameter = (
        parameters.get("DeploymentRegion") if isinstance(parameters, Mapping) else None
    )
    if (
        document.get("region") != EXPECTED_REGION
        or not isinstance(region_parameter, Mapping)
        or region_parameter.get("AllowedValues") != [EXPECTED_REGION]
        or not isinstance(rules, Mapping)
        or rules.get("DeploymentRegionIsFrozen") != expected_rule
    ):
        return ("DEPLOYMENT_REGION_INVALID",)
    return ()


def _parameter_reasons(
    parameters: object,
    *,
    candidate: Mapping[str, object],
    private_receipt: Mapping[str, object],
    clock: Callable[[], datetime],
) -> tuple[str, ...]:
    if not isinstance(parameters, Mapping) or set(parameters) != PARAMETER_NAMES:
        return ("CHANGE_SET_PARAMETERS_INVALID",)
    candidate_components = candidate["components"]
    identifiers = private_receipt.get("identifiers")
    private_contract = private_receipt.get("private_contract")
    packaging = private_contract.get("packaging") if isinstance(private_contract, Mapping) else None
    if (
        not isinstance(candidate_components, Mapping)
        or not isinstance(identifiers, Mapping)
        or not isinstance(packaging, Mapping)
    ):
        return ("G10_PRIVATE_BINDINGS_INVALID",)
    artifact_sha = candidate_components.get("artifact_sha256")
    if not isinstance(artifact_sha, str):
        return ("CANDIDATE_ARTIFACT_BINDING_INVALID",)
    expected = {
        "AllowLiveSandboxStop": "false",
        "AppStage": "hackathon",
        "AwsMutationsEnabled": "false",
        "Day15ArtifactBucketName": identifiers.get("artifact_bucket"),
        "Day15ArtifactObjectKey": packaging.get("artifact_path"),
        "DeploymentRegion": EXPECTED_REGION,
        "EmergencyExecutionDisabled": "true",
        "LambdaArtifactSha256Base64": base64.b64encode(bytes.fromhex(artifact_sha)).decode("ascii"),
        "LambdaConfigurationSha256": candidate_components.get("lambda_configuration_sha256"),
        "PublicIngressEnabled": "false",
        "SandboxInstanceId": identifiers.get("sandbox_instance_id"),
    }
    reasons: list[str] = []
    if packaging.get("artifact_path") != ARTIFACT_PATH or any(
        parameters.get(name) != value for name, value in expected.items()
    ):
        reasons.append("CHANGE_SET_PARAMETER_BINDING_INVALID")
    expiry = validate_judge_token_not_after(parameters.get("JudgeTokenNotAfter"), clock=clock)
    if expiry.status != "PASS":
        reasons.extend(expiry.reasons)
    return tuple(reasons)


def review_change_set(
    document: object,
    rendered_template: object,
    *,
    rendered_template_raw: bytes,
    candidate_descriptor: Mapping[str, object],
    g10_sanitized_receipt: Mapping[str, object],
    g10_private_receipt: Mapping[str, object],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    """Return sanitized review evidence, never deployment authorization."""

    candidate, candidate_digest = _validated_candidate(candidate_descriptor)
    checks: dict[str, list[str]] = {name: [] for name in CHECK_NAMES}
    try:
        validate_sanitized_receipt(
            g10_sanitized_receipt,
            expected_candidate=candidate,
            private_receipt=g10_private_receipt,
            validation_time=clock(),
        )
    except ClosureFailure as error:
        checks["g10_receipt_binding"].append(error.reason)
    if (
        g10_sanitized_receipt.get("status") != "PASS"
        or g10_sanitized_receipt.get("ready_for_change_set") is not True
    ):
        checks["g10_receipt_binding"].append("G10_PASS_RECEIPT_REQUIRED")
    observed_at = g10_private_receipt.get("observed_at")
    try:
        observed_time = datetime.strptime(str(observed_at), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        now = clock().astimezone(UTC)
    except (ValueError, TypeError):
        checks["g10_receipt_binding"].append("G10_RECEIPT_TIME_INVALID")
    else:
        age = now - observed_time
        if age < timedelta(minutes=-1) or age > MAX_G10_RECEIPT_AGE:
            checks["g10_receipt_binding"].append("G10_RECEIPT_STALE")

    document_sha256 = _canonical_sha256(document) if isinstance(document, Mapping) else None
    if not isinstance(document, Mapping) or set(document) != CHANGE_SET_EXPORT_KEYS:
        checks["change_set_state"].append("CHANGE_SET_EXPORT_SCHEMA_INVALID")
        document = {}
    if not isinstance(rendered_template, Mapping) or "Transform" in rendered_template:
        checks["processed_template_binding"].append("RENDERED_TEMPLATE_REQUIRED")
        rendered_template = {}

    if document.get("candidate_digest") != candidate_digest:
        checks["candidate_binding"].append("CANDIDATE_DIGEST_BINDING_INVALID")
    candidate_components = candidate.get("components")
    expected_rendered_sha = (
        candidate_components.get("rendered_template_sha256")
        if isinstance(candidate_components, Mapping)
        else None
    )
    if (
        _sha256(rendered_template_raw) != expected_rendered_sha
        or document.get("rendered_template_sha256") != expected_rendered_sha
        or document.get("processed_template_sha256") != _canonical_sha256(rendered_template)
    ):
        checks["processed_template_binding"].append("PROCESSED_TEMPLATE_BINDING_INVALID")

    change_set = document.get("change_set")
    change_set_model = change_set if isinstance(change_set, Mapping) else None
    if change_set_model is None or document.get("change_set_digest") != _canonical_sha256(
        change_set_model
    ):
        checks["change_set_digest"].append("CHANGE_SET_DIGEST_BINDING_INVALID")
    if (
        document.get("schema_version") != 3
        or change_set_model is None
        or set(change_set_model) != {"capabilities", "changes", "execution_status", "status"}
        or change_set_model.get("capabilities") != EXPECTED_CAPABILITIES
        or change_set_model.get("status") != "CREATE_COMPLETE"
        or change_set_model.get("execution_status") != "AVAILABLE"
    ):
        checks["change_set_state"].append("CHANGE_SET_NOT_REVIEWABLE")
    identifiers = g10_private_receipt.get("identifiers")
    role_arn = identifiers.get("deployment_role_arn") if isinstance(identifiers, Mapping) else None
    change_set_id = document.get("change_set_id")
    change_set_match = (
        CHANGE_SET_ARN_PATTERN.fullmatch(change_set_id) if isinstance(change_set_id, str) else None
    )
    role_account = role_arn.split(":", 5)[4] if isinstance(role_arn, str) else None
    if (
        document.get("stack_name") != EXPECTED_STACK_NAME
        or document.get("change_set_name") != EXPECTED_CHANGE_SET_NAME
        or document.get("change_set_type") != "CREATE"
        or not isinstance(role_arn, str)
        or document.get("deployment_role_arn_sha256") != _sha256(role_arn.encode("utf-8"))
        or change_set_match is None
        or change_set_match.group("region") != EXPECTED_REGION
        or change_set_match.group("account") != role_account
        or change_set_match.group("name") != EXPECTED_CHANGE_SET_NAME
    ):
        checks["change_set_identity"].append("CHANGE_SET_IDENTITY_INVALID")
    captured_at = document.get("captured_at")
    try:
        captured_time = datetime.strptime(str(captured_at), "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=UTC
        )
        capture_age = clock().astimezone(UTC) - captured_time
    except (ValueError, TypeError):
        checks["capture_provenance"].append("CHANGE_SET_CAPTURE_TIME_INVALID")
    else:
        if capture_age < timedelta(minutes=-1) or capture_age > MAX_CHANGE_SET_CAPTURE_AGE:
            checks["capture_provenance"].append("CHANGE_SET_CAPTURE_STALE")
    if document.get("capture_operations") != CAPTURE_OPERATIONS:
        checks["capture_provenance"].append("CHANGE_SET_CAPTURE_OPERATIONS_INVALID")

    resource_reasons, diff_reasons = _resource_reasons(rendered_template, change_set_model)
    checks["resource_allowlist"].extend(resource_reasons)
    checks["complete_resource_diff"].extend(diff_reasons)
    checks["public_surface"].extend(_public_surface_reasons(rendered_template))
    checks["iam_boundary"].extend(_iam_reasons(rendered_template))
    checks["mutation_controls"].extend(_mutation_reasons(rendered_template))
    checks["dynamodb_safety"].extend(_dynamodb_reasons(rendered_template))
    checks["region"].extend(_region_reasons(document, rendered_template))
    checks["parameter_binding"].extend(
        _parameter_reasons(
            document.get("parameters"),
            candidate=candidate,
            private_receipt=g10_private_receipt,
            clock=clock,
        )
    )
    if any(
        isinstance(item, str) and "provisionedconcurrency" in item.casefold()
        for item in _walk(rendered_template)
    ):
        checks["provisioned_concurrency"].append("PROVISIONED_CONCURRENCY_FORBIDDEN")

    reasons = sorted({reason for values in checks.values() for reason in values})
    status = "PASS" if not reasons else "FAIL"
    changes = change_set_model.get("changes") if change_set_model is not None else None
    resource_types = (
        sorted({str(item.get("resource_type")) for item in changes if isinstance(item, Mapping)})
        if isinstance(changes, list)
        else []
    )
    return {
        "aws_calls_performed": False,
        "candidate_digest": candidate_digest,
        "change_set_digest": (
            _canonical_sha256(change_set_model) if change_set_model is not None else None
        ),
        "change_set_export_sha256": document_sha256,
        "change_set_id_sha256": (
            _sha256(change_set_id.encode("utf-8")) if isinstance(change_set_id, str) else None
        ),
        "checks": {name: "PASS" if not checks[name] else "FAIL" for name in CHECK_NAMES},
        "deployment_authorized": False,
        "parameter_names": sorted(PARAMETER_NAMES),
        "predeploy_review_pass": status == "PASS",
        "public_ingress_enabled": False,
        "reasons": reasons,
        "region": EXPECTED_REGION,
        "resource_change_count": len(changes) if isinstance(changes, list) else 0,
        "resource_types": resource_types,
        "sanitized": True,
        "schema_version": 3,
        "status": status,
        "wildcard_write_iam": False if not checks["iam_boundary"] else None,
    }


def _blocked_payload(reason: str, *, status: str = "BLOCKED") -> dict[str, object]:
    return {
        "aws_calls_performed": False,
        "candidate_digest": None,
        "change_set_digest": None,
        "change_set_export_sha256": None,
        "change_set_id_sha256": None,
        "checks": {name: status for name in CHECK_NAMES},
        "deployment_authorized": False,
        "parameter_names": sorted(PARAMETER_NAMES),
        "predeploy_review_pass": False,
        "public_ingress_enabled": False,
        "reasons": [reason],
        "region": EXPECTED_REGION,
        "resource_change_count": 0,
        "resource_types": [],
        "sanitized": True,
        "schema_version": 3,
        "status": status,
        "wildcard_write_iam": None,
    }


def _atomic_write(path: Path, payload: Mapping[str, object]) -> None:
    if path.is_symlink():
        raise ReviewFailure("CHANGE_SET_REVIEW_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix="day15-change-set-review-",
        suffix=".tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        handle.write(_canonical_bytes(payload))
    try:
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--change-set-export", required=True, type=Path)
    parser.add_argument("--rendered-template", required=True, type=Path)
    parser.add_argument("--g10-sanitized-receipt", required=True, type=Path)
    parser.add_argument("--g10-private-receipt", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        document = _read_protected_document(args.change_set_export, "CHANGE_SET_EXPORT_REQUIRED")
        private_receipt = _read_protected_document(
            args.g10_private_receipt, "G10_PRIVATE_RECEIPT_REQUIRED"
        )
        public_receipt = _read_public_document(
            args.g10_sanitized_receipt, "G10_SANITIZED_RECEIPT_REQUIRED"
        )
        rendered_raw = args.rendered_template.read_bytes()
        rendered = load_template(args.rendered_template)
        candidate = build_candidate_descriptor()
        payload = review_change_set(
            document,
            rendered,
            rendered_template_raw=rendered_raw,
            candidate_descriptor=candidate,
            g10_sanitized_receipt=public_receipt,
            g10_private_receipt=private_receipt,
        )
        if args.output is not None:
            _atomic_write(args.output, payload)
    except ReviewFailure as error:
        payload = _blocked_payload(error.reason, status=error.status)
    except (OSError, CandidateFailure, TemplateFailure) as error:
        reason = error.reason if hasattr(error, "reason") else "REVIEW_INPUT_UNAVAILABLE"
        payload = _blocked_payload(str(reason), status="FAIL")
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload["reasons"]) or "-"
        print(f"DAY15_CHANGE_SET_REVIEW {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
