"""The generic observer must stay on the existing Core sandbox route."""

import unittest

import test_nz11_general_recipe as support
from q09_support import Fixture

from runtime.mission import repair_validation


class CoreRecipeTests(unittest.TestCase):
    def setUp(self):
        self.case = support.GeneralRecipeTests(
            "test_source_is_actual_git_commit_tree_and_independently_exported_bytes"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = Fixture(self.case.root / "core.json")
        self.addCleanup(self.fx.close)

    def test_generic_recipe_is_accepted_without_creating_another_core(self):
        profile = self.case.profile()
        try:
            validator = repair_validation.CoreSandboxValidation(
                self.fx.journal,
                lambda *_: (),
                profile=profile,
            )
        except ValueError as error:
            self.fail("generic operator recipe was refused: " + str(error))
        self.assertIs(validator.journal, self.fx.journal)
        self.assertIs(validator.profile, profile)

    def test_foreign_session_ids_fail_before_source_or_sandbox_access(self):
        from runtime.mission.worker import (
            CandidateFile,
            CandidatePatch,
            Task,
            WorkerSession,
        )

        snapshot = self.case.source()
        task = Task(
            "task-1",
            "run-1",
            "workspace-1",
            "text-repository",
            snapshot.source_base_sha,
            "Normalize text.",
            1000,
        )
        materializer = repair_validation.CoreRepositoryMaterializer(
            self.fx.journal,
            lambda *_: self.fail("sandbox accessed"),
            profile=self.case.profile(),
            source_snapshot=snapshot,
            source_repository=self.case.repo.path,
            base_root=self.case.root / "missing-export",
            output_root=self.case.root / "outputs",
        )
        session = WorkerSession(
            "session-1", "foreign-task", "foreign-run", task.digest, "synthetic"
        )
        with self.assertRaisesRegex(ValueError, "MATERIALIZATION_TASK_BINDING"):
            materializer.materialize(
                task,
                session,
                CandidatePatch((CandidateFile("src/textutil.py", "value = 1\n"),)),
            )

    def test_materializer_requires_actual_core_and_never_accepts_model_authority(self):
        cls = getattr(repair_validation, "CoreRepositoryMaterializer", None)
        self.assertTrue(
            callable(cls), "Core-owned repository materialization is missing"
        )
        for journal in (None, {}, {"approved": True}):
            with self.subTest(journal=journal), self.assertRaises(ValueError):
                cls(
                    journal,
                    lambda *_: None,
                    profile=self.case.profile(),
                    source_snapshot=self.case.source(),
                    source_repository=self.case.repo.path,
                    base_root=self.case.root / "base",
                    output_root=self.case.root / "outputs",
                )


if __name__ == "__main__":
    unittest.main()
