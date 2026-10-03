"""Paid-call-free end-to-end launcher and restart evidence."""
import json
from pathlib import Path
import tempfile
import unittest
import http.client
import threading
import subprocess
from unittest.mock import patch

from runtime.personal_ai_demo_launcher import DemoComposition, run_self_test, _require
from runtime.webapp import make_server


class DemoLauncherTests(unittest.TestCase):
    def test_full_authority_and_restart_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_self_test(Path(directory) / "demo")
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["effect_apply_count"], 1)
            self.assertEqual(result["duplicate_effect_count"], 0)
            self.assertEqual(result["state_sequence"], ["APPROVAL_REQUIRED", "APPROVED", "EXECUTED", "RECONCILED", "REPLAY_BLOCKED"])
            self.assertFalse(result["private_content_persisted"])
            self.assertFalse(result["fallback"])
            self.assertEqual(result["cpl_status"], "COMPLETED_ADVISORY")
            self.assertEqual(result["verified_delta_status"], "ZERO_WRITE")

    def test_start_does_not_call_provider_or_approve(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = DemoComposition(Path(directory) / "demo")
            try:
                self.assertEqual(demo.fixture_calls, 0)
                self.assertIsNone(demo.cpl_fixture)
                self.assertFalse(demo.catalog["live_catalog_validated"])
                self.assertEqual(demo.catalog["transport_scope"], "TEST")
                self.assertEqual(demo.runtime._lite_scheduler.bindings.provider._transport_scope, "TEST")
                self.assertEqual(demo.target.read()["effect_count"], 0)
                self.assertIsNone(demo.guard.inspect(demo.reader, demo.operation_id)["approval"])
            finally:
                demo.close()

    def test_self_test_checks_survive_optimized_python(self):
        result = subprocess.run(["python3", "-O", "-B", "-c",
            "from runtime.personal_ai_demo_launcher import _require; _require(False, 'CONTROLLED_FAILURE')"],
            capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONTROLLED_FAILURE", result.stderr)

    def test_http_flow_requires_distinct_intents_and_restarts_whole_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = DemoComposition(Path(directory) / "demo")
            web = demo.web
            server = make_server("127.0.0.1", 0, web)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def request(method, route, payload=None, intent=None, token=True):
                connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=20)
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["X-AIOA-Session-Token"] = web.csrf_token
                if intent:
                    headers["X-AIOA-Intent"] = intent
                connection.request(method, route, json.dumps(payload) if payload is not None else None, headers)
                response = connection.getresponse()
                result = response.status, json.loads(response.read())
                connection.close()
                return result
            try:
                for action in ("restart", "replay"):
                    self.assertEqual(request("POST", "/api/personal-ai/" + action,
                        {"operation_id": demo.operation_id}, "personal-ai-" + action + "-v1", False)[0], 403)
                    self.assertEqual(request("POST", "/api/personal-ai/" + action,
                        {"operation_id": demo.operation_id})[0], 403)
                initial = request("GET", "/api/personal-ai/status")
                self.assertEqual(initial[0], 200)
                self.assertEqual(initial[1]["provider"]["mode"], "FIXTURE")
                self.assertEqual(initial[1]["target"]["mode"], "FIXTURE")
                for route in ("/api/status", "/api/authority-timeline", "/api/cpl/preset", "/api/cpl/status",
                              "/api/review/scenario", "/api/competition-evaluation", "/api/provider-availability"):
                    code, result = request("GET", route)
                    self.assertEqual(code, 200, (route, result))
                self.assertEqual(demo.fixture_calls, 0)
                self.assertIsNone(demo.cpl_fixture)
                for route in ("/api/chat", "/api/model", "/api/cpl/plan"):
                    self.assertEqual(request("POST", route, {})[0], 403)
                payload = {"operation_id": demo.operation_id, "target_id": demo.target_id, "memory_query": "maintenance approved window"}
                code, prepared = request("POST", "/api/personal-ai/prepare", payload, "personal-ai-prepare-v1")
                self.assertEqual(code, 200, prepared)
                self.assertEqual(prepared["service_guard"]["state"], "APPROVAL_REQUIRED")
                self.assertEqual(prepared["verification"]["delta"], "ZERO_WRITE")
                for action in ("resume", "restart", "replay"):
                    code, result = request("POST", "/api/personal-ai/" + action,
                        {"operation_id": demo.operation_id}, "personal-ai-" + action + "-v1")
                    self.assertIn(code, (400, 409))
                    self.assertEqual(demo.target.read()["effect_count"], 0)
                code, approved = request("POST", "/api/personal-ai/approve", {"proposal_id": prepared["proposal_id"]}, "personal-ai-approve-exact-v1")
                self.assertEqual(code, 200, approved)
                self.assertEqual(demo.target.read()["effect_count"], 0)
                for action, expected in (("resume", "EXECUTED"), ("restart", "RECONCILED"), ("replay", "REPLAY_BLOCKED")):
                    code, result = request("POST", "/api/personal-ai/" + action,
                        {"operation_id": demo.operation_id}, "personal-ai-" + action + "-v1")
                    self.assertEqual(code, 200, result)
                    self.assertEqual(result["service_guard"]["state"], expected)
                    self.assertEqual(result["effects"]["apply_count"], 1)
                    self.assertEqual(result["effects"]["duplicate_count"], 0)
                self.assertIsNot(web.runtime, demo.runtime)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
                web.personal_ai_demo_owner.close()

    def test_live_provider_requires_separate_cost_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = DemoComposition(Path(directory) / "demo", mode="LIVE")
            try:
                with self.assertRaisesRegex(ValueError, "BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION"):
                    demo.prepare()
                self.assertEqual(demo.target.read()["effect_count"], 0)
            finally:
                demo.close()


if __name__ == "__main__":
    unittest.main()
