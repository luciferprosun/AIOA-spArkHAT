from __future__ import annotations

import hashlib
import json
import shutil
import socket
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from scripts.phase3 import build_attestation_contract as builder
from scripts.phase3.attest_release import _write_private

from aioa_cloudops_agent.release.attestation import (
    ALLOWED_POST_TEST_REPORT,
    ATTESTED_ARTIFACTS,
    QUALITY_CHECK_NAMES,
    AttestationError,
    LocalGateEvidence,
    PriorityGateEvidence,
    ReleaseCandidateAttestation,
    _ensure_public_safe,
    attest_release_candidate,
    create_local_gate_evidence,
    render_attestation_markdown,
    render_attestation_schema,
    render_local_gate_evidence_schema,
    validate_release_attestation_document,
    validate_release_candidate,
)
from aioa_cloudops_agent.release.attestation import TestSuiteEvidence as SuiteEvidence
from aioa_cloudops_agent.release.deployment_contract import canonical_json, load_deployment_contract

REPO = Path(__file__).resolve().parents[2]
HEAD = "a" * 40
TREE = "b" * 40
NOW = datetime(2026, 8, 27, 18, 0, tzinfo=UTC)


class FakeRunner:
    def __init__(
        self,
        *,
        head: str = HEAD,
        tree: str = TREE,
        origin: str = HEAD,
        branch: str = "main",
        dirty: bool = False,
        diff_paths: tuple[str, ...] = (),
    ) -> None:
        self.head = head
        self.tree = tree
        self.origin = origin
        self.branch = branch
        self.dirty = dirty
        self.diff_paths = diff_paths
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: object, _root: Path, _timeout: int) -> SimpleNamespace:
        assert isinstance(command, tuple)
        self.calls.append(command)
        if command == ("git", "rev-parse", "HEAD"):
            output = self.head
        elif command == ("git", "rev-parse", "HEAD^{tree}"):
            output = self.tree
        elif command == ("git", "rev-parse", "refs/remotes/origin/main"):
            output = self.origin
        elif command == ("git", "branch", "--show-current"):
            output = self.branch
        elif command == ("git", "status", "--porcelain"):
            output = " M changed.txt" if self.dirty else ""
        elif command[:3] == ("git", "diff", "--name-only"):
            output = "\n".join(self.diff_paths)
        else:
            raise AssertionError(f"unexpected command: {command!r}")
        return SimpleNamespace(returncode=0, stdout=output + ("\n" if output else ""), stderr="")


def _gate(head: str = HEAD) -> LocalGateEvidence:
    return create_local_gate_evidence(
        tested_git_sha=head,
        generated_at=NOW,
        full_tests=SuiteEvidence(
            status="PASS",
            passed=1_300,
            skipped=0,
            duration_seconds=800.0,
            output_sha256="1" * 64,
        ),
        p0=PriorityGateEvidence(
            status="PASS",
            passed_gates=15,
            expected_gates=15,
            proof_tests=136,
            skipped=0,
            output_sha256="2" * 64,
        ),
        p1=PriorityGateEvidence(
            status="PASS",
            passed_gates=6,
            expected_gates=6,
            proof_tests=93,
            skipped=0,
            output_sha256="3" * 64,
        ),
        quality_checks={name: "PASS" for name in QUALITY_CHECK_NAMES},
    )


def _copy_attested_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative, _purpose in ATTESTED_ARTIFACTS:
        source = REPO / relative
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return root


def _attest(root: Path, runner: FakeRunner | None = None, gate: LocalGateEvidence | None = None):
    return attest_release_candidate(
        root=root,
        contract=load_deployment_contract(root / "requirements/phase3-deployment-contract.json"),
        gate_evidence=gate or _gate(),
        expected_head=(runner or FakeRunner()).head,
        runner=runner or FakeRunner(),
        clock=lambda: NOW,
    )


