"""Deterministic Phase 3 preflight with local and fixture-only AWS checks."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .deployment_contract import (
    AwsDeploymentContract,
    DeploymentContractError,
    canonical_json,
    contract_sha256,
    load_deployment_contract,
    operator_input_blockers,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ReasonCode = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_:.-]{2,127}$")]
ExternalBlockerCode = Annotated[
    str,
    StringConstraints(pattern=r"^EXTERNAL_OPERATOR_INPUT_REQUIRED:[a-z0-9_.]{3,160}$"),
]
CheckIdentifier = Annotated[str, StringConstraints(pattern=r"^P3-PF-[0-9]{3}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]

_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"(?<![0-9a-f])[0-9]{12}(?![0-9a-f])"),
    re.compile(r"arn:aws:(?:iam|sts|secretsmanager):"),
    re.compile(r"i-[0-9a-f]{8}(?:[0-9a-f]{9})?"),
)
_SAFE_REFERENCE = re.compile(r"^(?:fixture|local|repo|contract|gate):[A-Za-z0-9._/#:-]{1,256}$")


class PreflightError(RuntimeError):
    """Fixed-reason preflight failure with no provider detail."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class CheckClass(StrEnum):
    LOCAL = "LOCAL"
    FUTURE_READ_ONLY_AWS = "FUTURE_READ_ONLY_AWS"
    REQUIRES_EXPLICIT_MUTATION_APPROVAL = "REQUIRES_EXPLICIT_MUTATION_APPROVAL"


class CheckOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"
    NOT_RUN_EXTERNAL = "NOT_RUN_EXTERNAL"


class PreflightMode(StrEnum):
    LOCAL_ONLY = "LOCAL_ONLY"
    OFFLINE_AWS_FIXTURE = "OFFLINE_AWS_FIXTURE"


class PreflightStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED_EXTERNAL = "BLOCKED_EXTERNAL"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class PreflightCheck(StrictModel):
    check_id: CheckIdentifier
    classification: CheckClass
    title: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9-]+$")


CHECKS: tuple[PreflightCheck, ...] = (
    PreflightCheck(
        check_id="P3-PF-001",
        classification=CheckClass.LOCAL,
        title="deployment-contract",
    ),
    PreflightCheck(
        check_id="P3-PF-002",
        classification=CheckClass.LOCAL,
        title="expected-head-and-branch",
    ),
    PreflightCheck(
        check_id="P3-PF-003",
        classification=CheckClass.LOCAL,
        title="clean-origin-synchronized-worktree",
    ),
    PreflightCheck(
        check_id="P3-PF-004",
        classification=CheckClass.LOCAL,
        title="runtime-and-packaging-prerequisites",
    ),
    PreflightCheck(
        check_id="P3-PF-005",
        classification=CheckClass.LOCAL,
        title="p0-p1-gate-definitions",
    ),
    PreflightCheck(
        check_id="P3-PF-006",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="credential-source-presence",
    ),
    PreflightCheck(
        check_id="P3-PF-007",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="sts-caller-identity",
    ),
    PreflightCheck(
        check_id="P3-PF-008",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="account-region-allowlist",
    ),
    PreflightCheck(
        check_id="P3-PF-009",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="role-permission-separation",
    ),
    PreflightCheck(
        check_id="P3-PF-010",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="bedrock-model-access",
    ),
    PreflightCheck(
        check_id="P3-PF-011",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="service-quotas-and-availability",
    ),
    PreflightCheck(
        check_id="P3-PF-012",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="resource-name-collisions",
    ),
    PreflightCheck(
        check_id="P3-PF-013",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="sandbox-tags-cloudwatch-evidence",
    ),
    PreflightCheck(
        check_id="P3-PF-014",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="artifact-bucket-and-secret-controls",
    ),
    PreflightCheck(
        check_id="P3-PF-015",
        classification=CheckClass.FUTURE_READ_ONLY_AWS,
        title="budget-owner-notifications",
    ),
    PreflightCheck(
        check_id="P3-PF-016",
        classification=CheckClass.REQUIRES_EXPLICIT_MUTATION_APPROVAL,
        title="deployment-mutation-approval",
    ),
)


