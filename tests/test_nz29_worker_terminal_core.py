"""F05 through WorkerMailbox, Core coding admission and durable receipt readback."""

from dataclasses import asdict, replace
import json
from pathlib import PurePosixPath
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec

import q09_support
import test_nz11_general_recipe as recipe_support
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission import coding_tasks, repair, repository_worker
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.repair_validation import (
    CoreRepositoryMaterializer,
    CoreSandboxValidation,
    workspace_tree_digest,
)
from runtime.mission.worker import WorkerError, WorkerFailure, WorkerMailbox, WorkerResult
from runtime.mobile_gateway.wire import Identity


class OrderedWorker:
    """Inject a fixed ordering into the real mailbox from a local transport."""

    def __init__(self, candidate, cancel, timing, *, duplicate=False):
        self.candidate = candidate
        self.cancel_token = cancel
        self.timing = timing
        self.duplicate = duplicate
        self.clock = 100
        self.elapsed = 0
        self.starts = self.cancels = 0
        self.events = ()
        self.late_reply = self.captured = self.current = None
        self.foreign_denied = False

    def start(self, task):
        self.starts += 1
        self.task = task
        self.box = WorkerMailbox(task, clock=lambda: self.clock)
        if self.timing in ('stop', 'cancel'):
            self.cancel_token.cancel()
        elif self.timing == 'unknown':
            self.box.fail(self.box.session, 'OUTCOME_UNKNOWN')
        return self.box.session

    def late(self, session):
        if self.duplicate:
            payload = {
                'schema': 'aioa.worker-candidate.v1',
                'task_id': session.task_id, 'run_id': session.run_id,
                'session_id': session.session_id, 'task_digest': session.task_digest,
                'files': [asdict(item) for item in self.candidate.files],
            }
            self.late_reply = self.box.complete_json(
                session, json.dumps(payload).encode(), completion_tokens=32)
        else:
            self.late_reply = self.box.progress(session)

    def poll(self, session):
        if self.timing == 'deadline':
            self.clock = self.task.deadline_at
            self.box.progress(session)
        elif self.timing != 'unknown':
            if self.timing == 'foreign':
                try:
                    self.box.complete(replace(session, run_id='other-run'), self.candidate)
                except WorkerError:
                    self.foreign_denied = True
            self.box.complete(session, self.candidate)
            if self.timing == 'before_drain':
                self.late(session)
        self.events = self.box.drain(session)
        if self.timing == 'after_drain':
            self.late(session)
        elif self.timing == 'deadline_during_poll':
            self.clock = self.task.deadline_at
        elif self.timing == 'budget_during_poll':
            self.elapsed = 20
        return self.events

    def result(self, session):
        self.captured = self.box.result(session)
        if self.timing == 'after_capture':
            self.late(session)
            self.repeated_reply = self.box.complete(session, self.candidate)
            self.repeated_progress = self.box.progress(session)
        self.current = self.box.result(session)
        return self.captured

    def cancel(self, session):
        self.cancels += 1
        code = 'OUTCOME_UNKNOWN' if self.timing == 'stop' else 'CANCELLED'
        self.box.fail(session, code)

    def interrupt(self, session):
        self.box.fail(session, 'INTERRUPTED')

    def close(self):
        return 0


