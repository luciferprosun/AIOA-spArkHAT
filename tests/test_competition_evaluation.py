"""Competition trajectory metric tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from competition_evaluation import competition_evaluation
from competition_view import ENV_PATH
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
        self.assertEqual(2, value["trajectory"]["stage_count"])
        self.assertIs(value["trajectory"]["scenario_count_matches"], True)
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
        self.assertEqual("EXTERNAL_UNAVAILABLE", value["provider_mode"])
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
        self.assertIn('id="competition-mission-heartbeat"', html)
        self.assertIn('id="competition-receipt-state"', html)
        self.assertIn('id="competition-measurement-state"', html)
        self.assertIn('id="competition-restart-recovery"', html)
        self.assertIn('jsonFetch("/api/competition-evaluation")', script)
        self.assertIn("renderCompetitionEvaluation", script)
        self.assertNotIn('fetch("/api/competition-evaluation", {method: "POST"', script)


if __name__ == "__main__":
    unittest.main()
