"""Finite coordinator behavior; actual kernel E2E is qualified separately."""

import importlib
import shutil
import tempfile
import unittest
from pathlib import Path

from runtime.mission.patchset import observe_source
from runtime.mission.worker import CandidateFile, CandidatePatch, SyntheticWorker, Task


class DirectoryProducer:
    """Test-owned fixture materialization; worker advice never chooses its root."""

    def __init__(self, api, base, root, task, candidates):
        self.api, self.base, self.root, self.task = api, base, root, task
        self.worker = SyntheticWorker(tuple(candidates), clock=lambda: 100)
        self.closed = False

    def produce(self, attempt_number, feedback_code):
        session = self.worker.start(self.task)
        self.worker.poll(session)
        result = self.worker.result(session)
        root = self.root / ("attempt-" + str(attempt_number))
        shutil.copytree(self.base, root)
        for f in result.candidate.files:
            path = root / f.path
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if f.text is None:
                path.unlink()
            else:
                path.write_text(f.text)
                path.chmod(0o644)
        return self.api.CandidateWorkspace(root, session, result)

    def close(self):
        self.closed = True
        self.worker.close()
        return 0


class FaultSession:
    """Specific host-side faults; no test commands or untrusted success parser."""

    def __init__(
        self, api, root, patchset, outcome, *, orphans=0, drift=False, wrong_stage=False
    ):
        self.api, self.root, self.patchset, self.outcome = api, root, patchset, outcome
        self.orphans, self.drift, self.wrong_stage = orphans, drift, wrong_stage
        self.closed = False

    def run(self, stage):
        status = self.outcome if stage == "FAST_TESTS" else "PASS"
        code = 0 if status == "PASS" else 1 if status == "FAIL" else None
        if stage == "FINAL_TESTS" and self.drift:
            (self.root / "calc.py").write_text("def add(a, b):\n    return 777\n")
        actual_stage = "FINAL_TESTS" if self.wrong_stage else stage
        return self.api.ValidationStep(
            actual_stage,
            status,
            code,
            self.patchset.patchset_sha256,
            "b" * 64,
            "c" * 64,
        )

    def close(self):
        self.closed = True
        return self.orphans


class FaultBackend:
    def __init__(self, api, outcomes, **faults):
        self.api, self.outcomes, self.faults = api, list(outcomes), faults
        self.sessions = []

    def open(self, root, patchset):
        outcome = self.outcomes[len(self.sessions)]
        session = FaultSession(self.api, root, patchset, outcome, **self.faults)
        self.sessions.append(session)
        return session


