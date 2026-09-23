#!/usr/bin/env python3
"""Run deterministic AIOA NVIDIA reviewer checks without provider credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

EXPECTED_SCOPE = "DETERMINISTIC_TEST_FIXTURE_ONLY"
EXPECTED_STAGE_COUNT = int("14")
EXPECTED_EFFECT_EXECUTOR = "ServiceGuard"
DEFAULT_TIMEOUT_S = int("300")
FAIL_CLOSED_PROXY_PORT = int("9")
EXIT_SUCCESS = 0
EXIT_FAILURE = 1
MIN_POSITIVE_INT = 1
FAIL_CLOSED_PROXY = f"http://127.0.0.1:{FAIL_CLOSED_PROXY_PORT}"
LIVE_CLAIM_KEYS = (
    "live_provider_validated_by_this_run",
    "live_cockroach_validated_by_this_run",
    "live_openrouter_validated_by_this_run",
    "live_aws_validated_by_this_run",
)
BASE_ENV_KEYS = ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "TZ")
class ReviewerError(RuntimeError):
    """Expected reviewer-skill failure."""


def _sanitized_env() -> dict[str, str]:
    """Return a minimal environment with hosted-provider access disabled."""
    env = {
        key: value
        for key in BASE_ENV_KEYS
        if (value := os.environ.get(key))
    }
    env.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "HTTP_PROXY": FAIL_CLOSED_PROXY,
            "HTTPS_PROXY": FAIL_CLOSED_PROXY,
            "ALL_PROXY": FAIL_CLOSED_PROXY,
            "NO_PROXY": "127.0.0.1,localhost",
        }
    )
    return env


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < MIN_POSITIVE_INT:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed
def _preflight_path(repo: Path) -> Path:
    resolved = repo.expanduser().resolve()
    preflight = resolved / "scripts" / "nvidia_reviewer_preflight.py"
    if not preflight.is_file():
        raise ReviewerError("TARGET_NOT_AIOA_CHECKOUT")
    return preflight


def _run_preflight(repo: Path, timeout_s: int) -> dict:
    preflight = _preflight_path(repo)
    with tempfile.TemporaryDirectory(prefix="aioa-nvidia-reviewer-skill-") as tmp:
        root = Path(tmp) / "preflight"
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                str(preflight),
                "--root",
                str(root),
            ],
            cwd=str(repo.expanduser().resolve()),
            env=_sanitized_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    if completed.returncode != EXIT_SUCCESS:
        raise ReviewerError("PREFLIGHT_FAILED")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReviewerError("PREFLIGHT_OUTPUT_INVALID") from exc
    if not isinstance(payload, dict):
        raise ReviewerError("PREFLIGHT_OUTPUT_INVALID")
    return payload
def _summarize(payload: dict) -> dict:
    projection = payload.get("projection") or {}
    evaluation = payload.get("evaluation") or {}
    claims = payload.get("claims") or {}
    preflight_checks = payload.get("checks") or {}
    required_preflight_checks = (
        "projection_ready",
        "evaluation_pass",
        "provider_fixture_truthful",
        "memory_fallback_truthful",
        "dynamics_shadow_only",
        "authority_human_bound",
        "provider_has_no_authority",
        "single_effect_replay_safe",
        "receipt_verified",
        "independent_measurement_verified",
        "stage_order_verified",
        "service_guard_remains_executor",
    )
    checks = {
        "preflight_pass": payload.get("status") == "PASS",
        "evaluation_pass": evaluation.get("status") == "PASS",
        "preflight_checks_complete": all(
            preflight_checks.get(name) is True for name in required_preflight_checks
        ),
        "scope_fixture_only": payload.get("scope") == EXPECTED_SCOPE,
        "stage_count_14": evaluation.get("stage_count") == EXPECTED_STAGE_COUNT,
        "duplicate_effects_zero": evaluation.get("duplicate_effects") == 0,
        "restart_redispatch_zero": evaluation.get("restart_replay_dispatches") == 0,
        "service_guard_executor": (
            evaluation.get("effect_executor") == EXPECTED_EFFECT_EXECUTOR
        ),
        "provider_fixture_truthful": projection.get("provider_mode") == "TEST_FIXTURE",
        "memory_fixture_truthful": projection.get("memory_mode") == "TEST_FIXTURE",
        "dynamics_shadow_only": projection.get("dvm_pheromone_mode") == "SHADOW",
        "no_live_claims": all(claims.get(key) is False for key in LIVE_CLAIM_KEYS),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "schema": "aioa.nvidia-reviewer-skill.v1",
        "status": "PASS" if not failures else "FAIL",
        "scope": payload.get("scope"),
        "checks": checks,
        "failure_reasons": failures,
        "stage_count": evaluation.get("stage_count"),
        "duplicate_effects": evaluation.get("duplicate_effects"),
        "restart_replay_dispatches": evaluation.get("restart_replay_dispatches"),
        "effect_executor": evaluation.get("effect_executor"),
        "provider_mode": projection.get("provider_mode"),
        "memory_mode": projection.get("memory_mode"),
        "dvm_pheromone_mode": projection.get("dvm_pheromone_mode"),
        "live_provider_validated_by_this_run": (
            claims.get("live_provider_validated_by_this_run") is True
        ),
        "unproven_claims": [
            "LIVE_NVIDIA_NEMOTRON",
            "LIVE_OPENROUTER",
            "LIVE_COCKROACHDB",
            "LIVE_AWS_NONZERO",
            "24H_PASS_CLOSED",
            "PRODUCTION_DVM_PHEROMONE_AUTHORITY",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="AIOA spArkHAT source checkout to review.",
    )
    parser.add_argument(
        "--timeout-s",
        type=_positive_int,
        default=DEFAULT_TIMEOUT_S,
        help="Maximum deterministic preflight runtime in seconds.",
    )
    args = parser.parse_args()
    try:
        payload = _run_preflight(args.repo, args.timeout_s)
        result = _summarize(payload)
    except (ReviewerError, subprocess.TimeoutExpired) as exc:
        result = {
            "schema": "aioa.nvidia-reviewer-skill.v1",
            "status": "FAIL",
            "reason": (
                "PREFLIGHT_TIMEOUT"
                if isinstance(exc, subprocess.TimeoutExpired)
                else str(exc)
            ),
        }

    print(json.dumps(result, sort_keys=True, indent=2))
    return EXIT_SUCCESS if result.get("status") == "PASS" else EXIT_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
