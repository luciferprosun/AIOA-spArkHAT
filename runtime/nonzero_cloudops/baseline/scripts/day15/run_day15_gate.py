#!/usr/bin/env python3
"""Run the deterministic, local-only Day 15 deployment-readiness gate."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.build_lambda_artifact import (  # noqa: E402
    DEFAULT_ARTIFACT,
    DEFAULT_LOCK,
    DEFAULT_MANIFEST,
    DEFAULT_SCAN_REPORT,
    ArtifactFailure,
    BuildPaths,
    discover_lambda_handlers,
    inspect_archive,
    revalidate_artifact,
    validate_repository_inputs,
    validate_runtime_lock,
)
from scripts.day15.external_preflight_attestation import (  # noqa: E402
    AttestationFailure,
    read_attestation_key,
    validate_receipt,
)
from scripts.day15.g10_candidate import (  # noqa: E402
    CandidateFailure,
    build_candidate_descriptor,
)
from scripts.day15.preflight_region import (  # noqa: E402
    CheckResult,
    combine_status,
    validate_judge_token_not_after,
    validate_region,
)
from scripts.day15.render_template import (  # noqa: E402
    RenderFailure,
    verify_rendered_template,
)
from scripts.day15.run_g10_closure import (  # noqa: E402
    ClosureFailure,
    validate_sanitized_receipt,
)
from scripts.day15.validate_template import (  # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateFailure,
    canonical_json,
    compare_lambda_configuration_sha256,
    has_sam_transform,
    load_template,
    resources_of_type,
)

DEFAULT_TOOLCHAIN: Final = ROOT / "requirements" / "day15-toolchain.json"
DEFAULT_DEPLOYMENT_CONTRACT: Final = ROOT / "requirements" / "day15-deployment-contract.json"
DEFAULT_RECEIPT: Final = ROOT / "dist" / "day15" / "external-preflight.json"
DEFAULT_G10_SANITIZED_RECEIPT: Final = ROOT / ".aioa-private" / "day15-g10-readiness.json"
AWS_CLIENTS_SOURCE: Final = ROOT / "src" / "aioa_cloudops_agent" / "aws_clients.py"
RUNTIME_SOURCE_ROOT: Final = ROOT / "src"
JUDGE_ROUTER_SOURCES: Final = (
    ROOT / "src" / "aioa_cloudops_agent" / "judge" / "application.py",
    ROOT / "src" / "aioa_cloudops_agent" / "judge" / "lambda_handler.py",
)
JUDGE_RUNTIME_SOURCE: Final = ROOT / "src" / "aioa_cloudops_agent" / "judge" / "runtime.py"
JUDGE_CONFIG_SOURCE: Final = ROOT / "src" / "aioa_cloudops_agent" / "deployment" / "config.py"
APPROVAL_RESUME_SOURCE: Final = ROOT / "src" / "aioa_cloudops_agent" / "deployment" / "resume.py"
RUNTIME_PROOF_CONTRACTS: Final = (
    (
        ROOT / "tests" / "unit" / "test_day15_judge_http.py",
        (
            "test_health_and_root_create_no_clients_and_expose_hardened_same_origin_ui",
            "test_unknown_approval_mutation_and_wrong_method_routes_fail_before_services",
            "test_wrong_token_denies_before_quota_agent_and_status",
        ),
    ),
    (
        ROOT / "tests" / "unit" / "test_day15_judge_runtime.py",
        (
            "test_each_investigation_builds_fresh_snapshot_session_agent_and_server_budget",
            "test_default_session_factory_is_snapshot_manager_with_no_agent_reuse",
        ),
    ),
    (
        ROOT / "tests" / "unit" / "test_day15_runtime_contracts.py",
        (
            "test_server_owned_judge_budget_is_exact_and_fresh",
            "test_judge_schema_rejects_caller_authority_and_budget_fields",
        ),
    ),
    (
        ROOT / "tests" / "integration" / "test_durable_hitl_approval_flow.py",
        ("test_fresh_process_restores_native_interrupt_with_trusted_one_time_freshness",),
    ),
)
ROLLBACK_RUNBOOK: Final = ROOT / "docs" / "operations" / "day15-deployment-gate.md"
ROLLBACK_TOOL: Final = ROOT / "scripts" / "day15" / "alias_rollback.py"
ROLLBACK_PROOF: Final = ROOT / "tests" / "unit" / "test_day15_gate.py"
ROLLBACK_PROOF_NAMES: Final = (
    "test_alias_rollback_plan_is_read_first_stable_and_alias_only",
    "test_alias_rollback_requires_reviewed_hash_then_reconciles_both_aliases",
    "test_alias_partial_update_reports_explicit_reconciliation",
)
STATUS_VALUES: Final = frozenset({"PASS", "FAIL", "PARTIAL", "BLOCKED"})
SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
ABSOLUTE_PATH_PATTERN: Final = re.compile(r"(?:^|\s)(?:/home/|/tmp/|[A-Za-z]:\\Users\\)")
TIMESTAMP_KEY_PATTERN: Final = re.compile(r"(?:^|_)(?:time|timestamp|created_at|built_at)(?:$|_)")
PINNED_AWS_CLI_VERSION: Final = "2.36.11"
AWS_CLI_VERSION_PATTERN: Final = re.compile(r"^aws-cli/([^\s]+)(?:\s|$)")
DEPLOYMENT_CONTRACT_FIXED: Final = {
    "artifact_bucket_controls": {
        "encryption_at_rest_required": True,
        "lifecycle_expiration_days_max": 3,
        "noncurrent_version_expiration_days_max": 3,
        "ownership_controls_required": True,
        "public_access_block": {
            "block_public_acls": True,
            "block_public_policy": True,
            "ignore_public_acls": True,
            "restrict_public_buckets": True,
        },
        "tls_only_required": True,
        "versioning_required": True,
    },
    "artifact_path": "day15/reviewed/aioa-lambda.zip",
    "artifact_prefix": "day15/reviewed/",
    "capabilities": ["CAPABILITY_IAM"],
    "change_set_name": "day15-reviewed-release",
    "deployment_profile": "aioa-day15-deployer",
    "deployment_role_name": "AIOANonZeroCloudOpsDay15DeploymentRole",
    "region": "eu-central-1",
    "schema_version": 2,
    "stack_name": "aioa-nonzero-cloudops-day15",
}
DEPLOYMENT_CONTRACT_HASH_FIELDS: Final = frozenset(
    {
        "artifact_bucket_sha256",
        "deployment_role_arn_sha256",
    }
)
BUCKET_CONTROL_CHECKS: Final = frozenset(
    {
        "artifact_bucket_encryption_ready",
        "artifact_bucket_lifecycle_ready",
        "artifact_bucket_ownership_controls_ready",
        "artifact_bucket_public_access_block_ready",
        "artifact_bucket_tls_only_ready",
        "artifact_bucket_versioning_ready",
    }
)
EXPECTED_ASSUME_ROLE_POLICY: Final = {
    "Statement": [
        {
            "Action": ["sts:AssumeRole"],
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
        }
    ],
    "Version": "2012-10-17",
}
EXPECTED_OWNERSHIP_TAGS: Final = [
    {"Key": "AIOAProject", "Value": "NonZeroCloudOps"},
    {"Key": "AIOAStage", "Value": "hackathon"},
    {"Key": "ManagedBy", "Value": "CloudFormation"},
]
EXPECTED_ROLE_POLICIES: Final = {
    "RemediationExecutorRole": {
        "BoundedXRayDelivery": [
            {
                "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                "Effect": "Allow",
                "Resource": "*",
            }
        ],
        "FreshSandboxScopeRead": [
            {
                "Action": ["ec2:DescribeInstances"],
                "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}},
                "Effect": "Allow",
                "Resource": "*",
            }
        ],
        "RemediationLogDelivery": [
            {
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Effect": "Allow",
                "Resource": {
                    "Fn::Sub": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:"
                    "log-group:/aws/lambda/${AWS::StackName}-remediation-executor:*"
                },
            }
        ],
        "StopConfiguredTaggedSandboxOnly": [
            {
                "Action": ["ec2:StopInstances"],
                "Condition": {
                    "StringEquals": {
                        "aws:RequestedRegion": "eu-central-1",
                        "aws:ResourceTag/AIOACloudOpsSandbox": "true",
                    }
                },
                "Effect": "Allow",
                "Resource": {
                    "Fn::Sub": "arn:${AWS::Partition}:ec2:${AWS::Region}:${AWS::AccountId}:"
                    "instance/${SandboxInstanceId}"
                },
            }
        ],
    },
    "OrchestratorRole": {
        "BoundedXRayDelivery": [
            {
                "Action": ["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                "Effect": "Allow",
                "Resource": "*",
            }
        ],
        "DurableItemOnlyState": [
            {
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Effect": "Allow",
                "Resource": {"Fn::GetAtt": ["StateTable", "Arn"]},
            }
        ],
        "InvokeNovaTwoLiteEuProfileOnly": [
            {
                "Action": ["bedrock:InvokeModelWithResponseStream"],
                "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}},
                "Effect": "Allow",
                "Resource": {
                    "Fn::Sub": "arn:${AWS::Partition}:bedrock:${AWS::Region}:"
                    "${AWS::AccountId}:inference-profile/eu.amazon.nova-2-lite-v1:0"
                },
                "Sid": "InvokeExactEuInferenceProfile",
            },
            {
                "Action": ["bedrock:InvokeModelWithResponseStream"],
                "Condition": {
                    "StringEquals": {
                        "aws:RequestedRegion": "eu-central-1",
                        "bedrock:InferenceProfileArn": {
                            "Fn::Sub": "arn:${AWS::Partition}:bedrock:${AWS::Region}:"
                            "${AWS::AccountId}:inference-profile/"
                            "eu.amazon.nova-2-lite-v1:0"
                        },
                    }
                },
                "Effect": "Allow",
                "Resource": [
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-central-1::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-north-1::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-south-1::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-south-2::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-west-1::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                    {
                        "Fn::Sub": "arn:${AWS::Partition}:bedrock:eu-west-3::"
                        "foundation-model/amazon.nova-2-lite-v1:0"
                    },
                ],
                "Sid": "InvokeProfileDestinationModelsOnly",
            },
        ],
        "InvokePrivateExecutorAliasOnly": [
            {
                "Action": ["lambda:InvokeFunction"],
                "Effect": "Allow",
                "Resource": {"Ref": "RemediationExecutorAlias"},
            }
        ],
        "OrchestratorLogDelivery": [
            {
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Effect": "Allow",
                "Resource": {
                    "Fn::Sub": "arn:${AWS::Partition}:logs:${AWS::Region}:${AWS::AccountId}:"
                    "log-group:/aws/lambda/${AWS::StackName}-orchestrator:*"
                },
            }
        ],
        "ReadConfiguredSandboxEvidence": [
            {
                "Action": ["ec2:DescribeInstances", "cloudwatch:GetMetricStatistics"],
                "Condition": {"StringEquals": {"aws:RequestedRegion": "eu-central-1"}},
                "Effect": "Allow",
                "Resource": "*",
            }
        ],
        "ReadDedicatedJudgeSecretOnly": [
            {
                "Action": ["secretsmanager:GetSecretValue"],
                "Effect": "Allow",
                "Resource": {"Ref": "JudgeTokenSecret"},
            }
        ],
    },
}
FORBIDDEN_COST_RESOURCE_TYPES: Final = frozenset(
    {
        "AWS::ApiGateway::RestApi",
        "AWS::Budgets::Budget",
        "AWS::EC2::NatGateway",
        "AWS::ECS::Cluster",
        "AWS::ECS::Service",
        "AWS::EKS::Cluster",
        "AWS::ElastiCache::CacheCluster",
        "AWS::ElastiCache::ReplicationGroup",
        "AWS::Events::Rule",
        "AWS::OpenSearchService::Domain",
        "AWS::RDS::DBCluster",
        "AWS::RDS::DBInstance",
        "AWS::SQS::Queue",
        "AWS::Scheduler::Schedule",
        "AWS::StepFunctions::StateMachine",
    }
)
FORBIDDEN_COST_RESOURCE_PREFIXES: Final = (
    "AWS::ApiGateway::",
    "AWS::ApiGatewayV2::",
    "AWS::Budgets::",
    "AWS::EC2::NatGateway",
    "AWS::ECS::",
    "AWS::EKS::",
    "AWS::ElastiCache::",
    "AWS::Elasticsearch::",
    "AWS::Events::",
    "AWS::MemoryDB::",
    "AWS::OpenSearchService::",
    "AWS::OpenSearchServerless::",
    "AWS::RDS::",
    "AWS::SQS::",
    "AWS::Scheduler::",
    "AWS::StepFunctions::",
)


@dataclass(frozen=True, slots=True)
class GateDefinition:
    gate_id: str
    title: str


@dataclass(frozen=True, slots=True)
class GateResult:
    gate_id: str
    title: str
    status: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in STATUS_VALUES:
            raise ValueError("invalid Day 15 gate status")
        if tuple(sorted(set(self.reasons))) != self.reasons:
            raise ValueError("gate reasons must be sorted and unique")

    def as_dict(self) -> dict[str, object]:
        return {
            "gate_id": self.gate_id,
            "reasons": list(self.reasons),
            "status": self.status,
            "title": self.title,
        }


GATES: Final = (
    GateDefinition("D15-G01", "bounded-runtime-composition"),
    GateDefinition("D15-G02", "least-privilege-rendered-iam"),
    GateDefinition("D15-G03", "owned-sdk-retry-bounds"),
    GateDefinition("D15-G04", "reproducible-scanned-lambda-artifact"),
    GateDefinition("D15-G05", "durable-state-retention"),
    GateDefinition("D15-G06", "eu-central-1-preflight"),
    GateDefinition("D15-G07", "immutable-versions-aliases-rollback"),
    GateDefinition("D15-G08", "bounded-logs-telemetry-cost-controls"),
    GateDefinition("D15-G09", "single-read-only-public-surface"),
    GateDefinition("D15-G10", "external-prerequisites-and-token-window"),
)


@dataclass(frozen=True, slots=True)
class GateContext:
    template: dict[str, object]
    template_path: Path
    rendered_template: dict[str, object] | None
    rendered_template_path: Path | None
    template_has_sam: bool
    artifact: Path
    lock: Path
    manifest: Path
    scan_report: Path
    toolchain: Path
    external_receipt: Path
    external_attestation_key: Path | None
    region: str | None
    judge_token_not_after: str | None
    lambda_configuration_sha256: str | None
    clock: Callable[[], datetime]
    deployment_contract: Path = DEFAULT_DEPLOYMENT_CONTRACT
    g10_sanitized_receipt: Path | None = None
    g10_private_receipt: Path | None = None


def _result(gate: GateDefinition, status: str, reasons: Iterable[str] = ()) -> GateResult:
    return GateResult(gate.gate_id, gate.title, status, tuple(sorted(set(reasons))))


def _status_for(reasons: Iterable[str], *, incomplete: str | None = None) -> str:
    if tuple(reasons):
        return "FAIL"
    return incomplete or "PASS"


def _properties(resource: Mapping[str, object]) -> Mapping[str, object]:
    value = resource.get("Properties", {})
    return value if isinstance(value, Mapping) else {}


def _functions(template: dict[str, object]) -> dict[str, dict[str, object]]:
    return resources_of_type(template, "AWS::Lambda::Function", "AWS::Serverless::Function")


def _is_orchestrator(name: str, resource: Mapping[str, object]) -> bool:
    handler = _properties(resource).get("Handler")
    return "orchestrator" in name.casefold() or (
        isinstance(handler, str)
        and ("judge" in handler.casefold() or "orchestrator" in handler.casefold())
    )


def _is_executor(name: str, resource: Mapping[str, object]) -> bool:
    handler = _properties(resource).get("Handler")
    return "executor" in name.casefold() or (
        isinstance(handler, str) and "remediation" in handler.casefold()
    )


def _walk_strings(value: object) -> tuple[str, ...]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str):
                strings.append(key)
            strings.extend(_walk_strings(item))
    elif isinstance(value, list):
        for item in value:
            strings.extend(_walk_strings(item))
    return tuple(strings)


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else [value]


def _policy_statements(template: dict[str, object]) -> tuple[tuple[str, Mapping[str, object]], ...]:
    statements: list[tuple[str, Mapping[str, object]]] = []
    resources = template.get("Resources", {})
    if not isinstance(resources, Mapping):
        return ()
    for logical_id, resource in resources.items():
        if not isinstance(logical_id, str) or not isinstance(resource, Mapping):
            continue
        properties = _properties(resource)
        documents: list[object] = []
        if resource.get("Type") in {"AWS::IAM::ManagedPolicy", "AWS::IAM::Policy"}:
            documents.append(properties.get("PolicyDocument"))
        if resource.get("Type") == "AWS::IAM::Role":
            for policy in _as_list(properties.get("Policies", [])):
                if isinstance(policy, Mapping):
                    documents.append(policy.get("PolicyDocument"))
        for document in documents:
            if not isinstance(document, Mapping):
                continue
            for statement in _as_list(document.get("Statement", [])):
                if isinstance(statement, Mapping):
                    statements.append((logical_id, statement))
    return tuple(statements)


def _actions(statement: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(item for item in _as_list(statement.get("Action", [])) if isinstance(item, str))


def _resource_is_star(statement: Mapping[str, object]) -> bool:
    return any(item == "*" for item in _as_list(statement.get("Resource", [])))


def _python_tree(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return None


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    return next(
        (item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name),
        None,
    )


def _class_definition(tree: ast.Module, name: str) -> ast.ClassDef | None:
    return next(
        (item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == name),
        None,
    )


def _class_method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    return next(
        (
            item
            for item in class_node.body
            if isinstance(item, ast.FunctionDef) and item.name == name
        ),
        None,
    )


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _call_names(node: ast.AST) -> frozenset[str]:
    return frozenset(
        name
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and (name := _call_name(item)) is not None
    )


def _assignment(tree: ast.Module, name: str) -> ast.expr | None:
    for item in tree.body:
        if (
            isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == name
        ):
            return item.value
        if isinstance(item, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in item.targets
        ):
            return item.value
    return None


def _declared_handler_is_available(handler: object) -> bool:
    if not isinstance(handler, str) or handler.count(".") < 1:
        return False
    module_name, callable_name = handler.rsplit(".", 1)
    module_parts = module_name.split(".")
    if not callable_name.isidentifier() or not all(part.isidentifier() for part in module_parts):
        return False
    source = RUNTIME_SOURCE_ROOT.joinpath(*module_parts).with_suffix(".py")
    tree = _python_tree(source)
    return tree is not None and _top_level_function(tree, callable_name) is not None


def _lambda_handler_contract_is_exact(
    orchestrators: list[tuple[str, dict[str, object]]],
    executors: list[tuple[str, dict[str, object]]],
) -> bool:
    expected = {
        "orchestrator": "aioa_cloudops_agent.judge.lambda_handler.lambda_handler",
        "executor": "aioa_cloudops_agent.remediation.lambda_handler.lambda_handler",
    }
    classified = ((orchestrators, "orchestrator"), (executors, "executor"))
    for functions, kind in classified:
        if len(functions) != 1:
            return False
        handler = _properties(functions[0][1]).get("Handler")
        if handler != expected[kind] or not _declared_handler_is_available(handler):
            return False
    return True


def _request_member(node: ast.AST, member: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == member
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    )


def _method_has_guard(method: ast.FunctionDef, expected: str) -> bool:
    return any(
        isinstance(item, ast.Compare)
        and _request_member(item.left, "method")
        and len(item.ops) == 1
        and isinstance(item.ops[0], ast.NotEq)
        and len(item.comparators) == 1
        and isinstance(item.comparators[0], ast.Constant)
        and item.comparators[0].value == expected
        for item in ast.walk(method)
    )


def _judge_route_contract_is_exact(tree: ast.Module) -> bool:
    application = _class_definition(tree, "JudgeFunctionUrlApplication")
    if application is None:
        return False
    handle = _class_method(application, "handle")
    if handle is None:
        return False
    literal_routes = {
        item.comparators[0].value
        for item in ast.walk(handle)
        if isinstance(item, ast.Compare)
        and _request_member(item.left, "path")
        and len(item.ops) == 1
        and isinstance(item.ops[0], ast.Eq)
        and len(item.comparators) == 1
        and isinstance(item.comparators[0], ast.Constant)
        and isinstance(item.comparators[0].value, str)
    }
    status_pattern = _assignment(tree, "_STATUS_PATH")
    status_is_exact = (
        isinstance(status_pattern, ast.Call)
        and _call_name(status_pattern) == "compile"
        and len(status_pattern.args) == 1
        and isinstance(status_pattern.args[0], ast.Constant)
        and status_pattern.args[0].value == r"^/judge/status/([^/]+)$"
    )
    method_contract = {
        "_health": "GET",
        "_public_get": "GET",
        "_readiness": "GET",
        "_investigate": "POST",
        "_status": "GET",
    }
    methods_are_exact = all(
        (method := _class_method(application, name)) is not None
        and _method_has_guard(method, expected)
        for name, expected in method_contract.items()
    )
    return (
        literal_routes == {"/", "/health", "/judge/investigate", "/ready"}
        and status_is_exact
        and methods_are_exact
    )


def _server_budget_contract_is_exact(tree: ast.Module) -> bool:
    expected_constants = {
        "JUDGE_MAX_TURNS": 8,
        "JUDGE_MAX_TOKENS": 8_192,
        "JUDGE_MAX_ELAPSED_SECONDS": 60,
    }
    if any(
        not isinstance(value := _assignment(tree, name), ast.Constant) or value.value != expected
        for name, expected in expected_constants.items()
    ):
        return False
    request = _class_definition(tree, "JudgeInvestigationRequest")
    budget_factory = _top_level_function(tree, "new_judge_budget")
    if request is None or budget_factory is None:
        return False
    intent = next(
        (
            item
            for item in request.body
            if isinstance(item, ast.AnnAssign)
            and isinstance(item.target, ast.Name)
            and item.target.id == "intent"
        ),
        None,
    )
    model_config = next(
        (
            item.value
            for item in request.body
            if isinstance(item, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "model_config"
                for target in item.targets
            )
        ),
        None,
    )
    strict_schema = (
        isinstance(intent, ast.AnnAssign)
        and isinstance(intent.annotation, ast.Subscript)
        and isinstance(intent.annotation.value, ast.Name)
        and intent.annotation.value.id == "Literal"
        and isinstance(intent.annotation.slice, ast.Constant)
        and intent.annotation.slice.value == "investigate_idle_sandbox"
        and isinstance(model_config, ast.Call)
        and _call_name(model_config) == "ConfigDict"
        and {
            keyword.arg: keyword.value.value
            for keyword in model_config.keywords
            if keyword.arg is not None and isinstance(keyword.value, ast.Constant)
        }
        == {"extra": "forbid", "frozen": True}
    )
    returns = [item for item in ast.walk(budget_factory) if isinstance(item, ast.Return)]
    if len(returns) != 1 or not isinstance(returns[0].value, ast.Call):
        return False
    budget_call = returns[0].value
    budget_keywords = {
        keyword.arg: keyword.value.id
        for keyword in budget_call.keywords
        if keyword.arg is not None and isinstance(keyword.value, ast.Name)
    }
    return (
        strict_schema
        and _call_name(budget_call) == "BudgetCounters"
        and budget_keywords
        == {
            "max_turns": "JUDGE_MAX_TURNS",
            "max_tokens": "JUDGE_MAX_TOKENS",
            "max_elapsed_seconds": "JUDGE_MAX_ELAPSED_SECONDS",
        }
    )


def _fresh_request_runtime_contract_is_exact(tree: ast.Module) -> bool:
    runtime = _class_definition(tree, "JudgeInvestigationRuntime")
    investigate = _class_method(runtime, "investigate") if runtime is not None else None
    investigate_run = _class_method(runtime, "_investigate_run") if runtime is not None else None
    if investigate is None or investigate_run is None:
        return False
    if not {"new_judge_budget", "_investigate_run"} <= _call_names(investigate):
        return False
    required_fresh_construction = {
        "_session_manager_factory",
        "_model_factory",
        "_agent_factory",
        "_flow_factory",
    }
    if not required_fresh_construction <= _call_names(investigate_run):
        return False
    agent_calls = [
        item
        for item in ast.walk(investigate_run)
        if isinstance(item, ast.Call) and _call_name(item) == "_agent_factory"
    ]
    if len(agent_calls) != 1:
        return False
    tracer = next(
        (keyword.value for keyword in agent_calls[0].keywords if keyword.arg == "tracer"),
        None,
    )
    return (
        isinstance(tracer, ast.Attribute)
        and tracer.attr == "_tracer"
        and isinstance(tracer.value, ast.Name)
        and tracer.value.id == "self"
    )


def _cold_start_resume_contract_is_exact(tree: ast.Module) -> bool:
    service = _class_definition(tree, "AuthenticatedApprovalResumeService")
    if service is None:
        return False
    issue = _class_method(service, "issue")
    resume = _class_method(service, "resume")
    if issue is None or resume is None:
        return False
    return {"save_checkpoint", "_digest"} <= _call_names(issue) and {
        "compare_digest",
        "save_checkpoint",
        "ApprovalResumeRequest",
    } <= _call_names(resume)


def _runtime_proof_contracts_are_present() -> bool:
    for path, expected_names in RUNTIME_PROOF_CONTRACTS:
        tree = _python_tree(path)
        if tree is None:
            return False
        tests = {
            item.name: item
            for item in tree.body
            if isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
        }
        for name in expected_names:
            test = tests.get(name)
            if test is None or not any(
                isinstance(item, (ast.Assert, ast.With)) for item in ast.walk(test)
            ):
                return False
    return True


def _gate_runtime(context: GateContext) -> GateResult:
    gate = GATES[0]
    reasons: list[str] = []
    functions = _functions(context.template)
    orchestrators = [
        (name, item) for name, item in functions.items() if _is_orchestrator(name, item)
    ]
    executors = [(name, item) for name, item in functions.items() if _is_executor(name, item)]
    if len(functions) != 2 or len(orchestrators) != 1 or len(executors) != 1:
        reasons.append("EXACT_ORCHESTRATOR_AND_EXECUTOR_REQUIRED")
    if not _lambda_handler_contract_is_exact(orchestrators, executors):
        reasons.append("LAMBDA_HANDLER_CONTRACT_INVALID")
    for _, resource in functions.items():
        properties = _properties(resource)
        if properties.get("Runtime") != "python3.12":
            reasons.append("FUNCTION_RUNTIME_INVALID")
        if properties.get("Architectures") != ["x86_64"]:
            reasons.append("FUNCTION_ARCHITECTURE_INVALID")
        if properties.get("ReservedConcurrentExecutions") != 1:
            reasons.append("FUNCTION_RESERVED_CONCURRENCY_NOT_ONE")
        if properties.get("CodeUri") != "../../dist/day15/aioa-lambda.zip":
            reasons.append("FUNCTION_CODE_URI_NOT_FROZEN_ZIP")
    if any("agentcore" in item.casefold() for item in _walk_strings(context.template)):
        reasons.append("AGENTCORE_RESOURCE_FORBIDDEN")
    application_tree = _python_tree(JUDGE_ROUTER_SOURCES[0])
    if application_tree is None or not _judge_route_contract_is_exact(application_tree):
        reasons.append("JUDGE_ROUTE_METHOD_CONTRACT_INVALID")
    config_tree = _python_tree(JUDGE_CONFIG_SOURCE)
    if config_tree is None or not _server_budget_contract_is_exact(config_tree):
        reasons.append("SERVER_OWNED_BUDGET_CONTRACT_INVALID")
    runtime_tree = _python_tree(JUDGE_RUNTIME_SOURCE)
    if runtime_tree is None or not _fresh_request_runtime_contract_is_exact(runtime_tree):
        reasons.append("FRESH_REQUEST_RUNTIME_CONTRACT_INVALID")
    resume_tree = _python_tree(APPROVAL_RESUME_SOURCE)
    if resume_tree is None or not _cold_start_resume_contract_is_exact(resume_tree):
        reasons.append("COLD_START_RESUME_CONTRACT_INVALID")
    if not _runtime_proof_contracts_are_present():
        reasons.append("RUNTIME_PROOF_CONTRACT_MISSING")
    return _result(gate, _status_for(reasons), reasons)


def _gate_iam(context: GateContext) -> GateResult:
    gate = GATES[1]
    reasons: list[str] = []
    if context.rendered_template_path is None:
        if context.template_has_sam:
            return _result(gate, "BLOCKED", ("RENDERED_IAM_TEMPLATE_REQUIRED",))
        template = context.template
    else:
        try:
            verified_template, _ = verify_rendered_template(
                template=context.template_path,
                toolchain=context.toolchain,
                rendered_template=context.rendered_template_path,
            )
        except RenderFailure as error:
            return _result(gate, error.status, (error.reason,))
        if context.rendered_template != verified_template:
            return _result(gate, "FAIL", ("RENDERED_TEMPLATE_CONTEXT_MISMATCH",))
        template = verified_template
    resources = template.get("Resources", {})
    iam_resources = {
        name: resource
        for name, resource in resources.items()
        if isinstance(name, str)
        and isinstance(resource, Mapping)
        and isinstance(resource.get("Type"), str)
        and str(resource["Type"]).startswith("AWS::IAM::")
    }
    roles = resources_of_type(template, "AWS::IAM::Role")
    if set(iam_resources) != set(EXPECTED_ROLE_POLICIES) or set(roles) != set(
        EXPECTED_ROLE_POLICIES
    ):
        reasons.append("IAM_RESOURCE_ALLOWLIST_INVALID")
    for role_name, expected_policies in EXPECTED_ROLE_POLICIES.items():
        role = roles.get(role_name)
        properties = _properties(role) if role is not None else {}
        policies = properties.get("Policies")
        actual_policies: dict[str, object] = {}
        if isinstance(policies, list):
            for policy in policies:
                if not isinstance(policy, Mapping) or set(policy) != {
                    "PolicyDocument",
                    "PolicyName",
                }:
                    reasons.append("IAM_INLINE_POLICY_SCHEMA_INVALID")
                    continue
                name = policy.get("PolicyName")
                document = policy.get("PolicyDocument")
                if not isinstance(name, str) or name in actual_policies:
                    reasons.append("IAM_INLINE_POLICY_SCHEMA_INVALID")
                    continue
                actual_policies[name] = document
        else:
            reasons.append("IAM_INLINE_POLICY_SCHEMA_INVALID")
        expected_documents = {
            name: {"Statement": statements, "Version": "2012-10-17"}
            for name, statements in expected_policies.items()
        }
        if (
            set(properties) != {"AssumeRolePolicyDocument", "Policies", "Tags"}
            or properties.get("AssumeRolePolicyDocument") != EXPECTED_ASSUME_ROLE_POLICY
            or properties.get("Tags") != EXPECTED_OWNERSHIP_TAGS
            or actual_policies != expected_documents
        ):
            reasons.append("IAM_ROLE_POLICY_ALLOWLIST_INVALID")
    statements = _policy_statements(template)
    all_actions: list[tuple[str, str, Mapping[str, object]]] = []
    for owner, statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        for action in _actions(statement):
            all_actions.append((owner, action, statement))
            if "*" in action:
                reasons.append("IAM_WILDCARD_ACTION_FORBIDDEN")
            if _resource_is_star(statement) and action.casefold() not in {
                "cloudwatch:getmetricstatistics",
                "ec2:describeinstances",
                "logs:createlogstream",
                "logs:putlogevents",
                "xray:puttelemetryrecords",
                "xray:puttracesegments",
            }:
                reasons.append("IAM_SENSITIVE_ACTION_RESOURCE_STAR")
    stop = [item for item in all_actions if item[1].casefold() == "ec2:stopinstances"]
    if len(stop) != 1:
        reasons.append("EXACT_SCOPED_STOP_STATEMENT_REQUIRED")
    elif stop:
        owner, _, statement = stop[0]
        text = canonical_json(statement).casefold()
        if (
            "executor" not in owner.casefold()
            or "instance/" not in text
            or "sandboxinstanceid" not in text
        ):
            reasons.append("STOP_RESOURCE_SCOPE_INVALID")
        if not all(
            token in text
            for token in ("aws:requestedregion", "eu-central-1", "aws:resourcetag", "true")
        ):
            reasons.append("STOP_CONDITION_SCOPE_INVALID")
    describes = [item for item in all_actions if item[1].casefold() == "ec2:describeinstances"]
    describe_owners = {owner.casefold() for owner, _, _ in describes}
    if not any("executor" in owner for owner in describe_owners):
        reasons.append("EXECUTOR_DESCRIBE_PERMISSION_MISSING")
    if not any("orchestrator" in owner for owner in describe_owners):
        reasons.append("ORCHESTRATOR_DESCRIBE_PERMISSION_MISSING")
    bedrock = [item for item in all_actions if item[1].casefold().startswith("bedrock:")]
    if not bedrock or any(item[1] != "bedrock:InvokeModelWithResponseStream" for item in bedrock):
        reasons.append("BEDROCK_STREAMING_ACTION_SCOPE_INVALID")
    else:
        bedrock_text = canonical_json([statement for _, _, statement in bedrock])
        if (
            any(_resource_is_star(statement) for _, _, statement in bedrock)
            or "inference-profile" not in bedrock_text
            or "foundation-model" not in bedrock_text
        ):
            reasons.append("BEDROCK_RESOURCE_SCOPE_INVALID")
    invokes = [item for item in all_actions if item[1].casefold() == "lambda:invokefunction"]
    aliases = resources_of_type(context.template, "AWS::Lambda::Alias")
    live_executor_aliases = {
        name.casefold()
        for name, alias in aliases.items()
        if _properties(alias).get("Name") == "live" and "remediation" in name.casefold()
    }
    if not any(
        "orchestrator" in owner.casefold()
        and "remediation" in canonical_json(statement).casefold()
        and any(alias in canonical_json(statement).casefold() for alias in live_executor_aliases)
        for owner, _, statement in invokes
    ):
        reasons.append("QUALIFIED_PRIVATE_INVOKE_PERMISSION_MISSING")
    raw_managed = resources_of_type(template, "AWS::IAM::ManagedPolicy")
    for resource in raw_managed.values():
        if not _properties(resource).get("Roles"):
            reasons.append("DETACHED_MANAGED_POLICY_FORBIDDEN")
    return _result(gate, _status_for(reasons), reasons)


def _gate_retries(_context: GateContext) -> GateResult:
    gate = GATES[2]
    reasons: list[str] = []
    try:
        text = AWS_CLIENTS_SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return _result(gate, "FAIL", ("AWS_CLIENT_FACTORY_UNAVAILABLE",))
    constant_is_one = any(
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "AWS_TOTAL_MAX_ATTEMPTS"
        and isinstance(node.value, ast.Constant)
        and node.value.value == 1
        for node in ast.walk(tree)
    )
    if not constant_is_one or "total_max_attempts" not in text:
        reasons.append("TOTAL_MAX_ATTEMPTS_ONE_NOT_FROZEN")
    for factory in (
        "create_cloudwatch_read_client",
        "create_ec2_read_client",
        "create_ec2_stop_client",
        "create_lambda_invoke_client",
    ):
        if not any(
            isinstance(node, ast.FunctionDef) and node.name == factory for node in tree.body
        ):
            reasons.append("CRITICAL_AWS_CLIENT_FACTORY_MISSING")
    if (
        "ignore_configured_endpoint_urls=True" not in text
        or "region_name=DEFAULT_AWS_REGION" not in text
    ):
        reasons.append("AWS_CLIENT_HOST_CONFIG_NOT_OWNED")
    return _result(gate, _status_for(reasons), reasons)


def _read_canonical_json(
    path: Path, *, unavailable_reason: str
) -> tuple[dict[str, object] | None, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text)
    except FileNotFoundError:
        return None, unavailable_reason
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, "JSON_EVIDENCE_INVALID"
    if not isinstance(value, dict) or text != canonical_json(value) + "\n":
        return None, "JSON_EVIDENCE_NOT_CANONICAL"
    return value, None


def _metadata_is_public_safe(value: object) -> bool:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                return False
            lowered = key.casefold()
            if lowered in {
                "cwd",
                "hostname",
                "host_path",
                "username",
            } or TIMESTAMP_KEY_PATTERN.search(lowered):
                return False
            if not _metadata_is_public_safe(item):
                return False
    elif isinstance(value, list):
        return all(_metadata_is_public_safe(item) for item in value)
    elif isinstance(value, str) and ABSOLUTE_PATH_PATTERN.search(value):
        return False
    return True


def _gate_artifact(context: GateContext) -> GateResult:
    gate = GATES[3]
    blockers: list[str] = []
    failures: list[str] = []
    try:
        lock_entries = validate_runtime_lock(context.lock)
        lock_sha = hashlib.sha256(context.lock.read_bytes()).hexdigest()
    except (ArtifactFailure, OSError):
        return _result(gate, "FAIL", ("RUNTIME_LOCK_INVALID",))
    if not context.artifact.is_file():
        blockers.append("LAMBDA_ARTIFACT_REQUIRED")
    manifest, manifest_error = _read_canonical_json(
        context.manifest,
        unavailable_reason="ARTIFACT_MANIFEST_REQUIRED",
    )
    scan, scan_error = _read_canonical_json(
        context.scan_report,
        unavailable_reason="DEPENDENCY_SCAN_REPORT_REQUIRED",
    )
    toolchain, toolchain_error = _read_canonical_json(
        context.toolchain,
        unavailable_reason="DAY15_TOOLCHAIN_RECORD_REQUIRED",
    )
    if manifest_error:
        (blockers if manifest_error.endswith("REQUIRED") else failures).append(manifest_error)
    if scan_error:
        (blockers if scan_error.endswith("REQUIRED") else failures).append(scan_error)
    if toolchain_error:
        (blockers if toolchain_error.endswith("REQUIRED") else failures).append(toolchain_error)
    if (
        blockers
        or failures
        or manifest is None
        or scan is None
        or toolchain is None
        or not context.artifact.is_file()
    ):
        status = "FAIL" if failures else "BLOCKED"
        return _result(gate, status, (*failures, *blockers))
    try:
        archive = inspect_archive(context.artifact)
        artifact_raw = context.artifact.read_bytes()
    except (ArtifactFailure, OSError):
        return _result(gate, "FAIL", ("LAMBDA_ARTIFACT_INVALID",))
    artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
    try:
        fresh = revalidate_artifact(
            context.artifact,
            context.lock,
            context.template_path,
            context.toolchain,
        )
    except ArtifactFailure as error:
        (blockers if error.status in {"BLOCKED", "PARTIAL"} else failures).append(error.reason)
        fresh = None
    try:
        repository = validate_repository_inputs(
            BuildPaths(
                lock=context.lock,
                source=ROOT / "src",
                template=DEFAULT_TEMPLATE,
                artifact=context.artifact,
                manifest=context.manifest,
                scan_report=context.scan_report,
            )
        )
    except ArtifactFailure as error:
        (blockers if error.status == "BLOCKED" else failures).append(
            "ARTIFACT_REPOSITORY_PROVENANCE_INVALID"
        )
        repository = None
    artifact_model = manifest.get("artifact")
    inputs = manifest.get("inputs")
    if not isinstance(artifact_model, Mapping) or not isinstance(inputs, Mapping):
        failures.append("ARTIFACT_MANIFEST_SCHEMA_INVALID")
    else:
        expected_base64 = base64.b64encode(bytes.fromhex(artifact_sha)).decode("ascii")
        if (
            artifact_model.get("sha256") != artifact_sha
            or artifact_model.get("code_sha256_base64") != expected_base64
            or artifact_model.get("filename") != "aioa-lambda.zip"
            or artifact_model.get("entry_count") != archive.get("entry_count")
            or inputs.get("lock_sha256") != lock_sha
        ):
            failures.append("ARTIFACT_MANIFEST_HASH_MISMATCH")
    dependencies = manifest.get("dependencies")
    expected_dependencies = [
        {"name": entry.name, "version": entry.version} for entry in lock_entries
    ]
    if dependencies != expected_dependencies:
        failures.append("ARTIFACT_DEPENDENCY_INVENTORY_MISMATCH")
    if manifest.get("lambda_like_clean_import") != "PASS":
        failures.append("LAMBDA_CLEAN_IMPORT_PROOF_INVALID")
    if manifest.get("archive_scan") != archive:
        failures.append("ARTIFACT_ARCHIVE_SCAN_PROOF_INVALID")
    if manifest.get("builder") != toolchain.get("artifact_builder"):
        failures.append("ARTIFACT_BUILDER_TOOLCHAIN_MISMATCH")
    if repository is not None and manifest.get("repository") != repository:
        failures.append("ARTIFACT_COMMIT_BINDING_MISMATCH")
    rebuild = manifest.get("deterministic_rebuild")
    if not isinstance(rebuild, Mapping) or rebuild != {
        "sha256": artifact_sha,
        "status": "PASS",
    }:
        failures.append("DETERMINISTIC_REBUILD_PROOF_INVALID")
    try:
        expected_handlers = list(discover_lambda_handlers(DEFAULT_TEMPLATE))
    except ArtifactFailure:
        expected_handlers = []
    if (
        context.template == load_template(DEFAULT_TEMPLATE)
        and manifest.get("handlers") != expected_handlers
    ):
        failures.append("ARTIFACT_HANDLER_INVENTORY_MISMATCH")
    if not _metadata_is_public_safe(manifest) or not _metadata_is_public_safe(scan):
        failures.append("ARTIFACT_EVIDENCE_HAS_HOST_OR_TIME_METADATA")
    scanner_contract = toolchain.get("dependency_scanner")
    expected_scanner_version = (
        scanner_contract.get("version") if isinstance(scanner_contract, Mapping) else None
    )
    if (
        scan.get("artifact_sha256") != artifact_sha
        or scan.get("lock_sha256") != lock_sha
        or scan.get("scanner") != "pip-audit"
        or scan.get("scanner_version") != expected_scanner_version
        or scan.get("audited_dependency_count") != len(lock_entries)
        or scan.get("expected_dependency_count") != len(lock_entries)
        or scan.get("vulnerability_count") != 0
        or scan.get("vulnerabilities") != []
    ):
        failures.append("DEPENDENCY_SCAN_HASH_MISMATCH")
    scan_status = scan.get("status")
    if scan_status == "FAIL":
        failures.append("DEPENDENCY_VULNERABILITY_SCAN_FAILED")
    elif scan_status == "BLOCKED":
        blockers.append("DEPENDENCY_VULNERABILITY_SCAN_BLOCKED")
    elif scan_status != "PASS":
        failures.append("DEPENDENCY_SCAN_STATUS_INVALID")
    container = manifest.get("lambda_compatible_container_validation")
    if not isinstance(container, Mapping) or container.get("status") not in STATUS_VALUES:
        failures.append("LAMBDA_CONTAINER_VALIDATION_INVALID")
    elif container.get("status") == "FAIL":
        failures.append("LAMBDA_CONTAINER_VALIDATION_FAILED")
    elif container.get("status") in {"PARTIAL", "BLOCKED"}:
        blockers.append("LAMBDA_CONTAINER_VALIDATION_BLOCKED")
    container_contract = toolchain.get("lambda_compatible_container")
    if isinstance(container, Mapping) and isinstance(container_contract, Mapping):
        image = container_contract.get("image")
        expected_digest = (
            image.rsplit("@", 1)[1] if isinstance(image, str) and "@" in image else None
        )
        if (
            container.get("engine") != container_contract.get("engine")
            or container.get("engine_version") != container_contract.get("engine_version")
            or container.get("image_digest") != expected_digest
            or container.get("architecture") != "amd64"
        ):
            failures.append("LAMBDA_CONTAINER_IDENTITY_INVALID")
    if fresh is not None:
        fresh_scan = fresh.get("scan")
        fresh_container = fresh.get("lambda_compatible_container_validation")
        if fresh.get("archive_scan") != archive:
            failures.append("FRESH_ARCHIVE_SCAN_MISMATCH")
        if fresh.get("lambda_like_clean_import") != "PASS":
            failures.append("FRESH_CLEAN_IMPORT_FAILED")
        if fresh.get("builder") != manifest.get("builder"):
            failures.append("FRESH_BUILDER_IDENTITY_MISMATCH")
        if fresh.get("dependencies") != dependencies or fresh.get("handlers") != manifest.get(
            "handlers"
        ):
            failures.append("FRESH_ARTIFACT_INVENTORY_MISMATCH")
        if isinstance(fresh_scan, Mapping):
            fresh_scan_status = fresh_scan.get("status")
            if fresh_scan_status == "FAIL":
                failures.append("FRESH_DEPENDENCY_SCAN_FAILED")
            elif fresh_scan_status in {"BLOCKED", "PARTIAL"}:
                blockers.append("FRESH_DEPENDENCY_SCAN_BLOCKED")
            elif fresh_scan_status != "PASS":
                failures.append("FRESH_DEPENDENCY_SCAN_INVALID")
            elif fresh_scan != scan:
                failures.append("FRESH_DEPENDENCY_SCAN_MISMATCH")
        else:
            failures.append("FRESH_DEPENDENCY_SCAN_INVALID")
        if isinstance(fresh_container, Mapping):
            fresh_container_status = fresh_container.get("status")
            if fresh_container_status == "FAIL":
                failures.append("FRESH_CONTAINER_VALIDATION_FAILED")
            elif fresh_container_status in {"BLOCKED", "PARTIAL"}:
                blockers.append("FRESH_CONTAINER_VALIDATION_BLOCKED")
            elif fresh_container_status != "PASS":
                failures.append("FRESH_CONTAINER_VALIDATION_INVALID")
            elif fresh_container != container:
                failures.append("FRESH_CONTAINER_VALIDATION_MISMATCH")
        else:
            failures.append("FRESH_CONTAINER_VALIDATION_INVALID")
    if failures:
        return _result(gate, "FAIL", failures)
    if blockers:
        return _result(gate, "BLOCKED", blockers)
    return _result(gate, "PASS")


def _gate_state(context: GateContext) -> GateResult:
    gate = GATES[4]
    reasons: list[str] = []
    tables = resources_of_type(context.template, "AWS::DynamoDB::Table")
    if len(tables) != 1:
        reasons.append("EXACT_ONE_STATE_TABLE_REQUIRED")
    for table in tables.values():
        properties = _properties(table)
        if table.get("DeletionPolicy") != "Retain" or table.get("UpdateReplacePolicy") != "Retain":
            reasons.append("STATE_TABLE_RETAIN_POLICIES_REQUIRED")
        pitr = properties.get("PointInTimeRecoverySpecification")
        if not isinstance(pitr, Mapping) or pitr.get("PointInTimeRecoveryEnabled") is not True:
            reasons.append("STATE_TABLE_PITR_REQUIRED")
        if properties.get("DeletionProtectionEnabled") is not True:
            reasons.append("STATE_TABLE_DELETION_PROTECTION_REQUIRED")
        if properties.get("BillingMode") != "PAY_PER_REQUEST":
            reasons.append("STATE_TABLE_ON_DEMAND_REQUIRED")
        sse = properties.get("SSESpecification")
        if not isinstance(sse, Mapping) or sse.get("SSEEnabled") is not True:
            reasons.append("STATE_TABLE_ENCRYPTION_REQUIRED")
    return _result(gate, _status_for(reasons), reasons)


def _template_has_region_guard(template: dict[str, object]) -> bool:
    rules = template.get("Rules")
    if not isinstance(rules, Mapping):
        return False
    expected_operands = ({"Ref": "AWS::Region"}, "eu-central-1")
    for rule in rules.values():
        if not isinstance(rule, Mapping) or "RuleCondition" in rule:
            continue
        assertions = rule.get("Assertions")
        if not isinstance(assertions, list):
            continue
        for assertion in assertions:
            expression = assertion.get("Assert") if isinstance(assertion, Mapping) else None
            operands = expression.get("Fn::Equals") if isinstance(expression, Mapping) else None
            if (
                isinstance(operands, list)
                and len(operands) == 2
                and (
                    tuple(operands) == expected_operands
                    or tuple(reversed(operands)) == expected_operands
                )
            ):
                return True
    return False


def _gate_region(context: GateContext) -> GateResult:
    gate = GATES[5]
    preflight = validate_region(context.region)
    reasons = list(preflight.reasons)
    status = preflight.status
    if not _template_has_region_guard(context.template):
        reasons.append("TEMPLATE_REGION_GUARD_MISSING")
        status = "FAIL"
    return _result(gate, status, reasons)


def _string_constants(node: ast.AST) -> frozenset[str]:
    return frozenset(
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    )


def _expression_contract(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return f"${node.id}"
    if isinstance(node, ast.Attribute):
        prefix = _expression_contract(node.value)
        return f"{prefix}.{node.attr}" if prefix is not None else None
    return None


def _aws_json_command_contract(function: ast.FunctionDef) -> tuple[str, ...] | None:
    calls = [
        item
        for item in ast.walk(function)
        if isinstance(item, ast.Call) and _call_name(item) == "_aws_json"
    ]
    if len(calls) != 1 or not calls[0].args or not isinstance(calls[0].args[0], ast.Tuple):
        return None
    values = tuple(_expression_contract(item) for item in calls[0].args[0].elts)
    if any(value is None for value in values):
        return None
    return tuple(str(value) for value in values)


def _rollback_contract_is_exact() -> bool:
    tree = _python_tree(ROLLBACK_TOOL)
    proof_tree = _python_tree(ROLLBACK_PROOF)
    if tree is None or proof_tree is None:
        return False
    expected_operations = {
        "_stack_functions": (
            "cloudformation",
            "describe-stack-resources",
            "--stack-name",
            "$request.stack_name",
        ),
        "_alias_version": (
            "lambda",
            "get-alias",
            "--function-name",
            "$function_name",
            "--name",
            "live",
        ),
        "_validate_version_exists": (
            "lambda",
            "get-function",
            "--function-name",
            "$function_name",
            "--qualifier",
            "$version",
        ),
        "_update_alias": (
            "lambda",
            "update-alias",
            "--function-name",
            "$function_name",
            "--name",
            "live",
            "--function-version",
            "$version",
        ),
    }
    functions = {item.name: item for item in tree.body if isinstance(item, ast.FunctionDef)}
    callers = {name for name, function in functions.items() if "_aws_json" in _call_names(function)}
    if callers != set(expected_operations):
        return False
    if any(
        (function := functions.get(name)) is None
        or _aws_json_command_contract(function) != operation
        for name, operation in expected_operations.items()
    ):
        return False
    build_plan = functions.get("build_plan")
    execute_plan = functions.get("execute_plan")
    if build_plan is None or execute_plan is None:
        return False
    if not {
        "_stack_functions",
        "_alias_version",
        "_validate_version_exists",
        "_validate_request",
    } <= _call_names(build_plan):
        return False
    if not {"_update_alias", "build_plan"} <= _call_names(execute_plan):
        return False
    if not {
        "alias-only-rollback-no-rebuild",
        "PLAN_CONFIRMATION_REQUIRED",
        "ALIAS_RECONCILIATION_REQUIRED",
        "ALIASES_MATCH_CAPTURED_VERSIONS",
        "live",
    } <= _string_constants(tree):
        return False
    forbidden_operations = {
        "create-alias",
        "delete-function",
        "delete-provisioned-concurrency-config",
        "publish-version",
        "put-provisioned-concurrency-config",
        "update-function-code",
        "update-function-configuration",
    }
    if forbidden_operations & _string_constants(tree):
        return False
    proof_functions = {
        item.name: item
        for item in proof_tree.body
        if isinstance(item, ast.FunctionDef) and item.name.startswith("test_")
    }
    return all(
        (test := proof_functions.get(name)) is not None
        and any(isinstance(item, (ast.Assert, ast.With)) for item in ast.walk(test))
        for name in ROLLBACK_PROOF_NAMES
    )


def _gate_versions(context: GateContext) -> GateResult:
    gate = GATES[6]
    reasons: list[str] = []
    functions = _functions(context.template)
    versions = resources_of_type(context.template, "AWS::Lambda::Version")
    aliases = resources_of_type(context.template, "AWS::Lambda::Alias")
    if len(functions) != 2 or len(versions) != len(functions) or len(aliases) != len(functions):
        reasons.append("EXPLICIT_VERSION_ALIAS_PAIR_REQUIRED")
    function_ids = set(functions)
    version_ids = set(versions)
    for name, version in versions.items():
        properties = _properties(version)
        version_function = properties.get("FunctionName")
        code_sha = properties.get("CodeSha256")
        description_text = canonical_json(properties.get("Description"))
        if (
            version.get("DeletionPolicy") != "Retain"
            or version.get("UpdateReplacePolicy") != "Retain"
        ):
            reasons.append("EXPLICIT_VERSION_RETENTION_REQUIRED")
        if (
            not isinstance(version_function, Mapping)
            or version_function.get("Ref") not in function_ids
        ):
            reasons.append("EXPLICIT_VERSION_FUNCTION_BINDING_INVALID")
        if not isinstance(code_sha, Mapping) or code_sha.get("Ref") != "LambdaArtifactSha256Base64":
            reasons.append("EXPLICIT_VERSION_CODE_HASH_BINDING_INVALID")
        if "LambdaConfigurationSha256" not in description_text:
            reasons.append("VERSION_CONFIGURATION_DIGEST_BINDING_REQUIRED")
        if "orchestrator" in name.casefold() and "JudgeTokenNotAfter" not in description_text:
            reasons.append("ORCHESTRATOR_EXPIRY_ROTATION_BINDING_REQUIRED")
    for alias in aliases.values():
        properties = _properties(alias)
        function_ref = properties.get("FunctionName")
        version_ref = properties.get("FunctionVersion")
        if properties.get("Name") != "live":
            reasons.append("EXPLICIT_LIVE_ALIAS_REQUIRED")
        if not isinstance(function_ref, Mapping) or function_ref.get("Ref") not in function_ids:
            reasons.append("ALIAS_FUNCTION_BINDING_INVALID")
        if (
            not isinstance(version_ref, Mapping)
            or not isinstance(version_ref.get("Fn::GetAtt"), list)
            or version_ref["Fn::GetAtt"][0] not in version_ids
            or version_ref["Fn::GetAtt"][1] != "Version"
        ):
            reasons.append("ALIAS_QUALIFIED_VERSION_BINDING_INVALID")
    orchestrators = [item for name, item in functions.items() if _is_orchestrator(name, item)]
    if orchestrators:
        variables = _properties(orchestrators[0]).get("Environment", {})
        live_alias_ids = {
            name.casefold()
            for name, alias in aliases.items()
            if _properties(alias).get("Name") == "live"
        }
        if not any(alias_id in canonical_json(variables).casefold() for alias_id in live_alias_ids):
            reasons.append("PRIVATE_EXECUTOR_ALIAS_BINDING_REQUIRED")
    parameters = context.template.get("Parameters", {})
    digest_parameter = (
        parameters.get("LambdaConfigurationSha256") if isinstance(parameters, Mapping) else None
    )
    if not isinstance(digest_parameter, Mapping):
        reasons.append("LAMBDA_CONFIGURATION_DIGEST_PARAMETER_REQUIRED")
    try:
        digest_status, digest_reasons, _ = compare_lambda_configuration_sha256(
            context.template,
            context.lambda_configuration_sha256,
        )
    except TemplateFailure:
        digest_status = "FAIL"
        digest_reasons = ("LAMBDA_CONFIGURATION_MODEL_INVALID",)
    reasons.extend(digest_reasons)
    if not ROLLBACK_RUNBOOK.is_file():
        reasons.append("ALIAS_ROLLBACK_RUNBOOK_REQUIRED")
    if not _rollback_contract_is_exact():
        reasons.append("ALIAS_ONLY_ROLLBACK_CONTRACT_INVALID")
    failure_reasons = [
        reason for reason in reasons if reason != "LAMBDA_CONFIGURATION_SHA256_REQUIRED"
    ]
    if failure_reasons:
        return _result(gate, "FAIL", failure_reasons)
    if digest_status == "BLOCKED":
        return _result(gate, "BLOCKED", digest_reasons)
    return _result(gate, "PASS")


def _gate_observability(context: GateContext) -> GateResult:
    gate = GATES[7]
    reasons: list[str] = []
    functions = _functions(context.template)
    log_groups = resources_of_type(context.template, "AWS::Logs::LogGroup")
    if len(log_groups) != len(functions) or any(
        _properties(group).get("RetentionInDays") != 3 for group in log_groups.values()
    ):
        reasons.append("THREE_DAY_LOG_GROUP_PER_FUNCTION_REQUIRED")
    alarms = resources_of_type(context.template, "AWS::CloudWatch::Alarm")
    alarm_text = canonical_json(alarms).casefold()
    for metric in ("duration", "errors", "throttles"):
        if metric not in alarm_text:
            reasons.append("BOUNDED_LAMBDA_ALARMS_INCOMPLETE")
            break
    template_text = canonical_json(context.template).casefold()
    if not any(token in template_text for token in ("tracing", "xray:puttracesegments", "otel")):
        reasons.append("NON_AGENTCORE_TELEMETRY_REQUIRED")
    if "agentcore" in template_text:
        reasons.append("AGENTCORE_TELEMETRY_FORBIDDEN")
    resources = context.template.get("Resources", {})
    resource_types = (
        {
            str(resource.get("Type"))
            for resource in resources.values()
            if isinstance(resource, Mapping) and isinstance(resource.get("Type"), str)
        }
        if isinstance(resources, Mapping)
        else set()
    )
    if any(
        resource_type in FORBIDDEN_COST_RESOURCE_TYPES
        or resource_type.startswith(FORBIDDEN_COST_RESOURCE_PREFIXES)
        for resource_type in resource_types
    ):
        reasons.append("FORBIDDEN_COST_RESOURCE_PRESENT")
    if any("provisionedconcurrency" in item.casefold() for item in _walk_strings(context.template)):
        reasons.append("PROVISIONED_CONCURRENCY_FORBIDDEN")
    return _result(gate, _status_for(reasons), reasons)


def _public_permissions(template: dict[str, object]) -> dict[str, dict[str, object]]:
    return resources_of_type(template, "AWS::Lambda::Permission")


def _public_ingress_condition_is_exact(template: dict[str, object]) -> bool:
    parameters = template.get("Parameters")
    conditions = template.get("Conditions")
    parameter = parameters.get("PublicIngressEnabled") if isinstance(parameters, Mapping) else None
    condition = (
        conditions.get("PublicIngressEnabledCondition") if isinstance(conditions, Mapping) else None
    )
    return (
        isinstance(parameter, Mapping)
        and parameter.get("Type") == "String"
        and parameter.get("Default") == "false"
        and parameter.get("AllowedValues") == ["false", "true"]
        and condition
        == {
            "Fn::Equals": [
                {"Ref": "PublicIngressEnabled"},
                "true",
            ]
        }
    )


def _gate_public_surface(context: GateContext) -> GateResult:
    gate = GATES[8]
    reasons: list[str] = []
    resources = context.template.get("Resources", {})
    if not isinstance(resources, Mapping):
        return _result(gate, "FAIL", ("TEMPLATE_RESOURCES_INVALID",))
    forbidden_types = {
        "AWS::ApiGateway::RestApi",
        "AWS::ApiGatewayV2::Api",
        "AWS::Serverless::Api",
        "AWS::Serverless::HttpApi",
    }
    if any(
        isinstance(item, Mapping) and item.get("Type") in forbidden_types
        for item in resources.values()
    ):
        reasons.append("API_GATEWAY_PUBLIC_SURFACE_FORBIDDEN")
    inline_url_functions: list[tuple[str, Mapping[str, object]]] = []
    for name, function in _functions(context.template).items():
        properties = _properties(function)
        if "FunctionUrlConfig" in properties:
            inline_url_functions.append((name, function))
        events = properties.get("Events", {})
        if isinstance(events, Mapping) and any(
            isinstance(event, Mapping) and event.get("Type") in {"Api", "HttpApi"}
            for event in events.values()
        ):
            reasons.append("API_GATEWAY_EVENT_FORBIDDEN")
    explicit_urls = resources_of_type(context.template, "AWS::Lambda::Url")
    if not _public_ingress_condition_is_exact(context.template):
        reasons.append("PUBLIC_INGRESS_CONDITION_BINDING_INVALID")
    if inline_url_functions:
        reasons.append("INLINE_FUNCTION_URL_CONFIG_FORBIDDEN")
    if len(explicit_urls) != 1:
        reasons.append("EXACT_ONE_ORCHESTRATOR_FUNCTION_URL_REQUIRED")
    else:
        url_resource = next(iter(explicit_urls.values()))
        url_properties = _properties(url_resource)
        target = url_properties.get("TargetFunctionArn")
        if url_resource.get("Condition") != "PublicIngressEnabledCondition":
            reasons.append("FUNCTION_URL_CONDITION_BINDING_INVALID")
        if (
            url_properties.get("AuthType") != "NONE"
            or url_properties.get("Qualifier") != "live"
            or not isinstance(target, Mapping)
            or target.get("Ref") != "OrchestratorFunction"
        ):
            reasons.append("FUNCTION_URL_CONFIG_INVALID")
    routers: list[str] = []
    for source in JUDGE_ROUTER_SOURCES:
        try:
            routers.append(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            reasons.append("JUDGE_ROUTER_UNAVAILABLE")
            break
    if routers:
        router = "\n".join(routers)
        route_literals = re.findall(r"[\"'](/[^\"']*)[\"']", router)
        if any(
            any(
                word in route.casefold()
                for word in ("approve", "resume", "execute", "mutate", "stop")
            )
            for route in route_literals
        ):
            reasons.append("PUBLIC_MUTATION_OR_APPROVAL_ROUTE_FORBIDDEN")
    permissions = _public_permissions(context.template)
    public = [item for item in permissions.values() if _properties(item).get("Principal") == "*"]
    if len(public) != 2:
        reasons.append("EXACT_TWO_PUBLIC_URL_PERMISSIONS_REQUIRED")
    else:
        if any(item.get("Condition") != "PublicIngressEnabledCondition" for item in public):
            reasons.append("PUBLIC_URL_PERMISSION_CONDITION_BINDING_INVALID")
        public_properties = [_properties(item) for item in public]
        actions = {item.get("Action") for item in public_properties}
        if actions != {"lambda:InvokeFunction", "lambda:InvokeFunctionUrl"}:
            reasons.append("PUBLIC_URL_PERMISSION_ACTIONS_INVALID")
        by_action = {str(item.get("Action")): item for item in public_properties}
        url_permission = by_action.get("lambda:InvokeFunctionUrl", {})
        invoke_permission = by_action.get("lambda:InvokeFunction", {})
        if (
            url_permission.get("FunctionUrlAuthType") != "NONE"
            or invoke_permission.get("InvokedViaFunctionUrl") is not True
            or any(
                not isinstance(item.get("FunctionName"), Mapping)
                or item["FunctionName"].get("Ref") != "OrchestratorAlias"
                for item in public_properties
            )
        ):
            reasons.append("PUBLIC_URL_PERMISSION_CONDITIONS_INVALID")
    return _result(gate, _status_for(reasons), reasons)


def _receipt_result(
    path: Path,
    *,
    expected_bindings: Mapping[str, str],
    attestation_key: Path | None,
) -> CheckResult:
    receipt, error = _read_canonical_json(
        path, unavailable_reason="EXTERNAL_PREFLIGHT_RECEIPT_REQUIRED"
    )
    if error is not None:
        status = "BLOCKED" if error.endswith("REQUIRED") else "FAIL"
        return CheckResult(status, (error,))
    assert receipt is not None
    try:
        key = read_attestation_key(attestation_key)
        validate_receipt(receipt, expected_bindings=expected_bindings, key=key)
    except AttestationFailure as failure:
        return CheckResult(failure.status, (failure.reason,))
    return CheckResult("PASS")


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _deployment_contract_result(
    contract_path: Path,
    receipt_path: Path,
) -> CheckResult:
    contract, contract_error = _read_canonical_json(
        contract_path,
        unavailable_reason="DAY15_DEPLOYMENT_CONTRACT_REQUIRED",
    )
    if contract_error is not None:
        status = "BLOCKED" if contract_error.endswith("REQUIRED") else "FAIL"
        return CheckResult(status, (contract_error,))
    assert contract is not None
    expected_keys = {
        *DEPLOYMENT_CONTRACT_FIXED,
        *DEPLOYMENT_CONTRACT_HASH_FIELDS,
        "status",
    }
    if set(contract) != expected_keys or any(
        contract.get(name) != value for name, value in DEPLOYMENT_CONTRACT_FIXED.items()
    ):
        return CheckResult("FAIL", ("DAY15_DEPLOYMENT_CONTRACT_INVALID",))
    hashes = {name: contract.get(name) for name in DEPLOYMENT_CONTRACT_HASH_FIELDS}
    contract_status = contract.get("status")
    selected_values = tuple(hashes.values())
    if contract_status == "BLOCKED" and all(value is None for value in selected_values):
        return CheckResult("BLOCKED", ("DEPLOYMENT_CONTRACT_SELECTION_REQUIRED",))
    if contract_status != "PASS" or not all(
        isinstance(value, str) and SHA256_PATTERN.fullmatch(value) is not None
        for value in selected_values
    ):
        return CheckResult("FAIL", ("DAY15_DEPLOYMENT_CONTRACT_INVALID",))
    receipt, receipt_error = _read_canonical_json(
        receipt_path,
        unavailable_reason="EXTERNAL_PREFLIGHT_RECEIPT_REQUIRED",
    )
    if receipt_error is not None or receipt is None:
        status = "BLOCKED" if receipt_error and receipt_error.endswith("REQUIRED") else "FAIL"
        return CheckResult(status, (receipt_error or "EXTERNAL_PREFLIGHT_RECEIPT_REQUIRED",))
    external = receipt.get("external_identity_bindings")
    checks = receipt.get("checks")
    if not isinstance(external, Mapping) or not isinstance(checks, Mapping):
        return CheckResult("FAIL", ("DEPLOYMENT_CONTRACT_RECEIPT_BINDING_INVALID",))
    expected_external = {
        "artifact_bucket_sha256": hashes["artifact_bucket_sha256"],
        "artifact_path_sha256": _text_sha256(str(DEPLOYMENT_CONTRACT_FIXED["artifact_path"])),
        "change_set_name_sha256": _text_sha256(str(DEPLOYMENT_CONTRACT_FIXED["change_set_name"])),
        "deployment_profile_sha256": _text_sha256(
            str(DEPLOYMENT_CONTRACT_FIXED["deployment_profile"])
        ),
        "deployment_role_arn_sha256": hashes["deployment_role_arn_sha256"],
        "stack_name_sha256": _text_sha256(str(DEPLOYMENT_CONTRACT_FIXED["stack_name"])),
    }
    if any(external.get(name) != value for name, value in expected_external.items()):
        return CheckResult("FAIL", ("DEPLOYMENT_CONTRACT_RECEIPT_BINDING_INVALID",))
    if any(checks.get(name) != "PASS" for name in BUCKET_CONTROL_CHECKS):
        return CheckResult("FAIL", ("DEPLOYMENT_BUCKET_CONTROLS_NOT_ATTESTED",))
    return CheckResult("PASS")


def _deployment_policy_result(contract_path: Path) -> CheckResult:
    """Validate the tracked policy while forbidding private operator hashes in Git."""

    contract, error = _read_canonical_json(
        contract_path,
        unavailable_reason="DAY15_DEPLOYMENT_CONTRACT_REQUIRED",
    )
    if error is not None:
        return CheckResult("BLOCKED" if error.endswith("REQUIRED") else "FAIL", (error,))
    assert contract is not None
    expected_keys = {
        *DEPLOYMENT_CONTRACT_FIXED,
        *DEPLOYMENT_CONTRACT_HASH_FIELDS,
        "status",
    }
    if (
        set(contract) != expected_keys
        or any(contract.get(name) != value for name, value in DEPLOYMENT_CONTRACT_FIXED.items())
        or contract.get("status") != "BLOCKED"
        or any(contract.get(name) is not None for name in DEPLOYMENT_CONTRACT_HASH_FIELDS)
    ):
        return CheckResult("FAIL", ("TRACKED_DEPLOYMENT_POLICY_INVALID",))
    return CheckResult("PASS")


def _read_private_g10_receipt(path: Path | None) -> tuple[dict[str, object] | None, str | None]:
    if path is None:
        return None, None
    try:
        metadata = path.lstat()
    except OSError:
        return None, "G10_PRIVATE_RECEIPT_REQUIRED"
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
    ):
        return None, "G10_PRIVATE_RECEIPT_PROTECTION_INVALID"
    value, error = _read_canonical_json(
        path,
        unavailable_reason="G10_PRIVATE_RECEIPT_REQUIRED",
    )
    return value, error


def _g10_candidate_receipt_result(
    sanitized_path: Path | None,
    private_path: Path | None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> CheckResult:
    if sanitized_path is None:
        return CheckResult("BLOCKED", ("G10_SANITIZED_RECEIPT_REQUIRED",))
    receipt, error = _read_canonical_json(
        sanitized_path,
        unavailable_reason="G10_SANITIZED_RECEIPT_REQUIRED",
    )
    if error is not None or receipt is None:
        return CheckResult(
            "BLOCKED" if error and error.endswith("REQUIRED") else "FAIL",
            (error or "G10_SANITIZED_RECEIPT_REQUIRED",),
        )
    private_receipt, private_error = _read_private_g10_receipt(private_path)
    if private_error is not None:
        return CheckResult(
            "BLOCKED" if private_error.endswith("REQUIRED") else "FAIL",
            (private_error,),
        )
    try:
        candidate = build_candidate_descriptor()
        validate_sanitized_receipt(
            receipt,
            expected_candidate=candidate,
            private_receipt=private_receipt,
            validation_time=clock(),
        )
    except CandidateFailure as failure:
        return CheckResult("FAIL", (failure.reason,))
    except ClosureFailure as failure:
        return CheckResult(failure.status, (failure.reason,))
    status = receipt.get("status")
    reasons = receipt.get("reasons")
    if status == "PASS":
        return CheckResult("PASS")
    if (
        status == "BLOCKED"
        and isinstance(reasons, list)
        and all(isinstance(reason, str) for reason in reasons)
    ):
        return CheckResult("BLOCKED", tuple(str(reason) for reason in reasons))
    return CheckResult("FAIL", ("G10_SANITIZED_RECEIPT_STATUS_INVALID",))


def _template_token_binding(template: dict[str, object]) -> bool:
    for name, function in _functions(template).items():
        if not _is_orchestrator(name, function):
            continue
        environment = _properties(function).get("Environment")
        variables = environment.get("Variables") if isinstance(environment, Mapping) else None
        return isinstance(variables, Mapping) and "JUDGE_TOKEN_NOT_AFTER" in variables
    return False


def _aws_cli_tool_result(toolchain: Mapping[str, object]) -> CheckResult:
    contract = toolchain.get("aws_cli")
    if contract != {"status": "PASS", "version": PINNED_AWS_CLI_VERSION}:
        return CheckResult("FAIL", ("AWS_CLI_NOT_EXACTLY_PINNED",))
    executable = shutil.which("aws")
    if executable is None:
        return CheckResult("BLOCKED", ("PINNED_AWS_CLI_UNAVAILABLE",))
    environment = {
        "AWS_CONFIG_FILE": os.devnull,
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    try:
        result = subprocess.run(
            (executable, "--version"),
            cwd=ROOT,
            env=environment,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return CheckResult("BLOCKED", ("PINNED_AWS_CLI_UNAVAILABLE",))
    output = f"{result.stdout}{result.stderr}".strip()
    match = AWS_CLI_VERSION_PATTERN.match(output)
    if result.returncode != 0 or match is None:
        return CheckResult("BLOCKED", ("AWS_CLI_VERSION_UNAVAILABLE",))
    if match.group(1) != PINNED_AWS_CLI_VERSION:
        return CheckResult("FAIL", ("AWS_CLI_VERSION_MISMATCH",))
    return CheckResult("PASS")


def _gate_external(context: GateContext) -> GateResult:
    gate = GATES[9]
    token = validate_judge_token_not_after(context.judge_token_not_after, clock=context.clock)
    statuses = [token.status]
    reasons = [*token.reasons]
    receipt = _g10_candidate_receipt_result(
        context.g10_sanitized_receipt,
        context.g10_private_receipt,
        clock=context.clock,
    )
    statuses.append(receipt.status)
    reasons.extend(receipt.reasons)
    deployment_policy = _deployment_policy_result(context.deployment_contract)
    statuses.append(deployment_policy.status)
    reasons.extend(deployment_policy.reasons)
    if not _template_token_binding(context.template):
        statuses.append("FAIL")
        reasons.append("TEMPLATE_JUDGE_TOKEN_EXPIRY_BINDING_MISSING")
    toolchain, toolchain_error = _read_canonical_json(
        context.toolchain,
        unavailable_reason="DAY15_TOOLCHAIN_RECORD_REQUIRED",
    )
    if toolchain_error:
        statuses.append("BLOCKED" if toolchain_error.endswith("REQUIRED") else "FAIL")
        reasons.append(toolchain_error)
    elif toolchain is not None:
        aws_cli = _aws_cli_tool_result(toolchain)
        statuses.append(aws_cli.status)
        reasons.extend(aws_cli.reasons)
    return _result(gate, combine_status(*statuses), reasons)


def _validate_gate_definitions() -> tuple[str, ...]:
    reasons: list[str] = []
    expected = tuple(f"D15-G{index:02d}" for index in range(1, 11))
    actual = tuple(gate.gate_id for gate in GATES)
    if actual != expected:
        reasons.append("GATE_IDS_INVALID")
    if len({gate.title for gate in GATES}) != len(GATES):
        reasons.append("GATE_TITLES_DUPLICATE")
    return tuple(reasons)


def _payload(results: tuple[GateResult, ...], *, mode: str) -> dict[str, object]:
    counts = {
        status.casefold(): sum(item.status == status for item in results)
        for status in sorted(STATUS_VALUES)
    }
    status = combine_status(*(item.status for item in results))
    ready_for_change_set = mode == "full" and status == "PASS"
    return {
        "aws_calls_performed": False,
        "counts": counts,
        "deployment_authorized": False,
        "deployment_performed": False,
        "gate_count": len(results),
        "gates": [item.as_dict() for item in results],
        "mode": mode,
        "predeploy_change_set_review_required": True,
        "ready_for_change_set": ready_for_change_set,
        "ready_for_deployment": False,
        "schema_version": 2,
        "status": status,
    }


def run_gate(
    *,
    template_path: Path = DEFAULT_TEMPLATE,
    rendered_template_path: Path | None = None,
    artifact: Path = DEFAULT_ARTIFACT,
    lock: Path = DEFAULT_LOCK,
    manifest: Path = DEFAULT_MANIFEST,
    scan_report: Path = DEFAULT_SCAN_REPORT,
    toolchain: Path = DEFAULT_TOOLCHAIN,
    deployment_contract: Path = DEFAULT_DEPLOYMENT_CONTRACT,
    external_receipt: Path = DEFAULT_RECEIPT,
    external_attestation_key: Path | None = None,
    g10_sanitized_receipt: Path | None = None,
    g10_private_receipt: Path | None = None,
    region: str | None,
    judge_token_not_after: str | None,
    lambda_configuration_sha256: str | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    try:
        template = load_template(template_path)
    except TemplateFailure as error:
        results = tuple(_result(gate, "FAIL", (error.reason,)) for gate in GATES)
        return _payload(results, mode="full")
    rendered = None
    if rendered_template_path is not None:
        try:
            rendered = load_template(rendered_template_path)
        except TemplateFailure as error:
            results = tuple(_result(gate, "FAIL", (error.reason,)) for gate in GATES)
            return _payload(results, mode="full")
    context = GateContext(
        template=template,
        template_path=template_path,
        rendered_template=rendered,
        rendered_template_path=rendered_template_path,
        template_has_sam=has_sam_transform(template),
        artifact=artifact,
        lock=lock,
        manifest=manifest,
        scan_report=scan_report,
        toolchain=toolchain,
        external_receipt=external_receipt,
        external_attestation_key=external_attestation_key,
        region=region,
        judge_token_not_after=judge_token_not_after,
        lambda_configuration_sha256=lambda_configuration_sha256,
        clock=clock,
        deployment_contract=deployment_contract,
        g10_sanitized_receipt=g10_sanitized_receipt,
        g10_private_receipt=g10_private_receipt,
    )
    results = (
        _gate_runtime(context),
        _gate_iam(context),
        _gate_retries(context),
        _gate_artifact(context),
        _gate_state(context),
        _gate_region(context),
        _gate_versions(context),
        _gate_observability(context),
        _gate_public_surface(context),
        _gate_external(context),
    )
    return _payload(results, mode="full")


def validate_only() -> dict[str, object]:
    reasons = _validate_gate_definitions()
    results = tuple(_result(gate, "PASS" if not reasons else "FAIL", reasons) for gate in GATES)
    return _payload(results, mode="validate-only")


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--rendered-template", type=Path)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--scan-report", type=Path, default=DEFAULT_SCAN_REPORT)
    parser.add_argument("--toolchain", type=Path, default=DEFAULT_TOOLCHAIN)
    parser.add_argument(
        "--deployment-contract",
        type=Path,
        default=DEFAULT_DEPLOYMENT_CONTRACT,
    )
    parser.add_argument("--g10-sanitized-receipt", type=Path)
    parser.add_argument("--g10-private-receipt", type=Path)
    parser.add_argument("--region")
    parser.add_argument("--judge-token-not-after")
    parser.add_argument("--lambda-configuration-sha256")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = (
        validate_only()
        if args.validate_only
        else run_gate(
            template_path=args.template,
            rendered_template_path=args.rendered_template,
            artifact=args.artifact,
            lock=args.lock,
            manifest=args.manifest,
            scan_report=args.scan_report,
            toolchain=args.toolchain,
            deployment_contract=args.deployment_contract,
            g10_sanitized_receipt=args.g10_sanitized_receipt,
            g10_private_receipt=args.g10_private_receipt,
            region=args.region,
            judge_token_not_after=args.judge_token_not_after,
            lambda_configuration_sha256=args.lambda_configuration_sha256,
        )
    )
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = sorted(reason for gate in payload["gates"] for reason in gate["reasons"])
        print(f"DAY15_GATE {payload['status']} reasons={','.join(reasons) or '-'}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
