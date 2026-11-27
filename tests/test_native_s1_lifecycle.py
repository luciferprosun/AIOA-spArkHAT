import os
import select
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from runtime.red_hat.authenticated_boundary import _seal
from runtime.red_hat.broker_protocol import Peer, digest, send_frame
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.native_services import await_broker_completion
from runtime.red_hat.role_storage import DirectoryPin
from runtime.red_hat.sequencer import serve_sequencer
from runtime.red_hat.writer_lifecycle import COMPLETION_STAGE, OneShotWriter, require_writer_closed
from test_redhat_broker_protocol import NOW, fixture_enrollment, fixture_request


class NativeWriterLifecycleTests(unittest.TestCase):
    def test_s1_sequencer_does_not_reopen_a_previous_aperture(self):
        stopped = threading.Event()
        stopped.set()
        ready = Mock()
        core = Peer(os.getpid(), os.getuid(), os.getgid())
        broker = Peer(os.getpid() + 1, os.getuid(), os.getgid())
        with tempfile.TemporaryDirectory() as root, socket.socket(socket.AF_UNIX) as listener:
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                def run(epoch):
                    serve_sequencer(listener, directory=directory, core_peer=core, broker_peer=broker,
                                    epoch=epoch, stop=stopped, on_ready=ready, enabled=True, fence_restart=True)

                run(1)
                self.assertFalse(Path(root, "outstanding").exists())
                with self.assertRaisesRegex(ValueError, "BROKER_RECORD_EXISTS"):
                    run(2)
                ready.assert_called_once()
            finally:
                os.close(directory)

    def test_actual_pidfd_and_original_completion_required_for_closure(self):
        enrollment, signer = fixture_enrollment()
        _, foreign = fixture_enrollment()
        metadata = dict(operation_digest="1" * 64, capsule_digest="2" * 64, plan_digest="3" * 64,
                        source_digest="4" * 64, policy_digest="5" * 64, reservation_id_digest="6" * 64,
                        outbox_id_digest="7" * 64, storage_digest="8" * 64,
                        boot_id=Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
                        repository_mount=2, ref_parent_mount=2)
        request = fixture_request(challenge=digest(metadata), executor_key_id=enrollment.executor.key_id)
        binding = NativeExecutionBindingV1(request, **metadata)
        storage = SimpleNamespace(writer_cgroup=DirectoryPin(2, 3, 4), digest=metadata["storage_digest"],
                                  exact_ref=request.exact_ref, require_anchor=Mock(),
                                  broker=SimpleNamespace(uid=os.getuid(), cgroup=Path("/proc/self/cgroup").read_text().strip()))
        records = {}

        def publish(_, name, value, _storage, *, sync_directory=True, before_directory_sync=None):
            if name in records:
                raise FileExistsError(name)
            records[name] = value

        def read(_, name, _storage):
            if name not in records:
                raise FileNotFoundError(name)
            return records[name]

        facts = {"schema": COMPLETION_STAGE, "binding": digest(binding.to_wire()), "completion_sha256": "9" * 64}
        stage = _seal(signer, facts)
        mod = "runtime.red_hat.writer_lifecycle"
        # This exercises the actual unreaped-child pidfd. Filesystem authority
        # and cgroup population are synthetic; this cannot qualify Linux roles.
        with patch(f"{mod}.os.geteuid", return_value=0), patch(f"{mod}._cgroup"), patch(
            f"{mod}._empty", return_value=True
        ) as empty, patch(f"{mod}._publish", side_effect=publish), patch(
            f"{mod}._read", side_effect=read
        ), patch(f"{mod}.time.time", return_value=NOW), OneShotWriter(-1, storage, -1) as writer:
            with self.assertRaises(FileExistsError):
                OneShotWriter(-1, storage, -1)
            with self.assertRaisesRegex(ValueError, "CLOSURE_UNAVAILABLE"):
                require_writer_closed(-1, storage, binding)
            child = subprocess.Popen([sys.executable, "-IBS", "-c", "import sys; sys.stdin.read()"],
                                     stdin=subprocess.PIPE)
            try:
                writer.register(child)
                with self.assertRaisesRegex(ValueError, "STILL_LIVE"):
                    writer.close_writer(binding, stage, enrollment)
                child.stdin.close()
                self.assertEqual(select.select([writer.pidfd], [], [], 3)[0], [writer.pidfd])
                empty.return_value = False
                with self.assertRaisesRegex(ValueError, "STILL_LIVE"):
                    writer.close_writer(binding, stage, enrollment)
                empty.return_value = True
                with self.assertRaisesRegex(ValueError, "RH06_SIGNATURE"):
                    writer.close_writer(binding, _seal(foreign, facts), enrollment)
                with self.assertRaisesRegex(ValueError, "COMPLETION_STAGE"):
                    writer.close_writer(binding, _seal(signer, {**facts, "binding": "a" * 64}), enrollment)
                sender, receiver = socket.socketpair()
                with sender, receiver:
                    send_frame(sender, stage)
                    await_broker_completion(writer, receiver, binding, enrollment, deadline=time.monotonic() + 3)
                self.assertEqual(require_writer_closed(-1, storage, binding), "9" * 64)
            finally:
                child.stdin.close()
                child.wait(timeout=3)
