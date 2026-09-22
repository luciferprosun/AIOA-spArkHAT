"""Competition evidence projection tests."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from competition_view import ENV_PATH, load_competition_demo


COMPETITION_EVENTS = [
    {"stage": "observe", "status": "OBSERVED", "authority": "DATA_ONLY"},
    {"stage": "evidence_hat", "status": "READY", "authority": "ADVISORY_ONLY"},
    {"stage": "nemotron_proposal", "status": "TEST_FIXTURE", "authority": "ADVISORY_ONLY"},
    {"stage": "cpl_review", "status": "VERIFIED", "authority": "ADVISORY_ONLY"},
    {"stage": "verified_delta_reuse", "status": "ZERO_WRITE", "authority": "ADVISORY_ONLY"},
    {"stage": "stale_source_revalidation", "status": "REVALIDATION_REQUIRED", "authority": "CORE_POLICY"},
    {"stage": "core_authority_gate", "status": "HUMAN_APPROVAL_REQUIRED", "authority": "CORE_POLICY"},
    {"stage": "scheduler_boundary", "status": "AGENT_RUNTIME_OWNED", "authority": "COORDINATION_ONLY"},
    {"stage": "human_approval", "status": "BOUND", "authority": "HUMAN"},
    {"stage": "service_guard_effect", "status": "VERIFIED", "authority": "CORE_GATE"},
    {"stage": "durable_receipt", "status": "COMMITTED_BY_TARGET_RECEIPT", "authority": "EVIDENCE_ONLY"},
    {"stage": "independent_verification", "status": "MAINTENANCE", "authority": "MEASUREMENT"},
    {"stage": "durable_memory_audit", "status": "PERSISTED", "authority": "EVIDENCE_ONLY"},
    {"stage": "restart_replay", "status": "REPLAY", "authority": "CORE_REPLAY_BARRIER"},
]


def evidence(*, mode="TEST_FIXTURE", live=False):
    return {
        "schema": "aioa.nvidia-competition-demo.v1",
        "execution_mode": mode,
        "live_provider_claimed": live,
        "provider_status": "EXTERNAL_UNAVAILABLE_OR_NOT_USED",
        "task_success_rate": 1.0,
        "scenario_count": len(COMPETITION_EVENTS),
        "events": [dict(event) for event in COMPETITION_EVENTS],
        "mission": {
            "snapshot_state": "COMPLETE",
            "heartbeat_state": "COMPLETED_EVIDENCE_SNAPSHOT",
            "last_stage": "restart_replay",
            "restart_recovery": "VERIFIED_REPLAY",
            "runtime_factory": "AgentRuntime",
        },
        "memory": {
            "backend_id": "repository-durable-test",
            "backend_mode": "TEST_FIXTURE",
            "schema_profile": "test-fixture",
            "first_write": 1,
            "reuse_zero_write": True,
            "stale_revalidation": "REVALIDATION_REQUIRED",
            "dvm_pheromone_mode": "SHADOW",
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
        self.assertEqual("repository-durable-test", value["memory"]["backend_id"])
        self.assertEqual("TEST_FIXTURE", value["memory"]["backend_mode"])
        self.assertEqual("SHADOW", value["memory"]["dvm_pheromone_mode"])
        self.assertNotIn("approval_bound", value["effect"])

    def test_non_shadow_dvm_evidence_is_rejected(self):
        broken = evidence()
        broken["memory"]["dvm_pheromone_mode"] = "ACTIVE"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])
        self.assertIs(value["evidence_available"], False)

    def test_boolean_count_type_confusion_is_rejected(self):
        broken = evidence()
        broken["effect"]["receipt_effect_count"] = True
        broken["effect"]["independent_measurement_effect_count"] = True
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])
        self.assertIs(value["evidence_available"], False)

    def test_boolean_duplicate_effects_type_confusion_is_rejected(self):
        broken = evidence()
        broken["safety"]["duplicate_effects"] = False
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])

    def test_non_hex_effect_digest_is_rejected(self):
        broken = evidence()
        broken["effect"]["receipt_digest"] = "z" * 64
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "demo.json"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with patch.dict(os.environ, {ENV_PATH: str(path)}):
                value = load_competition_demo()
        self.assertEqual("INVALID_EVIDENCE", value["status"])

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
