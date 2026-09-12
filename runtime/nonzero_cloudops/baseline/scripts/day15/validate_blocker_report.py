#!/usr/bin/env python3
"""Authenticate the historical, non-deploying Day 15 M2 blocker snapshot.

The default paths validate the immutable digests recorded for the reviewed M2
commit and prove its recovered lineage. Explicit/custom paths, or
``--validate-current-candidate``, recompute candidate bytes from the current tree.
Neither successful mode is deployment authorization.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from itertools import pairwise
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.validate_template import (  # noqa: E402
    canonical_json,
    lambda_configuration_sha256,
    load_template,
)

DEFAULT_REPORT: Final = (
    ROOT / "docs" / "evidence" / "deployment" / ("day15-deployment-blockers.json")
)
DEFAULT_LOCAL_GATE: Final = ROOT / "docs" / "evidence" / "deployment" / "day15-local-gate-m2.json"
DEFAULT_ARTIFACT: Final = ROOT / "dist" / "day15" / "aioa-lambda.zip"
DEFAULT_MANIFEST: Final = ROOT / "dist" / "day15" / "aioa-lambda.manifest.json"
DEFAULT_SCAN: Final = ROOT / "dist" / "day15" / "pip-audit.json"
DEFAULT_RENDERED_TEMPLATE: Final = ROOT / "dist" / "day15" / "rendered-template.yaml"
DEFAULT_RENDER_PROVENANCE: Final = ROOT / "dist" / "day15" / "rendered-template.provenance.json"
DEFAULT_DEPLOYMENT_CONTRACT: Final = ROOT / "requirements" / "day15-deployment-contract.json"
DEFAULT_SOURCE_TEMPLATE: Final = ROOT / "infra" / "sam" / "template.yaml"

RECOVERY_BASELINE: Final = "aa941a989a8b8cd0e40367bb130472e9f3c082a7"
PRESERVED_M1: Final = "17d5f4637dbd69a33eff1cbb46282c36b19ce6ad"
PRESERVED_M2: Final = "8e4583ac9341cb7b66de47cf0e7b2a442ac67b32"
PRESERVED_M3: Final = "30c2a30cda0ac6d6e2003166daf6c29bf2c764f0"
RECOVERED_M1: Final = "f2ee79c09ba174ba72cb527b70c095f412151758"
FINAL_M2: Final = "36fd17df981dfa593d4e63f6a143410317410763"

EXPECTED_CANDIDATE: Final = {
    "artifact_sha256": "399fce019af3ee8a596ffb05ab37ad7f0ac5266bfed32363c2b5c6f8e66846cf",
    "dependency_scan_sha256": "f4f7831f77bc9826ece9a93fcd16b4fbaca3f579f524a2760fe94e9006e719c7",
    "deployment_contract_sha256": (
        "cc4dc67a4a2db65efd62d9dd81d021f2ee2f3ca583f783aea07a13a886b5211c"
    ),
    "lambda_configuration_sha256": (
        "67afd13d45f19b62993a78bd8a1ae61a6b67364370791533615ed53a2ebe830f"
    ),
    "manifest_sha256": "c2045cfd66ad05b512def07ecbb0165af2b3831eedb240666cb929b198067ea9",
    "region": "eu-central-1",
    "rendered_template_provenance_sha256": (
        "3452fa1402a653cc2a4940268f876350f40dbbd2a205c7b30d00b8f693a38acc"
    ),
    "rendered_template_sha256": (
        "b36b749d1913362142fe2ddaedec52fa105bf11cd4b2ffda1560cd00af4891d2"
    ),
}
EXPECTED_LOCAL_GATE_SHA256: Final = (
    "802b1521f3166aa719c7ace6dc5e8a79a9e81f0bd310c479323a00f499cf32a3"
)
EXPECTED_G10_REASONS: Final = [
    "DEPLOYMENT_CONTRACT_SELECTION_REQUIRED",
    "EXTERNAL_PREFLIGHT_RECEIPT_REQUIRED",
]
EXPECTED_EXTERNAL_PREREQUISITES: Final = [
    "AUTHORIZED_AWS_PROFILE_AND_ROLE",
    "CORRECT_HACKATHON_AWS_ACCOUNT",
    "EU_CENTRAL_1_DEPLOYMENT_REGION",
    "ENCRYPTED_PRIVATE_SHORT_LIFECYCLE_PACKAGING_BUCKET_AND_PATH",
    "DEDICATED_JUDGE_TOKEN_SECRET_CREATE_AND_READ",
    "PREEXISTING_OPERATOR_SELECTED_SANDBOX_EC2",
    "EXACT_SANDBOX_TAG_AIOA_CLOUD_OPS_SANDBOX_TRUE",
    "SANDBOX_TARGET_IN_EU_CENTRAL_1",
    "SUFFICIENT_CLOUDWATCH_READ_ONLY_DATA",
    "NOVA_2_EU_INFERENCE_PROFILE_ACCESS",
    "REQUIRED_BUDGET_NOTIFICATION_OWNERSHIP",
]
EXPECTED_AWS_ACTIVITY: Final = {
    "aws_state_changed": False,
    "change_set_created": False,
    "deployment_performed": False,
    "final_candidate_aws_api_calls_performed": False,
    "function_url_created": False,
    "live_stop_instances_called": False,
    "public_approval_route_created": False,
    "public_mutation_route_created": False,
    "reboot_instances_called": False,
    "start_instances_called": False,
    "stop_instances_dry_run_called": False,
    "tag_mutation_called": False,
    "terminate_instances_called": False,
    "write_calls_performed": False,
}
EXPECTED_DEPLOYED_BY_RECOVERY: Final = {
    "dynamodb_table": False,
    "function_url": False,
    "judge_token_secret": False,
    "log_or_telemetry_resources": False,
    "orchestrator_lambda": False,
    "private_executor_lambda": False,
    "stack": False,
}
EXPECTED_OBSERVATIONS: Final = {
    "candidate_bound_external_receipt": "NOT_PROVIDED",
    "deployment_contract_selection": "NOT_PROVIDED",
    "exact_named_profile_configured_locally": False,
    "final_candidate_external_resource_state": "UNPROVEN",
    "recovered_safe_identity_read": "NO_AUTHORIZED_IDENTITY_RETURNED",
}

ACCOUNT_ID_PATTERN: Final = re.compile(r"(?<!\d)\d{12}(?!\d)")
ARN_PATTERN: Final = re.compile(r"\barn:aws(?:-[a-z]+)*:", re.IGNORECASE)
EC2_ID_PATTERN: Final = re.compile(r"\bi-[0-9a-f]{8,17}\b", re.IGNORECASE)
EMAIL_PATTERN: Final = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
IP_ADDRESS_PATTERN: Final = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\."
    r"(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
ACCESS_KEY_PATTERN: Final = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
PRIVATE_KEY_PATTERN: Final = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


class BlockerReportFailure(RuntimeError):
    """Raised when blocker evidence is incomplete, unauthentic, or unsafe."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path, reason: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise BlockerReportFailure(reason)
    try:
        return path.read_bytes()
    except OSError as error:
        raise BlockerReportFailure(reason) from error


