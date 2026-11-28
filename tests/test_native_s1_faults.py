"""Same-UID fault regressions with real Unix sockets and actual receipt syscalls."""
import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.red_hat.broker_protocol import Peer, digest
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.sequencer import SequenceClient, serve_sequencer
from runtime.red_hat.writer_lifecycle import (
    _CLOSED, _CLOSED_SYNCED, _closure, _publish_closure, require_writer_closed,
)
from test_redhat_broker_protocol import fixture_request


_BROKER = """
import os, sys
from runtime.red_hat.broker_protocol import Peer
from runtime.red_hat.sequencer import SequenceClient, _message, _read, _send

endpoint, pid, mode = sys.argv[1:]
client = SequenceClient(endpoint, Peer(int(pid), os.getuid(), os.getgid()), 1)
binding = 'a' * 64
with client._connect() as stream:
    _send(stream, _message(1, 'publish', binding), 3)
    grant = _read(stream, 3)
    assert grant['action'] == 'granted'
    print('GRANTED', flush=True)
    assert sys.stdin.readline().strip() == 'CONTINUE'
    _send(stream, _message(1, 'done' if mode != 'no-done' else 'wrong', binding,
                           token=grant['token']), 3)
    if mode == 'send-unread':
        assert sys.stdin.readline().strip() == 'DISCARD'
    else:
        assert _read(stream, 3) == {'denied': True}
    print('NO_CLOSED_OBSERVED', flush=True)
try:
    with client.hold(binding=binding):
        raise AssertionError('same process got a second publication slot')
except ValueError as exc:
    assert 'NOT_GRANTED' in str(exc)
print('REPLAY_DENIED', flush=True)
"""

_CONSUMER = """
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from runtime.red_hat.execution_binding import NativeExecutionBindingV1
from runtime.red_hat.writer_lifecycle import require_writer_closed

root = Path(sys.argv[1])
binding = NativeExecutionBindingV1.from_wire(json.loads(sys.argv[2]))
storage = SimpleNamespace(digest=binding.storage_digest, exact_ref=binding.request.exact_ref,
                          require_anchor=lambda _: None)
def read(_, name, _storage):
    return json.loads((root / name).read_bytes())
with patch('runtime.red_hat.writer_lifecycle._read', side_effect=read), patch(
        'runtime.red_hat.writer_lifecycle._process', return_value={'pid': 4}):
    try:
        print(require_writer_closed(-1, storage, binding))
    except ValueError as exc:
        print(exc)
"""


