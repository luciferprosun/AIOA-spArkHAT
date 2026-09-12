from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from scripts.day15 import g10_candidate as candidate
from scripts.day15.validate_template import DEFAULT_TEMPLATE, canonical_json

HEAD = "1" * 40
OTHER_HEAD = "2" * 40


def _write_canonical(path: Path, value: object, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def _full_gate_result(prefix: str, count: int) -> dict[str, object]:
    gates = [
        {
            "gate_id": f"{prefix}-{index:02d}",
            "name": f"proof-{index}",
            "proof_tests": index,
            "reasons": [],
            "skipped": 0,
            "status": "PASS",
        }
        for index in range(1, count + 1)
    ]
    return {
        "gate_count": count,
        "gates": gates,
        "gates_fail": 0,
        "gates_pass": count,
        "gates_skipped": 0,
        "matrix_reasons": [],
        "status": "PASS",
    }


def _candidate_inputs(tmp_path: Path, *, manifest_head: str = HEAD) -> dict[str, Path]:
    artifact = tmp_path / "artifact.zip"
    artifact.write_bytes(b"exact-lambda-archive")
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = tmp_path / "artifact-manifest.json"
    _write_canonical(
        manifest,
        {
            "artifact": {"sha256": artifact_sha},
            "repository": {"commit_oid": manifest_head},
            "schema_version": 1,
        },
    )
    scan = tmp_path / "dependency-scan.json"
    _write_canonical(scan, {"artifact_sha256": artifact_sha, "status": "PASS"})
    contract = tmp_path / "deployment-contract.json"
    _write_canonical(contract, {"region": candidate.REGION, "schema_version": 1})
    rendered = tmp_path / "rendered-template.yaml"
    rendered.write_bytes(b"exact-rendered-template\n")
    provenance = tmp_path / "render-provenance.json"
    _write_canonical(
        provenance,
        {
            "rendered_template_sha256": hashlib.sha256(rendered.read_bytes()).hexdigest(),
            "repository_commit_oid": HEAD,
            "schema_version": 1,
        },
    )
    reviewer = tmp_path / "reviewer-manifest.json"
    reviewer.write_bytes(b'{\n  "actual_reviewer_manifest": true\n}\n')
    p0 = tmp_path / "p0-full-result.json"
    p1 = tmp_path / "p1-full-result.json"
    _write_canonical(p0, _full_gate_result("P0", 15))
    _write_canonical(p1, _full_gate_result("P1", 6))
    return {
        "artifact_path": artifact,
        "artifact_manifest_path": manifest,
        "dependency_scan_path": scan,
        "deployment_contract_path": contract,
        "source_template_path": DEFAULT_TEMPLATE,
        "rendered_template_path": rendered,
        "render_provenance_path": provenance,
        "reviewer_manifest_path": reviewer,
        "p0_result_path": p0,
        "p1_result_path": p1,
    }


def test_candidate_descriptor_is_stable_closed_and_binds_actual_reviewer_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _candidate_inputs(tmp_path)
    monkeypatch.setattr(candidate, "_clean_head", lambda _root: HEAD)

    first = candidate.build_candidate_descriptor(root=tmp_path, **inputs)
    second = candidate.build_candidate_descriptor(root=tmp_path, **inputs)

    assert first == second
    assert set(first) == {
        "candidate_digest",
        "components",
        "region",
        "schema_version",
        "source_commit",
    }
    assert first["source_commit"] == HEAD
    assert first["region"] == candidate.REGION
    assert set(first["components"]) == candidate.COMPONENT_KEYS
    assert (
        first["components"]["reviewer_manifest_sha256"]
        == hashlib.sha256(inputs["reviewer_manifest_path"].read_bytes()).hexdigest()
    )
    assert first["candidate_digest"] == candidate.derive_candidate_digest(
        source_commit=HEAD,
        region=candidate.REGION,
        components=first["components"],
    )


@pytest.mark.parametrize("component", sorted(candidate.COMPONENT_KEYS))
def test_candidate_digest_changes_for_every_component(component: str) -> None:
    components = {
        name: hashlib.sha256(name.encode()).hexdigest() for name in candidate.COMPONENT_KEYS
    }
    original = candidate.derive_candidate_digest(
        source_commit=HEAD, region=candidate.REGION, components=components
    )
    changed = dict(components)
    changed[component] = hashlib.sha256((component + "-changed").encode()).hexdigest()

    assert (
        candidate.derive_candidate_digest(
            source_commit=HEAD, region=candidate.REGION, components=changed
        )
        != original
    )


def test_candidate_digest_changes_with_clean_head() -> None:
    components = {
        name: hashlib.sha256(name.encode()).hexdigest() for name in candidate.COMPONENT_KEYS
    }
    assert candidate.derive_candidate_digest(
        source_commit=HEAD, region=candidate.REGION, components=components
    ) != candidate.derive_candidate_digest(
        source_commit=OTHER_HEAD, region=candidate.REGION, components=components
    )


def test_candidate_rejects_stale_artifact_or_render_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = _candidate_inputs(tmp_path, manifest_head=OTHER_HEAD)
    monkeypatch.setattr(candidate, "_clean_head", lambda _root: HEAD)
    with pytest.raises(candidate.CandidateFailure, match="CANDIDATE_ARTIFACT_HEAD_MISMATCH"):
        candidate.build_candidate_descriptor(root=tmp_path, **inputs)

    inputs = _candidate_inputs(tmp_path)
    provenance = json.loads(inputs["render_provenance_path"].read_text(encoding="utf-8"))
    provenance["repository_commit_oid"] = OTHER_HEAD
    _write_canonical(inputs["render_provenance_path"], provenance)
    with pytest.raises(candidate.CandidateFailure, match="CANDIDATE_RENDER_HEAD_MISMATCH"):
        candidate.build_candidate_descriptor(root=tmp_path, **inputs)


def test_candidate_rejects_dirty_worktree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outputs = iter((HEAD, " M tracked.py"))
    monkeypatch.setattr(candidate, "_git_output", lambda _root, *_args: next(outputs))
    with pytest.raises(candidate.CandidateFailure, match="CANDIDATE_WORKTREE_NOT_CLEAN"):
        candidate._clean_head(tmp_path)


@pytest.mark.parametrize(("prefix", "count"), (("P0", 15), ("P1", 6)))
def test_candidate_requires_canonical_complete_gate_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prefix: str,
    count: int,
) -> None:
    inputs = _candidate_inputs(tmp_path)
    monkeypatch.setattr(candidate, "_clean_head", lambda _root: HEAD)
    key = "p0_result_path" if prefix == "P0" else "p1_result_path"
    result = _full_gate_result(prefix, count)
    result["gates_pass"] = count - 1
    _write_canonical(inputs[key], result)

    with pytest.raises(candidate.CandidateFailure, match=f"{prefix}_RESULT_NOT_FULL_PASS"):
        candidate.build_candidate_descriptor(root=tmp_path, **inputs)

    _write_canonical(inputs[key], _full_gate_result(prefix, count))
    inputs[key].write_text("  " + inputs[key].read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(candidate.CandidateFailure, match=f"{prefix}_RESULT_NOT_CANONICAL"):
        candidate.build_candidate_descriptor(root=tmp_path, **inputs)


def _private_contract(digest: str = "d" * 64) -> dict[str, object]:
    account_id = "1" * 12
    return {
        "bootstrap": {"create_judge_secret": False, "create_packaging_bucket": False},
        "budget_notification": {
            "budget_name": "aioa-day15-budget",
            "owner_binding": "private-owner" + "@example.invalid",
            "owner_type": "EMAIL",
            "thresholds_usd": [10, 25, 40],
        },
        "candidate_digest": digest,
        "cloudwatch": {
            "metric_name": "CPUUtilization",
            "minimum_datapoints": 6,
            "namespace": "AWS/EC2",
            "observation_window_minutes": 60,
            "period_seconds": 300,
        },
        "deployment_role_arn": (
            f"arn:aws:iam::{account_id}:role/AIOANonZeroCloudOpsDay15DeploymentRole"
        ),
        "expected_account_id": account_id,
        "judge_secret": {"creation_policy": "STACK_OWNED", "secret_name": None},
        "nova": {
            "allow_bounded_inference_probe": False,
            "inference_profile_id": candidate.NOVA_PROFILE,
            "region": candidate.REGION,
        },
        "operator_selection_timestamp": "2026-08-24T19:00:00Z",
        "packaging": {
            "artifact_path": candidate.ARTIFACT_PATH,
            "bucket_name": "private-day15-artifacts",
        },
        "region": candidate.REGION,
        "sandbox": {
            "expected_state": "running",
            "instance_id": "i-" + "a" * 17,
            "require_ebs_backed": True,
            "tag_key": "AIOACloudOpsSandbox",
            "tag_value": "true",
        },
        "schema_version": 1,
        "selected_profile": "aioa-day15-deployer",
        "selection_source": "PRIVATE_CONTRACT",
        "stack_name": candidate.STACK_NAME,
    }


def _outside_contract(tmp_path: Path, value: dict[str, object] | None = None) -> tuple[Path, Path]:
    root = tmp_path / "repository"
    root.mkdir()
    path = tmp_path / "private" / "contract.json"
    _write_canonical(path, value or _private_contract(), mode=0o600)
    return root, path


def test_private_contract_loads_only_canonical_mode_0600_file_outside_repository(
    tmp_path: Path,
) -> None:
    root, path = _outside_contract(tmp_path)
    loaded = candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)
    assert loaded == _private_contract()


