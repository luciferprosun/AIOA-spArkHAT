"""Strict communication with a pre-owned peer; no tool or inference authority."""

import json
import socket
import threading
import unittest

from runtime.mission import codex_worker
from runtime.mission.worker import WorkerError
from runtime.providers.exact import CancellationToken


class CodexTransportTests(unittest.TestCase):
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

    def test_wrong_response_id_and_tool_approval_never_gain_authority(self):
        transport, peer = self.transport()
        peer.sendall(b'{"id":999,"result":{}}\n')
        with self.assertRaisesRegex(WorkerError, "PROTOCOL_RESPONSE_BINDING"):
            transport.initialize()
        other, other_peer = self.transport()
        other.bind_turn("thread-1", "turn-1")
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