class PreflightCheckResult(StrictModel):
    check_id: CheckIdentifier
    classification: CheckClass
    title: str
    outcome: CheckOutcome
    executed: bool
    fixture: bool
    reasons: tuple[ReasonCode, ...] = ()
    evidence_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_semantics(self) -> Self:
        if tuple(sorted(set(self.reasons))) != self.reasons:
            raise ValueError("preflight reasons must be sorted and unique")
        if tuple(sorted(set(self.evidence_references))) != self.evidence_references:
            raise ValueError("evidence references must be sorted and unique")
        if any(_SAFE_REFERENCE.fullmatch(item) is None for item in self.evidence_references):
            raise ValueError("evidence reference is not public-safe")
        if self.outcome is CheckOutcome.PASS and not self.executed:
            raise ValueError("an unexecuted check cannot pass")
        if self.outcome is CheckOutcome.NOT_RUN_EXTERNAL and self.executed:
            raise ValueError("a NOT_RUN_EXTERNAL check cannot be executed")
        if self.fixture and (
            not self.executed
            or self.classification is not CheckClass.FUTURE_READ_ONLY_AWS
        ):
            raise ValueError("only executed read-only AWS checks may use fixture evidence")
        if self.outcome is CheckOutcome.PASS and self.reasons:
            raise ValueError("passing checks cannot contain reasons")
        if self.outcome is not CheckOutcome.PASS and not self.reasons:
            raise ValueError("non-passing checks require a reason")
        return self


class AwsPreflightFixture(StrictModel):
    """Closed synthetic observation set; it never represents a live receipt."""

    schema_version: Literal[1]
    fixture_id: Literal["PHASE3_OFFLINE_AWS_PREFLIGHT_V1"]
    synthetic: Literal[True]
    credential_source_present: bool
    sts_identity_authenticated: bool
    expected_account_match: bool
    expected_region_match: bool
    role_permissions_match: bool
    read_write_roles_separate: bool
    bedrock_model_access: bool
    service_quotas_sufficient: bool
    required_services_available: bool
    resource_name_collisions_absent: bool
    sandbox_target_exact: bool
    sandbox_tag_exact: bool
    cloudwatch_evidence_sufficient: bool
    artifact_bucket_controls_match: bool
    judge_secret_authority_match: bool
    budget_owner_and_notifications_match: bool
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipt: Literal[False]


class PreflightReceipt(StrictModel):
    schema_version: Literal[1]
    receipt_type: Literal["PHASE3_PREFLIGHT"]
    mode: PreflightMode
    status: PreflightStatus
    generated_at: datetime
    repo_sha: GitSha
    expected_repo_sha: GitSha
    deployment_contract_sha256: Sha256Digest
    deployment_contract_external_blockers: tuple[ExternalBlockerCode, ...]
    checks: tuple[PreflightCheckResult, ...]
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]
    secrets_redacted: Literal[True]
    receipt_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("preflight timestamp must be UTC")
        if tuple(item.check_id for item in self.checks) != tuple(item.check_id for item in CHECKS):
            raise ValueError("preflight check order or coverage is invalid")
        expected_status = _combined_status(self.checks)
        if self.status is not expected_status:
            raise ValueError("preflight status is inconsistent")
        if tuple(sorted(set(self.deployment_contract_external_blockers))) != (
            self.deployment_contract_external_blockers
        ):
            raise ValueError("contract blockers must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"receipt_sha256"})
        expected_hash = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
        if self.receipt_sha256 != expected_hash:
            raise ValueError("preflight receipt hash is invalid")
        _ensure_public_safe(self.model_dump(mode="json"))
        return self


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path, Mapping[str, str], int], CommandResult]


