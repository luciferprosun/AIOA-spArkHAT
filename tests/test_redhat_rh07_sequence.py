"""Disposable same-UID tests of the RH-07 IPC ordering and one Core settlement."""

import json
import os
import socket
import subprocess
import sys
import threading
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.providers.exact import CancellationToken
from runtime.red_hat.broker_protocol import Peer, ProtocolError, authenticate, digest, send_frame
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.executor_custody import ExecutorRoles, _read_signer_fd, load_broker_signer
from runtime.red_hat.sequenced_boundary import (
    CoreReleaseClient, handle_fixture_release, serve_sequenced_fixture_once,
)
from runtime.red_hat.sequencer import SequenceClient, SequencedCoreGate, bind_fixture_runner, serve_sequencer
from test_redhat_broker_protocol import NOW
import test_redhat_native_cas_broker as cas
import test_redhat_rh06_authenticated_boundary as rh06


def peer(pid):
    return Peer(pid, os.getuid(), os.getgid())


def child(root, mode, name, stage):
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(root / name))
        listener.listen(8)
        listener.settimeout(5)
        print("READY", flush=True)
        config = json.loads(sys.stdin.readline())
        if mode == "sequence":
            anchor = cas.fd(root / "sequencer")

            def sequence_fault(point):
                if point == stage:
                    os._exit(74)
                if point == "control_waiting":
                    print("CONTROL_WAITING", flush=True)

            try:
                serve_sequencer(listener, directory=anchor, core_peer=Peer(**config["core"]),
                                broker_peer=Peer(**config["broker"]), epoch=1, timeout=3,
                                active_timeout=config.get("active_timeout", 6),
                                fault=sequence_fault, enabled=True)
            finally:
                os.close(anchor)
            return

        spec = json.loads((root / "rh06-spec.json").read_text())
        expected = NativeExecutionBindingV1.from_wire(spec["binding"])
        core = Peer(**config["core"])
        enrollment = rh06.enrolled(expected, spec)
        ref_parent = (root / "repo/refs/heads").stat()
        real_link = os.link

        def count_link(source, name, *, dst_dir_fd, follow_symlinks):
            info = os.fstat(dst_dir_fd)
            if (info.st_dev, info.st_ino, name) == (
                ref_parent.st_dev, ref_parent.st_ino, expected.request.exact_ref.rsplit("/", 1)[-1],
            ):
                with (root / "dispatches").open("a") as out:
                    out.write(f"{os.getpid()}\n")
                    out.flush()
                    os.fsync(out.fileno())
            return real_link(source, name, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)

        def broker_fault(point):
            if stage == point:
                os._exit(74)

        anchor = cas.fd(root)
        try:
            with patch("os.link", count_link):
                serve_sequenced_fixture_once(
                    listener, sequence=SequenceClient(config["sequence_path"], Peer(**config["sequence"]), 1),
                    release=CoreReleaseClient(config["release_path"], core, spec["core_spki"]),
                    root_fd=anchor, expected=expected, enrollment=enrollment,
                    identity=rh06.load_key(root / "fixture-key"), core_peer=core,
                    core_spki=spec["core_spki"], core_epoch=expected.request.core_epoch,
                    broker_epoch=expected.request.broker_epoch, clock=lambda: NOW,
                    fault=broker_fault, enabled=True)
        finally:
            os.close(anchor)


class SequencedBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = rh06.AuthenticatedBoundaryTests("test_default_off_and_durable_start_binding")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.fx, self.root = self.fixture.fx, self.fixture.root
        self.principal = self.fx.p()
        self.work_cancel = CancellationToken()
        self.anchor = self.root / "sequencer"
        self.anchor.mkdir(mode=0o700)
        self.seq_number = 0
        self.broker_number = 0
        self.listener = socket.socket(socket.AF_UNIX)
        self.addCleanup(self.listener.close)
        self.release_path = str(self.root / "release.sock")
        self.listener.bind(self.release_path)
        self.listener.listen(1)
        self.listener.settimeout(4)

    @property
    def marker(self):
        return self.anchor / "outstanding"

    def start(self, mode, name, stage):
        process = subprocess.Popen([sys.executable, "-B", __file__, str(self.root), mode, name, stage],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(cas.CasBrokerTests.reap, process)
        self.assertEqual("READY", self.fixture.broker.read_line(process))
        return process, str(self.root / name)

    @staticmethod
    def configure(process, **value):
        process.stdin.write(json.dumps(value) + "\n")
        process.stdin.flush()

    def start_sequencer(self, broker_peer, stage="", *, active_timeout=6):
        self.seq_number += 1
        seq, endpoint = self.start("sequence", f"seq-{self.seq_number}.sock", stage)
        self.configure(seq, core=asdict(peer(os.getpid())), broker=asdict(broker_peer),
                       active_timeout=active_timeout)
        return seq, SequenceClient(endpoint, peer(seq.pid), 1)

    def setup_triplet(self, *, stage="", seq_stage="", active_timeout=6):
        self.broker_number += 1
        broker, broker_path = self.start("broker", f"pub-{self.broker_number}.sock", stage)
        seq, client = self.start_sequencer(peer(broker.pid), seq_stage, active_timeout=active_timeout)
        gate = SequencedCoreGate(client, enabled=True)
        bind_fixture_runner(self.fx.runner, gate, enabled=True)

        def retire_fixture_binding():
            # This disposable Core is no longer in use when cleanup runs.
            del self.fx.runner.execution_gate
            del self.fx.runner._admission.execution_gate

        self.addCleanup(retire_fixture_binding)
        self.configure(broker, sequence_path=client.endpoint, sequence=asdict(client.peer),
                       release_path=self.release_path, core=asdict(peer(os.getpid())))
        return broker, broker_path, seq, client, gate

    def submit(self, broker, endpoint):
        stream = socket.socket(socket.AF_UNIX)
        self.addCleanup(stream.close)
        stream.settimeout(4)
        stream.connect(endpoint)
        authenticate(stream, peer(broker.pid))
        send_frame(stream, self.fixture.envelope)
        return stream

    def release(self, broker, client, gate, *, fault=lambda _: None):
        case = self.fixture.case

        def require_owned_work():
            task = self.fixture.tasks.request(self.fx.p(Capability.READ), "read_status",
                                              {"task_id": case["task"].task_id})
            if self.fixture.tasks.closed or self.work_cancel.cancelled or task["state"] != "UNKNOWN":
                raise ValueError("RH07_TEST_TASK_STATE")

        handle_fixture_release(
            self.listener, sequence=client, gate=gate, broker_peer=peer(broker.pid),
            signer=self.fixture.core, expected=self.fixture.binding, adapter=case["adapter"],
            principal=self.principal, warrant=self.fx.warrant, enrollment=case["enrollment"],
            trusted_device_id=self.fixture.binding.request.device_id,
            require_owned_work=require_owned_work, clock=lambda: NOW, fault=fault, enabled=True)

    def revoke(self):
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)

    def assert_fenced(self, client):
        with self.assertRaises((ValueError, OSError)):
            with client.hold():
                self.fail("ambiguous lease was transferred")

    def assert_link_count(self, count):
        self.assertEqual(count, len(self.fixture.broker.dispatches()))
        self.assertEqual(bool(count), self.fixture.ref.exists())

    def test_stale_export_rejected_after_durable_core_revocation(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        # Sign first, then revoke through the existing Core ledger under the
        # same sequencer that the broker must enter for its final release.
        self.revoke()
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_kill_commits_before_broker_release(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        self.fx.gov.set_kill(self.fx.p(Capability.MANAGE), True)
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_epoch_commits_before_broker_release(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        next_epoch = self.fx.gov.start_epoch(self.fx.p(Capability.MANAGE))
        self.assertGreater(next_epoch, self.fixture.binding.request.core_epoch)
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_money_policy_uses_control_slot_and_invalidates_export(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        governor = self.fx.gov
        review = governor.money_policy_review(self.fx.p(Capability.READ),
            dict.fromkeys(("task_limit", "owner_provider_limit", "global_limit"), 100), request_id="rh07-policy")
        observed = []
        def observe_authority():
            observed.append(self.marker.exists())
        applied = governor.apply_money_policy(self.fx.p(Capability.MANAGE), review,
                                               authority_check=observe_authority)
        self.assertEqual([True, True], observed)
        self.assertGreater(applied["epoch"], self.fixture.binding.request.core_epoch)
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_capacity_operator_apply_persists_epoch_under_control_slot(self):
        import nz13_native_foundation_support as native

        owner, _ = native.new_host(self)
        native.fixture_tls(owner)
        native.initialize(owner)
        review = native.review(owner)
        native.approve(owner, review)
        _, client = self.start_sequencer(peer(os.getpid() + 1))
        gate = SequencedCoreGate(client, enabled=True)
        bind_fixture_runner(owner.runner, gate, enabled=True)
        self.addCleanup(delattr, owner.runner, "execution_gate")
        self.addCleanup(delattr, owner.core, "execution_gate")
        governor = owner.foundation.governor
        persist = governor._write
        observations = []
        def observed_write(*args, **kwargs):
            observations.append(self.marker.exists())
            return persist(*args, **kwargs)
        with patch.object(governor, "_write", side_effect=observed_write):
            receipt = native.apply(owner, review)
        self.assertEqual("APPLIED", receipt["status"])
        self.assertEqual([True], observations)
        self.assertFalse(self.marker.exists())
        self.assertEqual("READBACK_ONLY", native.apply(owner, review)["status"])

    def test_task_drain_forbids_the_exported_operation(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        self.fixture.tasks.drain(0)
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def _cancel_before_publication(self, action):
        task_id = self.fixture.case["task"].task_id
        self.fixture.tasks._effects[task_id] = self.work_cancel
        self.addCleanup(self.fixture.tasks._effects.pop, task_id, None)
        broker, endpoint, _, client, gate = self.setup_triplet()
        self.fixture.tasks.request(self.fx.p(Capability.MANAGE), action,
                                   {"task_id": self.fixture.case["task"].task_id})
        self.assertTrue(self.work_cancel.cancelled)
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_task_stop_cancels_owned_work_before_final_release(self):
        self._cancel_before_publication("stop")

    def test_task_cancel_cancels_owned_work_before_final_release(self):
        self._cancel_before_publication("cancel")

    def test_core_close_forbids_exported_operation(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        self.fx.core.close()
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)

    def test_runner_close_removes_release_authority(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        self.fx.runner.close()
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_link_count(0)

    def test_no_sequencer_io_inside_a_core_transaction(self):
        _, client = self.start_sequencer(peer(os.getpid() + 1))
        def read(tx):
            with self.assertRaisesRegex(ProtocolError, "RH07_IPC_IN_TRANSACTION"):
                with client.hold():
                    self.fail("slot granted inside a transaction")
        self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ), Capability.READ), read)
        self.assertFalse(self.marker.exists())

    def test_parent_replacement_during_release_ipc_refuses_link(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        stream = self.submit(broker, endpoint)
        parent = self.root / "repo/refs/heads"
        moved = parent.with_name("heads-before-release")

        def replace_parent(_):
            parent.rename(moved)
            parent.mkdir(mode=0o755)

        self.release(broker, client, gate, fault=replace_parent)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assertFalse((moved / self.fixture.ref.name).exists())
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_publisher_releases_once_before_contending_core_revoke(self):
        broker, endpoint, seq, client, gate = self.setup_triplet()
        stream = self.submit(broker, endpoint)
        errors = []

        def revoke():
            try:
                self.revoke()
                self.assertTrue(self.fixture.ref.exists())
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=revoke)

        def wait_for_stop(point):
            thread.start()
            self.assertEqual("CONTROL_WAITING", self.fixture.broker.read_line(seq))
            self.assertFalse(self.fixture.ref.exists())
            self.assertTrue(self.marker.exists())

        self.release(broker, client, gate, fault=wait_for_stop)
        self.assertEqual({"ack": True}, self.fixture.broker.finish(broker, stream))
        thread.join(timeout=8)
        self.assertFalse(thread.is_alive())
        self.assertEqual([], errors)
        self.assert_link_count(1)
        self.fixture.assert_held()

    def test_release_reply_loss_denies_link_and_fences_outstanding(self):
        broker, endpoint, _, client, gate = self.setup_triplet()
        stream = self.submit(broker, endpoint)

        def lose_reply(_):
            raise OSError("synthetic release reply loss")

        with self.assertRaises(OSError):
            self.release(broker, client, gate, fault=lose_reply)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assert_fenced(client)
        self.assertTrue(self.marker.exists())
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_sequencer_death_before_grant_retains_fence_after_restart(self):
        broker, endpoint, seq, _, _ = self.setup_triplet(seq_stage="slot_durable")
        stream = self.submit(broker, endpoint)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assertEqual(74, seq.wait(timeout=8))
        self.assertTrue(self.marker.exists())
        _, restarted = self.start_sequencer(peer(broker.pid))
        self.assert_fenced(restarted)
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_stop_timeout_does_not_commit_while_publisher_remains_capable(self):
        broker, endpoint, _, client, gate = self.setup_triplet(active_timeout=2)
        stream = self.submit(broker, endpoint)
        errors = []

        def revoke():
            try:
                with self.assertRaises((OSError, ValueError)):
                    self.revoke()
            except BaseException as error:
                errors.append(error)

        control = threading.Thread(target=revoke)

        def wait_past_slot(_):
            control.start()
            control.join(timeout=5)
            self.assertFalse(control.is_alive())
            self.assertTrue(self.marker.exists())

        with self.assertRaises((ValueError, OSError)):
            self.release(broker, client, gate, fault=wait_past_slot)
        # The broker's bounded release receive may close while the handler is paused.
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assertEqual([], errors)
        revoked = self.fx.runner.run(
            TransactionContext(self.fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.APPROVAL, self.fx.ledger._key(self.fx.warrant)).payload["revoked"],
        )
        self.assertIs(revoked, False)
        self.assert_fenced(client)
        self.assert_link_count(0)
        self.fixture.assert_held()

    def test_postlink_crash_keeps_held_and_refuses_second_attempt(self):
        broker, endpoint, seq, client, gate = self.setup_triplet(stage="effect_synced")
        stream = self.submit(broker, endpoint)
        self.release(broker, client, gate)
        self.fixture.broker.finish(broker, stream, crash=True)
        self.assert_fenced(client)
        seq.kill()
        seq.wait(timeout=8)
        _, restarted = self.start_sequencer(peer(broker.pid))
        self.assert_fenced(restarted)
        # Restart the existing attempt consumer as well. Same binding cannot link again.
        self.assertFalse(self.fixture.dispatch())
        with self.assertRaisesRegex(ValueError, "WITNESS_NOT_SETTLEMENT_GRADE"):
            self.fixture.recover()
        self.assert_link_count(1)
        self.fixture.assert_held()

    def test_postwitness_lost_ack_settles_in_fresh_core_once(self):
        broker, endpoint, _, client, gate = self.setup_triplet(stage="witness_durable")
        stream = self.submit(broker, endpoint)
        before = self.fixture.revision()
        self.release(broker, client, gate)
        self.fixture.broker.finish(broker, stream, crash=True)
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.fixture.dispatch())
        first, second = self.fixture.recover(), self.fixture.recover()
        self.assertEqual("VERIFIED", first["task"]["state"])
        self.assertEqual("Applied", first["intent"]["outcome"]["contract_type"])
        self.assertEqual(first["task"], second["task"])
        self.assertEqual(before + 1, self.fixture.revision())
        self.assert_link_count(1)

    def test_lost_sequence_close_ack_does_not_redispatch_durable_effect(self):
        broker, endpoint, seq, client, gate = self.setup_triplet(seq_stage="slot_closed")
        stream = self.submit(broker, endpoint)
        before = self.fixture.revision()
        self.release(broker, client, gate)
        self.assertEqual({"ack": False}, self.fixture.broker.finish(broker, stream))
        self.assertEqual(74, seq.wait(timeout=8))
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.fixture.dispatch())
        first = self.fixture.recover()
        self.assertEqual("VERIFIED", first["task"]["state"])
        self.assertEqual(before + 1, self.fixture.revision())
        self.assert_link_count(1)

    def test_wrong_sequence_peer_epoch_and_token_are_denied(self):
        _, client = self.start_sequencer(peer(os.getpid() + 1))
        with self.assertRaises(ProtocolError):
            with client.hold(binding=digest(self.fixture.binding.to_wire())):
                self.fail("Core peer got publication slot")
        with self.assertRaises(ProtocolError):
            with replace(client, epoch=2).hold():
                self.fail("stale epoch got slot")
        with self.assertRaises(ProtocolError):
            client.check_publisher(digest(self.fixture.binding.to_wire()), "a" * 64)
        self.assertFalse(self.marker.exists())
        self.assert_link_count(0)

    def test_core_gate_rejects_inherited_process_state(self):
        _, client = self.start_sequencer(peer(os.getpid() + 1))
        gate = SequencedCoreGate(client, enabled=True)
        gate._thread.owns = True
        with patch("os.getpid", return_value=os.getpid() + 1):
            with self.assertRaisesRegex(ProtocolError, "RH07_SEQUENCE_FORK"):
                with gate.hold():
                    self.fail("inherited gate skipped authentication")
        self.assertFalse(self.marker.exists())

    def test_signer_fd_reads_valid_private_fixture_file(self):
        key = self.root / "fixture-key"
        key.chmod(0o400)
        # Set old access time so a relatime filesystem may update it on pread.
        os.utime(key, ns=(0, key.stat().st_mtime_ns))
        fd = os.open(key, os.O_RDONLY | os.O_CLOEXEC)
        self.addCleanup(os.close, fd)
        self.assertTrue(_read_signer_fd(fd, os.getuid()) == key.read_bytes())

    def test_custody_rejects_role_overlap_wrong_process_or_writable_fd(self):
        with self.assertRaisesRegex(ProtocolError, "RH07_DISTINCT_ROLE_UIDS"):
            ExecutorRoles(100, 100, 102, 101)
        roles = ExecutorRoles(100, 101, 102, 101)
        if os.getuid() == roles.broker_uid:
            roles = ExecutorRoles(100, 103, 102, 103)
        key = self.root / "fixture-key"
        fd = os.open(key, os.O_RDWR | os.O_CLOEXEC)
        self.addCleanup(os.close, fd)
        with self.assertRaisesRegex(ProtocolError, "RH07_SIGNER_FD"):
            _read_signer_fd(fd, os.getuid())
        with self.assertRaisesRegex(ProtocolError, "RH07_BROKER_ROLE"):
            load_broker_signer(fd, roles, self.fixture.case["enrollment"],
                               key_epoch=3, now=NOW, enabled=True)


if __name__ == "__main__":
    child(Path(sys.argv[1]), *sys.argv[2:])
