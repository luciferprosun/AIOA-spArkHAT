import fcntl
import json
import os
import select
import socket
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.broker_protocol import (
    AttemptGuard, BrokerRequest, Peer, ProtocolError, authenticate, publish_record, read_frame,
    read_record, send_frame,
)
from runtime.red_hat.broker_service import serve_once
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.verifier import verify
from runtime.red_hat.witness import RegisteredExecutor
from test_redhat_broker_protocol import NOW, fixture_request


def fd(path):
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)


def git(directory, *args, input=None):
    return subprocess.run(
        ["/usr/bin/git", "-C", str(directory), *args], input=input, text=True,
        capture_output=True, check=True, timeout=10,
        env={"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
             "GIT_AUTHOR_NAME": "Fixture", "GIT_COMMITTER_NAME": "Fixture",
             "GIT_AUTHOR_EMAIL": "fixture@example.invalid", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"},
    ).stdout.strip()


def put(path, raw, mode):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode), "wb") as out:
        out.write(raw)


def run_child(root, mode, *args):
    if mode == "key":
        identity = Identity(ec.generate_private_key(ec.SECP256R1()))
        put(root / "fixture-key", identity.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()), 0o600)
        print(identity.spki)
        return
    spec = json.loads((root / "fixture.json").read_text())
    req = BrokerRequest.from_wire(spec["request"])
    enrolled = ExecutorEnrollment(RegisteredExecutor("fixture-executor", os.getuid(), spec["spki"]),
                                  3, NOW - 60, NOW + 600, revoked="revoked" in args)
    anchor = fd(root)
    try:
        if mode == "verify":
            expected_core_epoch = spec.get("core_epoch", 5)
            observation = verify(
                anchor, req, enrolled, now=NOW + (60 if "late" in args else 0),
                core_epoch=expected_core_epoch + (1 if "stale" in args else 0), broker_epoch=7,
            )
            settled = False
            if observation.settlement_supported:
                # Only a test decision record. The original intent and reservation are fixed.
                decision = {"start": req.start_digest, "intent": req.intent_digest,
                            "reservation": req.reservation_digest, "attempt": req.attempt_id,
                            "outcome": "APPLIED"}
                try:
                    publish_record(anchor, "settlement", decision)
                    settled = True
                except ProtocolError as error:
                    if str(error) != "BROKER_RECORD_EXISTS":
                        raise
                    assert json.loads(read_record(anchor, "settlement", os.getuid(),
                                                  sync=True)) == decision
            print(json.dumps({"pid": os.getpid(), **asdict(observation), "settled": settled}))
            return

        if mode == "stop":
            state = fd(root / "state")
            try:
                if args == ("contended",):
                    lock = os.open("lock", os.O_RDWR | os.O_NOFOLLOW, dir_fd=state)
                    try:
                        try:
                            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            print("BLOCKED", flush=True)
                        else:
                            raise AssertionError("independent STOP did not contend")
                    finally:
                        os.close(lock)
                AttemptGuard(state).stop()
            finally:
                os.close(state)
            return

        socket_name, stage = args
        identity = Identity(serialization.load_pem_private_key(
            (root / "fixture-key").read_bytes(), password=None))
        ref_info = (root / "repo/refs/heads").stat()
        evidence_info = (root / "evidence").stat()
        real_link, real_sync = os.link, os.fsync

        def fault(where):
            if stage == where:
                os._exit(74)
            if stage == "pause_" + where:
                print("PAUSED", flush=True)
                assert sys.stdin.readline().strip() == "CONTINUE"

        def link(source, name, *, dst_dir_fd, follow_symlinks):
            inode = os.fstat(dst_dir_fd)
            if (inode.st_dev, inode.st_ino, name) == (
                ref_info.st_dev, ref_info.st_ino, req.exact_ref.rsplit("/", 1)[1]
            ):
                with (root / "dispatches").open("a") as counter:
                    counter.write(f"{os.getpid()}\n")
                    counter.flush()
                    real_sync(counter.fileno())
            real_link(source, name, dst_dir_fd=dst_dir_fd, follow_symlinks=follow_symlinks)

        def fsync(target):
            info = os.fstat(target)
            if (info.st_dev, info.st_ino) == (evidence_info.st_dev, evidence_info.st_ino):
                fault("before_witness_directory_fsync")
            elif info.st_nlink == 0 and b"aioa.native-cas-witness.v1" in os.pread(target, 8192, 0):
                fault("before_witness_file_fsync")
            return real_sync(target)

        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(str(root / socket_name))
            listener.listen(1)
            listener.settimeout(5)
            print("READY", flush=True)
            with patch("os.link", link), patch("os.fsync", fsync):
                serve_once(listener, root_fd=anchor, expected=req, enrollment=enrolled,
                           identity=identity, core_peer=Peer(**spec["peer"]),
                           core_epoch=spec.get("core_epoch", 5),
                           broker_epoch=7, clock=lambda: NOW, fault=fault)
    finally:
        os.close(anchor)