class RepairTests(unittest.TestCase):
    def setUp(self):
        try:
            self.api = importlib.import_module("runtime.mission.repair")
        except ModuleNotFoundError:
            self.fail("Finite Core repair coordinator is not implemented")
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.base = self.root / "base"
        self.base.mkdir(mode=0o700)
        (self.base / "calc.py").write_text("def add(a, b):\n    return a - b\n")
        (self.base / "calc.py").chmod(0o644)
        self.task = Task(
            "task-1", "run-1", "workspace-1", "repo-1", "a" * 40, "Fix addition.", 200
        )
        self.source = observe_source(
            self.base,
            repository_id="repo-1",
            workspace_id="workspace-1",
            source_base_sha="a" * 40,
        )
        self.coordinator = self.api.BoundedRepairLoopCoordinator(clock=lambda: 100)

    def candidate(self, expression):
        return CandidatePatch(
            (
                CandidateFile(
                    "calc.py", "def add(a, b):\n    return " + expression + "\n"
                ),
            )
        )

    def run_loop(self, candidates, outcomes, *, max_repairs=2, **faults):
        producer = DirectoryProducer(
            self.api, self.base, self.root, self.task, candidates
        )
        backend = FaultBackend(self.api, outcomes, **faults)
        result = self.coordinator.run(
            task=self.task,
            source=self.source,
            base_root=self.base,
            producer=producer,
            validator=backend,
            max_repairs=max_repairs,
        )
        return result, producer, backend

    def test_one_failed_attempt_then_repair_reaches_reviewed_patch(self):
        result, producer, backend = self.run_loop(
            [self.candidate("a*b"), self.candidate("a+b")], ["FAIL", "PASS"]
        )
        self.assertEqual(result.status, "PATCH_READY")
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].status, "FAIL")
        self.assertEqual(result.attempts[1].status, "PASS")
        self.assertNotEqual(
            result.attempts[0].patchset_sha256, result.attempts[1].patchset_sha256
        )
        self.assertEqual(result.history[-2:], ("INDEPENDENT_REVIEW", "PATCH_READY"))
        self.assertEqual(result.authority, "NONE")
        self.assertTrue(producer.closed and all(s.closed for s in backend.sessions))

    def test_at_most_two_repairs_then_exhausted_with_three_actual_candidates(self):
        result, producer, backend = self.run_loop(
            [self.candidate("a*b"), self.candidate("a/b"), self.candidate("a//b")],
            ["FAIL"] * 3,
        )
        self.assertEqual(result.status, "EXHAUSTED")
        self.assertEqual(len(list(self.root.glob("attempt-*"))), 3)
        self.assertEqual(len(result.attempts), 3)
        self.assertIsNone(result.final_patchset)
        self.assertTrue(producer.closed and all(s.closed for s in backend.sessions))

    def test_repeated_content_is_denied_even_with_new_session_hash(self):
        result, _, _ = self.run_loop(
            [self.candidate("a*b"), self.candidate("a*b")], ["FAIL", "PASS"]
        )
        self.assertEqual(result.status, "DENIED")
        self.assertEqual(result.failure_code, "REPAIR_CONTENT_NOT_NEW")
        self.assertIsNone(result.final_patchset)

    def test_timeout_crash_unknown_and_cancelled_never_repair_or_pass(self):
        for status in ("TIMEOUT", "CRASH", "UNKNOWN", "CANCELLED"):
            with self.subTest(status=status):
                case = self.root / status
                case.mkdir()
                producer = DirectoryProducer(
                    self.api,
                    self.base,
                    case,
                    self.task,
                    [self.candidate("a*b"), self.candidate("a+b")],
                )
                backend = FaultBackend(self.api, [status, "PASS"])
                result = self.coordinator.run(
                    task=self.task,
                    source=self.source,
                    base_root=self.base,
                    producer=producer,
                    validator=backend,
                )
                self.assertNotEqual(result.status, "PATCH_READY")
                self.assertEqual(len(list(case.glob("attempt-*"))), 1)
                self.assertIsNone(result.final_patchset)
                self.assertTrue(producer.closed and backend.sessions[0].closed)

    def test_cleanup_orphan_overrides_passing_test_claims(self):
        result, _, _ = self.run_loop([self.candidate("a+b")], ["PASS"], orphans=1)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(result.failure_code, "SANDBOX_CLEANUP_FAILED")
        self.assertIsNone(result.final_patchset)

    def test_post_validation_drift_never_survives_final_policy_check(self):
        result, _, _ = self.run_loop([self.candidate("a+b")], ["PASS"], drift=True)
        self.assertNotEqual(result.status, "PATCH_READY")
        self.assertIsNone(result.final_patchset)

    def test_semantic_review_rejects_fixture_constant_even_if_backend_claims_pass(self):
        result, _, _ = self.run_loop([self.candidate("5")], ["PASS"])
        self.assertEqual(result.status, "DENIED")
        self.assertEqual(result.failure_code, "REVIEW_FIXTURE_BYPASS")

    def test_wrong_stage_cannot_be_relabelled_as_passing_fast_test(self):
        result, _, _ = self.run_loop(
            [self.candidate("a+b")], ["PASS"], wrong_stage=True
        )
        self.assertEqual(result.status, "FAILED")
        self.assertIsNone(result.final_patchset)

    def test_policy_denial_prevents_sandbox_open(self):
        candidate = CandidatePatch(
            (CandidateFile("tests/test_calc.py", "assert True\n"),)
        )
        result, _, backend = self.run_loop([candidate], ["PASS"])
        self.assertEqual(result.status, "DENIED")
        self.assertEqual(backend.sessions, [])

    def test_validation_receipt_rejects_false_pass_and_unknown_stage(self):
        for stage, status, exit_code in [
            ("FAST_TESTS", "PASS", 1),
            ("FAST_TESTS", "PASS", True),
            ("CUSTOM_SHELL", "PASS", 0),
            ("FAST_TESTS", "MADE_UP", 0),
        ]:
            with (
                self.subTest(stage=stage, status=status),
                self.assertRaises(ValueError),
            ):
                self.api.ValidationStep(
                    stage, status, exit_code, "a" * 64, "b" * 64, "c" * 64
                )

    def test_repair_limit_cannot_be_increased_or_coerced_from_bool(self):
        for repairs in (True, 3, -1):
            producer = DirectoryProducer(
                self.api, self.base, self.root, self.task, [self.candidate("a+b")]
            )
            with self.subTest(repairs=repairs), self.assertRaises(ValueError):
                self.coordinator.run(
                    task=self.task,
                    source=self.source,
                    base_root=self.base,
                    producer=producer,
                    validator=FaultBackend(self.api, ["PASS"]),
                    max_repairs=repairs,
                )


if __name__ == "__main__":
    unittest.main()
