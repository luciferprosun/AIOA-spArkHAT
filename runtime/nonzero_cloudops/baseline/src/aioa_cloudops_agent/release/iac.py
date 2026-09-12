"""Offline-only validation and resource-intent projection for the Phase 3 SAM stack."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .deployment_contract import (
    AwsDeploymentContract,
    canonical_json,
    contract_sha256,
    pretty_json,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
LogicalId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9]{0,254}$")]


class IacValidationError(RuntimeError):
    """A public-safe, fixed-reason IaC validation failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StrictIacModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class IacCheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ResourceAuthority(StrEnum):
    SECRET_AUTH = "SECRET_AUTH"
    DURABLE_STATE = "DURABLE_STATE"
    OBSERVABILITY = "OBSERVABILITY"
    READ_PLAN = "READ_PLAN"
    EXACT_PLAN_AND_CONFIRM_WRITE = "EXACT_PLAN_AND_CONFIRM_WRITE"
    IMMUTABLE_ROLLBACK = "IMMUTABLE_ROLLBACK"
    ROUTING = "ROUTING"
    CONDITIONAL_PUBLIC_READ_INGRESS = "CONDITIONAL_PUBLIC_READ_INGRESS"


class ResourceLifecycle(StrEnum):
    STACK_DELETE = "STACK_DELETE"
    RETAIN_EXPLICIT_DISPOSITION = "RETAIN_EXPLICIT_DISPOSITION"
    CONDITIONAL_STACK_DELETE = "CONDITIONAL_STACK_DELETE"


class OwnershipProof(StrEnum):
    STACK_AND_EXACT_TAGS = "STACK_AND_EXACT_TAGS"
    STACK_MEMBERSHIP_AND_LOGICAL_ID = "STACK_MEMBERSHIP_AND_LOGICAL_ID"


class FutureRequestClass(StrEnum):
    LOCAL = "LOCAL"
    REQUIRES_EXPLICIT_MUTATION_APPROVAL = "REQUIRES_EXPLICIT_MUTATION_APPROVAL"


class IacCheck(StrictIacModel):
    check_id: Annotated[str, StringConstraints(pattern=r"^P3-IAC-[0-9]{2}$")]
    status: IacCheckStatus
    reasons: tuple[Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]+$")], ...] = ()

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if (self.status is IacCheckStatus.PASS) != (not self.reasons):
            raise ValueError("PASS requires no reasons and FAIL requires at least one reason")
        if tuple(sorted(set(self.reasons))) != self.reasons:
            raise ValueError("IaC reasons must be sorted and unique")
        return self


class ResourceIntent(StrictIacModel):
    logical_id: LogicalId
    resource_type: Annotated[str, StringConstraints(pattern=r"^AWS::[A-Za-z0-9]+::[A-Za-z0-9]+$")]
    purpose: Annotated[str, StringConstraints(min_length=3, max_length=160)]
    authority: ResourceAuthority
    ownership_proof: OwnershipProof
    lifecycle: ResourceLifecycle
    cleanup_behavior: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]+$")]
    condition: LogicalId | None
    deletion_policy: Literal["Delete", "Retain"]
    update_replace_policy: Literal["Delete", "Retain"]
    dependencies: tuple[LogicalId, ...]
    creates_or_modifies: Literal["CREATE_IF_EXPLICITLY_APPROVED"]

    @model_validator(mode="after")
    def validate_dependencies(self) -> Self:
        if tuple(sorted(set(self.dependencies))) != self.dependencies:
            raise ValueError("resource dependencies must be sorted and unique")
        if self.logical_id in self.dependencies:
            raise ValueError("resource cannot depend on itself")
        if self.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION and (
            self.deletion_policy != "Retain" or self.update_replace_policy != "Retain"
        ):
            raise ValueError("retained lifecycle requires both retain policies")
        return self


class FutureDeploymentRequest(StrictIacModel):
    request_id: Annotated[str, StringConstraints(pattern=r"^P3-REQ-[0-9]{2}$")]
    service: Literal["local", "s3", "cloudformation"]
    action: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9:._-]+$")]
    request_class: FutureRequestClass
    default_enabled: Literal[False]
    binding: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]+$")]


