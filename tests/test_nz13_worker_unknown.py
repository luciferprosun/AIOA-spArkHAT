"""A lost worker outcome is durable uncertainty, never permission to resend.

Prepared outside the frozen checkout. All records and keys are fixture-only.
"""
import unittest
from dataclasses import asdict, replace
from unittest.mock import patch

import test_nz11_git_join as support

from runtime.core_admission import Capability
from runtime.mission import coding_tasks, repair
from runtime.mission.repair_validation import (
    CoreRepositoryMaterializer,
    CoreSandboxValidation,
)
from runtime.mission.worker import (
    CandidateFile,
    CandidatePatch,
    WorkerFailure,
    WorkerMailbox,
)
from runtime.providers.exact import CancellationToken


class UncertainFixtureWorker:
    """Transport-free fixture; one request has an explicitly unknown outcome."""

    def __init__(self, *, wrong_run=False, close_failure=False):
        self.box = None
        self.starts = 0
        self.closed = False
        self.wrong_run = wrong_run
        self.close_failure = close_failure

    def start(self, task):
        self.starts += 1
        self.box = WorkerMailbox(task, clock=lambda: 100)
        self.box.fail(self.box.session, 'OUTCOME_UNKNOWN')
        return self.box.session

    def poll(self, session):
        return self.box.drain(session)

    def result(self, session):
        result = self.box.result(session)
        return replace(result, run_id='other-run') if self.wrong_run else result

    def cancel(self, session):
        self.box.fail(session, 'CANCELLED')

    def interrupt(self, session):
        self.box.fail(session, 'INTERRUPTED')

    def close(self):
        self.closed = True
        if self.close_failure:
            raise OSError('fixture cleanup ACK unavailable')
        return 0


class CancelUncertainFixtureWorker(UncertainFixtureWorker):
    def __init__(self, cancel=None):
        super().__init__()
        self.cancel_token = cancel

    def start(self, task):
        self.starts += 1
        self.box = WorkerMailbox(task, clock=lambda: 100)
        if self.cancel_token is not None:
            self.cancel_token.cancel()
        return self.box.session

    def cancel(self, session):
        self.box.fail(session, 'OUTCOME_UNKNOWN')


