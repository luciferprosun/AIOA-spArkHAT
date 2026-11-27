"""Opt-in RH-06 fixture IPC. No production composition installs this port."""

import secrets
import socket
import time
from contextlib import nullcontext
from dataclasses import asdict, fields

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mobile_gateway.wire import Identity, public_key, unbase64
from runtime.red_hat.broker_protocol import (
    FRAME_TIMEOUT, Peer, _no_fault, authenticate, digest, read_frame, require,
    require_admission, send_frame,
)
from runtime.red_hat.broker_service import _serve_fixture
from runtime.red_hat.core_adapter import CoreIntentAdapter, DisposableNativeTaskWitnessPort
from runtime.red_hat.execution_binding import (
    NativeExecutionBindingV1, capture_binding, digest_string, require_physical_context,
)
from runtime.red_hat.verifier import Verification, sign, verify


AUTHORIZATION = "aioa.redhat.fixture-core-authorization.v1"
CHALLENGE = "aioa.redhat.fixture-verifier-challenge.v1"
READBACK = "aioa.redhat.fixture-verifier-response.v1"


def _seal(identity, payload):
    require(type(identity) is Identity, "RH06_SIGNER")
    return {"payload": payload, "signature": sign(identity, payload)}


def _open_seal(envelope, spki, schema):
    require(type(envelope) is dict and set(envelope) == {"payload", "signature"}
            and type(envelope["payload"]) is dict
            and envelope["payload"].get("schema") == schema, "RH06_ENVELOPE")
    payload = envelope["payload"]
    try:
        public_key(spki).verify(unbase64(envelope["signature"]), canonical_json_bytes(payload),
                                ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError, TypeError):
        require(False, "RH06_SIGNATURE")
    return payload


def authorize_fixture(adapter, principal, warrant, enrollment, identity, *,
                      trusted_device_id, now, broker_epoch, object_batch=None, enabled=False):
    """Export a fixture grant after Core confirms durable START and current authority."""
    require(enabled is True, "RH06_DISABLED")
    require(type(identity) is Identity and identity.spki != enrollment.executor.spki,
            "RH06_ROLE_KEYS")
    binding = capture_binding(adapter, principal, warrant, enrollment,
                              trusted_device_id=trusted_device_id, now=now,
                              broker_epoch=broker_epoch, for_grant_export=True)
    payload = {"schema": AUTHORIZATION, "binding": binding.to_wire()}
    if object_batch is not None:
        payload["object_batch"] = object_batch
    return binding, _seal(identity, payload)


def serve_authenticated_fixture_once(listener, *, root_fd, expected, enrollment, identity,
                                     core_peer, core_spki, core_epoch, broker_epoch,
                                     clock=lambda: int(time.time()), fault=_no_fault, enabled=False):
    """Consume a verified Core envelope before entering the existing fixture CAS."""
    require(enabled is True, "RH06_DISABLED")
    return _serve_authenticated_fixture(
        listener, root_fd=root_fd, expected=expected, enrollment=enrollment, identity=identity,
        core_peer=core_peer, core_spki=core_spki, core_epoch=core_epoch,
        broker_epoch=broker_epoch, clock=clock, fault=fault)


def _serve_authenticated_fixture(listener, *, root_fd, expected, enrollment, identity,
                                 core_peer, core_spki, core_epoch, broker_epoch, clock, fault,
                                 sequence=nullcontext, revalidate=_no_fault):
    require(type(expected) is NativeExecutionBindingV1
            and core_spki != enrollment.executor.spki, "RH06_ROLE_KEYS")

    def receive(peer):
        authenticate(peer, core_peer)
        payload = _open_seal(read_frame(peer), core_spki, AUTHORIZATION)
        require(set(payload) == {"schema", "binding"}, "RH06_AUTHORIZATION")
        binding = NativeExecutionBindingV1.from_wire(payload["binding"])
        require(binding == expected, "RH06_START_BINDING")
        require_admission(binding.request, enrollment, now=clock(), core_epoch=core_epoch,
                          broker_epoch=broker_epoch)
        return binding.request

    return _serve_fixture(listener, root_fd=root_fd, receive=receive, enrollment=enrollment,
                          identity=identity, core_epoch=core_epoch, broker_epoch=broker_epoch,
                          clock=clock, fault=fault,
                          check_context=lambda target: require_physical_context(target, expected),
                          sequence=sequence, revalidate=revalidate)


def serve_verifier_fixture_once(listener, *, root_fd, binding, enrollment, identity, core_peer,
                                core_spki, now, enabled=False, storage=None):
    """Independently verify physical evidence and sign a fresh challenge response."""
    require(enabled is True, "RH06_DISABLED")
    require(type(binding) is NativeExecutionBindingV1 and type(identity) is Identity
            and len({identity.spki, core_spki, enrollment.executor.spki}) == 3, "RH06_ROLE_KEYS")
    if storage is not None:
        from runtime.red_hat.role_storage import RoleStorage
        require(type(storage) is RoleStorage and type(core_peer) is Peer
                and (core_peer.uid, core_peer.gid) == (storage.core.uid, storage.core.gid),
                "NATIVE_STORAGE_CORE_PEER")
        storage.require_role("verifier")
    binding_digest = digest(binding.to_wire())
    with listener.accept()[0] as peer:
        authenticate(peer, core_peer)
        query = read_frame(peer)
        require(type(query) is dict and set(query) == {"schema", "binding_digest", "challenge"}
                and query["schema"] == CHALLENGE and query["binding_digest"] == binding_digest
                and digest_string(query["challenge"]), "RH06_VERIFIER_CHALLENGE")
        request = binding.request
        report = verify(root_fd, request, enrollment, now=now, core_epoch=request.core_epoch,
                        broker_epoch=request.broker_epoch,
                        check_context=lambda target: require_physical_context(target, binding),
                        storage=storage)
        send_frame(peer, _seal(identity, {
            "schema": READBACK, "challenge": query["challenge"], "binding_digest": binding_digest,
            "facts": asdict(report), "observed_at": now,
        }))


