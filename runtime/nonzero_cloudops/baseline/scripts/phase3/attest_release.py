"""Generate or verify a private exact-commit Phase 3 local RC attestation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from aioa_cloudops_agent.release.attestation import (
    AttestationError,
    attest_release_candidate,
    load_local_gate_evidence,
    validate_release_attestation_document,
    validate_release_candidate,
)
from aioa_cloudops_agent.release.deployment_contract import load_deployment_contract

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_GATE_EVIDENCE = ROOT / ".local" / "phase3" / "local-gate-evidence.json"
DEFAULT_ATTESTATION = ROOT / ".local" / "phase3" / "rc-attestation.json"


def _safe_git_environment() -> dict[str, str]:
    blocked = {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_PROFILE",
        "AWS_DEFAULT_PROFILE",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
    }
    environment = {name: value for name, value in os.environ.items() if name not in blocked}
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _run_git(command: object, cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    if not isinstance(command, tuple | list):
        return subprocess.CompletedProcess((), 126, "", "")
    try:
        return subprocess.run(
            tuple(str(value) for value in command),
            cwd=cwd,
            env=_safe_git_environment(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(tuple(command), 126, "", "")


def _write_private(path: Path, content: str) -> None:
    if path.is_symlink():
        raise AttestationError("RC_OUTPUT_SYMLINK_FORBIDDEN")
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--gate-evidence", type=Path, default=DEFAULT_GATE_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_ATTESTATION)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    try:
        if args.verify:
            raw = args.output.read_text(encoding="utf-8")
            attestation = validate_release_attestation_document(raw)
            validate_release_candidate(
                attestation,
                root=ROOT,
                expected_head=args.expected_head,
                runner=_run_git,
            )
        else:
            attestation = attest_release_candidate(
                root=ROOT,
                contract=load_deployment_contract(args.contract),
                gate_evidence=load_local_gate_evidence(args.gate_evidence),
                expected_head=args.expected_head,
                runner=_run_git,
                clock=lambda: datetime.now(UTC),
            )
            _write_private(
                args.output,
                json.dumps(
                    attestation.model_dump(mode="json"),
                    allow_nan=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
        payload = {
            "attestation_sha256": attestation.attestation_sha256,
            "aws_mutations": 0,
            "git_sha": attestation.repository_git_sha,
            "live_receipts": 0,
            "network_connections": 0,
            "status": attestation.status,
        }
        code = 0
    except (AttestationError, OSError, UnicodeDecodeError) as error:
        reason = error.reason if isinstance(error, AttestationError) else "RC_ATTESTATION_UNAVAILABLE"
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reason": reason,
            "status": "FAIL",
        }
        code = 1
    print(json.dumps(payload, allow_nan=False, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