class WorkerTerminalCoreTests(unittest.TestCase):
    def setUp(self):
        case = recipe_support.GeneralRecipeTests(
            'test_source_is_actual_git_commit_tree_and_independently_exported_bytes')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.case = case
        self.snapshot, self.base, self.source, self.task, self.candidate, _, _ = case.proposal()
        self.profile = case.profile()
        self.store = case.root / 'f05-core.json'
        self.identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.prepared = []
        self.materialized = []
        self.workers = []

    def controller(self, fixture, factory=None):
        capsules = CorePatchCapsules(fixture.journal, self.identity, source_probe=lambda: self.source)
        return coding_tasks.CoreCodingTasks(
            fixture.journal, capsules, run_factory=factory, run_principal=fixture.p(), clock=lambda: 100)

    def materialize_fixture(self, spec, predicted):
        self.prepared.append((spec, predicted))
        scratch = self.case.root / 'fixture-materialization'
        for directory in ('inputs', 'work', 'artifacts'):
            (scratch / directory).mkdir(parents=True, mode=0o700)
        for name in ('base.json', 'changes.json', 'materialization.json'):
            (scratch / 'inputs' / name).write_bytes(spec['files'][name])
        # Execute the trusted materialization routine on disposable files.
        # Only the guest mount locators are replaced.
        with patch.object(repository_worker, 'Path',
                          side_effect=lambda path: scratch.joinpath(*PurePosixPath(path).parts[1:])):
            repository_worker.materialize()
        for name, expected in spec['expected'].items():
            self.assertEqual((scratch / 'artifacts' / name).read_bytes(), expected)
        archive = (scratch / 'artifacts' / 'workspace.json').read_bytes()
        self.materialized.append(workspace_tree_digest(archive))
        # No broker dispatch, certified kernel readback or effect receipt.
        raise ValueError('F05_TEST_BROKER_CLOSED')

    def run_order(self, timing, *, duplicate=False):
        fixture = q09_support.Fixture(self.store)

        def factory(task, cancel):
            self.assertEqual(task, self.task)
            worker = OrderedWorker(self.candidate, cancel, timing, duplicate=duplicate)
            self.workers.append(worker)
            materializer = CoreRepositoryMaterializer(
                fixture.journal, self.materialize_fixture, profile=self.profile, source_snapshot=self.snapshot,
                source_repository=self.case.repo.path, base_root=self.base,
                output_root=self.case.root / 'mirrors', cancel=cancel)
            producer = repair.SandboxedCandidateProducer(
                task, worker, materializer, cancel=cancel,
                clock=lambda: worker.clock, monotonic=lambda: worker.elapsed)
            validator = CoreSandboxValidation(
                fixture.journal, lambda *_: self.fail('no validation without a broker receipt'),
                profile=self.profile, cancel=cancel)
            return coding_tasks.CodingRun(
                producer, validator, self.base, self.source, 'sha256:' + 'a'*64, 'target-1', 200)

        original = self.case.repo.git('show-ref', '--head')
        service = self.controller(fixture, factory)
        try:
            manager = fixture.p(Capability.MANAGE)
            reader = fixture.p(Capability.READ)
            task_id = {'task_id': self.task.task_id}
            service.request(manager, 'create_task', {'task': asdict(self.task)})
            service.request(manager, 'start', task_id)
            self.assertTrue(service.wait(self.task.task_id, 6))
            view = service.request(reader, 'get_receipts', task_id)
            self.assertIn(view['state'], ('FAILED', 'CANCELLED', 'UNKNOWN'))
            self.assertEqual(view['authority'], 'NONE')
            self.assertIsNone(view['capsule_digest'])
            self.assertFalse(view['effects_registered'])
            self.assertFalse(view['effect_verified'])
            self.assertIsNone(view['run_result']['final_patchset'])
            self.assertNotIn('PATCH_READY', [row['receipt']['state'] for row in view['receipts']])
            if view['state'] == 'UNKNOWN':
                service.request(manager, 'stop', task_id)
                self.assertEqual(service.request(reader, 'get_receipts', task_id)['state'], 'UNKNOWN')
                view = service.request(reader, 'get_receipts', task_id)
                self.assertEqual(service.request(manager, 'start', task_id)['state'], 'UNKNOWN')
            else:
                with self.assertRaises(ValueError):
                    service.request(manager, 'start', task_id)
            records = fixture.journal._run(reader, Capability.READ,
                lambda tx: tx.scan(RecordKind.OPERATION, limit=512))
            self.assertFalse(any(row.payload.get('schema') == 'aioa.materialization.v1'
                                 or 'warrant_digest' in row.payload for row in records))
        finally:
            service.close()
            fixture.close()
        self.assertEqual(self.case.repo.git('show-ref', '--head'), original)
        self.snapshot.verify_export(self.base)
        self.assertFalse((self.case.root / 'mirrors').exists())
        reopened = q09_support.Fixture(self.store)
        readback = self.controller(reopened, self.fail)
        try:
            before = self.store.read_bytes()
            self.assertEqual(readback.request(reopened.p(Capability.READ), 'get_receipts', task_id), view)
            self.assertEqual(self.store.read_bytes(), before)
        finally:
            readback.close()
            reopened.close()
        self.assertEqual(len(self.workers), 1)
        worker, = self.workers
        self.assertEqual(worker.starts, 1)
        print(json.dumps({
            'scenario': timing, 'duplicate': duplicate,
            'events': [row.kind for row in worker.events],
            'captured': worker.captured.status, 'mailbox': worker.current.status,
            'late_reply': getattr(worker.late_reply, 'code', worker.late_reply),
            'core': view['state'], 'materialization_requests': len(self.prepared),
            'materialized_tree_digests': self.materialized,
            'reopened': True, 'fixture_effect_receipts': 0,
        }, sort_keys=True))
        return worker, view

    def test_late_progress_before_drain_cannot_leave_queued_success(self):
        with self.assertLogs('runtime.mission.worker', 'WARNING') as audit:
            worker, _ = self.run_order('before_drain')
        self.assertEqual(worker.captured.code, 'LATE_EVENT')
        self.assertFalse(worker.late_reply)
        self.assertFalse(self.prepared)
        self.assertEqual([row.kind for row in worker.events], ['STARTED'])
        self.assertEqual([row.getMessage() for row in audit.records], [
            f'LATE_EVENT worker_session={worker.box.session.session_id} captured=False',
        ])

    def test_late_completion_after_drain_denies_materialization(self):
        worker, _ = self.run_order('after_drain', duplicate=True)
        self.assertEqual([row.kind for row in worker.events], ['STARTED', 'CANDIDATE', 'COMPLETED'])
        self.assertEqual(worker.late_reply.code, 'LATE_EVENT')
        self.assertEqual(worker.captured.code, 'LATE_EVENT')
        self.assertFalse(self.prepared)

    def test_completion_after_capture_leaves_the_same_advice_and_rejects_duplicate(self):
        with self.assertLogs('runtime.mission.worker', 'WARNING') as audit:
            worker, _ = self.run_order('after_capture', duplicate=True)
        self.assertIs(type(worker.captured), WorkerResult)
        self.assertIs(type(worker.late_reply), WorkerFailure)
        self.assertEqual(worker.late_reply.code, 'LATE_EVENT')
        self.assertIs(worker.repeated_reply, worker.late_reply)
        self.assertFalse(worker.repeated_progress)
        self.assertIs(worker.current, worker.captured)
        self.assertEqual([row.getMessage() for row in audit.records], [
            f'LATE_EVENT worker_session={worker.box.session.session_id} captured=True',
        ])
        (spec, candidate), = self.prepared
        self.assertEqual(candidate.worker_session_id, worker.captured.session_id)
        self.assertIn('workspace.json', spec['expected'])
        self.assertEqual(self.materialized, [candidate.final_tree_sha256])

    def test_foreign_completion_does_not_change_local_result(self):
        worker, _ = self.run_order('foreign')
        self.assertTrue(worker.foreign_denied)
        self.assertIs(type(worker.captured), WorkerResult)
        self.assertEqual(len(self.materialized), 1)

    def test_deadline_denies_materialization(self):
        worker, _ = self.run_order('deadline')
        self.assertEqual(worker.captured.code, 'TIMEOUT')
        self.assertFalse(self.prepared)

    def test_deadline_crossed_during_poll_denies_materialization(self):
        worker, view = self.run_order('deadline_during_poll')
        self.assertIs(type(worker.captured), WorkerResult)
        self.assertEqual(view['state'], 'FAILED')
        self.assertFalse(self.prepared)

    def test_worker_wait_budget_crossed_during_poll_denies_materialization(self):
        worker, view = self.run_order('budget_during_poll')
        self.assertIs(type(worker.captured), WorkerResult)
        self.assertEqual(view['state'], 'FAILED')
        self.assertFalse(self.prepared)

    def test_acknowledged_cancellation_denies_materialization(self):
        worker, view = self.run_order('cancel')
        self.assertEqual(worker.cancels, 1)
        self.assertEqual(worker.captured.code, 'CANCELLED')
        self.assertEqual(view['state'], 'CANCELLED')
        self.assertFalse(self.prepared)

    def test_stop_with_lost_ack_preserves_unknown_on_reopen(self):
        worker, view = self.run_order('stop')
        self.assertEqual(worker.cancels, 1)
        self.assertEqual(worker.captured.code, 'OUTCOME_UNKNOWN')
        self.assertEqual(view['state'], 'UNKNOWN')
        self.assertFalse(self.prepared)

    def test_unknown_transport_blocks_materialization_on_restart(self):
        worker, view = self.run_order('unknown')
        self.assertEqual(worker.captured.code, 'OUTCOME_UNKNOWN')
        self.assertEqual(view['state'], 'UNKNOWN')
        self.assertFalse(self.prepared)
