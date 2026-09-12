"""Execute the complete Phase 3 local gate and write private hashed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aioa_cloudops_agent.release.attestation import (
    QUALITY_CHECK_NAMES,
    AttestationError,
    PriorityGateEvidence,
    TestSuiteEvidence,
    create_local_gate_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / ".local" / "phase3" / "local-gate-evidence.json"
DEFAULT_SUMMARY = ROOT / ".local" / "phase3" / "local-gate-run.json"
DEFAULT_LOGS = ROOT / ".local" / "phase3" / "gate-logs"

_BLOCKED_ENVIRONMENT = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }
)


class LocalGateError(RuntimeError):
    """Fixed-reason local gate failure safe for terminal output."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class ExecutedCommand:
    command_id: str
    argv: tuple[str, ...]
    returncode: int
    duration_seconds: float
    output_sha256: str
    log_path: str
    stdout: str


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def _private_write(path: Path, content: str) -> None:
    if path.is_symlink():
        raise LocalGateError("LOCAL_GATE_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _safe_environment() -> dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if name not in _BLOCKED_ENVIRONMENT
    }
    environment.update(
        {
            "AIOA_LOCAL_MODE": "mock",
            "AWS_EC2_METADATA_DISABLED": "true",
            "GIT_TERMINAL_PROMPT": "0",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_INDEX": "1",
        }
    )
    return environment


def _run(
    command_id: str,
    argv: tuple[str, ...],
    *,
    logs_dir: Path,
    timeout_seconds: int,
) -> ExecutedCommand:
    started = time.monotonic()
    try:
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env=_safe_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LocalGateError(f"LOCAL_GATE_COMMAND_UNAVAILABLE:{command_id}") from error
    duration = time.monotonic() - started
    combined = result.stdout + result.stderr
    log_path = logs_dir / f"{command_id.casefold().replace('_', '-')}.log"
    _private_write(log_path, combined)
    executed = ExecutedCommand(
        command_id=command_id,
        argv=argv,
        returncode=result.returncode,
        duration_seconds=round(duration, 3),
        output_sha256=hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        log_path=log_path.relative_to(ROOT).as_posix(),
        stdout=result.stdout,
    )
    if result.returncode != 0:
        raise LocalGateError(f"LOCAL_GATE_COMMAND_FAILED:{command_id}")
    return executed


