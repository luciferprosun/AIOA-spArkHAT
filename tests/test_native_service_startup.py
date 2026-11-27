"""Real listener and peer credentials in offline same-UID subprocesses."""

import os
import socket
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from runtime.red_hat.broker_protocol import Peer, authenticate
from runtime.red_hat.native_services import await_service_ready, run_broker, start_listener


class NativeServiceStartupTests(unittest.TestCase):
    def test_role_listen_records_the_child_kernel_credentials(self):
        with tempfile.TemporaryDirectory(prefix="native-ready-") as work:
            address = work + "/role.sock"
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(address)
                control, child_control = socket.socketpair()
                with control, child_control:
                    program = """
import socket, sys
from runtime.red_hat.native_services import _ready, start_listener
with socket.socket(fileno=int(sys.argv[1])) as listener, socket.socket(fileno=int(sys.argv[2])) as control:
    control.set_inheritable(False)
    start_listener(listener, sys.argv[3])
    _ready(control, "broker")
    with listener.accept()[0] as client:
        client.sendall(b"ready")
"""
                    with subprocess.Popen([sys.executable, "-B", "-c", program, str(listener.fileno()),
                                           str(child_control.fileno()), address],
                                          pass_fds=(listener.fileno(), child_control.fileno())) as child:
                        child_control.close()
                        listener.close()
                        try:
                            await_service_ready(child, control, "broker")
                            with socket.socket(socket.AF_UNIX) as endpoint:
                                endpoint.settimeout(2)
                                endpoint.connect(address)
                                authenticate(endpoint, Peer(child.pid, os.getuid(), os.getgid()))
                                self.assertEqual(b"ready", endpoint.recv(5))
                            self.assertEqual(0, child.wait(timeout=2))
                        finally:
                            if child.poll() is None:
                                child.kill()

    def test_listener_rejects_wrong_name_and_listener_already_started(self):
        with tempfile.TemporaryDirectory(prefix="native-ready-") as work:
            with socket.socket(socket.AF_UNIX) as listener:
                address = work + "/role.sock"
                listener.bind(address)
                with self.assertRaisesRegex(ValueError, "SERVICE_LISTENER"):
                    start_listener(listener, work + "/foreign")
                start_listener(listener, address)
                self.assertFalse(listener.get_inheritable())
                with self.assertRaisesRegex(ValueError, "SERVICE_LISTENER"):
                    start_listener(listener, address)

    def test_broker_startup_failure_closes_the_broker_only_descriptor(self):
        fd = os.open("/dev/null", os.O_RDONLY)
        with self.assertRaisesRegex(ValueError, "SERVICE_CONFIGURATION"):
            run_broker(None, "/nonexistent", None, root_fd=-1, storage=None, device_id="fixture",
                       sequencer=None, release=None, core_spki=None, signer_fd=fd, enrollment=None,
                       core_epoch=1)
        with self.assertRaises(OSError):
            os.fstat(fd)

    def test_role_verifier_demands_signed_start_projection(self):
        from cryptography.hazmat.primitives.asymmetric import ec
        from runtime.mobile_gateway.wire import Identity
        from runtime.red_hat.authenticated_boundary import (
            _read_authenticated_report, serve_role_verifier_once,
        )
        from runtime.red_hat.broker_protocol import BrokerRequest, digest
        from runtime.red_hat.enrollment import ExecutorEnrollment
        from runtime.red_hat.execution_binding import NativeExecutionBindingV1
        from runtime.red_hat.role_storage import DirectoryPin, RoleStorage, StorageActor
        from runtime.red_hat.verifier import Verification
        from runtime.red_hat.witness import RegisteredExecutor
        from test_redhat_broker_protocol import fixture_request
        import time

        core, broker, verifier = (Identity(ec.generate_private_key(ec.SECP256R1())) for _ in range(3))
        peer = Peer(os.getpid(), os.getuid(), os.getgid())
        roles = tuple(StorageActor(uid, gid, f"{name} (enforce)", f"0::/native/{name}")
                      for name, uid, gid in (("core", peer.uid, peer.gid), ("broker", 61102, 61102),
                                              ("verifier", 61103, 61103)))
        pins = tuple(DirectoryPin(10, ino, 4) for ino in range(1, 5))
        ref = "refs/heads/aioa/nz11-" + "2" * 32
        storage = RoleStorage(*roles, 61104, 10, ref, *pins)
        enrolled = ExecutorEnrollment(RegisteredExecutor("fixture-executor", storage.broker.uid, broker.spki),
                                      3, 1, 2**62)
        metadata = dict(operation_digest="1"*64, capsule_digest="2"*64, plan_digest="3"*64,
                        source_digest="4"*64, policy_digest="5"*64, reservation_id_digest="6"*64,
                        outbox_id_digest="7"*64, boot_id="12345678-abcd-abcd-abcd-123456789012",
                        repository_mount=4, ref_parent_mount=4, storage_digest=storage.digest)
        values = {k: v for k, v in fixture_request().to_wire().items()
                  if k not in ("schema", "commit_permit_digest")}
        req = BrokerRequest.for_fixture(**{**values, "exact_ref": ref, "challenge": digest(metadata)})
        binding = NativeExecutionBindingV1(req, **metadata)
        report = Verification(**{name: (None if name.endswith(("sha256", "inode", "ctime_ns")) else False)
                                  for name in Verification.__dataclass_fields__})
        with tempfile.TemporaryDirectory(prefix="native-verify-") as work, socket.socket(socket.AF_UNIX) as listener:
            address = str(Path(work) / "verifier.sock")
            listener.bind(address)
            start_listener(listener, address)
            with patch.object(RoleStorage, "require_role"), patch.object(RoleStorage, "require_anchor"), patch(
                "runtime.red_hat.authenticated_boundary.verify", return_value=report
            ) as verify, patch(
                "runtime.red_hat.writer_lifecycle.require_writer_closed", return_value=None
            ), ThreadPoolExecutor(max_workers=1) as pool:
                def serve():
                    return serve_role_verifier_once(listener, root_fd=-1, storage=storage, enrollment=enrolled,
                                                    identity=verifier, core_peer=peer, core_spki=core.spki, enabled=True)
                forged = pool.submit(serve)
                with self.assertRaises(ValueError):
                    _read_authenticated_report(address, peer, verifier.spki, binding,
                                               now=int(time.time()), signer=broker)
                with self.assertRaisesRegex(ValueError, "RH06_SIGNATURE"):
                    forged.result(timeout=3)
                verify.assert_not_called()
                accepted = pool.submit(serve)
                observed, _ = _read_authenticated_report(address, peer, verifier.spki, binding,
                                                         now=int(time.time()), signer=core)
                accepted.result(timeout=3)
                verify.assert_called_once()
                self.assertEqual(report, observed)
