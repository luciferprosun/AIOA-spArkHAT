#!/usr/bin/env python3
"""Private, read-only AWS observations for the Day 15 G10 deployment gate.

The adapter deliberately has no ambient-session fallback and no command-line entry
point.  An authorized caller must inject a session that is already bound to the
reviewed profile.  The returned receipt keeps raw identifiers and selected AWS
observations in memory, while its string/repr forms are always redacted.

This module never logs, prints, writes a file, creates infrastructure, mutates a
workload, or discovers EC2 instances.  The only optional workload-like call is one
small synthetic Nova ``Converse`` request whose prompt is fixed here and whose
provider response is deliberately not retained.
"""

from __future__ import annotations

import copy
import json
import math
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Protocol

from botocore.config import Config

from aioa_cloudops_agent.config import NOVA_2_LITE_MIN_TEMPERATURE
from scripts.day15.g10_candidate import (
    ARTIFACT_PATH,
    COMPONENT_KEYS,
    DEPLOYMENT_PROFILE,
    DEPLOYMENT_ROLE_LEAF,
    EMAIL_PATTERN,
    NOVA_PROFILE,
    PRIVATE_TOP_LEVEL_KEYS,
    REGION,
    SELECTION_SOURCES,
    SNS_ARN_PATTERN,
    STACK_NAME,
    CandidateFailure,
    bucket_name_is_valid,
    budget_name_is_valid,
    derive_candidate_digest,
)

EXPECTED_REGION: Final = REGION
EXPECTED_SANDBOX_TAG_KEY: Final = "AIOACloudOpsSandbox"
EXPECTED_SANDBOX_TAG_VALUE: Final = "true"
EXPECTED_NOVA_PROFILE: Final = NOVA_PROFILE
EXPECTED_NOVA_MODEL_REGIONS: Final = frozenset(
    {
        "eu-central-1",
        "eu-north-1",
        "eu-south-1",
        "eu-south-2",
        "eu-west-1",
        "eu-west-3",
    }
)
EXPECTED_BUDGET_THRESHOLDS: Final = (Decimal("10"), Decimal("25"), Decimal("40"))
MAX_SYNTHETIC_TOKENS: Final = 32
MAX_CANONICAL_DOCUMENT_BYTES: Final = 65_536
CONNECT_TIMEOUT_SECONDS: Final = 3
READ_TIMEOUT_SECONDS: Final = 10
BEDROCK_READ_TIMEOUT_SECONDS: Final = 30
TOTAL_MAX_ATTEMPTS: Final = 1
MAX_CLOUDWATCH_WINDOW_SECONDS: Final = 86_400
MAX_OPERATOR_SELECTION_AGE: Final = timedelta(hours=1)
MAX_OPERATOR_SELECTION_FUTURE_SKEW: Final = timedelta(minutes=1)

SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
ACCOUNT_PATTERN: Final = re.compile(r"^[0-9]{12}$")
ROLE_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:iam::(?P<account>[0-9]{12}):role/(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})$"
)
ASSUMED_ROLE_ARN_PATTERN: Final = re.compile(
    r"^arn:aws:sts::(?P<account>[0-9]{12}):assumed-role/"
    r"(?P<name>[A-Za-z0-9+=,.@_/-]{1,512})/(?P<session>[A-Za-z0-9+=,.@_-]{1,128})$"
)
INSTANCE_PATTERN: Final = re.compile(r"^i-[0-9a-f]{8,17}$")
PROFILE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")
VISIBLE_PRIVATE_VALUE_PATTERN: Final = re.compile(r"^[\x21-\x7e]{1,512}$")
CANDIDATE_KEYS: Final = frozenset(
    {"candidate_digest", "components", "region", "schema_version", "source_commit"}
)
COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")

READ_OPERATION_ALLOWLIST: Final = frozenset(
    {
        "bedrock-runtime:Converse",
        "bedrock:GetInferenceProfile",
        "budgets:DescribeBudget",
        "budgets:DescribeNotificationsForBudget",
        "budgets:DescribeSubscribersForNotification",
        "cloudwatch:GetMetricStatistics",
        "ec2:DescribeInstances",
        "iam:SimulatePrincipalPolicy",
        "s3:GetBucketEncryption",
        "s3:GetBucketLifecycleConfiguration",
        "s3:GetBucketLocation",
        "s3:GetBucketOwnershipControls",
        "s3:GetBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketVersioning",
        "sts:GetCallerIdentity",
    }
)
PRIVATE_CHECK_KEYS: Final = frozenset(
    {
        "authenticated_identity_match",
        "budget_notification_owner_ready",
        "cloudwatch_evidence_ready",
        "judge_secret_ready",
        "nova2_profile_access",
        "packaging_bucket_ready",
        "sandbox_read_only_verified",
    }
)
PASS_OPERATION_SEQUENCE: Final = (
    "sts:GetCallerIdentity",
    "s3:GetBucketLocation",
    "s3:GetBucketEncryption",
    "s3:GetBucketPublicAccessBlock",
    "s3:GetBucketOwnershipControls",
    "s3:GetBucketVersioning",
    "s3:GetBucketLifecycleConfiguration",
    "s3:GetBucketPolicy",
    "iam:SimulatePrincipalPolicy",
    "iam:SimulatePrincipalPolicy",
    "ec2:DescribeInstances",
    "cloudwatch:GetMetricStatistics",
    "bedrock:GetInferenceProfile",
    "bedrock-runtime:Converse",
    "budgets:DescribeBudget",
    "budgets:DescribeNotificationsForBudget",
    "budgets:DescribeSubscribersForNotification",
    "budgets:DescribeSubscribersForNotification",
    "budgets:DescribeSubscribersForNotification",
)
PRIVATE_RECEIPT_KEYS: Final = frozenset(
    {
        "call_ledger",
        "candidate",
        "checks",
        "external_prerequisites_pass",
        "identifiers",
        "observations",
        "observed_at",
        "private_contract",
        "read_operation_allowlist",
        "receipt_nonce",
        "reasons",
        "region",
        "schema_version",
        "status",
        "write_operations",
    }
)
_OPERATION_METHODS: Final = {
    "bedrock-runtime:Converse": "converse",
    "bedrock:GetInferenceProfile": "get_inference_profile",
    "budgets:DescribeBudget": "describe_budget",
    "budgets:DescribeNotificationsForBudget": "describe_notifications_for_budget",
    "budgets:DescribeSubscribersForNotification": ("describe_subscribers_for_notification"),
    "cloudwatch:GetMetricStatistics": "get_metric_statistics",
    "ec2:DescribeInstances": "describe_instances",
    "iam:SimulatePrincipalPolicy": "simulate_principal_policy",
    "s3:GetBucketEncryption": "get_bucket_encryption",
    "s3:GetBucketLifecycleConfiguration": "get_bucket_lifecycle_configuration",
    "s3:GetBucketLocation": "get_bucket_location",
    "s3:GetBucketOwnershipControls": "get_bucket_ownership_controls",
    "s3:GetBucketPolicy": "get_bucket_policy",
    "s3:GetBucketPublicAccessBlock": "get_public_access_block",
    "s3:GetBucketVersioning": "get_bucket_versioning",
    "sts:GetCallerIdentity": "get_caller_identity",
}
_SECRET_ACTIONS: Final = (
    "secretsmanager:CreateSecret",
    "secretsmanager:GetSecretValue",
)
_PACKAGING_ACTIONS: Final = ("s3:GetObject", "s3:PutObject")
_SYNTHETIC_PROMPT: Final = "Reply with OK."


