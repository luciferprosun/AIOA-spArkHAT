from __future__ import annotations

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from test_nebius_personal_ai import NebiusGuardFixture, empty_memory
from test_nebius_routing import catalog_receipt, quote

from runtime.personal_ai_demo import PersonalAIDemoBindings, PersonalAIDemoService
from webapp import (
    PERSONAL_AI_APPROVAL_INTENT,
    PERSONAL_AI_OPERATOR_INTENT,
    PERSONAL_AI_RESUME_INTENT,
    WebRuntimeService,
    make_server,
)


class FakeHostRuntime:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class PersonalAIWebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.guard = NebiusGuardFixture(self.root / "guard")
        self.demo = PersonalAIDemoService(
            self.root / "demo",
            PersonalAIDemoBindings(
                memory_retrieve=empty_memory,
                guard=self.guard.guard,
                scheduler=self.guard.runtime._lite_scheduler,
                execution_mode="FIXTURE",
            ),
        )
        self.host_runtime = FakeHostRuntime()
        self.service = WebRuntimeService(
            runtime=self.host_runtime,
            personal_ai=self.demo,
            personal_ai_catalog=catalog_receipt(),
            personal_ai_cost_quote=quote(),
        )
        self.server = make_server("127.0.0.1", 0, self.service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.token = self.request("GET", "/api/session", token=False)[1]["token"]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.service.close()
        self.guard.close()
        self.temp.cleanup()

    def request(self, method, path, payload=None, *, token=True, intent=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-AIOA-Session-Token"] = self.token
        if intent is not None:
            headers["X-AIOA-Intent"] = intent
        body = json.dumps(payload) if payload is not None else None
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data)

    def prepare_payload(self):
        return {
            "operation_id": self.guard.operation_id,
            "target_id": self.guard.target_id,
            "memory_query": "maintenance approved window",
        }

    def prepare(self):
        status, payload = self.request(
            "POST",
            "/api/personal-ai/prepare",
            self.prepare_payload(),
            intent=PERSONAL_AI_OPERATOR_INTENT,
        )
        self.assertEqual(200, status, payload)
        return payload

    def test_all_personal_ai_routes_require_the_session_token(self):
        cases = (
            ("GET", "/api/personal-ai/status", None, None),
            ("POST", "/api/personal-ai/prepare", self.prepare_payload(), PERSONAL_AI_OPERATOR_INTENT),
            ("POST", "/api/personal-ai/approve", {"proposal_id": "a" * 64}, PERSONAL_AI_APPROVAL_INTENT),
            ("POST", "/api/personal-ai/resume", {"operation_id": self.guard.operation_id}, PERSONAL_AI_RESUME_INTENT),
        )
        for method, path, payload, intent in cases:
            with self.subTest(path=path):
                status, result = self.request(
                    method, path, payload, token=False, intent=intent
                )
                self.assertEqual(403, status)
                self.assertEqual("session_token_required", result["error"])
        self.assertEqual(0, self.guard.store.apply_count)

    def test_prepare_requires_operator_intent_strict_fields_and_stops_for_approval(self):
        status, result = self.request(
            "POST", "/api/personal-ai/prepare", self.prepare_payload()
        )
        self.assertEqual(403, status)
        self.assertEqual("PERSONAL_AI_OPERATOR_INTENT_REQUIRED", result["error"])

        bad = {**self.prepare_payload(), "auto_approve": True}
        status, result = self.request(
            "POST", "/api/personal-ai/prepare", bad,
            intent=PERSONAL_AI_OPERATOR_INTENT,
        )
        self.assertEqual(400, status)
        self.assertEqual("INVALID_PREPARE_REQUEST", result["error"])

        prepared = self.prepare()
        self.assertEqual("APPROVAL_REQUIRED", prepared["service_guard"]["state"])
        self.assertEqual("ADVISORY_ONLY", prepared["provider"]["authority"])
        self.assertEqual("FIXTURE", prepared["provider"]["execution_mode"])
        self.assertEqual(0, self.guard.store.apply_count)
        self.assertNotIn("private", json.dumps(prepared).lower())
        self.assertNotIn("model reason", json.dumps(prepared).lower())

    def test_exact_approval_and_separate_resume_intent_gate_the_only_effect(self):
        prepared = self.prepare()
        wrong = dict(proposal_id="f" * 64)
        status, result = self.request(
            "POST", "/api/personal-ai/approve", wrong,
            intent=PERSONAL_AI_APPROVAL_INTENT,
        )
        self.assertEqual(409, status)
        self.assertEqual("PROPOSAL_BINDING_MISMATCH", result["error"])
        self.assertEqual(0, self.guard.store.apply_count)

        status, result = self.request(
            "POST", "/api/personal-ai/approve",
            {"proposal_id": prepared["proposal_id"]},
        )
        self.assertEqual(403, status)
        self.assertEqual("PERSONAL_AI_APPROVAL_INTENT_REQUIRED", result["error"])

        status, approved = self.request(
            "POST", "/api/personal-ai/approve",
            {"proposal_id": prepared["proposal_id"]},
            intent=PERSONAL_AI_APPROVAL_INTENT,
        )
        self.assertEqual(200, status, approved)
        self.assertEqual("APPROVED", approved["approval"]["status"])
        self.assertEqual(0, self.guard.store.apply_count)

        resume_body = {"operation_id": self.guard.operation_id}
        status, result = self.request(
            "POST", "/api/personal-ai/resume", resume_body,
            intent=PERSONAL_AI_OPERATOR_INTENT,
        )
        self.assertEqual(403, status)
        self.assertEqual("PERSONAL_AI_RESUME_INTENT_REQUIRED", result["error"])
        self.assertEqual(0, self.guard.store.apply_count)

        status, completed = self.request(
            "POST", "/api/personal-ai/resume", resume_body,
            intent=PERSONAL_AI_RESUME_INTENT,
        )
        self.assertEqual(200, status, completed)
        self.assertEqual("RECONCILED", completed["service_guard"]["state"])
        self.assertEqual(1, self.guard.store.apply_count)

    def test_status_is_token_protected_read_only_and_sanitized(self):
        self.prepare()
        status, result = self.request("GET", "/api/personal-ai/status")
        self.assertEqual(200, status, result)
        self.assertTrue(result["read_only"])
        self.assertEqual("aioa.nebius-personal-ai-view.v1", result["schema"])
        rendered = json.dumps(result).lower()
        for forbidden in ("memory_query", "reason_summary", "prompt", "response", "chain_of_thought"):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(0, self.guard.store.apply_count)


class PersonalAIStaticUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.html = (root / "web" / "index.html").read_text(encoding="utf-8")
        cls.script = (root / "web" / "app.js").read_text(encoding="utf-8")

    def test_compact_panel_shows_all_bounded_states_and_authority_boundary(self):
        for identifier in (
            "personal-ai-panel", "personal-ai-provider", "personal-ai-memory",
            "personal-ai-cpl", "personal-ai-verification", "personal-ai-approval",
            "personal-ai-guard", "personal-ai-receipt", "personal-ai-replay",
            "personal-ai-timeline",
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn("MODEL ≠ AUTHORITY", self.html)
        self.assertIn("Private HAT content stays hidden", self.html)

    def test_prepare_approve_and_resume_are_separate_explicit_controls(self):
        for identifier in (
            "personal-ai-prepare", "personal-ai-approve", "personal-ai-resume"
        ):
            self.assertIn(f'id="{identifier}"', self.html)
        self.assertIn('jsonFetch("/api/personal-ai/prepare"', self.script)
        self.assertIn('jsonFetch("/api/personal-ai/approve"', self.script)
        self.assertIn('jsonFetch("/api/personal-ai/resume"', self.script)
        self.assertIn('"personal-ai-prepare-v1"', self.script)
        self.assertIn('"personal-ai-approve-exact-v1"', self.script)
        self.assertIn('"personal-ai-resume-v1"', self.script)

    def test_panel_uses_redacted_projection_without_private_transcript_fields(self):
        self.assertIn("payload.provider?.execution_mode", self.script)
        self.assertIn("payload.memory?.status", self.script)
        self.assertNotIn("reason_summary", self.script)
        self.assertNotIn("chain_of_thought", self.script)
        self.assertNotIn("private_text", self.script)


if __name__ == "__main__":
    unittest.main()
