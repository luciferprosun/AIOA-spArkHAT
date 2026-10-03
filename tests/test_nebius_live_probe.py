from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

from providers.exact import ExactCallError, ProviderResult
from providers.nebius import DEFAULT_NEBIUS_MODEL
from scripts import nebius_live_probe
from scripts.nebius_live_probe import _write_receipt, run_probe


class FakeProvider:
    def __init__(self, *, catalog, result=None, calls=None):
        self.catalog = tuple(catalog)
        self.result = result
        self.calls = calls if calls is not None else []
        self.requests = []
        self.base_url = "https://api.tokenfactory.nebius.com/v1"

    def discover_models(self, *, timeout_seconds):
        self.calls.append(("discover", timeout_seconds))
        return self.catalog

    def generate_exact(self, request, cancel, deadline):
        self.calls.append(("generate", request.requested_model))
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class DiagnosticExactError(ExactCallError):
    def __init__(self, code, metadata):
        super().__init__(code)
        self.safe_metadata = metadata


def provider_factory(fake):
    def build(*, api_key, model, base_url):
        if api_key != "test-key-not-a-real-secret":
            raise AssertionError("unexpected key")
        if model != DEFAULT_NEBIUS_MODEL:
            raise AssertionError("unexpected model")
        if base_url != "https://api.tokenfactory.nebius.com/v1":
            raise AssertionError("unexpected base")
        return fake

    return build


