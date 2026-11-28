"""Opt-in RH-06 fixture IPC. No production composition installs this port."""

import json
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
BOUND_CHALLENGE = "aioa.redhat.role-verifier-challenge.v1"


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
    require(storage is None, "NATIVE_S1_ROLE_VERIFIER_REQUIRED")
    require(type(binding) is NativeExecutionBindingV1 and type(identity) is Identity
            and len({identity.spki, core_spki, enrollment.executor.spki}) == 3, "RH06_ROLE_KEYS")
    binding_digest = digest(binding.to_wire())
    with listener.accept()[0] as peer:
        authenticate(peer, core_peer)
        query = read_frame(peer)
        require(type(query) is dict and set(query) == {"schema", "binding_digest", "challenge"}
                and query["schema"] == CHALLENGE and query["binding_digest"] == binding_digest
                and digest_string(query["challenge"]), "RH06_VERIFIER_CHALLENGE")
        _respond_to_verifier(peer, root_fd, binding, enrollment, identity,
                             challenge=query["challenge"], now=now, storage=storage)


def _respond_to_verifier(peer, root_fd, binding, enrollment, identity, *, challenge, now, storage,
                         expected_completion=None, qualification_read=None):
    request = binding.request
    report = verify(root_fd, request, enrollment, now=now, core_epoch=request.core_epoch,
                    broker_epoch=request.broker_epoch,
                    check_context=lambda target: require_physical_context(target, binding),
                    storage=storage, qualification_read=qualification_read)
    if storage is not None:
        require(report.completion_sha256 == expected_completion, "NATIVE_S1_COMPLETION_CHANGED")
    send_frame(peer, _seal(identity, {
        "schema": READBACK, "challenge": challenge, "binding_digest": digest(binding.to_wire()),
        "facts": asdict(report), "observed_at": now,
    }))


def serve_role_verifier_once(listener, *, root_fd, storage, enrollment, identity,
                             core_peer, core_spki, enabled=False, on_ready=None,
                             qualification_fault_challenge=False, qualification_read=None):
    """Accept only a signed original-binding challenge from the pinned cold Core."""
    from runtime.red_hat.role_storage import RoleStorage

    require(enabled is True and type(qualification_fault_challenge) is bool
            and type(storage) is RoleStorage and type(core_peer) is Peer
            and (core_peer.uid, core_peer.gid) == (storage.core.uid, storage.core.gid)
            and type(identity) is Identity and len({identity.spki, core_spki, enrollment.executor.spki}) == 3,
            "NATIVE_ROLE_VERIFIER_CONFIGURATION")
    storage.require_role("verifier")
    storage.require_anchor(root_fd)
    if on_ready is not None:
        on_ready()
    with listener.accept()[0] as peer:
        authenticate(peer, core_peer)
        query = _open_seal(read_frame(peer), core_spki, BOUND_CHALLENGE)
        require(set(query) == {"schema", "binding", "challenge"} and digest_string(query["challenge"]),
                "RH06_VERIFIER_CHALLENGE")
        binding = NativeExecutionBindingV1.from_wire(query["binding"])
        require(binding.storage_digest == storage.digest and binding.request.exact_ref == storage.exact_ref,
                "NATIVE_ROLE_VERIFIER_START")
        from runtime.red_hat.writer_lifecycle import require_writer_closed

        completion = require_writer_closed(root_fd, storage, binding)
        challenge = query["challenge"]
        if qualification_fault_challenge:
            # Explicit operator fault after authenticating the original request.
            # The signed readback is deliberately bound to a different challenge.
            challenge = ('1' if challenge[0] == '0' else '0') + challenge[1:]
        _respond_to_verifier(peer, root_fd, binding, enrollment, identity, challenge=challenge,
                             now=int(time.time()), storage=storage, expected_completion=completion,
                             qualification_read=qualification_read)


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


def _read_authenticated_report(endpoint, peer, spki, binding, *, now, signer=None):
    challenge = secrets.token_hex(32)
    binding_digest = digest(binding.to_wire())
    with socket.socket(socket.AF_UNIX) as stream:
        stream.settimeout(FRAME_TIMEOUT)
        stream.connect(endpoint)
        authenticate(stream, peer)
        query = {"schema": CHALLENGE, "binding_digest": binding_digest, "challenge": challenge}
        if signer is not None:
            query = _seal(signer, {"schema": BOUND_CHALLENGE, "binding": binding.to_wire(), "challenge": challenge})
        send_frame(stream, query)
        payload = _open_seal(read_frame(stream), spki, READBACK)
    latest = now if signer is None else min(int(time.time()), now + 5)
    require(set(payload) == {"schema", "challenge", "binding_digest", "facts", "observed_at"}
            and type(payload["observed_at"]) is int and now - 5 <= payload["observed_at"] <= latest
            and payload["challenge"] == challenge and payload["binding_digest"] == binding_digest,
            "RH06_VERIFIER_REPLAY_OR_BINDING")
    return _report(payload["facts"]), peer.pid


