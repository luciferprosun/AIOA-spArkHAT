"""Independent readback of v1 and an authenticated producer completion record."""

import base64
import hashlib
from contextlib import ExitStack
from dataclasses import dataclass, replace

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mobile_gateway.wire import public_key, unbase64
from runtime.red_hat.broker_protocol import (
    _no_fault, decode_record, digest, publish_record, require, require_admission,
)
from runtime.red_hat.fixture_repository import (
    open_dir, open_repository, require_named_directory, require_private,
)
from runtime.red_hat.witness import _verify as verify_v1_bytes


def sign(identity, payload):
    raw = identity.key.sign(canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(raw).decode("ascii")


def _completion_name(request):
    return "completion-" + request.witness_binding().witness_id


def _completion_payload(request, witness_bytes, stamp):
    return {
        "schema": "aioa.redhat.fixture-witness-sync.v1",
        "request_digest": digest(request.to_wire()),
        "witness_id": request.witness_binding().witness_id,
        "witness_sha256": hashlib.sha256(witness_bytes).hexdigest(),
        "published_inode": stamp[:2],
        "published_ctime_ns": stamp[2],
        "stage": "PRODUCER_WITNESS_FILE_AND_DIRECTORY_SYNC_RETURNED",
    }


def persist_completion(directory, request, identity, witness_bytes, stamp, *, reader_gid=None):
    # The caller must invoke this only after persist_witness returns.
    payload = _completion_payload(request, witness_bytes, stamp)
    publish_record(directory, _completion_name(request), {
        "payload": payload, "signature": sign(identity, payload),
    }, reader_gid=reader_gid)


@dataclass(frozen=True, slots=True)
class Verification:
    effect_observed: bool = False
    producer_effect_sync_completed: bool = False
    witness_bytes_verified: bool = False
    witness_durable_at_readback: bool = False
    producer_witness_sync_attested: bool = False
    settlement_supported: bool = False
    witness_sha256: str | None = None
    completion_sha256: str | None = None
    published_inode: tuple | None = None
    published_ctime_ns: int | None = None


def verify(root_fd, expected, enrollment, *, now, core_epoch, broker_epoch, check_context=_no_fault, storage=None):
    """Verify a trusted original request using public enrollment and fresh observations."""
    report = Verification()
    try:
        require(enrollment.permits(expected, now), "BROKER_ENROLLMENT")
        executor = enrollment.executor
        with open_repository(root_fd, expected, executor.uid, storage=storage,
                             role=None if storage is None else "verifier") as target, ExitStack() as stack:
            check_context(target)
            stamp = target.observe(expected)
            report = replace(report, effect_observed=True)
            target.check_commit(expected)
            directory = open_dir(root_fd, "evidence", stack)
            if storage is None:
                require_private(directory, executor.uid)
            else:
                require_named_directory(root_fd, "evidence", directory)
                storage.require_evidence(directory)
            binding = expected.witness_binding()
            raw = target.record(directory, binding.witness_id, executor.uid)
            published_at = decode_record(raw)["payload"]["published_at"]
            require_admission(expected, enrollment, now=published_at,
                              core_epoch=core_epoch, broker_epoch=broker_epoch)
            require(published_at <= now, "BROKER_WITNESS_TIME")
            verify_v1_bytes(raw, binding, executor, published_inode=stamp[:2])
            report = replace(report, producer_effect_sync_completed=True,
                             witness_bytes_verified=True)
            require(target.record(directory, binding.witness_id, executor.uid, sync=True) == raw,
                    "BROKER_WITNESS_MOVED")
            report = replace(report, witness_durable_at_readback=True)

            done_bytes = target.record(directory, _completion_name(expected), executor.uid, sync=True)
            done = decode_record(done_bytes)
            payload = _completion_payload(expected, raw, stamp)
            require(type(done) is dict and set(done) == {"payload", "signature"}
                    and canonical_json_bytes(done["payload"]) == canonical_json_bytes(payload),
                    "BROKER_COMPLETION_BINDING")
            public_key(executor.spki).verify(
                unbase64(done["signature"]), canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256())
            )
            require_named_directory(root_fd, "evidence", directory)
            target.check(expected)
            target.check_commit(expected)
            require(target.observe(expected) == stamp, "BROKER_REF_MOVED")
            check_context(target)
            require(target.record(directory, binding.witness_id, executor.uid) == raw
                    and target.record(directory, _completion_name(expected), executor.uid) == done_bytes,
                    "BROKER_WITNESS_MOVED")
            return replace(
                report,
                producer_witness_sync_attested=True,
                settlement_supported=True,
                witness_sha256=hashlib.sha256(raw).hexdigest(),
                completion_sha256=hashlib.sha256(done_bytes).hexdigest(),
                published_inode=stamp[:2],
                published_ctime_ns=stamp[2],
            )
    except (InvalidSignature, OSError, ValueError, TypeError, KeyError, RecursionError):
        return report
