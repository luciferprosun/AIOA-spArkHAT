"""Typed startup and readiness boundary for disposable Native role services."""

import os
import select
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from runtime.core_admission import Capability
from runtime.red_hat.authenticated_boundary import serve_role_verifier_once
from runtime.red_hat.broker_protocol import Peer, read_frame, require, send_frame
from runtime.red_hat.native_bootstrap import ColdNativeBootstrap
from runtime.red_hat.native_qualification import NativeQualificationPort, serve_qualified_native_once
from runtime.red_hat.role_storage import DirectoryPin, RoleStorage, StorageActor
from runtime.red_hat.sequencer import SequenceClient, SequencedCoreGate, serve_sequencer
from runtime.red_hat.sequenced_boundary import CoreReleaseClient


@dataclass(frozen=True, slots=True)
class RoleEndpoint:
    location: str
    peer: Peer

    def __post_init__(self):
        require(type(self.location) is str and Path(self.location).is_absolute()
                and type(self.peer) is Peer, "NATIVE_SERVICE_ENDPOINT")



def start_listener(listener, location):
    """Start listening as the role, on a bound descriptor from the supervisor."""
    require(type(listener) is socket.socket and listener.family == socket.AF_UNIX
            and listener.type == socket.SOCK_STREAM and listener.getsockname() == location
            and not listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN), "NATIVE_SERVICE_LISTENER")
    listener.set_inheritable(False)
    listener.listen(8)


def _ready(control, role):
    require(type(control) is socket.socket and control.family == socket.AF_UNIX
            and control.type == socket.SOCK_STREAM and not control.get_inheritable(), "NATIVE_SERVICE_CONTROL")
    send_frame(control, {"schema": "aioa.redhat.service-ready.v1", "role": role})


def await_service_ready(child, control, expected_role, *, timeout=None):
    """Wait for an actual child process and its private readiness frame."""
    # The existing loginctl + interactive polkit admission can take up to
    # 130 seconds. Other workers do not get that startup budget.
    limit = 150 if expected_role == "core" else 20
    if timeout is None:
        timeout = limit if expected_role == "core" else 5
    require(type(child) is subprocess.Popen and child.poll() is None
            and type(control) is socket.socket and expected_role in ("core", "broker", "verifier", "sequencer")
            and type(timeout) in (float, int) and 0 < timeout <= limit, "NATIVE_SERVICE_CONTROL")
    pidfd = os.pidfd_open(child.pid)
    try:
        ready, _, _ = select.select([control, pidfd], [], [], timeout)
        require(ready == [control], "NATIVE_SERVICE_DIED_OR_NOT_READY")
        require(read_frame(control) == {"schema": "aioa.redhat.service-ready.v1", "role": expected_role}
                and not select.select([pidfd], [], [], 0)[0], "NATIVE_SERVICE_DIED_OR_NOT_READY")
    finally:
        os.close(pidfd)


def await_broker_completion(writer, channel, binding, enrollment, *, deadline):
    """Collect the private broker stage and wait for exit without reaping it."""
    from runtime.red_hat.writer_lifecycle import OneShotWriter

    require(type(writer) is OneShotWriter and writer.pidfd is not None
            and type(channel) is socket.socket and channel.family == socket.AF_UNIX
            and channel.type == socket.SOCK_STREAM and not channel.get_inheritable(),
            "NATIVE_S1_COMPLETION_CHANNEL")
    channel.getpeername()
    remaining = deadline - time.monotonic()
    require(0 < remaining <= 20 and select.select([channel], [], [], remaining)[0],
            "NATIVE_S1_COMPLETION_TIMEOUT")
    report = read_frame(channel)
    remaining = deadline - time.monotonic()
    require(remaining > 0 and select.select([writer.pidfd], [], [], remaining)[0]
            and time.monotonic() < deadline, "NATIVE_S1_WRITER_STILL_LIVE")
    writer.close_writer(binding, report, enrollment)


def run_broker(listener, location, control, *, root_fd, storage, device_id, sequencer,
               release, core_spki, signer_fd, enrollment, core_epoch, completion=None, fault=lambda _: None,
               writer_admission=None, before_ack=None):
    require(type(signer_fd) is int and signer_fd >= 3, "RH07_SIGNER_FD")
    try:
        require(type(storage) is RoleStorage and type(sequencer) is SequenceClient
                and type(release) is RoleEndpoint, "NATIVE_SERVICE_CONFIGURATION")
        require(type(completion) is socket.socket and completion.family == socket.AF_UNIX
                and completion.type == socket.SOCK_STREAM and not completion.get_inheritable()
                and len({os.fstat(item.fileno()).st_ino for item in (listener, control, completion)}) == 3,
                "NATIVE_S1_COMPLETION_CHANNEL")
        completion.getpeername()  # Reject an unconnected channel before exposing readiness.
        controlled_release = CoreReleaseClient(release.location, release.peer, core_spki)
        start_listener(listener, location)
    except BaseException:
        os.close(signer_fd)
        raise
    return serve_qualified_native_once(
        listener, root_fd=root_fd, storage=storage, device_id=device_id, sequence=sequencer,
        release=controlled_release, core_peer=release.peer,
        core_spki=core_spki, signer_fd=signer_fd, enrollment=enrollment, core_epoch=core_epoch,
        broker_epoch=sequencer.epoch, enabled=True, on_ready=lambda: _ready(control, "broker"),
        on_completion=lambda report: send_frame(completion, report), fault=fault,
        writer_admission=writer_admission, before_ack=before_ack,
    )