class NebiusLiveProbeTests(unittest.TestCase):
    def base_args(self):
        return {
            "api_key": "test-key-not-a-real-secret",
            "model": DEFAULT_NEBIUS_MODEL,
            "base_url": "https://api.tokenfactory.nebius.com/v1",
            "allow_network": True,
            "allow_cost": False,
            "catalog_only": True,
            "timeout_seconds": 3.0,
        }


    def test_missing_key_blocks_before_provider(self):
        args = self.base_args()
        args["api_key"] = ""
        result = run_probe(**args, provider_factory=lambda **_: self.fail("provider called"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "NEBIUS_API_KEY_MISSING")

    def test_network_requires_explicit_authorization(self):
        args = self.base_args()
        args["allow_network"] = False
        result = run_probe(**args, provider_factory=lambda **_: self.fail("provider called"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "LIVE_NETWORK_AUTHORIZATION_REQUIRED")

    def test_non_nemotron_model_is_rejected_before_provider(self):
        args = self.base_args()
        args["model"] = "other/vendor-model"
        result = run_probe(**args, provider_factory=lambda **_: self.fail("provider called"))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "NON_NVIDIA_NEMOTRON_MODEL_REJECTED")


    def test_catalog_only_passes_without_generation(self):
        calls = []
        fake = FakeProvider(
            catalog=("nvidia/nemotron-3-nano", DEFAULT_NEBIUS_MODEL),
            calls=calls,
        )
        result = run_probe(**self.base_args(), provider_factory=provider_factory(fake))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["scope"], "LIVE_TOKEN_FACTORY_CATALOG_ONLY")
        self.assertTrue(result["live_catalog_validated"])
        self.assertFalse(result["live_inference_validated"])
        self.assertEqual([kind for kind, _ in calls], ["discover"])

    def test_catalog_only_selects_preferred_model_from_live_catalog(self):
        preferred = "nvidia/Nemotron-3_5-Lightning"
        calls = []
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL, preferred), calls=calls)
        result = run_probe(**self.base_args(), provider_factory=lambda **_: fake)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["requested_model"], preferred)
        self.assertTrue(result["selected_model_in_catalog"])
        self.assertEqual([kind for kind, _ in calls], ["discover"])

    def test_catalog_only_uses_configured_model_if_preferred_missing(self):
        calls = []
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), calls=calls)
        result = run_probe(**self.base_args(), provider_factory=lambda **_: fake)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["requested_model"], DEFAULT_NEBIUS_MODEL)
        self.assertTrue(result["selected_model_in_catalog"])
        self.assertEqual([kind for kind, _ in calls], ["discover"])

    def test_missing_selected_model_fails_before_generation(self):
        calls = []
        fake = FakeProvider(catalog=("nvidia/nemotron-3-nano",), calls=calls)
        result = run_probe(**self.base_args(), provider_factory=provider_factory(fake))
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason"], "MODEL_NOT_IN_TOKEN_FACTORY_CATALOG")
        self.assertEqual([kind for kind, _ in calls], ["discover"])


    def test_smoke_requires_separate_cost_authorization(self):
        args = self.base_args()
        args["catalog_only"] = False
        calls = []
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), calls=calls)
        result = run_probe(**args, provider_factory=provider_factory(fake))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "LIVE_PROVIDER_COST_AUTHORIZATION_REQUIRED")
        self.assertEqual([kind for kind, _ in calls], ["discover"])

    def test_smoke_receipt_excludes_response_and_key(self):
        args = self.base_args()
        args["catalog_only"] = False
        args["allow_cost"] = True
        calls = []
        provider_result = ProviderResult(
            "private response text",
            "nebius",
            DEFAULT_NEBIUS_MODEL,
            DEFAULT_NEBIUS_MODEL,
            "EXACT_MATCH",
            "req-123",

            {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
            "stop",
            "LIVE",
            321,
        )
        fake = FakeProvider(
            catalog=(DEFAULT_NEBIUS_MODEL,),
            result=provider_result,
            calls=calls,
        )
        result = run_probe(**args, provider_factory=provider_factory(fake))
        encoded = json.dumps(result, sort_keys=True)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["scope"], "LIVE_TOKEN_FACTORY_SMOKE")
        self.assertEqual(result["request_id"], "req-123")
        self.assertEqual(result["latency_ms"], 321)
        self.assertNotIn("private response text", encoded)
        self.assertNotIn("test-key-not-a-real-secret", encoded)
        self.assertEqual([kind for kind, _ in calls], ["discover", "generate"])

    def test_smoke_defaults_to_256_output_tokens(self):
        args = self.base_args()
        args.update(catalog_only=False, allow_cost=True)
        result = ProviderResult(
            "ack", "nebius", DEFAULT_NEBIUS_MODEL, DEFAULT_NEBIUS_MODEL,
            "EXACT_MATCH", "req-default", {"total_tokens": 9}, "stop", "LIVE", 4,
        )
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), result=result)

        receipt = run_probe(**args, provider_factory=provider_factory(fake))

        self.assertEqual("PASS", receipt["status"])
        self.assertEqual(256, fake.requests[0].max_output_tokens)

    def test_output_token_limit_is_bounded_before_provider(self):
        for value in (31, 513, True):
            with self.subTest(value=value):
                args = self.base_args()
                args.update(catalog_only=False, allow_cost=True, max_output_tokens=value)
                result = run_probe(
                    **args, provider_factory=lambda **_: self.fail("provider called")
                )
                self.assertEqual("BLOCKED", result["status"])
                self.assertEqual("INVALID_OUTPUT_TOKEN_LIMIT", result["reason"])

    def test_probe_rejects_non_exact_result_identity(self):
        args = self.base_args()
        args.update(catalog_only=False, allow_cost=True)
        result = ProviderResult(
            "ack", "nebius", DEFAULT_NEBIUS_MODEL, "nvidia/other-model",
            "MISMATCH", "req-wrong",
            {"total_tokens": 9, "api_key": "must-not-persist"},
            "stop", "LIVE", 4,
        )
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), result=result)

        receipt = run_probe(**args, provider_factory=provider_factory(fake))

        self.assertEqual("FAIL", receipt["status"])
        self.assertEqual("MODEL_IDENTITY_MISMATCH", receipt["reason"])
        self.assertFalse(receipt["live_inference_validated"])
        self.assertEqual({"total_tokens": 9}, receipt["usage"])
        self.assertNotIn("must-not-persist", json.dumps(receipt, sort_keys=True))

    def test_probe_keeps_truncated_completion_failed(self):
        args = self.base_args()
        args.update(catalog_only=False, allow_cost=True)
        error = DiagnosticExactError(
            "INCOMPLETE_COMPLETION",
            {
                "finish_reason": "length",
                "request_id": "req-truncated",
                "usage": {"prompt_tokens": 11, "completion_tokens": 256,
                          "total_tokens": 267},
                "latency_ms": 212,
            },
        )
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), result=error)

        receipt = run_probe(**args, provider_factory=provider_factory(fake))

        self.assertEqual("FAIL", receipt["status"])
        self.assertEqual("INCOMPLETE_COMPLETION", receipt["reason"])
        self.assertEqual("length", receipt["finish_reason"])
        self.assertFalse(receipt["live_inference_validated"])

    def test_failure_diagnostics_are_allowlisted_and_recursive(self):
        args = self.base_args()
        args.update(catalog_only=False, allow_cost=True)
        secret = "live-secret-must-not-persist"
        error = DiagnosticExactError(
            "INCOMPLETE_COMPLETION",
            {
                "finish_reason": "length",
                "request_id": "req-safe",
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 256,
                    "total_tokens": 263,
                    "api_key": secret,
                    "nested": {"response_content": "private model text"},
                },
                "latency_ms": 88,
                "response_content": "private model text",
                "authorization": "Bearer " + secret,
            },
        )
        fake = FakeProvider(catalog=(DEFAULT_NEBIUS_MODEL,), result=error)

        receipt = run_probe(**args, provider_factory=provider_factory(fake))
        encoded = json.dumps(receipt, sort_keys=True)

        self.assertEqual(
            {"prompt_tokens": 7, "completion_tokens": 256, "total_tokens": 263},
            receipt["usage"],
        )
        self.assertEqual("req-safe", receipt["request_id"])
        self.assertEqual(88, receipt["latency_ms"])
        self.assertNotIn(secret, encoded)
        self.assertNotIn("private model text", encoded)
        self.assertNotIn("authorization", encoded.casefold())


    def test_receipt_write_is_exclusive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            _write_receipt(path, {"status": "PASS"})
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"status": "PASS"},
            )
            with self.assertRaises(FileExistsError):
                _write_receipt(path, {"status": "FAIL"})

    def test_cli_loads_configured_secret_without_printing_it(self):
        secret = "test-key-not-a-real-secret"
        output = StringIO()
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(nebius_live_probe, "load_api_environment",
                          side_effect=lambda: os.environ.__setitem__("NEBIUS_API_KEY", secret)) as load, \
             patch.object(sys, "argv", ["nebius_live_probe"]), \
             patch("sys.stdout", output):
            # No network authorization means the probe exits before transport.
            code = nebius_live_probe.main()
        self.assertEqual(code, 2)
        load.assert_called_once_with()
        self.assertNotIn(secret, output.getvalue())


if __name__ == "__main__":
    unittest.main()
