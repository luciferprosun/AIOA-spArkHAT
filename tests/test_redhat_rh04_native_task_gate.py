"""RH-04 opt-in gate and actual CoreCodingTasks recovery fixture tests.

All Git repositories, keys, task data, databases and executor identities used
here are synthetic and disposable. These tests do not qualify a host or enable
production execution.
"""

import os
import json
import select
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec

from q09_support import Fixture, MODEL
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.governor import ReservationRequest
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.patch_capsule import CorePatchCapsules, ExecutionCapsule, KIND as CAPSULE_KIND
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.git_publish import CoreRemoteGitRoute
from lab.archaioa.authority import Money
from runtime.mission.worker import Task
from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.broker_protocol import BrokerRequest
from runtime.red_hat.core_adapter import (
    CoreAdapterError, CoreIntentAdapter, DisposableNativeTaskWitnessPort,
)
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.native_stop_gate import NativeStopCasGate, bind_transaction_runner
from test_redhat_broker_protocol import NOW
import test_redhat_native_cas_broker as cas_broker

git = cas_broker.git
from test_redhat_core_adapter import align_warrant_window
from runtime.mission.warrant import approval_digest


def align_warrant(fixture):
    align_warrant_window(fixture)
    fixture.warrant = replace(fixture.warrant,
                              approval_digest=approval_digest(fixture.warrant))


def make_native_zero_warrant(fixture):
    scope = replace(fixture.warrant.authority_scope,
                    operation_classes=tuple(set(fixture.warrant.authority_scope.operation_classes)
                                            | {"GIT_COMMIT"}),
                    monetary_ceiling=Money(Decimal("0"),
                                           fixture.warrant.authority_scope.monetary_ceiling.currency))
    fixture.warrant = replace(fixture.warrant, money_reservation_id="NONE",
                              authority_scope=scope, operation_class="GIT_COMMIT")


def _recover_native_task_from_restarted_core(config_path, *, lose_settlement_ack=False):
    from cryptography.hazmat.primitives import serialization
    from lab.archaioa.warrant import EffectWarrant
    from runtime.red_hat.enrollment import ExecutorEnrollment
    from runtime.red_hat.witness import RegisteredExecutor

    config = json.loads(Path(config_path).read_text())
    fixture = Fixture(Path(config["core_state_path"]))
    tasks = None
    root_fd = None
    try:
        fixture.warrant = EffectWarrant.from_dict(config["warrant"])
        private_key = serialization.load_pem_private_key(
            config["capsule_signing_key"].encode("ascii"), password=None)
        capsule_identity = Identity(private_key)
        capsules = CorePatchCapsules(fixture.journal, capsule_identity, source_probe=lambda: None)
        tasks = CoreCodingTasks(fixture.journal, capsules)
        request = BrokerRequest.from_wire(config["request"])
        enrollment = ExecutorEnrollment(
            RegisteredExecutor(config["executor"], config["executor_uid"], config["executor_spki"]),
            config["key_epoch"], config["valid_from"], config["valid_until"],
            revoked=config["revoked"],
        )
        root_fd = os.open(config["broker_root"], os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        adapter = CoreIntentAdapter(fixture.journal)
        task_id = config["task_id"]
        tasks.native_witness_recovery_port = DisposableNativeTaskWitnessPort(
            adapter, tasks,
            lambda requested_task: ({
                "warrant": fixture.warrant, "request": request,
                "enrollment": enrollment, "root_fd": root_fd,
                "trusted_device_id": request.device_id, "now": config["verify_now"],
                "core_epoch": request.core_epoch, "broker_epoch": config["broker_epoch"],
            } if requested_task == task_id else None),
        )
        if lose_settlement_ack:
            from runtime.memory_patch.persistence.ports import CommitOutcomeUnknown
            from nv03_support import DurableTransaction

            before_intent = fixture.journal.inspect(
                fixture.p(Capability.READ), fixture.warrant)
            before_task = tasks.request(
                fixture.p(Capability.READ), "read_status", {"task_id": task_id})
            if (before_intent["outcome"]["contract_type"] != "Unknown"
                    or before_task["state"] != "UNKNOWN"):
                raise AssertionError("lost-ACK precondition was not unresolved")
            original_commit = DurableTransaction.commit
            lost = False

            def commit_then_drop_ack(transaction):
                nonlocal lost
                original_commit(transaction)
                intent_row = next((row for row in transaction.snapshot.values()
                                   if row.record_id == fixture.journal._key(fixture.warrant)), None)
                task_row = next((row for row in transaction.snapshot.values()
                                 if row.record_id == tasks._key(task_id)), None)
                committed_settlement = (
                    intent_row is not None and intent_row.payload.get("resolution") is not None
                    and task_row is not None
                    and task_row.payload.get("receipts", [{}])[-1].get("receipt", {}).get("state") == "VERIFIED"
                )
                if not lost and transaction.context.purpose is Capability.COMMIT and committed_settlement:
                    lost = True
                    raise OSError("synthetic durable commit acknowledgment loss")

            DurableTransaction.commit = commit_then_drop_ack
            try:
                tasks.request(fixture.p(), "reconcile", {"task_id": task_id})
            except CommitOutcomeUnknown:
                os.write(1, b'{"ack_lost_after_durable_commit":true}\n')
                os._exit(86)
            finally:
                DurableTransaction.commit = original_commit
            raise AssertionError("expected lost durable settlement acknowledgment")
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: tasks.request(
                fixture.p(), "reconcile", {"task_id": task_id}), range(2)))
        task_view = tasks.request(fixture.p(Capability.READ), "read_status", {"task_id": task_id})
        intent = fixture.journal.inspect(fixture.p(Capability.READ), fixture.warrant)
        print(json.dumps({
            "pid": os.getpid(),
            "verifier_pids": [value["verification_process_pid"] for value in outcomes],
            "intent_outcome": intent["outcome"]["contract_type"],
            "task_state": task_view["state"],
            "task_receipt_counts": [value["task"]["receipt_count"] for value in outcomes],
        }, sort_keys=True))
    finally:
        if root_fd is not None:
            os.close(root_fd)
        if tasks is not None:
            tasks.close()
        fixture.close()