class AwsSession(Protocol):
    """Narrow injected session boundary used to construct bounded clients."""

    profile_name: str | None

    def client(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> Any: ...


class ContractValidationError(ValueError):
    """A public-safe reason for rejecting an untrusted observation request."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class PrivateObservationReceipt:
    """Canonical private receipt whose normal representation never exposes values."""

    _canonical: dict[str, object] = field(repr=False)

    @property
    def status(self) -> str:
        return str(self._canonical["status"])

    @property
    def reasons(self) -> tuple[str, ...]:
        values = self._canonical["reasons"]
        assert isinstance(values, list)
        return tuple(str(value) for value in values)

    @property
    def call_ledger(self) -> tuple[dict[str, object], ...]:
        values = self._canonical["call_ledger"]
        assert isinstance(values, list)
        return tuple(copy.deepcopy(value) for value in values if isinstance(value, dict))

    @property
    def write_operations(self) -> tuple[object, ...]:
        values = self._canonical["write_operations"]
        assert isinstance(values, list)
        return tuple(values)

    def private_mapping(self) -> dict[str, object]:
        """Return a private copy for the immediate in-memory gate decision only."""

        return copy.deepcopy(self._canonical)

    def __repr__(self) -> str:
        return (
            "PrivateObservationReceipt("
            f"status={self.status!r}, reasons={len(self.reasons)}, "
            f"calls={len(self.call_ledger)}, raw='REDACTED')"
        )

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class _ValidatedContract:
    raw: dict[str, object]
    account_id: str
    deployment_profile: str
    role_arn: str
    bucket: str
    artifact_prefix: str
    secret_arn: str
    instance_id: str
    cw_start: datetime
    cw_end: datetime
    cw_period: int
    cw_statistic: str
    cw_minimum: int
    nova_profile_id: str
    synthetic_converse: bool
    max_tokens: int
    budget_name: str
    budget_owner: str
    budget_owner_type: str
    stack_name: str


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ContractValidationError("NON_STRING_MAPPING_KEY")
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ContractValidationError("NAIVE_DATETIME_NOT_ALLOWED")
        utc_value = value.astimezone(UTC)
        return utc_value.isoformat(timespec="seconds").replace("+00:00", "Z")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ContractValidationError("NON_FINITE_NUMBER")
        return format(value, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError("NON_FINITE_NUMBER")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ContractValidationError("NON_JSON_VALUE")


def _canonical_mapping(value: Mapping[str, object]) -> dict[str, object]:
    normalized = _json_value(value)
    if not isinstance(normalized, dict):
        raise ContractValidationError("MAPPING_REQUIRED")
    encoded = json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_CANONICAL_DOCUMENT_BYTES:
        raise ContractValidationError("CANONICAL_DOCUMENT_TOO_LARGE")
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    return decoded


def _require_exact_keys(
    value: object,
    keys: frozenset[str],
    reason: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ContractValidationError(reason)
    return value


def _require_text(value: object, reason: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractValidationError(reason)
    return value


def _parse_utc(value: object, reason: str) -> datetime:
    text = _require_text(value, reason, maximum=40)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractValidationError(reason) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractValidationError(reason)
    return parsed.astimezone(UTC)


def _decimal(value: object) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def _validate_contract(
    private_contract: Mapping[str, object],
    *,
    expected_candidate_digest: str,
    observation_time: datetime,
) -> _ValidatedContract:
    contract = _require_exact_keys(
        private_contract,
        PRIVATE_TOP_LEVEL_KEYS,
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    if (
        contract.get("schema_version") != 1
        or contract.get("candidate_digest") != expected_candidate_digest
    ):
        raise ContractValidationError("PRIVATE_CONTRACT_SCHEMA_INVALID")
    if contract.get("region") != EXPECTED_REGION:
        raise ContractValidationError("REGION_MUST_BE_EU_CENTRAL_1")

    account_id = _require_text(contract.get("expected_account_id"), "ACCOUNT_INVALID")
    if ACCOUNT_PATTERN.fullmatch(account_id) is None:
        raise ContractValidationError("ACCOUNT_INVALID")
    profile = _require_text(contract.get("selected_profile"), "PROFILE_INVALID", maximum=128)
    if PROFILE_PATTERN.fullmatch(profile) is None or profile != DEPLOYMENT_PROFILE:
        raise ContractValidationError("PROFILE_INVALID")
    if contract.get("selection_source") not in SELECTION_SOURCES:
        raise ContractValidationError("PROFILE_INVALID")
    role_arn = _require_text(contract.get("deployment_role_arn"), "ROLE_ARN_INVALID")
    role_match = ROLE_ARN_PATTERN.fullmatch(role_arn)
    if (
        role_match is None
        or role_match.group("account") != account_id
        or role_arn.rsplit("/", 1)[-1] != DEPLOYMENT_ROLE_LEAF
    ):
        raise ContractValidationError("ROLE_ARN_INVALID")

    stack_name = _require_text(contract.get("stack_name"), "STACK_NAME_INVALID", maximum=128)
    if stack_name != STACK_NAME:
        raise ContractValidationError("STACK_NAME_INVALID")
    packaging = _require_exact_keys(
        contract.get("packaging"),
        frozenset({"artifact_path", "bucket_name"}),
        "PACKAGING_CONTRACT_INVALID",
    )
    bucket = _require_text(packaging.get("bucket_name"), "BUCKET_INVALID", maximum=63)
    if not bucket_name_is_valid(bucket):
        raise ContractValidationError("BUCKET_INVALID")
    artifact_path = _require_text(
        packaging.get("artifact_path"), "ARTIFACT_PATH_INVALID", maximum=512
    )
    if artifact_path != ARTIFACT_PATH or "/" not in artifact_path:
        raise ContractValidationError("ARTIFACT_PATH_INVALID")
    artifact_prefix = artifact_path.rsplit("/", 1)[0] + "/"

    bootstrap = _require_exact_keys(
        contract.get("bootstrap"),
        frozenset({"create_judge_secret", "create_packaging_bucket"}),
        "BOOTSTRAP_CONTRACT_INVALID",
    )
    if bootstrap != {"create_judge_secret": False, "create_packaging_bucket": False}:
        raise ContractValidationError("BOOTSTRAP_WRITES_FORBIDDEN")
    judge_secret = _require_exact_keys(
        contract.get("judge_secret"),
        frozenset({"creation_policy", "secret_name"}),
        "SECRET_CONTRACT_INVALID",
    )
    secret_name = judge_secret.get("secret_name")
    if judge_secret.get("creation_policy") != "STACK_OWNED" or secret_name is not None:
        raise ContractValidationError("SECRET_CONTRACT_INVALID")
    secret_leaf = f"{stack_name}-JudgeTokenSecret-*"
    secret_arn = f"arn:aws:secretsmanager:{EXPECTED_REGION}:{account_id}:secret:{secret_leaf}"

    sandbox = _require_exact_keys(
        contract.get("sandbox"),
        frozenset(
            {
                "expected_state",
                "instance_id",
                "require_ebs_backed",
                "tag_key",
                "tag_value",
            }
        ),
        "SANDBOX_CONTRACT_INVALID",
    )
    instance_id = _require_text(sandbox.get("instance_id"), "SANDBOX_CONTRACT_INVALID")
    if (
        INSTANCE_PATTERN.fullmatch(instance_id) is None
        or sandbox.get("expected_state") != "running"
        or sandbox.get("require_ebs_backed") is not True
        or sandbox.get("tag_key") != EXPECTED_SANDBOX_TAG_KEY
        or sandbox.get("tag_value") != EXPECTED_SANDBOX_TAG_VALUE
    ):
        raise ContractValidationError("SANDBOX_CONTRACT_INVALID")

    cloudwatch = _require_exact_keys(
        contract.get("cloudwatch"),
        frozenset(
            {
                "metric_name",
                "minimum_datapoints",
                "namespace",
                "observation_window_minutes",
                "period_seconds",
            }
        ),
        "CLOUDWATCH_CONTRACT_INVALID",
    )
    if (
        cloudwatch.get("namespace") != "AWS/EC2"
        or cloudwatch.get("metric_name") != "CPUUtilization"
    ):
        raise ContractValidationError("CLOUDWATCH_CONTRACT_INVALID")
    period = cloudwatch.get("period_seconds")
    minimum = cloudwatch.get("minimum_datapoints")
    window_minutes = cloudwatch.get("observation_window_minutes")
    if (
        isinstance(period, bool)
        or not isinstance(period, int)
        or period != 300
        or isinstance(minimum, bool)
        or not isinstance(minimum, int)
        or minimum != 6
        or isinstance(window_minutes, bool)
        or not isinstance(window_minutes, int)
        or window_minutes != 60
    ):
        raise ContractValidationError("CLOUDWATCH_CONTRACT_INVALID")
    selection_time = _parse_utc(
        contract.get("operator_selection_timestamp"),
        "PRIVATE_CONTRACT_TIMESTAMP_INVALID",
    )
    selection_age = observation_time - selection_time
    if (
        selection_age < -MAX_OPERATOR_SELECTION_FUTURE_SKEW
        or selection_age > MAX_OPERATOR_SELECTION_AGE
    ):
        raise ContractValidationError("PRIVATE_CONTRACT_TIMESTAMP_STALE")
    cw_end = observation_time
    cw_start = cw_end - timedelta(minutes=window_minutes)
    window_seconds = (cw_end - cw_start).total_seconds()
    if not 0 < window_seconds <= MAX_CLOUDWATCH_WINDOW_SECONDS:
        raise ContractValidationError("CLOUDWATCH_CONTRACT_INVALID")

    nova = _require_exact_keys(
        contract.get("nova"),
        frozenset({"allow_bounded_inference_probe", "inference_profile_id", "region"}),
        "NOVA_CONTRACT_INVALID",
    )
    synthetic_converse = nova.get("allow_bounded_inference_probe")
    if (
        nova.get("inference_profile_id") != EXPECTED_NOVA_PROFILE
        or nova.get("region") != EXPECTED_REGION
        or not isinstance(synthetic_converse, bool)
    ):
        raise ContractValidationError("NOVA_CONTRACT_INVALID")

    budget = _require_exact_keys(
        contract.get("budget_notification"),
        frozenset({"budget_name", "owner_binding", "owner_type", "thresholds_usd"}),
        "BUDGET_CONTRACT_INVALID",
    )
    budget_name = _require_text(budget.get("budget_name"), "BUDGET_CONTRACT_INVALID", maximum=100)
    owner = _require_text(budget.get("owner_binding"), "BUDGET_CONTRACT_INVALID", maximum=512)
    owner_type = budget.get("owner_type")
    thresholds = budget.get("thresholds_usd")
    parsed_thresholds = (
        tuple(_decimal(item) for item in thresholds) if isinstance(thresholds, list) else ()
    )
    if (
        VISIBLE_PRIVATE_VALUE_PATTERN.fullmatch(owner) is None
        or not budget_name_is_valid(budget_name)
        or owner_type not in {"EMAIL", "SNS"}
        or (owner_type == "EMAIL" and EMAIL_PATTERN.fullmatch(owner) is None)
        or (
            owner_type == "SNS"
            and (
                (sns_match := SNS_ARN_PATTERN.fullmatch(owner)) is None
                or sns_match.group(1) != account_id
            )
        )
        or parsed_thresholds != EXPECTED_BUDGET_THRESHOLDS
    ):
        raise ContractValidationError("BUDGET_CONTRACT_INVALID")

    raw = _canonical_mapping(private_contract)
    return _ValidatedContract(
        raw=raw,
        account_id=account_id,
        deployment_profile=profile,
        role_arn=role_arn,
        bucket=bucket,
        artifact_prefix=artifact_prefix,
        secret_arn=secret_arn,
        instance_id=instance_id,
        cw_start=cw_start,
        cw_end=cw_end,
        cw_period=period,
        cw_statistic="Average",
        cw_minimum=minimum,
        nova_profile_id=EXPECTED_NOVA_PROFILE,
        synthetic_converse=synthetic_converse,
        max_tokens=MAX_SYNTHETIC_TOKENS,
        budget_name=budget_name,
        budget_owner=owner,
        budget_owner_type=str(owner_type),
        stack_name=stack_name,
    )


def _validate_candidate(
    candidate_descriptor: Mapping[str, object],
    candidate_digest: str,
) -> tuple[dict[str, object], str]:
    candidate = _require_exact_keys(
        candidate_descriptor, CANDIDATE_KEYS, "CANDIDATE_DESCRIPTOR_INVALID"
    )
    if candidate.get("schema_version") != 1 or candidate.get("region") != EXPECTED_REGION:
        raise ContractValidationError("CANDIDATE_DESCRIPTOR_INVALID")
    source_commit = candidate.get("source_commit")
    components = candidate.get("components")
    if (
        not isinstance(source_commit, str)
        or COMMIT_PATTERN.fullmatch(source_commit) is None
        or not isinstance(components, Mapping)
        or set(components) != COMPONENT_KEYS
        or any(
            not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None
            for value in components.values()
        )
        or not isinstance(candidate.get("candidate_digest"), str)
        or SHA256_PATTERN.fullmatch(candidate_digest) is None
        or candidate_digest != candidate.get("candidate_digest")
    ):
        raise ContractValidationError("CANDIDATE_DIGEST_MISMATCH")
    component_values = {str(key): str(value) for key, value in components.items()}
    try:
        expected_digest = derive_candidate_digest(
            source_commit=source_commit,
            region=EXPECTED_REGION,
            components=component_values,
        )
    except CandidateFailure as error:
        raise ContractValidationError("CANDIDATE_DESCRIPTOR_INVALID") from error
    if expected_digest != candidate_digest:
        raise ContractValidationError("CANDIDATE_DIGEST_MISMATCH")
    canonical = _canonical_mapping(candidate_descriptor)
    return canonical, candidate_digest


def _bounded_config(service_name: str) -> Config:
    read_timeout = (
        BEDROCK_READ_TIMEOUT_SECONDS
        if service_name in {"bedrock", "bedrock-runtime"}
        else READ_TIMEOUT_SECONDS
    )
    return Config(
        region_name=EXPECTED_REGION,
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=read_timeout,
        ignore_configured_endpoint_urls=True,
        retries={"mode": "standard", "total_max_attempts": TOTAL_MAX_ATTEMPTS},
    )


@dataclass(slots=True)
class _Context:
    session: AwsSession
    monotonic_clock: Callable[[], float] = time.monotonic
    clients: dict[str, Any] = field(default_factory=dict)
    ledger: list[dict[str, object]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def reason(self, value: str) -> None:
        if value not in self.reasons:
            self.reasons.append(value)

    def _client(self, service_name: str) -> Any | None:
        if service_name in self.clients:
            return self.clients[service_name]
        try:
            client = self.session.client(
                service_name,
                region_name=EXPECTED_REGION,
                config=_bounded_config(service_name),
            )
        except Exception:  # An SDK error message may contain private endpoint/identity data.
            self.reason(f"CLIENT_CREATION_FAILED:{service_name.upper()}")
            return None
        self.clients[service_name] = client
        return client

    def call(
        self,
        operation: str,
        parameters: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        if operation not in READ_OPERATION_ALLOWLIST or operation not in _OPERATION_METHODS:
            raise AssertionError("operation is not in the immutable read allowlist")
        service_name = operation.split(":", 1)[0]
        client = self._client(service_name)
        if client is None:
            return None
        self.ledger.append(
            {
                "operation": operation,
                "sequence": len(self.ledger) + 1,
                "write": False,
            }
        )
        try:
            method = getattr(client, _OPERATION_METHODS[operation])
            response = method(**dict(parameters))
        except Exception:  # Never retain/log raw SDK exceptions.
            self.reason(f"AWS_CALL_FAILED:{operation.upper().replace(':', '_')}")
            return None
        if not isinstance(response, Mapping):
            self.reason(f"AWS_RESPONSE_INVALID:{operation.upper().replace(':', '_')}")
            return None
        return response


def _without_metadata(response: Mapping[str, object]) -> dict[str, object]:
    return _canonical_mapping(
        {key: value for key, value in response.items() if key != "ResponseMetadata"}
    )


def _principal_matches(expected_role_arn: str, observed_arn: object, account_id: str) -> bool:
    if observed_arn == expected_role_arn:
        return True
    if not isinstance(observed_arn, str):
        return False
    expected = ROLE_ARN_PATTERN.fullmatch(expected_role_arn)
    observed = ASSUMED_ROLE_ARN_PATTERN.fullmatch(observed_arn)
    if expected is None or observed is None or observed.group("account") != account_id:
        return False
    expected_leaf = expected.group("name").rsplit("/", 1)[-1]
    observed_leaf = observed.group("name").rsplit("/", 1)[-1]
    return expected_leaf == observed_leaf


def _s3_policy_is_tls_only(policy_value: object, bucket: str) -> bool:
    if not isinstance(policy_value, str) or len(policy_value) > MAX_CANONICAL_DOCUMENT_BYTES:
        return False
    try:
        policy = json.loads(policy_value)
    except json.JSONDecodeError:
        return False
    if not isinstance(policy, Mapping):
        return False
    statements = policy.get("Statement")
    if isinstance(statements, Mapping):
        statements = [statements]
    if not isinstance(statements, list):
        return False
    required_resources = {f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"}
    for statement in statements:
        if not isinstance(statement, Mapping):
            continue
        action = statement.get("Action")
        actions = {action} if isinstance(action, str) else set(action or [])
        resource = statement.get("Resource")
        resources = {resource} if isinstance(resource, str) else set(resource or [])
        condition = statement.get("Condition")
        if not isinstance(condition, Mapping):
            continue
        bool_condition = condition.get("Bool")
        if not isinstance(bool_condition, Mapping):
            continue
        secure_transport = bool_condition.get("aws:SecureTransport")
        if (
            statement.get("Effect") == "Deny"
            and statement.get("Principal") == "*"
            and "s3:*" in actions
            and required_resources <= resources
            and str(secure_transport).lower() == "false"
        ):
            return True
    return False


def _lifecycle_is_bounded(response: Mapping[str, object], prefix: str) -> bool:
    rules = response.get("Rules")
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, Mapping) or rule.get("Status") != "Enabled":
            continue
        rule_prefix: object = rule.get("Prefix")
        filter_value = rule.get("Filter")
        if isinstance(filter_value, Mapping):
            rule_prefix = filter_value.get("Prefix")
        expiration = rule.get("Expiration")
        days = expiration.get("Days") if isinstance(expiration, Mapping) else None
        noncurrent = rule.get("NoncurrentVersionExpiration")
        noncurrent_days = (
            noncurrent.get("NoncurrentDays") if isinstance(noncurrent, Mapping) else None
        )
        if (
            rule_prefix == prefix
            and isinstance(days, int)
            and not isinstance(days, bool)
            and 1 <= days <= 3
            and isinstance(noncurrent_days, int)
            and not isinstance(noncurrent_days, bool)
            and 1 <= noncurrent_days <= 3
        ):
            return True
    return False


def _observe_s3(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    bucket = contract.bucket
    bucket_parameters = {
        "Bucket": bucket,
        "ExpectedBucketOwner": contract.account_id,
    }
    responses: dict[str, object] = {}
    operations = (
        ("location", "s3:GetBucketLocation", bucket_parameters),
        ("encryption", "s3:GetBucketEncryption", bucket_parameters),
        ("public_access_block", "s3:GetBucketPublicAccessBlock", bucket_parameters),
        ("ownership", "s3:GetBucketOwnershipControls", bucket_parameters),
        ("versioning", "s3:GetBucketVersioning", bucket_parameters),
        (
            "lifecycle",
            "s3:GetBucketLifecycleConfiguration",
            bucket_parameters,
        ),
        ("policy", "s3:GetBucketPolicy", bucket_parameters),
    )
    raw: dict[str, Mapping[str, object]] = {}
    for name, operation, parameters in operations:
        response = context.call(operation, parameters)
        if response is not None:
            raw[name] = response
            responses[name] = _without_metadata(response)
    observations["artifact_bucket"] = responses

    location = raw.get("location")
    if location is not None and location.get("LocationConstraint") != EXPECTED_REGION:
        context.reason("S3_BUCKET_REGION_MISMATCH")
    encryption = raw.get("encryption")
    if encryption is not None:
        configuration = encryption.get("ServerSideEncryptionConfiguration")
        rules = configuration.get("Rules") if isinstance(configuration, Mapping) else None
        encrypted = False
        if isinstance(rules, list):
            for rule in rules:
                default = (
                    rule.get("ApplyServerSideEncryptionByDefault")
                    if isinstance(rule, Mapping)
                    else None
                )
                if isinstance(default, Mapping) and default.get("SSEAlgorithm") in {
                    "AES256",
                    "aws:kms",
                    "aws:kms:dsse",
                }:
                    encrypted = True
        if not encrypted:
            context.reason("S3_BUCKET_ENCRYPTION_INVALID")
    public_block = raw.get("public_access_block")
    if public_block is not None:
        configuration = public_block.get("PublicAccessBlockConfiguration")
        required = (
            "BlockPublicAcls",
            "BlockPublicPolicy",
            "IgnorePublicAcls",
            "RestrictPublicBuckets",
        )
        if not isinstance(configuration, Mapping) or not all(
            configuration.get(key) is True for key in required
        ):
            context.reason("S3_PUBLIC_ACCESS_BLOCK_INVALID")
    ownership = raw.get("ownership")
    if ownership is not None:
        rules = ownership.get("OwnershipControls", {})
        rules = rules.get("Rules") if isinstance(rules, Mapping) else None
        if not isinstance(rules, list) or not any(
            isinstance(rule, Mapping) and rule.get("ObjectOwnership") == "BucketOwnerEnforced"
            for rule in rules
        ):
            context.reason("S3_OWNERSHIP_CONTROLS_INVALID")
    versioning = raw.get("versioning")
    if versioning is not None and versioning.get("Status") != "Enabled":
        context.reason("S3_VERSIONING_INVALID")
    lifecycle = raw.get("lifecycle")
    if lifecycle is not None and not _lifecycle_is_bounded(lifecycle, contract.artifact_prefix):
        context.reason("S3_LIFECYCLE_INVALID")
    policy = raw.get("policy")
    if policy is not None and not _s3_policy_is_tls_only(policy.get("Policy"), bucket):
        context.reason("S3_TLS_POLICY_INVALID")


def _observe_iam(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    simulations = (
        (
            "secret_capability",
            _SECRET_ACTIONS,
            contract.secret_arn,
            "JUDGE_SECRET_CAPABILITY_NOT_ALLOWED",
        ),
        (
            "artifact_path_capability",
            _PACKAGING_ACTIONS,
            f"arn:aws:s3:::{contract.bucket}/{ARTIFACT_PATH}",
            "ARTIFACT_PATH_CAPABILITY_NOT_ALLOWED",
        ),
    )
    for observation_name, actions, resource_arn, failure_reason in simulations:
        response = context.call(
            "iam:SimulatePrincipalPolicy",
            {
                "ActionNames": list(actions),
                "PolicySourceArn": contract.role_arn,
                "ResourceArns": [resource_arn],
            },
        )
        if response is None:
            continue
        results = response.get("EvaluationResults")
        decisions: dict[str, object] = {}
        valid_results = isinstance(results, list) and len(results) == len(actions)
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, Mapping) or not isinstance(
                    result.get("EvalActionName"), str
                ):
                    valid_results = False
                    continue
                action = str(result["EvalActionName"])
                if action in decisions:
                    valid_results = False
                decisions[action] = {
                    "decision": result.get("EvalDecision"),
                    "resource_match": result.get("EvalResourceName") == resource_arn,
                }
        exact = (
            valid_results
            and response.get("IsTruncated") is False
            and set(decisions) == set(actions)
            and all(
                isinstance(decisions[action], Mapping)
                and decisions[action].get("decision") == "allowed"
                and decisions[action].get("resource_match") is True
                for action in actions
            )
        )
        observations[observation_name] = {
            "actions_exact": set(decisions) == set(actions),
            "allowed_for_exact_resource": exact,
            "not_truncated": response.get("IsTruncated") is False,
        }
        if not exact:
            context.reason(failure_reason)


def _observe_ec2(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    response = context.call(
        "ec2:DescribeInstances",
        {"InstanceIds": [contract.instance_id]},
    )
    if response is None:
        return
    instances: list[Mapping[str, object]] = []
    reservations = response.get("Reservations")
    if isinstance(reservations, list):
        for reservation in reservations:
            values = reservation.get("Instances") if isinstance(reservation, Mapping) else None
            if isinstance(values, list):
                instances.extend(item for item in values if isinstance(item, Mapping))
    if len(instances) != 1 or instances[0].get("InstanceId") != contract.instance_id:
        observations["sandbox"] = {"explicit_target_match": False}
        context.reason("SANDBOX_EXPLICIT_TARGET_MISMATCH")
        return
    instance = instances[0]
    state = instance.get("State")
    if not isinstance(state, Mapping) or state.get("Name") != "running":
        context.reason("SANDBOX_NOT_RUNNING")
    placement = instance.get("Placement")
    availability_zone = (
        placement.get("AvailabilityZone") if isinstance(placement, Mapping) else None
    )
    if not isinstance(availability_zone, str) or not availability_zone.startswith(
        f"{EXPECTED_REGION}"
    ):
        context.reason("SANDBOX_REGION_MISMATCH")
    mappings = instance.get("BlockDeviceMappings")
    has_ebs = isinstance(mappings, list) and any(
        isinstance(item, Mapping)
        and isinstance(item.get("Ebs"), Mapping)
        and bool(item["Ebs"].get("VolumeId"))
        for item in mappings
    )
    if instance.get("RootDeviceType") != "ebs" or not has_ebs:
        context.reason("SANDBOX_EBS_REQUIRED")
    tags = instance.get("Tags")
    matching_tags = (
        [
            tag
            for tag in tags
            if isinstance(tag, Mapping) and tag.get("Key") == EXPECTED_SANDBOX_TAG_KEY
        ]
        if isinstance(tags, list)
        else []
    )
    if len(matching_tags) != 1 or matching_tags[0].get("Value") != EXPECTED_SANDBOX_TAG_VALUE:
        context.reason("SANDBOX_TAG_MISMATCH")
    observations["sandbox"] = {
        "ebs_backed": instance.get("RootDeviceType") == "ebs" and has_ebs,
        "explicit_target_match": True,
        "region_match": isinstance(availability_zone, str)
        and availability_zone.startswith(EXPECTED_REGION),
        "running": isinstance(state, Mapping) and state.get("Name") == "running",
        "tag_match": len(matching_tags) == 1
        and matching_tags[0].get("Value") == EXPECTED_SANDBOX_TAG_VALUE,
    }


def _observe_cloudwatch(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    response = context.call(
        "cloudwatch:GetMetricStatistics",
        {
            "Dimensions": [{"Name": "InstanceId", "Value": contract.instance_id}],
            "EndTime": contract.cw_end,
            "MetricName": "CPUUtilization",
            "Namespace": "AWS/EC2",
            "Period": contract.cw_period,
            "StartTime": contract.cw_start,
            "Statistics": [contract.cw_statistic],
            "Unit": "Percent",
        },
    )
    if response is None:
        return
    datapoints = response.get("Datapoints")
    valid_periods: set[int] = set()
    if isinstance(datapoints, list):
        for datapoint in datapoints:
            value = datapoint.get(contract.cw_statistic) if isinstance(datapoint, Mapping) else None
            timestamp = datapoint.get("Timestamp") if isinstance(datapoint, Mapping) else None
            if (
                isinstance(value, (int, float, Decimal))
                and not isinstance(value, bool)
                and _decimal(value) is not None
                and isinstance(timestamp, datetime)
                and timestamp.tzinfo is not None
                and timestamp.utcoffset() is not None
                and contract.cw_start <= timestamp.astimezone(UTC) <= contract.cw_end
                and datapoint.get("Unit") == "Percent"
            ):
                valid_periods.add(int(timestamp.astimezone(UTC).timestamp()) // contract.cw_period)
    numeric_count = len(valid_periods)
    if numeric_count < contract.cw_minimum:
        context.reason("CLOUDWATCH_NUMERIC_DATAPOINTS_INSUFFICIENT")
    observations["cloudwatch"] = {
        "minimum_numeric_datapoints": contract.cw_minimum,
        "numeric_datapoints": numeric_count,
        "window_seconds": round((contract.cw_end - contract.cw_start).total_seconds()),
    }


def _observe_nova(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    response = context.call(
        "bedrock:GetInferenceProfile",
        {"inferenceProfileIdentifier": contract.nova_profile_id},
    )
    if response is None:
        return
    models = response.get("models")
    expected_model_arns = {
        f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0"
        for region in EXPECTED_NOVA_MODEL_REGIONS
    }
    observed_model_arns = (
        {
            str(model.get("modelArn"))
            for model in models
            if isinstance(model, Mapping) and isinstance(model.get("modelArn"), str)
        }
        if isinstance(models, list)
        else set()
    )
    profile_valid = (
        response.get("inferenceProfileId") == contract.nova_profile_id
        and response.get("status") == "ACTIVE"
        and isinstance(models, list)
        and observed_model_arns == expected_model_arns
        and len(models) == len(expected_model_arns)
    )
    observations["nova_profile"] = {
        "active": response.get("status") == "ACTIVE",
        "exact_profile": response.get("inferenceProfileId") == contract.nova_profile_id,
        "routed_model_count": len(observed_model_arns),
        "routed_models_exact": observed_model_arns == expected_model_arns,
    }
    if not profile_valid:
        context.reason("NOVA_PROFILE_UNAVAILABLE")
        return
    if not contract.synthetic_converse:
        observations["nova_synthetic_converse"] = {
            "called": False,
            "latency_ms": None,
            "outcome_class": "NOT_RUN",
        }
        context.reason("NOVA_INVOCATION_ACCESS_UNPROVEN")
        return
    if context.reasons:
        observations["nova_synthetic_converse"] = {
            "called": False,
            "latency_ms": None,
            "outcome_class": "NOT_RUN",
        }
        context.reason("NOVA_INVOCATION_PROBE_SKIPPED_DUE_TO_PRIOR_BLOCKER")
        return
    started = context.monotonic_clock()
    probe = context.call(
        "bedrock-runtime:Converse",
        {
            "inferenceConfig": {
                "maxTokens": min(contract.max_tokens, MAX_SYNTHETIC_TOKENS),
                "temperature": NOVA_2_LITE_MIN_TEMPERATURE,
            },
            "messages": [{"content": [{"text": _SYNTHETIC_PROMPT}], "role": "user"}],
            "modelId": contract.nova_profile_id,
        },
    )
    # Deliberately retain no raw provider response, prompt, text, token usage, or trace.
    elapsed = context.monotonic_clock() - started
    latency_ms = max(0, round(elapsed * 1_000))
    observations["nova_synthetic_converse"] = {
        "called": True,
        "latency_ms": latency_ms,
        "outcome_class": "SUCCESS" if probe is not None else "DEPENDENCY_ERROR",
        "response_received": probe is not None,
        "response_persisted": False,
    }
    if probe is None:
        context.reason("NOVA_SYNTHETIC_CONVERSE_FAILED")


def _notification_threshold(notification: object) -> Decimal | None:
    if not isinstance(notification, Mapping):
        return None
    if (
        notification.get("NotificationType") != "ACTUAL"
        or notification.get("ThresholdType") != "ABSOLUTE_VALUE"
        or notification.get("ComparisonOperator") != "GREATER_THAN"
    ):
        return None
    return _decimal(notification.get("Threshold"))


def _observe_budgets(
    context: _Context,
    contract: _ValidatedContract,
    observations: dict[str, object],
) -> None:
    shared_parameters = {
        "AccountId": contract.account_id,
        "BudgetName": contract.budget_name,
    }
    budget_response = context.call("budgets:DescribeBudget", shared_parameters)
    notifications_response = context.call(
        "budgets:DescribeNotificationsForBudget", shared_parameters
    )
    budget_observation: dict[str, object] = {}
    if budget_response is not None:
        budget = budget_response.get("Budget")
        limit = budget.get("BudgetLimit") if isinstance(budget, Mapping) else None
        budget_invalid = (
            not isinstance(budget, Mapping)
            or budget.get("BudgetName") != contract.budget_name
            or budget.get("BudgetType") != "COST"
            or not isinstance(limit, Mapping)
            or limit.get("Unit") != "USD"
        )
        budget_observation["budget"] = {"configuration_valid": not budget_invalid}
        if budget_invalid:
            context.reason("BUDGET_CONFIGURATION_INVALID")

    if notifications_response is None:
        observations["budget"] = budget_observation
        return
    notifications = notifications_response.get("Notifications")
    if not isinstance(notifications, list) or notifications_response.get("NextToken"):
        context.reason("BUDGET_THRESHOLDS_INVALID")
        observations["budget"] = budget_observation
        return
    by_threshold: dict[Decimal, Mapping[str, object]] = {}
    for notification in notifications:
        threshold = _notification_threshold(notification)
        if threshold is not None and isinstance(notification, Mapping):
            by_threshold[threshold] = notification
    if set(by_threshold) != set(EXPECTED_BUDGET_THRESHOLDS) or len(notifications) != 3:
        budget_observation["notifications"] = {"thresholds_exact": False}
        context.reason("BUDGET_THRESHOLDS_INVALID")
        observations["budget"] = budget_observation
        return

    budget_observation["notifications"] = {"thresholds_exact": True}
    subscriber_observations: list[dict[str, object]] = []
    for threshold in EXPECTED_BUDGET_THRESHOLDS:
        notification = by_threshold[threshold]
        response = context.call(
            "budgets:DescribeSubscribersForNotification",
            {**shared_parameters, "Notification": dict(notification)},
        )
        if response is None:
            continue
        subscribers = response.get("Subscribers")
        owner_present = isinstance(subscribers, list) and any(
            isinstance(subscriber, Mapping)
            and subscriber.get("SubscriptionType") == contract.budget_owner_type
            and subscriber.get("Address") == contract.budget_owner
            for subscriber in subscribers
        )
        if not owner_present or response.get("NextToken"):
            context.reason("BUDGET_NOTIFICATION_OWNER_MISSING")
        subscriber_observations.append(
            {"owner_present": owner_present and not bool(response.get("NextToken"))}
        )
    budget_observation["subscribers"] = subscriber_observations
    observations["budget"] = budget_observation


def _finish_receipt(
    *,
    contract: _ValidatedContract,
    candidate: dict[str, object],
    candidate_digest: str,
    context: _Context,
    observations: dict[str, object],
    observed_at: str,
    receipt_nonce: str,
) -> PrivateObservationReceipt:
    reasons = set(context.reasons)

    def has_reason_prefix(*prefixes: str) -> bool:
        return any(reason.startswith(prefixes) for reason in reasons)

    bucket_observation = observations.get("artifact_bucket")
    packaging_ready = (
        isinstance(bucket_observation, Mapping)
        and set(bucket_observation)
        == {
            "encryption",
            "lifecycle",
            "location",
            "ownership",
            "policy",
            "public_access_block",
            "versioning",
        }
        and isinstance(observations.get("artifact_path_capability"), Mapping)
        and observations["artifact_path_capability"].get("allowed_for_exact_resource") is True
        and not has_reason_prefix("S3_", "AWS_CALL_FAILED:S3_", "CLIENT_CREATION_FAILED:S3")
        and not has_reason_prefix("ARTIFACT_PATH_", "AWS_CALL_FAILED:IAM_")
    )
    nova_probe = observations.get("nova_synthetic_converse")
    nova_ready = (
        isinstance(observations.get("nova_profile"), Mapping)
        and isinstance(nova_probe, Mapping)
        and nova_probe.get("called") is True
        and nova_probe.get("response_received") is True
        and nova_probe.get("response_persisted") is False
        and not has_reason_prefix(
            "NOVA_",
            "AWS_CALL_FAILED:BEDROCK_",
            "CLIENT_CREATION_FAILED:BEDROCK",
        )
    )
    budget_observation = observations.get("budget")
    budget_ready = (
        isinstance(budget_observation, Mapping)
        and isinstance(budget_observation.get("budget"), Mapping)
        and isinstance(budget_observation.get("notifications"), Mapping)
        and isinstance(budget_observation.get("subscribers"), list)
        and len(budget_observation["subscribers"]) == len(EXPECTED_BUDGET_THRESHOLDS)
        and not has_reason_prefix(
            "BUDGET_",
            "AWS_CALL_FAILED:BUDGETS_",
            "CLIENT_CREATION_FAILED:BUDGETS",
        )
    )
    checks = {
        "authenticated_identity_match": (
            isinstance(observations.get("caller_identity"), Mapping)
            and not has_reason_prefix(
                "CALLER_",
                "AWS_CALL_FAILED:STS_",
                "CLIENT_CREATION_FAILED:STS",
            )
        ),
        "budget_notification_owner_ready": budget_ready,
        "cloudwatch_evidence_ready": (
            isinstance(observations.get("cloudwatch"), Mapping)
            and not has_reason_prefix(
                "CLOUDWATCH_",
                "AWS_CALL_FAILED:CLOUDWATCH_",
                "CLIENT_CREATION_FAILED:CLOUDWATCH",
            )
        ),
        "judge_secret_ready": (
            isinstance(observations.get("secret_capability"), Mapping)
            and observations["secret_capability"].get("allowed_for_exact_resource") is True
            and not has_reason_prefix(
                "JUDGE_SECRET_",
                "AWS_CALL_FAILED:IAM_",
                "CLIENT_CREATION_FAILED:IAM",
            )
        ),
        "nova2_profile_access": nova_ready,
        "packaging_bucket_ready": packaging_ready,
        "sandbox_read_only_verified": (
            isinstance(observations.get("sandbox"), Mapping)
            and not has_reason_prefix(
                "SANDBOX_",
                "AWS_CALL_FAILED:EC2_",
                "CLIENT_CREATION_FAILED:EC2",
            )
        ),
    }
    external_prerequisites_pass = not reasons and all(checks.values())
    receipt = {
        "call_ledger": context.ledger,
        "candidate": {"descriptor": candidate, "sha256": candidate_digest},
        "checks": checks,
        "external_prerequisites_pass": external_prerequisites_pass,
        "identifiers": {
            "artifact_bucket": contract.bucket,
            "budget_name": contract.budget_name,
            "budget_owner": contract.budget_owner,
            "deployment_profile": contract.deployment_profile,
            "deployment_role_arn": contract.role_arn,
            "expected_account_id": contract.account_id,
            "judge_secret_arn": contract.secret_arn,
            "nova_inference_profile_id": contract.nova_profile_id,
            "sandbox_instance_id": contract.instance_id,
        },
        "observations": observations,
        "private_contract": contract.raw,
        "read_operation_allowlist": sorted(READ_OPERATION_ALLOWLIST),
        "receipt_nonce": receipt_nonce,
        "reasons": context.reasons,
        "region": EXPECTED_REGION,
        "schema_version": 1,
        "status": "PASS" if external_prerequisites_pass else "BLOCKED",
        "observed_at": observed_at,
        "write_operations": [],
    }
    return PrivateObservationReceipt(_canonical_mapping(receipt))


def _ledger_is_valid(value: object, *, require_complete: bool) -> bool:
    if not isinstance(value, list):
        return False
    operations: list[str] = []
    for expected_sequence, item in enumerate(value, start=1):
        if (
            not isinstance(item, Mapping)
            or set(item) != {"operation", "sequence", "write"}
            or item.get("sequence") != expected_sequence
            or item.get("write") is not False
            or item.get("operation") not in READ_OPERATION_ALLOWLIST
        ):
            return False
        operations.append(str(item["operation"]))
    if require_complete:
        return tuple(operations) == PASS_OPERATION_SEQUENCE
    position = 0
    for operation in operations:
        try:
            position = PASS_OPERATION_SEQUENCE.index(operation, position) + 1
        except ValueError:
            return False
    return True


def _pass_bucket_observation_is_valid(value: object, contract: _ValidatedContract) -> bool:
    if not isinstance(value, Mapping) or set(value) != {
        "encryption",
        "lifecycle",
        "location",
        "ownership",
        "policy",
        "public_access_block",
        "versioning",
    }:
        return False
    encryption = value.get("encryption")
    configuration = (
        encryption.get("ServerSideEncryptionConfiguration")
        if isinstance(encryption, Mapping)
        else None
    )
    rules = configuration.get("Rules") if isinstance(configuration, Mapping) else None
    encrypted = isinstance(rules, list) and any(
        isinstance(rule, Mapping)
        and isinstance(rule.get("ApplyServerSideEncryptionByDefault"), Mapping)
        and rule["ApplyServerSideEncryptionByDefault"].get("SSEAlgorithm")
        in {"AES256", "aws:kms", "aws:kms:dsse"}
        for rule in rules
    )
    public_block = value.get("public_access_block")
    public_configuration = (
        public_block.get("PublicAccessBlockConfiguration")
        if isinstance(public_block, Mapping)
        else None
    )
    ownership = value.get("ownership")
    ownership_controls = (
        ownership.get("OwnershipControls") if isinstance(ownership, Mapping) else None
    )
    ownership_rules = (
        ownership_controls.get("Rules") if isinstance(ownership_controls, Mapping) else None
    )
    policy = value.get("policy")
    return (
        isinstance(value.get("location"), Mapping)
        and value["location"].get("LocationConstraint") == EXPECTED_REGION
        and encrypted
        and isinstance(public_configuration, Mapping)
        and all(
            public_configuration.get(name) is True
            for name in (
                "BlockPublicAcls",
                "BlockPublicPolicy",
                "IgnorePublicAcls",
                "RestrictPublicBuckets",
            )
        )
        and isinstance(ownership_rules, list)
        and any(
            isinstance(rule, Mapping) and rule.get("ObjectOwnership") == "BucketOwnerEnforced"
            for rule in ownership_rules
        )
        and isinstance(value.get("versioning"), Mapping)
        and value["versioning"].get("Status") == "Enabled"
        and isinstance(value.get("lifecycle"), Mapping)
        and _lifecycle_is_bounded(value["lifecycle"], contract.artifact_prefix)
        and isinstance(policy, Mapping)
        and _s3_policy_is_tls_only(policy.get("Policy"), contract.bucket)
    )


def _capability_observation_is_valid(value: object) -> bool:
    return isinstance(value, Mapping) and value == {
        "actions_exact": True,
        "allowed_for_exact_resource": True,
        "not_truncated": True,
    }


def _pass_observations_are_valid(
    observations: object,
    contract: _ValidatedContract,
) -> bool:
    if not isinstance(observations, Mapping) or set(observations) != {
        "artifact_bucket",
        "artifact_path_capability",
        "budget",
        "caller_identity",
        "cloudwatch",
        "nova_profile",
        "nova_synthetic_converse",
        "sandbox",
        "secret_capability",
    }:
        return False
    identity = observations.get("caller_identity")
    sandbox = observations.get("sandbox")
    cloudwatch = observations.get("cloudwatch")
    nova_profile = observations.get("nova_profile")
    nova_probe = observations.get("nova_synthetic_converse")
    budget = observations.get("budget")
    budget_configuration = budget.get("budget") if isinstance(budget, Mapping) else None
    notifications = budget.get("notifications") if isinstance(budget, Mapping) else None
    subscribers = budget.get("subscribers") if isinstance(budget, Mapping) else None
    return (
        isinstance(identity, Mapping)
        and set(identity) == {"Account", "Arn", "UserId"}
        and identity.get("Account") == contract.account_id
        and _principal_matches(contract.role_arn, identity.get("Arn"), contract.account_id)
        and _pass_bucket_observation_is_valid(observations.get("artifact_bucket"), contract)
        and _capability_observation_is_valid(observations.get("secret_capability"))
        and _capability_observation_is_valid(observations.get("artifact_path_capability"))
        and isinstance(sandbox, Mapping)
        and sandbox
        == {
            "ebs_backed": True,
            "explicit_target_match": True,
            "region_match": True,
            "running": True,
            "tag_match": True,
        }
        and isinstance(cloudwatch, Mapping)
        and set(cloudwatch)
        == {"minimum_numeric_datapoints", "numeric_datapoints", "window_seconds"}
        and cloudwatch.get("minimum_numeric_datapoints") == contract.cw_minimum
        and isinstance(cloudwatch.get("numeric_datapoints"), int)
        and not isinstance(cloudwatch.get("numeric_datapoints"), bool)
        and cloudwatch["numeric_datapoints"] >= contract.cw_minimum
        and cloudwatch.get("window_seconds")
        == round((contract.cw_end - contract.cw_start).total_seconds())
        and isinstance(nova_profile, Mapping)
        and nova_profile
        == {
            "active": True,
            "exact_profile": True,
            "routed_model_count": len(EXPECTED_NOVA_MODEL_REGIONS),
            "routed_models_exact": True,
        }
        and isinstance(nova_probe, Mapping)
        and set(nova_probe)
        == {
            "called",
            "latency_ms",
            "outcome_class",
            "response_persisted",
            "response_received",
        }
        and nova_probe.get("called") is True
        and isinstance(nova_probe.get("latency_ms"), int)
        and not isinstance(nova_probe.get("latency_ms"), bool)
        and nova_probe["latency_ms"] >= 0
        and nova_probe.get("outcome_class") == "SUCCESS"
        and nova_probe.get("response_received") is True
        and nova_probe.get("response_persisted") is False
        and budget_configuration == {"configuration_valid": True}
        and notifications == {"thresholds_exact": True}
        and isinstance(budget, Mapping)
        and set(budget) == {"budget", "notifications", "subscribers"}
        and isinstance(subscribers, list)
        and subscribers == [{"owner_present": True}] * len(EXPECTED_BUDGET_THRESHOLDS)
    )


def validate_private_observation_receipt(
    receipt: Mapping[str, object],
    *,
    expected_candidate: Mapping[str, object],
    validation_time: datetime | None = None,
) -> None:
    """Reject receipts that could not be the adapter's closed, candidate-bound output."""

    if set(receipt) != PRIVATE_RECEIPT_KEYS or receipt.get("schema_version") != 1:
        raise ContractValidationError("PRIVATE_RECEIPT_SCHEMA_INVALID")
    candidate, candidate_digest = _validate_candidate(
        expected_candidate,
        str(expected_candidate.get("candidate_digest", "")),
    )
    candidate_binding = receipt.get("candidate")
    if (
        not isinstance(candidate_binding, Mapping)
        or set(candidate_binding) != {"descriptor", "sha256"}
        or candidate_binding.get("descriptor") != candidate
        or candidate_binding.get("sha256") != candidate_digest
    ):
        raise ContractValidationError("PRIVATE_RECEIPT_CANDIDATE_MISMATCH")
    observed_at = receipt.get("observed_at")
    try:
        observed_time = _parse_utc(observed_at, "PRIVATE_RECEIPT_OBSERVED_AT_INVALID")
    except ContractValidationError:
        raise
    if observed_at != observed_time.isoformat(timespec="seconds").replace("+00:00", "Z"):
        raise ContractValidationError("PRIVATE_RECEIPT_OBSERVED_AT_INVALID")
    if validation_time is not None:
        if validation_time.tzinfo is None or validation_time.utcoffset() is None:
            raise ContractValidationError("PRIVATE_RECEIPT_VALIDATION_TIME_INVALID")
        age = validation_time.astimezone(UTC) - observed_time
        if age < -MAX_OPERATOR_SELECTION_FUTURE_SKEW or age > MAX_OPERATOR_SELECTION_AGE:
            raise ContractValidationError("PRIVATE_RECEIPT_STALE")
    private_contract = receipt.get("private_contract")
    if not isinstance(private_contract, Mapping):
        raise ContractValidationError("PRIVATE_RECEIPT_SCHEMA_INVALID")
    contract = _validate_contract(
        private_contract,
        expected_candidate_digest=candidate_digest,
        observation_time=observed_time,
    )
    expected_identifiers = {
        "artifact_bucket": contract.bucket,
        "budget_name": contract.budget_name,
        "budget_owner": contract.budget_owner,
        "deployment_profile": contract.deployment_profile,
        "deployment_role_arn": contract.role_arn,
        "expected_account_id": contract.account_id,
        "judge_secret_arn": contract.secret_arn,
        "nova_inference_profile_id": contract.nova_profile_id,
        "sandbox_instance_id": contract.instance_id,
    }
    checks = receipt.get("checks")
    reasons = receipt.get("reasons")
    status = receipt.get("status")
    passed = status == "PASS"
    if (
        receipt.get("region") != EXPECTED_REGION
        or receipt.get("identifiers") != expected_identifiers
        or receipt.get("read_operation_allowlist") != sorted(READ_OPERATION_ALLOWLIST)
        or not isinstance(receipt.get("receipt_nonce"), str)
        or re.fullmatch(r"[0-9a-f]{32,128}", str(receipt["receipt_nonce"])) is None
        or receipt.get("write_operations") != []
        or not isinstance(checks, Mapping)
        or set(checks) != PRIVATE_CHECK_KEYS
        or any(type(checks[name]) is not bool for name in PRIVATE_CHECK_KEYS)
        or not isinstance(reasons, list)
        or len(reasons) != len(set(str(reason) for reason in reasons))
        or any(
            not isinstance(reason, str) or re.fullmatch(r"[A-Z0-9_:.-]{1,160}", reason) is None
            for reason in reasons
        )
        or not _ledger_is_valid(receipt.get("call_ledger"), require_complete=passed)
    ):
        raise ContractValidationError("PRIVATE_RECEIPT_SCHEMA_INVALID")
    coherent_pass = (
        passed
        and receipt.get("external_prerequisites_pass") is True
        and reasons == []
        and all(checks.values())
        and _pass_observations_are_valid(receipt.get("observations"), contract)
    )
    coherent_block = (
        status == "BLOCKED"
        and receipt.get("external_prerequisites_pass") is False
        and (bool(reasons) or not all(checks.values()))
    )
    if not coherent_pass and not coherent_block:
        raise ContractValidationError("PRIVATE_RECEIPT_STATUS_INVALID")


def observe_aws_preflight(
    *,
    session: AwsSession,
    private_contract: Mapping[str, object],
    candidate_descriptor: Mapping[str, object],
    candidate_digest: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    nonce_factory: Callable[[], str] = lambda: secrets.token_hex(16),
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> PrivateObservationReceipt:
    """Perform the exact bounded G10 observation set through injected clients.

    Contract/candidate errors are rejected before client construction.  Once STS
    proves the expected account and dedicated deployment role, resource checks run
    using only the identifiers already present in the private contract.  AWS errors
    become public-safe reason codes; raw exception text is never retained.
    """

    candidate, validated_digest = _validate_candidate(candidate_descriptor, candidate_digest)
    observation_time = clock()
    if observation_time.tzinfo is None or observation_time.utcoffset() is None:
        raise ContractValidationError("OBSERVATION_TIME_INVALID")
    observed_at = (
        observation_time.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    receipt_nonce = nonce_factory()
    if (
        not isinstance(receipt_nonce, str)
        or re.fullmatch(r"[0-9a-f]{32,128}", receipt_nonce) is None
    ):
        raise ContractValidationError("RECEIPT_NONCE_INVALID")
    contract = _validate_contract(
        private_contract,
        expected_candidate_digest=validated_digest,
        observation_time=observation_time.astimezone(UTC),
    )
    if getattr(session, "profile_name", None) != contract.deployment_profile:
        raise ContractValidationError("SESSION_PROFILE_MISMATCH")
    context = _Context(session=session, monotonic_clock=monotonic_clock)
    observations: dict[str, object] = {}

    identity = context.call("sts:GetCallerIdentity", {})
    if identity is not None:
        observations["caller_identity"] = _without_metadata(identity)
        if identity.get("Account") != contract.account_id:
            context.reason("CALLER_ACCOUNT_MISMATCH")
        if not _principal_matches(contract.role_arn, identity.get("Arn"), contract.account_id):
            context.reason("CALLER_ROLE_MISMATCH")
    if identity is None or context.reasons:
        return _finish_receipt(
            contract=contract,
            candidate=candidate,
            candidate_digest=validated_digest,
            context=context,
            observations=observations,
            observed_at=observed_at,
            receipt_nonce=receipt_nonce,
        )

    _observe_s3(context, contract, observations)
    _observe_iam(context, contract, observations)
    _observe_ec2(context, contract, observations)
    _observe_cloudwatch(context, contract, observations)
    _observe_nova(context, contract, observations)
    _observe_budgets(context, contract, observations)
    return _finish_receipt(
        contract=contract,
        candidate=candidate,
        candidate_digest=validated_digest,
        context=context,
        observations=observations,
        observed_at=observed_at,
        receipt_nonce=receipt_nonce,
    )


__all__ = [
    "BEDROCK_READ_TIMEOUT_SECONDS",
    "CONNECT_TIMEOUT_SECONDS",
    "EXPECTED_REGION",
    "MAX_SYNTHETIC_TOKENS",
    "PASS_OPERATION_SEQUENCE",
    "PRIVATE_CHECK_KEYS",
    "READ_OPERATION_ALLOWLIST",
    "READ_TIMEOUT_SECONDS",
    "TOTAL_MAX_ATTEMPTS",
    "ContractValidationError",
    "PrivateObservationReceipt",
    "observe_aws_preflight",
    "validate_private_observation_receipt",
]
