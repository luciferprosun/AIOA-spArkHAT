"""Synthetic offline approvals only; RFC 8032 seeds are public test data."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
import json
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runtime.mcp_bridge import build_task, evaluate_task
from runtime.mcp_bridge.approval import (
    ApprovalToken, FIXTURE_KEY_ID, FIXTURE_PUBLIC_KEY, VERSION, verify_fixture_approval,
)
from runtime.mcp_bridge.contracts import ContractError
from runtime.mcp_bridge.policy import PolicyEffect


# RFC 8032 section 7.1 TEST 1; never a production or human key.
SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
SIGNER = Ed25519PrivateKey.from_private_bytes(SEED)
NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)


class MCPApprovalTests(unittest.TestCase):
    def setUp(self):
        self.task = build_task("patch.request_apply", {"path": "README.md"},
                               task_id="fixture-task", idempotency_key="fixture-idempotency")
        unsigned = ApprovalToken(
            version=VERSION, approval_id="12345678-1234-4234-8234-123456789abc",
            task_id=self.task.task_id, task_fingerprint=self.task.fingerprint,
            nonce="01" * 32, scope="fixture-branch", resource="README.md",
            risk_class="WRITE_LOCAL", issued_at="2026-10-10T11:00:00Z",
            expires_at="2026-10-10T13:00:00Z", key_id=FIXTURE_KEY_ID, signature="00" * 64,
        )
        self.token = self.sign(unsigned)

    def sign(self, token):
        return replace(token, signature=SIGNER.sign(token.signing_bytes()).hex())

    def verify(self, token=None, **kwargs):
        values = dict(scope="fixture-branch", resource="README.md", now=NOW)
        values.update(kwargs)
        return verify_fixture_approval(token or self.token, self.task, **values)

    def test_rfc8032_known_vector(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        signature = bytes.fromhex(
            "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
            "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
        )
        self.assertEqual(SIGNER.sign(b""), signature)
        Ed25519PublicKey.from_public_bytes(FIXTURE_PUBLIC_KEY).verify(signature, b"")

    def test_valid_roundtrip_has_no_authority(self):
        restored = ApprovalToken.from_json(self.token.to_json())
        self.assertEqual(restored, self.token)
        evidence = self.verify(restored)
        self.assertFalse(evidence.grants_effect_authority)
        self.assertEqual(evidence.provenance, "OFFLINE_PUBLIC_TEST_KEY")
        self.assertEqual(evaluate_task(self.task).effect, PolicyEffect.REQUIRE_HUMAN)

    def test_immutable_schema(self):
        with self.assertRaises(FrozenInstanceError):
            self.token.scope = "changed"
        copy = self.token.to_dict()
        copy["scope"] = "changed"
        self.assertEqual(self.token.scope, "fixture-branch")

    def test_exact_fields(self):
        for key in self.token.to_dict():
            value = self.token.to_dict()
            del value[key]
            with self.subTest(missing=key), self.assertRaises(ContractError):
                ApprovalToken.from_dict(value)
        for key in ("human_approved", "model_vote", "public_key", "approval_payload"):
            with self.subTest(extra=key), self.assertRaises(ContractError):
                ApprovalToken.from_dict(dict(self.token.to_dict(), **{key: "forged"}))

    def test_field_types(self):
        for key in self.token.to_dict():
            for bad in (None, True, 42, [], {}, "", "x" * 513):
                value = self.token.to_dict()
                value[key] = bad
                with self.subTest(field=key, value_type=type(bad)), self.assertRaises(ContractError):
                    ApprovalToken.from_dict(value)

    def test_bad_signature(self):
        with self.assertRaises(ContractError):
            self.verify(replace(self.token, signature="00" * 64))

    def test_wrong_key_id(self):
        with self.assertRaises(ContractError):
            self.verify(self.sign(replace(self.token, key_id="model-key")))

    def test_wrong_signing_key(self):
        wrong = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        token = replace(self.token, signature=wrong.sign(self.token.signing_bytes()).hex())
        with self.assertRaises(ContractError):
            self.verify(token)

    def test_validity_boundaries(self):
        self.verify(now=datetime(2026, 10, 10, 11, tzinfo=timezone.utc))
        for hour in (10, 13, 14):
            with self.subTest(hour=hour), self.assertRaises(ContractError):
                self.verify(now=datetime(2026, 10, 10, hour, tzinfo=timezone.utc))
        with self.assertRaises(ContractError):
            self.verify(now=NOW.replace(tzinfo=None))

    def test_timestamp_and_interval_validation(self):
        for issued in ("2026-10-10T11:00:00+00:00", "2026-10-10T11:00:00.000Z",
                       "2026-10-10T13:00:00Z", "2026-10-10T14:00:00Z", "2026-02-30T11:00:00Z"):
            with self.subTest(issued=issued), self.assertRaises(ContractError):
                replace(self.token, issued_at=issued)

    def test_all_signed_fields_bound(self):
        changes = dict(approval_id="22345678-1234-4234-8234-123456789abc",
                       task_id="edited", task_fingerprint="02" * 32, nonce="02" * 32,
                       scope="other-branch", resource="other.md", risk_class="READ",
                       issued_at="2026-10-10T10:00:00Z", expires_at="2026-10-10T14:00:00Z")
        for field, value in changes.items():
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.verify(replace(self.token, **{field: value}))

    def test_resigned_binding_mismatch(self):
        for field, value in dict(scope="other", resource="other", risk_class="READ",
                                task_id="other", task_fingerprint="00" * 32).items():
            with self.subTest(field=field), self.assertRaises(ContractError):
                self.verify(self.sign(replace(self.token, **{field: value})))

    def test_task_edit_after_approval(self):
        self.task.payload["path"] = "changed.md"
        with self.assertRaises(ContractError):
            self.verify()

    def test_unicode_fail_closed(self):
        composed = self.sign(replace(self.token, resource="caf\u00e9.md"))
        self.verify(composed, resource="caf\u00e9.md")
        for bad in ("cafe\u0301.md", "bad\x00", "bad\ud800"):
            with self.subTest(bad=ascii(bad)), self.assertRaises(ContractError):
                replace(self.token, resource=bad)
            with self.assertRaises(ContractError):
                self.verify(resource=bad)

    def test_wire_canonicalization(self):
        canonical = self.token.to_json()
        for bad in (b" " + canonical, json.dumps(self.token.to_dict()).encode(),
                    canonical[:-1] + b',"scope":"fixture-branch"}', b"[]", b"\xff",
                    b"x" * 8193, canonical.decode()):
            with self.subTest(kind=type(bad)), self.assertRaises(ContractError):
                ApprovalToken.from_json(bad)
        self.assertEqual(ApprovalToken.from_dict(dict(reversed(list(self.token.to_dict().items())))).signing_bytes(),
                         self.token.signing_bytes())

    def test_encoding_version_risk_uuid(self):
        for field, bad in (("version", "mcp.approval.v2"), ("risk_class", "MODEL_APPROVED"),
                           ("nonce", "01"), ("signature", "AB" * 64),
                           ("task_fingerprint", "gg" * 32), ("approval_id", "invalid"),
                           ("approval_id", "00000000-0000-0000-0000-000000000000")):
            with self.subTest(field=field), self.assertRaises(ContractError):
                replace(self.token, **{field: bad})

    def test_backend_missing_fails_closed(self):
        original = __import__
        def offline_import(name, *args, **kwargs):
            if name.startswith("cryptography"):
                raise ImportError("synthetic absent backend")
            return original(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=offline_import):
            with self.assertRaisesRegex(ContractError, "backend unavailable"):
                self.verify()

    def test_repeated_verification_never_claims_consumption(self):
        for _ in range(2):
            self.assertFalse(self.verify().grants_effect_authority)


if __name__ == "__main__":
    unittest.main()
