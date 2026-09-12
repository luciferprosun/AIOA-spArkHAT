"""Canonical Phase 3 deployment contract and deterministic projections."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
SafeName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"),
]
EnvironmentName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$"),
]


class DeploymentContractError(RuntimeError):
    """Public-safe fixed-reason contract failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class ContractRequirement(StrEnum):
    """How a deployment-contract value obtains authority."""

    REQUIRED = "REQUIRED"
    OPTIONAL_WITH_DEFAULT = "OPTIONAL_WITH_DEFAULT"
    DERIVED = "DERIVED"
    EXTERNAL_OPERATOR_INPUT = "EXTERNAL_OPERATOR_INPUT"


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class ContractField[T](StrictContractModel):
    """One explicitly classified contract field."""

    requirement: ContractRequirement
    value: T | None = None

    @model_validator(mode="after")
    def validate_presence(self) -> Self:
        if self.requirement in {
            ContractRequirement.REQUIRED,
            ContractRequirement.OPTIONAL_WITH_DEFAULT,
            ContractRequirement.DERIVED,
        } and self.value is None:
            raise ValueError(f"{self.requirement.value} fields require a value")
        return self


class ClassifiedSection(StrictContractModel):
    """Require every field in a section to use its reviewed authority class."""

    expected_requirements: ClassVar[Mapping[str, ContractRequirement]] = {}

    @model_validator(mode="after")
    def validate_requirement_classes(self) -> Self:
        if set(self.expected_requirements) != set(type(self).model_fields):
            raise ValueError("section classification coverage is incomplete")
        for name, expected in self.expected_requirements.items():
            value = getattr(self, name)
            if not isinstance(value, ContractField) or value.requirement is not expected:
                raise ValueError(f"{name} must be classified as {expected.value}")
        return self


class ArtifactBucketControls(StrictContractModel):
    encryption_at_rest_required: Literal[True]
    tls_only_required: Literal[True]
    versioning_required: Literal[True]
    ownership_controls_required: Literal[True]
    public_access_block: dict[
        Literal[
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        ],
        Literal[True],
    ]
    lifecycle_expiration_days_max: int = Field(ge=1, le=3)
    noncurrent_version_expiration_days_max: int = Field(ge=1, le=3)

    @model_validator(mode="after")
    def validate_public_access_block(self) -> Self:
        if set(self.public_access_block) != {
            "block_public_acls",
            "block_public_policy",
            "ignore_public_acls",
            "restrict_public_buckets",
        }:
            raise ValueError("all four S3 public-access controls are required")
        return self


class LambdaDefinition(StrictContractModel):
    logical_id: Literal["OrchestratorFunction", "RemediationExecutorFunction"]
    purpose: Literal["READ_PLAN_ORCHESTRATOR", "PRIVATE_REMEDIATION_EXECUTOR"]
    handler: SafeName
    runtime: Literal["python3.12"]
    architecture: Literal["x86_64"]
    memory_mb: Literal[256, 512]
    timeout_seconds: int = Field(ge=1, le=70)
    reserved_concurrency: Literal[1]
    public: bool
    authority: Literal["READ_PLAN", "EXACT_PLAN_AND_CONFIRM_WRITE"]


class ApiDefinition(StrictContractModel):
    topology: Literal["LAMBDA_FUNCTION_URL"]
    public_ingress_default: Literal[False]
    auth: Literal["BOUNDED_JUDGE_BEARER_SECRET"]
    public_routes: tuple[Literal["/", "/health", "/ready"], ...]
    authenticated_read_routes: tuple[
        Literal["/judge/investigate", "/judge/status/{run_id}"], ...
    ]
    public_mutation_routes: tuple[()]
    cors_enabled: Literal[False]

    @model_validator(mode="after")
    def validate_routes(self) -> Self:
        if self.public_routes != ("/", "/health", "/ready"):
            raise ValueError("public routes must be exact and ordered")
        if self.authenticated_read_routes != (
            "/judge/investigate",
            "/judge/status/{run_id}",
        ):
            raise ValueError("authenticated read routes must be exact and ordered")
        return self


class DynamoDbDefinition(StrictContractModel):
    logical_id: Literal["StateTable"]
    billing_mode: Literal["PAY_PER_REQUEST"]
    partition_key: Literal["PK"]
    sort_key: Literal["SK"]
    global_secondary_indexes: tuple[()]
    ttl_enabled: Literal[False]
    ttl_rule: Literal["DURABLE_AUTHORITY_REQUIRES_EXPLICIT_DISPOSITION"]
    encryption_enabled: Literal[True]
    point_in_time_recovery: Literal[True]
    deletion_protection: Literal[True]
    deletion_policy: Literal["Retain"]
    update_replace_policy: Literal["Retain"]