def _report(value):
    names = {f.name for f in fields(Verification)}
    require(type(value) is dict and set(value) == names, "RH06_VERIFIER_FACTS")
    hashes = {"witness_sha256", "completion_sha256"}
    stamp = {"published_inode", "published_ctime_ns"}
    require(all(type(value[key]) is bool for key in names - hashes - stamp)
            and all(value[key] is None or digest_string(value[key]) for key in hashes),
            "RH06_VERIFIER_FACTS")
    inode = value["published_inode"]
    ctime = value["published_ctime_ns"]
    require((inode is None or (type(inode) is list and len(inode) == 2
                              and all(type(part) is int and part > 0 for part in inode)))
            and (ctime is None or (type(ctime) is int and ctime > 0)), "RH06_VERIFIER_FACTS")
    return Verification(**{**value, "published_inode": None if inode is None else tuple(inode)})


def _read_authenticated_report(endpoint, peer, spki, binding, *, now):
    challenge = secrets.token_hex(32)
    binding_digest = digest(binding.to_wire())
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(FRAME_TIMEOUT)
        stream.connect(endpoint)
        authenticate(stream, peer)
        send_frame(stream, {"schema": CHALLENGE, "binding_digest": binding_digest,
                            "challenge": challenge})
        payload = _open_seal(read_frame(stream), spki, READBACK)
    require(set(payload) == {"schema", "challenge", "binding_digest", "facts", "observed_at"}
            and type(payload["observed_at"]) is int and now - 5 <= payload["observed_at"] <= now
            and payload["challenge"] == challenge and payload["binding_digest"] == binding_digest,
            "RH06_VERIFIER_REPLAY_OR_BINDING")
    return _report(payload["facts"]), peer.pid


class _AuthenticatedReadbackAdapter(CoreIntentAdapter):
    """Per-call adapter reusing RH-04 physical rechecks and Core settlement."""

    def __init__(self, journal, binding, endpoint, peer, spki, storage=None):
        super().__init__(journal)
        self.binding, self.endpoint, self.peer, self.spki = binding, endpoint, peer, spki
        self.storage = storage

    def _open_readback_repository(self, root_fd, request, executor_uid):
        if self.storage is None:
            return super()._open_readback_repository(root_fd, request, executor_uid)
        from runtime.red_hat.fixture_repository import open_repository
        return open_repository(root_fd, request, executor_uid, storage=self.storage, role="core")

    def _check_fixture_target(self, target):
        require_physical_context(target, self.binding)

    def _verify_fresh_process(self, root_fd, request, enrollment, *, now, core_epoch, broker_epoch):
        require(request == self.binding.request and request.core_epoch == core_epoch
                and request.broker_epoch == broker_epoch, "RH06_VERIFIER_START")
        require(enrollment.permits(request, now), "RH06_VERIFIER_ENROLLMENT")
        return _read_authenticated_report(self.endpoint, self.peer, self.spki, self.binding, now=now)


class AuthenticatedFixtureRecoveryPort(DisposableNativeTaskWitnessPort):
    """Trusted test composition supplies resolver, endpoint and public role keys."""

    def __init__(self, adapter, coding_tasks, resolver, *, endpoint, verifier_peer,
                 verifier_spki, core_spki, enabled=False, storage=None):
        require(enabled is True, "RH06_DISABLED")
        super().__init__(adapter, coding_tasks, resolver)
        self.endpoint, self.peer, self.spki = endpoint, verifier_peer, verifier_spki
        self.core_spki = core_spki
        if storage is not None:
            from runtime.red_hat.role_storage import RoleStorage
            require(type(storage) is RoleStorage and type(verifier_peer) is Peer
                    and (verifier_peer.uid, verifier_peer.gid) == (storage.verifier.uid, storage.verifier.gid),
                    "NATIVE_STORAGE_VERIFIER_PEER")
        self.storage = storage

    def recover_native_task(self, principal, task_id):
        material = self.resolver(task_id)
        require(type(material) is dict and set(material) == self._FIELDS, "RH06_RECOVERY_PORT")
        enrollment = material["enrollment"]
        require(len({self.spki, self.core_spki, enrollment.executor.spki}) == 3, "RH06_ROLE_KEYS")
        binding = capture_binding(
            self.adapter, principal, material["warrant"], enrollment,
            trusted_device_id=material["trusted_device_id"], now=material["now"],
            broker_epoch=material["broker_epoch"],
        )
        require(binding.request == material["request"], "RH06_RECOVERY_START")
        target = _AuthenticatedReadbackAdapter(self.adapter.journal, binding, self.endpoint,
                                               self.peer, self.spki, self.storage)
        return target.recover_disposable_native_task_fixture(
            principal, self.coding_tasks, task_id, **material)
