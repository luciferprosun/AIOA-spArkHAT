"""Hermetic tests for the offline MVP-01 mission runner. No network."""

from __future__ import annotations

import hashlib
import io
import json
import socket
import unittest
import urllib.request
from contextlib import redirect_stdout

from runtime.meta_hackathon import mission_runner_offline as runner
from runtime.meta_hackathon.contracts import MetaContractError


def _run(**kwargs):
    return runner.run_offline_demo(**kwargs)


class TestMissionRunner(unittest.TestCase):
    def test_demo_summary_shape(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            code = runner.main(["--demo"])
        self.assertEqual(code, 0)
        summary = json.loads(out.getvalue())
        self.assertEqual(summary["status"], "OFFLINE_LINKED_UNVERIFIED")
        self.assertEqual(summary["environment"], "OFFLINE_FIXTURE")
        self.assertFalse(summary["verified"])
        self.assertFalse(summary["dispatch_allowed"])
        self.assertEqual(summary["terminal_state"], "OBSERVED")
        self.assertRegex(summary["task_digest"], r"[0-9a-f]{64}")
        self.assertRegex(summary["evidence_digest"], r"[0-9a-f]{64}")
        self.assertIn("source_sha_note", summary)
        blob = json.dumps(summary)
        self.assertNotIn("MOCK_DONE", blob.replace(summary["status"], ""))
        for banned in ("api_key", "Bearer", "password", "prompt"):
            self.assertNotIn(banned, blob.lower())

    def test_core_read_denial(self) -> None:
        with self.assertRaises(Exception):
            _run(without_read=True)

    def test_stop_denies(self) -> None:
        try:
            result = _run(stopped=True)
        except Exception:
            return
        self.assertEqual(result.get("status"), "UNKNOWN")

    def test_binding_drift_denies(self) -> None:
        with self.assertRaises(Exception):
            _run(owner_scope_digest="0" * 64)
        with self.assertRaises(Exception):
            _run(source_sha="1" * 40)

    def test_no_network(self) -> None:
        real_socket, real_urlopen = socket.socket, urllib.request.urlopen

        def _denied(*args, **kwargs):
            raise AssertionError("network used")

        socket.socket = _denied  # type: ignore[assignment]
        urllib.request.urlopen = _denied  # type: ignore[assignment]
        try:
            summary = _run()
        finally:
            socket.socket = real_socket  # type: ignore[assignment]
            urllib.request.urlopen = real_urlopen
        self.assertEqual(summary["status"], "OFFLINE_LINKED_UNVERIFIED")

    def test_no_verified_done_claim(self) -> None:
        summary = _run()
        self.assertFalse(summary["verified"])
        self.assertFalse(summary["dispatch_allowed"])
        self.assertNotEqual(summary["status"], "VERIFIED")
        self.assertNotEqual(summary.get("terminal_state"), "DONE")
        with self.assertRaises(MetaContractError):
            _run(now_utc="2026-06-03T12:00:00Z")
        digest = hashlib.sha256(b"meta-mvp-01-demo-nonce").hexdigest()
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
