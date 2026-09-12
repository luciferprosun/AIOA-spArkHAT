from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.day15 import validate_blocker_report as blocker
from scripts.day15.validate_template import canonical_json


def _report() -> dict[str, object]:
    return json.loads(blocker.DEFAULT_REPORT.read_text(encoding="utf-8"))


def _write_canonical(path: Path, value: object) -> Path:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")
    return path


def _validate_report_at(path: Path) -> dict[str, object]:
    return blocker.validate_blocker_report(report_path=path)


def test_final_blocker_report_authenticates_exact_m2_candidate() -> None:
    result = blocker.validate_blocker_report()

    assert result["status"] == "PASS"
    assert result["report_status"] == "BLOCKED"
    assert result["ready_for_deployment"] is False
    assert result["aws_state_changed"] is False
    assert result["local_gate"] == "9_PASS_1_BLOCKED"
    assert result["m2_commit"] == blocker.FINAL_M2


def test_blocker_report_must_be_canonical_json(tmp_path: Path) -> None:
    path = tmp_path / "pretty.json"
    path.write_text(json.dumps(_report(), indent=2) + "\n", encoding="utf-8")

    with pytest.raises(blocker.BlockerReportFailure, match="BLOCKER_REPORT_INVALID"):
        _validate_report_at(path)


def test_blocker_report_rejects_rebound_artifact_hash(tmp_path: Path) -> None:
    report = _report()
    candidate = report["candidate"]
    assert isinstance(candidate, dict)
    candidate["artifact_sha256"] = "f" * 64
    path = _write_canonical(tmp_path / "rebound.json", report)

    with pytest.raises(blocker.BlockerReportFailure, match="BLOCKER_CANDIDATE_INVALID"):
        _validate_report_at(path)


def test_blocker_report_requires_every_external_prerequisite(tmp_path: Path) -> None:
    report = _report()
    prerequisites = report["missing_or_unproven_external_prerequisites"]
    assert isinstance(prerequisites, list)
    prerequisites.pop()
    path = _write_canonical(tmp_path / "missing-prerequisite.json", report)

    with pytest.raises(
        blocker.BlockerReportFailure,
        match="BLOCKER_EXTERNAL_PREREQUISITES_INVALID",
    ):
        _validate_report_at(path)


def test_blocker_report_rejects_any_true_aws_mutation_indicator(tmp_path: Path) -> None:
    report = _report()
    activity = report["aws_activity"]
    assert isinstance(activity, dict)
    activity["stop_instances_dry_run_called"] = True
    path = _write_canonical(tmp_path / "mutation.json", report)

    with pytest.raises(blocker.BlockerReportFailure, match="BLOCKER_AWS_ACTIVITY_INVALID"):
        _validate_report_at(path)


@pytest.mark.parametrize(
    "sensitive",
    [
        "123456" + "789012",
        "i-01234567" + "89abcdef0",
        "arn:aws:secretsmanager:eu-central-1:" + "123456" + "789012:secret:judge",
        "192.0." + "2.44",
        "operator" + "@example.test",
        "AK" + "IAABCDEFGHIJKLMNOP",
        "-----BEGIN " + "PRIVATE KEY-----",
    ],
)
def test_blocker_report_rejects_identity_sensitive_values(sensitive: str) -> None:
    with pytest.raises(
        blocker.BlockerReportFailure,
        match="BLOCKER_REPORT_SENSITIVE_IDENTIFIER_FORBIDDEN",
    ):
        blocker._validate_no_sensitive_identifiers({"unexpected": sensitive})


def test_blocker_report_rejects_changed_recovery_lineage(tmp_path: Path) -> None:
    report = _report()
    commits = report["source_commits"]
    assert isinstance(commits, dict)
    commits["recovered_m1"] = blocker.PRESERVED_M1
    path = _write_canonical(tmp_path / "wrong-lineage.json", report)

    with pytest.raises(blocker.BlockerReportFailure, match="BLOCKER_SOURCE_COMMITS_INVALID"):
        _validate_report_at(path)


def test_blocker_report_rejects_noncanonical_or_changed_local_gate(tmp_path: Path) -> None:
    gate = json.loads(blocker.DEFAULT_LOCAL_GATE.read_text(encoding="utf-8"))
    gate["counts"]["pass"] = 8
    path = _write_canonical(tmp_path / "changed-gate.json", gate)

    with pytest.raises(
        blocker.BlockerReportFailure,
        match="BLOCKER_LOCAL_GATE_SHA256_MISMATCH",
    ):
        blocker.validate_blocker_report(local_gate_path=path)


def test_blocker_report_recomputes_candidate_file_hashes(tmp_path: Path) -> None:
    path = tmp_path / "aioa-lambda.zip"
    path.write_bytes(b"not-the-reviewed-artifact")

    with pytest.raises(blocker.BlockerReportFailure, match="BLOCKER_ARTIFACT_INVALID"):
        blocker.validate_blocker_report(artifact_path=path)
