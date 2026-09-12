#!/usr/bin/env python3
"""Run the local Phase 3 preflight without contacting AWS."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from aioa_cloudops_agent.release.preflight import (  # noqa: E402
    PreflightError,
    PreflightMode,
    PreflightStatus,
    run_preflight,
)
from scripts.phase3.build_deployment_contract import DEFAULT_CONTRACT  # noqa: E402


def _run_command(
    command: object,
    cwd: Path,
    environment: object,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    if not isinstance(command, tuple | list) or not isinstance(environment, dict):
        return subprocess.CompletedProcess((), 126, "", "")
    try:
        return subprocess.run(
            tuple(str(value) for value in command),
            cwd=cwd,
            env={str(name): str(value) for name, value in environment.items()},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(tuple(command), 126, "", "")


def _write_private(path: Path, payload: str) -> None:
    if path.is_symlink():
        raise PreflightError("PREFLIGHT_OUTPUT_SYMLINK_FORBIDDEN")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _exit_code(status: PreflightStatus | str) -> int:
    value = status.value if isinstance(status, PreflightStatus) else status
    return {"PASS": 0, "FAIL": 1, "BLOCKED_EXTERNAL": 3}.get(value, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--mode",
        choices=("local", "fixture"),
        default="local",
    )
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    mode = (
        PreflightMode.OFFLINE_AWS_FIXTURE
        if args.mode == "fixture"
        else PreflightMode.LOCAL_ONLY
    )
    try:
        receipt = run_preflight(
            root=ROOT,
            contract_path=args.contract,
            expected_head=args.expected_head,
            mode=mode,
            fixture_path=args.fixture,
            runner=_run_command,
        )
        payload: dict[str, object] = receipt.model_dump(mode="json")
        status = receipt.status
    except PreflightError as error:
        payload = {
            "aws_mutations": 0,
            "live_receipts": 0,
            "network_connections": 0,
            "reasons": [error.reason],
            "schema_version": 1,
            "status": "FAIL",
        }
        status = PreflightStatus.FAIL
    rendered = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ) + "\n"
    if args.output is not None:
        _write_private(args.output, rendered)
    if args.json:
        print(rendered, end="")
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"PHASE3_PREFLIGHT {status.value} reasons={reasons}")
    return _exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
