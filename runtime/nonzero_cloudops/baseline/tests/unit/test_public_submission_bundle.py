from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from scripts.build_public_submission import (
    ARCHIVE_NAME,
    BUNDLE_NAME,
    PublicBundleError,
    build_bundle,
    classify_path,
    source_entries,
)

ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=True,
        timeout=10,
    )


def _fixture_repository(root: Path) -> None:
    _git(root, "init", "--quiet")
    _write(root / "README.md", "# Frozen B5 README\n")
    _write(root / "LICENSE", "MIT fixture\n")
    _write(root / "PRIOR-ART.md", "No imported code.\n")
    _write(root / "src/example.py", "VALUE = 1\n")
    _write(root / "docs/audits/internal.md", "internal\n")
    _write(root / ".env", "fixture-only\n")
    _write(root / "docs/submission/public/README.md", "# Public README\n")
    _write(
        root / "docs/submission/PUBLICATION_EXCLUSIONS.md",
        "# Publication exclusions\n",
    )
    _write(
        root / "docs/evidence/release/portable-b5-build-complete-attestation.json",
        json.dumps(
            {
                "attestation_sha256": "a" * 64,
                "aws_calls": 0,
                "aws_mutations": 0,
                "container_digest": "sha256:" + "b" * 64,
                "container_id": "c" * 64,
                "limitations": "local only",
                "publications": 0,
                "source_commit": "d" * 40,
                "status": "BUILD_COMPLETE",
            }
        )
        + "\n",
    )
    _git(root, "add", ".")


def test_policy_classifies_public_private_generated_secret_and_legal_paths() -> None:
    assert classify_path("src/example.py").name == "PUBLIC_REQUIRED"
    assert classify_path("tests/unit/test_example.py").name == "PUBLIC_ALLOWED"
    assert classify_path("docs/audits/private.md").name == "PRIVATE_INTERNAL"
    assert classify_path("README.md").name == "GENERATED"
    assert classify_path("LICENSE").name == "LEGAL_REVIEW"
    assert classify_path("operator.pem").name == "SECRET_RISK"


def test_index_inventory_rejects_symlinks(tmp_path: Path) -> None:
    _git(tmp_path, "init", "--quiet")
    (tmp_path / "target").write_text("safe\n", encoding="utf-8")
    (tmp_path / "link").symlink_to("target")
    _git(tmp_path, "add", ".")

    with pytest.raises(PublicBundleError, match="PUBLIC_SOURCE_SYMLINK_OR_SPECIAL_FILE"):
        source_entries(tmp_path, "INDEX")


