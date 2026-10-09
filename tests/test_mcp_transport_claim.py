import json
import unittest

from runtime.mcp_bridge.claim import CLAIM_PREFIX, parse_claim_comment
from runtime.mcp_bridge.contracts import ContractError


class MCPTransportClaimTests(unittest.TestCase):
    def _claim(self) -> dict:
        return {
            "envelope_task_id": "task-system-status-001",
            "local_job_id": "9bd7f5a4-24de-434d-8783-9adf6990d15b",
            "issue_number": 13,
            "worker_id": "f10c867d-0ade-4d99-9a4f-cca3fcf024fb",
            "nonce": "59b83691-23e2-415b-983d-bb44af606fd4",
            "payload_hash": "d" * 64,
            "lease_expires_at": 1791262402065,
        }

    def test_valid_claim_is_transport_evidence_only(self) -> None:
        claim = parse_claim_comment(CLAIM_PREFIX + json.dumps(self._claim()))
        self.assertEqual(claim.authority, "TRANSPORT_EVIDENCE_ONLY")
        self.assertFalse(claim.can_authorize_effects)
        self.assertEqual(claim.issue_number, 13)

    def test_claim_cannot_smuggle_approval(self) -> None:
        value = self._claim()
        value["approved"] = True
        with self.assertRaises(ContractError):
            parse_claim_comment(CLAIM_PREFIX + json.dumps(value))

    def test_bad_hash_is_rejected(self) -> None:
        value = self._claim()
        value["payload_hash"] = "xyz"
        with self.assertRaises(ContractError):
            parse_claim_comment(CLAIM_PREFIX + json.dumps(value))

    def test_non_uuid_worker_identity_is_rejected(self) -> None:
        value = self._claim()
        value["worker_id"] = "worker-1"
        with self.assertRaises(ContractError):
            parse_claim_comment(CLAIM_PREFIX + json.dumps(value))

    def test_plain_github_comment_is_not_a_claim(self) -> None:
        with self.assertRaises(ContractError):
            parse_claim_comment("approved=true")


if __name__ == "__main__":
    unittest.main()
