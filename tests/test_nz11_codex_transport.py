"""Strict communication with a pre-owned peer; no tool or inference authority."""

import json
import os
import socket
import threading
import unittest
from unittest.mock import patch

from runtime.mission import codex_worker
from runtime.mission.worker import Task, WorkerError, WorkerFailure
from runtime.providers.exact import CancellationToken


class CodexTransportTests(unittest.TestCase):
    def test_jsonl_rejects_floating_point_overflow(self):
        self.assertEqual(({"value": 100.0},), codex_worker.JsonlFramer().feed(b'{"value":1e2}\n'))
        for value in (b"1e999", b"-1e999"):
            with self.subTest(value=value), self.assertRaisesRegex(WorkerError, "^PROTOCOL_JSON$"):
                codex_worker.JsonlFramer().feed(b'{"value":' + value + b'}\n')

    def test_explicit_wire_version_must_be_jsonrpc_2_in_responses_and_events(self):
        for value in ("1.0", None, 2):
            with self.subTest(value=value):
                transport, peer = self.transport()
                peer.sendall(json.dumps({"jsonrpc": value, "id": 1, "result": {}}).encode() + b"\n")
                with self.assertRaisesRegex(WorkerError, "^PROTOCOL_VERSION$"):
                    transport.initialize()
        transport, peer = self.transport()
        peer.sendall(b'{"jsonrpc":"2.0","id":1,"result":{}}\n')
        self.assertEqual({}, transport.initialize())
        peer.sendall(b'{"jsonrpc":"1.0","method":"thread/started"}\n')
        with self.assertRaisesRegex(WorkerError, "^PROTOCOL_VERSION$"):
            transport.next_event()
        self.assertEqual([], transport.events)

    def test_uncertified_codex_worker_returns_no_candidate_or_authority(self):
        worker = codex_worker.CodexWorker(clock=lambda: 100)
        self.addCleanup(worker.close)
        task = Task("fixture-task", "fixture-run", "fixture-workspace", "fixture-repo",
                    "a" * 40, "Qualify worker refusal offline", 160)
        session = worker.start(task)
        outcome = worker.result(session)
        self.assertIs(type(outcome), WorkerFailure)
        self.assertEqual(("NOT_CERTIFIED", "NONE"), (outcome.code, outcome.authority))
        self.assertEqual((task.task_id, task.run_id), (outcome.task_id, outcome.run_id))

    def transport(self):
        cls = getattr(codex_worker, "OwnedCodexProtocol", None)
        self.assertTrue(callable(cls), "bounded owned App Server protocol is missing")
        client, peer = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(peer.close)
        value = cls(client.fileno(), client.fileno())
        self.addCleanup(value.close)
        return value, peer

    def test_initialize_thread_events_and_interrupt_correlate_with_current_v2_shape(
        self,
    ):
        transport, peer = self.transport()

        def server():
            with peer.makefile("rwb", buffering=0) as io:
                first = json.loads(io.readline())
                self.assertEqual(first["method"], "initialize")
                io.write(
                    json.dumps(
                        {"id": first["id"], "result": {"userAgent": "synthetic"}}
                    ).encode()
                    + b"\n"
                )
                self.assertEqual(json.loads(io.readline())["method"], "initialized")
                second = json.loads(io.readline())
                self.assertEqual(second["method"], "thread/start")
                self.assertEqual(second["params"]["sandbox"], "read-only")
                self.assertEqual(second["params"]["approvalPolicy"], "never")
                io.write(
                    json.dumps(
                        {
                            "method": "thread/started",
                            "params": {"thread": {"id": "thread-1"}},
                        }
                    ).encode()
                    + b"\n"
                )
                io.write(
                    json.dumps(
                        {"id": second["id"], "result": {"thread": {"id": "thread-1"}}}
                    ).encode()
                    + b"\n"
                )
                third = json.loads(io.readline())
                self.assertEqual(third["method"], "turn/interrupt")
                io.write(json.dumps({"id": third["id"], "result": {}}).encode() + b"\n")
                io.write(
                    json.dumps(
                        {
                            "method": "turn/completed",
                            "params": {
                                "threadId": "thread-1",
                                "turn": {
                                    "id": "turn-1",
                                    "status": "interrupted",
                                    "error": None,
                                },
                            },
                        }
                    ).encode()
                    + b"\n"
                )

        thread = threading.Thread(target=server, daemon=True)
        thread.start()
        self.assertEqual(transport.initialize()["userAgent"], "synthetic")
        self.assertEqual(transport.thread_start()["thread"]["id"], "thread-1")
        with self.assertRaisesRegex(WorkerError, "^PROTOCOL_THREAD_BINDING$"):
            transport.bind_turn("foreign-thread", "turn-1")
        transport.bind_turn("thread-1", "turn-1")
        transport.interrupt("thread-1", "turn-1")
        transport.next_event(seconds=1)
        self.assertEqual(transport.protocol.terminal_status, "CANCELLED")
        self.assertIn("thread/started", [event["method"] for event in transport.events])
        self.assertEqual(transport.authority, "NONE")
        self.assertEqual(codex_worker.CODEX_CERTIFICATION, "NOT_CERTIFIED")
        thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_timeout_cancellation_and_crash_are_typed_without_retry(self):
        transport, peer = self.transport()
        with self.assertRaisesRegex(WorkerError, "PROTOCOL_TIMEOUT"):
            transport.next_event(seconds=0.03)
        token = CancellationToken()
        token.cancel()
        with self.assertRaisesRegex(WorkerError, "CANCELLED"):
            transport.next_event(seconds=0.1, cancel=token)
        peer.shutdown(socket.SHUT_WR)
        with self.assertRaisesRegex(WorkerError, "PROTOCOL_EOF"):
            transport.next_event(seconds=0.1)

    def test_cancellation_does_not_deliver_an_already_buffered_event(self):
        transport, peer = self.transport()
        peer.sendall(b'{"method":"first"}\n{"method":"second"}\n')
        token = CancellationToken()
        self.assertEqual('first', transport.next_event(cancel=token)['method'])
        token.cancel()
        with self.assertRaisesRegex(WorkerError, '^CANCELLED$'):
            transport.next_event(cancel=token)
        self.assertEqual(['first'], [event['method'] for event in transport.events])

    def test_deadline_does_not_deliver_a_buffered_event(self):
        read_fd, peer_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, peer_fd)
        transport = codex_worker.OwnedCodexProtocol(read_fd, peer_fd)
        self.addCleanup(transport.close)
        os.write(peer_fd, b'{"method":"first"}\n{"method":"second"}\n')
        self.assertEqual("first", transport.next_event()["method"])
        with patch.object(codex_worker.time, "monotonic", side_effect=(100, 101)), \
                self.assertRaisesRegex(WorkerError, "^PROTOCOL_TIMEOUT$"):
            transport.next_event(seconds=0.01)
        self.assertEqual(["first"], [event["method"] for event in transport.events])
        self.assertEqual("second", transport.next_event()["method"])

    def test_send_does_not_write_if_deadline_expires_during_select(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        self.addCleanup(os.close, write_fd)
        transport = codex_worker.OwnedCodexProtocol(read_fd, write_fd)
        self.addCleanup(transport.close)
        now = [100.0]

        def ready(*args):
            now[0] = 101.0
            return [], [write_fd], []

        with patch.object(codex_worker.time, "monotonic", side_effect=lambda: now[0]), \
                patch("select.select", side_effect=ready), patch("os.write", wraps=os.write) as write, \
                self.assertRaisesRegex(WorkerError, "^PROTOCOL_TIMEOUT$"):
            try:
                transport._send({"method": "initialized"}, deadline=100.01)
            finally:
                write.assert_not_called()

    def test_wrong_response_id_and_tool_approval_never_gain_authority(self):
        transport, peer = self.transport()
        peer.sendall(b'{"id":999,"result":{}}\n')
        with self.assertRaisesRegex(WorkerError, "PROTOCOL_RESPONSE_BINDING"):
            transport.initialize()
        other, other_peer = self.transport()
        other_peer.sendall(
            b'{"id":42,"method":"item/commandExecution/requestApproval","params":{"threadId":"thread-1","turnId":"turn-1"}}\n'
        )
        other.next_event(seconds=0.1)
        denial = json.loads(other_peer.recv(4096))
        self.assertEqual(denial["error"]["code"], -32601)

    def test_diagnostic_transport_has_no_turn_start_or_generic_command_port(self):
        transport, _ = self.transport()
        for name in ("turn_start", "execute", "shell", "dispatch", "approve"):
            self.assertFalse(hasattr(transport, name))


if __name__ == "__main__":
    unittest.main()
