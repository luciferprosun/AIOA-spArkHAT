"""Offline RH-06 fixture tests. Each role runs in its own process, under one UID."""

import copy
import json
import os
import secrets
import socket
import subprocess
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.coding_tasks import CoreCodingTasks
from runtime.mission.patch_capsule import CorePatchCapsules
from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.authenticated_boundary import (
    AUTHORIZATION, READBACK, AuthenticatedFixtureRecoveryPort, authorize_fixture,
    serve_authenticated_fixture_once, serve_verifier_fixture_once,
)
from runtime.red_hat.broker_protocol import (
    AttemptGuard, BrokerRequest, Peer, ProtocolError, authenticate, digest, read_frame, send_frame,
)
from runtime.red_hat.core_adapter import CoreAdapterError, CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import NativeExecutionBindingV1, physical_context
from runtime.red_hat.verifier import sign
from runtime.red_hat.witness import RegisteredExecutor
from test_redhat_broker_protocol import NOW
import test_redhat_native_cas_broker as cas
import test_redhat_rh04_native_task_gate as rh04


def identity():
    return Identity(ec.generate_private_key(ec.SECP256R1()))


def save_key(path, signer):
    cas.put(path, signer.key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()), 0o600)


def load_key(path):
    return Identity(serialization.load_pem_private_key(path.read_bytes(), password=None))


def enrolled(binding, spec):
    req = binding.request
    return ExecutorEnrollment(RegisteredExecutor(req.executor_id, spec["broker_uid"],
                              spec["broker_spki"]), req.key_epoch, NOW - 60, NOW + 600)


def launch(root, role, filename, stage):
    spec = json.loads((root / "rh06-spec.json").read_text())
    binding = NativeExecutionBindingV1.from_wire(spec["binding"])
    enrollment = enrolled(binding, spec)
    peer = Peer(**spec["peer"])
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(root / filename))
        listener.listen(1)
        listener.settimeout(5)
        print("READY", flush=True)
        anchor = cas.fd(root)
        try:
            if role == "verifier":
                verifier = load_key(root / "verifier-key")
                if stage == "replay":
                    with listener.accept()[0] as stream:
                        query = read_frame(stream)
                        payload = {"schema": READBACK, "binding_digest": query["binding_digest"],
                                   "challenge": "0" * 64, "facts": {}, "observed_at": NOW + 60}
                        send_frame(stream, {"payload": payload, "signature": sign(verifier, payload)})
                else:
                    serve_verifier_fixture_once(
                        listener, root_fd=anchor, binding=binding, enrollment=enrollment,
                        identity=verifier, core_peer=peer, core_spki=spec["core_spki"],
                        now=NOW + 60, enabled=True)
                return

            def fault(point):
                if point == stage:
                    os._exit(74)
                if stage == "broker_first" and point == "release_acquired":
                    print("PAUSED", flush=True)
                    assert sys.stdin.readline().strip() == "CONTINUE"
                if stage == "stop_first" and point == "before_release":
                    state = cas.fd(root / "state")
                    try:
                        AttemptGuard(state).stop()
                    finally:
                        os.close(state)

            repo = root / "repo"
            ref_parent = (repo / "refs/heads").stat()
            actual_link = os.link

            def count_link(source, name, *, dst_dir_fd, follow_symlinks):
                row = os.fstat(dst_dir_fd)
                if (row.st_dev, row.st_ino, name) == (
                    ref_parent.st_dev, ref_parent.st_ino, binding.request.exact_ref.rsplit("/", 1)[-1],
                ):
                    with (root / "dispatches").open("a", encoding="ascii") as count:
                        count.write(f"{os.getpid()}\n")
                        count.flush()
                        os.fsync(count.fileno())
                return actual_link(source, name, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)

            with patch("os.link", count_link):
                serve_authenticated_fixture_once(
                    listener, root_fd=anchor, expected=binding, enrollment=enrollment,
                    identity=load_key(root / "fixture-key"), core_peer=peer, core_spki=spec["core_spki"],
                    core_epoch=binding.request.core_epoch, broker_epoch=binding.request.broker_epoch,
                    clock=lambda: NOW, fault=fault, enabled=True)
        finally:
            os.close(anchor)


