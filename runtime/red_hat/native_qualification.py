"""Explicit disposable Native composition. No production factory installs this port."""

import hashlib
import os
import secrets
import select
import socket
import time
from dataclasses import dataclass
from pathlib import Path

from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import transaction_active
from runtime.red_hat.authenticated_boundary import authorize_fixture
from runtime.red_hat.broker_protocol import FRAME_TIMEOUT, Peer, authenticate, require, send_frame
from runtime.red_hat.core_adapter import CoreIntentAdapter
from runtime.red_hat.enrollment import ExecutorEnrollment
from runtime.red_hat.execution_binding import digest_string, physical_context
from runtime.red_hat.object_ingress import MAX_BATCH_BYTES, decode_objects, encode_objects, import_objects
from runtime.red_hat.sequenced_boundary import handle_fixture_release
from runtime.red_hat.sequencer import SequencedCoreGate


@dataclass(frozen=True, slots=True)
class NativeQualificationPort:
    """Supervisor-selected channels. No task or model input chooses a peer or a path."""

    gate: SequencedCoreGate
    enrollment: ExecutorEnrollment
    device_id: str
    broker_peer: Peer
    endpoint: str
    release_listener: socket.socket
    anchor: int
    nonce: str
    issued_at: int
    expires_at: int
    storage: object = None

    def __post_init__(self):
        require(type(self.gate) is SequencedCoreGate and type(self.enrollment) is ExecutorEnrollment
                and type(self.broker_peer) is Peer and self.broker_peer.uid == self.enrollment.executor.uid
                and self.broker_peer.pid != os.getpid() and type(self.device_id) is str
                and type(self.endpoint) is str and os.path.isabs(self.endpoint)
                and type(self.release_listener) is socket.socket
                and self.release_listener.family == socket.AF_UNIX
                and self.release_listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
                and type(self.anchor) is int and self.anchor >= 3 and digest_string(self.nonce)
                and type(self.issued_at) is int and type(self.expires_at) is int
                and not self.enrollment.revoked and self.enrollment.valid_from <= self.issued_at
                and self.expires_at <= self.enrollment.valid_until
                and 0 < self.expires_at - self.issued_at <= 300, "NATIVE_QUALIFICATION_CONFIGURATION")

        if self.storage is not None:
            from runtime.red_hat.role_storage import RoleStorage
            require(type(self.storage) is RoleStorage and self.storage.staging is not None
                    and (self.broker_peer.uid, self.broker_peer.gid)
                        == (self.storage.broker.uid, self.storage.broker.gid),
                    "NATIVE_QUALIFICATION_CONFIGURATION")
            self.storage.require_role("core")
            self.storage.require_anchor(self.anchor)

    @classmethod
    def prepare(cls, *, gate, enrollment, device_id, broker_peer, endpoint,
                release_listener, anchor, lifetime, enabled=False, storage=None):
        require(enabled is True and type(lifetime) is int and 0 < lifetime <= 300,
                "NATIVE_QUALIFICATION_CONFIGURATION")
        now = int(time.time())
        return cls(gate, enrollment, device_id, broker_peer, endpoint, release_listener,
                   anchor, secrets.token_hex(32), now, now + lifetime, storage)

    def metadata(self, route):
        root = Path(route.target_repository).stat()
        child = os.stat("repo", dir_fd=self.anchor, follow_symlinks=False)
        require((root.st_dev, root.st_ino) == (child.st_dev, child.st_ino)
                and route.plan.ref == "refs/heads/aioa/nz11-" + route.capsule.digest[:32],
                "NATIVE_QUALIFICATION_TARGET")
        storage_fields = {}
        if self.storage is not None:
            self.storage.require_role("core")
            self.storage.require_anchor(self.anchor)
            require(route.plan.ref == self.storage.exact_ref and (child.st_dev, child.st_ino)
                    == (self.storage.repository.device, self.storage.repository.inode),
                    "NATIVE_QUALIFICATION_TARGET")
            storage_fields["storage_digest"] = self.storage.digest
        return {**storage_fields, **physical_context(self.anchor, exact_ref=route.plan.ref),
                "nonce": self.nonce, "executor_id": self.enrollment.executor.executor,
                "executor_key_id": self.enrollment.executor.key_id,
                "key_epoch": self.enrollment.key_epoch, "broker_epoch": self.gate._client.epoch,
                "issued_at": self.issued_at, "expires_at": self.expires_at}

    def dispatch(self, route, controller, principal, warrant, release):
        require(not transaction_active() and route.runner.execution_gate is self.gate
                and controller.journal is route.journal, "NATIVE_QUALIFICATION_CONFIGURATION")
        # Runs on the owning apply thread, so the lifecycle, cancellation token,
        # durable START and original consumed warrant are all independently checked.
        controller._native_git_effect_check(route, warrant, Capability.COMMIT)
        adapter = CoreIntentAdapter(route.journal)
        seq = self.gate._client
        objects = encode_objects(route.plan.objects)
        batch = {"bytes": len(objects), "sha256": hashlib.sha256(objects).hexdigest()}
        binding, grant = authorize_fixture(
            adapter, principal, warrant, self.enrollment, route.identity,
            trusted_device_id=self.device_id, now=int(time.time()), broker_epoch=seq.epoch, object_batch=batch, enabled=True)
        req = binding.request
        require((req.nonce, req.issued_at, req.expires_at, req.exact_ref, req.new_oid)
                == (self.nonce, self.issued_at, self.expires_at, route.plan.ref, route.plan.commit_sha)
                and binding.storage_digest == (None if self.storage is None else self.storage.digest)
                and binding.capsule_digest == route.capsule.digest
                and binding.plan_digest == route.plan.digest, "NATIVE_QUALIFICATION_START_MISMATCH")
        with socket.socket(socket.AF_UNIX) as peer:
            peer.settimeout(FRAME_TIMEOUT)
            peer.connect(self.endpoint)
            authenticate(peer, self.broker_peer)
            send_frame(peer, grant, body=objects)
            ready, _, _ = select.select([peer, self.release_listener], [], [], FRAME_TIMEOUT)
            if self.release_listener in ready:
                handle_fixture_release(
                    self.release_listener, sequence=seq, gate=self.gate, broker_peer=self.broker_peer,
                    signer=route.identity, expected=binding, adapter=adapter, principal=principal,
                    warrant=warrant, enrollment=self.enrollment, trusted_device_id=self.device_id,
                    require_owned_work=release, enabled=True)
                # Allow the broker to finish after the final release. An ACK is
                # informational. Only a separate authenticated verifier can settle.
                select.select([peer], [], [], FRAME_TIMEOUT)
        raise CommitOutcomeUnknown()


