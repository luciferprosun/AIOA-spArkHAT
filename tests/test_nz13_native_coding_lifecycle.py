"""Causal ownership seams needed for STOP, expiry, JIT and populated restart."""
import threading
import time
from dataclasses import FrozenInstanceError, asdict
from datetime import timedelta
from unittest.mock import patch

import nz13_native_foundation_support as fx

from runtime.core_admission import AdmissionError, Capability
from runtime.mission.patch_capsule import CorePatchCapsules
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