class CasBrokerTests(unittest.TestCase):
    def child(self, mode, *args, **kwargs):
        return subprocess.run([sys.executable, "-B", __file__, str(self.root), mode, *args],
                              capture_output=True, text=True, check=True, timeout=10, **kwargs).stdout

    def workspace(self):
        scratch = tempfile.TemporaryDirectory(prefix="rh-")
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        repo = self.root / "repo"
        for name in ("repo", "state", "evidence"):
            (self.root / name).mkdir(mode=0o700)
        git(repo, "init", "--bare", "--template=", "--object-format=sha1")
        # The sandbox now rejects group-writable storage components. Normalize
        # only this disposable fixture, preserving the private workspace root.
        for path in repo.rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
        put(repo / ".redhat-disposable", b"AIOA_RED_HAT_FIXTURE_V1\n", 0o400)
        commit = git(repo, "commit-tree", git(repo, "mktree", input=""), "-m", "Disposable")
        for path in repo.rglob("*"):
            if path.name != ".redhat-disposable":
                path.chmod(0o755 if path.is_dir() else 0o644)
        spki = self.child("key").strip()
        self.enrollment = RegisteredExecutor("fixture-executor", os.getuid(), spki)
        info, directory = repo.stat(), (repo / "refs/heads").stat()
        self.request = fixture_request(
            repository_dev=info.st_dev, repository_inode=info.st_ino,
            ref_directory_dev=directory.st_dev, ref_directory_inode=directory.st_ino,
            new_oid=commit, executor_key_id=self.enrollment.key_id)
        self.ref = repo / self.request.exact_ref
        self.spec = {"request": self.request.to_wire(), "spki": spki,
                     "peer": asdict(Peer(os.getpid(), os.getuid(), os.getgid()))}
        put(self.root / "fixture.json", json.dumps(self.spec).encode(), 0o600)
        self.index = 0

    def start_broker(self, stage="", request=None):
        self.index += 1
        path = f"broker-{self.index}.sock"
        broker = self.start_child("broker", path, stage)
        self.assertEqual(self.read_line(broker), "READY")
        client = socket.socket(socket.AF_UNIX)
        self.addCleanup(client.close)
        client.settimeout(3)
        client.connect(str(self.root / path))
        authenticate(client, Peer(broker.pid, os.getuid(), os.getgid()))
        send_frame(client, (self.request if request is None else request).to_wire())
        return broker, client

    def start_child(self, *args):
        process = subprocess.Popen(
            [sys.executable, "-B", __file__, str(self.root), *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(self.reap, process)
        return process

    @staticmethod
    def reap(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()

    def read_line(self, process):
        readable, _, _ = select.select([process.stdout], [], [], 8)
        self.assertTrue(readable)
        return process.stdout.readline().strip()

    def finish(self, broker, client, crash=False):
        with client:
            if crash:
                with self.assertRaisesRegex(ProtocolError, "TRUNCATED"):
                    read_frame(client)
                self.assertEqual(broker.wait(timeout=8), 74)
                return None
            result = read_frame(client)
            self.assertEqual(broker.wait(timeout=8), 0)
            return result

    def run_broker(self, stage="", crash=False, request=None):
        return self.finish(*self.start_broker(stage, request), crash=crash)

    def recover(self, *args):
        result = json.loads(self.child("verify", *args))
        self.assertNotEqual(result["pid"], os.getpid())
        return result

    def dispatches(self):
        path = self.root / "dispatches"
        return path.read_text().splitlines() if path.exists() else []

    def assert_recovery_denied(self):
        recovery = self.recover()
        self.assertFalse(recovery["settled"])
        self.assertFalse(recovery["settlement_supported"])
        self.assertFalse((self.root / "settlement").exists())

    def test_crash_before_permit_and_stop_before_permit(self):
        self.workspace()
        self.run_broker("before_permit", crash=True)
        self.assertFalse(self.ref.exists())
        self.assertFalse(list((self.root / "state").glob("permit-*")))
        self.child("stop")
        self.assertFalse(self.run_broker()["ack"])
        self.assertFalse(self.ref.exists())
        self.assertEqual(self.dispatches(), [])

    def test_stop_after_permit_before_release(self):
        self.workspace()
        broker, client = self.start_broker("pause_before_release")
        self.assertEqual(self.read_line(broker), "PAUSED")
        self.child("stop")
        broker.stdin.write("CONTINUE\n")
        broker.stdin.flush()
        self.assertFalse(self.finish(broker, client)["ack"])
        self.assertFalse(self.ref.exists())
        self.assertEqual(self.dispatches(), [])
        self.assert_recovery_denied()

    def test_stop_contends_with_final_release_lock(self):
        self.workspace()
        broker, client = self.start_broker("pause_release_acquired")
        self.assertEqual(self.read_line(broker), "PAUSED")
        stopper = self.start_child("stop", "contended")
        self.assertEqual(self.read_line(stopper), "BLOCKED")
        self.assertFalse(self.ref.exists())
        broker.stdin.write("CONTINUE\n")
        broker.stdin.flush()
        self.assertTrue(self.finish(broker, client)["ack"])
        self.assertEqual(stopper.wait(timeout=8), 0)
        self.assertEqual(len(self.dispatches()), 1)

    def test_crash_between_permit_and_cas_fences_restart(self):
        for stage in ("permit_durable", "attempt_consumed", "release_acquired"):
            with self.subTest(stage=stage):
                self.workspace()
                self.run_broker(stage, crash=True)
                self.assertTrue(list((self.root / "state").glob("permit-*")))
                self.assertFalse(self.run_broker()["ack"])
                self.assertFalse(self.ref.exists())
                self.assertEqual(self.dispatches(), [])
                self.assert_recovery_denied()

    def test_old_oid_conflict_and_foreign_same_oid(self):
        for oid in ("1" * 40, None):
            with self.subTest(oid=oid):
                self.workspace()
                put(self.ref, ((oid or self.request.new_oid) + "\n").encode(), 0o400)
                original = self.ref.stat().st_ino
                self.assertFalse(self.run_broker()["ack"])
                self.assertEqual(self.ref.stat().st_ino, original)
                self.assertEqual(len(self.dispatches()), 1)
                self.assertFalse(self.run_broker()["ack"])
                self.assertEqual(len(self.dispatches()), 1)
                self.assert_recovery_denied()

    def test_crash_after_cas_or_before_witness_file_sync(self):
        for stage in ("effect_synced", "before_witness_file_fsync"):
            with self.subTest(stage=stage):
                self.workspace()
                self.run_broker(stage, crash=True)
                self.assertTrue(self.ref.exists())
                self.assertFalse(self.run_broker()["ack"])
                self.assertEqual(len(self.dispatches()), 1)
                observed = self.recover()
                self.assertTrue(observed["effect_observed"])
                self.assertFalse(observed["producer_effect_sync_completed"])
                self.assertFalse(observed["witness_bytes_verified"])
                self.assertFalse(observed["settlement_supported"])

    def test_surviving_signed_witness_cannot_attest_original_directory_sync(self):
        self.workspace()
        self.run_broker("before_witness_directory_fsync", crash=True)
        observed = self.recover()
        self.assertTrue(observed["witness_bytes_verified"])
        self.assertTrue(observed["producer_effect_sync_completed"])
        self.assertTrue(observed["witness_durable_at_readback"])
        self.assertFalse(observed["producer_witness_sync_attested"])
        self.assertFalse(observed["settlement_supported"])
        self.assertFalse(self.run_broker()["ack"])
        self.assertEqual(len(self.dispatches()), 1)

    def test_lost_ack_one_settlement_zero_actual_redispatch(self):
        self.workspace()
        self.run_broker("witness_durable", crash=True)
        original = self.dispatches()
        self.assertEqual(len(original), 1)
        self.assertEqual(git(self.root / "repo", "rev-parse", "--verify", self.request.exact_ref),
                         self.request.new_oid)
        for _ in range(2):
            self.assertFalse(self.run_broker()["ack"])
        readers = [self.start_child("verify"), self.start_child("verify", "late")]
        views = []
        for reader in readers:
            output, errors = reader.communicate(timeout=8)
            self.assertEqual(reader.returncode, 0, errors)
            views.append(json.loads(output))
        first, second = sorted(views, key=lambda view: not view["settled"])
        self.assertTrue(first["producer_witness_sync_attested"])
        self.assertTrue(first["settlement_supported"])
        self.assertNotIn(str(first["pid"]), original)
        self.assertNotEqual(first["pid"], second["pid"])
        self.assertTrue(first["settled"])
        self.assertFalse(second["settled"])
        self.assertTrue(second["settlement_supported"])
        self.assertEqual(json.loads((self.root / "settlement").read_text())["reservation"],
                         self.request.reservation_digest)
        redispatch_count = len(self.dispatches()) - len(original)
        self.assertEqual(redispatch_count, 0)

    def test_replaced_inode_invalid_signature_and_revoked_key(self):
        for damage in ("inode", "same_inode", "signature", "completion", "revoked", "stale"):
            with self.subTest(damage=damage):
                self.workspace()
                self.assertTrue(self.run_broker()["ack"])
                if damage == "inode":
                    replacement = self.ref.with_name("replacement")
                    replacement.write_bytes(self.ref.read_bytes())
                    replacement.chmod(0o400)
                    replacement.replace(self.ref)
                elif damage == "same_inode":
                    self.ref.chmod(0o600)
                    self.ref.chmod(0o400)
                elif damage in ("signature", "completion"):
                    name = self.request.witness_binding().witness_id
                    if damage == "completion":
                        name = "completion-" + name
                    path = self.root / "evidence" / name
                    envelope = json.loads(path.read_bytes())
                    envelope["signature"] = "AA=="
                    path.chmod(0o600)
                    path.write_text(json.dumps(envelope, sort_keys=True, separators=(",", ":")))
                    path.chmod(0o400)
                denied = self.recover(damage)
                self.assertFalse(denied["settlement_supported"])
                self.assertFalse(denied["settled"])

    def test_native_ref_is_published_in_its_bound_parent(self):
        self.workspace()
        heads = self.root / "repo/refs/heads"
        parent = heads / "aioa"
        parent.mkdir(mode=0o700)
        ref = "refs/heads/aioa/nz11-" + "a" * 32
        fields = asdict(self.request)
        fields.pop("commit_permit_digest")
        fields.update(exact_ref=ref, ref_directory_inode=parent.stat().st_ino)
        self.request = BrokerRequest.for_fixture(**fields)
        self.ref = self.root / "repo" / ref
        self.spec["request"] = self.request.to_wire()
        (self.root / "fixture.json").write_text(json.dumps(self.spec))
        self.assertTrue(self.run_broker()["ack"])
        self.assertEqual(self.request.new_oid, self.ref.read_text().strip())
        self.assertFalse((heads / self.ref.name).exists())
        self.assertTrue(self.recover()["settlement_supported"])

    def test_unbound_nested_ref_cannot_alias_a_direct_ref(self):
        self.workspace()
        fields = asdict(self.request)
        fields.pop("commit_permit_digest")
        fields["exact_ref"] = "refs/heads/other/" + self.ref.name
        self.request = BrokerRequest.for_fixture(**fields)
        self.spec["request"] = self.request.to_wire()
        (self.root / "fixture.json").write_text(json.dumps(self.spec))
        self.assertFalse(self.run_broker()["ack"])
        self.assertFalse(self.ref.exists())
        self.assertEqual([], self.dispatches())

    def test_invalid_storage_refuses_publication(self):
        for damage in ("corrupt_commit", "packed_refs", "config"):
            with self.subTest(damage=damage):
                self.workspace()
                repo = self.root / "repo"
                if damage == "corrupt_commit":
                    commit = repo / "objects" / self.request.new_oid[:2] / self.request.new_oid[2:]
                    commit.chmod(0o600)
                    commit.write_bytes(b"invalid zlib")
                elif damage == "packed_refs":
                    put(repo / "packed-refs", b"# pack-refs\n", 0o400)
                else:
                    with (repo / "config").open("a") as config:
                        config.write("[include]\n\tpath = outside\n")
                self.assertFalse(self.run_broker()["ack"])
                self.assertEqual(self.dispatches(), [])
                self.assertFalse(self.ref.exists())

    def test_unreadable_readback_sync_retains_signature_facts(self):
        self.workspace()
        self.assertTrue(self.run_broker()["ack"])
        anchor = fd(self.root)
        try:
            enrollment = ExecutorEnrollment(self.enrollment, 3, NOW - 60, NOW + 60)
            with patch("os.fsync", side_effect=OSError("fixture readback storage fault")):
                observation = verify(anchor, self.request, enrollment, now=NOW,
                                     core_epoch=5, broker_epoch=7)
        finally:
            os.close(anchor)
        self.assertTrue(observation.witness_bytes_verified)
        self.assertTrue(observation.producer_effect_sync_completed)
        self.assertFalse(observation.witness_durable_at_readback)
        self.assertFalse(observation.settlement_supported)

    def test_symlink_and_path_traversal_refuse_publication(self):
        self.workspace()
        with self.assertRaises(ProtocolError):
            replace(self.request, exact_ref="refs/heads/../protected")
        self.ref.symlink_to(self.root / "untouched")
        self.assertFalse(self.run_broker()["ack"])
        self.assertFalse((self.root / "untouched").exists())
        self.assertEqual(self.dispatches(), [])
        self.assert_recovery_denied()


if __name__ == "__main__":
    run_child(Path(sys.argv[1]), sys.argv[2], *sys.argv[3:])