def serve_prepared_native_fixture(listener, *, root_fd, exact_ref, device_id, sequence,
                                  release, core_peer, core_spki, identity, enrollment,
                                  core_epoch, broker_epoch, enabled=False):
    """Start before START exists. Accept only a signed grant for this launch target."""
    require(enabled is True and type(core_peer) is Peer
            and core_peer.uid == os.geteuid() == enrollment.executor.uid,
            "RH07_FIXTURE_ONLY_NO_QUALIFIED_CONFINEMENT")
    return _serve_prepared_native(
        listener, root_fd=root_fd, exact_ref=exact_ref, device_id=device_id, sequence=sequence,
        release=release, core_peer=core_peer, core_spki=core_spki, identity=identity,
        enrollment=enrollment, core_epoch=core_epoch, broker_epoch=broker_epoch)


def serve_qualified_native_once(listener, *, root_fd, storage, device_id, sequence,
                                release, core_peer, core_spki, signer_fd, enrollment,
                                core_epoch, broker_epoch, enabled=False, on_ready=None):
    """Explicit disposable entry point for a supervisor-provisioned writer."""
    from runtime.red_hat.executor_custody import ExecutorRoles, load_broker_signer
    from runtime.red_hat.role_storage import RoleStorage

    require(type(signer_fd) is int and signer_fd >= 3, "RH07_SIGNER_FD")
    try:
        require(enabled is True and type(storage) is RoleStorage and type(core_peer) is Peer
                and (core_peer.uid, core_peer.gid) == (storage.core.uid, storage.core.gid)
                and core_peer.pid != os.getpid(), "NATIVE_STORAGE_WRITER_CONFIGURATION")
        storage.require_writer(root_fd)
        roles = ExecutorRoles(storage.core.uid, storage.broker.uid, storage.verifier.uid,
                              storage.broker.gid)
        identity = load_broker_signer(signer_fd, roles, enrollment,
                                      key_epoch=enrollment.key_epoch, now=int(time.time()),
                                      enabled=True, storage=storage)
    finally:
        os.close(signer_fd)
    return _serve_prepared_native(
        listener, root_fd=root_fd, exact_ref=storage.exact_ref, device_id=device_id,
        sequence=sequence, release=release, core_peer=core_peer, core_spki=core_spki,
        identity=identity, enrollment=enrollment, core_epoch=core_epoch,
        broker_epoch=broker_epoch, storage=storage, on_ready=on_ready)