class _AuthenticatedReadbackAdapter(CoreIntentAdapter):
    """Per-call adapter reusing RH-04 physical rechecks and Core settlement."""

    def __init__(self, journal, binding, endpoint, peer, spki, storage=None, signer=None, *, run_verified_settlement=None):
        super().__init__(journal, run_verified_settlement=run_verified_settlement)
        self.binding, self.endpoint, self.peer, self.spki = binding, endpoint, peer, spki
        self.storage = storage
        self.signer = signer

    def _open_readback_repository(self, root_fd, request, executor_uid):
        if self.storage is None:
            return super()._open_readback_repository(root_fd, request, executor_uid)
        from runtime.red_hat.fixture_repository import open_repository
        from runtime.red_hat.writer_lifecycle import require_writer_closed

        require_writer_closed(root_fd, self.storage, self.binding)
        return open_repository(root_fd, request, executor_uid, storage=self.storage, role="core")

    def _check_fixture_target(self, target):
        require_physical_context(target, self.binding)

    def _verify_fresh_process(self, root_fd, request, enrollment, *, now, core_epoch, broker_epoch):
        require(request == self.binding.request and request.core_epoch == core_epoch
                and request.broker_epoch == broker_epoch, "RH06_VERIFIER_START")
        require(enrollment.permits(request, now), "RH06_VERIFIER_ENROLLMENT")
        report, pid = _read_authenticated_report(
            self.endpoint, self.peer, self.spki, self.binding, now=now, signer=self.signer)
        if self.storage is not None:
            from runtime.red_hat.writer_lifecycle import require_writer_closed

            completion = require_writer_closed(root_fd, self.storage, self.binding)
            require(report.completion_sha256 == completion, "NATIVE_S1_COMPLETION_CHANGED")
        return report, pid


class AuthenticatedFixtureRecoveryPort(DisposableNativeTaskWitnessPort):
    """Trusted test composition supplies resolver, endpoint and public role keys."""

    def __init__(self, adapter, coding_tasks, resolver, *, endpoint, verifier_peer,
                 verifier_spki, core_spki, enabled=False, storage=None, signer=None):
        require(enabled is True, "RH06_DISABLED")
        super().__init__(adapter, coding_tasks, resolver)
        self.endpoint, self.peer, self.spki = endpoint, verifier_peer, verifier_spki
        self.core_spki = core_spki
        require(signer is None or type(signer) is Identity and signer.spki == core_spki, "RH06_SIGNER")
        self.signer = signer
        if storage is not None:
            from runtime.red_hat.role_storage import RoleStorage
            require(type(storage) is RoleStorage and type(verifier_peer) is Peer
                    and (verifier_peer.uid, verifier_peer.gid) == (storage.verifier.uid, storage.verifier.gid),
                    "NATIVE_STORAGE_VERIFIER_PEER")
        self.storage = storage

    def _resolve_material(self, principal, task_id):
        return self.resolver(task_id)

    def recover_native_task(self, principal, task_id):
        material = self._resolve_material(principal, task_id)
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
                                               self.peer, self.spki, self.storage, self.signer,
                                               run_verified_settlement=self.adapter._run_verified_settlement)
        return target.recover_disposable_native_task_fixture(
            principal, self.coding_tasks, task_id, **material)


class DurableRoleRecoveryPort(AuthenticatedFixtureRecoveryPort):
    """Recover one approved task using its persisted Core records and host pins."""

    def __init__(self, adapter, coding_tasks, *, task_id, root_fd, enrollment,
                 trusted_device_id, broker_epoch, storage, endpoint, verifier_peer,
                 verifier_spki, core_spki, enabled=False, signer=None):
        from runtime.red_hat.enrollment import ExecutorEnrollment
        from runtime.red_hat.role_storage import RoleStorage

        require(enabled is True and type(storage) is RoleStorage
                and type(enrollment) is ExecutorEnrollment
                and type(root_fd) is int and root_fd >= 3
                and type(task_id) is str and 0 < len(task_id) <= 96
                and type(broker_epoch) is int and broker_epoch > 0
                and enrollment.executor.uid == storage.broker.uid,
                "NATIVE_ROLE_RECOVERY_CONFIGURATION")
        storage.require_role("core")
        storage.require_anchor(root_fd)
        super().__init__(adapter, coding_tasks, self._read_original, endpoint=endpoint,
                         verifier_peer=verifier_peer, verifier_spki=verifier_spki,
                         core_spki=core_spki, enabled=True, storage=storage, signer=signer)
        self.task_id = task_id
        self.root_fd = root_fd
        self.enrollment = enrollment
        self.device_id = trusted_device_id
        self.broker_epoch = broker_epoch

    def _resolve_material(self, principal, task_id):
        return self.resolver(principal, task_id)

    def _read_original(self, principal, task_id):
        require(task_id == self.task_id and self.coding_tasks.capsules.identity.spki == self.core_spki,
                "NATIVE_ROLE_RECOVERY_TASK")
        from runtime.core_admission import Capability

        journal = self.adapter.journal
        warrant = journal._run(principal, Capability.COMMIT, lambda tx: read_original_warrant_in_transaction(
            tx, journal, self.coding_tasks.capsules, task_id, self.storage))
        now = int(time.time())
        binding = capture_binding(self.adapter, principal, warrant, self.enrollment,
                                  trusted_device_id=self.device_id, now=now,
                                  broker_epoch=self.broker_epoch)
        require(binding.storage_digest == self.storage.digest, "NATIVE_ROLE_RECOVERY_START")
        return {"warrant": warrant, "request": binding.request, "enrollment": self.enrollment,
                "root_fd": self.root_fd, "trusted_device_id": self.device_id, "now": now,
                "core_epoch": binding.request.core_epoch, "broker_epoch": self.broker_epoch}