def test_private_contract_rejects_permissions_and_symlink(tmp_path: Path) -> None:
    root, path = _outside_contract(tmp_path)
    path.chmod(0o640)
    with pytest.raises(candidate.PrivateContractFailure, match="PRIVATE_CONTRACT_MODE_INVALID"):
        candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)

    path.chmod(0o600)
    link = tmp_path / "private" / "contract-link.json"
    link.symlink_to(path)
    with pytest.raises(
        candidate.PrivateContractFailure, match="PRIVATE_CONTRACT_SYMLINK_FORBIDDEN"
    ):
        candidate.load_private_contract(link, expected_candidate_digest="d" * 64, root=root)


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        (lambda value: value.update({"unexpected": True}), "PRIVATE_CONTRACT_SCHEMA_INVALID"),
        (lambda value: value.update({"selected_profile": ""}), "PRIVATE_CONTRACT_PROFILE_INVALID"),
        (
            lambda value: value.update({"selected_profile": "another-explicit-profile"}),
            "PRIVATE_CONTRACT_PROFILE_INVALID",
        ),
        (
            lambda value: value.update({"selection_source": "DEFAULT_PROFILE"}),
            "PRIVATE_CONTRACT_SELECTION_SOURCE_INVALID",
        ),
        (
            lambda value: value.update({"expected_account_id": "1" * 11}),
            "PRIVATE_CONTRACT_ACCOUNT_ROLE_INVALID",
        ),
        (
            lambda value: value.update(
                {"deployment_role_arn": (f"arn:aws:iam::{'1' * 12}:role/another-deployment-role")}
            ),
            "PRIVATE_CONTRACT_ACCOUNT_ROLE_INVALID",
        ),
        (
            lambda value: value.update({"region": "us-east-1"}),
            "PRIVATE_CONTRACT_REGION_OR_STACK_INVALID",
        ),
        (
            lambda value: value["sandbox"].update({"tag_value": "false"}),
            "PRIVATE_CONTRACT_SANDBOX_INVALID",
        ),
        (
            lambda value: value["sandbox"].update({"instance_id": "DISCOVER_AUTOMATICALLY"}),
            "PRIVATE_CONTRACT_SANDBOX_INVALID",
        ),
        (
            lambda value: value["bootstrap"].update({"create_packaging_bucket": True}),
            "PRIVATE_CONTRACT_BOOTSTRAP_FORBIDDEN",
        ),
        (
            lambda value: value["packaging"].update({"bucket_name": "invalid..bucket"}),
            "PRIVATE_CONTRACT_PACKAGING_INVALID",
        ),
        (
            lambda value: value["packaging"].update({"bucket_name": "192.168.1.1"}),
            "PRIVATE_CONTRACT_PACKAGING_INVALID",
        ),
        (
            lambda value: value["judge_secret"].update({"secret_name": "preexisting-secret"}),
            "PRIVATE_CONTRACT_SECRET_POLICY_INVALID",
        ),
        (
            lambda value: value["budget_notification"].update({"owner_binding": "not-an-email"}),
            "PRIVATE_CONTRACT_BUDGET_OWNER_INVALID",
        ),
        (
            lambda value: value["budget_notification"].update({"budget_name": "invalid:name"}),
            "PRIVATE_CONTRACT_BUDGET_OWNER_INVALID",
        ),
        (
            lambda value: value["budget_notification"].update(
                {
                    "owner_binding": ("arn:aws:sns:eu-central-1:" + "2" * 12 + ":wrong-account"),
                    "owner_type": "SNS",
                }
            ),
            "PRIVATE_CONTRACT_BUDGET_OWNER_INVALID",
        ),
    ),
)
def test_private_contract_rejects_schema_and_authority_drift(
    tmp_path: Path,
    change: object,
    reason: str,
) -> None:
    value = copy.deepcopy(_private_contract())
    change(value)
    root, path = _outside_contract(tmp_path, value)
    with pytest.raises(candidate.PrivateContractFailure, match=reason) as failure:
        candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)
    assert value.get("expected_account_id", "") not in str(failure.value)


