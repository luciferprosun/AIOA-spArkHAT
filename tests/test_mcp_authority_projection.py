import unittest

from runtime.mcp_bridge import build_task, evaluate_task
from runtime.mcp_bridge.authority import project_authority


class MCPAuthorityProjectionTests(unittest.TestCase):
    def test_read_projects_to_auto_read_only(self) -> None:
        decision = evaluate_task(build_task("git.status", {}))
        projection = project_authority(decision)
        self.assertEqual(projection.authority_gate, "AUTO_READ_ONLY")
        self.assertTrue(projection.executable)
        self.assertFalse(projection.requires_human)
        self.assertEqual(projection.source_authority, "ADVISORY_ONLY")

    def test_write_projects_to_plan_and_confirm(self) -> None:
        decision = evaluate_task(build_task("patch.request_apply", {"path": "README.md"}))
        projection = project_authority(decision)
        self.assertEqual(projection.authority_gate, "PLAN_AND_CONFIRM")
        self.assertFalse(projection.executable)
        self.assertTrue(projection.requires_human)

    def test_unknown_projects_to_never_autonomous(self) -> None:
        decision = evaluate_task(build_task("terminal.exec", {"command": "whoami"}))
        projection = project_authority(decision)
        self.assertEqual(projection.authority_gate, "NEVER_AUTONOMOUS")
        self.assertFalse(projection.executable)
        self.assertFalse(projection.requires_human)


if __name__ == "__main__":
    unittest.main()
