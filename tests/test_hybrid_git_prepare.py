"""General patch preparation never widens the existing create-only actuator."""

import tempfile
import unittest
from pathlib import Path

from runtime.mission.git_publish import CoreRemoteGitRoute
from runtime.mission.patchset import observe_source
from runtime.mission.worker import Task


class GitPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.base = self.root / "base"
        self.final = self.root / "final"
        self.base.mkdir(mode=0o700)
        self.final.mkdir(mode=0o700)
        for path, text in (
            (self.base / "calc.py", "a-b"),
            (self.final / "calc.py", "a+b"),
        ):
            path.write_text("def add(a,b):\n    return " + text + "\n")
            path.chmod(0o644)
        self.task = Task(
            "task-1",
            "run-1",
            "workspace-1",
            "1445911975",
            "a" * 40,
            "Fix arithmetic.",
            200,
        )
        self.source = observe_source(
            self.base,
            repository_id=self.task.repository_id,
            workspace_id=self.task.workspace_id,
            source_base_sha="a" * 40,
        )

    def prepare(self):
        method = getattr(CoreRemoteGitRoute, "prepare_patchset", None)
        self.assertTrue(
            callable(method),
            "Missing bounded preparation on the one existing Git route",
        )
        return method(
            self.base,
            self.final,
            source=self.source,
            task=self.task,
            worker_session_id="worker-1",
            capsule_digest="b" * 64,
        )

    def test_real_modify_has_exact_postimage_but_no_write_authority(self):
        plan = self.prepare()
        self.assertEqual(plan.patchset.files[0].operation, "MODIFY")
        self.assertEqual(plan.postimages[0][1], (self.final / "calc.py").read_bytes())
        self.assertEqual(plan.authority, "NONE")
        self.assertFalse(plan.preview()["live_enabled"])

    def test_modify_cannot_be_cast_to_create_only_github_profile(self):
        plan = self.prepare()
        with self.assertRaises(ValueError):
            plan.create_only_plan(
                title="Fix",
                body="Reviewed",
                operation_id="c" * 32,
                issued_at=100,
                base_tree_sha="d" * 40,
                source_reply_sha256="e" * 64,
                source_receipt_sha256="f" * 64,
            )

    def test_late_drift_stale_source_and_model_selected_path_are_denied(self):
        self.prepare()
        (self.base / "calc.py").write_text("def add(a,b):\n    return a*b\n")
        with self.assertRaises(ValueError):
            self.prepare()

    def test_symbolic_link_is_refused_before_any_git_operation(self):
        (self.final / "calc.py").unlink()
        (self.final / "calc.py").symlink_to(self.base / "calc.py")
        with self.assertRaises(ValueError):
            self.prepare()


if __name__ == "__main__":
    unittest.main()