class NativeS1FaultTests(unittest.TestCase):
    def test_live_sequencer_never_regrants_after_unobserved_closed(self):
        faults = {
            'no-done': None, 'fsync': 'before_slot_sync',
            'send-failure': 'slot_closed', 'send-unread': None,
        }
        for mode, injected in faults.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                stop = threading.Event()
                pending_stop = threading.Event()
                sent = threading.Event()
                ready = threading.Event()
                endpoint = str(root / 'seq')
                core = Peer(os.getpid(), os.getuid(), os.getgid())
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    with socket.socket(socket.AF_UNIX) as listener, ThreadPoolExecutor(max_workers=2) as pool:
                        listener.bind(endpoint)
                        listener.listen(4)
                        child = subprocess.Popen([sys.executable, '-B', '-c', _BROKER, endpoint, str(core.pid), mode],
                                                 stdout=subprocess.PIPE, stdin=subprocess.PIPE, text=True)
                        try:
                            faulted = False

                            def fault(point):
                                nonlocal faulted
                                if point == 'control_waiting':
                                    pending_stop.set()
                                if point == 'closed_sent':
                                    sent.set()
                                if point == injected and not faulted:
                                    faulted = True
                                    raise OSError(errno.EIO, 'injected sequence fault')

                            service = pool.submit(serve_sequencer, listener, directory=directory, core_peer=core,
                                                  broker_peer=Peer(child.pid, core.uid, core.gid), epoch=1,
                                                  timeout=4, active_timeout=4, stop=stop, fault=fault,
                                                  enabled=True, on_ready=ready.set, fence_restart=True)
                            self.assertTrue(ready.wait(3))
                            self.assertEqual(child.stdout.readline().strip(), 'GRANTED')

                            def stop_after_publication():
                                try:
                                    with SequenceClient(endpoint, core, 1, timeout=4).hold():
                                        return 'STOP_SLOT_AFTER_CLOSED'
                                except ValueError:
                                    return 'STOP_FENCED'

                            waiting = pool.submit(stop_after_publication)
                            self.assertTrue(pending_stop.wait(3))
                            self.assertFalse(waiting.done())
                            child.stdin.write('CONTINUE\n')
                            child.stdin.flush()
                            if mode == 'send-unread':
                                self.assertTrue(sent.wait(3), 'real server send did not complete')
                                child.stdin.write('DISCARD\n')
                                child.stdin.flush()
                            output, _ = child.communicate(timeout=8)
                            self.assertEqual(child.returncode, 0)
                            self.assertEqual(output.splitlines(), ['NO_CLOSED_OBSERVED', 'REPLAY_DENIED'])
                            self.assertFalse(service.done(), 'sequencer must still be alive')
                            self.assertEqual(waiting.result(timeout=5), (
                                'STOP_FENCED' if mode in ('no-done', 'fsync') else 'STOP_SLOT_AFTER_CLOSED'))
                            self.assertEqual((root / 'outstanding').is_file(), mode == 'no-done')
                            self.assertTrue((root / 's1-sequencer-incarnation').is_file())
                        finally:
                            stop.set()
                            if child.poll() is None:
                                child.kill()
                                child.communicate(timeout=3)
                        service.result(timeout=3)
                finally:
                    os.close(directory)

    def test_supervisor_write_barriers_and_cold_consumer(self):
        from runtime.red_hat.writer_lifecycle import _boot

        metadata = dict(operation_digest='1'*64, capsule_digest='2'*64, plan_digest='3'*64,
                        source_digest='4'*64, policy_digest='5'*64, reservation_id_digest='6'*64,
                        outbox_id_digest='7'*64, storage_digest='8'*64,
                        boot_id=_boot(), repository_mount=2, ref_parent_mount=2)
        request = fixture_request(challenge=digest(metadata))
        binding = NativeExecutionBindingV1(request, **metadata)
        storage = SimpleNamespace(digest=binding.storage_digest, exact_ref=request.exact_ref,
                                  reader_gid=os.getgid(), require_anchor=lambda _: None)
        process = {'pid': 4}
        closure = _closure(binding, storage, process, '9'*64)
        mod = 'runtime.red_hat.writer_lifecycle'
        real_sync = os.fsync
        for point in ('short-write', 'file-fsync', 'link', 'directory-fsync', 'complete'):
            with self.subTest(point=point), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)

                def sync(fd):
                    if (fd != directory and point == 'file-fsync') or (fd == directory and point == 'directory-fsync'):
                        raise OSError(errno.EIO, point)
                    return real_sync(fd)

                try:
                    # Fixture simulates authority ownership, while exercising
                    # real write/fsync/link and an independent consumer process.
                    with patch(f'{mod}.os.fchown'), patch(f'{mod}.os.fsync', side_effect=sync):
                        if point == 'short-write':
                            with patch(f'{mod}.os.write', return_value=0), self.assertRaisesRegex(
                                    ValueError, 'NATIVE_S1_WRITER_RECORD'):
                                _publish_closure(directory, storage, binding, closure)
                        elif point == 'link':
                            with patch(f'{mod}.os.link', side_effect=OSError(errno.EIO, point)), self.assertRaises(OSError):
                                _publish_closure(directory, storage, binding, closure)
                        elif point != 'complete':
                            with self.assertRaises(OSError):
                                _publish_closure(directory, storage, binding, closure)
                        else:
                            _publish_closure(directory, storage, binding, closure)
                    self.assertEqual((root / _CLOSED).exists(), point in ('directory-fsync', 'complete'))
                    self.assertEqual((root / _CLOSED_SYNCED).exists(), point == 'complete')
                    if point == 'directory-fsync':
                        with patch(f'{mod}.os.fchown'), self.assertRaises(FileExistsError):
                            _publish_closure(directory, storage, binding, closure)
                    result = subprocess.run([sys.executable, '-B', '-c', _CONSUMER, temporary,
                                             json.dumps(binding.to_wire())], capture_output=True, check=True,
                                            text=True, timeout=5)
                    self.assertEqual(result.stdout.strip(), '9'*64 if point == 'complete'
                                     else 'NATIVE_S1_WRITER_CLOSURE_UNAVAILABLE')
                finally:
                    os.close(directory)