def run_verifier(listener, location, control, *, root_fd, storage, enrollment,
                 identity, core_peer, core_spki, reads, qualification_fault_challenge=False,
                 qualification_read=None, succession=None):
    require(type(reads) is int and 1 <= reads <= 8, "NATIVE_SERVICE_VERIFIER_LIMIT")
    start_listener(listener, location)
    for index in range(reads):
        serve_role_verifier_once(
            listener, root_fd=root_fd, storage=storage, enrollment=enrollment,
            identity=identity, core_peer=core_peer, core_spki=core_spki, enabled=True,
            qualification_fault_challenge=qualification_fault_challenge,
            qualification_read=qualification_read if index == 0 else None, succession=succession,
            on_ready=(lambda: _ready(control, "verifier")) if index == 0 else None,
        )


def run_sequencer(listener, location, control, *, directory, directory_pin, actor, reader_gid, mount_namespace,
                  core_peer, broker_peer, epoch, stop, fault=lambda _: None,
                  publication_fault=lambda _point, _stream: None):
    require(type(directory_pin) is DirectoryPin and type(actor) is StorageActor and type(core_peer) is Peer and type(broker_peer) is Peer
            and len({actor.uid, core_peer.uid, broker_peer.uid}) == 3
            and os.stat("/proc/self/ns/mnt").st_ino == mount_namespace, "NATIVE_SERVICE_SEQUENCE_ROLE")
    actor.require_process(reader_gid)
    directory_pin.require_fd(directory)
    start_listener(listener, location)
    serve_sequencer(listener, directory=directory, core_peer=core_peer, broker_peer=broker_peer,
                    epoch=epoch, stop=stop, enabled=True, on_ready=lambda: _ready(control, "sequencer"),
                    timeout=5, active_timeout=15, fence_restart=True, fault=fault, publication_fault=publication_fault)


def start_core(control, *, root, origin, spec, candidates, existing_profile,
               gate=None, cold_bootstrap=None):
    """Start the existing Core as an admitted local operator and acknowledge startup."""
    from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition

    require((type(gate) is SequencedCoreGate and cold_bootstrap is None)
            or (gate is None and type(cold_bootstrap) is ColdNativeBootstrap),
            "NATIVE_SERVICE_CORE_CONFIGURATION")
    host = NativeMobileComposition(
        root, origin=origin, host_composition=spec, offline_candidates=candidates,
        existing_profile=existing_profile, qualification_gate=gate, cold_bootstrap=cold_bootstrap,
    )
    if cold_bootstrap is not None:
        return host  # Recovery readiness follows successful verifier attachment.
    try:
        _ready(control, "core")
    except BaseException:
        host.close()
        raise
    return host


def bind_core_publication(host, task_id, *, storage, anchor, sequencer, broker, release_listener,
                          enrollment, device_id, before_dispatch=None, hold_ack=None):
    """Bind one reviewed task after its capsule exists, before review_effect."""
    from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition

    require(type(host) is NativeMobileComposition and host._cold_bootstrap is None
            and type(storage) is RoleStorage and type(sequencer) is SequenceClient
            and type(broker) is RoleEndpoint, "NATIVE_SERVICE_CORE_CONFIGURATION")
    coding = host._native_coding
    with coding.prepare_lock:
        require(coding.qualification_port is None and coding.spec.qualification_target
                == storage.core_target().pre_capsule(), "NATIVE_SERVICE_CORE_CONFIGURATION")

        def read(tx):
            _, row, _ = host.coding_tasks._load(tx, task_id)
            last = row["receipts"][-1]["receipt"]
            capsule = last["capsule_digest"]
            require(last["state"] == "REVIEW_REQUIRED" and type(capsule) is str
                    and storage.exact_ref == "refs/heads/aioa/nz11-" + capsule[:32],
                    "NATIVE_SERVICE_CORE_CAPSULE")

        with coding.authority(Capability.READ) as principal:
            host.coding_tasks._run(principal, Capability.READ, read)
        gate = host._qualification_gate
        require(type(gate) is SequencedCoreGate and host.runner.execution_gate is gate
                and host.core.execution_gate is gate and gate._client == sequencer,
                "NATIVE_SERVICE_SEQUENCE_NOT_PREBOUND")
        port = NativeQualificationPort.prepare(
            gate=gate, enrollment=enrollment, device_id=device_id, broker_peer=broker.peer,
            endpoint=broker.location, release_listener=release_listener, anchor=anchor,
            lifetime=300, enabled=True, storage=storage, before_dispatch=before_dispatch, hold_ack=hold_ack,
        )
        coding.qualification_port = port
        return port


def bind_cold_verifier(host, verifier, verifier_spki, *, control=None):
    """Install the only effect-result port available to the authenticated cold Core."""
    from runtime.meta_hackathon.runtime_adapter import NativeMobileComposition

    require(type(host) is NativeMobileComposition and type(host._cold_bootstrap) is ColdNativeBootstrap
            and type(verifier) is RoleEndpoint and host.foundation is None
            and host.coding_tasks.native_witness_recovery_port is None, "NATIVE_SERVICE_COLD_CONFIGURATION")
    bootstrap = host._cold_bootstrap
    require(host._host_composition.qualification_target == bootstrap.storage.core_target(),
            "NATIVE_SERVICE_COLD_CONFIGURATION")
    host.coding_tasks.native_witness_recovery_port = bootstrap.recovery_port(
        host._cold_adapter, host.coding_tasks,
        endpoint=verifier.location, peer=verifier.peer, verifier_spki=verifier_spki, identity=host.identity,
    )
    if control is not None:
        _ready(control, "core")