class ExpectedResourceManifest(StrictIacModel):
    schema_version: Literal[1]
    manifest_id: Literal["AIOA_PHASE3_EXPECTED_AWS_RESOURCES"]
    mode: Literal["OFFLINE_TEMPLATE_DRY_RUN"]
    status: Literal["PASS"]
    mechanism: Literal["AWS_SAM_CLOUDFORMATION"]
    template_path: Literal["infra/sam/template.yaml"]
    template_sha256: Sha256Digest
    deployment_contract_sha256: Sha256Digest
    checks: tuple[IacCheck, ...]
    resources: tuple[ResourceIntent, ...]
    future_requests: tuple[FutureDeploymentRequest, ...]
    resource_count: int = Field(ge=1, le=100)
    tagged_resource_count: int = Field(ge=1, le=100)
    retained_resource_count: int = Field(ge=0, le=100)
    conditional_public_resource_count: int = Field(ge=0, le=10)
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        if any(check.status is not IacCheckStatus.PASS for check in self.checks):
            raise ValueError("a PASS manifest may contain only passing checks")
        if tuple(check.check_id for check in self.checks) != tuple(
            f"P3-IAC-{number:02d}" for number in range(1, 12)
        ):
            raise ValueError("the exact ordered IaC check set is required")
        if tuple(sorted(item.logical_id for item in self.resources)) != tuple(
            item.logical_id for item in self.resources
        ):
            raise ValueError("resources must be ordered by logical ID")
        if len({item.logical_id for item in self.resources}) != len(self.resources):
            raise ValueError("resource logical IDs must be unique")
        if self.resource_count != len(self.resources):
            raise ValueError("resource_count does not match resources")
        retained = sum(
            item.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION
            for item in self.resources
        )
        conditional = sum(
            item.authority is ResourceAuthority.CONDITIONAL_PUBLIC_READ_INGRESS
            for item in self.resources
        )
        if self.retained_resource_count != retained:
            raise ValueError("retained_resource_count does not match resources")
        if self.conditional_public_resource_count != conditional:
            raise ValueError("conditional public count does not match resources")
        return self


class _DuplicateSafeLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: _DuplicateSafeLoader,
    node: yaml.nodes.MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    result: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as error:
            raise IacValidationError("IAC_TEMPLATE_MAPPING_KEY_INVALID") from error
        if duplicate:
            raise IacValidationError("IAC_TEMPLATE_DUPLICATE_KEY")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_DuplicateSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


_TAGGABLE_TYPES = frozenset(
    {
        "AWS::CloudWatch::Alarm",
        "AWS::DynamoDB::Table",
        "AWS::IAM::Role",
        "AWS::Logs::LogGroup",
        "AWS::SecretsManager::Secret",
        "AWS::Serverless::Function",
    }
)

_ALLOWED_TYPES = frozenset(
    {
        *_TAGGABLE_TYPES,
        "AWS::Lambda::Alias",
        "AWS::Lambda::Permission",
        "AWS::Lambda::Url",
        "AWS::Lambda::Version",
    }
)

_FORBIDDEN_TYPES = frozenset(
    {
        "AWS::ApiGateway::RestApi",
        "AWS::ApiGatewayV2::Api",
        "AWS::CloudFront::Distribution",
        "AWS::DynamoDB::GlobalTable",
        "AWS::EC2::Instance",
        "AWS::ECS::Service",
        "AWS::RDS::DBInstance",
        "AWS::S3::Bucket",
        "AWS::Serverless::Api",
        "AWS::Serverless::HttpApi",
    }
)

