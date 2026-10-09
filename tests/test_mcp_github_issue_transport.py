import unittest

from runtime.mcp_bridge import TaskResult, TaskState, build_task
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.github_issue_transport import (
    build_issue_body,
    build_issue_title,
    build_result_comment,
    parse_issue,
    parse_result_comment,
)


class MCPGitHubIssueTransportTests(unittest.TestCase):
    def test_issue_round_trip(self) -> None:
        task = build_task(
            "system.status",
            {},
            task_id="task-issue-1",
            idempotency_key="idem-issue-1",
        )
        parsed = parse_issue(15, build_issue_title(task), build_issue_body(task))
        self.assertEqual(parsed.issue_number, 15)
        self.assertEqual(parsed.task, task)

    def test_title_task_id_mismatch_fails(self) -> None:
        task = build_task("git.status", {}, task_id="task-good")
        with self.assertRaises(ContractError):
            parse_issue(1, "[MCP-TASK] task-bad :: git.status", build_issue_body(task))

    def test_title_operation_mismatch_fails(self) -> None:
        task = build_task("git.status", {}, task_id="task-good")
        with self.assertRaises(ContractError):
            parse_issue(1, "[MCP-TASK] task-good :: git.diff", build_issue_body(task))

    def test_result_comment_round_trip(self) -> None:
        result = TaskResult(
            task_id="task-result-1",
            state=TaskState.DONE,
            summary="worker healthy",
            metadata={"worker": "local"},
        )
        self.assertEqual(parse_result_comment(build_result_comment(result)), result)

    def test_plain_comment_cannot_masquerade_as_result(self) -> None:
        with self.assertRaises(ContractError):
            parse_result_comment("approved=true")


if __name__ == "__main__":
    unittest.main()
