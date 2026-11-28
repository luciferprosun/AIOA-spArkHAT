"""Pinned management evidence for the opt-in Native power-loss profile."""

import hashlib
import os
import re
import stat
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.mobile_gateway.wire import public_key, strict_json, unbase64


SCHEMA = "aioa.native.s2-exclusive-readback.v1"
MAX_RECEIPT = 8192
MAX_LIFETIME = 300
_DIGEST = re.compile(r"[a-f0-9]{64}")
_IMMUTABLE = frozenset((
    "start_sha256", "intent_sha256", "reservation_sha256", "original_policy_epoch",
    "volume_sha256", "predecessor_boot_sha256", "predecessor_generation", "predecessor_spki_sha256",
    "witness_sha256", "completion_sha256", "writer_closed_sha256",
))
_OBSERVED = frozenset((
    "current_boot_sha256", "current_generation", "current_policy_epoch", "reader_identity_sha256", "challenge",
))
_NUMBERS = frozenset(("original_policy_epoch", "current_policy_epoch", "predecessor_generation", "current_generation"))


def verify_receipt(receipt, expected, *, authority_spki, now):
    """Bind a fresh management assertion to original Core evidence and current pins."""
    if type(expected) is not dict or set(expected) != _IMMUTABLE | _OBSERVED:
        raise ValueError("S2_EXPECTED_BINDING")
    if any(type(expected[key]) is not int or not 0 < expected[key] < 2**63 for key in _NUMBERS):
        raise ValueError("S2_GENERATION_OR_EPOCH")
    if any(type(expected[key]) is not str or not _DIGEST.fullmatch(expected[key])
           for key in set(expected) - _NUMBERS):
        raise ValueError("S2_EXPECTED_DIGEST")
    if (expected["current_boot_sha256"] == expected["predecessor_boot_sha256"]
            or expected["current_generation"] <= expected["predecessor_generation"]
            or expected["current_policy_epoch"] < expected["original_policy_epoch"]):
        raise ValueError("S2_NO_SUCCESSOR_CONTINUITY")
    if type(receipt) is not dict or set(receipt) != {"payload", "signature"}:
        raise ValueError("S2_RECEIPT_ENVELOPE")
    data = receipt["payload"]
    if type(data) is not dict or set(data) != set(expected) | {"schema", "authority", "issued_at", "expires_at"}:
        raise ValueError("S2_RECEIPT_SCHEMA")
    if data["schema"] != SCHEMA or data["authority"] != "EXCLUSIVE_READBACK_PREDECESSOR_FENCED":
        raise ValueError("S2_RECEIPT_AUTHORITY")
    if canonical_json_bytes({key: data[key] for key in expected}) != canonical_json_bytes(expected):
        raise ValueError("S2_RECEIPT_BINDING")
    issued, expires = data["issued_at"], data["expires_at"]
    if (any(type(value) is not int for value in (issued, expires, now))
            or not 0 < issued <= now < expires <= issued + MAX_LIFETIME):
        raise ValueError("S2_RECEIPT_EXPIRED")
    public_key(authority_spki).verify(unbase64(receipt["signature"]), canonical_json_bytes(data),
                                      ec.ECDSA(hashes.SHA256()))
    return hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()


def _read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_RECEIPT:
            raise ValueError("S2_FILE_BOUND")
        raw = stream.read(MAX_RECEIPT + 1)
    if len(raw) != info.st_size:
        raise ValueError("S2_FILE_BOUND")
    return raw


@dataclass(frozen=True, slots=True)
class ManagementEvidence:
    """Raw, bounded files delivered by the launcher, with independent off-guest pins."""

    expected_bytes: bytes
    expected_sha256: str
    receipt_bytes: bytes
    spki_bytes: bytes
    spki_sha256: str

    @classmethod
    def from_files(cls, expected, expected_sha256, receipt, spki, spki_sha256):
        return cls(_read(expected), expected_sha256, _read(receipt), _read(spki), spki_sha256)

    def verify(self, *, now, derived=None):
        if (not all(type(raw) is bytes and 0 < len(raw) <= MAX_RECEIPT
                    for raw in (self.expected_bytes, self.receipt_bytes, self.spki_bytes))
                or hashlib.sha256(self.expected_bytes).hexdigest() != self.expected_sha256
                or hashlib.sha256(self.spki_bytes).hexdigest() != self.spki_sha256):
            raise ValueError("S2_MANAGEMENT_PIN_CHANGED")
        expected = strict_json(self.expected_bytes)
        if derived is not None and canonical_json_bytes(expected) != canonical_json_bytes(derived):
            raise ValueError("S2_JOURNAL_OR_OBSERVATION_CHANGED")
        try:
            return verify_receipt(strict_json(self.receipt_bytes), expected,
                                  authority_spki=self.spki_bytes.decode("ascii").strip(), now=now)
        except InvalidSignature as error:
            raise ValueError("S2_MANAGEMENT_SIGNATURE") from error