_PURPOSES: dict[str, str] = {
    "JudgeTokenSecret": "Bounded judge bearer-token material",
    "StateTable": "Durable run, approval, idempotency, provenance, and evidence truth",
    "OrchestratorFunctionLogGroup": "Bounded orchestrator logs",
    "RemediationExecutorLogGroup": "Bounded private executor logs",
    "RemediationExecutorRole": "Exact private executor read and tagged-instance stop authority",
    "RemediationExecutorFunction": "Private exact-plan-and-confirm remediation executor",
    "RemediationExecutorVersion": "Immutable reviewed executor rollback target",
    "RemediationExecutorAlias": "Stable routing to one reviewed executor version",
    "OrchestratorRole": "Read, plan, state, model, secret, and exact executor-invoke authority",
    "OrchestratorFunction": "Read/plan judge API and durable HITL orchestration",
    "OrchestratorVersion": "Immutable reviewed orchestrator rollback target",
    "OrchestratorAlias": "Stable routing to one reviewed orchestrator version",
    "OrchestratorFunctionUrl": "Disabled-by-default public read-only judge ingress",
    "PublicFunctionUrlInvokePermission": "Conditional Function URL invocation permission",
    "PublicFunctionInvokeViaUrlPermission": "Conditional invocation-via-URL permission",
    "OrchestratorErrorsAlarm": "Orchestrator error guardrail",
    "OrchestratorThrottlesAlarm": "Orchestrator throttle guardrail",
    "OrchestratorDurationAlarm": "Orchestrator duration guardrail",
    "RemediationExecutorErrorsAlarm": "Executor error guardrail",
    "RemediationExecutorThrottlesAlarm": "Executor throttle guardrail",
    "RemediationExecutorDurationAlarm": "Executor duration guardrail",
    "StateTableThrottledRequestsAlarm": "Durable-state throttle guardrail",
}


def load_iac_template(path: Path) -> dict[str, object]:
    """Load a duplicate-safe local YAML template without environment interpolation."""

    try:
        raw = path.read_text(encoding="utf-8")
        loaded = yaml.load(raw, Loader=_DuplicateSafeLoader)
    except IacValidationError:
        raise
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise IacValidationError("IAC_TEMPLATE_UNAVAILABLE_OR_INVALID") from error
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise IacValidationError("IAC_TEMPLATE_ROOT_INVALID")
    return loaded


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) and all(isinstance(k, str) for k in value) else {}


