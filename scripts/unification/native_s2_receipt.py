"""Read-only validator for a separate Native S2 qualification profile."""

import argparse
import json
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from runtime.red_hat.s2_receipt import (
    SCHEMA, ManagementEvidence, _IMMUTABLE, _OBSERVED, verify_receipt,
)


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
        material = ManagementEvidence.from_files(
            args.expected, args.expected_sha256, args.receipt, args.authority_spki, args.authority_spki_sha256)
        digest = material.verify(now=int(time.time()))
    except (OSError, InvalidSignature, ValueError, TypeError):
        print(json.dumps({**verdict, "continuity": "REJECTED", "required_core_posture": "KEEP_HELD"}))
        return 1
    print(json.dumps({**verdict, "continuity": "VERIFIED_MANAGEMENT_RECEIPT", "receipt_sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
