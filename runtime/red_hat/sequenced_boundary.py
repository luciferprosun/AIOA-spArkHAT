"""RH-07 fixture final release, ordered with existing Core control mutations."""

import os
import secrets
import socket
import time
from dataclasses import dataclass

from runtime.mobile_gateway.wire import Identity
from runtime.red_hat.authenticated_boundary import _open_seal, _seal, _serve_authenticated_fixture
from runtime.red_hat.broker_protocol import (
    FRAME_TIMEOUT, Peer, authenticate, digest, read_frame, require, send_frame,
)
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.execution_binding import NativeExecutionBindingV1, capture_binding, digest_string
from runtime.red_hat.sequencer import SequenceClient, SequencedCoreGate


RELEASE = "aioa.redhat.fixture-final-core-release.v1"


@dataclass(frozen=True, slots=True)
class CoreReleaseClient:
    endpoint: str
    peer: Peer
    core_spki: str

    def require_release(self, binding, token, epoch):
        challenge = secrets.token_hex(32)
        query = {"schema": RELEASE, "binding": digest(binding.to_wire()),
                 "token": token, "epoch": epoch, "challenge": challenge}
        with socket.socket(socket.AF_UNIX) as stream:
            stream.settimeout(FRAME_TIMEOUT)
            stream.connect(self.endpoint)
            authenticate(stream, self.peer)
            send_frame(stream, query)
            answer = _open_seal(read_frame(stream), self.core_spki, RELEASE)
        require(answer == {**query, "decision": "ALLOW"}, "RH07_RELEASE_DENIED")


def handle_fixture_release(listener, *, sequence, gate, broker_peer, signer, expected,
                           adapter, principal, warrant, enrollment, trusted_device_id,
                           require_owned_work, clock=lambda: int(time.time()), fault=lambda _: None,
                           enabled=False):
    """One request for Core's current authorization. No gate or SQL tx spans an IPC call."""
    require(enabled is True, "RH07_DISABLED")
    require(type(adapter) is CoreIntentAdapter, "RH07_RELEASE_CONFIGURATION")
    runner = adapter.journal.ledger.runner
    require(type(sequence) is SequenceClient and type(gate) is SequencedCoreGate
            and gate._client == sequence and getattr(runner, "execution_gate", None) is gate
            and adapter.journal.governor.runner is runner
            and getattr(runner._admission, "execution_gate", None) is gate
            and type(signer) is Identity and type(expected) is NativeExecutionBindingV1
            and callable(require_owned_work), "RH07_RELEASE_CONFIGURATION")
    with listener.accept()[0] as stream:
        authenticate(stream, broker_peer)
        query = read_frame(stream)
        binding = digest(expected.to_wire())
        require(type(query) is dict and set(query) == {
            "schema", "binding", "token", "epoch", "challenge",
        } and query["schema"] == RELEASE and query["binding"] == binding
            and type(query["epoch"]) is int and query["epoch"] == sequence.epoch
            and digest_string(query["token"]) and digest_string(query["challenge"]),
            "RH07_RELEASE_QUERY")
        sequence.check_publisher(binding, query["token"])
        try:
            # Trusted fixture composition checks its original owned task/cancel
            # binding. This is not a callback supplied by the IPC request.
            require_owned_work()
            current = capture_binding(
                adapter, principal, warrant, enrollment, trusted_device_id=trusted_device_id,
                now=clock(), broker_epoch=expected.request.broker_epoch, for_grant_export=True)
            require(current == expected, "RH07_RELEASE_START")
        except (OSError, ValueError):
            decision = "DENY"
        else:
            decision = "ALLOW"
        fault("before_release_reply")
        sequence.check_publisher(binding, query["token"])
        send_frame(stream, _seal(signer, {**query, "decision": decision}))


def serve_sequenced_fixture_once(listener, *, sequence, release, root_fd, expected,
                                 enrollment, identity, core_peer, core_spki, core_epoch,
                                 broker_epoch, clock=lambda: int(time.time()),
                                 fault=lambda _: None, enabled=False):
    """Signed fixture broker with an authenticated final check on the held slot."""
    require(enabled is True, "RH07_DISABLED")
    require(type(sequence) is SequenceClient and type(release) is CoreReleaseClient
            and release.peer == core_peer and release.core_spki == core_spki
            and type(expected) is NativeExecutionBindingV1, "RH07_RELEASE_CONFIGURATION")
    require(core_peer.uid == enrollment.executor.uid == os.geteuid(),
            "RH07_FIXTURE_ONLY_NO_QUALIFIED_CONFINEMENT")
    binding = digest(expected.to_wire())
    return _serve_authenticated_fixture(
        listener, root_fd=root_fd, expected=expected, enrollment=enrollment, identity=identity,
        core_peer=core_peer, core_spki=core_spki, core_epoch=core_epoch, broker_epoch=broker_epoch,
        clock=clock, fault=fault, sequence=lambda: sequence.hold(binding=binding),
        revalidate=lambda token: release.require_release(expected, token, sequence.epoch))