def _prepare_native_task_case(root, broker):
    """Create one synthetic original task/START bound to an RH-02 fixture."""
    base = broker.request
    fx = Fixture(Path(root) / "native-core.json")
    align_warrant(fx)
    make_native_zero_warrant(fx)

    identity = Identity(ec.generate_private_key(ec.SECP256R1()))
    capsules = CorePatchCapsules(fx.journal, identity, source_probe=lambda: None)
    tasks = CoreCodingTasks(fx.journal, capsules)
    task = Task(fx.warrant.task_id, "native-run-1", "fixture-workspace",
                "fixture-repository", "a" * 40,
                "A signed offline Native fixture task.", NOW + 900)
    tasks.request(fx.p(Capability.MANAGE), "create_task", {"task": asdict(task)})
    capsule = ExecutionCapsule(
        task_id=task.task_id, run_id=task.run_id, workspace_id=task.workspace_id,
        repository_id=task.repository_id, worker_session_id="fixture-session",
        source_base_sha=task.source_base_sha, base_tree_sha256="1" * 64,
        final_tree_sha256="2" * 64, task_digest=task.digest,
        patchset_sha256="3" * 64, loop_receipt_sha256="4" * 64,
        test_profile_digest="5" * 64, owner_scope_sha256=canonical_sha256(fx.ledger.scope),
        validation_warrants=tuple("sha256:" + ch * 64 for ch in "678"),
        validation_receipts=tuple(ch * 64 for ch in "901"),
        issued_at=NOW - 30, expires_at=NOW + 240,
        target_fingerprint=fx.warrant.target_fingerprint,
        target_revision=fx.warrant.expected_target_revision,
    )
    capsule_receipt = {
        "schema": "aioa.patch-review-receipt.v1", "state": "REVIEW_REQUIRED",
        "capsule": capsule.payload(), "capsule_digest": capsule.digest, "authority": "NONE",
    }
    capsule_row = StoredRecord(RecordKind.OPERATION,
        canonical_sha256([CAPSULE_KIND, capsule.digest]), fx.ledger.scope, 1,
        {"receipt": capsule_receipt, "signature": identity.sign(capsule_receipt),
         "signer_spki": identity.spki})

    plan_digest = canonical_sha256({"fixture": "native-plan-v3", "capsule": capsule.digest})
    payload = {
        "schema": "aioa.local-operation.v3", "principal_session_id": fx.p().actor_session_id,
        "policy_epoch": 1, "profile": "DISPOSABLE_BARE_PATCH_V1",
        "plan_digest": plan_digest, "capsule_digest": capsule.digest,
        "patchset_sha256": capsule.patchset_sha256, "source_base_sha": task.source_base_sha,
        "commit_sha": base.new_oid,
        "tree_sha": git(broker.root / "repo", "show", "-s", "--format=%T", base.new_oid),
        "device_id": base.device_id,
        "repository_dev": base.repository_dev, "repository_inode": base.repository_inode,
        "ref_directory_dev": base.ref_directory_dev,
        "ref_directory_inode": base.ref_directory_inode,
        "ref": base.exact_ref, "old_oid": base.old_oid, "new_oid": base.new_oid,
    }
    operation = {"operation_class": "GIT_COMMIT",
                 "target_fingerprint": fx.warrant.target_fingerprint,
                 "expected_target_revision": fx.warrant.expected_target_revision,
                 "payload": payload}
    fx.operation = operation
    fx.warrant = replace(fx.warrant, operation_hash="sha256:" + canonical_sha256(operation),
                         risk_reservation_id="paired-1")
    fx.warrant = replace(fx.warrant, approval_digest=approval_digest(fx.warrant))
    fx.journal = CoreIntentJournal(fx.ledger, fx.gov, verifier=fx.verify)
    capsules.journal = fx.journal
    tasks.journal = fx.journal
    fx.request = ReservationRequest("paired-1", task.task_id, "fixture", MODEL,
                                    canonical_sha256(operation), 0, 5)
    fx.init()
    started = fx.journal.start_local_zero(fx.p(), fx.warrant, operation, fx.request)
    require_unknown = started["outcome"]["contract_type"] == "Unknown"
    if not require_unknown:
        raise AssertionError("synthetic Native START was not UNKNOWN")

    def seed_task_links(tx):
        tx.insert(capsule_row)
        for expected, state in (("QUEUED", "REVIEW_REQUIRED"),
                                ("REVIEW_REQUIRED", "APPROVED"),
                                ("APPROVED", "APPLYING"),
                                ("APPLYING", "UNKNOWN")):
            tasks._append_transition(tx, task.task_id, (expected,), state,
                capsule_digest=capsule.digest if state == "REVIEW_REQUIRED" else None)
        step = StoredRecord(RecordKind.OPERATION,
            "github-step-" + capsule.digest[:32] + "-local_patch", fx.ledger.scope, 1,
            {"schema": "aioa.local-patch-step.v1", "state": "GITHUB_STEP_UNKNOWN",
             "warrant_digest": fx.warrant.digest(), "operation_hash": fx.warrant.operation_hash,
             "plan_digest": plan_digest, "automatic_retry": False})
        tx.insert(step)

    fx.runner.run(TransactionContext(fx.p(), Capability.COMMIT), seed_task_links)
    adapter = CoreIntentAdapter(fx.journal)
    binding = adapter.capture_start(fx.p(), fx.warrant)
    enrollment = ExecutorEnrollment(broker.enrollment, 3, NOW - 60, NOW + 600)
    request_values = asdict(base)
    request_values.pop("commit_permit_digest")
    request_values.update({
        "operation_id": binding.operation_id, "attempt_id": binding.attempt_id,
        "owner_id": binding.owner_scope_digest, "executor_id": enrollment.executor.executor,
        "executor_key_id": enrollment.executor.key_id, "key_epoch": enrollment.key_epoch,
        "start_digest": binding.start_digest, "intent_digest": binding.intent_digest,
        "warrant_digest": binding.warrant_digest, "reservation_digest": binding.reservation_digest,
        "core_epoch": binding.core_epoch,
    })
    request = BrokerRequest.for_fixture(**request_values)
    broker.request = request
    broker.spec["request"] = request.to_wire()
    broker.spec["core_epoch"] = binding.core_epoch
    (broker.root / "fixture.json").write_text(json.dumps(broker.spec))
    return {"fx": fx, "tasks": tasks, "task": task, "identity": identity,
            "capsule": capsule, "plan_digest": plan_digest, "operation": operation,
            "adapter": adapter, "binding": binding, "enrollment": enrollment,
            "request": request, "started": started}


