"""A self-consistent PatchSet is insufficient to mint a Git effect."""

import unittest
from contextlib import nullcontext
from pathlib import Path

import test_nz11_general_recipe as support
from cryptography.hazmat.primitives.asymmetric import ec
from q09_support import Fixture

from runtime.mission.git_publish import CoreRemoteGitRoute, VerifiedPatchSet
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mobile_gateway.wire import Identity


class GitJoinTests(unittest.TestCase):
    def setUp(self):
        self.case = support.GeneralRecipeTests(
            "test_source_is_actual_git_commit_tree_and_independently_exported_bytes"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = Fixture(self.case.root / "core.json")
        self.addCleanup(self.fx.close)
        (
            self.snapshot,
            self.base,
            self.source,
            self.task,
            self.candidate,
            self.patch,
            self.archive,
        ) = self.case.proposal()
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.capsules = CorePatchCapsules(
            self.fx.journal, self.identity, source_probe=lambda: self.source
        )
        self.preparation = VerifiedPatchSet(
            self.patch,
            tuple((f.path, f.text.encode()) for f in self.candidate.files),
            "0" * 64,
            tuple(
                (c.path, dict(self.snapshot.files).get(c.path))
                for c in self.patch.files
            ),
        )

    def factory(self):
        method = getattr(CoreRemoteGitRoute, "for_local_patch", None)
        self.assertTrue(
            callable(method), "the canonical capsule/Core/Git join is missing"
        )
        return method

    def test_inert_preparation_cannot_substitute_for_canonical_capsule(self):
        method = self.factory()
        with self.assertRaisesRegex(ValueError, "CAPSULE_REQUIRED"):
            method(
                self.fx.p(),
                self.fx.journal,
                capsules=self.capsules,
                preparation=self.preparation,
                profile=self.case.profile(),
                source_snapshot=self.snapshot,
                source_repository=self.case.repo.path,
                target_repository=self.case.repo.path,
                check=lambda: None,
                target_guard=nullcontext,
            )

    def test_local_plan_binds_unchanged_unicode_paths_to_the_actual_final_tree(self):
        from runtime.mission.git_publish import LocalPatchGitPlan

        plan = LocalPatchGitPlan(
            self.snapshot,
            self.preparation,
            self.case.profile().digest,
            (1, 2, "a" * 64),
            100,
        )
        self.assertIn("docs/żółw.md", dict(plan.files))
        self.assertEqual(plan.source.export_tree_sha256, self.patch.base_tree_sha256)

    def test_bare_target_needs_an_explicit_disposable_fixture_marker(self):
        from runtime.mission.git_publish import _git_target_identity

        with self.assertRaises(ValueError):
            _git_target_identity(self.case.repo.path)

    def test_join_refuses_another_core_before_accessing_any_repository(self):
        method = self.factory()
        with self.assertRaisesRegex(ValueError, "EXISTING_CORE_REQUIRED"):
            method(
                self.fx.p(),
                None,
                capsules=self.capsules,
                preparation=self.preparation,
                profile=self.case.profile(),
                source_snapshot=self.snapshot,
                source_repository=self.case.repo.path,
                target_repository=Path("/unrelated"),
                check=lambda: None,
                target_guard=nullcontext,
            )


if __name__ == "__main__":
    unittest.main()
