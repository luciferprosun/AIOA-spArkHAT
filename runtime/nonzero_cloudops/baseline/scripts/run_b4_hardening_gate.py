#!/usr/bin/env python3
"""Run the explicit B4 attack/recovery matrix and emit one integrity-bound receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
OUTPUT_ROOT: Final = ROOT / ".local" / "b4"
DEFAULT_OUTPUT: Final = OUTPUT_ROOT / "hardening-gate.json"
NETWORK_GUARD_PLUGIN: Final = "scripts.b4_network_guard"
SCENARIOS: Final[tuple[tuple[str, str], ...]] = (
    (
        "APPROVE_NORMAL",
        "tests/integration/test_local_hitl_execution.py::"
        "test_approved_eip_executes_once_verifies_and_reconciles_after_restart",
    ),
    (
        "DENY_NORMAL",
        "tests/integration/test_local_hitl_execution.py::"
        "test_denial_is_terminal_and_never_calls_executor",
    ),
    (
        "RECOVERY_AFTER_INTERRUPTION",
        "tests/integration/test_local_hitl_execution.py::"
        "test_restart_recovers_after_mutation_before_receipt_checkpoint",
    ),
    (
        "REPLAY_REJECTED",
        "tests/integration/test_local_hitl_execution.py::"
        "test_identical_decision_reconciles_but_conflicting_replay_is_rejected",
    ),
    (
        "APPROVAL_TAMPER_REJECTED",
        "tests/integration/test_local_hitl_execution.py::"
        "test_every_decision_binding_tamper_fails_closed",
    ),
    (
        "EVIDENCE_TAMPER_DETECTED",
        "tests/unit/test_local_file_state_store.py::test_local_snapshot_tampering_is_detected",
    ),
    (
        "PROVIDER_FAILURE_SAFE",
        "tests/integration/test_local_first_phase_one.py::"
        "test_model_failures_are_typed_terminal_and_create_no_proposal",
    ),
    (
        "INVALID_INPUT_REJECTED",
        "tests/unit/test_local_hitl_api.py::"
        "test_routes_reject_queries_bad_ids_methods_and_oversized_bodies",
    ),
    (
        "CORRUPTED_STATE_SAFE_FAILURE",
        "tests/unit/test_local_file_state_store.py::"
        "test_corrupt_or_unknown_local_state_fails_closed",
    ),
    (
        "SECRET_REDACTION_PASS",
        "tests/unit/test_evidence_security.py::"
        "test_redaction_removes_secret_material_without_echo",
    ),
    (
        "NETWORK_EGRESS_ZERO",
        "tests/integration/test_portable_judge_sandbox.py::"
        "test_portable_demo_is_deterministic_and_opens_no_socket",
    ),
)
_PASSED = re.compile(r"(?P<count>[0-9]+) passed")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--list", action="store_true", help="list the frozen scenario mapping")
    return parser.parse_args()


def _environment() -> dict[str, str]:
    blocked = {
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
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in blocked
        and not name.startswith("AWS_ENDPOINT_URL")
        and not name.startswith("BEDROCK_")
    }
    environment.update(
        {
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
        }
    )
    return environment


def _run_scenario(name: str, node: str) -> dict[str, object]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "-p",
                NETWORK_GUARD_PLUGIN,
                node,
            ),
            cwd=ROOT,
            env=_environment(),
            capture_output=True,
            check=False,
            text=True,
            timeout=180,
        )
        rendered = f"{result.stdout}\n{result.stderr}"
        match = _PASSED.search(rendered)
        proof_tests = int(match.group("count")) if match is not None else 0
        outcome = "PASS" if result.returncode == 0 and proof_tests > 0 else "FAIL"
    except subprocess.TimeoutExpired:
        outcome = "FAIL"
        proof_tests = 0
    return {
        "duration_milliseconds": round((time.monotonic() - started) * 1_000),
        "outcome": outcome,
        "proof_node": node,
        "proof_tests": proof_tests,
        "scenario": name,
    }


def _git_head() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _receipt(results: tuple[dict[str, object], ...]) -> dict[str, object]:
    material: dict[str, object] = {
        "aws_calls": 0,
        "aws_mutations": 0,
        "external_deployments": 0,
        "external_network_calls": 0,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "git_head": _git_head(),
        "network_guard": "LOOPBACK_ONLY_FAIL_CLOSED",
        "phase": "PORTABLE_B4_RELIABILITY_SECURITY_EVIDENCE_HARDENING",
        "proof_tests": sum(int(result["proof_tests"]) for result in results),
        "receipt_type": "AIOA_B4_HARDENING_GATE",
        "remote_pushes": 0,
        "results": results,
        "schema_version": 1,
        "status": "PASS" if all(result["outcome"] == "PASS" for result in results) else "FAIL",
    }
    canonical = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return {**material, "receipt_sha256": hashlib.sha256(canonical).hexdigest()}


def _write(path: Path, rendered: str) -> None:
    resolved = path.resolve(strict=False)
    root = OUTPUT_ROOT.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise RuntimeError("B4_OUTPUT_OUTSIDE_PRIVATE_EVIDENCE_ROOT")
    if path.is_symlink() or any(
        parent.is_symlink() for parent in path.parents if parent.exists()
    ):
        raise RuntimeError("B4_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = _arguments()
    if args.list:
        print(json.dumps(dict(SCENARIOS), indent=2, sort_keys=True))
        return 0
    results = tuple(_run_scenario(name, node) for name, node in SCENARIOS)
    receipt = _receipt(results)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        _write(args.output, rendered)
    print(rendered, end="")
    return 0 if receipt["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
