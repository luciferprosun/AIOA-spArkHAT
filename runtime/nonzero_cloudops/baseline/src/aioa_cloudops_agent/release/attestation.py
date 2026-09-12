"""Commit-bound local Release Candidate attestation and validation."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import tomllib
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
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
    canonical_json,
    contract_sha256,
    operator_input_blockers,
    pretty_json,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
SafePath = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=240,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$",
    ),
]
SafeCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_:.-]{2,160}$")]

ALLOWED_POST_TEST_REPORT = "docs/reports/phase3-local-release-candidate-gate-2026-08-27.md"

ATTESTED_ARTIFACTS: tuple[tuple[str, str], ...] = (
    (
        "docs/architecture/phase3-deployment-ready-local-rc.md",
        "PHASE3_ARCHITECTURE_DOCUMENT",
    ),
    (
        "docs/evidence/release/phase3-expected-resources.json",
        "EXPECTED_RESOURCE_MANIFEST",
    ),
    (
        "docs/evidence/release/phase3-offline-verifier-receipt.json",
        "OFFLINE_VERIFIER_RECEIPT",
    ),
    (
        "docs/evidence/release/phase3-devpost-claim-audit.json",
        "DEVPOST_SENTENCE_AUDIT",
    ),
    ("docs/submission/demo-runbook.md", "DEMO_RUNBOOK"),
    ("docs/submission/devpost-draft.md", "DEVPOST_DRAFT"),
    ("infra/sam/template.yaml", "SAM_TEMPLATE"),
    ("pyproject.toml", "PYTHON_PACKAGE_CONTRACT"),
    ("requirements/day15-toolchain.json", "TOOLCHAIN_LOCK"),
    ("requirements/lambda-runtime.txt", "LAMBDA_DEPENDENCY_LOCK"),
    (
        "requirements/phase3-cleanup-contract.json",
        "ROLLBACK_CLEANUP_CONTRACT",
    ),
    (
        "requirements/phase3-deployment-contract.json",
        "AWS_DEPLOYMENT_CONTRACT",
    ),
    (
        "requirements/phase3-iac-manifest.schema.json",
        "IAC_MANIFEST_SCHEMA",
    ),
    (
        "requirements/phase3-verifier-receipt.schema.json",
        "VERIFIER_RECEIPT_SCHEMA",
    ),
)

QUALITY_CHECK_NAMES = frozenset(
    {
        "DEPLOYMENT_CONTRACT",
        "DEMO_APPROVE",
        "DEMO_DENY",
        "GENERATED_ARTIFACTS",
        "GIT_DIFF_CHECK",
        "IAC_DRY_RUN",
        "OFFLINE_NETWORK_GUARD",
        "PACKAGE_BUILD",
        "PIP_CHECK",
        "REPLAY_PROTECTION",
        "RECOVERY",
        "RUFF",
        "SECRET_SCAN",
        "VERIFIER_LOCAL_CHAIN",
    }
)


class AttestationError(RuntimeError):
    """Public-safe fixed-reason attestation failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StrictAttestationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class TestSuiteEvidence(StrictAttestationModel):
    status: Literal["PASS"]
    passed: int = Field(ge=1, le=100_000)
    skipped: Literal[0]
    duration_seconds: float = Field(gt=0, le=86_400)
    output_sha256: Sha256Digest


class PriorityGateEvidence(StrictAttestationModel):
    status: Literal["PASS"]
    passed_gates: int = Field(ge=1, le=100)
    expected_gates: int = Field(ge=1, le=100)
    proof_tests: int = Field(ge=1, le=100_000)
    skipped: Literal[0]
    output_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_gate_count(self) -> Self:
        if self.passed_gates != self.expected_gates:
            raise ValueError("priority gate must pass every expected gate")
        return self


class LocalGateEvidence(StrictAttestationModel):
    schema_version: Literal[1]
    evidence_type: Literal["PHASE3_EXECUTED_LOCAL_GATE"]
    tested_git_sha: GitSha
    tested_worktree_clean: Literal[True]
    generated_at: datetime
    full_tests: TestSuiteEvidence
    p0: PriorityGateEvidence
    p1: PriorityGateEvidence
    quality_checks: dict[str, Literal["PASS"]]
    network_connections_during_offline_demos: Literal[0]
    provider_network_calls: Literal[0]
    aws_mutations: Literal[0]
    mock_mutations: Literal[1]
    live_receipts: Literal[0]
    evidence_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("local gate evidence timestamp must be UTC")
        if set(self.quality_checks) != QUALITY_CHECK_NAMES:
            raise ValueError("local gate quality-check coverage is incomplete")
        if self.p0.expected_gates != 15 or self.p1.expected_gates != 6:
            raise ValueError("priority gate counts must remain 15 and 6")
        material = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if self.evidence_sha256 != hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest():
            raise ValueError("local gate evidence hash is invalid")
        return self


