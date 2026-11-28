"""Offline checks of the external continuity record, without a Native writer."""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec

from runtime.mobile_gateway.wire import Identity
from scripts.unification import native_s2_receipt as s2


class NativeS2ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.authority = Identity(ec.generate_private_key(ec.SECP256R1()))
        self.now = int(time.time())
        self.expected = {key: hashlib.sha256(key.encode()).hexdigest() for key in s2._IMMUTABLE | s2._OBSERVED}
        self.expected.update(predecessor_generation=9, current_generation=10,
                             original_policy_epoch=1, current_policy_epoch=1)

    def seal(self, **changes):
        data = dict(self.expected, schema=s2.SCHEMA, authority="EXCLUSIVE_READBACK_PREDECESSOR_FENCED",
                    issued_at=self.now - 2, expires_at=self.now + 60)
        data.update(changes)
        return {"payload": data, "signature": self.authority.sign(data)}

    def test_receipt_requires_original_proofs_and_fresh_exclusive_successor(self):
        s2.verify_receipt(self.seal(), self.expected, authority_spki=self.authority.spki, now=self.now)
        for field in ("challenge", "volume_sha256", "start_sha256", "reservation_sha256",
                      "witness_sha256", "completion_sha256", "writer_closed_sha256", "predecessor_spki_sha256"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "BINDING"):
                s2.verify_receipt(self.seal(**{field: "0" * 64}), self.expected,
                                  authority_spki=self.authority.spki, now=self.now)
        with self.assertRaisesRegex(ValueError, "CONTINUITY"):
            rolled_back = dict(self.expected, current_generation=9)
            s2.verify_receipt(self.seal(current_generation=9), rolled_back,
                              authority_spki=self.authority.spki, now=self.now)
        with self.assertRaisesRegex(ValueError, "EXPIRED"):
            s2.verify_receipt(self.seal(expires_at=self.now), self.expected,
                              authority_spki=self.authority.spki, now=self.now)
        with self.assertRaises(InvalidSignature):
            other = Identity(ec.generate_private_key(ec.SECP256R1()))
            s2.verify_receipt(self.seal(), self.expected, authority_spki=other.spki, now=self.now)

    def test_cli_is_read_only_and_refuses_missing_receipt_or_changed_management_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest, public, receipt = (root / name for name in ("expected", "spki", "receipt"))
            manifest.write_text(json.dumps(self.expected), encoding="ascii")
            public.write_text(self.authority.spki, encoding="ascii")
            receipt.write_text(json.dumps(self.seal()), encoding="ascii")
            command = [sys.executable, "-B", "-m", "scripts.unification.native_s2_receipt",
                       "--expected", str(manifest), "--expected-sha256", hashlib.sha256(manifest.read_bytes()).hexdigest(),
                       "--receipt", str(receipt), "--authority-spki", str(public), "--authority-spki-sha256",
                       hashlib.sha256(public.read_bytes()).hexdigest()]
            result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
            data = json.loads(result.stdout)
            self.assertEqual("VERIFIED_MANAGEMENT_RECEIPT", data["continuity"])
            self.assertIs(False, data["writer_enabled"])
            self.assertIs(False, data["settlement_performed"])
            result = subprocess.run(command + ["--receipt", str(root / "absent")], capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(1, result.returncode)
            self.assertEqual("KEEP_HELD", json.loads(result.stdout)["required_core_posture"])
            manifest.write_text("{}", encoding="ascii")
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(1, result.returncode)