class IamBoundary(StrictContractModel):
    orchestrator_actions: tuple[str, ...]
    executor_actions: tuple[str, ...]
    direct_orchestrator_ec2_writes: tuple[()]
    executor_mutation_actions: tuple[Literal["ec2:StopInstances"], ...]
    read_write_roles_separate: Literal[True]
    autonomy: dict[
        Literal["READ_ONLY", "REMEDIATION", "UNKNOWN"],
        Literal["AUTO", "PLAN_AND_CONFIRM", "NEVER_AUTONOMOUS"],
    ]

    @model_validator(mode="after")
    def validate_separation(self) -> Self:
        if len(set(self.orchestrator_actions)) != len(self.orchestrator_actions):
            raise ValueError("orchestrator action allowlist contains duplicates")
        if len(set(self.executor_actions)) != len(self.executor_actions):
            raise ValueError("executor action allowlist contains duplicates")
        if tuple(sorted(self.orchestrator_actions)) != self.orchestrator_actions:
            raise ValueError("orchestrator actions must be sorted")
        if tuple(sorted(self.executor_actions)) != self.executor_actions:
            raise ValueError("executor actions must be sorted")
        if "ec2:StopInstances" in self.orchestrator_actions:
            raise ValueError("orchestrator must not receive direct StopInstances authority")
        if self.autonomy != {
            "READ_ONLY": "AUTO",
            "REMEDIATION": "PLAN_AND_CONFIRM",
            "UNKNOWN": "NEVER_AUTONOMOUS",
        }:
            raise ValueError("Non-Zero authority classes are contradictory")
        return self


class ModelDefinition(StrictContractModel):
    provider: Literal["AMAZON_BEDROCK"]
    model_id: Literal["eu.amazon.nova-2-lite-v1:0"]
    region: Literal["eu-central-1"]
    invocation_action: Literal["bedrock:InvokeModelWithResponseStream"]
    max_output_tokens: Literal[1024]
    fallback_policy: Literal["FAIL_CLOSED_NO_MODEL_FALLBACK"]


class ObservabilityDefinition(StrictContractModel):
    log_retention_days: Literal[3]
    tracing: Literal["ACTIVE_XRAY_BOUNDED_OTEL"]
    trace_sample_ratio: float = Field(ge=0.0, le=0.05)
    alarms: tuple[
        Literal[
            "ORCHESTRATOR_ERRORS",
            "ORCHESTRATOR_THROTTLES",
            "ORCHESTRATOR_DURATION",
            "EXECUTOR_ERRORS",
            "EXECUTOR_THROTTLES",
            "EXECUTOR_DURATION",
            "DYNAMODB_THROTTLED_REQUESTS",
        ],
        ...,
    ]
    provisioned_concurrency: Literal[False]


class CostDefinition(StrictContractModel):
    table_capacity: Literal["ON_DEMAND"]
    provisioned_concurrency: Literal[False]
    max_judge_investigations: Literal[10]
    max_model_output_tokens_per_run: Literal[1024]
    budget_thresholds_usd: tuple[Literal[10, 25, 40], ...]
    retained_state_requires_operator_disposition: Literal[True]

    @model_validator(mode="after")
    def validate_thresholds(self) -> Self:
        if self.budget_thresholds_usd != (10, 25, 40):
            raise ValueError("budget thresholds must be exactly 10/25/40 USD")
        return self


class VerificationDefinition(StrictContractModel):
    health_path: Literal["/health"]
    readiness_path: Literal["/ready"]
    ordered_chain: tuple[
        Literal[
            "AUTHORIZED_IDENTITY",
            "ACCOUNT_REGION_MATCH",
            "API_HEALTH",
            "AGENT_REQUEST",
            "DURABLE_PROVENANCE",
            "HITL_PAUSE",
            "EXPLICIT_DECISION",
            "APPROVED_REMEDIATION",
            "INDEPENDENT_EVIDENCE",
            "REPLAY_REJECTION",
            "RECOVERY_RECONCILIATION",
        ],
        ...,
    ]
    deny_path_required: Literal[True]
    fail_closed_path_required: Literal[True]
    live_mode_default: Literal[False]


