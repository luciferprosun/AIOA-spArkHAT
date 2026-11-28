"""Read-only validator for a separate Native S2 qualification profile."""

import argparse
import hashlib
import json
import os
import re
import stat
import time
from pathlib import Path

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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--authority-spki", required=True, type=Path, help="Base64 DER key from the management plane")
    parser.add_argument("--authority-spki-sha256", required=True, help="Digest of the management SPKI file bytes")
    args = parser.parse_args(argv)
    verdict = {"writer_enabled": False, "settlement_performed": False}
    try:
        expected, spki = _read(args.expected), _read(args.authority_spki)
        if (hashlib.sha256(expected).hexdigest() != args.expected_sha256
                or hashlib.sha256(spki).hexdigest() != args.authority_spki_sha256):
            raise ValueError("S2_MANAGEMENT_PIN_CHANGED")
        digest = verify_receipt(strict_json(_read(args.receipt)), strict_json(expected),
                                authority_spki=spki.decode("ascii").strip(), now=int(time.time()))
    except (OSError, InvalidSignature, ValueError, TypeError):
        print(json.dumps({**verdict, "continuity": "REJECTED", "required_core_posture": "KEEP_HELD"}))
        return 1
    print(json.dumps({**verdict, "continuity": "VERIFIED_MANAGEMENT_RECEIPT", "receipt_sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