def _resources(template: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = _mapping(template.get("Resources"))
    if not raw or not all(isinstance(value, dict) for value in raw.values()):
        return {}
    return {name: value for name, value in raw.items() if isinstance(value, dict)}


def _properties(resource: dict[str, object]) -> dict[str, object]:
    return _mapping(resource.get("Properties"))


def _actions(resource: dict[str, object]) -> tuple[str, ...]:
    actions: set[str] = set()
    policies = _properties(resource).get("Policies")
    if not isinstance(policies, list):
        return ()
    for policy in policies:
        document = _mapping(_mapping(policy).get("PolicyDocument"))
        statements = document.get("Statement")
        if not isinstance(statements, list):
            continue
        for statement in statements:
            action = _mapping(statement).get("Action")
            values = [action] if isinstance(action, str) else action
            if isinstance(values, list):
                actions.update(value for value in values if isinstance(value, str))
    return tuple(sorted(actions))


def _normalized_tags(resource: dict[str, object]) -> dict[str, str] | None:
    tags = _properties(resource).get("Tags")
    if isinstance(tags, dict) and all(
        isinstance(key, str) and isinstance(value, str) for key, value in tags.items()
    ):
        return tags
    if not isinstance(tags, list):
        return None
    result: dict[str, str] = {}
    for entry in tags:
        item = _mapping(entry)
        key = item.get("Key")
        value = item.get("Value")
        if not isinstance(key, str) or not isinstance(value, str) or key in result:
            return None
        result[key] = value
    return result


def _check(check_id: str, *reasons: str) -> IacCheck:
    unique = tuple(sorted(set(reasons)))
    return IacCheck(
        check_id=check_id,
        status=IacCheckStatus.FAIL if unique else IacCheckStatus.PASS,
        reasons=unique,
    )


def _parameter_value(template: dict[str, object], name: str) -> dict[str, object]:
    return _mapping(_mapping(template.get("Parameters")).get(name))


def validate_iac(
    template: dict[str, object],
    contract: AwsDeploymentContract,
) -> tuple[IacCheck, ...]:
    """Validate the actual SAM source against the canonical deployment contract."""

    resources = _resources(template)
    types = {
        name: resource.get("Type")
        for name, resource in resources.items()
        if isinstance(resource.get("Type"), str)
    }
    mechanism_reasons: list[str] = []
    if template.get("AWSTemplateFormatVersion") != "2010-09-09":
        mechanism_reasons.append("TEMPLATE_FORMAT_INVALID")
    if template.get("Transform") != "AWS::Serverless-2016-10-31":
        mechanism_reasons.append("SAM_TRANSFORM_INVALID")
    if not resources or len(types) != len(resources):
        mechanism_reasons.append("RESOURCE_MAP_INVALID")

    parameter_reasons: list[str] = []
    if _parameter_value(template, "DeploymentRegion").get("AllowedValues") != [
        "eu-central-1"
    ]:
        parameter_reasons.append("REGION_NOT_FROZEN")
    stage = _parameter_value(template, "AppStage")
    if stage.get("Default") != "hackathon" or stage.get("AllowedValues") != ["hackathon"]:
        parameter_reasons.append("STAGE_NOT_FROZEN")
    expected_parameters = {
        "PublicIngressEnabled": ("false", ["false", "true"]),
        "AwsMutationsEnabled": ("false", ["false"]),
        "AllowLiveSandboxStop": ("false", ["false"]),
        "EmergencyExecutionDisabled": ("true", ["true"]),
    }
    for name, (default, allowed) in expected_parameters.items():
        parameter = _parameter_value(template, name)
        if parameter.get("Default") != default or parameter.get("AllowedValues") != allowed:
            parameter_reasons.append("FEATURE_FLAG_PARAMETER_UNSAFE")
    rules = canonical_json(_mapping(template.get("Rules")))
    if not all(name in rules for name in expected_parameters):
        parameter_reasons.append("PUBLIC_INGRESS_VETO_RULE_INCOMPLETE")

    function_reasons: list[str] = []
    functions = {
        name: value
        for name, value in resources.items()
        if value.get("Type") == "AWS::Serverless::Function"
    }
    expected_functions = contract.runtime.lambda_functions.value or ()
    if set(functions) != {item.logical_id for item in expected_functions}:
        function_reasons.append("LAMBDA_SET_MISMATCH")
    environment_contract = contract.runtime.environment_variables.value or {}
    for definition in expected_functions:
        properties = _properties(functions.get(definition.logical_id, {}))
        expected = {
            "Handler": definition.handler,
            "Runtime": definition.runtime,
            "Architectures": [definition.architecture],
            "MemorySize": definition.memory_mb,
            "Timeout": definition.timeout_seconds,
            "ReservedConcurrentExecutions": definition.reserved_concurrency,
            "CodeUri": "../../dist/day15/aioa-lambda.zip",
            "Tracing": "Active",
        }
        if any(properties.get(name) != value for name, value in expected.items()):
            function_reasons.append("LAMBDA_CONFIGURATION_MISMATCH")
        environment = _mapping(_mapping(properties.get("Environment")).get("Variables"))
        environment_key = (
            "orchestrator" if definition.logical_id == "OrchestratorFunction" else "executor"
        )
        if tuple(sorted(environment)) != environment_contract.get(environment_key):
            function_reasons.append("LAMBDA_ENVIRONMENT_MISMATCH")
        if "ProvisionedConcurrencyConfig" in properties:
            function_reasons.append("PROVISIONED_CONCURRENCY_FORBIDDEN")

    iam_reasons: list[str] = []
    iam = contract.runtime.iam.value
    if iam is None:
        iam_reasons.append("IAM_CONTRACT_MISSING")
    else:
        orchestrator = resources.get("OrchestratorRole", {})
        executor = resources.get("RemediationExecutorRole", {})
        if orchestrator is executor or not orchestrator or not executor:
            iam_reasons.append("IAM_ROLES_NOT_SEPARATE")
        if _actions(orchestrator) != iam.orchestrator_actions:
            iam_reasons.append("ORCHESTRATOR_ACTION_ALLOWLIST_MISMATCH")
        if _actions(executor) != iam.executor_actions:
            iam_reasons.append("EXECUTOR_ACTION_ALLOWLIST_MISMATCH")
        if any("*" in action for action in (*_actions(orchestrator), *_actions(executor))):
            iam_reasons.append("IAM_ACTION_WILDCARD_FORBIDDEN")
        if "ec2:StopInstances" in _actions(orchestrator):
            iam_reasons.append("ORCHESTRATOR_WRITE_AUTHORITY_FORBIDDEN")
        serialized_executor = canonical_json(executor)
        required_stop_fragments = (
            "ec2:StopInstances",
            "instance/${SandboxInstanceId}",
            "aws:RequestedRegion",
            "eu-central-1",
            "aws:ResourceTag/AIOACloudOpsSandbox",
        )
        if not all(value in serialized_executor for value in required_stop_fragments):
            iam_reasons.append("EXECUTOR_STOP_SCOPE_INVALID")
    for resource in resources.values():
        serialized = canonical_json(resource)
        if '"NotAction"' in serialized or '"NotResource"' in serialized:
            iam_reasons.append("IAM_NEGATIVE_SCOPE_FORBIDDEN")

    data_reasons: list[str] = []
    table = resources.get("StateTable", {})
    table_properties = _properties(table)
    expected_table = contract.runtime.dynamodb.value
    if expected_table is None or table.get("Type") != "AWS::DynamoDB::Table":
        data_reasons.append("DYNAMODB_TABLE_MISSING")
    else:
        if table.get("DeletionPolicy") != "Retain" or table.get("UpdateReplacePolicy") != "Retain":
            data_reasons.append("DYNAMODB_RETENTION_INVALID")
        exact_properties = {
            "BillingMode": "PAY_PER_REQUEST",
            "DeletionProtectionEnabled": True,
            "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
            "SSESpecification": {"SSEEnabled": True},
        }
        if any(table_properties.get(key) != value for key, value in exact_properties.items()):
            data_reasons.append("DYNAMODB_SAFETY_SETTINGS_INVALID")
        if "TimeToLiveSpecification" in table_properties:
            data_reasons.append("DYNAMODB_TTL_CONTRADICTS_DURABLE_AUTHORITY")
        if "GlobalSecondaryIndexes" in table_properties:
            data_reasons.append("DYNAMODB_GSI_UNEXPECTED")
    secret = resources.get("JudgeTokenSecret", {})
    generated = _mapping(_properties(secret).get("GenerateSecretString"))
    if (
        secret.get("Type") != "AWS::SecretsManager::Secret"
        or generated.get("PasswordLength") != 64
        or generated.get("GenerateStringKey") != "token"
        or "JudgeTokenSecret" in _mapping(template.get("Outputs"))
    ):
        data_reasons.append("JUDGE_SECRET_CONTRACT_INVALID")

    ingress_reasons: list[str] = []
    url_resources = {
        name: value for name, value in resources.items() if value.get("Type") == "AWS::Lambda::Url"
    }
    permissions = {
        name: value
        for name, value in resources.items()
        if value.get("Type") == "AWS::Lambda::Permission"
    }
    public_default = _parameter_value(template, "PublicIngressEnabled").get("Default")
    if set(url_resources) != {"OrchestratorFunctionUrl"} or public_default != "false":
        ingress_reasons.append("PUBLIC_INGRESS_DEFAULT_INVALID")
    public_names = {
        "OrchestratorFunctionUrl",
        "PublicFunctionUrlInvokePermission",
        "PublicFunctionInvokeViaUrlPermission",
    }
    if set(permissions) != public_names - {"OrchestratorFunctionUrl"}:
        ingress_reasons.append("PUBLIC_PERMISSION_SET_INVALID")
    for name in public_names:
        if resources.get(name, {}).get("Condition") != "PublicIngressEnabledCondition":
            ingress_reasons.append("PUBLIC_RESOURCE_NOT_CONDITIONED")
    for permission in permissions.values():
        properties = _properties(permission)
        if properties.get("Principal") != "*" or properties.get("FunctionName") != {
            "Ref": "OrchestratorAlias"
        }:
            ingress_reasons.append("PUBLIC_PERMISSION_SCOPE_INVALID")
    if any(resource_type in _FORBIDDEN_TYPES for resource_type in types.values()):
        ingress_reasons.append("PARALLEL_OR_FORBIDDEN_PUBLIC_TOPOLOGY")

    observability_reasons: list[str] = []
    log_groups = [
        value for value in resources.values() if value.get("Type") == "AWS::Logs::LogGroup"
    ]
    alarms = [
        value for value in resources.values() if value.get("Type") == "AWS::CloudWatch::Alarm"
    ]
    observability = contract.operations.observability.value
    if observability is None or len(log_groups) != 2 or any(
        _properties(value).get("RetentionInDays") != 3 for value in log_groups
    ):
        observability_reasons.append("LOG_RETENTION_INVALID")
    if len(alarms) != 7 or any(
        _properties(value).get("TreatMissingData") != "notBreaching" for value in alarms
    ):
        observability_reasons.append("ALARM_GUARDRAILS_INVALID")
    if "ProvisionedConcurrencyConfig" in canonical_json(template):
        observability_reasons.append("PROVISIONED_CONCURRENCY_FORBIDDEN")

    tag_reasons: list[str] = []
    expected_tags = contract.application.ownership_tags.value
    tagged = 0
    for resource in resources.values():
        if resource.get("Type") in _TAGGABLE_TYPES:
            tagged += 1
            if _normalized_tags(resource) != expected_tags:
                tag_reasons.append("OWNERSHIP_TAGS_MISSING_OR_INVALID")
                break
    if tagged != 15:
        tag_reasons.append("TAGGABLE_RESOURCE_COUNT_DRIFT")

    cost_reasons: list[str] = []
    if set(types.values()) - _ALLOWED_TYPES:
        cost_reasons.append("UNREVIEWED_RESOURCE_TYPE")
    cost = contract.operations.cost.value
    if cost is None or table_properties.get("BillingMode") != "PAY_PER_REQUEST":
        cost_reasons.append("UNBOUNDED_TABLE_CAPACITY")
    if any(
        key in canonical_json(template)
        for key in ("ProvisionedThroughput", "DesiredCount", "MinCapacity", "DBInstanceClass")
    ):
        cost_reasons.append("UNBOUNDED_OR_PROVISIONED_COST_SETTING")

    lifecycle_reasons: list[str] = []
    if set(resources) != set(_PURPOSES):
        lifecycle_reasons.append("RESOURCE_LIFECYCLE_COVERAGE_DRIFT")
    retained = {
        name
        for name, resource in resources.items()
        if resource.get("DeletionPolicy") == "Retain"
        or resource.get("UpdateReplacePolicy") == "Retain"
    }
    if retained != {"StateTable", "OrchestratorVersion", "RemediationExecutorVersion"}:
        lifecycle_reasons.append("RETAINED_RESOURCE_SET_DRIFT")

    graph_reasons: list[str] = []
    for name, resource in resources.items():
        dependencies = _resource_dependencies(name, resource, set(resources))
        if any(dependency not in resources for dependency in dependencies):
            graph_reasons.append("RESOURCE_GRAPH_REFERENCE_INVALID")
    if len(resources) != 22:
        graph_reasons.append("RESOURCE_COUNT_DRIFT")

    return (
        _check("P3-IAC-01", *mechanism_reasons),
        _check("P3-IAC-02", *parameter_reasons),
        _check("P3-IAC-03", *function_reasons),
        _check("P3-IAC-04", *iam_reasons),
        _check("P3-IAC-05", *data_reasons),
        _check("P3-IAC-06", *ingress_reasons),
        _check("P3-IAC-07", *observability_reasons),
        _check("P3-IAC-08", *tag_reasons),
        _check("P3-IAC-09", *cost_reasons),
        _check("P3-IAC-10", *lifecycle_reasons),
        _check("P3-IAC-11", *graph_reasons),
    )


def _walk_references(value: object, resources: set[str]) -> set[str]:
    dependencies: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("Ref")
        if isinstance(reference, str) and reference in resources:
            dependencies.add(reference)
        get_att = value.get("Fn::GetAtt")
        if (
            isinstance(get_att, list)
            and get_att
            and isinstance(get_att[0], str)
            and get_att[0] in resources
        ):
            dependencies.add(get_att[0])
        substitution = value.get("Fn::Sub")
        if isinstance(substitution, str):
            dependencies.update(
                name
                for name in re.findall(r"\$\{([A-Za-z][A-Za-z0-9]*)", substitution)
                if name in resources
            )
        for child in value.values():
            dependencies.update(_walk_references(child, resources))
    elif isinstance(value, list):
        for child in value:
            dependencies.update(_walk_references(child, resources))
    return dependencies


def _resource_dependencies(
    logical_id: str,
    resource: dict[str, object],
    resources: set[str],
) -> tuple[str, ...]:
    dependencies = _walk_references(resource, resources)
    explicit = resource.get("DependsOn")
    values = [explicit] if isinstance(explicit, str) else explicit
    if isinstance(values, list):
        dependencies.update(value for value in values if isinstance(value, str))
    dependencies.discard(logical_id)
    return tuple(sorted(dependencies))


def _semantics(logical_id: str, resource: dict[str, object]) -> tuple[
    ResourceAuthority,
    ResourceLifecycle,
    str,
]:
    resource_type = resource.get("Type")
    if logical_id == "JudgeTokenSecret":
        authority = ResourceAuthority.SECRET_AUTH
    elif logical_id == "StateTable":
        authority = ResourceAuthority.DURABLE_STATE
    elif resource_type in {"AWS::Logs::LogGroup", "AWS::CloudWatch::Alarm"}:
        authority = ResourceAuthority.OBSERVABILITY
    elif logical_id.startswith("RemediationExecutor") and resource_type in {
        "AWS::IAM::Role",
        "AWS::Serverless::Function",
    }:
        authority = ResourceAuthority.EXACT_PLAN_AND_CONFIRM_WRITE
    elif logical_id.startswith("Orchestrator") and resource_type in {
        "AWS::IAM::Role",
        "AWS::Serverless::Function",
    }:
        authority = ResourceAuthority.READ_PLAN
    elif resource_type == "AWS::Lambda::Version":
        authority = ResourceAuthority.IMMUTABLE_ROLLBACK
    elif resource_type == "AWS::Lambda::Alias":
        authority = ResourceAuthority.ROUTING
    else:
        authority = ResourceAuthority.CONDITIONAL_PUBLIC_READ_INGRESS

    retained = resource.get("DeletionPolicy") == "Retain"
    conditional = resource.get("Condition") is not None
    if retained:
        return (
            authority,
            ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION,
            "RETAIN_THEN_SEPARATE_OWNERSHIP_BOUND_DISPOSITION",
        )
    if conditional:
        return (
            authority,
            ResourceLifecycle.CONDITIONAL_STACK_DELETE,
            "DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF",
        )
    return authority, ResourceLifecycle.STACK_DELETE, "DELETE_WITH_STACK_AFTER_OWNERSHIP_PROOF"


def build_expected_resource_manifest(
    template: dict[str, object],
    contract: AwsDeploymentContract,
    *,
    template_bytes: bytes,
) -> ExpectedResourceManifest:
    """Build a deterministic manifest only after every offline check passes."""

    checks = validate_iac(template, contract)
    if any(check.status is IacCheckStatus.FAIL for check in checks):
        raise IacValidationError("IAC_DRY_RUN_VALIDATION_FAILED")
    resources = _resources(template)
    resource_names = set(resources)
    intents: list[ResourceIntent] = []
    for logical_id in sorted(resources):
        resource = resources[logical_id]
        resource_type = resource.get("Type")
        if not isinstance(resource_type, str):
            raise IacValidationError("IAC_RESOURCE_TYPE_INVALID")
        authority, lifecycle, cleanup = _semantics(logical_id, resource)
        condition = resource.get("Condition")
        intents.append(
            ResourceIntent(
                logical_id=logical_id,
                resource_type=resource_type,
                purpose=_PURPOSES[logical_id],
                authority=authority,
                ownership_proof=(
                    OwnershipProof.STACK_AND_EXACT_TAGS
                    if resource_type in _TAGGABLE_TYPES
                    else OwnershipProof.STACK_MEMBERSHIP_AND_LOGICAL_ID
                ),
                lifecycle=lifecycle,
                cleanup_behavior=cleanup,
                condition=condition if isinstance(condition, str) else None,
                deletion_policy=resource.get("DeletionPolicy", "Delete"),
                update_replace_policy=resource.get("UpdateReplacePolicy", "Delete"),
                dependencies=_resource_dependencies(logical_id, resource, resource_names),
                creates_or_modifies="CREATE_IF_EXPLICITLY_APPROVED",
            )
        )
    future_requests = (
        FutureDeploymentRequest(
            request_id="P3-REQ-01",
            service="local",
            action="sam:build",
            request_class=FutureRequestClass.LOCAL,
            default_enabled=False,
            binding="REVIEWED_SOURCE_AND_LOCK_HASHES",
        ),
        FutureDeploymentRequest(
            request_id="P3-REQ-02",
            service="s3",
            action="s3:PutObject",
            request_class=FutureRequestClass.REQUIRES_EXPLICIT_MUTATION_APPROVAL,
            default_enabled=False,
            binding="CONTRACT_BUCKET_HASH_AND_ARTIFACT_HASH",
        ),
        FutureDeploymentRequest(
            request_id="P3-REQ-03",
            service="cloudformation",
            action="cloudformation:CreateChangeSet",
            request_class=FutureRequestClass.REQUIRES_EXPLICIT_MUTATION_APPROVAL,
            default_enabled=False,
            binding="ACCOUNT_REGION_STACK_CONTRACT_AND_COMMIT",
        ),
        FutureDeploymentRequest(
            request_id="P3-REQ-04",
            service="cloudformation",
            action="cloudformation:ExecuteChangeSet",
            request_class=FutureRequestClass.REQUIRES_EXPLICIT_MUTATION_APPROVAL,
            default_enabled=False,
            binding="REVIEWED_CHANGE_SET_AND_FRESH_OPERATOR_APPROVAL",
        ),
    )
    tagged_count = sum(
        resource.get("Type") in _TAGGABLE_TYPES for resource in resources.values()
    )
    retained_count = sum(
        intent.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION for intent in intents
    )
    conditional_public_count = sum(
        intent.authority is ResourceAuthority.CONDITIONAL_PUBLIC_READ_INGRESS
        for intent in intents
    )
    return ExpectedResourceManifest(
        schema_version=1,
        manifest_id="AIOA_PHASE3_EXPECTED_AWS_RESOURCES",
        mode="OFFLINE_TEMPLATE_DRY_RUN",
        status="PASS",
        mechanism="AWS_SAM_CLOUDFORMATION",
        template_path="infra/sam/template.yaml",
        template_sha256=hashlib.sha256(template_bytes).hexdigest(),
        deployment_contract_sha256=contract_sha256(contract),
        checks=checks,
        resources=tuple(intents),
        future_requests=future_requests,
        resource_count=len(intents),
        tagged_resource_count=tagged_count,
        retained_resource_count=retained_count,
        conditional_public_resource_count=conditional_public_count,
        network_connections=0,
        aws_mutations=0,
        live_receipts=0,
    )


def render_iac_manifest_schema() -> str:
    return pretty_json(ExpectedResourceManifest.model_json_schema(mode="validation"))


def render_iac_manifest_markdown(manifest: ExpectedResourceManifest) -> str:
    rows = [
        "| "
        + " | ".join(
            (
                f"`{item.logical_id}`",
                f"`{item.resource_type}`",
                item.purpose,
                f"`{item.authority.value}`",
                f"`{item.lifecycle.value}`",
                f"`{item.ownership_proof.value}`",
                f"`{item.cleanup_behavior}`",
            )
        )
        + " |"
        for item in manifest.resources
    ]
    requests = [
        f"- `{item.request_id}` — `{item.service}:{item.action}`; "
        f"`{item.request_class.value}`; disabled by default; binding `{item.binding}`."
        for item in manifest.future_requests
    ]
    return "\n".join(
        [
            "# Phase 3 Expected AWS Resource Manifest",
            "",
            "Status: deterministic offline dry-run only. No AWS account was contacted and no "
            "resource was created or modified.",
            "",
            f"- Template SHA-256: `{manifest.template_sha256}`",
            f"- Deployment contract SHA-256: `{manifest.deployment_contract_sha256}`",
            f"- Intended resources: `{manifest.resource_count}`",
            f"- Explicitly tagged resources: `{manifest.tagged_resource_count}`",
            f"- Retained resources requiring separate disposition: `{manifest.retained_resource_count}`",
            f"- Conditional public-ingress resources: "
            f"`{manifest.conditional_public_resource_count}`",
            "- Offline network connections: `0`",
            "- AWS mutations: `0`",
            "- Live receipts: `0`",
            "",
            "This document is generated from the duplicate-safe parse of "
            "`infra/sam/template.yaml` and the canonical Phase 3 deployment contract.",
            "",
            "## Resources",
            "",
            "| Logical ID | Type | Purpose | Authority | Lifecycle | Ownership proof | Cleanup |",
            "|---|---|---|---|---|---|---|",
            *rows,
            "",
            "## Future request boundary",
            "",
            *requests,
            "",
            "Only `P3-REQ-01` is local. Every AWS-side request remains disabled and requires a "
            "fresh, deployment-bound operator decision. Creating a change set is treated as a cloud "
            "mutation even though it does not execute the stack.",
            "",
        ]
    )
