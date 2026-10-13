import json
import tempfile
import unittest
from pathlib import Path

from tools.executor import ExecutionEngine
from tools.memory import MemoryStore


class ExecutorContainmentTests(unittest.TestCase):
    def test_action_results_are_replay_only_not_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "project"
            desktop_dir = Path(tmp) / "Desktop"
            project_dir.mkdir()
            desktop_dir.mkdir()

            memory = MemoryStore(project_dir, project_dir)
            engine = ExecutionEngine(project_dir, memory)
            result = engine.execute(
                {
                    "action": "create_folder",
                    "path": str(desktop_dir / "AI_TEST"),
                    "reason": "Create desktop folder.",
                },
                require_approval=False,
            )

            self.assertFalse(result["success"])
            self.assertEqual('UNSUPPORTED_EFFECT_ROUTE',result['error'])
            self.assertFalse((desktop_dir / "AI_TEST").exists())
            self.assertTrue(memory.memory.recent_outputs)
            self.assertEqual(len(list(memory.paths.command_logs_dir.glob("*.json"))), 1)
            self.assertFalse(memory.evidence_file.exists())

            history_lines = memory.history_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(history_lines), 1)
            history_record = json.loads(history_lines[0])
            authority = history_record["payload"]["authority"]
            self.assertEqual(history_record["kind"], "action_result")
            self.assertEqual(authority["classification"], "operational_event")
            self.assertEqual(authority["retention"], "replay_only")
            self.assertTrue(authority["non_authoritative"])
            self.assertFalse(authority["canonical_evidence"])


if __name__ == "__main__":
    unittest.main()
