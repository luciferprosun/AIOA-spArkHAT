"""Independent review counterexamples become desired fail-closed regressions."""

import unittest
from dataclasses import replace
from unittest.mock import patch

import test_nz11_controller as support

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.repair_validation import CoreRepositoryMaterializer
from runtime.mission.worker import SyntheticWorker


class ReviewControllerTests(unittest.TestCase):
    def setUp(self):
        self.case = support.ControllerTests(
            "test_two_active_runs_cancel_independently_without_worker_or_core_replay"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx, self.task = self.case.fx, self.case.case.task

    def fill_history(self):
        def fill(tx):
            for number in range(1024):
                tx.insert(
                    StoredRecord(
                        RecordKind.OPERATION,
                        "000-review-filler-" + str(number).zfill(4),
                        self.fx.ledger.scope,
                        1,
                        {"schema": "review.inert.v1"},
                    )
                )

        self.fx.journal._run(self.fx.p(), Capability.COMMIT, fill)

    def next_task(self, suffix):
        return replace(self.task, task_id="next-" + suffix, run_id="next-run-" + suffix)

    def test_materialization_failure_after_start_is_unknown_and_quarantined(self):
        service = self.case.service()
        original = service.run_factory

        def factory(task, token):
            run = original(task, token)
            run.producer.worker = SyntheticWorker(
                (self.case.case.candidate,), clock=lambda: 100
            )
            return run

        def lost_materialization(_materializer, *args):
            self.fx.init()
            self.fx.start()
            raise ValueError("VALIDATION_UNRESOLVED")

        service.run_factory = factory
        self.case.admit(service, self.task)
        with patch.object(
            CoreRepositoryMaterializer, "materialize", lost_materialization
        ):
            service.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": self.task.task_id}
            )
            self.assertTrue(service.wait(self.task.task_id, 5))
        self.assertEqual(self.fx.inspect()["outcome"]["contract_type"], "Unknown")
        view = service.request(
            self.fx.p(Capability.READ), "read_status", {"task_id": self.task.task_id}
        )
        self.assertEqual(view["state"], "UNKNOWN")
        self.assertTrue(service._active[self.task.task_id]["quarantined"])
        for controller in (service, self.case.service()):
            following = self.next_task("after-materialization")
            self.case.admit(controller, following)
            with self.assertRaises(ValueError):
                controller.request(
                    self.fx.p(Capability.MANAGE),
                    "start",
                    {"task_id": following.task_id},
                )
            self.assertNotIn(following.task_id, self.case.workers)

    def test_clean_failure_before_start_remains_failed_and_releases_capacity(self):
        service = self.case.service()
        original = service.run_factory

        def factory(task, token):
            run = original(task, token)
            run.producer.worker = SyntheticWorker(
                (self.case.case.candidate,), clock=lambda: 100
            )
            return run

        service.run_factory = factory
        self.case.admit(service, self.task)
        with patch.object(
            CoreRepositoryMaterializer,
            "materialize",
            side_effect=ValueError("SOURCE_REF_DRIFT"),
        ):
            service.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": self.task.task_id}
            )
            self.assertTrue(service.wait(self.task.task_id, 5))
        self.assertEqual(
            service.request(
                self.fx.p(Capability.READ),
                "read_status",
                {"task_id": self.task.task_id},
            )["state"],
            "FAILED",
        )
        self.assertNotIn(self.task.task_id, service._active)
        service.run_factory = original
        following = self.next_task("clean-failure")
        self.case.admit(service, following)
        service.request(
            self.fx.p(Capability.MANAGE), "start", {"task_id": following.task_id}
        )
        self.case.wait_started(following)
        service.request(
            self.fx.p(Capability.MANAGE), "stop", {"task_id": following.task_id}
        )
        self.assertTrue(service.wait(following.task_id, 5))

    def test_unresolved_core_intent_blocks_admission_without_an_unknown_task(self):
        self.fx.init()
        self.fx.start()
        service = self.case.service()
        self.case.admit(service, self.task)
        with self.assertRaisesRegex(ValueError, "CODING_UNRESOLVED_INTENT"):
            service.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": self.task.task_id}
            )
        self.assertFalse(self.case.workers)

    def test_history_prefix_cannot_hide_unknown_across_restart(self):
        self._assert_history_denial("UNKNOWN")

    def test_history_prefix_cannot_hide_active_claim_across_restart(self):
        self._assert_history_denial("RUNNING")

    def _assert_history_denial(self, state):
        service = self.case.service()
        self.case.admit(service, self.task)
        service._transition(self.fx.p(), self.task.task_id, ("QUEUED",), state)
        self.fill_history()
        restarted = self.case.service()
        following = self.next_task("history-" + state.lower())
        self.case.admit(restarted, following)
        with self.assertRaisesRegex(ValueError, "CODING_HISTORY_LIMIT"):
            restarted.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": following.task_id}
            )
        self.assertFalse(self.case.workers)

    def test_cancellation_cannot_assume_a_truncated_intent_scan_is_complete(self):
        service = self.case.service()
        self.case.admit(service, self.task)
        service.request(
            self.fx.p(Capability.MANAGE), "start", {"task_id": self.task.task_id}
        )
        self.case.wait_started(self.task)
        self.fx.init()
        self.fx.start()
        self.fill_history()
        service.request(
            self.fx.p(Capability.MANAGE), "stop", {"task_id": self.task.task_id}
        )
        self.assertTrue(service.wait(self.task.task_id, 5))
        self.assertEqual(
            service.request(
                self.fx.p(Capability.READ),
                "read_status",
                {"task_id": self.task.task_id},
            )["state"],
            "UNKNOWN",
        )
        self.assertTrue(service._active[self.task.task_id]["quarantined"])


if __name__ == "__main__":
    unittest.main()