def recover_core(root):
    config = json.load(sys.stdin)
    spec = json.loads((root / "rh06-spec.json").read_text())
    binding = NativeExecutionBindingV1.from_wire(spec["binding"])
    request = binding.request
    enrollment = enrolled(binding, spec)
    if config["enrollment_expires_early"]:
        enrollment = replace(enrollment, valid_until=NOW + 50)
    task_id = config["task_id"]
    fx = rh04.Fixture(root / "native-core.json")
    tasks = None
    anchor = cas.fd(root)
    try:
        fx.warrant = EffectWarrant.from_dict(config["warrant"])
        capsules = CorePatchCapsules(fx.journal, load_key(root / "capsule-key"), source_probe=lambda: None)
        tasks = CoreCodingTasks(fx.journal, capsules)
        tasks.native_witness_recovery_port = AuthenticatedFixtureRecoveryPort(
            CoreIntentAdapter(fx.journal), tasks,
            lambda requested: {
                "warrant": fx.warrant, "request": request, "enrollment": enrollment,
                "root_fd": anchor, "trusted_device_id": request.device_id,
                "now": NOW + 60, "core_epoch": request.core_epoch, "broker_epoch": request.broker_epoch,
            } if requested == task_id else None,
            endpoint=config["endpoint"], verifier_peer=Peer(**config["verifier_peer"]),
            verifier_spki=config["verifier_spki"], core_spki=spec["core_spki"], enabled=True)
        result = tasks.request(fx.p(), "reconcile", {"task_id": task_id})
        print(json.dumps({"pid": os.getpid(), "result": result}))
    except (CoreAdapterError, ProtocolError) as error:
        print(json.dumps({"pid": os.getpid(), "error": type(error).__name__, "code": str(error)}))
    finally:
        os.close(anchor)
        if tasks is not None:
            tasks.close()
        fx.close()