class ArtifactEvidence(StrictAttestationModel):
    path: SafePath
    purpose: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9_]+$")]
    size_bytes: int = Field(ge=1, le=100_000_000)
    sha256: Sha256Digest


class ReleaseCandidateAttestation(StrictAttestationModel):
    schema_version: Literal[1]
    attestation_type: Literal["AIOA_PHASE3_LOCAL_RELEASE_CANDIDATE"]
    status: Literal["DEPLOYMENT_READY_LOCAL_RC"]
    generated_at: datetime
    rc_identifier: Literal["phase3-local-rc1"]
    release_version: Literal["0.2.0-rc.1"]
    package_version: Literal["0.2.0rc1"]
    repository_git_sha: GitSha
    repository_tree_sha: GitSha
    origin_main_sha: GitSha
    branch: Literal["main"]
    worktree_clean: Literal[True]
    origin_main_matches: Literal[True]
    full_test_subject_sha: GitSha
    post_test_changes: tuple[SafePath, ...]
    python_version: Annotated[str, StringConstraints(pattern=r"^3\.12\.[0-9]+$")]
    runtime_architecture: Literal["x86_64"]
    deployment_contract_sha256: Sha256Digest
    artifacts: tuple[ArtifactEvidence, ...]
    artifact_manifest_sha256: Sha256Digest
    architecture_document_sha256: Sha256Digest
    demo_runbook_sha256: Sha256Digest
    devpost_draft_sha256: Sha256Digest
    dependency_lock_sha256: dict[SafePath, Sha256Digest]
    local_gate_evidence: LocalGateEvidence
    preflight_schema_version: Literal[1]
    verifier_schema_version: Literal[1]
    production_deployed: Literal[False]
    live_verified: Literal[False]
    external_submission_performed: Literal[False]
    external_network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]
    external_blockers: tuple[SafeCode, ...]
    attestation_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_attestation(self) -> Self:
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() != timedelta(0):
            raise ValueError("RC attestation timestamp must be UTC")
        if self.repository_git_sha != self.origin_main_sha or not self.origin_main_matches:
            raise ValueError("RC must be synchronized to origin/main")
        if self.full_test_subject_sha == self.repository_git_sha:
            if self.post_test_changes:
                raise ValueError("same tested and attested commit cannot have post-test changes")
        elif self.post_test_changes != (ALLOWED_POST_TEST_REPORT,):
            raise ValueError("only the exact Phase 3 report may follow the fully tested commit")
        expected_artifacts = tuple(path for path, _purpose in ATTESTED_ARTIFACTS)
        if tuple(item.path for item in self.artifacts) != expected_artifacts:
            raise ValueError("RC artifact coverage or order is invalid")
        if len({item.path for item in self.artifacts}) != len(self.artifacts):
            raise ValueError("RC artifact paths must be unique")
        artifact_material = [item.model_dump(mode="json") for item in self.artifacts]
        if self.artifact_manifest_sha256 != hashlib.sha256(
            canonical_json(artifact_material).encode("utf-8")
        ).hexdigest():
            raise ValueError("artifact manifest hash is invalid")
        hashes = {item.path: item.sha256 for item in self.artifacts}
        if self.architecture_document_sha256 != hashes[ATTESTED_ARTIFACTS[0][0]]:
            raise ValueError("architecture document hash is inconsistent")
        if self.demo_runbook_sha256 != hashes["docs/submission/demo-runbook.md"]:
            raise ValueError("demo runbook hash is inconsistent")
        if self.devpost_draft_sha256 != hashes["docs/submission/devpost-draft.md"]:
            raise ValueError("Devpost draft hash is inconsistent")
        expected_locks = {
            path: hashes[path]
            for path in (
                "pyproject.toml",
                "requirements/day15-toolchain.json",
                "requirements/lambda-runtime.txt",
            )
        }
        if self.dependency_lock_sha256 != expected_locks:
            raise ValueError("dependency lock hashes are incomplete or inconsistent")
        if self.local_gate_evidence.tested_git_sha != self.full_test_subject_sha:
            raise ValueError("full test subject is not gate-evidence bound")
        if tuple(sorted(set(self.external_blockers))) != self.external_blockers:
            raise ValueError("external blockers must be sorted and unique")
        material = self.model_dump(mode="json", exclude={"attestation_sha256"})
        if self.attestation_sha256 != hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest():
            raise ValueError("RC attestation hash is invalid")
        _ensure_public_safe(self.model_dump(mode="json"))
        return self


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], Path, int], CommandResult]