def _canonical_object(path: Path, reason: str) -> tuple[dict[str, object], bytes]:
    raw = _read_bytes(path, reason)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BlockerReportFailure(reason) from error
    if not isinstance(value, dict) or raw != (canonical_json(value) + "\n").encode():
        raise BlockerReportFailure(reason)
    return value, raw


def _require_exact(actual: object, expected: object, reason: str) -> None:
    if actual != expected:
        raise BlockerReportFailure(reason)


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    try:
        result = subprocess.run(
            ("git", "merge-base", "--is-ancestor", ancestor, descendant),
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _validate_lineage(source_commits: object) -> None:
    expected = {
        "final_m2": FINAL_M2,
        "preserved_m1": PRESERVED_M1,
        "preserved_m2": PRESERVED_M2,
        "preserved_m3_blocker": PRESERVED_M3,
        "recovered_m1": RECOVERED_M1,
        "recovery_baseline": RECOVERY_BASELINE,
    }
    _require_exact(source_commits, expected, "BLOCKER_SOURCE_COMMITS_INVALID")
    ordered = (
        RECOVERY_BASELINE,
        PRESERVED_M1,
        PRESERVED_M2,
        PRESERVED_M3,
        RECOVERED_M1,
        FINAL_M2,
    )
    if any(not _git_is_ancestor(first, second) for first, second in pairwise(ordered)):
        raise BlockerReportFailure("BLOCKER_SOURCE_LINEAGE_INVALID")
    if not _git_is_ancestor(FINAL_M2, "HEAD"):
        raise BlockerReportFailure("BLOCKER_M2_NOT_IN_CURRENT_HISTORY")


def _validate_local_gate(value: dict[str, object], raw: bytes) -> None:
    if _sha256(raw) != EXPECTED_LOCAL_GATE_SHA256:
        raise BlockerReportFailure("BLOCKER_LOCAL_GATE_SHA256_MISMATCH")
    expected_summary = {
        "aws_calls_performed": False,
        "counts": {"blocked": 1, "fail": 0, "partial": 0, "pass": 9},
        "deployment_performed": False,
        "gate_count": 10,
        "mode": "full",
        "ready_for_deployment": False,
        "schema_version": 1,
        "status": "BLOCKED",
    }
    for key, expected in expected_summary.items():
        _require_exact(value.get(key), expected, "BLOCKER_LOCAL_GATE_SUMMARY_INVALID")
    gates = value.get("gates")
    if not isinstance(gates, list) or len(gates) != 10:
        raise BlockerReportFailure("BLOCKER_LOCAL_GATE_SET_INVALID")
    for index, gate in enumerate(gates, start=1):
        if not isinstance(gate, dict) or gate.get("gate_id") != f"D15-G{index:02d}":
            raise BlockerReportFailure("BLOCKER_LOCAL_GATE_SET_INVALID")
        expected_status = "BLOCKED" if index == 10 else "PASS"
        expected_reasons = EXPECTED_G10_REASONS if index == 10 else []
        if gate.get("status") != expected_status or gate.get("reasons") != expected_reasons:
            raise BlockerReportFailure("BLOCKER_LOCAL_GATE_RESULT_INVALID")


def _validate_candidate_files(
    *,
    artifact_path: Path,
    manifest_path: Path,
    scan_path: Path,
    rendered_template_path: Path,
    render_provenance_path: Path,
    deployment_contract_path: Path,
    source_template_path: Path,
) -> None:
    paths_and_hashes = (
        (artifact_path, EXPECTED_CANDIDATE["artifact_sha256"], "BLOCKER_ARTIFACT_INVALID"),
        (
            manifest_path,
            EXPECTED_CANDIDATE["manifest_sha256"],
            "BLOCKER_ARTIFACT_MANIFEST_INVALID",
        ),
        (scan_path, EXPECTED_CANDIDATE["dependency_scan_sha256"], "BLOCKER_SCAN_INVALID"),
        (
            rendered_template_path,
            EXPECTED_CANDIDATE["rendered_template_sha256"],
            "BLOCKER_RENDERED_TEMPLATE_INVALID",
        ),
        (
            render_provenance_path,
            EXPECTED_CANDIDATE["rendered_template_provenance_sha256"],
            "BLOCKER_RENDER_PROVENANCE_INVALID",
        ),
        (
            deployment_contract_path,
            EXPECTED_CANDIDATE["deployment_contract_sha256"],
            "BLOCKER_DEPLOYMENT_CONTRACT_INVALID",
        ),
    )
    for path, expected_hash, reason in paths_and_hashes:
        if _sha256(_read_bytes(path, reason)) != expected_hash:
            raise BlockerReportFailure(reason)

    manifest, _ = _canonical_object(manifest_path, "BLOCKER_ARTIFACT_MANIFEST_INVALID")
    repository = manifest.get("repository")
    artifact = manifest.get("artifact")
    if (
        not isinstance(repository, dict)
        or repository.get("commit_oid") != FINAL_M2
        or repository.get("status") != "CLEAN"
        or not isinstance(artifact, dict)
        or artifact.get("sha256") != EXPECTED_CANDIDATE["artifact_sha256"]
        or manifest.get("lambda_like_clean_import") != "PASS"
    ):
        raise BlockerReportFailure("BLOCKER_ARTIFACT_MANIFEST_INVALID")

    scan, _ = _canonical_object(scan_path, "BLOCKER_SCAN_INVALID")
    if (
        scan.get("status") != "PASS"
        or scan.get("artifact_sha256") != EXPECTED_CANDIDATE["artifact_sha256"]
        or scan.get("vulnerability_count") != 0
    ):
        raise BlockerReportFailure("BLOCKER_SCAN_INVALID")

    provenance, _ = _canonical_object(render_provenance_path, "BLOCKER_RENDER_PROVENANCE_INVALID")
    if (
        provenance.get("status") != "PASS"
        or provenance.get("repository_commit_oid") != FINAL_M2
        or provenance.get("rendered_template_sha256")
        != EXPECTED_CANDIDATE["rendered_template_sha256"]
    ):
        raise BlockerReportFailure("BLOCKER_RENDER_PROVENANCE_INVALID")

    configuration_sha256 = lambda_configuration_sha256(load_template(source_template_path))
    if configuration_sha256 != EXPECTED_CANDIDATE["lambda_configuration_sha256"]:
        raise BlockerReportFailure("BLOCKER_LAMBDA_CONFIGURATION_INVALID")


def _validate_external_blockers(value: object) -> None:
    if not isinstance(value, list):
        raise BlockerReportFailure("BLOCKER_EXTERNAL_PREREQUISITES_INVALID")
    expected = [
        {
            "evidence": "NO_CANDIDATE_BOUND_AUTHENTICATED_RECEIPT",
            "external_state": "UNPROVEN",
            "prerequisite": name,
        }
        for name in EXPECTED_EXTERNAL_PREREQUISITES
    ]
    _require_exact(value, expected, "BLOCKER_EXTERNAL_PREREQUISITES_INVALID")


def _validate_no_sensitive_identifiers(value: object) -> None:
    strings: list[str] = []

    def collect(item: object) -> None:
        if isinstance(item, dict):
            for child in item.values():
                collect(child)
        elif isinstance(item, list):
            for child in item:
                collect(child)
        elif isinstance(item, str):
            strings.append(item)

    collect(value)
    patterns = (
        ACCOUNT_ID_PATTERN,
        ARN_PATTERN,
        EC2_ID_PATTERN,
        EMAIL_PATTERN,
        IP_ADDRESS_PATTERN,
        ACCESS_KEY_PATTERN,
        PRIVATE_KEY_PATTERN,
    )
    if any(pattern.search(item) for item in strings for pattern in patterns):
        raise BlockerReportFailure("BLOCKER_REPORT_SENSITIVE_IDENTIFIER_FORBIDDEN")


def validate_blocker_report(
    *,
    report_path: Path = DEFAULT_REPORT,
    local_gate_path: Path = DEFAULT_LOCAL_GATE,
    artifact_path: Path = DEFAULT_ARTIFACT,
    manifest_path: Path = DEFAULT_MANIFEST,
    scan_path: Path = DEFAULT_SCAN,
    rendered_template_path: Path = DEFAULT_RENDERED_TEMPLATE,
    render_provenance_path: Path = DEFAULT_RENDER_PROVENANCE,
    deployment_contract_path: Path = DEFAULT_DEPLOYMENT_CONTRACT,
    source_template_path: Path = DEFAULT_SOURCE_TEMPLATE,
    validate_candidate_files: bool | None = None,
) -> dict[str, object]:
    """Validate immutable M2 blocker evidence, optionally against supplied files.

    The default report is historical evidence for ``FINAL_M2``. A later candidate is
    expected to replace generated dist files, so default validation authenticates the
    sealed report and tracked local-gate bytes without misrepresenting the current
    worktree as M2. Supplying any candidate path (or setting the explicit flag) turns
    on byte-for-byte candidate recomputation.
    """

    report, report_raw = _canonical_object(report_path, "BLOCKER_REPORT_INVALID")
    expected_keys = {
        "aws_activity",
        "candidate",
        "decision",
        "deployed_by_this_recovery",
        "external_observations",
        "external_prerequisites_pass",
        "local_gate",
        "missing_or_unproven_external_prerequisites",
        "phase_package",
        "ready_for_deployment",
        "schema_version",
        "source_commits",
        "status",
    }
    if set(report) != expected_keys:
        raise BlockerReportFailure("BLOCKER_REPORT_SCHEMA_INVALID")
    expected_scalars = {
        "decision": "DO_NOT_DEPLOY",
        "external_prerequisites_pass": False,
        "phase_package": "DAY15_INTERRUPTED_SESSION_RECOVERY_AND_COMPLETION",
        "ready_for_deployment": False,
        "schema_version": 2,
        "status": "BLOCKED",
    }
    for key, expected in expected_scalars.items():
        _require_exact(report.get(key), expected, "BLOCKER_REPORT_DECISION_INVALID")

    _validate_lineage(report.get("source_commits"))
    _require_exact(report.get("candidate"), EXPECTED_CANDIDATE, "BLOCKER_CANDIDATE_INVALID")
    _require_exact(
        report.get("aws_activity"), EXPECTED_AWS_ACTIVITY, "BLOCKER_AWS_ACTIVITY_INVALID"
    )
    _require_exact(
        report.get("deployed_by_this_recovery"),
        EXPECTED_DEPLOYED_BY_RECOVERY,
        "BLOCKER_DEPLOYMENT_OUTCOME_INVALID",
    )
    _require_exact(
        report.get("external_observations"),
        EXPECTED_OBSERVATIONS,
        "BLOCKER_EXTERNAL_OBSERVATIONS_INVALID",
    )
    _validate_external_blockers(report.get("missing_or_unproven_external_prerequisites"))
    _validate_no_sensitive_identifiers(report)

    local_gate, local_gate_raw = _canonical_object(local_gate_path, "BLOCKER_LOCAL_GATE_INVALID")
    _validate_local_gate(local_gate, local_gate_raw)
    expected_local_gate = {
        "blocked": 1,
        "canonical_output_sha256": EXPECTED_LOCAL_GATE_SHA256,
        "evidence_path": "docs/evidence/deployment/day15-local-gate-m2.json",
        "fail": 0,
        "g10_reasons": EXPECTED_G10_REASONS,
        "pass": 9,
        "ready_for_deployment": False,
        "status": "BLOCKED",
    }
    _require_exact(report.get("local_gate"), expected_local_gate, "BLOCKER_LOCAL_GATE_INVALID")

    candidate_paths = (
        (artifact_path, DEFAULT_ARTIFACT),
        (manifest_path, DEFAULT_MANIFEST),
        (scan_path, DEFAULT_SCAN),
        (rendered_template_path, DEFAULT_RENDERED_TEMPLATE),
        (render_provenance_path, DEFAULT_RENDER_PROVENANCE),
        (deployment_contract_path, DEFAULT_DEPLOYMENT_CONTRACT),
        (source_template_path, DEFAULT_SOURCE_TEMPLATE),
    )
    should_validate_candidate = (
        any(actual != default for actual, default in candidate_paths)
        if validate_candidate_files is None
        else validate_candidate_files
    )
    if should_validate_candidate:
        _validate_candidate_files(
            artifact_path=artifact_path,
            manifest_path=manifest_path,
            scan_path=scan_path,
            rendered_template_path=rendered_template_path,
            render_provenance_path=render_provenance_path,
            deployment_contract_path=deployment_contract_path,
            source_template_path=source_template_path,
        )
    return {
        "aws_state_changed": False,
        "local_gate": "9_PASS_1_BLOCKED",
        "m2_commit": FINAL_M2,
        "ready_for_deployment": False,
        "report_sha256": _sha256(report_raw),
        "report_status": "BLOCKED",
        "schema_version": 1,
        "status": "PASS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--local-gate", type=Path, default=DEFAULT_LOCAL_GATE)
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--scan", type=Path, default=DEFAULT_SCAN)
    parser.add_argument("--rendered-template", type=Path, default=DEFAULT_RENDERED_TEMPLATE)
    parser.add_argument("--render-provenance", type=Path, default=DEFAULT_RENDER_PROVENANCE)
    parser.add_argument("--deployment-contract", type=Path, default=DEFAULT_DEPLOYMENT_CONTRACT)
    parser.add_argument("--source-template", type=Path, default=DEFAULT_SOURCE_TEMPLATE)
    parser.add_argument("--validate-current-candidate", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_blocker_report(
            report_path=args.report,
            local_gate_path=args.local_gate,
            artifact_path=args.artifact,
            manifest_path=args.manifest,
            scan_path=args.scan,
            rendered_template_path=args.rendered_template,
            render_provenance_path=args.render_provenance,
            deployment_contract_path=args.deployment_contract,
            source_template_path=args.source_template,
            validate_candidate_files=args.validate_current_candidate or None,
        )
    except BlockerReportFailure as error:
        result = {"reason": error.reason, "schema_version": 1, "status": "FAIL"}
        print(canonical_json(result) if args.json else f"FAIL: {error.reason}")
        return 1
    print(canonical_json(result) if args.json else "PASS: Day 15 blocker report authenticated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
