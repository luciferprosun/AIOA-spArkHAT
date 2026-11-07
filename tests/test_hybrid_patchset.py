"""Actual filesystem evidence, conservative policy and fresh readback denials."""

import copy
import hashlib
import importlib
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from runtime.mission.worker import Task


class PatchSetTests(unittest.TestCase):
    def api(self):
        try:
            return importlib.import_module("runtime.mission.patchset")
        except ModuleNotFoundError:
            self.fail("Actual-state BoundedPatchSetPolicy is not implemented")

    def setUp(self):
        self.module = self.api()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base, self.final = self.root / "base", self.root / "candidate"
        self.base.mkdir(mode=0o700)
        self.write(self.base / "calc.py", b"def add(a, b):\n    return a - b\n")
        shutil.copytree(self.base, self.final)
        self.task = Task(
            "task-1", "run-1", "workspace-1", "repo-1", "a" * 40, "Fix addition.", 200
        )
        self.source = self.module.observe_source(
            self.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        self.policy = self.module.BoundedPatchSetPolicy()

    @staticmethod
    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o644)

    def evaluate(self):
        return self.policy.evaluate(
            self.base,
            self.final,
            source=self.source,
            task=self.task,
            worker_session_id="worker-1",
        )

    def fixed(self):
        self.write(self.final / "calc.py", b"def add(a, b):\n    return a + b\n")
        return self.evaluate()

    def recheck(self, observed, **changes):
        values = {
            "base_root": self.base,
            "final_root": self.final,
            "source": self.source,
            "task": self.task,
            "worker_session_id": "worker-1",
        }
        values.update(changes)
        return self.policy.recheck(observed, **values)

    def test_modify_existing_file_has_hand_checked_hashes_and_real_diff(self):
        observed = self.fixed()
        self.assertEqual(len(observed.files), 1)
        changed = observed.files[0]
        self.assertEqual((changed.path, changed.operation), ("calc.py", "MODIFY"))
        self.assertEqual(
            changed.before.sha256,
            hashlib.sha256(b"def add(a, b):\n    return a - b\n").hexdigest(),
        )
        self.assertEqual(
            changed.after.sha256,
            hashlib.sha256(b"def add(a, b):\n    return a + b\n").hexdigest(),
        )
        self.assertEqual((changed.lines_added, changed.lines_deleted), (1, 1))
        self.assertIn("-    return a - b", observed.canonical_diff)
        self.assertIn("+    return a + b", observed.canonical_diff)
        self.assertEqual(observed.authority, "NONE")
        self.assertEqual(self.recheck(observed), observed.patchset_sha256)

    def test_add_and_delete_are_derived_from_actual_files(self):
        self.write(self.final / "new.py", b"value = 7\n")
        (self.final / "calc.py").unlink()
        observed = self.evaluate()
        self.assertEqual(
            [(f.path, f.operation) for f in observed.files],
            [("calc.py", "DELETE"), ("new.py", "ADD")],
        )

    def test_independent_tree_observer_matches_both_actual_trees(self):
        observed = self.fixed()
        self.assertEqual(
            self.module.independent_tree_digest(self.base), observed.base_tree_sha256
        )
        self.assertEqual(
            self.module.independent_tree_digest(self.final), observed.final_tree_sha256
        )
        self.assertNotEqual(observed.base_tree_sha256, observed.final_tree_sha256)

    def test_empty_patch_is_not_success(self):
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_file_bound_observes_four_changes_without_trusting_model_counts(self):
        for n in range(4):
            self.write(self.final / f"change{n}.py", b"x = 1\n")
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_exact_line_boundary_and_excess_are_distinguished(self):
        self.write(self.final / "new.py", b"x = 1\n" * 300)
        self.assertEqual(self.evaluate().lines_added, 300)
        self.write(self.final / "new.py", b"x = 1\n" * 301)
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_multiple_deletions_and_excess_removed_lines_are_denied(self):
        self.write(self.base / "other.py", b"x = 2\n")
        self.write(self.final / "other.py", b"x = 2\n")
        self.source = self.module.observe_source(
            self.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        (self.final / "calc.py").unlink()
        (self.final / "other.py").unlink()
        with self.assertRaises(ValueError):
            self.evaluate()
        self.write(self.base / "calc.py", b"x = 1\n" * 151)
        self.write(self.final / "other.py", b"x = 2\n")
        self.source = self.module.observe_source(
            self.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_binary_and_invalid_utf8_change_are_denied(self):
        for data in (b"\x00binary", b"\xffnot-utf8"):
            with self.subTest(data=data):
                self.write(self.final / "calc.py", data)
                with self.assertRaises(ValueError):
                    self.evaluate()

    def test_symlink_never_reads_or_changes_outside_canary(self):
        outside = self.root / "outside"
        self.write(outside, b"UNCHANGED\n")
        os.symlink(outside, self.final / "link.py")
        with self.assertRaises(ValueError):
            self.evaluate()
        self.assertEqual(outside.read_bytes(), b"UNCHANGED\n")

    def test_hardlink_is_denied_before_content_export(self):
        outside = self.root / "outside"
        self.write(outside, b"UNCHANGED\n")
        os.link(outside, self.final / "hard.py")
        with self.assertRaises(ValueError):
            self.evaluate()
        self.assertEqual(outside.read_bytes(), b"UNCHANGED\n")

    def test_fifo_is_denied_without_a_blocking_read(self):
        os.mkfifo(self.final / "pipe")
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_git_metadata_and_secret_paths_are_denied(self):
        for name in (".git/config", ".env", "secrets/key.pem", ".ssh/id_ed25519"):
            with self.subTest(name=name):
                location = self.final / name
                self.write(location, b"synthetic fixture\n")
                with self.assertRaises(ValueError):
                    self.evaluate()
                location.unlink()
                for directory in sorted(self.final.rglob("*"), reverse=True):
                    if directory.is_dir() and not any(directory.iterdir()):
                        directory.rmdir()

    def test_secret_content_does_not_enter_patch_or_logs(self):
        self.write(
            self.final / "calc.py",
            b"Authorization: Bearer " + b"synthetic-credential-123\n",
        )
        with self.assertRaises(ValueError) as caught:
            self.evaluate()
        self.assertNotIn("synthetic-credential", str(caught.exception))

    def test_tests_manifests_and_core_policy_are_protected(self):
        for name in (
            "tests/test_calc.py",
            "pyproject.toml",
            ".github/workflows/test.yml",
            "runtime/mission/patchset.py",
            "runtime/core_admission.py",
        ):
            with self.subTest(name=name):
                location = self.final / name
                self.write(location, b"x = 1\n")
                with self.assertRaises(ValueError):
                    self.evaluate()
                location.unlink()

    def test_unicode_traversal_and_noncanonical_paths_are_not_normalized_optimistically(
        self,
    ):
        for name in (
            "../escape.py",
            "/tmp/escape.py",
            "a/../b.py",
            "a\\b.py",
            "a//b.py",
            "cafe\u0301.py",
            "x\x00.py",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.module.normalize_patch_relative_path(name)
        self.assertEqual(
            self.module.normalize_patch_relative_path("café.py"), "café.py"
        )

    def test_case_ambiguity_is_denied_within_and_across_trees(self):
        self.write(self.final / "Calc.py", b"x = 1\n")
        with self.assertRaises(ValueError):
            self.evaluate()
        (self.final / "calc.py").unlink()
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_mode_changes_and_executable_additions_are_denied(self):
        (self.final / "calc.py").chmod(0o755)
        with self.assertRaises(ValueError):
            self.evaluate()
        (self.final / "calc.py").chmod(0o644)
        self.write(self.final / "run.py", b"print(1)\n")
        (self.final / "run.py").chmod(0o755)
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_stale_base_and_wrong_commit_binding_are_denied(self):
        self.write(self.base / "calc.py", b"def add(a, b):\n    return 0\n")
        with self.assertRaises(ValueError):
            self.fixed()
        self.write(self.base / "calc.py", b"def add(a, b):\n    return a - b\n")
        self.task = replace(self.task, source_base_sha="b" * 40)
        with self.assertRaises(ValueError):
            self.evaluate()

    def test_cross_task_and_worker_replay_are_denied(self):
        observed = self.fixed()
        with self.assertRaises(ValueError):
            self.recheck(observed, task=replace(self.task, task_id="task-2"))
        with self.assertRaises(ValueError):
            self.recheck(observed, worker_session_id="worker-2")

    def test_altered_hash_and_late_tree_change_are_denied(self):
        observed = self.fixed()
        forged = copy.copy(observed)
        object.__setattr__(forged, "patchset_sha256", "0" * 64)
        with self.assertRaises(ValueError):
            self.recheck(forged)
        self.write(self.final / "calc.py", b"def add(a, b):\n    return 9\n")
        with self.assertRaises(ValueError):
            self.recheck(observed)

    def test_file_change_during_observation_is_not_a_verified_snapshot(self):
        self.write(self.final / "calc.py", b"def add(a, b):\n    return a + b\n")
        original = self.module._read_regular
        changed = []

        def race(*args, **kwargs):
            data = original(*args, **kwargs)
            if not changed:
                changed.append(True)
                self.write(self.base / "calc.py", b"def add(a, b):\n    return 88\n")
            return data

        with (
            patch.object(self.module, "_read_regular", side_effect=race),
            self.assertRaises(ValueError),
        ):
            self.evaluate()

    def test_model_cannot_weaken_test_framework_from_application_code(self):
        for data in (
            b"import unittest\nunittest.TestCase.assertEqual = lambda *args: None\n",
            b'import pytest\npytest.skip("skip approved checks")\n',
        ):
            self.write(self.final / "calc.py", data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.evaluate()

    def test_invalid_root_type_is_a_typed_denial(self):
        with self.assertRaises(ValueError):
            self.policy.evaluate(
                str(self.base),
                self.final,
                source=self.source,
                task=self.task,
                worker_session_id="worker-1",
            )


if __name__ == "__main__":
    unittest.main()
