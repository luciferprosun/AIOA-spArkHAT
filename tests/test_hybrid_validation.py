"""Trusted report decoding is distinct from model prose and test-process exit."""

import importlib
import json
import tempfile
import unittest
from pathlib import Path


class ValidationTests(unittest.TestCase):
    def test_full_archive_refuses_sensitive_content_even_in_unchanged_files(self):
        api = self.api()
        raw = json.dumps(
            {
                "schema": "aioa.validation-workspace.v1",
                "files": [
                    {
                        "path": "config.py",
                        "mode": 0o600,
                        "text": "api_key=synthetic-secret-value\n",
                    }
                ],
            }
        ).encode()
        with self.assertRaises(ValueError):
            api.workspace_tree_digest(raw)

    def api(self):
        try:
            return importlib.import_module("runtime.mission.repair_validation")
        except ModuleNotFoundError:
            self.fail("Core-bound validation receipt adapter is not implemented")

    def context(self):
        return {
            "schema": "aioa.trusted-test-context.v1",
            "stage": "FAST_TESTS",
            "profile_digest": "a" * 64,
            "patchset_sha256": "b" * 64,
            "test_count": 3,
        }

    def report(self, **changes):
        result = {
            "schema": "aioa.trusted-test-result.v1",
            "stage": "FAST_TESTS",
            "profile_digest": "a" * 64,
            "patchset_sha256": "b" * 64,
            "tests_run": 3,
            "status": "PASS",
            "exit_code": 0,
        }
        result.update(changes)
        return json.dumps(result) + "\n"

    def test_complete_passing_report_and_actual_failure_remain_distinct(self):
        api = self.api()
        self.assertEqual(
            api.decode_test_report(self.report(), self.context()), ("PASS", 0)
        )
        self.assertEqual(
            api.decode_test_report(
                self.report(status="FAIL", exit_code=1, tests_run=1), self.context()
            ),
            ("FAIL", 1),
        )

    def test_partial_wrong_stage_swapped_patch_and_false_exit_never_pass(self):
        api = self.api()
        for changes in (
            {"tests_run": 2},
            {"stage": "FINAL_TESTS"},
            {"patchset_sha256": "c" * 64},
            {"profile_digest": "c" * 64},
            {"exit_code": 1},
            {"exit_code": True},
            {"status": "UNKNOWN"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                api.decode_test_report(self.report(**changes), self.context())

    def test_prose_duplicate_json_and_truncated_eof_are_not_reports(self):
        api = self.api()
        for text in (
            "All tests PASS\n",
            self.report() + self.report(),
            self.report().rstrip(),
            '{"status":"PASS","status":"PASS"}\n',
        ):
            with self.subTest(text=text[:24]), self.assertRaises(ValueError):
                api.decode_test_report(text, self.context())

    def test_validator_does_not_accept_a_second_fake_journal(self):
        api = self.api()
        with self.assertRaises(ValueError):
            api.CoreSandboxValidation({}, lambda *_: ())

    def test_empty_prepared_steps_cannot_execute_or_fake_success(self):
        api = self.api()
        from q09_support import Fixture

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory) / "core.json")
            try:
                validator = api.CoreSandboxValidation(fixture.journal, lambda *_: ())
                with self.assertRaises(ValueError):
                    validator.open(Path(directory), None)
            finally:
                fixture.close()

    def test_archive_is_bound_to_actual_final_tree_and_refuses_late_drift(self):
        api = self.api()
        from runtime.mission.patchset import BoundedPatchSetPolicy, observe_source
        from runtime.mission.worker import Task

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "base"
            final = Path(directory) / "final"
            base.mkdir(mode=0o700)
            final.mkdir(mode=0o700)
            (base / "calc.py").write_text("def add(a,b):\n    return a-b\n")
            (final / "calc.py").write_text("def add(a,b):\n    return a+b\n")
            (base / "calc.py").chmod(0o644)
            (final / "calc.py").chmod(0o644)
            task = Task(
                "task-1",
                "run-1",
                "workspace-1",
                "repo-1",
                "a" * 40,
                "Fix addition.",
                200,
            )
            source = observe_source(
                base,
                repository_id="repo-1",
                workspace_id="workspace-1",
                source_base_sha="a" * 40,
            )
            observed = BoundedPatchSetPolicy().evaluate(
                base, final, source=source, task=task, worker_session_id="worker-1"
            )
            archive = api.pack_workspace(final, observed)
            self.assertEqual(
                api.workspace_tree_digest(archive), observed.final_tree_sha256
            )
            (final / "calc.py").write_text("def add(a,b):\n    return a*b\n")
            with self.assertRaises(ValueError):
                api.pack_workspace(final, observed)

    def test_test_profile_is_fixed_order_bounded_and_not_model_commands(self):
        api = self.api()
        scripts = (
            ("FAST_TESTS", b"check(True)\n"),
            ("TARGETED_TESTS", b"check(True)\n"),
            ("FINAL_TESTS", b"check(True)\n"),
        )
        counts = (("FAST_TESTS", 1), ("TARGETED_TESTS", 1), ("FINAL_TESTS", 1))
        profile = api.TrustedTestProfile("fixture-profile", scripts, counts)
        self.assertEqual(len(profile.digest), 64)
        for candidate in (tuple(reversed(scripts)), scripts[:2]):
            with self.assertRaises(ValueError):
                api.TrustedTestProfile("fixture-profile", candidate, counts)


if __name__ == "__main__":
    unittest.main()
