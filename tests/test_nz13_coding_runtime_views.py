"""One existing Core, authenticated runtime readback and signed task counts."""
import http.client
import json
import threading
import unittest
from types import SimpleNamespace

import test_nz11_controller as support
from q09_support import Fixture

from runtime.core_admission import AdmissionError, Capability
from runtime.main import AgentRuntime
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import StoredRecord
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.webapp import WebRuntimeService, make_server


class CodingRuntimeViewTests(unittest.TestCase):
    def setUp(self):
        self.case = support.ControllerTests('test_two_active_runs_cancel_independently_without_worker_or_core_replay')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = self.case.fx
        self.tasks = self.case.service()
        self.root = self.case.case.case.root
        self.runtime = AgentRuntime(None, '', self.root, inspection_only=True, coding_tasks=self.tasks)
        self.addCleanup(self.runtime.close)
        self.principals = {name: self.fx.p(getattr(Capability, name)) for name in
                           ('READ', 'MANAGE', 'COMMIT', 'OWNER_APPROVAL')}

    def view(self):
        self.assertTrue(callable(getattr(CoreCodingTasks, 'runtime_view', None)),
                        'Missing Core-owned runtime read projection')
        return self.tasks.request(self.fx.p(Capability.READ), 'runtime_status', {})

    def admit(self):
        task = self.case.case.task
        self.case.admit(self.tasks, task)
        return task

    def test_agent_runtime_keeps_the_same_admitted_core_as_its_coding_controller(self):
        self.assertIs(self.runtime._memory_patch_admission, self.fx.core)
        self.assertIs(self.runtime._coding_tasks.journal, self.fx.journal)

    def test_runtime_counts_are_read_from_signed_core_records_without_task_content(self):
        task = self.admit()
        view = self.view()
        self.assertEqual(1, view['task_counts']['QUEUED'])
        self.assertEqual(1, sum(view['task_counts'].values()))
        self.assertEqual('CONFIGURED', view['controller_state'])
        self.assertEqual('NOT_CHECKED_BY_READ', view['worker_certification'])
        self.assertEqual('NONE', view['authority'])
        self.assertTrue(view['read_only'])
        self.assertFalse(view['automatic_retry'])
        self.assertNotIn(task.instruction, json.dumps(view))
        self.assertEqual('QUEUED', self.tasks.request(self.fx.p(Capability.READ), 'read_status', {'task_id': task.task_id})['state'])

    def test_runtime_readback_tracks_actual_running_and_stopped_worker(self):
        task = self.admit()
        self.view()
        self.tasks.request(self.fx.p(Capability.MANAGE), 'start', {'task_id': task.task_id})
        self.case.wait_started(task)
        self.assertEqual(1, self.view()['task_counts']['RUNNING'])
        self.tasks.request(self.fx.p(Capability.MANAGE), 'stop', {'task_id': task.task_id})
        self.assertTrue(self.tasks.wait(task.task_id, 3))
        self.assertEqual(1, self.view()['task_counts']['CANCELLED'])
        self.assertEqual(1, self.case.workers[task.task_id].cancels)

    def test_foreign_owner_gets_no_runtime_metadata_or_signed_task_counts(self):
        self.admit()
        self.view()
        foreign = Fixture(self.root / 'foreign-view-core.json')
        self.addCleanup(foreign.close)
        with self.assertRaises(AdmissionError):
            self.tasks.request(foreign.p(Capability.READ), 'runtime_status', {})

    def test_corrupt_signature_cannot_be_projected_as_a_successful_or_queued_task(self):
        task = self.admit()
        self.view()

        def corrupt(tx):
            prior, data, _ = self.tasks._load(tx, task.task_id)
            data = json.loads(canonical_json_bytes(data))
            data['receipts'][-1]['signature'] = 'SYNTHETIC_INVALID_SIGNATURE'
            tx.replace(StoredRecord(prior.kind, prior.record_id, prior.scope, prior.revision + 1, data),
                       expected_revision=prior.revision)

        self.fx.journal._run(self.fx.p(), Capability.COMMIT, corrupt)
        with self.assertRaises(MemoryPatchError) as denied:
            self.view()
        self.assertEqual(ErrorCode.TRANSACTION_FAILED, denied.exception.code)

    def test_web_composition_rejects_coding_and_meta_bound_to_different_cores(self):
        self.view()
        from runtime.meta_hackathon.runtime_adapter import OfflineMetaComposition
        other = OfflineMetaComposition(self.root / 'other-meta-core',
                                       source_probe=lambda: ('1' * 40, 'a' * 64))
        self.addCleanup(other.close)
        original = self.runtime._memory_patch_admission
        self.runtime._memory_patch_admission = other.core
        try:
            with self.assertRaisesRegex(ValueError, 'CODING_SAME_CORE_REQUIRED'):
                WebRuntimeService(runtime=self.runtime, coding_principals=self.principals,
                                  meta_missions=other.missions,
                                  meta_owner=SimpleNamespace(runtime=self.runtime))
        finally:
            self.runtime._memory_patch_admission = original

    def test_runtime_http_get_is_authenticated_and_does_not_create_another_core(self):
        self.admit()
        self.view()
        service = WebRuntimeService(runtime=self.runtime, coding_principals=self.principals)
        server = make_server('127.0.0.1', 0, service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for authenticated, expected in ((False, 403), (True, 200)):
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                headers = {'X-AIOA-Session-Token': service.csrf_token} if authenticated else {}
                try:
                    connection.request('GET', '/api/agent/coding/runtime', headers=headers)
                    response = connection.getresponse()
                    data = response.read()
                    self.assertEqual(expected, response.status)
                    if authenticated:
                        self.assertEqual(1, json.loads(data)['task_counts']['QUEUED'])
                finally:
                    connection.close()
            self.assertIs(service.runtime._coding_tasks.journal.ledger.core, self.fx.core)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