class ReleaseSection(ClassifiedSection):
    expected_requirements = {
        "rc_identifier": ContractRequirement.REQUIRED,
        "version": ContractRequirement.REQUIRED,
        "branch": ContractRequirement.REQUIRED,
        "commit_binding": ContractRequirement.DERIVED,
    }

    rc_identifier: ContractField[SafeName]
    version: ContractField[SafeName]
    branch: ContractField[Literal["main"]]
    commit_binding: ContractField[Literal["CURRENT_CLEAN_ORIGIN_MAIN_AT_ATTESTATION"]]


class IdentitySection(ClassifiedSection):
    expected_requirements = {
        "partition": ContractRequirement.REQUIRED,
        "target_regions": ContractRequirement.REQUIRED,
        "expected_account_id_sha256": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "deployment_profile": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "deployment_role_name": ContractRequirement.REQUIRED,
        "deployment_role_arn_sha256": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
    }

    partition: ContractField[Literal["aws"]]
    target_regions: ContractField[tuple[Literal["eu-central-1"], ...]]
    expected_account_id_sha256: ContractField[Sha256Digest]
    deployment_profile: ContractField[Literal["aioa-day15-deployer"]]
    deployment_role_name: ContractField[Literal["AIOANonZeroCloudOpsDay15DeploymentRole"]]
    deployment_role_arn_sha256: ContractField[Sha256Digest]

    @model_validator(mode="after")
    def validate_regions(self) -> Self:
        if self.target_regions.value != ("eu-central-1",):
            raise ValueError("deployment region is frozen to eu-central-1")
        return self


class ApplicationSection(ClassifiedSection):
    expected_requirements = {
        "stack_name": ContractRequirement.REQUIRED,
        "application_name": ContractRequirement.REQUIRED,
        "stage": ContractRequirement.OPTIONAL_WITH_DEFAULT,
        "resource_prefix": ContractRequirement.REQUIRED,
        "ownership_tags": ContractRequirement.REQUIRED,
    }

    stack_name: ContractField[Literal["aioa-nonzero-cloudops-day15"]]
    application_name: ContractField[Literal["aioa-nonzero-cloudops-agent"]]
    stage: ContractField[Literal["hackathon"]]
    resource_prefix: ContractField[Literal["aioa-nonzero"]]
    ownership_tags: ContractField[dict[SafeName, SafeName]]

    @model_validator(mode="after")
    def validate_tags(self) -> Self:
        if self.ownership_tags.value != {
            "AIOAProject": "NonZeroCloudOps",
            "AIOAStage": "hackathon",
            "ManagedBy": "CloudFormation",
        }:
            raise ValueError("ownership tags must be exact")
        return self


class InfrastructureSection(ClassifiedSection):
    expected_requirements = {
        "mechanism": ContractRequirement.REQUIRED,
        "template_path": ContractRequirement.REQUIRED,
        "artifact_object_path": ContractRequirement.REQUIRED,
        "artifact_bucket_sha256": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "artifact_bucket_controls": ContractRequirement.REQUIRED,
        "s3_stack_managed": ContractRequirement.REQUIRED,
        "cloudfront_enabled": ContractRequirement.REQUIRED,
    }

    mechanism: ContractField[Literal["AWS_SAM_CLOUDFORMATION"]]
    template_path: ContractField[Literal["infra/sam/template.yaml"]]
    artifact_object_path: ContractField[Literal["day15/reviewed/aioa-lambda.zip"]]
    artifact_bucket_sha256: ContractField[Sha256Digest]
    artifact_bucket_controls: ContractField[ArtifactBucketControls]
    s3_stack_managed: ContractField[Literal[False]]
    cloudfront_enabled: ContractField[Literal[False]]


