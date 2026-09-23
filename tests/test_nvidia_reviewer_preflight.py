"""Reviewer preflight acceptance tests."""

import tempfile
import unittest
from pathlib import Path

from scripts.nvidia_reviewer_preflight import run_preflight


class NvidiaReviewerPreflightTests(unittest.TestCase):
    def test_preflight_replays_dashboard_contract_without_live_claims(self):
        with tempfile.TemporaryDirectory() as temp:
            result = run_preflight(Path(temp) / "review")

        self.assertEqual("PASS", result["status"])
        self.assertEqual("DETERMINISTIC_TEST_FIXTURE_ONLY", result["scope"])
        self.assertTrue(all(result["checks"].values()))
        self.assertEqual("TEST_FIXTURE", result["projection"]["provider_mode"])
        self.assertEqual("repository-durable-test", result["projection"]["memory_backend"])
        self.assertEqual("SHADOW", result["projection"]["dvm_pheromone_mode"])
        self.assertEqual("PASS", result["evaluation"]["status"])
        self.assertEqual(14, result["evaluation"]["stage_count"])
        self.assertEqual(0, result["evaluation"]["duplicate_effects"])
        self.assertEqual(0, result["evaluation"]["restart_replay_dispatches"])
        self.assertEqual("ServiceGuard", result["evaluation"]["effect_executor"])
        self.assertEqual("ATIF-v1.7", result["trajectory_schema"])
        self.assertEqual(64, len(result["trajectory_artifact_sha256"]))
        self.assertTrue(result["checks"]["trajectory_export_ready"])
        self.assertFalse(any(result["claims"].values()))

    def test_preflight_requires_fresh_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "review"
            root.mkdir()
            (root / "existing.txt").write_text("occupied", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "PREFLIGHT_ROOT_MUST_BE_FRESH"):
                run_preflight(root)


if __name__ == "__main__":
    unittest.main()