class AuthenticatedBoundaryTests(unittest.TestCase):
    native_plan_ref = False

    def setUp(self):
        self.broker = cas.CasBrokerTests("test_lost_ack_one_settlement_zero_actual_redispatch")
        self.addCleanup(self.broker.doCleanups)
        self.broker.workspace()
        self.root = self.broker.root
        self.anchor = cas.fd(self.root)
        self.addCleanup(os.close, self.anchor)
        req = self.broker.request
        if self.native_plan_ref:
            values = asdict(req)
            values.pop("commit_permit_digest")
            values["broker_epoch"] = 1
            self.broker.request = req = BrokerRequest.for_fixture(**values)
        metadata = {**physical_context(self.anchor), "nonce": secrets.token_hex(32),
                    **{key: getattr(req, key) for key in (
                        "executor_id", "executor_key_id", "key_epoch", "broker_epoch",
                        "issued_at", "expires_at",
                    )}}
        self.case = rh04._prepare_native_task_case(self.root, self.broker, rh06_fixture=metadata,
                                                   native_plan_ref=self.native_plan_ref)
        self.fx, self.tasks = self.case["fx"], self.case["tasks"]
        self.addCleanup(self.fx.close)
        self.addCleanup(self.tasks.close)
        self.core = identity()
        self.verifier = identity()
        save_key(self.root / "verifier-key", self.verifier)
        save_key(self.root / "capsule-key", self.case["identity"])
        self.args = {"trusted_device_id": req.device_id, "now": NOW, "broker_epoch": req.broker_epoch}
        self.binding, self.envelope = self.authorize(enabled=True)
        self.spec = {"binding": self.binding.to_wire(), "core_spki": self.core.spki,
                     "broker_uid": os.getuid(), "broker_spki": self.broker.enrollment.spki,
                     "peer": asdict(Peer(os.getpid(), os.getuid(), os.getgid()))}
        self.spec_path = self.root / "rh06-spec.json"
        self.spec_path.write_text(json.dumps(self.spec))
        self.ref = self.root / "repo" / self.binding.request.exact_ref
        self.index = 0

    def authorize(self, **flags):
        return authorize_fixture(self.case["adapter"], self.fx.p(), self.fx.warrant,
                                 self.case["enrollment"], self.core, **self.args, **flags)

    def child(self, role, stage=""):
        self.index += 1
        name = f"rh06-{self.index}.sock"
        process = subprocess.Popen([sys.executable, "-B", __file__,
                                    str(self.root), role, name, stage],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.broker.reap, process)
        self.assertEqual("READY", self.broker.read_line(process))
        return process, str(self.root / name), Peer(process.pid, os.getuid(), os.getgid())

    def connect_broker(self, envelope=None, *, stage=""):
        process, endpoint, peer = self.child("broker", stage)
        stream = socket.socket(socket.AF_UNIX)
        self.addCleanup(stream.close)
        stream.settimeout(4)
        stream.connect(endpoint)
        authenticate(stream, peer)
        send_frame(stream, self.envelope if envelope is None else envelope)
        return process, stream

    def dispatch(self, envelope=None, *, stage="", crash=False):
        process, stream = self.connect_broker(envelope, stage=stage)
        return self.broker.finish(process, stream, crash=crash) if crash else (
            self.broker.finish(process, stream)["ack"]
        )

    def recover(self, *, stage="", verifier_spki=None, enrollment_expires_early=False):
        core = subprocess.Popen([sys.executable, "-B", __file__, str(self.root), "recover"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.broker.reap, core)
        process = None
        if enrollment_expires_early:
            # The Core policy check must reject before it connects.
            endpoint = str(self.root / "no-verifier.sock")
            peer = Peer(os.getpid(), os.getuid(), os.getgid())
        else:
            self.spec_path.write_text(json.dumps({
                **self.spec, "peer": asdict(Peer(core.pid, os.getuid(), os.getgid())),
            }))
            process, endpoint, peer = self.child("verifier", stage)
        config = {"task_id": self.case["task"].task_id, "warrant": self.fx.warrant.to_dict(),
                  "endpoint": endpoint, "verifier_peer": asdict(peer),
                  "verifier_spki": verifier_spki or self.verifier.spki,
                  "enrollment_expires_early": enrollment_expires_early}
        try:
            stdout, stderr = core.communicate(input=json.dumps(config), timeout=15)
        finally:
            self.spec_path.write_text(json.dumps(self.spec))
        self.assertEqual(0, core.returncode, stderr)
        if process is not None:
            self.assertEqual(0, process.wait(timeout=8))
        result = json.loads(stdout)
        self.assertEqual(core.pid, result["pid"])
        if "error" in result:
            kind = {"ProtocolError": ProtocolError, "CoreAdapterError": CoreAdapterError}[result["error"]]
            raise kind(result["code"])
        self.assertNotEqual(core.pid, result["result"]["verification_process_pid"])
        self.assertEqual(peer.pid, result["result"]["verification_process_pid"])
        return result["result"]

    def revision(self):
        return self.fx.runner.run(TransactionContext(self.fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OPERATION, self.fx.journal._key(self.fx.warrant)).revision)

    def assert_held(self):
        self.assertEqual("Unknown", self.fx.journal.inspect(
            self.fx.p(Capability.READ), self.fx.warrant)["outcome"]["contract_type"])
        self.assertEqual("UNKNOWN", self.fx.gov.inspect(self.fx.p(Capability.READ))[
            "reservations"]["paired-1"]["state"])
        self.assertEqual("HELD", self.fx.runner.run(
            TransactionContext(self.fx.p(Capability.READ), Capability.READ),
            lambda tx: tx.get(RecordKind.OUTBOX, self.fx.journal._key(self.fx.warrant)).payload["state"]))

    def test_default_off_and_durable_start_binding(self):
        with self.assertRaisesRegex(ProtocolError, "RH06_DISABLED"):
            self.authorize()
        self.assertEqual(self.binding, NativeExecutionBindingV1.from_wire(self.binding.to_wire()))
        with self.assertRaisesRegex(ProtocolError, "RH06_METADATA_BINDING"):
            replace(self.binding, source_digest="1" * 64)
        self.assertIsNone(self.tasks.native_witness_recovery_port)
        self.assert_held()

    def test_forged_or_mismatched_requests_never_consume(self):
        meta = self.binding.metadata()
        for field, value in (
            ("owner_id", "untrusted"), ("device_id", "other-device"), ("key_epoch", 19),
            ("exact_ref", "refs/heads/other"), ("repository_inode", self.binding.request.repository_inode + 1),
        ):
            with self.subTest(field=field):
                wire = self.binding.to_wire()
                request = asdict(self.binding.request)
                request.pop("commit_permit_digest")
                request[field] = value
                wire["request"] = BrokerRequest.for_fixture(**request).to_wire()
                self.assertEqual(wire["request"]["challenge"], digest(meta))
                payload = {"schema": AUTHORIZATION, "binding": wire}
                self.assertFalse(self.dispatch({"payload": payload, "signature": sign(self.core, payload)}))
        forged = copy.deepcopy(self.envelope)
        forged["signature"] = sign(identity(), forged["payload"])
        self.assertFalse(self.dispatch(forged))
        self.assertFalse(self.dispatch(self.binding.request.to_wire()))
        self.assertFalse(self.ref.exists())
        self.assertEqual([], list((self.root / "state").iterdir()))
        self.assertEqual([], self.broker.dispatches())
        self.assert_held()

    def test_nested_ref_refused_instead_of_linking_leaf_at_wrong_path(self):
        values = asdict(self.binding.request)
        values.pop("commit_permit_digest")
        values["exact_ref"] = "refs/heads/nested/other"
        with self.assertRaisesRegex(ProtocolError, "RH06_REF_NOT_DIRECT"):
            replace(self.binding, request=BrokerRequest.for_fixture(**values))

    def test_core_revocation_refuses_new_grant_export(self):
        self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), self.fx.warrant)
        with self.assertRaisesRegex(ValueError, "WARRANT_REVOKED"):
            self.authorize(enabled=True)
        self.assertFalse(self.ref.exists())
        self.assertEqual([], self.broker.dispatches())
        self.assert_held()

    def test_broker_stop_before_release_refuses_link(self):
        self.assertFalse(self.dispatch(stage="stop_first"))
        self.assertFalse(self.ref.exists())
        self.assertEqual([], self.broker.dispatches())
        self.assert_held()

    def test_broker_final_section_wins_over_contending_fixture_stop(self):
        broker, stream = self.connect_broker(stage="broker_first")
        self.assertEqual("PAUSED", self.broker.read_line(broker))
        stopper = self.broker.start_child("stop", "contended")
        self.assertEqual("BLOCKED", self.broker.read_line(stopper))
        broker.stdin.write("CONTINUE\n")
        broker.stdin.flush()
        self.assertEqual({"ack": True}, self.broker.finish(broker, stream))
        self.assertEqual(0, stopper.wait(timeout=8))
        self.assertTrue((self.root / "state" / "stopped").exists())
        self.assertTrue(self.ref.exists())
        self.assertFalse(self.dispatch())
        self.assertEqual(1, len(self.broker.dispatches()))

    def test_expired_core_enrollment_denies_before_verifier_ipc(self):
        self.assertTrue(self.dispatch())
        with self.assertRaisesRegex(ProtocolError, "RH06_VERIFIER_ENROLLMENT"):
            self.recover(enrollment_expires_early=True)
        self.assert_held()

    def test_crash_before_witness_stays_held_after_cold_recovery(self):
        before = self.revision()
        self.dispatch(stage="effect_synced", crash=True)
        self.assertTrue(self.ref.exists())
        self.assertFalse(self.dispatch())
        with self.assertRaisesRegex(CoreAdapterError, "WITNESS_NOT_SETTLEMENT_GRADE"):
            self.recover()
        self.assert_held()
        self.assertEqual(before, self.revision())
        self.assertEqual(1, len(self.broker.dispatches()))

    def test_lost_ack_authenticated_readback_settles_original_once(self):
        before = self.revision()
        self.dispatch(stage="witness_durable", crash=True)
        self.assert_held()
        self.assertFalse(self.dispatch())
        with self.assertRaisesRegex(ProtocolError, "RH06_SIGNATURE"):
            self.recover(verifier_spki=identity().spki)
        with self.assertRaisesRegex(ProtocolError, "RH06_VERIFIER_REPLAY_OR_BINDING"):
            self.recover(stage="replay")
        self.assert_held()
        first = self.recover()
        self.assertEqual("VERIFIED", first["task"]["state"])
        self.assertEqual("Applied", first["intent"]["outcome"]["contract_type"])
        self.assertEqual(before + 1, self.revision())
        again = self.recover()
        self.assertEqual(first["task"], again["task"])
        self.assertEqual(first["intent"], again["intent"])
        self.assertNotEqual(first["verification_process_pid"], again["verification_process_pid"])
        self.assertEqual(before + 1, self.revision())
        self.assertEqual(1, len(self.broker.dispatches()))

    def test_signed_report_refuses_same_oid_replacement(self):
        self.assertTrue(self.dispatch())
        rh04._replace_ref_with_same_oid(self.root, self.binding.request)
        with self.assertRaisesRegex(CoreAdapterError, "WITNESS_NOT_SETTLEMENT_GRADE"):
            self.recover()
        self.assertEqual(1, len(self.broker.dispatches()))
        self.assert_held()

    def test_signed_report_refuses_witness_mutation(self):
        self.assertTrue(self.dispatch())
        witness = self.root / "evidence" / self.binding.request.witness_binding().witness_id
        witness.chmod(0o600)
        witness.write_bytes(b"{}")
        witness.chmod(0o400)
        with self.assertRaisesRegex(CoreAdapterError, "WITNESS_NOT_SETTLEMENT_GRADE"):
            self.recover()
        self.assertEqual(1, len(self.broker.dispatches()))
        self.assert_held()

    def test_mount_binding_is_rechecked_before_attempt(self):
        wire = self.binding.to_wire()
        wire["repository_mount"] += 1
        request = asdict(self.binding.request)
        request.pop("commit_permit_digest")
        request["challenge"] = digest({k: v for k, v in wire.items() if k not in ("request", "schema")})
        wire["request"] = BrokerRequest.for_fixture(**request).to_wire()
        self.spec_path.write_text(json.dumps({**self.spec, "binding": wire}))
        payload = {"schema": AUTHORIZATION, "binding": wire}
        self.assertFalse(self.dispatch({"payload": payload, "signature": sign(self.core, payload)}))
        self.assertEqual([], list((self.root / "state").iterdir()))
        self.assertFalse(self.ref.exists())
        self.assert_held()


if __name__ == "__main__":
    root = Path(sys.argv[1])
    if sys.argv[2:] == ["recover"]:
        recover_core(root)
    else:
        launch(root, *sys.argv[2:])
