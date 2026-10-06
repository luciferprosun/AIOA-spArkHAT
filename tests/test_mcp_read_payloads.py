import unittest

from runtime.mcp_bridge import build_task
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.read_ops import (
    VERIFIED_READ_OPERATIONS,
    validate_read_payload,
)


class MCPReadPayloadTests(unittest.TestCase):
    def test_verified_live_payloads_are_accepted(self) -> None:
        cases = [
            ("system.status", {}),
            ("git.status", {}),
            ("git.branches", {}),
            ("git.diff", {"max_bytes": 500, "max_lines": 12}),
            ("git.log", {"limit": 2}),
            ("fs.list", {"path": ".", "limit": 8}),
            ("fs.stat", {"path": "README.md"}),
            ("fs.read", {"path": "README.md", "bytes": 200, "lines": 6}),
            ("fs.search", {"query": "MCP Commander", "max_hits": 3}),
            ("artifact.list", {}),
            (
                "artifact.get",
                {
                    "artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b",
                    "max_bytes": 400,
                    "max_lines": 12,
                },
            ),
        ]
        for operation, payload in cases:
            with self.subTest(operation=operation):
                self.assertIn(operation, VERIFIED_READ_OPERATIONS)
                validate_read_payload(operation, payload)
                task = build_task(operation, payload)
                self.assertEqual(task.operation, operation)

    def test_unknown_payload_key_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            build_task("git.status", {"unexpected": True})

    def test_path_escape_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            build_task("fs.read", {"path": "../secrets.txt", "bytes": 100})

    def test_unbounded_read_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            build_task("fs.read", {"path": "README.md", "bytes": 999999})

    def test_artifact_id_must_be_uuid(self) -> None:
        with self.assertRaises(ContractError):
            build_task("artifact.get", {"artifact_id": "not-an-id"})

    def test_unverified_approval_status_fails_before_transport(self) -> None:
        with self.assertRaisesRegex(ContractError, "schema is not verified"):
            build_task("approval.status", {})

    def test_other_unverified_reads_fail_before_transport(self) -> None:
        for operation in ("patch.propose", "provider.status", "provider.models"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ContractError, "schema is not verified"):
                    build_task(operation, {})


if __name__ == "__main__":
    unittest.main()