def _replace_ref_with_same_oid(repository_root, request):
    ref_path = Path(repository_root) / "repo" / Path(request.exact_ref)
    original = ref_path.with_name(ref_path.name + ".rh04-original")
    os.rename(ref_path, original)
    replacement_fd = os.open(ref_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                             os.O_NOFOLLOW | os.O_CLOEXEC, 0o400)
    try:
        os.write(replacement_fd, (request.new_oid + "\n").encode("ascii"))
        os.fsync(replacement_fd)
    finally:
        os.close(replacement_fd)
    parent_fd = os.open(ref_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


class RedHatRH04Tests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="rh04-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)

    def test_stop_gate_serializes_core_revoke_before_ref_link(self):
        fixture = Fixture(self.root / "core-revoke.json")
        align_warrant(fixture)
        gate_dir = self.root / "gate"
        gate_dir.mkdir(mode=0o700)
        stop_contended = threading.Event()
        gate = NativeStopCasGate(str(gate_dir), contention_observer=stop_contended.set)
        self.addCleanup(gate.close)
        self.addCleanup(fixture.close)
        bind_transaction_runner(fixture.runner, gate)
        fixture.init()
        fixture.start()

        parent = self.root / "refs"
        parent.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, parent_fd)
        checked = threading.Event()
        release_link = threading.Event()
        result = []

        def release():
            def authorize(tx):
                fixture.gov._epoch(fixture.gov._load(tx), fixture.warrant.lease_epoch)
                if fixture.gov._load(tx)["kill"]:
                    raise ValueError("KILL_SWITCH")
                fixture.ledger.require_active_in_transaction(tx, fixture.warrant, consumed=True)
            fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT), authorize)
            checked.set()
            self.assertTrue(release_link.wait(3))

        def publish():
            try:
                result.append(LinuxPublish.publish(parent_fd, release, gate))
            except BaseException as error:
                result.append(error)

        publisher = threading.Thread(target=publish)
        publisher.start()
        self.assertTrue(checked.wait(3))

        def revoke():
            fixture.ledger.revoke(fixture.p(Capability.OWNER_APPROVAL), fixture.warrant)

        stopper = threading.Thread(target=revoke)
        stopper.start()
        self.assertTrue(stop_contended.wait(3))
        release_link.set()
        publisher.join(3)
        stopper.join(3)
        self.assertFalse(publisher.is_alive())
        self.assertFalse(stopper.is_alive())
        self.assertEqual([True], result)
        self.assertTrue((parent / "ref").exists())
        # The final release/link section wins once entered; the serialized STOP
        # then commits. This ordering is a candidate requiring owner approval.
        self.assertTrue(fixture.ledger._run(
            fixture.p(Capability.READ), Capability.READ,
            lambda tx: tx.get(RecordKind.APPROVAL,
                              fixture.ledger._key(fixture.warrant)).payload["revoked"]))

    def test_stop_gate_refuses_link_when_revocation_won_first(self):
        fixture = Fixture(self.root / "core-stop-first.json")
        align_warrant(fixture)
        gate_dir = self.root / "gate-first"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir))
        self.addCleanup(gate.close)
        self.addCleanup(fixture.close)
        bind_transaction_runner(fixture.runner, gate)
        fixture.init()
        fixture.start()
        fixture.ledger.revoke(fixture.p(Capability.OWNER_APPROVAL), fixture.warrant)
        parent = self.root / "refs-first"
        parent.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, parent_fd)

        def release():
            fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT),
                lambda tx: fixture.ledger.require_active_in_transaction(tx, fixture.warrant, consumed=True))

        with self.assertRaisesRegex(ValueError, "WARRANT"):
            LinuxPublish.publish(parent_fd, release, gate)
        self.assertFalse((parent / "ref").exists())

    def test_core_admission_close_waits_for_final_link_gate(self):
        fixture = Fixture(self.root / "core-admission-close.json")
        align_warrant(fixture)
        gate_dir = self.root / "gate-admission-close"
        gate_dir.mkdir(mode=0o700)
        contended = threading.Event()
        gate = NativeStopCasGate(str(gate_dir), contention_observer=contended.set)
        self.addCleanup(gate.close)
        self.addCleanup(fixture.close)
        bind_transaction_runner(fixture.runner, gate)
        fixture.init()
        fixture.start()
        parent = self.root / "refs-admission-close"
        parent.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, parent_fd)
        checked, release_link = threading.Event(), threading.Event()
        result = []

        def release():
            fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT),
                lambda tx: fixture.ledger.require_active_in_transaction(
                    tx, fixture.warrant, consumed=True))
            checked.set()
            self.assertTrue(release_link.wait(3))

        publisher = threading.Thread(target=lambda: result.append(
            LinuxPublish.publish(parent_fd, release, gate)))
        publisher.start()
        self.assertTrue(checked.wait(3))
        closer = threading.Thread(target=fixture.core.close)
        closer.start()
        self.assertTrue(contended.wait(3))
        release_link.set()
        publisher.join(3)
        closer.join(3)
        self.assertFalse(publisher.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertEqual([True], result)
        self.assertTrue((parent / "ref").exists())
        self.assertFalse(fixture.core.configured)

    def test_governor_kill_racing_the_final_link_uses_the_same_gate(self):
        fixture = Fixture(self.root / "core-kill.json")
        align_warrant(fixture)
        gate_dir = self.root / "gate-kill"
        gate_dir.mkdir(mode=0o700)
        kill_contended = threading.Event()
        gate = NativeStopCasGate(str(gate_dir), contention_observer=kill_contended.set)
        self.addCleanup(gate.close)
        self.addCleanup(fixture.close)
        bind_transaction_runner(fixture.runner, gate)
        fixture.init()
        fixture.start()
        parent = self.root / "refs-kill"
        parent.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, parent_fd)
        checked = threading.Event()
        release_link = threading.Event()
        result = []

        def release():
            def authorize(tx):
                state = fixture.gov._load(tx)
                fixture.gov._epoch(state, fixture.warrant.lease_epoch)
                if state["kill"]:
                    raise ValueError("KILL_SWITCH")
                fixture.ledger.require_active_in_transaction(tx, fixture.warrant, consumed=True)
            fixture.runner.run(TransactionContext(fixture.p(), Capability.COMMIT), authorize)
            checked.set()
            self.assertTrue(release_link.wait(3))

        def publish():
            try:
                result.append(LinuxPublish.publish(parent_fd, release, gate))
            except BaseException as error:
                result.append(error)

        publisher = threading.Thread(target=publish)
        publisher.start()
        self.assertTrue(checked.wait(3))
        killer = threading.Thread(target=lambda: fixture.gov.set_kill(
            fixture.p(Capability.MANAGE), True))
        killer.start()
        self.assertTrue(kill_contended.wait(3))
        release_link.set()
        publisher.join(3)
        killer.join(3)
        self.assertFalse(publisher.is_alive())
        self.assertFalse(killer.is_alive())
        self.assertEqual([True], result)
        self.assertTrue((parent / "ref").exists())
        self.assertTrue(fixture.gov.inspect(fixture.p(Capability.READ))["kill"])

    def test_shared_gate_times_out_and_replacement_fails_closed(self):
        gate_dir = self.root / "gate-unsafe"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir), timeout=0.1)
        self.addCleanup(gate.close)
        other = NativeStopCasGate(str(gate_dir), timeout=0.1)
        self.addCleanup(other.close)
        with gate.hold():
            with self.assertRaisesRegex(RuntimeError, "STOP_GATE_TIMEOUT"):
                other.hold().__enter__()
        os.unlink(gate_dir / "native-stop-cas.lock")
        (gate_dir / "native-stop-cas.lock").write_bytes(b"")
        os.chmod(gate_dir / "native-stop-cas.lock", 0o600)
        with self.assertRaisesRegex(RuntimeError, "STOP_GATE_IDENTITY|STOP_GATE_REPLACED"):
            with gate.hold():
                pass

    def test_gate_close_cannot_release_another_threads_critical_section(self):
        gate_dir = self.root / "gate-close"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir), timeout=0.1)
        other = NativeStopCasGate(str(gate_dir), timeout=0.1)
        self.addCleanup(lambda: gate.close() if not gate._closed else None)
        self.addCleanup(lambda: other.close() if not other._closed else None)
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()

        def holder():
            with gate.hold():
                entered.set()
                release.wait(2)
            finished.set()

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(entered.wait(2))
        with self.assertRaisesRegex(RuntimeError, "STOP_GATE_CLOSE_WHILE_HELD"):
            gate.close()
        with self.assertRaisesRegex(RuntimeError, "STOP_GATE_TIMEOUT"):
            with other.hold():
                pass
        self.assertFalse(finished.is_set())
        release.set()
        thread.join(2)
        self.assertTrue(finished.is_set())
        gate.close()

    def test_admission_invalidation_cannot_be_overwritten_by_capacity_activation(self):
        from runtime.meta_hackathon.native_authority import NativeLifecycle, NativePhase

        gate_dir = self.root / "gate-activation"
        gate_dir.mkdir(mode=0o700)
        stop_contended = threading.Event()
        gate = NativeStopCasGate(str(gate_dir), contention_observer=stop_contended.set)
        self.addCleanup(gate.close)

        class Fence:
            admission_generation = 17

            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

        fence = Fence()
        lifecycle = NativeLifecycle.__new__(NativeLifecycle)
        lifecycle.foundation = SimpleNamespace(runner=SimpleNamespace(execution_gate=gate))
        lifecycle.lock = threading.RLock()
        lifecycle._phase = NativePhase.CAPACITY_ADMIN
        lifecycle._fence = fence
        lifecycle._capacity_previous_phase = NativePhase.FENCED
        lifecycle._handles = {}
        lifecycle.admission_generation = 17
        lifecycle.fence_sequence = 3
        aborted, resume_activation = threading.Event(), threading.Event()
        real_abort = lifecycle.abort

        def pause_after_abort(current):
            real_abort(current)
            aborted.set()
            self.assertTrue(resume_activation.wait(2))

        lifecycle.abort = pause_after_abort
        errors = []

        def activate():
            try:
                lifecycle.complete_capacity_application(fence, activate=True)
            except BaseException as error:
                errors.append(error)

        def invalidate():
            try:
                lifecycle.invalidate_admission()
            except BaseException as error:
                errors.append(error)

        activation = threading.Thread(target=activate)
        activation.start()
        self.assertTrue(aborted.wait(2))
        invalidation = threading.Thread(target=invalidate)
        invalidation.start()
        self.assertTrue(stop_contended.wait(2))
        resume_activation.set()
        activation.join(2)
        invalidation.join(2)
        self.assertFalse(activation.is_alive())
        self.assertFalse(invalidation.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(NativePhase.FENCED, lifecycle.phase)
        self.assertEqual(18, lifecycle.admission_generation)

    def test_gate_lock_is_released_by_kernel_after_process_death(self):
        gate_dir = self.root / "gate-crash"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir))
        self.addCleanup(gate.close)
        code = (
            "import os,sys; from runtime.red_hat.native_stop_gate import NativeStopCasGate; "
            "g=NativeStopCasGate(sys.argv[1]); "
            "ctx=g.hold(); ctx.__enter__(); print('HELD',flush=True); os._exit(74)"
        )
        child = subprocess.Popen([sys.executable, "-B", "-c", code, str(gate_dir)],
                                 cwd=Path(__file__).resolve().parents[1],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True,
                                 env={"PATH": os.defpath, "PYTHONNOUSERSITE": "1"})
        self.addCleanup(lambda: child.kill() if child.poll() is None else None)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.stderr.close)
        readable, _, _ = select.select([child.stdout], [], [], 3)
        self.assertTrue(readable)
        self.assertEqual("HELD\n", child.stdout.readline())
        self.assertEqual(74, child.wait(timeout=3))
        with gate.hold():
            pass

    def test_fresh_verifier_atomically_settles_original_native_task_once(self):
        from cryptography.hazmat.primitives import serialization
        from lab.archaioa.warrant import EffectWarrant

        broker = cas_broker.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        broker.workspace()
        self.addCleanup(broker.doCleanups)
        case = _prepare_native_task_case(self.root, broker)
        fx, tasks = case["fx"], case["tasks"]
        task, identity, capsule = case["task"], case["identity"], case["capsule"]
        plan_digest, adapter = case["plan_digest"], case["adapter"]
        binding, enrollment, request = case["binding"], case["enrollment"], case["request"]
        self.addCleanup(fx.close)
        self.addCleanup(tasks.close)
        started = case["started"]
        self.assertEqual("Unknown", started["outcome"]["contract_type"])
        self.assertEqual("UNKNOWN", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertEqual("HELD", fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX,
                              fx.journal._key(fx.warrant)).payload["state"],
        ))

        dispatches_before = len(broker.dispatches())
        broker.run_broker("witness_durable", crash=True)
        self.assertEqual(dispatches_before + 1, len(broker.dispatches()))
        settlement_epoch = fx.gov.start_epoch(fx.p(Capability.MANAGE))
        self.assertGreater(settlement_epoch, binding.core_epoch)
        held_task = tasks.request(fx.p(Capability.READ), "read_status", {"task_id": task.task_id})
        self.assertEqual("UNKNOWN", held_task["state"])
        held_intent = fx.journal.inspect(fx.p(Capability.READ), fx.warrant)
        self.assertEqual("Unknown", held_intent["outcome"]["contract_type"])

        core_state_path = str(fx.runner._factory.path)
        intent_row = fx.runner.run(TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION, fx.journal._key(fx.warrant)))
        intent_revision_before = intent_row.revision
        key_bytes = identity.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()).decode("ascii")
        recovery_config = self.root / "fresh-core-recovery.json"
        recovery_config.write_text(json.dumps({
            "core_state_path": core_state_path,
            "task_id": task.task_id,
            "warrant": fx.warrant.to_dict(),
            "capsule_signing_key": key_bytes,
            "request": request.to_wire(),
            "executor": enrollment.executor.executor,
            "executor_uid": enrollment.executor.uid,
            "executor_spki": enrollment.executor.spki,
            "key_epoch": enrollment.key_epoch,
            "valid_from": enrollment.valid_from,
            "valid_until": enrollment.valid_until,
            "revoked": enrollment.revoked,
            "broker_root": str(broker.root),
            "verify_now": NOW + 60,
            "broker_epoch": 7,
        }))
        recovery_config.chmod(0o600)

        # Close the original Core objects before a new process reopens its
        # durable task, warrant, journal and outbox from the disposable store.
        fx.close()
        checkout = Path(__file__).resolve().parents[1]
        lost_ack_process = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()),
             "recover-native-lost-ack", str(recovery_config)],
            capture_output=True, text=True, check=False, timeout=45, cwd=checkout,
            env={"PATH": os.defpath,
                 "PYTHONPATH": str(checkout) + ":" + str(checkout / "tests"),
                 "PYTHONNOUSERSITE": "1"},
        )
        self.assertEqual(86, lost_ack_process.returncode, lost_ack_process.stderr)
        self.assertIn('"ack_lost_after_durable_commit":true', lost_ack_process.stdout)
        self.assertEqual(1, len(broker.dispatches()))

        # Inspect the committed result after the child lost the Core response,
        # before another process retries reconciliation.
        fx_mid = Fixture(Path(core_state_path))
        fx_mid.warrant = EffectWarrant.from_dict(json.loads(
            recovery_config.read_text())["warrant"])
        self.assertEqual("Applied", fx_mid.journal.inspect(
            fx_mid.p(Capability.READ), fx_mid.warrant)["outcome"]["contract_type"])
        self.assertEqual("PENDING", fx_mid.runner.run(
            TransactionContext(fx_mid.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX,
                              fx_mid.journal._key(fx_mid.warrant)).payload["state"],
        ))
        self.assertEqual(intent_revision_before + 1, fx_mid.runner.run(
            TransactionContext(fx_mid.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION,
                              fx_mid.journal._key(fx_mid.warrant)).revision,
        ))
        identity_mid = Identity(serialization.load_pem_private_key(
            key_bytes.encode("ascii"), password=None))
        capsules_mid = CorePatchCapsules(fx_mid.journal, identity_mid, source_probe=lambda: None)
        tasks_mid = CoreCodingTasks(fx_mid.journal, capsules_mid)
        self.assertEqual("VERIFIED", tasks_mid.request(
            fx_mid.p(Capability.READ), "read_status", {"task_id": task.task_id})["state"])
        self.assertEqual(held_task["receipt_count"] + 1, tasks_mid.request(
            fx_mid.p(Capability.READ), "read_status", {"task_id": task.task_id})["receipt_count"])
        tasks_mid.close()
        fx_mid.close()

        fresh_process = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()),
             "recover-native", str(recovery_config)],
            capture_output=True, text=True, check=True, timeout=45, cwd=checkout,
            env={"PATH": os.defpath,
                 "PYTHONPATH": str(checkout) + ":" + str(checkout / "tests"),
                 "PYTHONNOUSERSITE": "1"},
        )
        fresh = json.loads(fresh_process.stdout)
        self.assertNotEqual(os.getpid(), fresh["pid"])
        self.assertEqual("Applied", fresh["intent_outcome"])
        self.assertEqual("VERIFIED", fresh["task_state"])
        self.assertTrue(all(pid not in (fresh["pid"], os.getpid())
                            for pid in fresh["verifier_pids"]))
        self.assertEqual(1, fresh["task_receipt_counts"][0] - held_task["receipt_count"])
        self.assertEqual([held_task["receipt_count"] + 1] * 2,
                         fresh["task_receipt_counts"])
        self.assertEqual(1, len(broker.dispatches()))

        fx2 = Fixture(Path(core_state_path))
        self.addCleanup(fx2.close)
        fx2.warrant = EffectWarrant.from_dict(json.loads(
            recovery_config.read_text())["warrant"])
        identity2 = Identity(serialization.load_pem_private_key(
            key_bytes.encode("ascii"), password=None))
        capsules2 = CorePatchCapsules(fx2.journal, identity2, source_probe=lambda: None)
        tasks2 = CoreCodingTasks(fx2.journal, capsules2)
        self.addCleanup(tasks2.close)
        adapter2 = CoreIntentAdapter(fx2.journal)
        request2 = BrokerRequest.from_wire(request.to_wire())
        root_fd = os.open(broker.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, root_fd)
        tasks2.native_witness_recovery_port = DisposableNativeTaskWitnessPort(
            adapter2, tasks2,
            lambda requested_task: ({
                "warrant": fx2.warrant, "request": request2,
                "enrollment": enrollment, "root_fd": root_fd,
                "trusted_device_id": request2.device_id, "now": NOW + 60,
                "core_epoch": request2.core_epoch, "broker_epoch": 7,
            } if requested_task == task.task_id else None),
        )
        repeated = tasks2.request(fx2.p(), "reconcile", {"task_id": task.task_id})
        self.assertEqual(fresh["task_receipt_counts"][0], repeated["task"]["receipt_count"])
        intent_row_after = fx2.runner.run(TransactionContext(fx2.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION, fx2.journal._key(fx2.warrant)))
        self.assertEqual(intent_revision_before + 1, intent_row_after.revision)
        self.assertEqual("Applied", fx2.journal.inspect(
            fx2.p(Capability.READ), fx2.warrant)["outcome"]["contract_type"])
        self.assertEqual("COMMITTED", fx2.gov.inspect(fx2.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertEqual("PENDING", fx2.journal.delivery(
            fx2.p(Capability.READ), fx2.warrant)["delivery_state"])
        self.assertEqual("VERIFIED", tasks2.request(
            fx2.p(Capability.READ), "read_status", {"task_id": task.task_id})["state"])
        self.assertEqual(1, len(broker.dispatches()))
        self.assertEqual(request.new_oid, git(broker.root / "repo", "rev-parse", request.exact_ref))
        self.assertEqual("Applied", fx2.journal.inspect(
            fx2.p(Capability.READ), fx2.warrant)["outcome"]["contract_type"])
        self.assertEqual("VERIFIED", tasks2.request(
            fx2.p(Capability.READ), "read_status", {"task_id": task.task_id})["state"])

    def test_same_oid_replaced_ref_inode_cannot_settle_original_native_task(self):
        broker = cas_broker.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        broker.workspace()
        self.addCleanup(broker.doCleanups)
        case = _prepare_native_task_case(self.root / "replacement-case", broker)
        fx, tasks = case["fx"], case["tasks"]
        self.addCleanup(fx.close)
        self.addCleanup(tasks.close)
        request, enrollment = case["request"], case["enrollment"]
        task, adapter = case["task"], case["adapter"]
        held_task = tasks.request(fx.p(Capability.READ), "read_status", {"task_id": task.task_id})
        self.assertEqual("UNKNOWN", held_task["state"])
        self.assertEqual("HELD", fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX,
                              fx.journal._key(fx.warrant)).payload["state"],
        ))
        broker.run_broker("witness_durable", crash=True)
        self.assertEqual(1, len(broker.dispatches()))
        fx.gov.start_epoch(fx.p(Capability.MANAGE))
        root_fd = os.open(broker.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, root_fd)
        tasks.native_witness_recovery_port = DisposableNativeTaskWitnessPort(
            adapter, tasks,
            lambda requested_task: ({
                "warrant": fx.warrant, "request": request,
                "enrollment": enrollment, "root_fd": root_fd,
                "trusted_device_id": request.device_id, "now": NOW + 60,
                "core_epoch": request.core_epoch, "broker_epoch": 7,
            } if requested_task == task.task_id else None),
        )
        _replace_ref_with_same_oid(broker.root, request)
        self.assertEqual(request.new_oid, git(broker.root / "repo", "rev-parse", request.exact_ref))
        with self.assertRaisesRegex(CoreAdapterError, "WITNESS_NOT_SETTLEMENT_GRADE"):
            tasks.request(fx.p(), "reconcile", {"task_id": task.task_id})
        current_task = tasks.request(fx.p(Capability.READ), "read_status", {"task_id": task.task_id})
        self.assertEqual("UNKNOWN", current_task["state"])
        self.assertEqual(held_task["receipt_count"], current_task["receipt_count"])
        self.assertEqual("Unknown", fx.journal.inspect(
            fx.p(Capability.READ), fx.warrant)["outcome"]["contract_type"])
        self.assertEqual("UNKNOWN", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertEqual("HELD", fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX,
                              fx.journal._key(fx.warrant)).payload["state"],
        ))
        self.assertEqual(1, len(broker.dispatches()))

    def test_same_oid_ref_replacement_after_verifier_before_settlement_is_held(self):
        broker = cas_broker.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        broker.workspace()
        self.addCleanup(broker.doCleanups)
        case = _prepare_native_task_case(self.root / "settlement-race-case", broker)
        fx, tasks = case["fx"], case["tasks"]
        self.addCleanup(fx.close)
        self.addCleanup(tasks.close)
        request, enrollment = case["request"], case["enrollment"]
        task, adapter = case["task"], case["adapter"]
        held_task = tasks.request(fx.p(Capability.READ), "read_status",
                                  {"task_id": task.task_id})
        broker.run_broker("witness_durable", crash=True)
        self.assertEqual(1, len(broker.dispatches()))
        fx.gov.start_epoch(fx.p(Capability.MANAGE))
        root_fd = os.open(broker.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, root_fd)
        tasks.native_witness_recovery_port = DisposableNativeTaskWitnessPort(
            adapter, tasks,
            lambda requested_task: ({
                "warrant": fx.warrant, "request": request,
                "enrollment": enrollment, "root_fd": root_fd,
                "trusted_device_id": request.device_id, "now": NOW + 60,
                "core_epoch": request.core_epoch, "broker_epoch": 7,
            } if requested_task == task.task_id else None),
        )
        verify = adapter._verify_disposable_fixture

        def verify_then_replace(principal, warrant, request_arg, enrollment_arg, **kwargs):
            result = verify(principal, warrant, request_arg, enrollment_arg, **kwargs)
            _replace_ref_with_same_oid(broker.root, request_arg)
            return result

        adapter._verify_disposable_fixture = verify_then_replace
        self.assertEqual(request.new_oid, git(broker.root / "repo", "rev-parse",
                                              request.exact_ref))
        with self.assertRaisesRegex(CoreAdapterError, "VERIFIED_READBACK_IDENTITY_CHANGED"):
            tasks.request(fx.p(), "reconcile", {"task_id": task.task_id})
        current_task = tasks.request(fx.p(Capability.READ), "read_status",
                                     {"task_id": task.task_id})
        self.assertEqual("UNKNOWN", current_task["state"])
        self.assertEqual(held_task["receipt_count"], current_task["receipt_count"])
        self.assertEqual("Unknown", fx.journal.inspect(
            fx.p(Capability.READ), fx.warrant)["outcome"]["contract_type"])
        self.assertEqual("UNKNOWN", fx.gov.inspect(fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertEqual("HELD", fx.runner.run(
            TransactionContext(fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX,
                              fx.journal._key(fx.warrant)).payload["state"],
        ))
        self.assertEqual(1, len(broker.dispatches()))

    def test_legacy_operation_without_v3_device_binding_cannot_enter_native_cold_port(self):
        # The v2 decoder remains available for historical inspection, but its
        # absent trusted device/physical linkage is explicit and non-executable.
        fixture = Fixture(self.root / "legacy-binding.json")
        self.addCleanup(fixture.close)
        align_warrant(fixture)
        make_native_zero_warrant(fixture)
        operation = {"operation_class": "GIT_COMMIT",
                     "target_fingerprint": fixture.warrant.target_fingerprint,
                     "expected_target_revision": fixture.warrant.expected_target_revision,
                     "payload": {"schema": "aioa.local-operation.v2",
                                 "principal_session_id": fixture.p().actor_session_id,
                                 "policy_epoch": fixture.warrant.lease_epoch,
                                 "profile": "DISPOSABLE_BARE_PATCH_V1",
                                 "plan_digest": "a" * 64}}
        fixture.operation = operation
        fixture.warrant = replace(fixture.warrant,
            operation_hash="sha256:" + canonical_sha256(operation), risk_reservation_id="paired-1")
        fixture.warrant = replace(fixture.warrant,
                                  approval_digest=approval_digest(fixture.warrant))
        fixture.request = ReservationRequest("paired-1", fixture.warrant.task_id, "fixture", MODEL,
                                             canonical_sha256(operation), 0, 5)
        fixture.journal = CoreIntentJournal(fixture.ledger, fixture.gov, verifier=fixture.verify)
        fixture.init()
        fixture.journal.start_local_zero(fixture.p(), fixture.warrant, operation, fixture.request)
        binding = CoreIntentAdapter(fixture.journal).capture_start(fixture.p(), fixture.warrant)
        self.assertIsNone(binding.device_id)
        self.assertIsNone(binding.repository)

    def test_actual_native_dispatch_fails_closed_without_shared_gate_and_v3(self):
        route = CoreRemoteGitRoute.__new__(CoreRemoteGitRoute)
        route.native_access = object()
        route.journal = SimpleNamespace(runner=SimpleNamespace(execution_gate=None))
        with self.assertRaisesRegex(ValueError, "NATIVE_STOP_GATE_REQUIRED"):
            route._dispatch_local_patch(
                None, None,
                {"payload": {"schema": "aioa.local-operation.v2"}},
                lambda: None, None,
            )

    def test_native_route_construction_rejects_missing_gate_before_start(self):
        fixture = Fixture(self.root / "native-route-no-gate.json")
        self.addCleanup(fixture.close)
        capsules = CorePatchCapsules(
            fixture.journal, Identity(ec.generate_private_key(ec.SECP256R1())),
            source_probe=lambda: None)
        store_path = fixture.runner._factory.path
        before = store_path.read_bytes() if store_path.exists() else None
        with self.assertRaisesRegex(ValueError, "NATIVE_STOP_GATE_REQUIRED"):
            CoreRemoteGitRoute.for_local_patch(
                fixture.p(), fixture.journal,
                capsules=capsules, preparation=None, profile=None,
                source_snapshot=None, source_repository=self.root,
                target_repository=self.root, check=lambda: None,
                target_guard=lambda: None, native_access=object(),
            )
        self.assertEqual(before, store_path.read_bytes() if store_path.exists() else None)

    def test_native_local_operation_v3_records_exact_existing_ref_parent(self):
        repository = self.root / "bare-target"
        repository.mkdir(mode=0o700)
        git(repository, "init", "--bare", "--template=")
        (repository / "refs").chmod(0o755)
        (repository / "refs" / "heads").chmod(0o755)
        ref_parent = repository / "refs" / "heads" / "aioa"
        ref_parent.mkdir(mode=0o755)
        repo_stat = repository.stat()
        gate_dir = self.root / "gate-v3"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir))
        self.addCleanup(gate.close)
        route = CoreRemoteGitRoute.__new__(CoreRemoteGitRoute)
        route.target_repository = repository
        route.plan = SimpleNamespace(
            target_identity=(repo_stat.st_dev, repo_stat.st_ino, "storage-digest"),
            ref="refs/heads/aioa/native69-fixture", commit_sha="a" * 40,
            tree_sha="b" * 40, target_fingerprint="sha256:" + "c" * 64,
            source=SimpleNamespace(source_base_sha="d" * 40))
        route.capsule = SimpleNamespace(digest="e" * 64, patchset_sha256="f" * 64)
        route.native_stop_cas_gate = gate
        route.native_device_id = "qualified-fixture-device"
        operation = route._local_patch_operation("session-fixture", 3, "1" * 64)
        payload = operation["payload"]
        self.assertEqual("aioa.local-operation.v3", payload["schema"])
        self.assertEqual("qualified-fixture-device", payload["device_id"])
        self.assertEqual((repo_stat.st_dev, repo_stat.st_ino),
                         (payload["repository_dev"], payload["repository_inode"]))
        info = ref_parent.stat()
        self.assertEqual((info.st_dev, info.st_ino),
                         (payload["ref_directory_dev"], payload["ref_directory_inode"]))

    def test_ref_link_checks_authorized_parent_identity_and_rejects_group_write(self):
        parent = self.root / "safe-ref-parent"
        parent.mkdir(mode=0o700)
        parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, parent_fd)
        gate_dir = self.root / "gate-parent-check"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir))
        self.addCleanup(gate.close)
        info = os.fstat(parent_fd)
        wrong = (info.st_dev, info.st_ino + 1)
        with self.assertRaisesRegex(ValueError, "GIT_REF_DIRECTORY_CHANGED"):
            LinuxPublish.publish(parent_fd, lambda: None, gate,
                                 expected_parent_identity=wrong)
        self.assertFalse((parent / "ref").exists())

        repository = self.root / "unsafe-target"
        repository.mkdir(mode=0o700)
        git(repository, "init", "--bare", "--template=")
        target_ref_dir = repository / "refs" / "heads" / "unsafe"
        target_ref_dir.mkdir(mode=0o770)
        root_fd = os.open(repository, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, root_fd)
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        with self.assertRaisesRegex(ValueError, "GIT_STORAGE_OWNER_OR_MOUNT"):
            LinuxSandboxBroker._git_directory(
                root_fd, ("refs", "heads", "unsafe"), create=False, cancel=None)

    def test_git_plumbing_parent_replacement_is_rejected_before_lock_creation(self):
        from runtime.mission.git_publish import LOCAL_GIT_SHA256
        from runtime.mission.sandbox_linux import LinuxSandboxBroker, git_storage_identity
        from contextlib import nullcontext

        broker = cas_broker.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        broker.workspace()
        self.addCleanup(broker.doCleanups)
        repository = broker.root / "repo"
        repository_fd = os.open(repository,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, repository_fd)
        parent = repository / "refs" / "heads"
        parent_info = parent.stat()
        expected_parent = (parent_info.st_dev, parent_info.st_ino)
        expected_storage = git_storage_identity(repository_fd)
        moved = parent.with_name("heads.rh04-original")
        target = "refs/heads/native69-parent-race"
        ref_lock = parent / (target.rsplit("/", 1)[1] + ".lock")
        original_directory = LinuxSandboxBroker._git_directory
        replaced = False

        def replace_when_target_parent_is_open(parent_fd, components, *, create, cancel):
            nonlocal replaced
            info = os.fstat(parent_fd)
            if (not replaced and (info.st_dev, info.st_ino) == expected_parent
                    and tuple(components) == () and create is False):
                os.rename(parent, moved)
                os.mkdir(parent, 0o755)
                replaced = True
            return original_directory(parent_fd, components, create=create, cancel=cancel)

        try:
            with patch.object(LinuxSandboxBroker, "_git_directory",
                              side_effect=replace_when_target_parent_is_open):
                with self.assertRaisesRegex(ValueError, "GIT_STORAGE_CHANGED"):
                    LinuxSandboxBroker._git_plumbing(
                        repository_fd,
                        ("update-ref", target, broker.request.new_oid, "0" * 40),
                        git_sha256=LOCAL_GIT_SHA256,
                        expected_storage=expected_storage,
                        expected_ref_directory=expected_parent,
                        before_ref_link=lambda: None,
                        before_ref_link_guard=lambda: nullcontext(),
                    )
            self.assertTrue(replaced)
            self.assertFalse(ref_lock.exists())
            self.assertFalse((repository / "packed-refs.lock").exists())
            self.assertEqual([], list(parent.iterdir()))
            self.assertEqual([], list(moved.iterdir()))
        finally:
            if parent.exists():
                parent.rmdir()
            if moved.exists():
                os.rename(moved, parent)
        self.assertFalse((parent / (target.rsplit("/", 1)[1] + ".lock")).exists())

    def test_git_plumbing_v3_ref_link_ack_cleans_both_git_locks(self):
        from runtime.mission.git_publish import LOCAL_GIT_SHA256
        from runtime.mission.sandbox_linux import LinuxSandboxBroker, git_storage_identity

        broker = cas_broker.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        broker.workspace()
        self.addCleanup(broker.doCleanups)
        repository = broker.root / "repo"
        repository_fd = os.open(repository,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        self.addCleanup(os.close, repository_fd)
        target = broker.request.exact_ref
        parent = repository / "refs" / "heads"
        parent_info = parent.stat()
        expected_parent = (parent_info.st_dev, parent_info.st_ino)
        gate_dir = self.root / "gate-plumbing-success"
        gate_dir.mkdir(mode=0o700)
        gate = NativeStopCasGate(str(gate_dir))
        self.addCleanup(gate.close)

        response = LinuxSandboxBroker._git_plumbing(
            repository_fd,
            ("update-ref", target, broker.request.new_oid, "0" * 40),
            git_sha256=LOCAL_GIT_SHA256,
            expected_storage=git_storage_identity(repository_fd),
            expected_ref_directory=expected_parent,
            before_ref_link=lambda: None,
            before_ref_link_guard=gate,
        )
        self.assertEqual(b"", response)
        self.assertEqual((broker.request.new_oid + "\n").encode(),
                         (repository / Path(target)).read_bytes())
        self.assertFalse((repository / "packed-refs.lock").exists())
        self.assertFalse((parent / (target.rsplit("/", 1)[1] + ".lock")).exists())


class LinuxPublish:
    """Small invocation of the real descriptor-bound exclusive link helper."""
    @staticmethod
    def publish(parent_fd, authorize, gate, *, expected_parent_identity=None):
        from runtime.mission.sandbox_linux import LinuxSandboxBroker
        from runtime.providers.exact import CancellationToken
        return LinuxSandboxBroker._git_publish_new(
            parent_fd, "ref", b"fixture-oid\n", cancel=CancellationToken(),
            before_ref_link=authorize, before_ref_link_guard=gate,
            expected_parent_identity=expected_parent_identity)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] in ("recover-native", "recover-native-lost-ack"):
        _recover_native_task_from_restarted_core(
            sys.argv[2], lose_settlement_ack=sys.argv[1] == "recover-native-lost-ack")
    else:
        unittest.main()
