"""Produce a plan-only Phase 3 cleanup receipt from synthetic/local observations."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from aioa_cloudops_agent.release.cleanup import (
    CleanupError,
    CleanupPlanStatus,
    DeploymentPartialState,
    load_cleanup_contract,
    load_cleanup_observations,
    plan_cleanup,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CLEANUP_CONTRACT = ROOT / "requirements" / "phase3-cleanup-contract.json"
DEFAULT_FIXTURE = ROOT / "tests" / "fixtures" / "phase3" / "cleanup-owned-partial.json"


def _write_private(path: Path, content: str) -> None:
    if path.is_symlink():
        raise CleanupError("CLEANUP_OUTPUT_SYMLINK_FORBIDDEN")
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
    parser.add_argument("--contract", type=Path, default=DEFAULT_CLEANUP_CONTRACT)
    parser.add_argument("--observations", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument(
        "--state",
        choices=tuple(state.value for state in DeploymentPartialState),
        default=DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED.value,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        contract = load_cleanup_contract(args.contract)
        observations = load_cleanup_observations(args.observations)
        plan = plan_cleanup(
            contract,
            observations,
            deployment_state=DeploymentPartialState(args.state),
        )
        payload: dict[str, object] = plan.model_dump(mode="json")
        code = 3 if plan.status is CleanupPlanStatus.BLOCKED_OWNERSHIP else 0
    except CleanupError as error:
        payload = {
            "aws_mutations": 0,
            "cloud_commands_emitted": 0,
            "live_receipts": 0,
            "network_connections": 0,
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
