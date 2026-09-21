import unittest
from pathlib import Path

from critical_loop.preset import (
    MODELS,
    OBSERVER_MODELS,
    PRESET_ID,
    PRIMARY_MODEL,
    build_openrouter_cpl_preset,
)
from critical_loop.review import SUPPORTED_ROLES


class _Manager:
    def __init__(self, *, configured):
        self.configured = configured

    def strict_status(self):
        return {
            "provider": "openrouter",
            "enabled": True,
            "configured": self.configured,
            "mode": "LIVE_PENDING_AUTHORIZATION",
            "fallback": False,
            "retry": False,
        }


class _Service:
    def __init__(self, status, *, configured):
        self._status = status
        self.manager = _Manager(configured=configured)

    def status(self):
        return dict(self._status)


class CPLPresetTests(unittest.TestCase):
    def test_exact_competition_binding_is_read_only(self):
        service = _Service(
            {"mode": "TEST", "live_enabled": False, "session_budget_usd": "0"},
            configured=True,
        )
        preset = build_openrouter_cpl_preset(service)
        self.assertEqual(preset["preset_id"], PRESET_ID)
        self.assertEqual(preset["models"], list(MODELS))
        self.assertEqual(preset["primary_model"], PRIMARY_MODEL)
        self.assertEqual(preset["observer_models"], list(OBSERVER_MODELS))
        self.assertEqual(preset["roles"], list(SUPPORTED_ROLES))
        self.assertEqual(preset["expected_generation_requests"], 5)
        self.assertIs(preset["read_only"], True)
        self.assertEqual(preset["authority"], "ADVISORY_ONLY")
        self.assertIs(preset["live_preconditions_ready"], False)
        self.assertIn("NOT_LIVE_RUNTIME", preset["blocking_reasons"])

    def test_live_without_key_and_policy_fails_closed(self):
        service = _Service(
            {"mode": "LIVE", "live_enabled": False, "session_budget_usd": "0"},
            configured=False,
        )
        preset = build_openrouter_cpl_preset(service)
        self.assertIs(preset["live_preconditions_ready"], False)
        self.assertIn("OPENROUTER_KEY_MISSING", preset["blocking_reasons"])
        self.assertIn("LIVE_COST_POLICY_DISABLED", preset["blocking_reasons"])
        self.assertIn("SESSION_BUDGET_NOT_POSITIVE", preset["blocking_reasons"])

    def test_existing_ui_exposes_preset_and_explicit_cpl_bypass(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / 'web' / 'index.html').read_text(encoding='utf-8')
        script = (root / 'web' / 'app.js').read_text(encoding='utf-8')
        self.assertIn('id="assistant-mode"', html)
        self.assertIn('value="cpl"', html)
        self.assertIn('value="plain"', html)
        self.assertIn('id="cpl-load-preset"', html)
        self.assertIn("jsonFetch('/api/cpl/preset')", script)
        self.assertIn("state.cplPreset.models.join('\\n')", script)
        self.assertIn('No provider call occurred', script)

    def test_live_preconditions_can_be_reported_without_starting_a_run(self):
        service = _Service(
            {"mode": "LIVE", "live_enabled": True, "session_budget_usd": "1"},
            configured=True,
        )
        preset = build_openrouter_cpl_preset(service)
        self.assertIs(preset["live_preconditions_ready"], True)
        self.assertEqual(preset["blocking_reasons"], [])


if __name__ == "__main__":
    unittest.main()
