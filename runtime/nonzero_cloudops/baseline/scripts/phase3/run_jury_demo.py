"""Run the complete sub-five-minute jury proof in explicit MOCK/OFFLINE mode."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from aioa_cloudops_agent.release.deployment_contract import load_deployment_contract
from aioa_cloudops_agent.release.post_deploy_verifier import (
    PostDeployVerifierError,
    VerifierMode,
    load_verifier_fixture,
    run_post_deploy_verifier,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "requirements" / "phase3-deployment-contract.json"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "post-deploy-verifier-pass.json"
TARGET_SECONDS = 300.0


def _write_private(path: Path, content: str) -> None:
    if path.is_symlink():
        raise PostDeployVerifierError("JURY_DEMO_OUTPUT_SYMLINK_FORBIDDEN")
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


def run_jury_demo(workspace: Path) -> dict[str, object]:
    started = time.monotonic()
    receipt = run_post_deploy_verifier(
        mode=VerifierMode.OFFLINE_LOCAL_FIXTURE,
        fixture=load_verifier_fixture(DEFAULT_FIXTURE),
        deployment_contract=load_deployment_contract(DEFAULT_CONTRACT),
        workspace=workspace,
    )
    duration = time.monotonic() - started
    within_target = duration < TARGET_SECONDS
    return {
        "approved": {
            "final_state": receipt.approved_path.final_state,
            "independent_verification_sha256": (
                receipt.approved_path.independent_verification_sha256
            ),
            "mock_mutations": receipt.approved_path.mock_mutation_count,
            "operation": receipt.approved_path.operation,
        },
        "aws_mutations": 0,
        "demo_type": "AIOA_PHASE3_FIVE_MINUTE_JURY_PROOF",
        "denied": {
            "final_state": receipt.deny_path.final_state,
            "mock_mutations": receipt.deny_path.mock_mutation_count,
            "operation": receipt.deny_path.operation,
            "receipt_absent": receipt.deny_path.execution_receipt_absent,
        },
        "duration_seconds": round(duration, 3),
        "external_network_connections": 0,
        "fail_closed_probes": [probe.probe_id.value for probe in receipt.failure_probes],
        "live_receipts": 0,
        "mode": "MOCK_OFFLINE_NEVER_LIVE",
        "pending_approval_recovered_after_restart": (
            receipt.approved_path.pending_approval_recovered_after_restart
        ),
        "provider_network_calls": 0,
        "recovery": {
            "mock_mutations_after_restart": receipt.approved_path.recovery_mock_mutation_count,
            "reconciled": receipt.approved_path.recovery_reconciled,
        },
        "replay": {
            "mutation_delta": receipt.approved_path.replay_mutation_delta,
            "reason": receipt.approved_path.replay_reason,
            "rejected": receipt.approved_path.replay_rejected,
        },
        "schema_version": 1,
        "status": "PASS" if within_target else "FAIL",
        "target_seconds": TARGET_SECONDS,
        "verifier_receipt_sha256": receipt.receipt_sha256,
        "within_target": within_target,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.workspace is None:
            with tempfile.TemporaryDirectory(prefix="phase3-jury-demo-") as temporary:
                payload = run_jury_demo(Path(temporary))
        else:
            payload = run_jury_demo(args.workspace)
        code = 0 if payload["status"] == "PASS" else 1
    except PostDeployVerifierError as error:
        payload = {
            "aws_mutations": 0,
            "external_network_connections": 0,
            "live_receipts": 0,
            "mode": "MOCK_OFFLINE_NEVER_LIVE",
            "reason": error.reason,
            "status": "FAIL",
        }
        code = 1
    rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        _write_private(args.output, rendered)
    print(rendered, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
