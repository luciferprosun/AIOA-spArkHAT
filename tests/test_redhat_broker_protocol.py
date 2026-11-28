import os
import socket
import struct
import tempfile
import unittest
from array import array
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric import ec

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.broker_protocol import (
    AttemptGuard, BrokerRequest, Peer, ProtocolError, read_frame, receive_request, send_frame,
)
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.witness import RegisteredExecutor


NOW = 1_800_000_000


def fixture_request(**changes):
    values = dict(
        operation_id="fixture-operation", attempt_id="fixture-attempt",
        owner_id="fixture-owner", device_id="fixture-device", executor_id="fixture-executor",
        executor_key_id="a" * 64, key_epoch=3, start_digest="1" * 64,
        intent_digest="2" * 64, warrant_digest="3" * 64, reservation_digest="4" * 64,
        core_epoch=5, broker_epoch=7, nonce="6" * 64, challenge="7" * 64,
        repository_dev=2, repository_inode=3, ref_directory_dev=2, ref_directory_inode=4,
        exact_ref="refs/heads/native69", old_oid="0" * 40, new_oid="f" * 40,
        issued_at=NOW - 1, expires_at=NOW + 30,
    )
    return BrokerRequest.for_fixture(**(values | changes))


def fixture_enrollment(identity=None):
    identity = identity or Identity(ec.generate_private_key(ec.SECP256R1()))
    executor = RegisteredExecutor("fixture-executor", os.getuid(), identity.spki)
    return ExecutorEnrollment(executor, 3, NOW - 60, NOW + 600), identity


class BrokerProtocolTests(unittest.TestCase):
    def setUp(self):
        self.enrollment, _ = fixture_enrollment()
        self.request = fixture_request(executor_key_id=self.enrollment.executor.key_id)
        self.peer = Peer(os.getpid(), os.getuid(), os.getgid())

    def receive(self, payload, *, peer=None, enrollment=None, now=NOW, core_epoch=5, broker_epoch=7):
        sender, receiver = socket.socketpair()
        with sender, receiver:
            send_frame(sender, payload)
            return receive_request(receiver, peer or self.peer, self.request,
                                   enrollment or self.enrollment, now=now,
                                   core_epoch=core_epoch, broker_epoch=broker_epoch)

    def test_valid_authenticated_request(self):
        self.assertEqual(self.receive(self.request.to_wire()), self.request)

    def test_unauthorized_peer(self):
        with self.assertRaisesRegex(ProtocolError, "PEER"):
            self.receive(self.request.to_wire(), peer=replace(self.peer, pid=self.peer.pid + 1))

    def test_exact_schema_and_types(self):
        for payload in (self.request.to_wire() | {"extra": 0},
                        self.request.to_wire() | {"schema": "unknown"},
                        self.request.to_wire() | {"core_epoch": True},
                        self.request.to_wire() | {"expires_at": []}, {}):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                self.receive(payload)

    def test_wrong_authorized_binding(self):
        for key, value in (
            ("owner_id", "other-owner"), ("device_id", "other-device"),
            ("warrant_digest", "b" * 64), ("start_digest", "b" * 64),
            ("reservation_digest", "b" * 64), ("intent_digest", "b" * 64),
            ("repository_inode", 100), ("ref_directory_inode", 500),
            ("exact_ref", "refs/heads/elsewhere"), ("commit_permit_digest", "b" * 64),
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ProtocolError, "BINDING|PERMIT"):
                changed = replace(self.request, **{key: value})
                self.receive(changed.to_wire())

    def test_expired_permit_and_stale_epochs(self):
        with self.assertRaisesRegex(ProtocolError, "PERMIT"):
            self.receive(self.request.to_wire(), now=self.request.expires_at)
        for epochs in ({"core_epoch": 6}, {"broker_epoch": 8}):
            with self.subTest(epochs=epochs), self.assertRaisesRegex(ProtocolError, "EPOCH"):
                self.receive(self.request.to_wire(), **epochs)

    def test_unknown_retired_and_expired_enrollment(self):
        unknown, _ = fixture_enrollment()
        for enrollment in (unknown, replace(self.enrollment, revoked=True),
                           replace(self.enrollment, valid_until=NOW),
                           replace(self.enrollment, key_epoch=4)):
            with self.subTest(enrollment=enrollment), self.assertRaisesRegex(ProtocolError, "ENROLLMENT"):
                self.receive(self.request.to_wire(), enrollment=enrollment)

    def test_truncated_oversize_corrupt_and_trailing_frames(self):
        for data in (b"\x00", struct.pack("!I", 4) + b"a", struct.pack("!I", 65536),
                     struct.pack("!I", 1) + b"{", struct.pack("!I", 2) + b"{}a"):
            with self.subTest(data=data):
                sender, receiver = socket.socketpair()
                with sender, receiver, self.assertRaisesRegex(ProtocolError, "FRAME"):
                    sender.sendall(data)
                    sender.shutdown(socket.SHUT_WR)
                    receive_request(receiver, self.peer, self.request, self.enrollment,
                                    now=NOW, core_epoch=5, broker_epoch=7)

    def test_rejects_and_closes_received_descriptors(self):
        for count in (1, 32):
            sender, receiver = socket.socketpair()
            with self.subTest(count=count), sender, receiver, tempfile.TemporaryFile() as handle:
                before = set(os.listdir("/proc/self/fd"))
                sender.sendmsg([b"\0"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                             array("i", [handle.fileno()] * count))])
                with self.assertRaisesRegex(ProtocolError, "BROKER_FRAME_ANCILLARY"):
                    read_frame(receiver)
                self.assertEqual(set(os.listdir("/proc/self/fd")), before)

    def test_attempt_and_nonce_survive_reopen(self):
        with tempfile.TemporaryDirectory() as path:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                AttemptGuard(fd).consume(self.request)
                for changes in ({}, {"nonce": "9" * 64, "attempt_id": "new-attempt"},
                                {"operation_id": "new-operation"},
                                {"operation_id": "new-operation", "attempt_id": "new-attempt"}):
                    with self.subTest(changes=changes), self.assertRaisesRegex(ProtocolError, "REPLAY"):
                        AttemptGuard(fd).consume(fixture_request(**changes))
            finally:
                os.close(fd)

    def test_self_consistent_but_unapproved_permit_cannot_authorize(self):
        forged = fixture_request(owner_id="another-owner",
                                 executor_key_id=self.enrollment.executor.key_id)
        forged.require_permit(NOW)
        with self.assertRaisesRegex(ProtocolError, "BINDING"):
            self.receive(forged.to_wire())

    def test_orphan_attempt_blocks_further_consumption(self):
        with tempfile.TemporaryDirectory() as path:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                store = AttemptGuard(fd)
                store.consume(self.request)
                next(Path(path).glob("permit-*")).unlink()
                with self.assertRaisesRegex(ProtocolError, "STATE_RECORD"):
                    store.consume(fixture_request(operation_id="independent", attempt_id="new",
                                                  nonce="e" * 64))
            finally:
                os.close(fd)

    def test_repeated_stop_confirms_durability(self):
        with tempfile.TemporaryDirectory() as path:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                store = AttemptGuard(fd)
                store.stop()
                with patch("os.fsync", wraps=os.fsync) as sync:
                    store.stop()
                self.assertEqual(sync.call_count, 2)
                sync.assert_any_call(fd)
                with self.assertRaisesRegex(ProtocolError, "STOPPED"):
                    store.consume(self.request)
            finally:
                os.close(fd)
