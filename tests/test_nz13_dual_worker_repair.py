"""Compare the two fixture adapters through the existing bounded repair loop."""

import unittest

import test_hybrid_repair as fixtures
from nz13_worker_acceptance import WireFixtureWorker
from runtime.mission.repair import TEST_STAGES
from runtime.mission.worker import SyntheticWorker


class DualWorkerRepairTests(unittest.TestCase):
    def test_in_process_and_wire_adapters_share_repair_and_review_boundaries(self):
        surfaces = (
            ("synthetic", SyntheticWorker),
            ("candidate-message", WireFixtureWorker),
        )
        observed = []
        for name, worker_factory in surfaces:
            with self.subTest(adapter=name):
                case = fixtures.RepairTests("test_one_failed_attempt_then_repair_reaches_reviewed_patch")
                case.setUp()
                self.addCleanup(case.doCleanups)
                original = (case.base / "calc.py").read_bytes()
                advice = (case.candidate("a*b"), case.candidate("a+b"))
                producer = fixtures.DirectoryProducer(case.api, case.base, case.root, case.task, ())
                producer.worker.close()
                producer.worker = worker_factory(advice, clock=lambda: 100)
                validator = fixtures.FaultBackend(case.api, ("FAIL", "PASS"))
                result = case.coordinator.run(
                    task=case.task,
                    source=case.source,
                    base_root=case.base,
                    producer=producer,
                    validator=validator,
                    max_repairs=1,
                )

                self.assertEqual(result.status, "PATCH_READY")
                self.assertEqual(result.authority, "NONE")
                self.assertEqual([attempt.status for attempt in result.attempts], ["FAIL", "PASS"])
                self.assertEqual(
                    tuple(step.stage for step in result.attempts[-1].steps), TEST_STAGES
                )
                self.assertEqual(result.history[-2:], ("INDEPENDENT_REVIEW", "PATCH_READY"))
                self.assertTrue(producer.closed)
                self.assertTrue(all(session.closed for session in validator.sessions))
                self.assertEqual((case.base / "calc.py").read_bytes(), original)
                if name == "candidate-message":
                    self.assertEqual(producer.worker.messages, 2)
                patchset = result.final_patchset
                self.assertEqual(patchset.worker_session_id, result.attempts[-1].worker_session_id)
                observed.append((result.history, patchset.final_tree_sha256, patchset.patchset_sha256))

        self.assertEqual(len(observed), 2)
        self.assertEqual(observed[0][:2], observed[1][:2])
        self.assertNotEqual(observed[0][2], observed[1][2])
