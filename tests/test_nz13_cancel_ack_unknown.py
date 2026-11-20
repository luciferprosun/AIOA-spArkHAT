"""Cancellation is a request; missing acknowledgement is durable uncertainty."""
import threading
import unittest
from dataclasses import asdict, replace

import test_nz13_worker_unknown as support

from runtime.core_admission import Capability
from runtime.mission import coding_tasks, repair
from runtime.mission.worker import (
    CandidateFile,
    CandidatePatch,
    WorkerMailbox,
    WorkerOutcomeUnknown,
)
from runtime.providers.exact import CancellationToken


class CancellationAckFixture(support.UncertainFixtureWorker):
    def __init__(self, *, cancel=None, missing=False, barrier=False):
        super().__init__()
        self.cancel_token, self.missing, self.barrier = cancel, missing, barrier
        self.cancel_calls = 0
        self.polled, self.release = threading.Event(), threading.Event()

    def start(self, task):
        self.starts += 1
        self.box = WorkerMailbox(task, clock=lambda: 100)
        if self.cancel_token is not None:
            self.cancel_token.cancel()
        return self.box.session

    def poll(self, session):
        self.polled.set()
        if self.barrier and not self.release.wait(3):
            raise AssertionError('fixture release was not acknowledged')
        return self.box.drain(session)

    def cancel(self, session):
        self.cancel_calls += 1
        if self.missing:
            return
        if self.cancel_calls == 1:
            raise OSError('FIXTURE_CANCEL_ACK_LOST')
        # A blind second send would hide the uncertainty of the first one.
        self.box.fail(session, 'CANCELLED')


class BlockingCancellationAckFixture(CancellationAckFixture):
    def __init__(self):
        super().__init__()
        self.entered, self.finish = threading.Event(), threading.Event()
        self.counter_lock = threading.Lock()

    def cancel(self, session):
        with self.counter_lock:
            self.cancel_calls += 1
        self.entered.set()
        if not self.finish.wait(5):
            raise AssertionError('test cancellation ACK was not released')
        self.box.fail(session, 'CANCELLED')


class RepairStartRaceFixture(CancellationAckFixture):
    def __init__(self):
        super().__init__()
        self.boxes, self.cancelled_sessions = {}, []
        self.starting, self.finish_start = threading.Event(), threading.Event()

    def start(self, task):
        self.starts += 1
        self.box = WorkerMailbox(task, clock=lambda: 100)
        self.boxes[self.box.session.session_id] = self.box
        session = self.box.session
        if self.starts == 2:
            self.starting.set()
            if not self.finish_start.wait(5):
                raise AssertionError('test second start was not released')
        return session

    def result(self, session):
        return self.boxes[session.session_id].result(session)

    def cancel(self, session):
        self.cancel_calls += 1
        self.cancelled_sessions.append(session.session_id)
        box = self.boxes[session.session_id]
        if box.result(session) is None:
            box.fail(session, 'OUTCOME_UNKNOWN')


