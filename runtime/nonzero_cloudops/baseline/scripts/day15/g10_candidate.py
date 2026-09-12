#!/usr/bin/env python3
"""Build the exact Day 15 candidate binding and load its private operator contract.

This module is deliberately local-only.  It neither discovers AWS identities nor
performs AWS calls.  Identity-bearing contract values are returned to an authorized
caller, but validation failures expose stable reason codes only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from scripts.day15.validate_template import (
    TemplateFailure,
    canonical_json,
    lambda_configuration_sha256,
    load_template,
)

ROOT: Final = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT: Final = ROOT / "dist" / "day15" / "aioa-lambda.zip"
DEFAULT_ARTIFACT_MANIFEST: Final = ROOT / "dist" / "day15" / "aioa-lambda.manifest.json"
DEFAULT_DEPENDENCY_SCAN: Final = ROOT / "dist" / "day15" / "pip-audit.json"
DEFAULT_DEPLOYMENT_CONTRACT: Final = ROOT / "requirements" / "day15-deployment-contract.json"
DEFAULT_SOURCE_TEMPLATE: Final = ROOT / "infra" / "sam" / "template.yaml"
DEFAULT_RENDERED_TEMPLATE: Final = ROOT / "dist" / "day15" / "rendered-template.yaml"
DEFAULT_RENDER_PROVENANCE: Final = ROOT / "dist" / "day15" / "rendered-template.provenance.json"
DEFAULT_REVIEWER_MANIFEST: Final = ROOT / "docs" / "evidence" / ("reviewer-evidence-manifest.json")
DEFAULT_P0_RESULT: Final = ROOT / ".aioa-private" / "day15-p0-full-result.json"
DEFAULT_P1_RESULT: Final = ROOT / ".aioa-private" / "day15-p1-full-result.json"

SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
PROFILE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
ACCOUNT_ID_PATTERN: Final = re.compile(r"^\d{12}$")
ROLE_ARN_PATTERN: Final = re.compile(r"^arn:aws:iam::(\d{12}):role/[A-Za-z0-9+=,.@_/-]{1,512}$")
BUCKET_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
IPV4_PATTERN: Final = re.compile(r"^(?:\d{1,3}\.){3}\d{1,3}$")
STACK_PATTERN: Final = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,127}$")
INSTANCE_PATTERN: Final = re.compile(r"^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
VISIBLE_PRIVATE_VALUE_PATTERN: Final = re.compile(r"^[\x21-\x7e]{1,512}$")
EMAIL_PATTERN: Final = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SNS_ARN_PATTERN: Final = re.compile(r"^arn:aws:sns:eu-central-1:(\d{12}):[A-Za-z0-9_-]{1,256}$")
TIMESTAMP_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BUCKET_RESERVED_PREFIXES: Final = ("amzn-s3-demo-", "sthree-", "xn--")
BUCKET_RESERVED_SUFFIXES: Final = (
    "-s3alias",
    "--ol-s3",
    ".mrap",
    "--x-s3",
    "--table-s3",
)

REGION: Final = "eu-central-1"
DEPLOYMENT_PROFILE: Final = "aioa-day15-deployer"
DEPLOYMENT_ROLE_LEAF: Final = "AIOANonZeroCloudOpsDay15DeploymentRole"
ARTIFACT_PATH: Final = "day15/reviewed/aioa-lambda.zip"
STACK_NAME: Final = "aioa-nonzero-cloudops-day15"
NOVA_PROFILE: Final = "eu.amazon.nova-2-lite-v1:0"
SELECTION_SOURCES: Final = frozenset(
    {"PRIVATE_CONTRACT", "EXPLICIT_AWS_PROFILE", "UNIQUE_EXPLICIT_PROJECT_PROFILE"}
)

COMPONENT_KEYS: Final = frozenset(
    {
        "artifact_manifest_sha256",
        "artifact_sha256",
        "dependency_scan_sha256",
        "deployment_contract_sha256",
        "lambda_configuration_sha256",
        "p0_full_result_sha256",
        "p1_full_result_sha256",
        "rendered_template_provenance_sha256",
        "rendered_template_sha256",
        "reviewer_manifest_sha256",
    }
)

PRIVATE_TOP_LEVEL_KEYS: Final = frozenset(
    {
        "bootstrap",
        "budget_notification",
        "candidate_digest",
        "cloudwatch",
        "deployment_role_arn",
        "expected_account_id",
        "judge_secret",
        "nova",
        "operator_selection_timestamp",
        "packaging",
        "region",
        "sandbox",
        "schema_version",
        "selected_profile",
        "selection_source",
        "stack_name",
    }
)


class CandidateFailure(RuntimeError):
    """A non-sensitive candidate validation failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PrivateContractFailure(RuntimeError):
    """A private-contract failure that never embeds identity-bearing values."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bucket_name_is_valid(value: object) -> bool:
    """Return whether a bucket name satisfies the current general-purpose S3 shape."""

    return (
        isinstance(value, str)
        and BUCKET_PATTERN.fullmatch(value) is not None
        and ".." not in value
        and ".-" not in value
        and "-." not in value
        and IPV4_PATTERN.fullmatch(value) is None
        and not value.startswith(BUCKET_RESERVED_PREFIXES)
        and not value.endswith(BUCKET_RESERVED_SUFFIXES)
    )


def budget_name_is_valid(value: object) -> bool:
    """Mirror the AWS Budgets BudgetName service-model constraints."""

    return (
        isinstance(value, str)
        and 1 <= len(value) <= 100
        and ":" not in value
        and "\\" not in value
        and "/action/" not in value
        and not ("<script>" in value.lower() and "</script>" in value.lower())
    )


def _read_regular_bytes(path: Path, reason: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CandidateFailure(reason) from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CandidateFailure(reason)
    try:
        return path.read_bytes()
    except OSError as error:
        raise CandidateFailure(reason) from error


def _load_json_object(path: Path, reason: str) -> tuple[dict[str, object], bytes]:
    raw = _read_regular_bytes(path, reason)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CandidateFailure(reason) from error
    if not isinstance(value, dict):
        raise CandidateFailure(reason)
    return value, raw


def _git_output(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CandidateFailure("CANDIDATE_GIT_UNAVAILABLE") from error
    if result.returncode != 0:
        raise CandidateFailure("CANDIDATE_GIT_UNAVAILABLE")
    return result.stdout.strip()


def _clean_head(root: Path) -> str:
    head = _git_output(root, "rev-parse", "--verify", "HEAD")
    if COMMIT_PATTERN.fullmatch(head) is None:
        raise CandidateFailure("CANDIDATE_HEAD_INVALID")
    status = _git_output(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise CandidateFailure("CANDIDATE_WORKTREE_NOT_CLEAN")
    return head


def _validate_full_gate_result(
    path: Path,
    *,
    prefix: str,
    expected_count: int,
) -> bytes:
    value, raw = _load_json_object(path, f"{prefix}_RESULT_INVALID")
    if raw != (canonical_json(value) + "\n").encode("utf-8"):
        raise CandidateFailure(f"{prefix}_RESULT_NOT_CANONICAL")
    expected_keys = {
        "gate_count",
        "gates",
        "gates_fail",
        "gates_pass",
        "gates_skipped",
        "matrix_reasons",
        "status",
    }
    if set(value) != expected_keys:
        raise CandidateFailure(f"{prefix}_RESULT_SCHEMA_INVALID")
    if (
        value.get("status") != "PASS"
        or value.get("gate_count") != expected_count
        or value.get("gates_pass") != expected_count
        or value.get("gates_fail") != 0
        or value.get("gates_skipped") != 0
        or value.get("matrix_reasons") != []
    ):
        raise CandidateFailure(f"{prefix}_RESULT_NOT_FULL_PASS")
    gates = value.get("gates")
    if not isinstance(gates, list) or len(gates) != expected_count:
        raise CandidateFailure(f"{prefix}_RESULT_SCHEMA_INVALID")
    expected_gate_keys = {
        "gate_id",
        "name",
        "proof_tests",
        "reasons",
        "skipped",
        "status",
    }
    for index, gate in enumerate(gates, 1):
        if not isinstance(gate, dict) or set(gate) != expected_gate_keys:
            raise CandidateFailure(f"{prefix}_RESULT_SCHEMA_INVALID")
        if (
            gate.get("gate_id") != f"{prefix}-{index:02d}"
            or not isinstance(gate.get("name"), str)
            or not gate.get("name")
            or gate.get("status") != "PASS"
            or type(gate.get("proof_tests")) is not int
            or gate["proof_tests"] < 1
            or gate.get("skipped") != 0
            or gate.get("reasons") != []
        ):
            raise CandidateFailure(f"{prefix}_RESULT_NOT_FULL_PASS")
    return raw


def derive_candidate_digest(
    *,
    source_commit: str,
    region: str,
    components: dict[str, str],
) -> str:
    """Derive the stable digest from a closed candidate descriptor core."""

    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise CandidateFailure("CANDIDATE_HEAD_INVALID")
    if region != REGION:
        raise CandidateFailure("CANDIDATE_REGION_INVALID")
    if set(components) != COMPONENT_KEYS or any(
        SHA256_PATTERN.fullmatch(value) is None for value in components.values()
    ):
        raise CandidateFailure("CANDIDATE_COMPONENTS_INVALID")
    core = {
        "components": {key: components[key] for key in sorted(components)},
        "region": region,
        "schema_version": 1,
        "source_commit": source_commit,
    }
    return _sha256(canonical_json(core).encode("utf-8"))


def build_candidate_descriptor(
    *,
    root: Path = ROOT,
    artifact_path: Path = DEFAULT_ARTIFACT,
    artifact_manifest_path: Path = DEFAULT_ARTIFACT_MANIFEST,
    dependency_scan_path: Path = DEFAULT_DEPENDENCY_SCAN,
    deployment_contract_path: Path = DEFAULT_DEPLOYMENT_CONTRACT,
    source_template_path: Path = DEFAULT_SOURCE_TEMPLATE,
    rendered_template_path: Path = DEFAULT_RENDERED_TEMPLATE,
    render_provenance_path: Path = DEFAULT_RENDER_PROVENANCE,
    reviewer_manifest_path: Path = DEFAULT_REVIEWER_MANIFEST,
    p0_result_path: Path = DEFAULT_P0_RESULT,
    p1_result_path: Path = DEFAULT_P1_RESULT,
    region: str = REGION,
) -> dict[str, object]:
    """Bind exact local evidence bytes to the repository's clean current HEAD."""

    head = _clean_head(root)
    if region != REGION:
        raise CandidateFailure("CANDIDATE_REGION_INVALID")
    artifact = _read_regular_bytes(artifact_path, "CANDIDATE_ARTIFACT_INVALID")
    artifact_manifest, artifact_manifest_raw = _load_json_object(
        artifact_manifest_path, "CANDIDATE_ARTIFACT_MANIFEST_INVALID"
    )
    dependency_scan, dependency_scan_raw = _load_json_object(
        dependency_scan_path, "CANDIDATE_DEPENDENCY_SCAN_INVALID"
    )
    _deployment_contract, deployment_contract_raw = _load_json_object(
        deployment_contract_path, "CANDIDATE_DEPLOYMENT_CONTRACT_INVALID"
    )
    rendered_template = _read_regular_bytes(
        rendered_template_path, "CANDIDATE_RENDERED_TEMPLATE_INVALID"
    )
    render_provenance, render_provenance_raw = _load_json_object(
        render_provenance_path, "CANDIDATE_RENDER_PROVENANCE_INVALID"
    )
    reviewer_manifest = _read_regular_bytes(
        reviewer_manifest_path, "CANDIDATE_REVIEWER_MANIFEST_INVALID"
    )
    _read_regular_bytes(source_template_path, "CANDIDATE_SOURCE_TEMPLATE_INVALID")
    p0_result = _validate_full_gate_result(p0_result_path, prefix="P0", expected_count=15)
    p1_result = _validate_full_gate_result(p1_result_path, prefix="P1", expected_count=6)

    repository = artifact_manifest.get("repository")
    if not isinstance(repository, dict) or repository.get("commit_oid") != head:
        raise CandidateFailure("CANDIDATE_ARTIFACT_HEAD_MISMATCH")
    if render_provenance.get("repository_commit_oid") != head:
        raise CandidateFailure("CANDIDATE_RENDER_HEAD_MISMATCH")
    artifact_sha256 = _sha256(artifact)
    artifact_record = artifact_manifest.get("artifact")
    if (
        not isinstance(artifact_record, dict)
        or artifact_record.get("sha256") != artifact_sha256
        or dependency_scan.get("artifact_sha256") != artifact_sha256
        or render_provenance.get("rendered_template_sha256") != _sha256(rendered_template)
    ):
        raise CandidateFailure("CANDIDATE_CROSS_BINDING_INVALID")

    try:
        source_template = load_template(source_template_path)
        configuration_sha256 = lambda_configuration_sha256(source_template)
    except TemplateFailure as error:
        raise CandidateFailure("CANDIDATE_LAMBDA_CONFIGURATION_INVALID") from error

    components = {
        "artifact_manifest_sha256": _sha256(artifact_manifest_raw),
        "artifact_sha256": artifact_sha256,
        "dependency_scan_sha256": _sha256(dependency_scan_raw),
        "deployment_contract_sha256": _sha256(deployment_contract_raw),
        "lambda_configuration_sha256": configuration_sha256,
        "p0_full_result_sha256": _sha256(p0_result),
        "p1_full_result_sha256": _sha256(p1_result),
        "rendered_template_provenance_sha256": _sha256(render_provenance_raw),
        "rendered_template_sha256": _sha256(rendered_template),
        "reviewer_manifest_sha256": _sha256(reviewer_manifest),
    }
    digest = derive_candidate_digest(
        source_commit=head,
        region=region,
        components=components,
    )
    return {
        "candidate_digest": digest,
        "components": {key: components[key] for key in sorted(components)},
        "region": region,
        "schema_version": 1,
        "source_commit": head,
    }