def _serve_prepared_native(listener, *, root_fd, exact_ref, device_id, sequence,
                           release, core_peer, core_spki, identity, enrollment,
                           core_epoch, broker_epoch, storage=None, on_ready=None):
    from runtime.red_hat.authenticated_boundary import AUTHORIZATION, _open_seal
    from runtime.red_hat.broker_protocol import digest, read_frame, require_admission
    from runtime.red_hat.broker_service import _serve_fixture
    from runtime.red_hat.execution_binding import NativeExecutionBindingV1, require_physical_context
    from runtime.red_hat.fixture_repository import native_parent_name
    from runtime.red_hat.sequenced_boundary import CoreReleaseClient
    from runtime.red_hat.sequencer import SequenceClient

    require(native_parent_name(exact_ref) == "aioa"
            and type(sequence) is SequenceClient and sequence.epoch == broker_epoch
            and type(release) is CoreReleaseClient and release.peer == core_peer
            and core_spki == release.core_spki and core_spki != identity.spki,
            "NATIVE_QUALIFICATION_BROKER_CONFIGURATION")
    binding = None
    objects = None

    def receive(peer):
        nonlocal binding, objects
        authenticate(peer, core_peer)

        def validate_and_read(frame, read_exact):
            signed = _open_seal(frame, core_spki, AUTHORIZATION)
            require(set(signed) == {"schema", "binding", "object_batch"}, "RH06_AUTHORIZATION")
            candidate = NativeExecutionBindingV1.from_wire(signed["binding"])
            require(candidate.storage_digest == (None if storage is None else storage.digest),
                    "NATIVE_STORAGE_START_DIGEST")
            req = candidate.request
            require(req.device_id == device_id and req.exact_ref == exact_ref,
                    "NATIVE_QUALIFICATION_TARGET")
            require_admission(req, enrollment, now=int(time.time()), core_epoch=core_epoch,
                              broker_epoch=broker_epoch)
            batch = signed["object_batch"]
            require(type(batch) is dict and set(batch) == {"bytes", "sha256"}
                    and type(batch["bytes"]) is int and 0 < batch["bytes"] <= MAX_BATCH_BYTES
                    and digest_string(batch["sha256"]), "NATIVE_OBJECT_BATCH")
            raw = read_exact(batch["bytes"])
            require(hashlib.sha256(raw).hexdigest() == batch["sha256"], "NATIVE_OBJECT_BATCH")
            return candidate, decode_objects(raw, expected_commit=req.new_oid)

        binding, objects = read_frame(peer, receive_body=validate_and_read)
        return binding.request

    if on_ready is not None:
        on_ready()
    return _serve_fixture(
        listener, root_fd=root_fd, receive=receive, enrollment=enrollment, identity=identity,
        core_epoch=core_epoch, broker_epoch=broker_epoch, clock=lambda: int(time.time()),
        fault=lambda _: None, check_context=lambda target: require_physical_context(target, binding),
        prepare=lambda target: import_objects(target.repo, target.uid, objects,
                                              reader_gid=None if storage is None else storage.reader_gid),
        storage=storage,
        sequence=lambda: sequence.hold(binding=digest(binding.to_wire())),
        revalidate=lambda token: release.require_release(binding, token, broker_epoch))