def sanitized_local_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Remove every credential/provider authority input from child checks."""

    blocked_names = {
        "AWS_ACCESS_KEY_ID",
        "AWS_CONFIG_FILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "BOTO_CONFIG",
        "NETRC",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
    }
    result = {
        name: value
        for name, value in base.items()
        if name not in blocked_names
        and not name.startswith("AWS_ENDPOINT_URL")
        and not name.startswith("AIOA_")
        and not name.startswith("BEDROCK_")
        and not name.startswith("SANDBOX_")
    }
    result.update(
        {
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return result


def _ensure_public_safe(value: object) -> None:
    rendered = canonical_json(value)
    if any(pattern.search(rendered) is not None for pattern in _SENSITIVE_VALUE_PATTERNS):
        raise PreflightError("PREFLIGHT_RECEIPT_SENSITIVE_VALUE_FORBIDDEN")
    if any(
        marker in rendered.casefold()
        for marker in (
            "aws_secret_access_key=",
            "aws_session_token=",
            "authorization: bearer",
            "private_endpoint",
        )
    ):
        raise PreflightError("PREFLIGHT_RECEIPT_SENSITIVE_VALUE_FORBIDDEN")


def load_aws_fixture(path: Path) -> AwsPreflightFixture:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PreflightError("AWS_PREFLIGHT_FIXTURE_UNAVAILABLE") from error
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, item in values:
            if name in result:
                raise ValueError("duplicate fixture key")
            result[name] = item
        return result

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
        fixture = AwsPreflightFixture.model_validate_json(raw)
    except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as error:
        raise PreflightError("AWS_PREFLIGHT_FIXTURE_INVALID") from error
    _ensure_public_safe(value)
    return fixture


def fixture_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result(
    definition: PreflightCheck,
    outcome: CheckOutcome,
    *,
    executed: bool,
    fixture: bool = False,
    reasons: Sequence[str] = (),
    evidence: Sequence[str] = (),
) -> PreflightCheckResult:
    return PreflightCheckResult(
        check_id=definition.check_id,
        classification=definition.classification,
        title=definition.title,
        outcome=outcome,
        executed=executed,
        fixture=fixture,
        reasons=tuple(sorted(set(reasons))),
        evidence_references=tuple(sorted(set(evidence))),
    )


def _git(
    root: Path,
    arguments: Sequence[str],
    environment: Mapping[str, str],
    runner: CommandRunner,
) -> CommandResult:
    return runner(("git", *arguments), root, environment, 30)


def _git_value(result: CommandResult, pattern: re.Pattern[str]) -> str | None:
    value = result.stdout.strip()
    if result.returncode != 0 or pattern.fullmatch(value) is None:
        return None
    return value


_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def _local_results(
    *,
    root: Path,
    contract: AwsDeploymentContract,
    contract_path: Path,
    expected_head: str | None,
    runner: CommandRunner,
    environment: Mapping[str, str],
) -> tuple[str, list[PreflightCheckResult]]:
    results: list[PreflightCheckResult] = []
    head = _git_value(_git(root, ("rev-parse", "HEAD"), environment, runner), _GIT_SHA_PATTERN)

    results.append(
        _result(
            CHECKS[0],
            CheckOutcome.PASS,
            executed=True,
            evidence=(
                "contract:requirements/phase3-deployment-contract.json",
                f"contract:sha256/{contract_sha256(contract)}",
            ),
        )
    )

    branch_result = _git(root, ("branch", "--show-current"), environment, runner)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    head_reasons: list[str] = []
    if head is None:
        head_reasons.append("REPOSITORY_HEAD_UNAVAILABLE")
    if expected_head is None:
        head_reasons.append("EXPECTED_HEAD_REQUIRED")
    elif _GIT_SHA_PATTERN.fullmatch(expected_head) is None:
        head_reasons.append("EXPECTED_HEAD_INVALID")
    elif head is not None and head != expected_head:
        head_reasons.append("EXPECTED_HEAD_MISMATCH")
    if branch != contract.release.branch.value:
        head_reasons.append("EXPECTED_BRANCH_MISMATCH")
    results.append(
        _result(
            CHECKS[1],
            CheckOutcome.PASS if not head_reasons else CheckOutcome.FAIL,
            executed=True,
            reasons=head_reasons,
            evidence=("repo:HEAD", "repo:branch/main"),
        )
    )

    status = _git(root, ("status", "--porcelain"), environment, runner)
    remote = _git_value(
        _git(root, ("rev-parse", "refs/remotes/origin/main"), environment, runner),
        _GIT_SHA_PATTERN,
    )
    sync_reasons: list[str] = []
    if status.returncode != 0:
        sync_reasons.append("WORKTREE_STATUS_UNAVAILABLE")
    elif status.stdout:
        sync_reasons.append("WORKTREE_NOT_CLEAN")
    if head is None or remote is None:
        sync_reasons.append("ORIGIN_MAIN_UNAVAILABLE")
    elif head != remote:
        sync_reasons.append("ORIGIN_MAIN_MISMATCH")
    results.append(
        _result(
            CHECKS[2],
            CheckOutcome.PASS if not sync_reasons else CheckOutcome.FAIL,
            executed=True,
            reasons=sync_reasons,
            evidence=("repo:origin/main", "repo:worktree-status"),
        )
    )

    runtime_reasons: list[str] = []
    if sys.version_info[:2] != (3, 12):
        runtime_reasons.append("PYTHON_RUNTIME_MISMATCH")
    if platform.machine().casefold() not in {"x86_64", "amd64"}:
        runtime_reasons.append("BUILD_ARCHITECTURE_MISMATCH")
    required_paths = (
        root / str(contract.infrastructure.template_path.value),
        root / "requirements" / "lambda-runtime.txt",
        root / "requirements" / "day15-toolchain.json",
        root / "pyproject.toml",
    )
    if any(not path.is_file() for path in required_paths):
        runtime_reasons.append("PACKAGING_PREREQUISITE_MISSING")
    results.append(
        _result(
            CHECKS[3],
            CheckOutcome.PASS if not runtime_reasons else CheckOutcome.FAIL,
            executed=True,
            reasons=runtime_reasons,
            evidence=(
                "local:python/3.12",
                "repo:requirements/lambda-runtime.txt",
                "repo:requirements/day15-toolchain.json",
                f"repo:{contract_path.relative_to(root).as_posix()}",
            ),
        )
    )

    gate_reasons: list[str] = []
    for name, command in (
        (
            "p0",
            (sys.executable, "scripts/run_p0_gate.py", "--validate-only", "--json"),
        ),
        (
            "p1",
            (sys.executable, "scripts/run_p1_gate.py", "--validate-only", "--json"),
        ),
    ):
        proof = runner(command, root, environment, 120)
        try:
            payload = json.loads(proof.stdout)
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = None
        if proof.returncode != 0 or not isinstance(payload, dict) or payload.get("status") != "PASS":
            gate_reasons.append(f"{name.upper()}_GATE_DEFINITION_INVALID")
    results.append(
        _result(
            CHECKS[4],
            CheckOutcome.PASS if not gate_reasons else CheckOutcome.FAIL,
            executed=True,
            reasons=gate_reasons,
            evidence=("gate:P0/validate-only", "gate:P1/validate-only"),
        )
    )
    return head or "0" * 40, results


def _fixture_results(
    fixture: AwsPreflightFixture,
    *,
    reference: str,
) -> list[PreflightCheckResult]:
    definitions = CHECKS[5:15]
    observations: tuple[tuple[bool, str, CheckOutcome], ...] = (
        (
            fixture.credential_source_present,
            "AWS_CREDENTIAL_SOURCE_NOT_AVAILABLE",
            CheckOutcome.BLOCKED_EXTERNAL,
        ),
        (
            fixture.sts_identity_authenticated,
            "STS_IDENTITY_NOT_AUTHENTICATED",
            CheckOutcome.BLOCKED_EXTERNAL,
        ),
        (
            fixture.expected_account_match and fixture.expected_region_match,
            "ACCOUNT_OR_REGION_MISMATCH",
            CheckOutcome.FAIL,
        ),
        (
            fixture.role_permissions_match and fixture.read_write_roles_separate,
            "ROLE_PERMISSION_EXPECTATION_MISMATCH",
            CheckOutcome.FAIL,
        ),
        (
            fixture.bedrock_model_access,
            "BEDROCK_MODEL_ACCESS_NOT_PROVEN",
            CheckOutcome.BLOCKED_EXTERNAL,
        ),
        (
            fixture.service_quotas_sufficient and fixture.required_services_available,
            "SERVICE_OR_QUOTA_PREREQUISITE_NOT_PROVEN",
            CheckOutcome.BLOCKED_EXTERNAL,
        ),
        (
            fixture.resource_name_collisions_absent,
            "RESOURCE_NAME_COLLISION_DETECTED",
            CheckOutcome.FAIL,
        ),
        (
            fixture.sandbox_target_exact
            and fixture.sandbox_tag_exact
            and fixture.cloudwatch_evidence_sufficient,
            "SANDBOX_OR_CLOUDWATCH_EVIDENCE_MISMATCH",
            CheckOutcome.FAIL,
        ),
        (
            fixture.artifact_bucket_controls_match
            and fixture.judge_secret_authority_match,
            "BUCKET_OR_SECRET_CONTROL_MISMATCH",
            CheckOutcome.FAIL,
        ),
        (
            fixture.budget_owner_and_notifications_match,
            "BUDGET_OWNER_NOTIFICATION_NOT_PROVEN",
            CheckOutcome.BLOCKED_EXTERNAL,
        ),
    )
    return [
        _result(
            definition,
            CheckOutcome.PASS if passed else failure_outcome,
            executed=True,
            fixture=True,
            reasons=() if passed else (reason,),
            evidence=(reference,),
        )
        for definition, (passed, reason, failure_outcome) in zip(
            definitions,
            observations,
            strict=True,
        )
    ]


def _not_run_external_results() -> list[PreflightCheckResult]:
    return [
        _result(
            definition,
            CheckOutcome.NOT_RUN_EXTERNAL,
            executed=False,
            reasons=("READ_ONLY_AWS_CHECK_NOT_RUN",),
        )
        for definition in CHECKS[5:15]
    ]


def _combined_status(results: Sequence[PreflightCheckResult]) -> PreflightStatus:
    outcomes = {item.outcome for item in results}
    if CheckOutcome.FAIL in outcomes:
        return PreflightStatus.FAIL
    if outcomes & {CheckOutcome.BLOCKED_EXTERNAL, CheckOutcome.NOT_RUN_EXTERNAL}:
        return PreflightStatus.BLOCKED_EXTERNAL
    return PreflightStatus.PASS


def _receipt(
    *,
    mode: PreflightMode,
    generated_at: datetime,
    repo_sha: str,
    expected_repo_sha: str,
    contract: AwsDeploymentContract,
    results: Sequence[PreflightCheckResult],
) -> PreflightReceipt:
    material = {
        "aws_mutations": 0,
        "checks": [item.model_dump(mode="json") for item in results],
        "deployment_contract_external_blockers": list(operator_input_blockers(contract)),
        "deployment_contract_sha256": contract_sha256(contract),
        "expected_repo_sha": expected_repo_sha,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "live_receipts": 0,
        "mode": mode.value,
        "network_connections": 0,
        "receipt_type": "PHASE3_PREFLIGHT",
        "repo_sha": repo_sha,
        "schema_version": 1,
        "secrets_redacted": True,
        "status": _combined_status(results).value,
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return PreflightReceipt.model_validate_json(
        canonical_json({**material, "receipt_sha256": digest})
    )


def run_preflight(
    *,
    root: Path,
    contract_path: Path,
    expected_head: str | None,
    mode: PreflightMode = PreflightMode.LOCAL_ONLY,
    fixture_path: Path | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    runner: CommandRunner | None = None,
    environment: Mapping[str, str] | None = None,
) -> PreflightReceipt:
    """Run local checks and optional synthetic AWS checks; never open a network path."""

    if runner is None:
        raise PreflightError("PREFLIGHT_LOCAL_COMMAND_RUNNER_REQUIRED")
    try:
        contract = load_deployment_contract(contract_path)
    except DeploymentContractError as error:
        raise PreflightError(error.reason) from error
    now = clock()
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise PreflightError("UTC_CLOCK_UNAVAILABLE")
    sanitized = sanitized_local_environment(environment or os.environ)
    repo_sha, results = _local_results(
        root=root,
        contract=contract,
        contract_path=contract_path,
        expected_head=expected_head,
        runner=runner,
        environment=sanitized,
    )
    if mode is PreflightMode.OFFLINE_AWS_FIXTURE:
        if fixture_path is None:
            raise PreflightError("AWS_PREFLIGHT_FIXTURE_REQUIRED")
        fixture = load_aws_fixture(fixture_path)
        reference = f"fixture:aws-preflight#sha256-{fixture_sha256(fixture_path)}"
        results.extend(_fixture_results(fixture, reference=reference))
    else:
        if fixture_path is not None:
            raise PreflightError("AWS_PREFLIGHT_FIXTURE_NOT_ALLOWED")
        results.extend(_not_run_external_results())
    results.append(
        _result(
            CHECKS[15],
            CheckOutcome.NOT_RUN_EXTERNAL,
            executed=False,
            reasons=("EXPLICIT_DEPLOYMENT_APPROVAL_NOT_PROVIDED",),
        )
    )
    expected = expected_head if expected_head and _GIT_SHA_PATTERN.fullmatch(expected_head) else "0" * 40
    return _receipt(
        mode=mode,
        generated_at=now,
        repo_sha=repo_sha,
        expected_repo_sha=expected,
        contract=contract,
        results=results,
    )


def validate_preflight_receipt(value: object) -> PreflightReceipt:
    try:
        if isinstance(value, str):
            return PreflightReceipt.model_validate_json(value)
        return PreflightReceipt.model_validate_json(canonical_json(value))
    except (ValidationError, ValueError, PreflightError) as error:
        raise PreflightError("PREFLIGHT_RECEIPT_INVALID") from error