def _private_failure(reason: str) -> PrivateContractFailure:
    return PrivateContractFailure(reason)


def _exact_keys(
    value: object, expected: set[str] | frozenset[str], reason: str
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != expected:
        raise _private_failure(reason)
    return value


def _private_path_allowed(path: Path, root: Path) -> None:
    lexical_path = Path(os.path.abspath(path))
    lexical_root = Path(os.path.abspath(root))
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError:
        return
    if not relative.parts or relative.parts[0] != ".aioa-private":
        raise _private_failure("PRIVATE_CONTRACT_REPOSITORY_PATH_FORBIDDEN")
    current = lexical_root
    for part in relative.parts[:-1]:
        current /= part
        try:
            if current.is_symlink():
                raise _private_failure("PRIVATE_CONTRACT_SYMLINK_FORBIDDEN")
        except OSError as error:
            raise _private_failure("PRIVATE_CONTRACT_PATH_INVALID") from error
    try:
        tracked = subprocess.run(
            ("git", "ls-files", "--error-unmatch", "--", relative.as_posix()),
            cwd=lexical_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
        ignored = subprocess.run(
            ("git", "check-ignore", "--quiet", "--no-index", "--", relative.as_posix()),
            cwd=lexical_root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise _private_failure("PRIVATE_CONTRACT_GIT_CHECK_FAILED") from error
    if tracked.returncode == 0:
        raise _private_failure("PRIVATE_CONTRACT_TRACKED_PATH_FORBIDDEN")
    if ignored.returncode != 0:
        raise _private_failure("PRIVATE_CONTRACT_IGNORED_PATH_REQUIRED")


def _validate_private_contract(value: dict[str, object], expected_digest: str) -> None:
    _exact_keys(value, PRIVATE_TOP_LEVEL_KEYS, "PRIVATE_CONTRACT_SCHEMA_INVALID")
    if value.get("schema_version") != 1:
        raise _private_failure("PRIVATE_CONTRACT_SCHEMA_INVALID")
    if (
        SHA256_PATTERN.fullmatch(expected_digest) is None
        or value.get("candidate_digest") != expected_digest
    ):
        raise _private_failure("PRIVATE_CONTRACT_CANDIDATE_MISMATCH")
    profile = value.get("selected_profile")
    if (
        not isinstance(profile, str)
        or PROFILE_PATTERN.fullmatch(profile) is None
        or profile != DEPLOYMENT_PROFILE
    ):
        raise _private_failure("PRIVATE_CONTRACT_PROFILE_INVALID")
    if value.get("selection_source") not in SELECTION_SOURCES:
        raise _private_failure("PRIVATE_CONTRACT_SELECTION_SOURCE_INVALID")
    account_id = value.get("expected_account_id")
    role_arn = value.get("deployment_role_arn")
    role_match = ROLE_ARN_PATTERN.fullmatch(role_arn) if isinstance(role_arn, str) else None
    if (
        not isinstance(account_id, str)
        or ACCOUNT_ID_PATTERN.fullmatch(account_id) is None
        or role_match is None
        or role_match.group(1) != account_id
        or role_arn.rsplit("/", 1)[-1] != DEPLOYMENT_ROLE_LEAF
    ):
        raise _private_failure("PRIVATE_CONTRACT_ACCOUNT_ROLE_INVALID")
    if value.get("region") != REGION or value.get("stack_name") != STACK_NAME:
        raise _private_failure("PRIVATE_CONTRACT_REGION_OR_STACK_INVALID")

    packaging = _exact_keys(
        value.get("packaging"), {"artifact_path", "bucket_name"}, "PRIVATE_CONTRACT_SCHEMA_INVALID"
    )
    if (
        not bucket_name_is_valid(packaging.get("bucket_name"))
        or packaging.get("artifact_path") != ARTIFACT_PATH
    ):
        raise _private_failure("PRIVATE_CONTRACT_PACKAGING_INVALID")
    bootstrap = _exact_keys(
        value.get("bootstrap"),
        {"create_judge_secret", "create_packaging_bucket"},
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    if bootstrap != {"create_judge_secret": False, "create_packaging_bucket": False}:
        raise _private_failure("PRIVATE_CONTRACT_BOOTSTRAP_FORBIDDEN")
    judge_secret = _exact_keys(
        value.get("judge_secret"),
        {"creation_policy", "secret_name"},
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    secret_name = judge_secret.get("secret_name")
    if judge_secret.get("creation_policy") != "STACK_OWNED" or secret_name is not None:
        raise _private_failure("PRIVATE_CONTRACT_SECRET_POLICY_INVALID")

    sandbox = _exact_keys(
        value.get("sandbox"),
        {"expected_state", "instance_id", "require_ebs_backed", "tag_key", "tag_value"},
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    instance_id = sandbox.get("instance_id")
    if (
        not isinstance(instance_id, str)
        or INSTANCE_PATTERN.fullmatch(instance_id) is None
        or sandbox.get("tag_key") != "AIOACloudOpsSandbox"
        or sandbox.get("tag_value") != "true"
        or sandbox.get("expected_state") != "running"
        or sandbox.get("require_ebs_backed") is not True
    ):
        raise _private_failure("PRIVATE_CONTRACT_SANDBOX_INVALID")
    cloudwatch = _exact_keys(
        value.get("cloudwatch"),
        {
            "metric_name",
            "minimum_datapoints",
            "namespace",
            "observation_window_minutes",
            "period_seconds",
        },
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    if cloudwatch != {
        "metric_name": "CPUUtilization",
        "minimum_datapoints": 6,
        "namespace": "AWS/EC2",
        "observation_window_minutes": 60,
        "period_seconds": 300,
    }:
        raise _private_failure("PRIVATE_CONTRACT_CLOUDWATCH_INVALID")
    nova = _exact_keys(
        value.get("nova"),
        {"allow_bounded_inference_probe", "inference_profile_id", "region"},
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    if (
        type(nova.get("allow_bounded_inference_probe")) is not bool
        or nova.get("inference_profile_id") != NOVA_PROFILE
        or nova.get("region") != REGION
    ):
        raise _private_failure("PRIVATE_CONTRACT_NOVA_INVALID")
    budget = _exact_keys(
        value.get("budget_notification"),
        {"budget_name", "owner_binding", "owner_type", "thresholds_usd"},
        "PRIVATE_CONTRACT_SCHEMA_INVALID",
    )
    budget_name = budget.get("budget_name")
    owner = budget.get("owner_binding")
    owner_type = budget.get("owner_type")
    sns_match = SNS_ARN_PATTERN.fullmatch(owner) if isinstance(owner, str) else None
    if (
        not budget_name_is_valid(budget_name)
        or not isinstance(owner, str)
        or VISIBLE_PRIVATE_VALUE_PATTERN.fullmatch(owner) is None
        or owner_type not in {"EMAIL", "SNS"}
        or (owner_type == "EMAIL" and EMAIL_PATTERN.fullmatch(owner) is None)
        or (owner_type == "SNS" and (sns_match is None or sns_match.group(1) != account_id))
        or budget.get("thresholds_usd") != [10, 25, 40]
    ):
        raise _private_failure("PRIVATE_CONTRACT_BUDGET_OWNER_INVALID")
    timestamp = value.get("operator_selection_timestamp")
    if not isinstance(timestamp, str) or TIMESTAMP_PATTERN.fullmatch(timestamp) is None:
        raise _private_failure("PRIVATE_CONTRACT_TIMESTAMP_INVALID")
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise _private_failure("PRIVATE_CONTRACT_TIMESTAMP_INVALID") from error
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise _private_failure("PRIVATE_CONTRACT_TIMESTAMP_INVALID")


def load_private_contract(
    path: Path,
    *,
    expected_candidate_digest: str,
    root: Path = ROOT,
) -> dict[str, object]:
    """Load a mode-0600 canonical contract without logging its private values."""

    try:
        metadata = path.lstat()
    except OSError as error:
        raise _private_failure("PRIVATE_CONTRACT_UNAVAILABLE") from error
    if stat.S_ISLNK(metadata.st_mode):
        raise _private_failure("PRIVATE_CONTRACT_SYMLINK_FORBIDDEN")
    if not stat.S_ISREG(metadata.st_mode):
        raise _private_failure("PRIVATE_CONTRACT_NOT_REGULAR")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise _private_failure("PRIVATE_CONTRACT_MODE_INVALID")
    _private_path_allowed(path, root)
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _private_failure("PRIVATE_CONTRACT_JSON_INVALID") from error
    if not isinstance(value, dict) or raw != (canonical_json(value) + "\n").encode("utf-8"):
        raise _private_failure("PRIVATE_CONTRACT_NOT_CANONICAL")
    _validate_private_contract(value, expected_candidate_digest)
    return value
