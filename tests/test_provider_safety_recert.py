"""Gate A provider safety recertification.  Every transport is a local fake."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from runtime.mission.lite_contracts import LiteBudget, MODEL
from runtime.providers.live_gate import (
    LiveCallGate, LiveCallPermit, PermitUsageLedger, require_transport_authorization,
)
from runtime.providers.nvidia import (
    NvidiaProvider, ProviderError, ProviderRequest, TransportResult,
)
from runtime.providers.safety import (
    ProviderFailureClass, UnknownEvent, UnknownQuarantine,
    classify_provider_failure, redact_evidence,
)


GIT_SHA = "a" * 40
TREE = "b" * 64
SUITE = "c" * 64


class FixtureTransport:
    transport_scope = "TEST"

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self, payload, key, timeout, max_bytes, authorization=None):
        require_transport_authorization(
            authorization, "TEST", transport=self, payload=payload, timeout=timeout,
            max_bytes=max_bytes, provider_id="nvidia", model_id=MODEL,
        )
        self.calls += 1
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def response(*, content=None, model=MODEL, finish="stop"):
    if content is None:
        content = json.dumps({"summary": "Read-only answer.", "needs_attention": False})
    return json.dumps({
        "id": "fixture-request-id", "model": model,
        "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }).encode()


def stream_response(*, content=None, model=MODEL, finish="stop"):
    if content is None:
        content = json.dumps({"summary": "Read-only answer.", "needs_attention": False})
    events = [
        {"id": "fixture-stream-id", "model": model,
         "choices": [{"finish_reason": None,
                      "delta": {"role": "assistant", "content": ""}}]},
        {"id": "fixture-stream-id", "model": model,
         "choices": [{"finish_reason": None,
                      "delta": {"content": content[:10]}}]},
        {"id": "fixture-stream-id", "model": model,
         "choices": [{"finish_reason": None,
                      "delta": {"content": content[10:]}}]},
        {"id": "fixture-stream-id", "model": model,
         "choices": [{"finish_reason": finish, "delta": {}}]},
    ]
    return ("".join(f"data: {json.dumps(event)}\n\n" for event in events)
            + "data: [DONE]\n\n").encode()


class ProviderSafetyRecertificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def provider(self, result, *, quarantine=None, allow_bounded_reformat=False):
        self.counter += 1
        transport = FixtureTransport(result)
        permit = LiveCallPermit(
            f"permit-{self.counter}", "RECERT", GIT_SHA, TREE, SUITE, "PASS",
            100, 200, 1, "nvidia", MODEL, "TEST",
        )
        gate = LiveCallGate(
            permit, source_reader=lambda: (GIT_SHA, TREE, SUITE),
            usage_ledger=PermitUsageLedger((self.root / f"gate-{self.counter}.sqlite3").resolve()),
            clock=lambda: 150,
        )
        provider = NvidiaProvider(
            LiteBudget(), secret_supplier=lambda: "fixture-key-not-real",
            transport=transport, clock=lambda: 150, live_gate=gate,
            quarantine=quarantine, source_commit_supplier=lambda: GIT_SHA,
            allow_bounded_reformat=allow_bounded_reformat,
        )
        return provider, transport

    @staticmethod
    def request(**changes):
        values = dict(
            request_id="request-recert", trace_id="operation-recert",
            provider_id="nvidia", model_id=MODEL,
            input_text='{"fixture":true}', budget_reservation_id="reservation-recert",
            max_output_tokens=256, request_timeout=30,
        )
        values.update(changes)
        return ProviderRequest(**values)

    def assert_class(self, result, expected, *, code=None):
        provider, transport = self.provider(result)
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request())
        self.assertEqual(expected, caught.exception.failure_class)
        if code is not None:
            self.assertEqual(code, caught.exception.code)
        self.assertEqual(1, transport.calls)
        return caught.exception

    def test_a01_valid_response_requires_strict_schema_then_accepts(self):
        provider, transport = self.provider(TransportResult(200, response(), {
            "content-type": "application/json", "x-request-id": "safe-id",
        }))
        result = provider.request(self.request())
        self.assertEqual("VALID", result.validation_result)
        self.assertEqual("safe-id", result.provider_request_id)
        self.assertEqual(1, transport.calls)

    def test_a01b_valid_stream_is_reconstructed_then_strictly_validated(self):
        provider, transport = self.provider(TransportResult(200, stream_response(), {
            "content-type": "text/event-stream; charset=utf-8",
            "x-request-id": "safe-stream-id",
        }))
        result = provider.request(self.request())
        self.assertEqual("VALID", result.validation_result)
        self.assertEqual("safe-stream-id", result.provider_request_id)
        self.assertEqual(1, transport.calls)

    def test_a01c_stream_requires_done_and_rejects_tool_calls(self):
        incomplete = stream_response().replace(b"data: [DONE]\n\n", b"")
        self.assert_class(TransportResult(200, incomplete, {
            "content-type": "text/event-stream",
        }), ProviderFailureClass.MALFORMED_JSON)
        tool = (
            'data: {"id":"fixture-stream-id","model":"' + MODEL
            + '","choices":[{"finish_reason":"stop","delta":{"tool_calls":[{}]}}]}\n\n'
            + 'data: [DONE]\n\n'
        ).encode()
        self.assert_class(TransportResult(200, tool, {
            "content-type": "text/event-stream",
        }), ProviderFailureClass.MALFORMED_JSON)

    def test_a02_auth_failures_are_classified_and_fail_closed(self):
        for status in (401, 403):
            with self.subTest(status=status):
                self.assert_class(TransportResult(status, b"", {}),
                                  ProviderFailureClass.AUTH_FAILURE)

    def test_a03_quota_has_one_outcome_and_bounded_retry_after_metadata(self):
        error = self.assert_class(TransportResult(429, b"", {"retry-after": "45"}),
                                  ProviderFailureClass.QUOTA_OR_RATE_LIMIT)
        self.assertEqual(45, error.retry_after_seconds)

    def test_a04_upstream_5xx_is_specific_and_never_passes(self):
        for status in (500, 502, 503):
            with self.subTest(status=status):
                self.assert_class(TransportResult(status, b"", {}),
                                  ProviderFailureClass.UPSTREAM_5XX)

    def test_a05_timeout_and_connection_failure_are_specific(self):
        for failure in (TimeoutError(), OSError()):
            with self.subTest(kind=type(failure).__name__):
                self.assert_class(failure, ProviderFailureClass.NETWORK_TIMEOUT)

    def test_a06_empty_response_is_rejected(self):
        self.assert_class(TransportResult(200, b"", {}),
                          ProviderFailureClass.EMPTY_RESPONSE)

    def test_a07_one_bounded_reformat_can_recover_then_schema_is_checked(self):
        fenced = "```json\n" + json.dumps({
            "summary": "Read-only answer.", "needs_attention": False,
        }) + "\n```"
        provider, _ = self.provider(
            TransportResult(200, response(content=fenced), {}),
            allow_bounded_reformat=True,
        )
        self.assertEqual("VALID", provider.request(self.request()).validation_result)

    def test_a08_failed_malformed_json_is_classified_and_quarantined(self):
        quarantine = UnknownQuarantine((self.root / "quarantine").resolve(), clock=lambda: 150)
        provider, _ = self.provider(TransportResult(200, response(content="{broken"), {}),
                                    quarantine=quarantine)
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request())
        self.assertEqual(ProviderFailureClass.MALFORMED_JSON, caught.exception.failure_class)
        self.assertIsNotNone(caught.exception.unknown_id)
        self.assertEqual((caught.exception.unknown_id,), quarantine.unresolved_ids())

    def test_a09_valid_json_wrong_schema_or_types_is_rejected(self):
        for content in ('{"summary":7,"needs_attention":false}',
                        '{"summary":"x","needs_attention":false,"authority":true}'):
            with self.subTest(content=content):
                self.assert_class(TransportResult(200, response(content=content), {}),
                                  ProviderFailureClass.SCHEMA_INVALID)

    def test_a10_truncation_is_specific(self):
        error = self.assert_class(TransportResult(200, response(finish="length"), {}),
                                  ProviderFailureClass.TRUNCATED_RESPONSE)
        self.assertEqual("length", error.safe_metadata.finish_reason)

    def test_a11_model_capability_mismatch_is_specific(self):
        self.assert_class(TransportResult(200, response(model="different/model"), {}),
                          ProviderFailureClass.MODEL_OR_CAPABILITY_MISMATCH)

    def test_a12_unclassifiable_error_is_unknown_and_quarantined(self):
        quarantine = UnknownQuarantine((self.root / "unknown").resolve(), clock=lambda: 150)
        provider, _ = self.provider(ProviderError("UNCLASSIFIABLE_FIXTURE", outcome_unknown=True),
                                    quarantine=quarantine)
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request())
        self.assertEqual(ProviderFailureClass.UNKNOWN, caught.exception.failure_class)
        self.assertEqual(1, len(quarantine.unresolved_ids()))

    def test_a13_manual_replay_requires_confirmation_and_creates_new_attempt(self):
        quarantine = UnknownQuarantine((self.root / "manual").resolve(), clock=lambda: 150)
        event = UnknownEvent(
            "operation-one", "nvidia", MODEL, "d" * 64, None, {}, "fixture", 1,
            "Unclassifiable synthetic outcome.", GIT_SHA, {"authorization": "Bearer secret"},
        )
        unknown_id = quarantine.record(event)
        with self.assertRaisesRegex(ValueError, "MANUAL_CONFIRMATION_REQUIRED"):
            quarantine.request_manual_replay(unknown_id, "operation-two", confirmed=False)
        attempt = quarantine.request_manual_replay(
            unknown_id, "operation-two", confirmed=True)
        self.assertTrue(attempt.startswith("replay-attempt-"))
        original = json.loads(quarantine.manifest.read_text().splitlines()[0])
        replay = json.loads(quarantine.replays.read_text().splitlines()[0])
        self.assertEqual("QUARANTINED_MANUAL_ONLY", original["replay_status"])
        self.assertEqual("REQUESTED_NOT_DISPATCHED", replay["status"])
        self.assertFalse(replay["authority_granted"])

    def test_a14_redaction_and_owner_only_permissions(self):
        value = redact_evidence({
            "Authorization": "Bearer abc123", "nested": {"api_key": "very-secret"},
            "message": "failed with Bearer token-value",
        })
        encoded = json.dumps(value)
        self.assertNotIn("abc123", encoded)
        self.assertNotIn("very-secret", encoded)
        self.assertNotIn("token-value", encoded)
        quarantine = UnknownQuarantine((self.root / "permissions").resolve())
        self.assertEqual(0o700, quarantine.root.stat().st_mode & 0o777)

    def test_a15_approval_is_bound_to_exact_payload_and_single_use(self):
        provider, transport = self.provider(TransportResult(200, response(), {}))
        request = self.request()
        payload = provider._payload(request)
        authorization = provider._live_gate.authorize(
            "nvidia", MODEL, "TEST", transport=transport, payload=payload,
            timeout=30, max_bytes=provider.budget.max_response_bytes,
        )
        with self.assertRaisesRegex(Exception, "LIVE_CALL_BLOCKED"):
            transport(payload + b" ", "fixture-key-not-real", 30,
                      provider.budget.max_response_bytes, authorization)
        self.assertEqual(0, transport.calls)

    def test_a16_no_fallback_or_permission_broadening_for_changed_model(self):
        provider, transport = self.provider(TransportResult(200, response(), {}))
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request(model_id="alternate/provider-model"))
        self.assertEqual(ProviderFailureClass.MODEL_OR_CAPABILITY_MISMATCH,
                         caught.exception.failure_class)
        self.assertEqual(0, transport.calls)

    def test_a17_preflight_rejection_is_not_a_provider_unknown(self):
        quarantine = UnknownQuarantine((self.root / "preflight").resolve())
        provider, transport = self.provider(TransportResult(200, response(), {}),
                                            quarantine=quarantine)
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request(input_text="x" * 20000))
        self.assertEqual("INPUT_TOO_LARGE", caught.exception.code)
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual((), quarantine.unresolved_ids())
        self.assertEqual(0, transport.calls)

    def test_taxonomy_is_complete_and_unknown_is_not_a_success_state(self):
        expected = {item.value for item in ProviderFailureClass}
        self.assertEqual(11, len(expected))
        self.assertEqual(ProviderFailureClass.UNKNOWN,
                         classify_provider_failure("NEW_UNSUPPORTED_CONDITION"))
        self.assertNotIn("PASS", expected)


class NachweisgesetzTemporalBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parent / "fixtures" / "nachwg_temporal_benchmark_20260919.json"
        cls.fixture = json.loads(path.read_text())

    def test_l1_2020_historical_anchors_and_primary_version_sources(self):
        case = self.fixture["cases"]["L1_2020"]
        self.assertEqual(6, len(case["anchors"]))
        self.assertIn("bgbl-1995", case["source_ids"])
        self.assertIn("bgbl-2001", case["source_ids"])

    def test_l2_2026_textform_is_distinguished_from_elektronische_form(self):
        anchors = " ".join(self.fixture["cases"]["L2_2026"]["anchors"])
        self.assertIn("§ 126b", anchors)
        self.assertIn("§ 126a", anchors)
        self.assertIn("not electronic form", anchors)

    def test_l3_current_change_detection_is_as_of_dated_and_anti_hallucination(self):
        self.assertEqual("2026-09-19", self.fixture["as_of_date"])
        status = self.fixture["current_consolidated_status"]
        self.assertFalse(status["later_nachwg_amendment_found_through_as_of_date"])
        self.assertIn("2024", status["last_amendment"])
        self.assertEqual("2025-01-01", status["effective_for_sections_2_and_3"])

    def test_all_sources_are_dated_https_and_government_or_primary(self):
        for source in self.fixture["sources"]:
            self.assertEqual("2026-09-19", source["accessed"])
            self.assertTrue(source["url"].startswith("https://"))
            self.assertIn(source["authority"], {"OFFICIAL_PRIMARY", "OFFICIAL_GOVERNMENT"})
            self.assertTrue(any(domain in source["url"] for domain in (
                "gesetze-im-internet.de", "bgbl.de", "bmas.de")))


if __name__ == "__main__":
    unittest.main()
