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
        "effect": {
            "status": "VERIFIED", "verified_effect": True,
            "dispatch_attempted": True, "effect_count": 1,
            "replay_status": "REPLAY", "replay_dispatch_attempted": False,
            "effect_count_after_replay": 1,
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
        self.assertEqual("EXTERNAL_UNAVAILABLE", value["provider_mode"])
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


if __name__ == "__main__":
    unittest.main()
