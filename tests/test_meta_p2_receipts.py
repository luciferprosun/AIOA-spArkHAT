"""META-P2-02 strictly hermetic synthetic receipt/budget regression tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import socket
import unittest
import urllib.request
from unittest import mock

from runtime.meta_hackathon.contracts import BrowserTaskV1, MetaContractError
from runtime.meta_hackathon.offline_receipts import (
    BudgetReservation,
    MOCK_RESPONSE_SCHEMA,
    OFFLINE_ENVIRONMENT,
    OfflineReceiptLedger,
    ProviderReceipt,
)
from runtime.meta_hackathon.provider_offline import (
    OFFLINE_MODEL,
    build_offline_envelope,
)

OWNER = "a" * 64
SHA = "b" * 40
DATE = "2026-10-27T20:05:00Z"
ISSUED = "2026-10-27T20:00:00Z"
EXPIRY = "2026-10-27T20:10:00Z"
ORIGIN = "https://example.org"


def task():
    return BrowserTaskV1(
        task_id="t1",
        owner_scope_digest=OWNER,
        source_sha=SHA,
        allowed_origins=(ORIGIN,),
        target_url=f"{ORIGIN}/docs",
        deadline_utc="2030-01-01T00:00:00Z",
        max_pages=1,
        timeout_ms=8000,
        max_chars=3000,
    )


def reservation(*, attempt_id="try-1", nonce="c" * 64, max_usd="0.50"):
    return BudgetReservation(
        task_digest=task().digest,
        owner_scope_digest=OWNER,
        source_sha=SHA,
        model=OFFLINE_MODEL,
        attempt_id=attempt_id,
        nonce=nonce,
        issued_at_utc=ISSUED,
        expires_at_utc=EXPIRY,
        max_output_tokens=64,
        max_usd=max_usd,
    )


def envelope(*, budget=0.5, max_tokens=64):
    return build_offline_envelope(task(), "fixture-only", max_output_tokens=max_tokens,
                                  budget_usd_limit=budget)


def fixture(r=None, *, status="MOCK_DONE", tokens=8, **changes):
    r = r or reservation()
    value = {
        "schema": MOCK_RESPONSE_SCHEMA,
        "model": r.model,
        "task_digest": r.task_digest,
        "owner_scope_digest": r.owner_scope_digest,
        "source_sha": r.source_sha,
        "attempt_id": r.attempt_id,
        "nonce_sha256": r.nonce_sha256,
        "completion_tokens": tokens,
        "status": status,
    }
    value.update(changes)
    return json.dumps(value, sort_keys=True)


def record(r=None, *, mock_cost_usd="0.10", status="MOCK_DONE", stopped=False,
           ledger=None, tokens=8, now_utc=DATE, response_json=None, env=None):
    r = r or reservation()
    return (ledger or OfflineReceiptLedger()).record_once(
        r,
        env or envelope(),
        mock_response_json=fixture(r, status=status, tokens=tokens)
        if response_json is None else response_json,
        mock_cost_usd=mock_cost_usd,
        now_utc=now_utc,
        stopped=stopped,
    )


class OfflineReceiptsTests(unittest.TestCase):
    def test_success_redacted_immutable_mock_only(self):
        r = reservation()
        receipt = record(r)
        self.assertIsInstance(receipt, ProviderReceipt)
        self.assertEqual(receipt.status, "MOCK_DONE")
        self.assertEqual(receipt.environment, OFFLINE_ENVIRONMENT)
        self.assertFalse(receipt.dispatch_allowed)
        self.assertFalse(receipt.verified)
        self.assertFalse(r.dispatch_allowed)
        self.assertFalse(OfflineReceiptLedger().dispatch_allowed)
        self.assertEqual(len(receipt.digest), 64)
        self.assertEqual(receipt.reservation_sha256, r.digest)
        self.assertNotIn(r.nonce, receipt.to_public_json())
        self.assertNotIn("fixture-only", receipt.to_public_json())
        self.assertEqual(receipt.to_public_dict()["status"], "MOCK_DONE")
        with self.assertRaises(AttributeError):
            receipt.status = "VERIFIED"

    def test_failed_unknown_stop_have_no_live_claim_or_retry(self):
        for status in ("MOCK_FAILED", "MOCK_UNKNOWN", "MOCK_STOPPED"):
            ledger = OfflineReceiptLedger()
            out = record(status=status, stopped=(status == "MOCK_STOPPED"),
                         tokens=0, ledger=ledger)
            self.assertEqual(out.status, status)
            self.assertFalse(out.verified)
            with self.assertRaisesRegex(MetaContractError, "META_MOCK_REPLAY_DENIED"):
                record(status=status, stopped=(status == "MOCK_STOPPED"),
                       tokens=0, ledger=ledger)

    def test_replay_attempt_or_nonce_reuse(self):
        ledger = OfflineReceiptLedger()
        record(ledger=ledger)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_REPLAY_DENIED"):
            record(ledger=ledger)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_REPLAY_DENIED"):
            record(reservation(attempt_id="try-1", nonce="d"*64), ledger=ledger)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_REPLAY_DENIED"):
            record(reservation(attempt_id="try-2", nonce="c"*64), ledger=ledger)

    def test_model_task_owner_sha_attempt_nonce_forgery_rejected(self):
        for changes in (
            {"model": "different-model"},
            {"task_digest": "0"*64},
            {"owner_scope_digest": "0"*64},
            {"source_sha": "0"*40},
            {"attempt_id": "different"},
            {"nonce_sha256": "0"*64},
        ):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(MetaContractError,
                                            "META_MOCK_BINDING_DENIED"):
                    record(response_json=fixture(**changes))

    def test_bad_reservation_bindings(self):
        r = reservation()
        for changed in (
            replace(r, task_digest="0"*64),
            replace(r, owner_scope_digest="0"*64),
            replace(r, source_sha="0"*40),
            replace(r, max_output_tokens=256),
            replace(r, max_usd="0.75"),
        ):
            with self.subTest(changed=changed.attempt_id):
                with self.assertRaisesRegex(MetaContractError,
                                            "META_MOCK_BINDING_DENIED"):
                    record(changed)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_BINDING_DENIED"):
            record(r, env=envelope(budget=0.0))

    def test_expiry_issued_future_and_max_lifetime(self):
        r = reservation()
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_TIME_DENIED"):
            record(r, now_utc="2026-10-27T19:59:59Z")
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_TIME_DENIED"):
            record(r, now_utc=EXPIRY)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_TIME_DENIED"):
            replace(r, expires_at_utc="2026-10-27T20:16:00Z")

    def test_mock_cap_and_total_ledger_cost(self):
        ledger = OfflineReceiptLedger(max_total_usd="0.50")
        first = record(ledger=ledger, mock_cost_usd="0.40")
        self.assertEqual(first.mock_cost_usd, "0.40")
        self.assertEqual(ledger.mock_spent_usd, "0.40")
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_BUDGET_DENIED"):
            record(reservation(attempt_id="two", nonce="d"*64), ledger=ledger,
                   mock_cost_usd="0.20")
        self.assertEqual(ledger.mock_spent_usd, "0.40")
        record(reservation(attempt_id="two", nonce="d"*64), ledger=ledger,
               mock_cost_usd="0.10")
        self.assertEqual(ledger.mock_spent_usd, "0.50")
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_BUDGET_DENIED"):
            record(mock_cost_usd="0.51")

    def test_fractional_preflight_budget_never_rounds_up(self):
        # A descriptive 0.499 USD ceiling must NOT admit a 0.50 USD reservation.
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_BINDING_DENIED"):
            record(env=envelope(budget=0.499))

    def test_malformed_nan_inf_duplicate_keys_and_secret_like_fields(self):
        bad_fixtures = [
            "{not JSON",
            fixture().replace('"completion_tokens": 8',
                              '"completion_tokens": NaN'),
            fixture().replace('"completion_tokens": 8',
                              '"completion_tokens": Infinity'),
            fixture().replace('"completion_tokens": 8',
                              '"completion_tokens": true'),
            fixture(completion_tokens=-1),
            fixture(completion_tokens=65),
            fixture(status="VERIFIED"),
            fixture(authorization="Bearer FAKE_NOT_A_REAL_SECRET"),
            fixture()[:-1] + ', "model": "muse-spark-1.3"}',
            fixture() + "X",
            "x" * 4097,
        ]
        for raw in bad_fixtures:
            with self.subTest(raw_start=raw[:12]):
                with self.assertRaises(MetaContractError) as caught:
                    record(response_json=raw)
                self.assertNotIn("FAKE_NOT_A_REAL_SECRET", str(caught.exception))
                self.assertNotIn("Bearer", str(caught.exception))
                self.assertNotIn(raw[:12] if raw[:12] == "x"*12 else "<not>",
                                 str(caught.exception))

    def test_invalid_dollars_and_tokens(self):
        for bad in ("1.01", "0.5", "0.0001", "-0.01", "NaN", "Infinity", "", 0.5, True):
            with self.subTest(value=str(bad)):
                with self.assertRaises(MetaContractError):
                    reservation(max_usd=bad)
                with self.assertRaises(MetaContractError):
                    record(mock_cost_usd=bad)
                with self.assertRaises(MetaContractError):
                    OfflineReceiptLedger(max_total_usd=bad)
        for bad in (0, 513, True, 12.2):
            with self.assertRaises(MetaContractError):
                replace(reservation(), max_output_tokens=bad)

    def test_stop_status_binding(self):
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_STOP_DENIED"):
            record(stopped=True, status="MOCK_DONE")
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_STOP_DENIED"):
            record(status="MOCK_STOPPED", tokens=0, stopped=False)
        with self.assertRaisesRegex(MetaContractError, "META_MOCK_RESPONSE_DENIED"):
            record(status="MOCK_UNKNOWN", tokens=5)

    def test_hermetic_no_network_dispatch_or_fallback(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("NO NET")), \
             mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("NO HTTP")):
            ledger = OfflineReceiptLedger()
            got = record(ledger=ledger)
            self.assertEqual(got.status, "MOCK_DONE")
            self.assertEqual(ledger.mock_spent_usd, "0.10")
            self.assertFalse(got.dispatch_allowed)

    def test_concurrent_same_nonce_at_most_once(self):
        shared = OfflineReceiptLedger(max_total_usd="0.50")
        def act(_):
            try:
                return record(ledger=shared).status
            except MetaContractError as e:
                return str(e)
        with ThreadPoolExecutor(max_workers=3) as pool:
            answers = list(pool.map(act, range(3)))
        self.assertEqual(answers.count("MOCK_DONE"), 1)
        self.assertEqual(answers.count("META_MOCK_REPLAY_DENIED"), 2)
        self.assertEqual(shared.mock_spent_usd, "0.10")

    def test_no_real_key_or_raw_content_in_public_receipt(self):
        payload = record().to_public_json()
        for marker in ("api_key", "Authorization", "Cookie", "raw",
                       "prompt", "response", "password", "secret"):
            self.assertNotIn(marker, payload)
        self.assertIn("OFFLINE_MOCK_ONLY", payload)
        self.assertEqual(json.loads(payload)["model"], OFFLINE_MODEL)


if __name__ == "__main__":
    unittest.main()
