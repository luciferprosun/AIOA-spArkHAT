"""Real source identity and an external oracle must replace self-reported PASS."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch as mock_patch

from nz11_support import BareRepository

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mission import git_publish, project_recipe, repository_worker
from runtime.mission.patchset import BoundedPatchSetPolicy
from runtime.mission.repair import TEST_STAGES
from runtime.mission.sandbox_contracts import PYTHON_ARGV
from runtime.mission.worker import CandidateFile, CandidatePatch, Task


class GeneralRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = BareRepository(
            self.root / "source.git",
            {
                "README.md": b"# Text utilities\n",
                "docs/żółw.md": b"Documentation fixture.\n",
                "src/textutil.py": b"def slug(text):\n    return text.strip()\n",
                "tests/test_textutil.py": b"# Operator tests remain protected.\n",
            },
        )

    def api(self, module, name):
        value = getattr(module, name, None)
        self.assertTrue(callable(value), name + " is not implemented")
        return value

    def source(self):
        cls = self.api(git_publish, "GitSourceSnapshot")
        return cls.capture(
            self.repo.path,
            expected_sha=self.repo.base,
            repository_id="text-repository",
            workspace_id="workspace-1",
        )

    def profile(self):
        case = self.api(project_recipe, "PythonFunctionCase")
        cls = self.api(project_recipe, "PythonRepositoryRecipe")
        return cls(
            repository_id="text-repository",
            source_base_sha=self.repo.base,
            allowed_paths=("src/extra.py", "src/textutil.py"),
            import_roots=("src",),
            stages=tuple(
                (
                    stage,
                    (
                        case(
                            "spaces",
                            "textutil",
                            "slug",
                            b'["  One   TWO "]',
                            b'"one-two"',
                        ),
                        case("empty", "textutil", "slug", b'[" "]', b'""'),
                    ),
                )
                for stage in TEST_STAGES
            ),
            command=PYTHON_ARGV,
        )

    def proposal(self):
        snapshot = self.source()
        base = self.root / "export"
        source = snapshot.export(base)
        task = Task(
            "general-task",
            "general-run",
            "workspace-1",
            "text-repository",
            self.repo.base,
            "Normalize whitespace and casing.",
            1000,
        )
        candidate = CandidatePatch(
            (
                CandidateFile(
                    "src/textutil.py",
                    'def slug(text):\n    return "-".join(text.lower().split())\n',
                ),
            )
        )
        preview = getattr(BoundedPatchSetPolicy(), "preview", None)
        self.assertTrue(callable(preview), "inert image preview is missing")
        patch, archive = preview(
            base,
            source=source,
            task=task,
            worker_session_id="worker-1",
            candidate=candidate,
        )
        return snapshot, base, source, task, candidate, patch, archive

    def test_source_is_actual_git_commit_tree_and_independently_exported_bytes(self):
        snapshot = self.source()
        source = snapshot.export(self.root / "export")
        self.assertEqual(snapshot.source_base_sha, self.repo.base)
        self.assertEqual(
            snapshot.git_tree_sha,
            self.repo.git("rev-parse", "main^{tree}").decode().strip(),
        )
        self.assertEqual(
            (self.root / "export/src/textutil.py").read_bytes(),
            self.repo.files["src/textutil.py"],
        )
        self.assertFalse((self.root / "export/.git").exists())
        self.assertEqual(source.source_base_sha, self.repo.base)
        self.assertEqual(snapshot.verify(self.repo.path), snapshot.digest)

    def test_source_export_denies_symlinked_parent_without_writing_through_it(self):
        actual = self.root / "actual"
        actual.mkdir(mode=0o700)
        link = self.root / "linked"
        link.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.source().export(link / "export")
        self.assertFalse((actual / "export").exists())

    def test_git_ref_drift_and_tampered_export_fail_before_any_execution(self):
        snapshot = self.source()
        newer = self.repo.commit(
            {**self.repo.files, "README.md": b"Changed\n"}, self.repo.base
        )
        self.repo.git("update-ref", "refs/heads/main", newer, self.repo.base)
        with self.assertRaises(ValueError):
            snapshot.verify(self.repo.path)
        with self.assertRaises(ValueError):
            type(snapshot).capture(
                self.repo.path,
                expected_sha=self.repo.base,
                repository_id="text-repository",
                workspace_id="workspace-1",
            )

    def test_export_bytes_cannot_claim_the_sha_of_a_different_git_tree(self):
        snapshot = self.source()
        base = self.root / "export"
        snapshot.export(base)
        (base / "src/textutil.py").write_text("forged = True\n")
        verify_export = getattr(snapshot, "verify_export", None)
        self.assertTrue(
            callable(verify_export), "Git-to-export byte binding is missing"
        )
        with self.assertRaises(ValueError):
            verify_export(base)

    def test_operator_manifest_roundtrip_is_strict_private_and_not_a_model_command(
        self,
    ):
        profile = self.profile()
        load = getattr(type(profile), "from_manifest", None)
        self.assertTrue(callable(load), "static operator manifest loader is missing")
        raw = profile.manifest_bytes()
        self.assertEqual(load(raw), profile)
        path = self.root / "operator-recipe.json"
        path.write_bytes(raw)
        path.chmod(0o600)
        self.assertEqual(type(profile).load_file(path), profile)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            type(profile).load_file(path)
        row = json.loads(raw)
        for changed in (
            {**row, "shell": "id"},
            {**row, "command": ["/bin/sh", "-c", "anything"]},
            {**row, "network": "ON"},
            {**row, "source_base_sha": "0" * 39},
        ):
            with self.assertRaises(ValueError):
                load(canonical_json_bytes(changed))

    def test_static_manifest_denies_shell_dynamic_paths_and_foreign_repo(self):
        profile = self.profile()
        for changes in (
            {"command": ("/bin/sh", "-c", "anything")},
            {"allowed_paths": ("src/*.py",)},
            {"allowed_paths": ("../escape.py",)},
            {"allowed_paths": ("tests/test_textutil.py",)},
            {"import_roots": ("/home/l",)},
            {"stages": profile.stages[:2]},
            {"source_base_sha": "wrong"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(profile, **changes)
        _, _, _, _, _, patch, _ = self.proposal()
        with self.assertRaises(ValueError):
            replace(profile, repository_id="other").validate_patch(patch)

    def test_materialization_recipe_pins_real_preimage_and_never_runs_candidate(self):
        _, base, source, task, candidate, patch, archive = self.proposal()
        profile = self.profile()
        actual, expected, spec = profile.materialization_spec(
            base,
            source=source,
            task=task,
            worker_session_id="worker-1",
            candidate=candidate,
        )
        self.assertEqual(actual, patch)
        self.assertEqual(expected, archive)
        self.assertEqual(spec["expected"]["workspace.json"], archive)
        self.assertEqual(
            (base / "src/textutil.py").read_bytes(), self.repo.files["src/textutil.py"]
        )
        self.assertEqual(
            json.loads(spec["files"]["mode.json"]), {"mode": "materialize"}
        )
        self.assertEqual(patch.files[0].operation, "MODIFY")

    def test_guest_has_calls_but_no_oracle_or_pass_counter_authority(self):
        *_, patch, archive = self.proposal()
        profile = self.profile()
        spec = profile.observation_spec("FAST_TESTS", archive, patch)
        calls = json.loads(spec["files"]["calls.json"])
        self.assertEqual(
            calls[0],
            {
                "case_id": "spaces",
                "module": "textutil",
                "function": "slug",
                "arguments": ["  One   TWO "],
            },
        )
        self.assertNotIn("expected", calls[0])
        self.assertNotIn(b'"one-two"', b"\n".join(spec["files"].values()))
        row = {
            "schema": "aioa.python-observation.v2",
            "profile_digest": profile.digest,
            "patchset_sha256": patch.patchset_sha256,
            "stage": "FAST_TESTS",
            "results": [
                {"case_id": "spaces", "kind": "returned", "value": "one-two"},
                {"case_id": "empty", "kind": "returned", "value": ""},
            ],
        }
        self.assertEqual(
            profile.decode_observation(
                canonical_json_bytes(row).decode() + "\n", "FAST_TESTS", patch
            ),
            ("PASS", 0),
        )
        row["results"][0]["value"] = "One   TWO"
        self.assertEqual(
            profile.decode_observation(
                canonical_json_bytes(row).decode() + "\n", "FAST_TESTS", patch
            ),
            ("FAIL", 1),
        )
        for forged in (
            {"status": "PASS", "tests_run": 999},
            {**row, "status": "PASS"},
            {**row, "results": row["results"][:1]},
            {**row, "profile_digest": "0" * 64},
        ):
            with self.subTest(forged=forged), self.assertRaises(ValueError):
                profile.decode_observation(
                    canonical_json_bytes(forged).decode() + "\n", "FAST_TESTS", patch
                )

    def test_protected_test_change_and_non_allowlisted_file_are_denied(self):
        _, base, source, task, _, _, _ = self.proposal()
        profile = self.profile()
        for path in ("tests/test_textutil.py", "src/other.py", ".env"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                profile.materialization_spec(
                    base,
                    source=source,
                    task=task,
                    worker_session_id="worker-1",
                    candidate=CandidatePatch((CandidateFile(path, "value = 1\n"),)),
                )

    def test_static_recipe_refuses_sensitive_call_arguments(self):
        case = self.api(project_recipe, "PythonFunctionCase")
        with self.assertRaises(ValueError):
            case(
                "credential",
                "textutil",
                "slug",
                canonical_json_bytes(["Bearer " + "a" * 32]),
                b'""',
            )

    def test_descriptor_read_accepts_atime_update_without_ignoring_content_identity(
        self,
    ):
        path = self.root / "readback.txt"
        path.write_bytes(b"fixed source\n")
        path.chmod(0o644)
        info = path.stat()
        os.utime(path, ns=(0, info.st_mtime_ns))
        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            try:
                data, mode = repository_worker.read_regular(fd, "readback.txt")
            except ValueError as error:
                self.fail(
                    "read-only atime update was treated as source drift: " + str(error)
                )
        finally:
            os.close(fd)
        self.assertEqual(data, b"fixed source\n")
        self.assertEqual(mode, 0o644)

    def test_descriptor_read_still_refuses_concurrent_same_size_rewrite(self):
        path = self.root / "readback.txt"
        path.write_bytes(b"fixed source\n")
        original = repository_worker.os.read

        def changed(fd, maximum):
            data = original(fd, maximum)
            path.write_bytes(b"other source\n")
            return data

        fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            with (
                mock_patch.object(repository_worker.os, "read", side_effect=changed),
                self.assertRaisesRegex(ValueError, "^REPOSITORY_FILE_CHANGED$"),
            ):
                repository_worker.read_regular(fd, "readback.txt")
        finally:
            os.close(fd)


if __name__ == "__main__":
    unittest.main()