def test_bundle_is_deterministic_and_inventories_every_index_blob(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _fixture_repository(repository)
    first = tmp_path / "first"
    second = tmp_path / "second"

    receipt_one = build_bundle(root=repository, source_ref="INDEX", output_root=first)
    receipt_two = build_bundle(root=repository, source_ref="INDEX", output_root=second)

    assert receipt_one["status"] == receipt_two["status"] == "PASS"
    assert receipt_one["archive_sha256"] == receipt_two["archive_sha256"]
    assert (first / ARCHIVE_NAME).read_bytes() == (second / ARCHIVE_NAME).read_bytes()

    candidate = first / BUNDLE_NAME
    manifest = json.loads((candidate / "PUBLICATION_MANIFEST.json").read_text())
    source = source_entries(repository, "INDEX")
    assert manifest["inventory_count"] == len(source)
    assert len(manifest["inventory"]) == len({entry["path"] for entry in manifest["inventory"]})
    by_path = {entry["path"]: entry for entry in manifest["inventory"]}
    assert by_path["README.md"]["classification"] == "GENERATED"
    assert by_path["README.md"]["included"] is False
    assert by_path["docs/audits/internal.md"]["classification"] == "PRIVATE_INTERNAL"
    assert by_path[".env"]["classification"] == "SECRET_RISK"
    assert (candidate / "README.md").read_text() == "# Public README\n"
    assert not (candidate / "docs/audits/internal.md").exists()
    assert not (candidate / ".env").exists()
    assert (candidate / "B5_BUILD_COMPLETE_REFERENCE.json").is_file()

    listed_sums = (candidate / "SHA256SUMS").read_text().splitlines()
    assert listed_sums == sorted(listed_sums, key=lambda line: line.split("  ", 1)[1])
    assert all(not line.endswith("  SHA256SUMS") for line in listed_sums)
    with zipfile.ZipFile(first / ARCHIVE_NAME) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert f"{BUNDLE_NAME}/README.md" in names
        assert f"{BUNDLE_NAME}/PUBLICATION_MANIFEST.json" in names

    assert receipt_one["archive_sha256"] == hashlib.sha256(
        (first / ARCHIVE_NAME).read_bytes()
    ).hexdigest()


def test_bundle_refuses_nonempty_output_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    _fixture_repository(repository)
    output = tmp_path / "output"
    output.mkdir()
    (output / "owner-file").write_text("preserve\n", encoding="utf-8")

    with pytest.raises(PublicBundleError, match="PUBLIC_OUTPUT_DIRECTORY_NOT_EMPTY"):
        build_bundle(root=repository, source_ref="INDEX", output_root=output)


def test_public_docs_cover_required_judge_contract() -> None:
    readme = (ROOT / "docs/submission/public/README.md").read_text(encoding="utf-8")
    required_fragments = (
        "Strands Agents SDK",
        "Non-Zero",
        "## Architecture",
        "## Quick start",
        "approve",
        "deny",
        "recovery",
        "replay",
        "## Environment contract",
        "## Evidence and claims",
        "## Known limitations",
        "## License and hackathon disclosure",
    )
    assert all(fragment in readme for fragment in required_fragments)
    for path in (
        "docs/submission/ARCHITECTURE.md",
        "docs/submission/DEMO_SCRIPT_DRAFT.md",
        "docs/submission/DEVPOST_CLAIMS_MATRIX.md",
        "docs/submission/PRIOR_ART_DISCLOSURE.md",
        "docs/submission/PUBLICATION_EXCLUSIONS.md",
        "docs/submission/REPRODUCIBILITY.md",
    ):
        assert (ROOT / path).is_file()


def test_every_claim_proof_path_exists_and_is_exportable() -> None:
    proof_paths = (
        "Dockerfile",
        "LICENSE",
        "PRIOR-ART.md",
        "docs/JUDGE_EXPERIENCE.md",
        "docs/architecture/provider-neutral-strands-runtime.md",
        "docs/evidence/release/portable-b5-artifact-manifest.json",
        "docs/evidence/release/portable-b5-container-gate.json",
        "docs/evidence/release/portable-b5-image-privacy-scan.json",
        "docs/evidence/release/portable-b5-nonroot-runtime.json",
        "requirements/build.lock",
        "requirements/portable.lock",
        "src/aioa_cloudops_agent/agent/factory.py",
        "src/aioa_cloudops_agent/nz/authority.py",
        "src/aioa_cloudops_agent/providers/factory.py",
        "src/aioa_cloudops_agent/verification/service.py",
        "tests/integration/test_durable_hitl_approval_flow.py",
        "tests/integration/test_human_approved_remediation_e2e.py",
        "tests/integration/test_local_hitl_execution.py",
        "tests/integration/test_local_provider_strands_compatibility.py",
        "tests/integration/test_portable_judge_experience.py",
        "tests/integration/test_portable_judge_sandbox.py",
        "tests/unit/test_identifiers_and_approval.py",
        "tests/unit/test_judge_console_ui.py",
        "tests/unit/test_nz_authority.py",
        "tests/unit/test_portable_runtime_boundary.py",
        "tests/unit/test_recovery_reconciliation.py",
        "tests/unit/test_safety_hardening.py",
        "tests/unit/test_strands_agent.py",
        "tests/unit/test_verification_closure.py",
    )
    assert all((ROOT / path).is_file() for path in proof_paths)
    assert all(classify_path(path).included for path in proof_paths)