class CancellationAckUnknownTests(unittest.TestCase):
    def setUp(self):
        self.case = support.WorkerUnknownTests('test_uncertain_result_is_inert_unknown_not_failed_or_succeeded')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def run_loop(self, worker, cancel=None, *, timeout=False):
        producer, validator = self.case.run_parts(worker, cancel)
        if timeout:
            ticks = iter((100, 121))
            producer.monotonic = lambda: next(ticks)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.case.task, source=self.case.case.source,
            base_root=self.case.case.base, producer=producer, validator=validator,
            cancelled=(lambda: cancel.cancelled) if cancel is not None else None,
        )
        self.assertEqual(result.status, 'UNKNOWN')
        self.assertEqual(result.failure_code, 'WORKER_OUTCOME_UNKNOWN')
        self.assertIsNone(result.final_patchset)
        self.assertEqual(result.attempts, ())
        self.assertEqual(worker.cancel_calls, 1)
        self.assertTrue(worker.closed)

    def test_lost_stop_ack_is_unknown_even_when_close_returns_zero(self):
        cancel = CancellationToken()
        self.run_loop(CancellationAckFixture(cancel=cancel), cancel)

    def test_lost_timeout_ack_is_unknown_even_when_close_returns_zero(self):
        self.run_loop(CancellationAckFixture(), timeout=True)

    def test_missing_terminal_ack_is_unknown_without_a_second_cancel(self):
        cancel = CancellationToken()
        self.run_loop(CancellationAckFixture(cancel=cancel, missing=True), cancel)

    def test_first_stop_ack_loss_remains_sticky_through_successful_close(self):
        worker = CancellationAckFixture()
        producer, _ = self.case.run_parts(worker)
        producer.session = worker.start(self.case.task)
        try:
            producer.stop()
        except OSError:
            pass  # Observe the existing defect without turning RED into ERROR.
        try:
            producer.close()
        except ValueError as error:
            self.assertIs(type(error), WorkerOutcomeUnknown)
        else:
            self.fail('successful close forgot the earlier cancellation ACK loss')
        self.assertEqual(worker.cancel_calls, 1)

    def test_overlapping_stop_does_not_resend_or_wait_for_transport_io(self):
        worker = BlockingCancellationAckFixture()
        producer, _ = self.case.run_parts(worker)
        producer.session = worker.start(self.case.task)
        errors = []
        completed = threading.Event()

        def stop(*, signal=False):
            try:
                producer.stop()
            except (ValueError, OSError, AssertionError) as error:
                errors.append(type(error).__name__)
            finally:
                if signal:
                    completed.set()

        first = threading.Thread(target=stop)
        second = threading.Thread(target=lambda: stop(signal=True))
        first.start()
        try:
            self.assertTrue(worker.entered.wait(2))
            second.start()
            self.assertTrue(completed.wait(2), 'overlapping STOP waited on transport I/O')
        finally:
            worker.finish.set()
            first.join(3)
            if second.ident is not None:
                second.join(3)
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(worker.cancel_calls, 1)
        with self.assertRaises(WorkerOutcomeUnknown):
            producer.close()

    def test_stop_during_next_repair_start_cannot_consume_a_previous_session_ack(self):
        cancel = CancellationToken()
        worker = RepairStartRaceFixture()
        producer, _ = self.case.run_parts(worker, cancel)
        old = worker.start(self.case.task)
        worker.box.complete(old, CandidatePatch((CandidateFile('src/calc.py', 'x = 0\n'),)))
        producer.session, producer.next_attempt = old, 1
        outcomes = []

        def produce():
            try:
                producer.produce(1, 'TEST_FAIL')
            except (ValueError, RuntimeError, OSError) as error:
                outcomes.append(type(error))

        thread = threading.Thread(target=produce)
        thread.start()
        try:
            self.assertTrue(worker.starting.wait(2))
            producer.stop()
        finally:
            worker.finish_start.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes, [WorkerOutcomeUnknown])
        new = worker.box.session
        self.assertNotEqual(new.session_id, old.session_id)
        self.assertEqual(worker.cancelled_sessions, [new.session_id])
        with self.assertRaises(WorkerOutcomeUnknown):
            producer.close()

    def test_shared_token_cancel_before_start_admission_prevents_dispatch(self):
        cancel = CancellationToken()
        worker = CancellationAckFixture()
        producer, _ = self.case.run_parts(worker, cancel)

        def clock():
            # Deterministic cancellation after the outer stopped check but
            # before the lifecycle's atomic admission of worker.start.
            cancel.cancel()
            return 100

        producer.clock = clock
        with self.assertRaises((ValueError, OSError)) as denied:
            producer.produce(0, None)
        self.assertEqual(worker.starts, 0)
        self.assertEqual(worker.cancel_calls, 0)
        self.assertIs(type(denied.exception), ValueError)
        self.assertEqual(producer.close(), 0)

    def test_core_retains_unknown_after_lost_stop_ack_and_refuses_replay_on_restart(self):
        fx, task = self.case.fx, self.case.task
        workers = []

        def factory(current, cancel):
            self.assertEqual(current, task)
            worker = CancellationAckFixture(barrier=True)
            workers.append(worker)
            producer, validator = self.case.run_parts(worker, cancel)
            return coding_tasks.CodingRun(
                producer, validator, self.case.case.base, self.case.case.source,
                'sha256:' + 'a' * 64, 'target-1', 200,
            )

        def service():
            value = coding_tasks.CoreCodingTasks(
                fx.journal, self.case.case.capsules, run_factory=factory,
                run_principal=fx.p(), clock=lambda: 100,
            )
            self.addCleanup(value.close)
            return value

        one = service()
        manager, reader = fx.p(Capability.MANAGE), fx.p(Capability.READ)
        one.request(manager, 'create_task', {'task': asdict(task)})
        one.request(manager, 'start', {'task_id': task.task_id})
        deadline = threading.Event()
        for _ in range(300):
            if workers:
                break
            deadline.wait(0.01)
        self.assertEqual(len(workers), 1)
        worker = workers[0]
        self.addCleanup(worker.release.set)
        self.assertTrue(worker.polled.wait(2))
        try:
            one.request(manager, 'stop', {'task_id': task.task_id})
        except OSError:
            pass  # The result state must expose uncertainty, even after lost ACK.
        finally:
            worker.release.set()
        self.assertTrue(one.wait(task.task_id, 3))
        before = one.request(reader, 'read_status', {'task_id': task.task_id})
        self.assertEqual(before['state'], 'UNKNOWN')
        self.assertFalse(before['effect_verified'])
        self.assertEqual(worker.cancel_calls, 1)
        one.close()
        two = service()
        self.assertEqual(two.request(reader, 'read_status', {'task_id': task.task_id}), before)
        other = replace(task, task_id='after-lost-ack', run_id='after-lost-ack-run')
        two.request(manager, 'create_task', {'task': asdict(other)})
        with self.assertRaises(ValueError):
            two.request(manager, 'start', {'task_id': other.task_id})
        self.assertEqual(len(workers), 1)
        self.assertEqual(worker.cancel_calls, 1)


if __name__ == '__main__':
    unittest.main()
