from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "aioa-nvidia-reviewer"
SCRIPT = SKILL / "scripts" / "review_aioa.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("aioa_nvidia_reviewer_skill", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("skill script import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NvidiaReviewerSkillTest(unittest.TestCase):
    def test_skill_metadata_and_claim_boundaries(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: aioa-nvidia-reviewer", text)
        self.assertIn('version: "0.1.0"', text)
        self.assertIn("license: MIT", text)
        self.assertIn("## Instructions", text)
        self.assertIn("## Available Scripts", text)
        self.assertIn("24H_PASS_CLOSED", text)
        self.assertIn("TEST_FIXTURE", text)
        self.assertIn("ServiceGuard", text)

    def test_wrapper_passes_from_foreign_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as foreign:
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", str(REPO)],
                cwd=foreign,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(payload["stage_count"], 14)
        self.assertEqual(payload["duplicate_effects"], 0)
        self.assertEqual(payload["restart_replay_dispatches"], 0)
        self.assertEqual(payload["effect_executor"], "ServiceGuard")
    def test_sanitized_environment_drops_provider_credentials(self) -> None:
        module = _load_script_module()
        values = {
            "OPENROUTER_API_KEY": "placeholder-openrouter-secret",
            "NVIDIA_API_KEY": "placeholder-nvidia-secret",
            "AWS_SECRET_ACCESS_KEY": "placeholder-aws-secret",
        }
        with mock.patch.dict(os.environ, values, clear=False):
            env = module._sanitized_env()
        for name in values:
            self.assertNotIn(name, env)
        self.assertEqual(env["HTTP_PROXY"], module.FAIL_CLOSED_PROXY)
        self.assertEqual(env["NO_PROXY"], "127.0.0.1,localhost")

    def test_summarize_fails_closed_on_inconsistent_preflight(self) -> None:
        module = _load_script_module()
        required = (
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
        payload = {
            "status": "PASS",
            "scope": "DETERMINISTIC_TEST_FIXTURE_ONLY",
            "checks": {name: True for name in required},
            "projection": {
                "provider_mode": "TEST_FIXTURE",
                "memory_mode": "TEST_FIXTURE",
                "dvm_pheromone_mode": "SHADOW",
            },
            "evaluation": {
                "status": "FAIL",
                "stage_count": 14,
                "duplicate_effects": 0,
                "restart_replay_dispatches": 0,
                "effect_executor": "ServiceGuard",
            },
            "claims": {
                "live_provider_validated_by_this_run": False,
                "live_cockroach_validated_by_this_run": False,
                "live_openrouter_validated_by_this_run": False,
                "live_aws_validated_by_this_run": False,
            },
        }
        self.assertEqual(module._summarize(payload)["status"], "FAIL")
        payload["evaluation"]["status"] = "PASS"
        payload["checks"]["provider_has_no_authority"] = False
        self.assertEqual(module._summarize(payload)["status"], "FAIL")

    def test_eval_dataset_has_positive_and_negative_routes(self) -> None:
        payload = json.loads(
            (SKILL / "evals" / "evals.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["skill_name"], "aioa-nvidia-reviewer")
        evals = payload["evals"]
        self.assertGreaterEqual(len(evals), 6)
        ids = [item["id"] for item in evals]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(any(item.get("expected_skill") is None for item in evals))
        self.assertTrue(
            any(item.get("expected_script") == "scripts/review_aioa.py" for item in evals)
        )


if __name__ == "__main__":
    unittest.main()