def _json_stdout(command: ExecutedCommand, *, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(command.stdout)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise LocalGateError(reason) from error
    if not isinstance(value, dict):
        raise LocalGateError(reason)
    return value


def _pytest_totals(path: Path) -> dict[str, float | int]:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as error:
        raise LocalGateError("LOCAL_GATE_JUNIT_INVALID") from error
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise LocalGateError("LOCAL_GATE_JUNIT_INVALID")
    totals: dict[str, float | int] = {
        "tests": sum(int(suite.attrib.get("tests", "0")) for suite in suites),
        "failures": sum(int(suite.attrib.get("failures", "0")) for suite in suites),
        "errors": sum(int(suite.attrib.get("errors", "0")) for suite in suites),
        "skipped": sum(int(suite.attrib.get("skipped", "0")) for suite in suites),
        "time": sum(float(suite.attrib.get("time", "0")) for suite in suites),
    }
    if totals["tests"] == 0:
        raise LocalGateError("LOCAL_GATE_JUNIT_EMPTY")
    return totals


def _priority_evidence(command: ExecutedCommand, *, expected: int) -> PriorityGateEvidence:
    value = _json_stdout(command, reason="LOCAL_GATE_PRIORITY_OUTPUT_INVALID")
    gates = value.get("gates")
    if (
        value.get("status") != "PASS"
        or value.get("gate_count") != expected
        or value.get("gates_pass") != expected
        or value.get("gates_fail") != 0
        or value.get("gates_skipped") != 0
        or not isinstance(gates, list)
    ):
        raise LocalGateError("LOCAL_GATE_PRIORITY_RESULT_INVALID")
    proof_tests = sum(
        item.get("proof_tests", 0) for item in gates if isinstance(item, dict)
    )
    if not isinstance(proof_tests, int) or proof_tests < 1:
        raise LocalGateError("LOCAL_GATE_PRIORITY_RESULT_INVALID")
    return PriorityGateEvidence(
        status="PASS",
        passed_gates=expected,
        expected_gates=expected,
        proof_tests=proof_tests,
        skipped=0,
        output_sha256=command.output_sha256,
    )


def _assert_clean_expected_head(expected_head: str) -> None:
    for command, reason, expected in (
        (("git", "rev-parse", "HEAD"), "LOCAL_GATE_HEAD_UNAVAILABLE", expected_head),
        (("git", "branch", "--show-current"), "LOCAL_GATE_BRANCH_MISMATCH", "main"),
        (("git", "status", "--porcelain"), "LOCAL_GATE_WORKTREE_NOT_CLEAN", ""),
    ):
        try:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=_safe_environment(),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LocalGateError(reason) from error
        if result.returncode != 0 or result.stdout.strip() != expected:
            raise LocalGateError(reason)


def _validate_status(value: dict[str, Any], reason: str) -> None:
    if value.get("status") != "PASS":
        raise LocalGateError(reason)


def execute_local_gate(
    *,
    expected_head: str,
    output: Path = DEFAULT_OUTPUT,
    summary_path: Path = DEFAULT_SUMMARY,
    logs_dir: Path = DEFAULT_LOGS,
) -> dict[str, object]:
    """Run every mandatory local proof against one clean commit."""

    _assert_clean_expected_head(expected_head)
    python = sys.executable
    junit = logs_dir / "full-pytest.xml"
    wheel_dir = ROOT / ".local" / "phase3" / "dist"
    commands: list[ExecutedCommand] = []

    full = _run(
        "FULL_TESTS",
        (python, "-m", "pytest", "-q", f"--junitxml={junit}"),
        logs_dir=logs_dir,
        timeout_seconds=7_200,
    )
    commands.append(full)
    totals = _pytest_totals(junit)
    if totals["failures"] or totals["errors"] or totals["skipped"]:
        raise LocalGateError("LOCAL_GATE_FULL_TEST_RESULT_INVALID")
    passed = int(totals["tests"])
    full_evidence = TestSuiteEvidence(
        status="PASS",
        passed=passed,
        skipped=0,
        duration_seconds=max(float(totals["time"]), 0.001),
        output_sha256=full.output_sha256,
    )

    p0_command = _run(
        "P0",
        (python, "scripts/run_p0_gate.py", "--json"),
        logs_dir=logs_dir,
        timeout_seconds=3_600,
    )
    commands.append(p0_command)
    p0 = _priority_evidence(p0_command, expected=15)
    p1_command = _run(
        "P1",
        (python, "scripts/run_p1_gate.py", "--json"),
        logs_dir=logs_dir,
        timeout_seconds=3_600,
    )
    commands.append(p1_command)
    p1 = _priority_evidence(p1_command, expected=6)

    simple_commands = (
        ("RUFF", (python, "-m", "ruff", "check", "."), 600),
        ("PIP_CHECK", (python, "-m", "pip", "check"), 600),
        ("GIT_DIFF_CHECK", ("git", "diff", "--check", "HEAD"), 120),
        ("SECRET_SCAN", (python, "scripts/phase3/scan_secrets.py"), 600),
        (
            "PACKAGE_BUILD",
            (
                python,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                wheel_dir.relative_to(ROOT).as_posix(),
                ".",
            ),
            900,
        ),
        (
            "DEPLOYMENT_CONTRACT",
            (python, "scripts/phase3/build_deployment_contract.py", "--check", "--json"),
            300,
        ),
        ("IAC_DRY_RUN", (python, "scripts/phase3/validate_iac.py", "--check"), 300),
        (
            "OFFLINE_NETWORK_GUARD",
            (
                python,
                "-m",
                "pytest",
                "-q",
                "tests/unit/test_phase3_jury_demo.py::test_jury_demo_opens_no_socket",
                "tests/unit/test_phase3_post_deploy_verifier.py::test_complete_verifier_opens_no_network_socket",
                "tests/unit/test_phase3_preflight.py::test_offline_fixture_path_opens_no_network_socket",
                "tests/unit/test_phase3_iac.py::test_offline_iac_path_opens_no_network_socket",
                "tests/unit/test_phase3_cleanup.py::test_cleanup_planning_and_authorization_open_no_network_socket",
            ),
            600,
        ),
    )
    quality = {name: "PASS" for name in QUALITY_CHECK_NAMES}
    for command_id, argv, timeout_seconds in simple_commands:
        command = _run(
            command_id,
            argv,
            logs_dir=logs_dir,
            timeout_seconds=timeout_seconds,
        )
        commands.append(command)
        if command_id in {"SECRET_SCAN", "DEPLOYMENT_CONTRACT", "IAC_DRY_RUN"}:
            _validate_status(
                _json_stdout(command, reason=f"LOCAL_GATE_{command_id}_OUTPUT_INVALID"),
                f"LOCAL_GATE_{command_id}_RESULT_INVALID",
            )

    generated_commands = (
        (python, "scripts/phase3/build_cleanup_contract.py", "--check"),
        (python, "scripts/phase3/build_verifier_contract.py", "--check"),
        (python, "scripts/phase3/build_attestation_contract.py", "--check"),
        (python, "scripts/phase3/audit_submission_claims.py", "--check"),
        (python, "scripts/build_reviewer_evidence_manifest.py", "--check"),
        (python, "scripts/validate_reviewer_evidence_manifest.py"),
    )
    for index, argv in enumerate(generated_commands, start=1):
        command = _run(
            f"GENERATED_ARTIFACTS_{index}",
            argv,
            logs_dir=logs_dir,
            timeout_seconds=600,
        )
        commands.append(command)

    verifier = _run(
        "VERIFIER_LOCAL_CHAIN",
        (python, "scripts/phase3/run_post_deploy_verifier.py", "--check"),
        logs_dir=logs_dir,
        timeout_seconds=600,
    )
    commands.append(verifier)
    verifier_value = _json_stdout(verifier, reason="LOCAL_GATE_VERIFIER_OUTPUT_INVALID")
    if (
        verifier_value.get("status") != "PASS_OFFLINE"
        or verifier_value.get("external_network_connections") != 0
        or verifier_value.get("provider_network_calls") != 0
        or verifier_value.get("aws_mutations") != 0
        or verifier_value.get("live_receipts") != 0
    ):
        raise LocalGateError("LOCAL_GATE_VERIFIER_RESULT_INVALID")

    demo = _run(
        "JURY_DEMO",
        (python, "scripts/phase3/run_jury_demo.py"),
        logs_dir=logs_dir,
        timeout_seconds=600,
    )
    commands.append(demo)
    demo_value = _json_stdout(demo, reason="LOCAL_GATE_DEMO_OUTPUT_INVALID")
    approved = demo_value.get("approved")
    denied = demo_value.get("denied")
    replay = demo_value.get("replay")
    recovery = demo_value.get("recovery")
    if not (
        demo_value.get("status") == "PASS"
        and demo_value.get("mode") == "MOCK_OFFLINE_NEVER_LIVE"
        and demo_value.get("within_target") is True
        and demo_value.get("external_network_connections") == 0
        and demo_value.get("provider_network_calls") == 0
        and demo_value.get("aws_mutations") == 0
        and demo_value.get("live_receipts") == 0
        and isinstance(approved, dict)
        and approved.get("final_state") == "SUCCESS_WITH_EVIDENCE"
        and approved.get("mock_mutations") == 1
        and isinstance(denied, dict)
        and denied.get("final_state") == "DENIED_BY_HUMAN"
        and denied.get("mock_mutations") == 0
        and denied.get("receipt_absent") is True
        and isinstance(replay, dict)
        and replay.get("rejected") is True
        and replay.get("mutation_delta") == 0
        and isinstance(recovery, dict)
        and recovery.get("reconciled") is True
        and recovery.get("mock_mutations_after_restart") == 0
        and demo_value.get("pending_approval_recovered_after_restart") is True
    ):
        raise LocalGateError("LOCAL_GATE_DEMO_RESULT_INVALID")

    evidence = create_local_gate_evidence(
        tested_git_sha=expected_head,
        generated_at=datetime.now(UTC),
        full_tests=full_evidence,
        p0=p0,
        p1=p1,
        quality_checks=quality,  # type: ignore[arg-type]
    )
    _private_write(
        output,
        json.dumps(evidence.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
    )
    summary: dict[str, object] = {
        "aws_mutations": 0,
        "commands": [
            {
                "command_id": item.command_id,
                "duration_seconds": item.duration_seconds,
                "log_path": item.log_path,
                "output_sha256": item.output_sha256,
                "returncode": item.returncode,
            }
            for item in commands
        ],
        "demo_duration_seconds": demo_value["duration_seconds"],
        "evidence_path": output.relative_to(ROOT).as_posix(),
        "evidence_sha256": evidence.evidence_sha256,
        "full_tests_passed": full_evidence.passed,
        "full_tests_skipped": 0,
        "live_receipts": 0,
        "network_connections": 0,
        "p0_gates": 15,
        "p0_proof_tests": p0.proof_tests,
        "p1_gates": 6,
        "p1_proof_tests": p1.proof_tests,
        "schema_version": 1,
        "status": "PASS",
        "tested_git_sha": expected_head,
    }
    _private_write(summary_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--logs-dir", type=Path, default=DEFAULT_LOGS)
    args = parser.parse_args()
    try:
        payload = execute_local_gate(
            expected_head=args.expected_head,
            output=args.output,
            summary_path=args.summary,
            logs_dir=args.logs_dir,
        )
        code = 0
    except (AttestationError, LocalGateError) as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": getattr(error, "reason", "LOCAL_GATE_FAILED"),
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