def test_attestation_binds_exact_commit_tree_artifacts_runtime_and_gate(tmp_path: Path) -> None:
    root = _copy_attested_root(tmp_path)
    runner = FakeRunner()

    attestation = _attest(root, runner)

    assert attestation.status == "DEPLOYMENT_READY_LOCAL_RC"
    assert attestation.repository_git_sha == attestation.origin_main_sha == HEAD
    assert attestation.repository_tree_sha == TREE
    assert attestation.worktree_clean is True
    assert attestation.package_version == "0.2.0rc1"
    assert attestation.release_version == "0.2.0-rc.1"
    assert len(attestation.artifacts) == len(ATTESTED_ARTIFACTS)
    assert attestation.local_gate_evidence.full_tests.passed == 1_300
    assert attestation.local_gate_evidence.p0.passed_gates == 15
    assert attestation.local_gate_evidence.p1.passed_gates == 6
    assert attestation.production_deployed is False
    assert attestation.live_verified is False
    assert attestation.external_submission_performed is False
    assert attestation.aws_mutations == attestation.live_receipts == 0
    assert validate_release_attestation_document(attestation.model_dump(mode="json")) == attestation
    validate_release_candidate(attestation, root=root, expected_head=HEAD, runner=runner)


@pytest.mark.parametrize(
    ("runner", "expected_head", "reason"),
    (
        (FakeRunner(dirty=True), HEAD, "RC_WORKTREE_NOT_CLEAN"),
        (FakeRunner(origin="c" * 40), HEAD, "RC_ORIGIN_MAIN_MISMATCH"),
        (FakeRunner(branch="feature"), HEAD, "RC_BRANCH_MISMATCH"),
        (FakeRunner(), "c" * 40, "RC_EXPECTED_HEAD_MISMATCH"),
    ),
)
def test_dirty_origin_branch_and_expected_head_mismatch_fail_closed(
    tmp_path: Path,
    runner: FakeRunner,
    expected_head: str,
    reason: str,
) -> None:
    root = _copy_attested_root(tmp_path)

    with pytest.raises(AttestationError, match=reason):
        attest_release_candidate(
            root=root,
            contract=load_deployment_contract(
                root / "requirements/phase3-deployment-contract.json"
            ),
            gate_evidence=_gate(),
            expected_head=expected_head,
            runner=runner,
            clock=lambda: NOW,
        )


def test_changed_artifact_invalidates_even_if_git_runner_claims_clean(tmp_path: Path) -> None:
    root = _copy_attested_root(tmp_path)
    runner = FakeRunner()
    attestation = _attest(root, runner)
    architecture = root / "docs/architecture/phase3-deployment-ready-local-rc.md"
    architecture.write_text(architecture.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")

    with pytest.raises(AttestationError, match="RC_ATTESTATION_ARTIFACT_DRIFT"):
        validate_release_candidate(attestation, root=root, expected_head=HEAD, runner=runner)


def test_different_head_invalidates_stale_attestation(tmp_path: Path) -> None:
    root = _copy_attested_root(tmp_path)
    attestation = _attest(root)
    changed = FakeRunner(
        head="c" * 40,
        tree="d" * 40,
        origin="c" * 40,
        diff_paths=(ALLOWED_POST_TEST_REPORT,),
    )

    with pytest.raises(AttestationError, match="RC_ATTESTATION_REPOSITORY_BINDING_MISMATCH"):
        validate_release_candidate(
            attestation,
            root=root,
            expected_head="c" * 40,
            runner=changed,
        )


def test_exact_report_only_delta_is_explicit_but_any_code_delta_is_blocked(
    tmp_path: Path,
) -> None:
    root = _copy_attested_root(tmp_path)
    report_only = FakeRunner(diff_paths=(ALLOWED_POST_TEST_REPORT,))
    attestation = _attest(root, report_only, _gate("c" * 40))
    assert attestation.full_test_subject_sha == "c" * 40
    assert attestation.post_test_changes == (ALLOWED_POST_TEST_REPORT,)

    code_delta = FakeRunner(diff_paths=("src/aioa_cloudops_agent/release/unsafe.py",))
    with pytest.raises(
        AttestationError,
        match="RC_POST_TEST_CHANGE_NOT_DOCUMENTATION_ONLY",
    ):
        _attest(root, code_delta, _gate("c" * 40))


def test_mismatched_contract_hash_invalidates_attestation(tmp_path: Path) -> None:
    root = _copy_attested_root(tmp_path)
    runner = FakeRunner()
    attestation = _attest(root, runner)
    value = attestation.model_dump(mode="json")
    value["deployment_contract_sha256"] = "f" * 64
    material = {name: item for name, item in value.items() if name != "attestation_sha256"}
    value["attestation_sha256"] = hashlib.sha256(
        canonical_json(material).encode("utf-8")
    ).hexdigest()
    mismatched = ReleaseCandidateAttestation.model_validate_json(json.dumps(value))

    with pytest.raises(AttestationError, match="RC_DEPLOYMENT_CONTRACT_HASH_MISMATCH"):
        validate_release_candidate(mismatched, root=root, expected_head=HEAD, runner=runner)


def test_gate_evidence_rejects_tamper_skips_missing_checks_and_wrong_gate_counts() -> None:
    evidence = _gate()
    value = evidence.model_dump(mode="json")
    value["full_tests"]["passed"] += 1
    with pytest.raises(ValidationError):
        LocalGateEvidence.model_validate_json(json.dumps(value))

    with pytest.raises(ValidationError):
        SuiteEvidence(
            status="PASS",
            passed=1,
            skipped=1,
            duration_seconds=1.0,
            output_sha256="a" * 64,
        )
    with pytest.raises(ValidationError):
        PriorityGateEvidence(
            status="PASS",
            passed_gates=14,
            expected_gates=15,
            proof_tests=1,
            skipped=0,
            output_sha256="a" * 64,
        )
    incomplete = {name: "PASS" for name in QUALITY_CHECK_NAMES}
    incomplete.pop("SECRET_SCAN")
    with pytest.raises(ValidationError):
        create_local_gate_evidence(
            tested_git_sha=HEAD,
            generated_at=NOW,
            full_tests=evidence.full_tests,
            p0=evidence.p0,
            p1=evidence.p1,
            quality_checks=incomplete,
        )


def test_missing_symlinked_or_wrong_version_artifact_blocks_generation(tmp_path: Path) -> None:
    missing_root = _copy_attested_root(tmp_path / "missing")
    (missing_root / "docs/submission/demo-runbook.md").unlink()
    with pytest.raises(AttestationError, match="RC_ARTIFACT_UNAVAILABLE_OR_UNSAFE"):
        _attest(missing_root)

    symlink_root = _copy_attested_root(tmp_path / "symlink")
    target = symlink_root / "target.md"
    target.write_text("target", encoding="utf-8")
    artifact = symlink_root / "docs/submission/demo-runbook.md"
    artifact.unlink()
    artifact.symlink_to(target)
    with pytest.raises(AttestationError, match="RC_ARTIFACT_UNAVAILABLE_OR_UNSAFE"):
        _attest(symlink_root)

    version_root = _copy_attested_root(tmp_path / "version")
    pyproject = version_root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace("0.2.0rc1", "0.1.0"),
        encoding="utf-8",
    )
    with pytest.raises(AttestationError, match="RC_PACKAGE_VERSION_MISMATCH"):
        _attest(version_root)


