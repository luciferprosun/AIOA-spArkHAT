"""Prepared B regressions: preserve signed legacy task rows and bind new budgets.

Not installed in the frozen A checkout; execute RED when phase B begins.
All keys and records below are fresh test data, never host credentials.
"""
import hashlib
import importlib.util
import json
import unittest
from dataclasses import replace

from runtime.nonzero_cloudops import module_descriptor

AVAILABLE = module_descriptor()["available"] and importlib.util.find_spec("cryptography") is not None
if AVAILABLE:
    from cryptography.hazmat.primitives.asymmetric import ec

    from runtime.core_admission import OwnerScope
    from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
    from runtime.mission.coding_tasks import decode_coding_task_row
    from runtime.mission.worker import Task
    from runtime.mobile_gateway.wire import Identity


def independent_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


@unittest.skipUnless(AVAILABLE, "NonZero/native optional extras are not installed")
class TaskReceiptCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.legacy = {
            "task_id": "legacy-task", "run_id": "legacy-run", "workspace_id": "workspace-1",
            "repository_id": "repo-1", "source_base_sha": "a" * 40,
            "instruction": "Fix the neutral arithmetic fixture.", "deadline_at": 200,
            "max_events": 64,
        }

    def record(self, payload, digest):
        receipts = []
        previous = "0" * 64
        for sequence, state in enumerate(("QUEUED", "RUNNING", "CANCELLED"), 1):
            body = {"schema": "aioa.coding-intake-receipt.v1", "task_digest": digest,
                    "sequence": sequence, "state": state, "previous": previous,
                    "capsule_digest": None}
            signed = {"receipt": body, "signature": self.identity.sign(body)}
            receipts.append(signed)
            previous = independent_digest(signed)
        return StoredRecord(RecordKind.OPERATION, "legacy-task-record",
                            OwnerScope("tenant-test", "owner-test", "space-test", "slot-test"), 1,
                            {"schema": "aioa.coding-task.v1", "task": payload,
                             "task_digest": digest, "receipts": receipts})

    def decode(self, row):
        return decode_coding_task_row(row, "legacy-task", self.identity.spki)

    def budget_task(self, limit):
        self.assertIn("max_output_tokens", Task.__dataclass_fields__,
                      "Canonical Task has no bounded output budget")
        return Task(**self.legacy, max_output_tokens=limit)

    def test_legacy_signed_chain_remains_readable_without_rewrite_or_resigning(self):
        digest = independent_digest(self.legacy)
        row = self.record(dict(self.legacy), digest)
        original_payload = row.payload
        returned, payload, task = self.decode(row)
        self.assertIs(returned, row)
        self.assertEqual(task.digest, digest)
        self.assertEqual(task.to_dict(), self.legacy)
        self.assertEqual(payload["receipts"][-1]["receipt"]["state"], "CANCELLED")
        self.assertIs(row.payload, original_payload)
        self.assertEqual(set(payload["task"]), set(self.legacy))

    def test_explicit_legacy_default_reads_the_same_original_signature_chain(self):
        self.budget_task(1024)
        digest = independent_digest(self.legacy)
        row = self.record({**self.legacy, "max_output_tokens": 1024}, digest)
        _, _, task = self.decode(row)
        self.assertEqual(task.digest, digest)
        self.assertEqual(task.max_output_tokens, 1024)

    def test_nondefault_limit_has_independent_bound_canonical_digest(self):
        task = self.budget_task(64)
        payload = {**self.legacy, "max_output_tokens": 64}
        digest = independent_digest(payload)
        self.assertEqual(task.digest, digest)
        self.assertNotEqual(digest, independent_digest(self.legacy))
        _, _, decoded = self.decode(self.record(payload, digest))
        self.assertEqual(decoded.max_output_tokens, 64)

    def test_budget_change_cannot_reuse_a_valid_legacy_signature(self):
        self.budget_task(64)
        row = self.record({**self.legacy, "max_output_tokens": 64}, independent_digest(self.legacy))
        with self.assertRaises(ValueError):
            self.decode(row)

    def test_extended_budget_tampering_is_denied_without_new_valid_signatures(self):
        task = self.budget_task(64)
        row = self.record({**self.legacy, "max_output_tokens": 128}, task.digest)
        with self.assertRaises(ValueError):
            self.decode(row)
        self.assertNotEqual(replace(task, max_output_tokens=128).digest, task.digest)

    def test_wrong_signer_never_becomes_legacy_compatibility(self):
        row = self.record(dict(self.legacy), independent_digest(self.legacy))
        other = Identity(ec.generate_private_key(ec.SECP256R1()))
        with self.assertRaises(ValueError):
            decode_coding_task_row(row, "legacy-task", other.spki)


if __name__ == "__main__":
    unittest.main()
