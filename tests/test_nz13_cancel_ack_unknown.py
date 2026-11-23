"""Cancellation is a request; missing acknowledgement is durable uncertainty."""
import threading
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec

import q09_support
import test_nz11_general_recipe as recipe_support
import test_nz13_worker_unknown as support

from runtime.core_admission import Capability
from runtime.mission import coding_tasks, repair
from runtime.mission.git_publish import GitSourceSnapshot
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.patchset import SourceIdentity
from runtime.mission.repair_validation import (
    CoreRepositoryMaterializer,
    CoreSandboxValidation,
)
from runtime.mission.worker import (
    CandidateFile,
    CandidatePatch,
    SyntheticWorker,
    Task,
    WorkerError,
    WorkerFailure,
    WorkerMailbox,
    WorkerOutcomeUnknown,
)
from runtime.mobile_gateway.wire import Identity
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


class StartAckLostFixture(CancellationAckFixture):
    def start(self, task):
        super().start(task)
        raise OSError('FIXTURE_START_ACK_LOST')


class ReadbackAckLostFixture(CancellationAckFixture):
    def __init__(self, method, *, stop_on_failure=None, error=OSError):
        super().__init__()
        self.method, self.stop_on_failure, self.error = method, stop_on_failure, error
        self.polls, self.results = 0, 0

    def _lose_ack(self):
        if self.stop_on_failure is not None:
            self.stop_on_failure.cancel()
        raise self.error('FIXTURE_READBACK_ACK_LOST')

    def poll(self, session):
        self.polls += 1
        events = super().poll(session)
        if self.method == 'poll':
            self._lose_ack()
        return events

    def result(self, session):
        self.results += 1
        if self.method == 'result':
            self._lose_ack()
        return super().result(session)


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


class StartAckUnknownTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = q09_support.Fixture(self.root / 'core.json')
        self.addCleanup(self.fixture.close)
        recipe = recipe_support.GeneralRecipeTests()
        recipe.setUp()
        self.addCleanup(recipe.doCleanups)
        self.profile = recipe.profile()
        self.snapshot = GitSourceSnapshot(
            self.profile.repository_id, 'workspace-1', self.profile.source_base_sha,
            'b' * 40, (('src/textutil.py', b'def slug(value): return value\n'),),
        )
        self.source = SourceIdentity(
            self.profile.repository_id, 'workspace-1', self.profile.source_base_sha,
            self.snapshot.export_tree_sha256,
        )
        self.task = Task(
            'test-start-ack', 'start-ack-run', self.source.workspace_id,
            self.source.repository_id, self.source.source_base_sha, 'Normalize text.', 200,
        )

    def producer(self, worker, cancel=None):
        materializer = CoreRepositoryMaterializer(
            self.fixture.journal, self.fail, profile=self.profile, source_snapshot=self.snapshot,
            source_repository=self.root / 'git-fixture', base_root=self.root,
            output_root=self.root / 'output', cancel=cancel,
        )
        return repair.SandboxedCandidateProducer(
            self.task, worker, materializer, cancel=cancel, clock=lambda: 100,
        )

    def run_loop(self, worker, cancel=None):
        producer = self.producer(worker, cancel)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.source, base_root=self.root, producer=producer,
            validator=None, cancelled=(lambda: cancel.cancelled) if cancel is not None else None,
        )
        self.assertEqual((result.status, result.failure_code), ('UNKNOWN', 'WORKER_OUTCOME_UNKNOWN'))
        self.assertIsNone(result.final_patchset)
        self.assertEqual(result.attempts, ())
        self.assertEqual(worker.cancel_calls, 0)
        self.assertTrue(worker.closed)
        self.assertFalse((self.root / 'output').exists())
        with self.assertRaises(WorkerOutcomeUnknown):
            producer.produce(1, 'TEST_FAIL')

    def test_lost_start_ack_is_unknown_with_or_without_stop(self):
        for stopped in (False, True):
            with self.subTest(stopped=stopped):
                cancel = CancellationToken()
                worker = StartAckLostFixture(cancel=cancel if stopped else None)
                self.run_loop(worker, cancel)
                self.assertEqual(worker.starts, 1)

    def test_mismatched_start_ack_is_unknown_and_cannot_be_cancelled(self):
        class UnboundStart(CancellationAckFixture):
            def start(self, task):
                session = super().start(task)
                return replace(session, run_id='unbound-run')

        worker = UnboundStart()
        self.run_loop(worker)
        self.assertEqual(worker.starts, 1)

    def test_lost_poll_or_result_ack_remains_unknown_with_or_without_stop(self):
        for method in ('poll', 'result'):
            for stopped in (False, True):
                with self.subTest(method=method, stopped=stopped):
                    cancel = CancellationToken()
                    worker = ReadbackAckLostFixture(
                        method, stop_on_failure=cancel if stopped else None,
                        error=OSError if method == 'poll' else EOFError,
                    )
                    self.run_loop(worker, cancel)
                    self.assertEqual((worker.starts, worker.polls, worker.results),
                                     (1, 1, int(method == 'result')))

    def test_explicit_readback_denial_preserves_known_failure(self):
        for method in ('poll', 'result'):
            with self.subTest(method=method):
                worker = ReadbackAckLostFixture(method, error=WorkerError)
                producer = self.producer(worker)
                with self.assertRaisesRegex(WorkerError, '^FIXTURE_READBACK_ACK_LOST$') as denial:
                    producer.produce(0, None)
                self.assertIs(type(denial.exception), WorkerError)
                self.assertEqual(producer.close(), 0)
                self.assertEqual((worker.starts, worker.cancel_calls), (1, 0))

    def test_bound_candidate_still_reaches_materialization(self):
        candidate = CandidatePatch((
            CandidateFile('src/textutil.py', 'def slug(value): return value.strip()\n'),
        ))
        worker = SyntheticWorker((candidate,), clock=lambda: 100)
        producer = self.producer(worker)
        with patch.object(CoreRepositoryMaterializer, 'materialize', return_value=self.root) as materialize:
            result = producer.produce(0, None)
        self.assertEqual(result.worker_result.candidate, candidate)
        materialize.assert_called_once_with(self.task, result.session, candidate)
        self.assertEqual(producer.close(), 0)

    def test_terminal_readback_preserves_binding_and_status(self):
        class TerminalReadback(CancellationAckFixture):
            def __init__(self, bound, code):
                super().__init__()
                self.bound, self.code = bound, code

            def result(self, session):
                return WorkerFailure(
                    session.session_id, session.task_id,
                    session.run_id if self.bound else 'wrong-run', self.code,
                )

        for bound, code, expected in (
            (True, 'WORKER_CRASH', ('FAILED', 'WORKER_PRODUCER_FAILED')),
            (True, 'OUTCOME_UNKNOWN', ('UNKNOWN', 'WORKER_OUTCOME_UNKNOWN')),
            (False, 'OUTCOME_UNKNOWN', ('FAILED', 'WORKER_PRODUCER_FAILED')),
        ):
            with self.subTest(bound=bound, code=code):
                worker = TerminalReadback(bound, code)
                result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
                    task=self.task, source=self.source, base_root=self.root,
                    producer=self.producer(worker), validator=None,
                )
                self.assertEqual((result.status, result.failure_code), expected)
                self.assertIsNone(result.final_patchset)
                self.assertEqual(worker.starts, 1)

    def test_acknowledged_stop_stays_cancelled(self):
        class AcknowledgedStop(CancellationAckFixture):
            def cancel(self, session):
                self.cancel_calls += 1
                self.box.fail(session, 'CANCELLED')

        cancel = CancellationToken()
        worker = AcknowledgedStop(cancel=cancel)
        result = repair.BoundedRepairLoopCoordinator(clock=lambda: 100).run(
            task=self.task, source=self.source, base_root=self.root, producer=self.producer(worker, cancel),
            validator=None, cancelled=lambda: cancel.cancelled,
        )
        self.assertEqual((result.status, result.failure_code), ('CANCELLED', 'CANCELLED'))
        self.assertEqual((worker.starts, worker.cancel_calls, worker.closed), (1, 1, True))

    def assert_reopen_denies_dispatch(self, worker):
        signer = Identity(ec.generate_private_key(ec.SECP256R1()))

        def run_factory(task, cancel):
            self.assertEqual(task, self.task)
            validator = CoreSandboxValidation(
                self.fixture.journal, self.fail, profile=self.profile, cancel=cancel,
            )
            return coding_tasks.CodingRun(
                self.producer(worker, cancel), validator, self.root, self.source,
                'sha256:' + 'a' * 64, 'target-1', 200,
            )

        def service(fixture, factory):
            capsules = CorePatchCapsules(fixture.journal, signer, source_probe=lambda: self.source)
            controller = coding_tasks.CoreCodingTasks(
                fixture.journal, capsules, run_factory=factory, run_principal=fixture.p(), clock=lambda: 100,
            )
            self.addCleanup(controller.close)
            return controller

        manager, reader = self.fixture.p(Capability.MANAGE), self.fixture.p(Capability.READ)
        task_id = {'task_id': self.task.task_id}
        first = service(self.fixture, run_factory)
        first.request(manager, 'create_task', {'task': asdict(self.task)})
        first.request(manager, 'start', task_id)
        self.assertTrue(first.wait(self.task.task_id, 3))
        observed = first.request(reader, 'get_receipts', task_id)
        self.assertEqual(observed['state'], 'UNKNOWN')
        self.assertFalse(observed['effect_verified'])
        self.assertIsNone(observed['run_result']['final_patchset'])
        first.close()
        self.fixture.close()

        reopened = q09_support.Fixture(self.root / 'core.json')
        self.addCleanup(reopened.close)
        after = service(reopened, self.fail)
        read = reopened.p(Capability.READ)
        manage = reopened.p(Capability.MANAGE)
        self.assertEqual(after.request(read, 'get_receipts', task_id), observed)
        with self.assertRaisesRegex(ValueError, 'CODING_TRANSITION_DENIED'):
            after.request(manage, 'start', task_id)
        subsequent = replace(self.task, task_id='later', run_id='later-run')
        after.request(manage, 'create_task', {'task': asdict(subsequent)})
        with self.assertRaises(ValueError):
            after.request(manage, 'start', {'task_id': subsequent.task_id})
        self.assertEqual((worker.starts, worker.cancel_calls, worker.closed), (1, 0, True))

    def test_core_persists_ambiguous_start_and_denies_dispatch_after_reopen(self):
        self.assert_reopen_denies_dispatch(StartAckLostFixture())

    def test_core_persists_ambiguous_result_and_denies_dispatch_after_reopen(self):
        self.assert_reopen_denies_dispatch(ReadbackAckLostFixture('result'))

    def test_explicit_start_denial_preserves_known_failure(self):
        class DeniedStart(CancellationAckFixture):
            def start(self, task):
                raise WorkerError('WORKER_START_DENIED')

        worker = DeniedStart()
        producer = self.producer(worker)
        with self.assertRaisesRegex(WorkerError, '^WORKER_START_DENIED$'):
            producer.produce(0, None)
        self.assertEqual(producer.close(), 0)
        self.assertEqual(worker.cancel_calls, 0)


if __name__ == '__main__':
    unittest.main()
