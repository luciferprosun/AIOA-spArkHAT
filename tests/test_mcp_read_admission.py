"""Offline transport-to-Core READ admission regressions."""

import unittest

from runtime.mcp_bridge import (
    PolicyEffect, RiskClass, TaskEnvelope, build_task, evaluate_task,
)
from runtime.mcp_bridge.authority import project_authority
from runtime.mcp_bridge.task_bus import encode_task, parse_task


class MCPReadAdmissionTests(unittest.TestCase):
    def inbound(self, operation, payload):
        # Untrusted senders need not use the planner's build_task helper.
        task = TaskEnvelope(
            task_id="fixture-inbound", target_project="commander",
            operation=operation, risk=RiskClass.READ, payload=payload,
            idempotency_key="fixture-idem", created_at="2026-10-10T00:00:00Z",
        )
        return parse_task(encode_task(task))

    def assert_denied(self, task):
        decision = evaluate_task(task)
        self.assertEqual(decision.effect, PolicyEffect.DENY)
        projection = project_authority(decision)
        self.assertFalse(projection.executable)
        self.assertEqual(projection.authority_gate, "NEVER_AUTONOMOUS")

    def test_inbound_approval_status_remains_privacy_blocked(self):
        for payload in ({}, {"approval_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b"}):
            with self.subTest(payload=payload):
                self.assert_denied(self.inbound("approval.status", payload))

    def test_inbound_unverified_reads_are_denied(self):
        for operation in ("patch.propose", "provider.status", "provider.models"):
            with self.subTest(operation=operation):
                self.assert_denied(self.inbound(operation, {}))

    def test_inbound_malformed_reads_are_denied(self):
        cases = (
            ("git.status", {"short": "true"}),
            ("git.status", {"unexpected": True}),
            ("fs.read", {"path": "../private"}),
            ("fs.read", {"path": "README.md", "bytes": 8193}),
            ("artifact.get", {"artifact_id": "invalid"}),
            ("artifact.get", {"artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b", "offset": True}),
            ("artifact.get", {"artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b", "max_bytes": 401}),
            ("artifact.get", {"artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b", "max_lines": 13}),
        )
        for operation, payload in cases:
            with self.subTest(operation=operation, payload=payload):
                self.assert_denied(self.inbound(operation, payload))

    def test_mutated_planner_payload_is_revalidated(self):
        task = build_task("fs.read", {"path": "README.md", "bytes": 100})
        task.payload["path"] = "../private"
        self.assert_denied(task)

    def test_denial_reason_does_not_echo_untrusted_payload(self):
        marker = "SYNTHETIC_PRIVATE_MARKER"
        task = self.inbound("git.status", {marker: "synthetic-secret"})
        decision = evaluate_task(task)
        self.assertEqual(decision.effect, PolicyEffect.DENY)
        self.assertNotIn(marker, decision.reason)
        self.assertNotIn("synthetic-secret", decision.reason)

    def test_valid_read_duplicate_delivery_stays_read_only(self):
        task = self.inbound("artifact.get", {
            "artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b",
            "offset": 1048576, "max_bytes": 400, "max_lines": 12,
        })
        for delivery in (task, parse_task(encode_task(task))):
            decision = evaluate_task(delivery)
            self.assertEqual(decision.effect, PolicyEffect.ALLOW)
            self.assertEqual(project_authority(decision).authority_gate, "AUTO_READ_ONLY")
            self.assertEqual(project_authority(decision).source_authority, "ADVISORY_ONLY")


if __name__ == "__main__":
    unittest.main()