_SENSITIVE_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ASIA[0-9A-Z]{16}"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?<![0-9a-f])[0-9]{12}(?![0-9a-f])"),
    re.compile(r"arn:aws:(?:iam|sts|secretsmanager):"),
    re.compile(r"i-[0-9a-f]{8}(?:[0-9a-f]{9})?"),
)


def _ensure_public_safe(value: object) -> None:
    rendered = canonical_json(value)
    if any(pattern.search(rendered) is not None for pattern in _SENSITIVE_PATTERNS):
        raise AttestationError("RC_ATTESTATION_SECRET_MATERIAL_FORBIDDEN")


def _strict_json(raw: str, *, reason: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise ValueError("duplicate key")
            result[name] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise AttestationError(reason) from error


def load_local_gate_evidence(path: Path) -> LocalGateEvidence:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise AttestationError("LOCAL_GATE_EVIDENCE_UNAVAILABLE") from error
    value = _strict_json(raw, reason="LOCAL_GATE_EVIDENCE_INVALID")
    try:
        evidence = LocalGateEvidence.model_validate_json(raw)
    except ValidationError as error:
        raise AttestationError("LOCAL_GATE_EVIDENCE_INVALID") from error
    _ensure_public_safe(value)
    return evidence


def create_local_gate_evidence(
    *,
    tested_git_sha: str,
    generated_at: datetime,
    full_tests: TestSuiteEvidence,
    p0: PriorityGateEvidence,
    p1: PriorityGateEvidence,
    quality_checks: dict[str, Literal["PASS"]],
) -> LocalGateEvidence:
    """Create a hashed receipt from results that a local gate runner actually executed."""

    material: dict[str, object] = {
        "aws_mutations": 0,
        "evidence_type": "PHASE3_EXECUTED_LOCAL_GATE",
        "full_tests": full_tests.model_dump(mode="json"),
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "live_receipts": 0,
        "mock_mutations": 1,
        "network_connections_during_offline_demos": 0,
        "p0": p0.model_dump(mode="json"),
        "p1": p1.model_dump(mode="json"),
        "provider_network_calls": 0,
        "quality_checks": quality_checks,
        "schema_version": 1,
        "tested_git_sha": tested_git_sha,
        "tested_worktree_clean": True,
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return LocalGateEvidence.model_validate_json(
        canonical_json({**material, "evidence_sha256": digest})
    )


def validate_release_attestation_document(value: object) -> ReleaseCandidateAttestation:
    try:
        raw = value if isinstance(value, str) else canonical_json(value)
        _strict_json(raw, reason="RC_ATTESTATION_INVALID")
        return ReleaseCandidateAttestation.model_validate_json(raw)
    except (ValidationError, AttestationError) as error:
        if isinstance(error, AttestationError) and error.reason == (
            "RC_ATTESTATION_SECRET_MATERIAL_FORBIDDEN"
        ):
            raise
        raise AttestationError("RC_ATTESTATION_INVALID") from error


def _git(
    runner: CommandRunner,
    root: Path,
    *arguments: str,
) -> CommandResult:
    return runner(("git", *arguments), root, 30)


def _git_value(
    runner: CommandRunner,
    root: Path,
    *arguments: str,
) -> str:
    result = _git(runner, root, *arguments)
    value = result.stdout.strip()
    if result.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise AttestationError("RC_GIT_BINDING_UNAVAILABLE")
    return value


def _repository_state(
    root: Path,
    runner: CommandRunner,
    *,
    expected_head: str,
    tested_head: str,
) -> tuple[str, str, str, tuple[str, ...]]:
    head = _git_value(runner, root, "rev-parse", "HEAD")
    tree = _git_value(runner, root, "rev-parse", "HEAD^{tree}")
    origin = _git_value(runner, root, "rev-parse", "refs/remotes/origin/main")
    branch_result = _git(runner, root, "branch", "--show-current")
    status_result = _git(runner, root, "status", "--porcelain")
    if expected_head != head:
        raise AttestationError("RC_EXPECTED_HEAD_MISMATCH")
    if branch_result.returncode != 0 or branch_result.stdout.strip() != "main":
        raise AttestationError("RC_BRANCH_MISMATCH")
    if status_result.returncode != 0 or status_result.stdout:
        raise AttestationError("RC_WORKTREE_NOT_CLEAN")
    if origin != head:
        raise AttestationError("RC_ORIGIN_MAIN_MISMATCH")
    if tested_head == head:
        post_test_changes: tuple[str, ...] = ()
    else:
        diff = _git(runner, root, "diff", "--name-only", f"{tested_head}..{head}")
        if diff.returncode != 0:
            raise AttestationError("RC_POST_TEST_DIFF_UNAVAILABLE")
        post_test_changes = tuple(sorted(line for line in diff.stdout.splitlines() if line))
        if post_test_changes != (ALLOWED_POST_TEST_REPORT,):
            raise AttestationError("RC_POST_TEST_CHANGE_NOT_DOCUMENTATION_ONLY")
    return head, tree, origin, post_test_changes


def _artifact_evidence(root: Path) -> tuple[ArtifactEvidence, ...]:
    artifacts: list[ArtifactEvidence] = []
    for relative, purpose in ATTESTED_ARTIFACTS:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise AttestationError("RC_ARTIFACT_UNAVAILABLE_OR_UNSAFE")
        try:
            data = path.read_bytes()
        except OSError as error:
            raise AttestationError("RC_ARTIFACT_UNAVAILABLE_OR_UNSAFE") from error
        if not data:
            raise AttestationError("RC_ARTIFACT_EMPTY")
        artifacts.append(
            ArtifactEvidence(
                path=relative,
                purpose=purpose,
                size_bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )
    return tuple(artifacts)


def _package_version(root: Path) -> str:
    try:
        value = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        version = value["project"]["version"]
    except (OSError, UnicodeDecodeError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise AttestationError("RC_PACKAGE_VERSION_UNAVAILABLE") from error
    if version != "0.2.0rc1":
        raise AttestationError("RC_PACKAGE_VERSION_MISMATCH")
    return version


def _attestation_material(
    *,
    generated_at: datetime,
    contract: AwsDeploymentContract,
    head: str,
    tree: str,
    origin: str,
    post_test_changes: tuple[str, ...],
    artifacts: tuple[ArtifactEvidence, ...],
    gate_evidence: LocalGateEvidence,
    package_version: str,
) -> dict[str, object]:
    artifact_values = [item.model_dump(mode="json") for item in artifacts]
    hashes = {item.path: item.sha256 for item in artifacts}
    blockers = tuple(
        sorted(
            {
                *operator_input_blockers(contract),
                "AUTHORIZED_LIVE_AWS_DEPLOYMENT_REQUIRED",
                "DEVPOST_OWNER_SUBMISSION_REQUIRED",
                "LIVE_POST_DEPLOY_VERIFICATION_REQUIRED",
            }
        )
    )
    return {
        "architecture_document_sha256": hashes[
            "docs/architecture/phase3-deployment-ready-local-rc.md"
        ],
        "artifact_manifest_sha256": hashlib.sha256(
            canonical_json(artifact_values).encode("utf-8")
        ).hexdigest(),
        "artifacts": artifact_values,
        "attestation_type": "AIOA_PHASE3_LOCAL_RELEASE_CANDIDATE",
        "aws_mutations": 0,
        "branch": "main",
        "demo_runbook_sha256": hashes["docs/submission/demo-runbook.md"],
        "dependency_lock_sha256": {
            path: hashes[path]
            for path in (
                "pyproject.toml",
                "requirements/day15-toolchain.json",
                "requirements/lambda-runtime.txt",
            )
        },
        "deployment_contract_sha256": contract_sha256(contract),
        "devpost_draft_sha256": hashes["docs/submission/devpost-draft.md"],
        "external_blockers": list(blockers),
        "external_network_connections": 0,
        "external_submission_performed": False,
        "full_test_subject_sha": gate_evidence.tested_git_sha,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "live_receipts": 0,
        "live_verified": False,
        "local_gate_evidence": gate_evidence.model_dump(mode="json"),
        "origin_main_matches": True,
        "origin_main_sha": origin,
        "package_version": package_version,
        "post_test_changes": list(post_test_changes),
        "preflight_schema_version": 1,
        "production_deployed": False,
        "python_version": platform.python_version(),
        "rc_identifier": contract.release.rc_identifier.value,
        "release_version": contract.release.version.value,
        "repository_git_sha": head,
        "repository_tree_sha": tree,
        "runtime_architecture": (
            "x86_64"
            if platform.machine().casefold() in {"amd64", "x86_64"}
            else platform.machine().casefold()
        ),
        "schema_version": 1,
        "status": "DEPLOYMENT_READY_LOCAL_RC",
        "verifier_schema_version": 1,
        "worktree_clean": True,
    }


def attest_release_candidate(
    *,
    root: Path,
    contract: AwsDeploymentContract,
    gate_evidence: LocalGateEvidence,
    expected_head: str,
    runner: CommandRunner,
    clock: Callable[[], datetime],
) -> ReleaseCandidateAttestation:
    """Build an attestation only for a clean, pushed, exact repository state."""

    now = clock()
    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise AttestationError("RC_ATTESTATION_CLOCK_INVALID")
    package_version = _package_version(root)
    head, tree, origin, post_test_changes = _repository_state(
        root,
        runner,
        expected_head=expected_head,
        tested_head=gate_evidence.tested_git_sha,
    )
    artifacts = _artifact_evidence(root)
    material = _attestation_material(
        generated_at=now,
        contract=contract,
        head=head,
        tree=tree,
        origin=origin,
        post_test_changes=post_test_changes,
        artifacts=artifacts,
        gate_evidence=gate_evidence,
        package_version=package_version,
    )
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return ReleaseCandidateAttestation.model_validate_json(
        canonical_json({**material, "attestation_sha256": digest})
    )


def validate_release_candidate(
    attestation: ReleaseCandidateAttestation,
    *,
    root: Path,
    expected_head: str,
    runner: CommandRunner,
) -> None:
    """Re-read Git and every artifact; any stale or changed binding invalidates the RC."""

    _package_version(root)
    head, tree, origin, post_test_changes = _repository_state(
        root,
        runner,
        expected_head=expected_head,
        tested_head=attestation.full_test_subject_sha,
    )
    if (
        head != attestation.repository_git_sha
        or tree != attestation.repository_tree_sha
        or origin != attestation.origin_main_sha
        or post_test_changes != attestation.post_test_changes
    ):
        raise AttestationError("RC_ATTESTATION_REPOSITORY_BINDING_MISMATCH")
    if _artifact_evidence(root) != attestation.artifacts:
        raise AttestationError("RC_ATTESTATION_ARTIFACT_DRIFT")
    try:
        contract_path = root / "requirements" / "phase3-deployment-contract.json"
        raw = contract_path.read_text(encoding="utf-8")
        contract = AwsDeploymentContract.model_validate_json(raw)
    except (OSError, UnicodeDecodeError, ValidationError) as error:
        raise AttestationError("RC_DEPLOYMENT_CONTRACT_UNAVAILABLE") from error
    if contract_sha256(contract) != attestation.deployment_contract_sha256:
        raise AttestationError("RC_DEPLOYMENT_CONTRACT_HASH_MISMATCH")
    validate_release_attestation_document(attestation.model_dump(mode="json"))


def render_attestation_schema() -> str:
    return pretty_json(ReleaseCandidateAttestation.model_json_schema(mode="validation"))


def render_local_gate_evidence_schema() -> str:
    return pretty_json(LocalGateEvidence.model_json_schema(mode="validation"))


def render_attestation_markdown() -> str:
    artifacts = [f"- `{path}` — `{purpose}`" for path, purpose in ATTESTED_ARTIFACTS]
    checks = [f"- `{name}`" for name in sorted(QUALITY_CHECK_NAMES)]
    return "\n".join(
        [
            "# Phase 3 Local Release Candidate Attestation",
            "",
            "The attestation status is exactly `DEPLOYMENT_READY_LOCAL_RC`. It never represents a "
            "production deployment, live AWS verification, external submission, or live receipt.",
            "",
            "Generation requires an exact expected HEAD, `main`, a clean worktree, matching "
            "`origin/main`, Python 3.12 on x86_64, the RC package version, valid executed local-gate "
            "evidence, and byte-current artifacts. Validation re-reads Git and every artifact. A "
            "different HEAD, tree, origin, dirty file, changed hash, or stale gate binding fails closed.",
            "",
            "Because a committed report cannot contain its own commit SHA, the attestation permits "
            f"only one explicit post-test delta: `{ALLOWED_POST_TEST_REPORT}`. The final attested HEAD "
            "still must be clean and pushed, and the diff from the fully tested commit is rechecked.",
            "",
            "## Attested artifacts",
            "",
            *artifacts,
            "",
            "## Required local-gate checks",
            "",
            *checks,
            "",
            "The full suite must have zero skips, P0 must pass 15/15, P1 must pass 6/6, and "
            "offline demos/verifier must record zero external connections, zero AWS mutations, and "
            "zero live receipts. The one allowed mutation count is explicitly the protected local mock "
            "approved-path action.",
            "",
        ]
    )