class WorkerUnknownTests(unittest.TestCase):
    def setUp(self):
        self.case = support.GitJoinTests('test_inert_preparation_cannot_substitute_for_canonical_capsule')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = self.case.fx
        self.task = self.case.task
        self.profile = self.case.case.profile()

    def require_unknown(self):
        session = WorkerMailbox(self.task, clock=lambda: 100).session
        try:
            failure = WorkerFailure(session.session_id, session.task_id, session.run_id, 'OUTCOME_UNKNOWN')
        except ValueError:
            self.fail('WorkerFailure cannot express an uncertain provider outcome')
        self.assertEqual(failure.status, 'UNKNOWN')
        self.assertEqual(failure.authority, 'NONE')

    def run_parts(self, worker, cancel=None):
        materializer = CoreRepositoryMaterializer(
            self.fx.journal, lambda *_: self.fail('UNKNOWN must not dispatch materialization'),
            profile=self.profile, source_snapshot=self.case.snapshot,
            source_repository=self.case.case.repo.path, base_root=self.case.base,
            output_root=self.case.case.root / 'mirrors', cancel=cancel,
        )
        producer = repair.SandboxedCandidateProducer(
            self.task, worker, materializer, cancel=cancel, clock=lambda: 100,
        )
        validator = CoreSandboxValidation(
            self.fx.journal, lambda *_: self.fail('UNKNOWN must not dispatch validation'),
            profile=self.profile, cancel=cancel,
        )
        return producer, validator

    def test_uncertain_result_is_inert_unknown_not_failed_or_succeeded(self):
        self.require_unknown()

    def test_mailbox_uncertainty_survives_stop_close_and_late_candidate(self):
        self.require_unknown()
        box = WorkerMailbox(self.task, clock=lambda: 100)
        box.fail(box.session, 'OUTCOME_UNKNOWN')
        original = box.result(box.session)
        for code in ('CANCELLED', 'INTERRUPTED', 'CLOSED'):
            box.fail(box.session, code)
            self.assertIs(box.result(box.session), original)
        candidate = CandidatePatch((CandidateFile('src/calc.py', 'x = 1\n'),))
        self.assertIs(box.complete(box.session, candidate), original)
        self.assertEqual([event.kind for event in box.drain(box.session)], ['STARTED'])

    def test_real_producer_and_coordinator_stop_before_materialization_without_retry(self):
        self.require_unknown()
        worker = UncertainFixtureWorker()
        producer, validator = self.run_parts(worker)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.case.source, base_root=self.case.base,
            producer=producer, validator=validator, max_repairs=2,
        )
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(result.failure_code, 'WORKER_OUTCOME_UNKNOWN')
        self.assertIsNone(result.final_patchset)
        self.assertEqual(result.attempts, ())
        self.assertEqual(worker.starts, 1)
        self.assertTrue(worker.closed)
        self.assertEqual(producer.next_attempt, 1)

    def test_wrong_session_unknown_cannot_change_the_admitted_task_outcome(self):
        self.require_unknown()
        worker = UncertainFixtureWorker(wrong_run=True)
        producer, validator = self.run_parts(worker)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.case.source, base_root=self.case.base,
            producer=producer, validator=validator,
        )
        self.assertEqual(result.status, 'FAILED')
        self.assertEqual(result.failure_code, 'WORKER_PRODUCER_FAILED')
        self.assertEqual(worker.starts, 1)

    def test_cleanup_ack_loss_does_not_downgrade_an_unknown_outcome_to_failed(self):
        self.require_unknown()
        worker = UncertainFixtureWorker(close_failure=True)
        producer, validator = self.run_parts(worker)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.case.source, base_root=self.case.base,
            producer=producer, validator=validator,
        )
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(result.failure_code, 'WORKER_CLEANUP_FAILED')
        self.assertEqual(worker.starts, 1)

    def test_stop_during_dispatch_preserves_the_bound_unknown_cancellation_ack(self):
        self.require_unknown()
        cancel = CancellationToken()
        worker = CancelUncertainFixtureWorker(cancel)
        producer, validator = self.run_parts(worker, cancel)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.case.source, base_root=self.case.base,
            producer=producer, validator=validator, cancelled=lambda: cancel.cancelled,
        )
        self.assertTrue(cancel.cancelled)
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(result.failure_code, 'WORKER_OUTCOME_UNKNOWN')
        self.assertEqual(worker.starts, 1)
        self.assertIsNone(result.final_patchset)

    def test_poll_timeout_preserves_the_bound_unknown_cancellation_ack(self):
        self.require_unknown()
        worker = CancelUncertainFixtureWorker()
        producer, validator = self.run_parts(worker)
        ticks = iter((100, 121))
        producer.monotonic = lambda: next(ticks)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.case.source, base_root=self.case.base,
            producer=producer, validator=validator,
        )
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(result.failure_code, 'WORKER_OUTCOME_UNKNOWN')
        self.assertEqual(worker.starts, 1)
        self.assertIsNone(result.final_patchset)

    def test_controller_signed_unknown_survives_restart_and_refuses_another_run(self):
        self.require_unknown()
        workers = []

        def factory(task, cancel):
            self.assertEqual(task, self.task)
            worker = UncertainFixtureWorker()
            workers.append(worker)
            producer, validator = self.run_parts(worker, cancel)
            return coding_tasks.CodingRun(
                producer, validator, self.case.base, self.case.source,
                'sha256:' + 'a' * 64, 'target-1', 200,
            )

        def service():
            result = coding_tasks.CoreCodingTasks(
                self.fx.journal, self.case.capsules, run_factory=factory,
                run_principal=self.fx.p(), clock=lambda: 100,
            )
            self.addCleanup(result.close)
            return result

        one = service()
        manager, reader = self.fx.p(Capability.MANAGE), self.fx.p(Capability.READ)
        one.request(manager, 'create_task', {'task': asdict(self.task)})
        with patch.object(CoreRepositoryMaterializer, 'materialize', side_effect=AssertionError('no materialization')) as materialize:
            one.request(manager, 'start', {'task_id': self.task.task_id})
            self.assertTrue(one.wait(self.task.task_id, 3))
            materialize.assert_not_called()
        before = one.request(reader, 'read_status', {'task_id': self.task.task_id})
        self.assertEqual(before['state'], 'UNKNOWN')
        self.assertIsNone(before['capsule_digest'])
        self.assertFalse(before['effect_verified'])
        self.assertFalse(before['effects_registered'])
        one.request(manager, 'stop', {'task_id': self.task.task_id})
        self.assertEqual(one.request(reader, 'read_status', {'task_id': self.task.task_id})['state'], 'UNKNOWN')
        one.close()
        two = service()
        self.assertEqual(two.request(reader, 'read_status', {'task_id': self.task.task_id}), before)
        other = replace(self.task, task_id='next-task', run_id='next-run')
        two.request(manager, 'create_task', {'task': asdict(other)})
        with self.assertRaises(ValueError):
            two.request(manager, 'start', {'task_id': other.task_id})
        self.assertEqual(len(workers), 1)
        self.assertEqual(workers[0].starts, 1)


if __name__ == '__main__':
    unittest.main()
