from __future__ import annotations

import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from evidence_review import bundled_scenario
from webapp import MAX_REQUEST_BYTES, make_server


class EvidenceReviewWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = make_server("127.0.0.1", 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_health_and_static_ui_are_unified(self) -> None:
        with urlopen(f"{self.base_url}/api/health", timeout=2) as response:
            payload = json.load(response)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["system"], "AOIA-Core")
            self.assertEqual(payload["network"], "local-only")
            self.assertIn("default-src 'self'", response.headers["Content-Security-Policy"])

        with urlopen(f"{self.base_url}/", timeout=2) as response:
            body = response.read().decode("utf-8")
        self.assertIn("AIOA spArkHAT Operator Console", body)
        self.assertIn("Formerly AOIA-Core", body)
        self.assertIn("Evidence review", body)

    def test_scenario_endpoint_returns_isolated_registry(self) -> None:
        with urlopen(f"{self.base_url}/api/review/scenario", timeout=2) as response:
            payload = json.load(response)

        self.assertEqual(payload["id"], "de-minimum-wage-2026")
        self.assertEqual(payload["expected_current_value"], "13.90")
        self.assertEqual(len(payload["evidence"]), 3)

    def test_review_endpoint_flags_bundled_answer(self) -> None:
        body = json.dumps(
            {"candidate_answer": bundled_scenario()["candidate_answer"]}
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/api/review",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:
            payload = json.load(response)

        self.assertEqual(payload["value_status"], "STALE_VALUE_DETECTED")
        self.assertEqual(payload["authority"], "METADATA_ONLY_NO_AUTHORITY")
        self.assertFalse(payload["network_used"])

    def test_invalid_and_oversized_payloads_fail_closed(self) -> None:
        invalid_request = Request(
            f"{self.base_url}/api/review",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as invalid_context:
            urlopen(invalid_request, timeout=2)
        self.assertEqual(invalid_context.exception.code, 400)

        oversized_request = Request(
            f"{self.base_url}/api/review",
            data=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as oversized_context:
            urlopen(oversized_request, timeout=2)
        self.assertEqual(oversized_context.exception.code, 413)

    def test_non_loopback_binding_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_server("0.0.0.0", 0)


if __name__ == "__main__":
    unittest.main()