def test_private_contract_rejects_stale_candidate_digest(tmp_path: Path) -> None:
    root, path = _outside_contract(tmp_path)
    with pytest.raises(
        candidate.PrivateContractFailure, match="PRIVATE_CONTRACT_CANDIDATE_MISMATCH"
    ):
        candidate.load_private_contract(path, expected_candidate_digest="e" * 64, root=root)


def _git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_private_contract_inside_repository_must_be_ignored_and_untracked(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    (root / ".gitignore").write_text(".aioa-private/\n", encoding="utf-8")
    path = root / ".aioa-private" / "contract.json"
    _write_canonical(path, _private_contract(), mode=0o600)
    assert (
        candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)
        == _private_contract()
    )

    _git(root, "add", "-f", ".aioa-private/contract.json")
    with pytest.raises(
        candidate.PrivateContractFailure, match="PRIVATE_CONTRACT_TRACKED_PATH_FORBIDDEN"
    ):
        candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)


def test_private_contract_rejects_any_other_repository_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    path = root / "private-contract.json"
    _write_canonical(path, _private_contract(), mode=0o600)
    with pytest.raises(
        candidate.PrivateContractFailure, match="PRIVATE_CONTRACT_REPOSITORY_PATH_FORBIDDEN"
    ):
        candidate.load_private_contract(path, expected_candidate_digest="d" * 64, root=root)


def test_private_contract_example_is_canonical_closed_placeholder() -> None:
    path = candidate.ROOT / "docs" / "operations" / "day15-private-contract.example.json"
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw)
    assert raw == canonical_json(value) + "\n"
    assert set(value) == candidate.PRIVATE_TOP_LEVEL_KEYS
    assert value["bootstrap"] == {
        "create_judge_secret": False,
        "create_packaging_bucket": False,
    }
    assert value["selected_profile"] == candidate.DEPLOYMENT_PROFILE
    assert str(value["deployment_role_arn"]).endswith(f":role/{candidate.DEPLOYMENT_ROLE_LEAF}")
    assert value["judge_secret"] == {"creation_policy": "STACK_OWNED", "secret_name": None}