class RuntimeSection(ClassifiedSection):
    expected_requirements = {
        "lambda_functions": ContractRequirement.REQUIRED,
        "api": ContractRequirement.REQUIRED,
        "dynamodb": ContractRequirement.REQUIRED,
        "model": ContractRequirement.REQUIRED,
        "iam": ContractRequirement.REQUIRED,
        "environment_variables": ContractRequirement.REQUIRED,
        "feature_flags": ContractRequirement.REQUIRED,
        "judge_secret_logical_id": ContractRequirement.REQUIRED,
        "judge_token_lifetime_seconds_max": ContractRequirement.REQUIRED,
        "sandbox_instance_id_sha256": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "judge_secret_authority_confirmed": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "cloudwatch_evidence_confirmed": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "model_access_confirmed": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
    }

    lambda_functions: ContractField[tuple[LambdaDefinition, ...]]
    api: ContractField[ApiDefinition]
    dynamodb: ContractField[DynamoDbDefinition]
    model: ContractField[ModelDefinition]
    iam: ContractField[IamBoundary]
    environment_variables: ContractField[
        dict[Literal["orchestrator", "executor"], tuple[EnvironmentName, ...]]
    ]
    feature_flags: ContractField[dict[EnvironmentName, str]]
    judge_secret_logical_id: ContractField[Literal["JudgeTokenSecret"]]
    judge_token_lifetime_seconds_max: ContractField[Literal[86400]]
    sandbox_instance_id_sha256: ContractField[Sha256Digest]
    judge_secret_authority_confirmed: ContractField[Literal[True]]
    cloudwatch_evidence_confirmed: ContractField[Literal[True]]
    model_access_confirmed: ContractField[Literal[True]]

    @model_validator(mode="after")
    def validate_runtime(self) -> Self:
        functions = self.lambda_functions.value or ()
        if tuple(item.logical_id for item in functions) != (
            "OrchestratorFunction",
            "RemediationExecutorFunction",
        ):
            raise ValueError("the exact two Lambda functions are required")
        flags = self.feature_flags.value
        if flags != {
            "AIOA_ALLOW_LIVE_SANDBOX_STOP": "false",
            "AIOA_EMERGENCY_EXECUTION_DISABLED": "true",
            "AWS_MUTATIONS_ENABLED": "false",
            "PUBLIC_INGRESS_ENABLED": "false",
        }:
            raise ValueError("release feature flags must remain fail closed")
        variables = self.environment_variables.value or {}
        if any(tuple(sorted(set(names))) != names for names in variables.values()):
            raise ValueError("environment-variable names must be sorted and unique")
        return self


class OperationsSection(ClassifiedSection):
    expected_requirements = {
        "observability": ContractRequirement.REQUIRED,
        "cost": ContractRequirement.REQUIRED,
        "budget_owner_sha256": ContractRequirement.EXTERNAL_OPERATOR_INPUT,
        "verification": ContractRequirement.REQUIRED,
        "rollback_policy": ContractRequirement.REQUIRED,
        "post_deploy_endpoints": ContractRequirement.DERIVED,
    }

    observability: ContractField[ObservabilityDefinition]
    cost: ContractField[CostDefinition]
    budget_owner_sha256: ContractField[Sha256Digest]
    verification: ContractField[VerificationDefinition]
    rollback_policy: ContractField[Literal["OWNERSHIP_BOUND_EXPLICIT_APPROVAL_ONLY"]]
    post_deploy_endpoints: ContractField[tuple[Literal["/health", "/ready"], ...]]

    @model_validator(mode="after")
    def validate_endpoints(self) -> Self:
        if self.post_deploy_endpoints.value != ("/health", "/ready"):
            raise ValueError("post-deploy endpoints must be exact and ordered")
        return self


class AwsDeploymentContract(StrictContractModel):
    """Single current source of deployment policy for the local Phase 3 RC."""

    schema_version: Literal[3]
    contract_id: Literal["AIOA_PHASE3_AWS_DEPLOYMENT_CONTRACT"]
    release: ReleaseSection
    identity: IdentitySection
    application: ApplicationSection
    infrastructure: InfrastructureSection
    runtime: RuntimeSection
    operations: OperationsSection

    @model_validator(mode="after")
    def validate_cross_section_invariants(self) -> Self:
        model = self.runtime.model.value
        regions = self.identity.target_regions.value
        if model is None or regions is None or model.region not in regions:
            raise ValueError("model and deployment regions must match")
        if self.application.stage.value not in self.application.ownership_tags.value.values():
            raise ValueError("stage must be bound into ownership tags")
        return self


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def pretty_json(value: object) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True) + "\n"


def _strict_json(raw: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, item in values:
            if name in result:
                raise DeploymentContractError("DEPLOYMENT_CONTRACT_DUPLICATE_KEY")
            result[name] = item
        return result

    def reject_constant(_value: str) -> None:
        raise DeploymentContractError("DEPLOYMENT_CONTRACT_NONFINITE_VALUE")

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=reject_constant)
    except DeploymentContractError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise DeploymentContractError("DEPLOYMENT_CONTRACT_JSON_INVALID") from error


def load_deployment_contract(path: Path) -> AwsDeploymentContract:
    """Load one strict contract without interpolating environment or credentials."""

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise DeploymentContractError("DEPLOYMENT_CONTRACT_UNAVAILABLE") from error
    try:
        _strict_json(raw)
        return AwsDeploymentContract.model_validate_json(raw)
    except ValidationError as error:
        raise DeploymentContractError("DEPLOYMENT_CONTRACT_SCHEMA_INVALID") from error


