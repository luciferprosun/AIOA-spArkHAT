"""Competition vertical-slice acceptance test."""

import tempfile
import unittest
from pathlib import Path

from scripts.nvidia_competition_demo import run_demo
from competition_evaluation import REQUIRED_STAGE_ORDER


class NvidiaCompetitionDemoTests(unittest.TestCase):
    def test_vertical_slice_is_deterministic_safe_and_replayable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo"
            value = run_demo(root)
        self.assertEqual("aioa.nvidia-competition-demo.v1", value["schema"])
        self.assertEqual("TEST_FIXTURE", value["execution_mode"])
        self.assertIs(value["live_provider_claimed"], False)
        self.assertEqual(1.0, value["task_success_rate"])
        self.assertEqual(list(REQUIRED_STAGE_ORDER), [event["stage"] for event in value["events"]])
        self.assertEqual("TEST_FIXTURE", value["events"][2]["status"])
        self.assertEqual("ADVISORY_ONLY", value["events"][2]["authority"])
        self.assertEqual("repository-durable-test", value["memory"]["backend_id"])
        self.assertEqual("TEST_FIXTURE", value["memory"]["backend_mode"])
        self.assertEqual(1, value["memory"]["first_write"])
        self.assertIs(value["memory"]["reuse_zero_write"], True)
        self.assertEqual("REVALIDATION_REQUIRED", value["memory"]["stale_revalidation"])
        self.assertEqual("VERIFIED", value["effect"]["status"])
        self.assertEqual(1, value["effect"]["effect_count"])
        self.assertEqual("REPLAY", value["effect"]["replay_status"])
        self.assertIs(value["effect"]["replay_dispatch_attempted"], False)
        self.assertEqual(1, value["effect"]["effect_count_after_replay"])
        self.assertEqual("TARGET_DURABLY_APPLIED", value["effect"]["receipt_transport_result"])
        self.assertEqual("COMMITTED_BY_TARGET_RECEIPT", value["effect"]["receipt_reconciliation_state"])
        self.assertEqual("MAINTENANCE", value["effect"]["independent_measurement_mode"])
        self.assertIs(value["effect"]["verified_record_persisted"], True)
        self.assertIs(value["effect"]["replay_verified_record_persisted"], True)
        self.assertEqual("COMPLETED_EVIDENCE_SNAPSHOT", value["mission"]["heartbeat_state"])
        self.assertEqual("VERIFIED_REPLAY", value["mission"]["restart_recovery"])
        self.assertEqual(0, value["safety"]["duplicate_effects"])
        self.assertIs(value["safety"]["provider_output_authority"], False)
        self.assertIs(value["safety"]["human_bound_effect_authority"], True)

    def test_cockroach_backend_requires_explicit_private_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "demo"
            with self.assertRaisesRegex(RuntimeError, "COCKROACH_PRIVATE_DIR_REQUIRED"):
                run_demo(root, memory_backend="cockroach")


if __name__ == "__main__":
    unittest.main()
