"""Competition evidence projection tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from competition_view import ENV_PATH, load_competition_demo


def evidence(*, mode="TEST_FIXTURE", live=False):
    return {
        "schema": "aioa.nvidia-competition-demo.v1",
        "execution_mode": mode,
        "live_provider_claimed": live,
        "provider_status": "EXTERNAL_UNAVAILABLE_OR_NOT_USED",
        "task_success_rate": 1.0,
        "scenario_count": 2,
        "events": [
            {"stage": "human_approval", "status": "BOUND", "authority": "HUMAN"},
            {"stage": "service_guard_effect", "status": "VERIFIED", "authority": "CORE_GATE"},
        ],
        "mission": {
            "snapshot_state": "COMPLETE",
            "heartbeat_state": "COMPLETED_EVIDENCE_SNAPSHOT",
            "last_stage": "restart_replay",
            "restart_recovery": "VERIFIED_REPLAY",
            "runtime_factory": "AgentRuntime",
        },
        "effect": {
            "status": "VERIFIED", "verified_effect": True,
            "dispatch_attempted": True, "effect_count": 1,
            "replay_status": "REPLAY", "replay_dispatch_attempted": False,
            "effect_count_after_replay": 1,
            "receipt_transport_result": "TARGET_DURABLY_APPLIED",
            "receipt_reconciliation_state": "COMMITTED_BY_TARGET_RECEIPT",
            "receipt_effect_count": 1,
            "receipt_digest": "a" * 64,
            "independent_measurement_mode": "MAINTENANCE",
            "independent_measurement_effect_count": 1,
            "measurement_digest": "b" * 64,
            "verified_record_persisted": True,
            "replay_verified_record_persisted": True,
        },
        "safety": {
            "provider_output_authority": False, "duplicate_effects": 0,
            "human_bound_effect_authority": True,
            "hidden_chain_of_thought_recorded": False,
        },
    }


class CompetitionViewTests(unittest.TestCase):
    def test_not_configured_is_explicit_and_read_only(self):
        with patch.dict(os.environ, {}, clear=True):
            value = load_competition_demo()
        self.assertEqual("NOT_CONFIGURED", value["status"])
        self.assertEqual("UNKNOWN", value["provider_mode"])
        self.assertIs(value["read_only"], True)

    def test_valid_fixture_is_projected_without_extra_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(evidence()), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("READY", value["status"])
        self.assertEqual("TEST_FIXTURE", value["provider_mode"])
        self.assertEqual(0, value["safety"]["duplicate_effects"])
        self.assertEqual("VERIFIED_REPLAY", value["mission"]["restart_recovery"])
        self.assertEqual("COMMITTED_BY_TARGET_RECEIPT", value["effect"]["receipt_reconciliation_state"])
        self.assertEqual("MAINTENANCE", value["effect"]["independent_measurement_mode"])
        self.assertNotIn("memory", value)
        self.assertNotIn("approval_bound", value["effect"])

    def test_fixture_cannot_claim_live(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(evidence(live=True)), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])
        self.assertIs(value["evidence_available"], False)

    def test_symlink_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "demo.json"
            target.write_text(json.dumps(evidence()), encoding="utf-8")
            link = Path(temp) / "demo-link.json"
            link.symlink_to(target)
            with patch.dict(os.environ, {ENV_PATH: str(link)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])
        self.assertIs(value["evidence_available"], False)


if __name__ == "__main__":
    unittest.main()
