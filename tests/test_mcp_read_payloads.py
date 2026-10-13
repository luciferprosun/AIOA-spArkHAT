import unittest

from runtime.mcp_bridge import build_task
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.task_bus import encode_task, parse_task
from runtime.mcp_bridge.read_ops import (
    VERIFIED_READ_OPERATIONS,
    validate_read_payload,
)


class MCPReadPayloadTests(unittest.TestCase):
    def test_verified_live_payloads_are_accepted(self) -> None:
        cases = [
            ("system.status", {}),
            ("git.status", {}),
            ("git.status", {"short": True}),
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

    def test_git_status_short_must_be_boolean(self) -> None:
        with self.assertRaises(ContractError):
            build_task("git.status", {"short": "yes"})

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

    def test_artifact_get_live_bounds_are_enforced(self) -> None:
        artifact_id = "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b"
        build_task(
            "artifact.get",
            {"artifact_id": artifact_id, "max_bytes": 400, "max_lines": 12},
        )
        with self.assertRaises(ContractError):
            build_task(
                "artifact.get",
                {"artifact_id": artifact_id, "max_bytes": 401, "max_lines": 12},
            )
        with self.assertRaises(ContractError):
            build_task(
                "artifact.get",
                {"artifact_id": artifact_id, "max_bytes": 400, "max_lines": 13},
            )

    def test_unverified_approval_status_fails_before_transport(self) -> None:
        with self.assertRaisesRegex(ContractError, "schema is not verified"):
            build_task("approval.status", {})

    def test_artifact_offset_boundaries_survive_transport(self) -> None:
        for offset in (0, 400, 1048576):
            with self.subTest(offset=offset):
                payload = {
                    "artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b",
                    "offset": offset, "max_bytes": 400, "max_lines": 12,
                }
                task = build_task("artifact.get", payload, task_id="task-offset",
                                  idempotency_key="idem-offset")
                decoded = parse_task(encode_task(task))
                self.assertEqual(decoded.payload, payload)
                self.assertEqual(decoded.fingerprint, task.fingerprint)

    def test_artifact_offset_rejects_invalid_types_and_ranges(self) -> None:
        for offset in (-1, 1048577, True, False, 0.0, 400.5, "400", None):
            with self.subTest(offset=offset):
                with self.assertRaises(ContractError):
                    build_task("artifact.get", {
                        "artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b",
                        "offset": offset,
                    })

    def test_artifact_offset_does_not_relax_other_payload_checks(self) -> None:
        for extra in (
            {"max_bytes": 401}, {"max_lines": 13}, {"max_bytes": True},
            {"max_lines": 12.0}, {"bytes": 4096}, {"path": "../private"},
            {"unexpected": 1}, {"artifact_id": "not-a-uuid"},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ContractError):
                    build_task("artifact.get", {
                        "artifact_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b",
                        "offset": 400, **extra,
                    })

    def test_approval_status_is_privacy_blocked_for_any_payload(self) -> None:
        for payload in ({}, {"approval_id": "not-a-uuid"},
                        {"approval_id": "5e9f72f3-4983-489c-9f2b-6f1299e8ca4b"}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(ContractError, "BLOCKED_PRIVACY_PROJECTION"):
                    build_task("approval.status", payload)

    def test_other_unverified_reads_fail_before_transport(self) -> None:
        for operation in ("patch.propose", "provider.status", "provider.models"):
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ContractError, "schema is not verified"):
                    build_task(operation, {})


if __name__ == "__main__":
    unittest.main()
