from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from io import StringIO

from providers.exact import ProviderResult
from providers.nebius import DEFAULT_NEBIUS_MODEL
from scripts import nebius_live_probe
from scripts.nebius_live_probe import _write_receipt, run_probe


class FakeProvider:
    def __init__(self, *, catalog, result=None, calls=None):
        self.catalog = tuple(catalog)
        self.result = result
        self.calls = calls if calls is not None else []
        self.base_url = "https://api.tokenfactory.nebius.com/v1"

    def discover_models(self, *, timeout_seconds):
        self.calls.append(("discover", timeout_seconds))
        return self.catalog

    def generate_exact(self, request, cancel, deadline):
        self.calls.append(("generate", request.requested_model))
        return self.result


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
