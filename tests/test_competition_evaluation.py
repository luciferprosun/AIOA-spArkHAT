"""Competition trajectory metric tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from competition_evaluation import competition_evaluation
from competition_view import ENV_PATH
from nonzero_cloudops import module_descriptor
from test_competition_view import evidence


class CompetitionEvaluationTests(unittest.TestCase):
    def test_ready_fixture_reports_explicit_outcome_metrics(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(evidence()), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("PASS", value["status"])
        self.assertEqual("DEMO_TRAJECTORY_ONLY", value["scope"])
        self.assertEqual("TEST_FIXTURE", value["provider_mode"])
        self.assertEqual(1.0, value["task_success_rate"])
        self.assertEqual("repository-durable-test", value["memory"]["backend_id"])
        self.assertEqual("TEST_FIXTURE", value["memory"]["backend_mode"])
        descriptor = module_descriptor()
        self.assertEqual("READY" if descriptor["available"] else "UNAVAILABLE", value["nonzero"]["status"])
        self.assertEqual(descriptor["availability_code"], value["nonzero"]["availability_code"])
        self.assertEqual("CORE_NATIVE", value["nonzero"]["implementation"])
        self.assertEqual("portable", value["nonzero"]["mode"])
        self.assertEqual("mock", value["nonzero"]["provider"])
        self.assertEqual("CORE_HUMAN_GATE_VERIFIED", value["nonzero"]["approval_status"])
        self.assertEqual("SERVICE_GUARD_RECEIPT_VERIFIED", value["nonzero"]["receipt_status"])
        self.assertEqual("ServiceGuard", value["nonzero"]["competition_effect_executor"])
        self.assertIs(value["nonzero"]["nonzero_executor_invoked"], False)
        self.assertIs(value["nonzero"]["read_only"], True)
        self.assertEqual(14, value["trajectory"]["stage_count"])
        self.assertIs(value["trajectory"]["scenario_count_matches"], True)
        self.assertIs(value["trajectory"]["stage_order_verified"], True)
        self.assertEqual(value["trajectory"]["required_stage_order"], value["trajectory"]["visible_stage_ids"])
        self.assertIs(value["trajectory"]["hidden_reasoning_logged"], False)
        self.assertEqual(1.0, value["trajectory_efficiency"]["effect_attempts_per_verified_effect"])
        self.assertEqual(0, value["trajectory_efficiency"]["restart_replay_dispatches"])
        self.assertEqual(0, value["trajectory_efficiency"]["duplicate_effects"])
        self.assertEqual(1, value["tool_usage"]["effect_dispatch_attempts"])
        self.assertEqual(1, value["tool_usage"]["verified_effects"])
        self.assertEqual(0, value["tool_usage"]["restart_replay_dispatches"])
        self.assertEqual(0, value["tool_usage"]["duplicate_effects"])
        self.assertEqual(1.0, value["tool_usage"]["effect_tool_success_rate"])
        self.assertEqual("COMPLETED_EVIDENCE_SNAPSHOT", value["reliability"]["mission_heartbeat_state"])
        self.assertEqual("VERIFIED_REPLAY", value["reliability"]["restart_recovery_state"])
        self.assertIs(value["reliability"]["durable_receipt_verified"], True)
        self.assertEqual("COMMITTED_BY_TARGET_RECEIPT", value["reliability"]["receipt_state"])
        self.assertIs(value["reliability"]["independent_effect_verified"], True)
        self.assertEqual("MAINTENANCE", value["reliability"]["independent_measurement_state"])
        self.assertEqual([], value["failure_modes"])



    def test_reordered_vertical_slice_fails_closed(self):
        broken = evidence()
        broken["events"][0], broken["events"][1] = broken["events"][1], broken["events"][0]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("FAIL", value["status"])
        self.assertIn("VERTICAL_SLICE_STAGE_ORDER_MISMATCH", value["failure_modes"])
        self.assertIs(value["trajectory"]["stage_order_verified"], False)

    def test_missing_receipt_or_recovery_evidence_fails_closed(self):
        broken = evidence()
        broken["effect"]["receipt_reconciliation_state"] = "UNKNOWN"
        broken["mission"]["restart_recovery"] = "UNKNOWN"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("FAIL", value["status"])
        self.assertIn("DURABLE_RECEIPT_EVIDENCE_MISSING", value["failure_modes"])
        self.assertIn("RESTART_RECOVERY_EVIDENCE_MISSING", value["failure_modes"])

    def test_missing_evidence_does_not_invent_success(self):
        with patch.dict(os.environ, {}, clear=True):
            value = competition_evaluation()
        self.assertEqual("UNAVAILABLE", value["status"])
        self.assertEqual("UNKNOWN", value["provider_mode"])
        self.assertIs(value["hidden_reasoning_logged"], False)

    def test_boolean_receipt_counts_cannot_produce_false_pass(self):
        broken = evidence()
        broken["effect"]["receipt_effect_count"] = True
        broken["effect"]["independent_measurement_effect_count"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("UNAVAILABLE", value["status"])
        self.assertIs(value["hidden_reasoning_logged"], False)

    def test_invalid_effect_metrics_fail_closed(self):
        broken = evidence()
        broken["effect"]["effect_count"] = "one"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("FAIL", value["status"])
        self.assertEqual(["INVALID_EFFECT_METRICS"], value["failure_modes"])
        self.assertIs(value["hidden_reasoning_logged"], False)

    def test_inconsistent_trajectory_metrics_fail_closed(self):
        broken = evidence()
        broken["scenario_count"] = 99
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("FAIL", value["status"])
        self.assertEqual(["INVALID_TRAJECTORY_METRICS"], value["failure_modes"])

    def test_inconsistent_effect_metrics_fail_closed(self):
        broken = evidence()
        broken["safety"]["duplicate_effects"] = 1
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = competition_evaluation()
        self.assertEqual("FAIL", value["status"])
        self.assertEqual(["INCONSISTENT_EFFECT_METRICS"], value["failure_modes"])


    def test_web_ui_renders_read_only_evaluation_summary(self):
        repo = Path(__file__).resolve().parents[1]
        html = (repo / "web/index.html").read_text(encoding="utf-8")
        script = (repo / "web/app.js").read_text(encoding="utf-8")
        self.assertIn('id="competition-evaluation-panel"', html)
        self.assertIn('id="competition-provider-mode"', html)
        self.assertIn('id="competition-duplicate-effects"', html)
        self.assertIn('id="competition-memory-backend"', html)
        self.assertIn('id="competition-mission-heartbeat"', html)
        self.assertIn('id="competition-receipt-state"', html)
        self.assertIn('id="competition-measurement-state"', html)
        self.assertIn('id="competition-restart-recovery"', html)
        self.assertIn('id="competition-nonzero-readiness"', html)
        self.assertIn('id="competition-nonzero-approval"', html)
        self.assertIn('id="competition-nonzero-receipt"', html)
        self.assertIn('id="competition-effect-executor"', html)
        self.assertIn('id="competition-nonzero-boundary"', html)
        self.assertIn("Non-Zero executor was not invoked", script)
        self.assertIn('jsonFetch("/api/competition-evaluation")', script)
        self.assertIn("renderCompetitionEvaluation", script)
        self.assertNotIn('fetch("/api/competition-evaluation", {method: "POST"', script)


if __name__ == "__main__":
    unittest.main()