def read_original_warrant_in_transaction(tx, journal, capsules, task_id, storage, *, expected_source=None):
    """Read the same signed task/START in cold bootstrap and live readback."""
    from lab.archaioa.warrant import EffectWarrant
    from runtime.memory_patch.contracts.serialization import canonical_sha256
    from runtime.memory_patch.persistence.ports import RecordKind
    from runtime.mission.coding_tasks import KIND as TASK_KIND, decode_coding_task_row
    from runtime.mission.patch_capsule import KIND as CAPSULE_KIND
    from runtime.mission.warrant import KIND

    task_row = tx.get(RecordKind.OPERATION, canonical_sha256([TASK_KIND, task_id]))
    _, coding, task = decode_coding_task_row(task_row, task_id, capsules.identity.spki)
    receipt = coding["receipts"][-1]["receipt"]
    capsule = receipt["capsule_digest"]
    require(receipt["state"] in ("APPLYING", "UNKNOWN", "VERIFIED") and digest_string(capsule)
            and storage.exact_ref == "refs/heads/aioa/nz11-" + capsule[:32],
            "NATIVE_ROLE_RECOVERY_CAPSULE")
    capsule_row = tx.get(RecordKind.OPERATION, canonical_sha256([CAPSULE_KIND, capsule]))
    require(capsule_row is not None, "NATIVE_ROLE_RECOVERY_CAPSULE")
    signed = capsules._decode(capsule_row)
    require(signed.digest == capsule and signed.task_id == task.task_id
            and signed.task_digest == task.digest, "NATIVE_ROLE_RECOVERY_CAPSULE")
    if expected_source is not None:
        require((signed.repository_id, signed.workspace_id, signed.source_base_sha, signed.base_tree_sha256)
                == (expected_source.repository_id, expected_source.workspace_id,
                    expected_source.source_base_sha, expected_source.base_tree_sha256),
                "NATIVE_ROLE_RECOVERY_SOURCE")
    nonce = "native-git-" + capsule[:40]
    row = tx.get(RecordKind.OPERATION, canonical_sha256((KIND, journal.ledger.scope, nonce)))
    require(row is not None, "NATIVE_ROLE_RECOVERY_WARRANT")
    candidate = EffectWarrant.from_dict(json.loads(canonical_json_bytes(row.payload["active"])))
    _, state, warrant = journal.ledger._load(tx, candidate)
    require(state["consumption"] is not None and warrant.task_id == task.task_id
            and warrant.nonce == nonce and warrant.operation_class == "GIT_COMMIT",
            "NATIVE_ROLE_RECOVERY_WARRANT")
    _, intent = journal._load(tx, warrant)
    require(intent is not None, "NATIVE_ROLE_RECOVERY_START")
    payload = intent["operation"]["payload"]
    source = payload.get("rh06_fixture")
    require(payload.get("capsule_digest") == capsule and payload.get("ref") == storage.exact_ref
            and type(source) is dict and source.get("storage_digest") == storage.digest,
            "NATIVE_ROLE_RECOVERY_START")
    step = tx.get(RecordKind.OPERATION, "github-step-" + capsule[:32] + "-local_patch")
    require(step is not None and step.payload.get("schema") == "aioa.local-patch-step.v1"
            and step.payload.get("state") == "GITHUB_STEP_UNKNOWN"
            and step.payload.get("warrant_digest") == warrant.digest()
            and step.payload.get("operation_hash") == warrant.operation_hash
            and step.payload.get("plan_digest") == payload.get("plan_digest")
            and step.payload.get("automatic_retry") is False, "NATIVE_ROLE_RECOVERY_STEP")
    return warrant