def test_attestation_document_rejects_unknown_fields_hash_tamper_and_secrets(
    tmp_path: Path,
) -> None:
    root = _copy_attested_root(tmp_path)
    attestation = _attest(root)
    value = attestation.model_dump(mode="json")
    value["production_url"] = "https://unsupported.invalid"
    with pytest.raises(AttestationError, match="RC_ATTESTATION_INVALID"):
        validate_release_attestation_document(value)

    value = attestation.model_dump(mode="json")
    value["live_receipts"] = 1
    with pytest.raises(AttestationError, match="RC_ATTESTATION_INVALID"):
        validate_release_attestation_document(value)

    with pytest.raises(
        AttestationError,
        match="RC_ATTESTATION_SECRET_MATERIAL_FORBIDDEN",
    ):
        _ensure_public_safe({"value": "AKIA" + "ABCDEFGHIJKLMNOP"})


def test_schemas_and_document_are_exact_deterministic_projections() -> None:
    assert render_attestation_schema() == builder.DEFAULT_ATTESTATION_SCHEMA.read_text(
        encoding="utf-8"
    )
    assert render_local_gate_evidence_schema() == builder.DEFAULT_GATE_EVIDENCE_SCHEMA.read_text(
        encoding="utf-8"
    )
    assert render_attestation_markdown() == builder.DEFAULT_DOCUMENT.read_text(encoding="utf-8")
    assert builder.build(check=True)["status"] == "PASS"


def test_private_writer_is_owner_only_and_rejects_symlink(tmp_path: Path) -> None:
    output = tmp_path / "attestation.json"
    _write_private(output, "{}\n")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    target = tmp_path / "target"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(AttestationError, match="RC_OUTPUT_SYMLINK_FORBIDDEN"):
        _write_private(link, "changed")
    assert target.read_text(encoding="utf-8") == "preserve"


def test_attestation_with_fake_git_opens_no_network_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("attestation attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)

    attestation = _attest(_copy_attested_root(tmp_path))
    assert attestation.external_network_connections == attestation.aws_mutations == 0