def contract_sha256(contract: AwsDeploymentContract) -> str:
    payload = contract.model_dump(mode="json")
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _walk_classified(
    value: object,
    *,
    path: str = "",
) -> Iterable[tuple[str, ContractField[object]]]:
    if isinstance(value, ContractField):
        yield path, value
        return
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            child_path = f"{path}.{name}" if path else name
            yield from _walk_classified(getattr(value, name), path=child_path)


def operator_input_blockers(contract: AwsDeploymentContract) -> tuple[str, ...]:
    """Return typed blockers for every unresolved external value."""

    blockers = [
        f"EXTERNAL_OPERATOR_INPUT_REQUIRED:{path}"
        for path, field in _walk_classified(contract)
        if field.requirement is ContractRequirement.EXTERNAL_OPERATOR_INPUT
        and field.value is None
    ]
    return tuple(sorted(blockers))


def classified_field_count(contract: AwsDeploymentContract) -> int:
    return sum(1 for _path, _field in _walk_classified(contract))


def render_contract_schema() -> str:
    return pretty_json(AwsDeploymentContract.model_json_schema(mode="validation"))


def _display_value(value: object) -> str:
    if value is None:
        return "`<operator input required>`"
    rendered = canonical_json(_jsonable(value))
    if len(rendered) > 180:
        return f"`sha256:{hashlib.sha256(rendered.encode('utf-8')).hexdigest()}` (structured value)"
    return f"`{rendered}`"


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(name): _jsonable(item) for name, item in value.items()}
    return value


def render_contract_markdown(contract: AwsDeploymentContract) -> str:
    """Render human-readable documentation from the validated JSON source."""

    rows = [
        f"| `{path}` | `{field.requirement.value}` | {_display_value(field.value)} |"
        for path, field in _walk_classified(contract)
    ]
    blockers = operator_input_blockers(contract)
    blocker_lines = [f"- `{reason}`" for reason in blockers]
    return "\n".join(
        [
            "# Phase 3 AWS Deployment Contract",
            "",
            "Status: deployment-ready local policy; live deployment and verification not performed.",
            "",
            f"- Contract ID: `{contract.contract_id}`",
            f"- Schema version: `{contract.schema_version}`",
            f"- Canonical SHA-256: `{contract_sha256(contract)}`",
            f"- Classified fields: `{classified_field_count(contract)}`",
            f"- Unresolved external inputs: `{len(blockers)}`",
            "",
            "This document is generated from `requirements/phase3-deployment-contract.json`. "
            "Edit the JSON source and rerun the builder; do not hand-edit this projection.",
            "The historical `requirements/day15-deployment-contract.json` is only the frozen "
            "Day 15 G10 operator-selection policy and is not a second current architecture source.",
            "",
            "## Classified fields",
            "",
            "| Field | Authority class | Reviewed value |",
            "|---|---|---|",
            *rows,
            "",
            "## Remaining operator inputs",
            "",
            *blocker_lines,
            "",
            "Every unresolved value is a typed blocker. None may be inferred from ambient AWS "
            "configuration, guessed from resource names, or replaced by a successful local test.",
            "",
            "## Authority and exposure boundary",
            "",
            "The orchestrator retains read/plan authority and can invoke only the exact private "
            "executor alias. The private executor alone contains the exact `ec2:StopInstances` "
            "authority, constrained by target, region, tag, three disabled-by-default flags, durable "
            "human approval, and emergency veto. The public surface contains no approval or mutation "
            "route. Unknown capabilities remain `NEVER_AUTONOMOUS`.",
            "",
            "## Data, lifecycle, and cost boundary",
            "",
            "The retained on-demand DynamoDB table intentionally has no TTL because durable authority "
            "and evidence require explicit disposition. Cleanup therefore needs ownership proof and "
            "separate operator approval. Logs expire after three days, concurrency and model output are "
            "bounded, the packaging bucket is external and short-lived, and CloudFront is not part of "
            "the current architecture.",
            "",
        ]
    )


_SENSITIVE_PATTERN = re.compile(
    r"(?:AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|-----BEGIN [A-Z ]+PRIVATE KEY-----)"
)


def validate_contract_has_no_secret_material(contract: AwsDeploymentContract) -> None:
    rendered = canonical_json(contract.model_dump(mode="json"))
    if _SENSITIVE_PATTERN.search(rendered) is not None:
        raise DeploymentContractError("DEPLOYMENT_CONTRACT_SECRET_MATERIAL_FORBIDDEN")
