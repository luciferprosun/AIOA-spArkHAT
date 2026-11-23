"""Causal ownership seams needed for STOP, expiry, JIT and populated restart."""
import threading
import time
from dataclasses import FrozenInstanceError, asdict
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import nz13_native_foundation_support as fx

from runtime.core_admission import AdmissionError, Capability
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mission.warrant import WarrantError
from runtime.mission.worker import Task

from nz13_native_coding_support import NativeCompletionCase, require_method, require_parameter

from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.portable_target import CorePortableTarget
from runtime.mission.repair_validation import CoreSandboxValidation


class NativeCodingLifecycleTests(NativeCompletionCase):
    def test_stop_between_claim_and_publication_has_owned_snapshot(self):
        require_method(self, CoreCodingTasks, "lifecycle_snapshot",
                       "NATIVE_PRECLAIM_OWNERSHIP_SNAPSHOT_MISSING")

    def test_close_waits_for_real_owned_drain(self):
        require_method(self, CoreCodingTasks, "drain",
                       "NATIVE_CODING_REAL_DRAIN_REPORT_MISSING")

    def test_five_minute_principal_refresh_has_native_binding(self):
        require_parameter(self, CoreCodingTasks, "native_access",
                          "NATIVE_PRINCIPAL_REFRESH_BOUNDARY_MISSING")

    def test_early_stage_failure_cannot_prestart_later_stages(self):
        require_parameter(self, CoreSandboxValidation, "stage_preparer",
                          "NATIVE_SINGLE_USE_JIT_STAGE_BOUNDARY_MISSING")

    def test_populated_restart_requires_fresh_portable_read_capture(self):
        require_parameter(self, CorePortableTarget, "native_access",
                          "NATIVE_PORTABLE_FRESH_READ_JOIN_MISSING")

    def test_partial_initialization_has_truthful_current_observation(self):
        require_method(self, NativeMobileComposition, "readiness",
                       "NATIVE_PARTIAL_GRAPH_READINESS_MISSING")

    def controller(self, *, native=False, factory=None):
        owner, _ = fx.new_host(self)
        fx.fixture_tls(owner)
        foundation = owner.foundation
        capsules = CorePatchCapsules(foundation.intent_journal, owner.identity,
                                    source_probe=lambda: foundation.spec.project_source)
        kwargs = {"native_access": foundation.access} if native else {}
        if factory is not None:
            kwargs.update(run_factory=factory)
            if not native:
                kwargs["run_principal"] = owner.core.local_operator(Capability.COMMIT)
        tasks = CoreCodingTasks(foundation.intent_journal, capsules, **kwargs)
        self.addCleanup(tasks.close)
        return owner, tasks

    def test_snapshot_and_empty_drain_are_immutable_real_facts(self):
        require_method(self, CoreCodingTasks, "lifecycle_snapshot", "NATIVE_PRECLAIM_OWNERSHIP_SNAPSHOT_MISSING")
        require_method(self, CoreCodingTasks, "drain", "NATIVE_CODING_REAL_DRAIN_REPORT_MISSING")
        owner, tasks = self.controller()
        snapshot = tasks.lifecycle_snapshot()
        self.assertEqual((), snapshot.work)
        self.assertFalse(snapshot.closed)
        with self.assertRaises(FrozenInstanceError):
            snapshot.closed = True
        report = tasks.drain(0)
        self.assertTrue(report.drained)
        self.assertFalse(report.quarantined)
        self.assertTrue(owner.core.configured)
        self.assertEqual((), report.work)
        self.assertEqual({"closed", "work"}, set(asdict(snapshot)))

    def test_handle_is_published_before_durable_running_and_stop_reaches_same_token(self):
        require_method(self, CoreCodingTasks, "lifecycle_snapshot", "NATIVE_PRECLAIM_OWNERSHIP_SNAPSHOT_MISSING")
        entered, release = threading.Event(), threading.Event()
        def factory(_task, cancel):
            entered.set()
            release.wait(2)
            self.assertTrue(cancel.cancelled)
            raise ValueError("OWNED_FIXTURE_CANCELLED_BEFORE_EFFECT")
        owner, tasks = self.controller(factory=factory)
        task = Task("publication-task", "publication-run", "fixture-workspace", "fixture-repo",
                    "c" * 40, "Finite synthetic publication barrier", int(time.time()) + 120)
        manage = owner.core.local_operator(Capability.MANAGE)
        tasks.request(manage, "create_task", {"task": task.to_dict()})
        transition = tasks._transition
        observations = []
        def durable(*args, **kwargs):
            if len(args) > 3 and args[3] == "RUNNING":
                active = tasks._active.get(task.task_id)
                self.assertIsNotNone(active, "DURABLE_CLAIM_BEFORE_OWNED_HANDLE")
                self.assertIs(type(active["thread"]), threading.Thread)
                self.assertIs(type(active["done"]), threading.Event)
                self.assertFalse(active["thread"].is_alive())
                observations.append(active["cancel"])
            return transition(*args, **kwargs)
        try:
            with patch.object(tasks, "_transition", side_effect=durable):
                tasks.request(manage, "start", {"task_id": task.task_id})
            self.assertTrue(entered.wait(2))
            tasks.request(manage, "stop", {"task_id": task.task_id})
            self.assertTrue(observations[0].cancelled)
            snapshot = tasks.lifecycle_snapshot()
            self.assertEqual((task.task_id,), tuple(work.task_id for work in snapshot.work))
            self.assertTrue(snapshot.work[0].cancel_requested)
        finally:
            release.set()
            tasks.wait(task.task_id, 3)

    def test_expired_static_principal_cannot_prevent_new_native_read_capture(self):
        require_parameter(self, CoreCodingTasks, "native_access", "NATIVE_PRINCIPAL_REFRESH_BOUNDARY_MISSING")
        owner, tasks = self.controller(native=True)
        old = owner.core.local_operator(Capability.READ)
        later = old.expires_at + timedelta(seconds=1)
        with patch.object(owner.core, "_clock", return_value=later):
            with self.assertRaises(AdmissionError):
                owner.core.require(old, Capability.READ)
            view = tasks.runtime_view(old)
        self.assertEqual("UNBOUND", view["controller_state"])
        self.assertEqual(300, (old.expires_at - old.issued_at).total_seconds())

    def test_public_native_reconcile_requires_original_lifecycle_before_git(self):
        _, tasks = self.controller(native=True)
        with patch('runtime.mission.git_publish._bounded_git') as git:
            with self.assertRaisesRegex(WarrantError, '^CODING_NATIVE_RECONCILIATION_BINDING$'):
                tasks.request(None, 'reconcile', {'task_id': 'old-task'})
            git.assert_not_called()
        self.assertEqual((), tasks.lifecycle_snapshot().work)

    def test_retained_native_handle_without_positive_broker_ack_cannot_read_back(self):
        from lab_archaioa.test_warrant import WarrantTests
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        from runtime.meta_hackathon.native_authority import NativeOwnedWorkHandle
        from runtime.mission.git_publish import CoreRemoteGitRoute
        from runtime.providers.exact import CancellationToken

        owner, tasks = self.controller(native=True)
        foundation = owner.foundation
        lifecycle = foundation.lifecycle
        route = object.__new__(CoreRemoteGitRoute)
        warrant = WarrantTests().fixture()
        task_id = warrant.task_id
        route.capsule = SimpleNamespace(task_id=task_id, digest='a' * 64)
        route.plan = SimpleNamespace(digest='c' * 64)
        cancel = CancellationToken()
        thread = threading.current_thread()
        done, guard = threading.Event(), threading.Lock()
        handle = NativeOwnedWorkHandle(
            foundation, tasks, 'CODING_HTTP_EFFECT', 'coding-effect-' + task_id,
            cancel, thread, done, started=True, synchronous=True, kind='LOCAL_GIT_APPLY',
        )
        operation = {'fixture': 'original operation before positive broker return'}
        item = {
            'route': route, 'warrant': warrant, 'operation': operation, 'thread': thread,
            'cancel': cancel, 'done': done, 'native_handle': handle, 'quarantined': False,
            'returned': False, 'admission_held': False, 'admission_guard': guard, 'phase': 'EXECUTING',
        }
        item['binding'] = handle.context = (
            item, tasks, foundation, route, warrant, canonical_json_bytes(operation),
            thread, cancel, done, guard, handle.kind,
        )
        tasks._effect_ownership[task_id] = item
        tasks._effects[task_id] = cancel
        lifecycle._handles[handle.task_id] = handle
        self.addCleanup(tasks._effect_ownership.pop, task_id)
        self.addCleanup(tasks._effects.pop, task_id)
        self.addCleanup(lifecycle._handles.pop, handle.task_id)
        # Capture through the original invocation boundary. The fixture
        # supplies the broker return; it never claims physical publication.
        lifecycle._boundary.coding_effect = item
        try:
            tasks._native_git_record_cas_ack(route, warrant, route.plan, route.plan.digest)
            ack = item.pop('cas_ack')
        finally:
            del lifecycle._boundary.coding_effect
        item.update(quarantined=True, returned=True)
        handle.returned = (tasks, item, thread, done)
        lifecycle.quarantine(handle)
        done.set()
        managed = SimpleNamespace(effects={(task_id, route.capsule.digest): ((route, warrant),)},
                                  graph_complete=False)
        with (patch.object(owner, '_native_coding', managed, create=True),
              patch.object(tasks, '_run', side_effect=RuntimeError('bounded read entry')) as read):
            for substitute in (None, (object(), ack[1], ack[2]), (ack[0], ack[1], 'f' * 64)):
                with self.subTest(substitute=bool(substitute)):
                    item['cas_ack'] = substitute
                    with self.assertRaisesRegex(WarrantError, '^CODING_NATIVE_GIT_CAS_ACK_REQUIRED$'):
                        tasks.request(None, 'reconcile', {'task_id': task_id})
                    read.assert_not_called()
            item['cas_ack'] = ack
            with self.assertRaisesRegex(RuntimeError, '^bounded read entry$'):
                tasks.request(None, 'reconcile', {'task_id': task_id})
            read.assert_called_once()
