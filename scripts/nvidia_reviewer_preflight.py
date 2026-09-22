#!/usr/bin/env python3
"""One-command deterministic reviewer preflight for the NVIDIA vertical slice.

The preflight executes only the repository-durable TEST_FIXTURE path. It then
feeds the generated artifact through the same read-only projection and
competition evaluation used by the web dashboard. No hosted provider, live
OpenRouter, Cockroach credentials, AWS backend, or second authority path is
required or invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import sys

REPO = Path(__file__).resolve().parents[1]
for value in (REPO, REPO / "runtime", REPO / "tests"):
    if str(value) not in sys.path:
        sys.path.insert(0, str(value))

from competition_evaluation import competition_evaluation  # noqa: E402
from competition_view import ENV_PATH, load_competition_demo  # noqa: E402
from scripts.nvidia_competition_demo import run_demo  # noqa: E402


def _write_artifact(path: Path, value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    # Exclusive creation rejects existing files and symlinks without truncation.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def run_preflight(workspace: Path) -> dict:
    if workspace.is_symlink():
        raise RuntimeError("PREFLIGHT_ROOT_SYMLINK_REJECTED")
    if workspace.exists() and any(workspace.iterdir()):
        raise RuntimeError("PREFLIGHT_ROOT_MUST_BE_FRESH")
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    demo = run_demo(workspace / "demo", memory_backend="fixture")
    artifact = workspace / "AIOA_NVIDIA_COMPETITION_DEMO.json"
    digest = _write_artifact(artifact, demo)

    previous = os.environ.get(ENV_PATH)
    os.environ[ENV_PATH] = str(artifact)
    try:
        view = load_competition_demo()
        evaluation = competition_evaluation()
    finally:
        if previous is None:
            os.environ.pop(ENV_PATH, None)
        else:
            os.environ[ENV_PATH] = previous

    checks = {
        "projection_ready": view.get("status") == "READY",
        "evaluation_pass": evaluation.get("status") == "PASS",
        "provider_fixture_truthful": (
            view.get("provider_mode") == "TEST_FIXTURE"
            and demo.get("live_provider_claimed") is False
        ),
        "memory_fallback_truthful": (
            view.get("memory", {}).get("backend_id") == "repository-durable-test"
            and view.get("memory", {}).get("backend_mode") == "TEST_FIXTURE"
        ),
        "dynamics_shadow_only": view.get("memory", {}).get("dvm_pheromone_mode") == "SHADOW",
        "authority_human_bound": view.get("safety", {}).get("human_bound_effect_authority") is True,
        "provider_has_no_authority": view.get("safety", {}).get("provider_output_authority") is False,
        "single_effect_replay_safe": (
            evaluation.get("tool_usage", {}).get("verified_effects") == 1
            and evaluation.get("tool_usage", {}).get("duplicate_effects") == 0
            and evaluation.get("tool_usage", {}).get("restart_replay_dispatches") == 0
        ),
        "receipt_verified": evaluation.get("reliability", {}).get("durable_receipt_verified") is True,
        "independent_measurement_verified": (
            evaluation.get("reliability", {}).get("independent_effect_verified") is True
        ),
        "stage_order_verified": evaluation.get("trajectory", {}).get("stage_order_verified") is True,
        "service_guard_remains_executor": (
            evaluation.get("nonzero", {}).get("competition_effect_executor") == "ServiceGuard"
            and evaluation.get("nonzero", {}).get("nonzero_executor_invoked") is False
        ),
    }
    return {
        "schema": "aioa.nvidia-reviewer-preflight.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": "DETERMINISTIC_TEST_FIXTURE_ONLY",
        "artifact": str(artifact),
        "artifact_sha256": digest,
        "checks": checks,
        "projection": {
            "provider_mode": view.get("provider_mode"),
            "memory_backend": view.get("memory", {}).get("backend_id"),
            "memory_mode": view.get("memory", {}).get("backend_mode"),
            "dvm_pheromone_mode": view.get("memory", {}).get("dvm_pheromone_mode"),
        },
        "evaluation": {
            "status": evaluation.get("status"),
            "failure_modes": evaluation.get("failure_modes", []),
            "stage_count": evaluation.get("trajectory", {}).get("stage_count"),
            "duplicate_effects": evaluation.get("tool_usage", {}).get("duplicate_effects"),
            "restart_replay_dispatches": evaluation.get("tool_usage", {}).get("restart_replay_dispatches"),
            "nonzero_status": evaluation.get("nonzero", {}).get("status"),
            "effect_executor": evaluation.get("nonzero", {}).get("competition_effect_executor"),
        },
        "claims": {
            "live_provider_validated_by_this_run": False,
            "live_cockroach_validated_by_this_run": False,
            "live_openrouter_validated_by_this_run": False,
            "live_aws_validated_by_this_run": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        help="Fresh output directory. If omitted, a fresh /tmp reviewer directory is created.",
    )
    args = parser.parse_args()
    root = args.root or Path(tempfile.mkdtemp(prefix="aioa-nvidia-review-preflight-"))
    result = run_preflight(root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
