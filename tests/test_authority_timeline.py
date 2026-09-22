"""Read-only authority timeline contract tests."""

import unittest
from pathlib import Path

from authority_timeline import build_authority_timeline


class _Provider:
    def describe(self):
        return "nvidia/nemotron-3.5-lightning-30b-a3b"


class _Critical:
    def status(self):
        return {"mode": "TEST"}


class _Runtime:
    provider_manager = _Provider()
    critical_loop = _Critical()

    def lite_status(self):
        return {"state": "IDLE", "guarded_effect_domain": True,
                "service_guard": {"status": "VERIFIED"}}

    def lite_memory_status(self):
        return {"readiness": "READY"}

    def lite_cpl_status(self):
        return {"mode": "ACTIVE"}

    def lite_dynamics_status(self):
        return {"mode": "SHADOW"}

    def nonzero_status(self):
        return {"status": "READY"}


class AuthorityTimelineTests(unittest.TestCase):
    def test_projection_exposes_authority_without_creating_it(self):
        value = build_authority_timeline(_Runtime())
        self.assertEqual("aioa.authority-timeline.v1", value["schema"])
        self.assertEqual("CORE_HUMAN_GATED_ONLY", value["effect_authority"])
        self.assertIs(value["provider_output_authority"], False)
        self.assertIs(value["timeline_is_read_only_projection"], True)
        events = {item["stage"]: item for item in value["events"]}
        self.assertEqual("ADVISORY_ONLY", events["provider_proposal"]["authority"])
        self.assertEqual("ADVISORY_ONLY", events["critical_prompt_loop"]["authority"])
        self.assertEqual("ADVISORY_ONLY", events["verified_memory"]["authority"])
        self.assertEqual("SHADOW_OR_ADVISORY", events["memory_dynamics"]["authority"])
        self.assertEqual("COORDINATION_ONLY", events["scheduler"]["authority"])
        self.assertEqual("CORE_GATE", events["service_guard"]["authority"])
        self.assertEqual("HUMAN_BOUND_CORE", events["nonzero_effect"]["authority"])
        self.assertEqual("METADATA_ONLY_NO_AUTHORITY", events["evidence_review"]["authority"])
        self.assertEqual("VERIFIED", events["service_guard"]["status"])

    def test_dependency_failure_is_redacted_to_unavailable(self):
        class Broken(_Runtime):
            def nonzero_status(self):
                raise RuntimeError("secret must never cross projection")

        value = build_authority_timeline(Broken())
        events = {item["stage"]: item for item in value["events"]}
        self.assertEqual("UNAVAILABLE", events["nonzero_effect"]["status"])
        self.assertNotIn("secret", str(value).lower())

    def test_web_ui_renders_token_protected_projection(self):
        repo = Path(__file__).resolve().parents[1]
        html = (repo / "web/index.html").read_text(encoding="utf-8")
        script = (repo / "web/app.js").read_text(encoding="utf-8")
        self.assertIn('id="authority-timeline"', html)
        self.assertIn('id="authority-effect-badge"', html)
        self.assertIn('jsonFetch("/api/authority-timeline")', script)
        self.assertIn("renderAuthorityTimeline", script)
        self.assertNotIn('fetch("/api/authority-timeline", {method: "POST"', script)


if __name__ == "__main__":
    unittest.main()
