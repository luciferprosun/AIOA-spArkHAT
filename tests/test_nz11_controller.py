"""Two admitted runs cancel independently, with durable no-replay recovery."""

import threading
import time
import unittest
from dataclasses import asdict, replace

import test_nz11_git_join as support

from runtime.core_admission import Capability
from runtime.mission import coding_tasks, repair
from runtime.mission.repair_validation import (
    CoreRepositoryMaterializer,
    CoreSandboxValidation,
)
from runtime.mission.worker import WorkerMailbox


class WaitingWorker:
    def __init__(self):
        self.started = threading.Event()
        self.closed = False
        self.box = None
        self.cancels = 0

    def start(self, task):
        self.box = WorkerMailbox(task, clock=lambda: 100)
        self.started.set()
        return self.box.session

    def poll(self, session):
        return self.box.drain(session)

    def result(self, session):
        return self.box.result(session)

    def cancel(self, session):
        self.cancels += 1
        self.box.fail(session, "CANCELLED")

    def interrupt(self, session):
        self.box.fail(session, "INTERRUPTED")

    def close(self):
        self.closed = True
        if self.box:
            self.box.fail(self.box.session, "CLOSED")


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.case = support.GitJoinTests(
            "test_inert_preparation_cannot_substitute_for_canonical_capsule"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = self.case.fx
        self.workers = {}
        self.tokens = {}

    def service(self, **kw):
        run_type = getattr(coding_tasks, "CodingRun", None)
        self.assertTrue(callable(run_type), "the bounded coding controller is missing")
        profile = self.case.case.profile()

        def factory(task, cancel):
            worker = WaitingWorker()
            self.workers[task.task_id] = worker
            self.tokens[task.task_id] = cancel
            materializer = CoreRepositoryMaterializer(
                self.fx.journal,
                lambda *_: None,
                profile=profile,
                source_snapshot=self.case.snapshot,
                source_repository=self.case.case.repo.path,
                base_root=self.case.base,
                output_root=self.case.case.root / "mirrors",
                cancel=cancel,
            )
            producer = repair.SandboxedCandidateProducer(
                task, worker, materializer, cancel=cancel, clock=lambda: 100
            )
            validator = CoreSandboxValidation(
                self.fx.journal, lambda *_: (), profile=profile, cancel=cancel
            )
            return run_type(
                producer,
                validator,
                self.case.base,
                self.case.source,
                "sha256:" + "a" * 64,
                "target-1",
                200,
            )

        service = coding_tasks.CoreCodingTasks(
            self.fx.journal,
            self.case.capsules,
            run_factory=factory,
            run_principal=self.fx.p(),
            clock=lambda: 100,
            **kw,
        )
        self.addCleanup(service.close)
        return service

    def admit(self, service, task):
        return service.request(
            self.fx.p(Capability.MANAGE), "create_task", {"task": asdict(task)}
        )

    def wait_started(self, task):
        deadline = time.monotonic() + 2
        while task.task_id not in self.workers and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIn(task.task_id, self.workers)
        self.assertTrue(self.workers[task.task_id].started.wait(2))

    def test_two_active_runs_cancel_independently_without_worker_or_core_replay(self):
        service = self.service()
        one = self.case.task
        two = replace(one, task_id="second-task", run_id="second-run")
        for task in (one, two):
            self.admit(service, task)
            service.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": task.task_id}
            )
            self.wait_started(task)
        duplicate = service.request(
            self.fx.p(Capability.MANAGE), "start", {"task_id": one.task_id}
        )
        self.assertEqual(duplicate["state"], "RUNNING")
        self.assertEqual(len(self.workers), 2)
        service.request(self.fx.p(Capability.MANAGE), "stop", {"task_id": one.task_id})
        self.assertTrue(service.wait(one.task_id, 3))
        self.assertTrue(self.tokens[one.task_id].cancelled)
        self.assertFalse(self.tokens[two.task_id].cancelled)
        self.assertEqual(
            service.request(
                self.fx.p(Capability.READ), "read_status", {"task_id": one.task_id}
            )["state"],
            "CANCELLED",
        )
        self.assertFalse(self.workers[two.task_id].closed)
        service.request(
            self.fx.p(Capability.MANAGE), "cancel", {"task_id": two.task_id}
        )
        self.assertTrue(service.wait(two.task_id, 3))
        for task in (one, two):
            self.assertTrue(self.workers[task.task_id].closed)
            self.assertGreater(self.workers[task.task_id].cancels, 0)
            before = len(self.workers)
            with self.assertRaises(ValueError):
                service.request(
                    self.fx.p(Capability.MANAGE), "start", {"task_id": task.task_id}
                )
            self.assertEqual(len(self.workers), before)

    def test_restart_cannot_start_another_task_before_active_run_recovery(self):
        service = self.service()
        task = self.case.task
        self.admit(service, task)
        service._transition(self.fx.p(), task.task_id, ("QUEUED",), "RUNNING")
        second = replace(task, task_id="new-after-crash", run_id="new-after-crash-run")
        restarted = self.service()
        self.admit(restarted, second)
        with self.assertRaises(ValueError):
            restarted.request(
                self.fx.p(Capability.MANAGE), "start", {"task_id": second.task_id}
            )
        self.assertFalse(self.workers)

    def test_restart_marks_running_unknown_and_never_restarts_worker(self):
        service = self.service()
        self.admit(service, self.case.task)
        # Exact claimed state, before an external worker could be spawned.
        service._transition(self.fx.p(), self.case.task.task_id, ("QUEUED",), "RUNNING")
        restarted = self.service()
        with self.assertRaises(ValueError):
            restarted.request(
                self.fx.p(Capability.MANAGE),
                "start",
                {"task_id": self.case.task.task_id},
            )
        self.assertFalse(self.workers)
        view = restarted.request(
            self.fx.p(Capability.MANAGE), "recover", {"task_id": self.case.task.task_id}
        )
        self.assertEqual(view["state"], "UNKNOWN")
        self.assertFalse(self.workers)
        with self.assertRaises(ValueError):
            restarted.request(
                self.fx.p(Capability.MANAGE),
                "start",
                {"task_id": self.case.task.task_id},
            )

    def test_run_cannot_mix_materialization_and_test_profiles(self):
        from runtime.providers.exact import CancellationToken

        service = self.service()
        run = service.run_factory(self.case.task, CancellationToken())
        first = run.validator.profile.stages[0][1][0]
        different = replace(
            run.validator.profile,
            stages=tuple(
                (
                    stage,
                    tuple(
                        replace(case, expected_json=b"null")
                        if case.case_id == first.case_id
                        else case
                        for case in cases
                    ),
                )
                for stage, cases in run.validator.profile.stages
            ),
        )
        validator = CoreSandboxValidation(
            self.fx.journal,
            lambda *_: (),
            profile=different,
            cancel=run.producer.cancel_token,
        )
        with self.assertRaises(ValueError):
            replace(run, validator=validator)

    def test_cleanup_failure_retains_unknown_and_blocks_new_runs_including_restart(
        self,
    ):
        service = self.service()
        task = self.case.task
        self.admit(service, task)
        service.request(
            self.fx.p(Capability.MANAGE), "start", {"task_id": task.task_id}
        )
        self.wait_started(task)

        def broken_close():
            raise OSError("CONTROLLED_WORKER_CLEANUP_FAILURE")

        self.workers[task.task_id].close = broken_close
        service.request(self.fx.p(Capability.MANAGE), "stop", {"task_id": task.task_id})
        self.assertTrue(service.wait(task.task_id, 5))
        view = service.request(
            self.fx.p(Capability.READ), "get_receipts", {"task_id": task.task_id}
        )
        self.assertEqual(view["state"], "UNKNOWN")
        self.assertEqual(view["run_result"]["failure_code"], "WORKER_CLEANUP_FAILED")
        self.assertFalse(self.workers[task.task_id].closed)
        self.assertIn(
            task.task_id, service._active, "uncertain owned worker handle was discarded"
        )
        next_task = replace(task, task_id="after-unknown", run_id="after-unknown-run")
        self.admit(service, next_task)
        for controller in (service, self.service()):
            with self.assertRaises(ValueError):
                controller.request(
                    self.fx.p(Capability.MANAGE),
                    "start",
                    {"task_id": next_task.task_id},
                )
        self.assertNotIn(next_task.task_id, self.workers)

    def test_cancel_does_not_hide_an_existing_unknown_core_intent(self):
        service = self.service()
        self.fx.init()
        self.fx.start()
        self.admit(service, self.case.task)
        service.request(
            self.fx.p(Capability.MANAGE), "start", {"task_id": self.case.task.task_id}
        )
        self.wait_started(self.case.task)
        service.request(
            self.fx.p(Capability.MANAGE), "stop", {"task_id": self.case.task.task_id}
        )
        self.assertTrue(service.wait(self.case.task.task_id, 3))
        view = service.request(
            self.fx.p(Capability.READ),
            "read_status",
            {"task_id": self.case.task.task_id},
        )
        self.assertEqual(view["state"], "UNKNOWN")
        self.assertFalse(view.get("effect_verified", False))

    def test_model_control_fields_and_wrong_capability_cannot_start_or_approve(self):
        service = self.service()
        self.admit(service, self.case.task)
        for payload in (
            {"task_id": self.case.task.task_id, "approved": True},
            {"task_id": self.case.task.task_id, "shell": "id"},
        ):
            with self.assertRaises(ValueError):
                service.request(self.fx.p(Capability.MANAGE), "start", payload)
        with self.assertRaises(ValueError):
            service.request(
                self.fx.p(Capability.READ), "start", {"task_id": self.case.task.task_id}
            )
        with self.assertRaises(ValueError):
            service.request(
                self.fx.p(Capability.MANAGE),
                "approve",
                {
                    "task_id": self.case.task.task_id,
                    "capsule_digest": "0" * 64,
                    "operation_digest": "0" * 64,
                },
            )
        self.assertFalse(self.workers)


if __name__ == "__main__":
    unittest.main()
