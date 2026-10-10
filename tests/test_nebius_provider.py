from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.request
from unittest.mock import patch

from providers.config import NEBIUS_COMPETITION_PROFILE, ProviderManager
from providers.exact import ExactCallError, decode_response
from providers.nebius import (
    DEFAULT_NEBIUS_BASE_URL,
    DEFAULT_NEBIUS_MODEL,
    NebiusProvider,
    normalize_nebius_base_url,
    catalog_opener,
)


class NebiusProviderTests(unittest.TestCase):
    def setUp(self):
        # Offline tests must not discover credentials from the operator's home.
        loader = patch("providers.config.load_api_environment")
        loader.start()
        self.addCleanup(loader.stop)

    def test_generate_uses_bounded_exact_transport(self):
        provider = NebiusProvider("fixture-key")

        def transport(adapter, request, cancel, deadline, **kwargs):
            self.assertIs(adapter, provider)
            request.validate()
            self.assertEqual(request.requested_model, DEFAULT_NEBIUS_MODEL)
            self.assertEqual(request.provider_connection_id, "nebius")
            self.assertEqual(request.max_output_tokens, 1200)
            self.assertTrue(request.bound_reasoning_tokens)
            self.assertLessEqual(deadline - time.monotonic(), 20)
            return decode_response(json.dumps({
                "model": request.requested_model,
                "choices": [{"finish_reason": "stop", "message": {"content": "Advice"}}],
            }).encode(), request)

        with patch.dict(os.environ, {}, clear=True), patch(
                "providers.exact.generate_http_exact", side_effect=transport) as strict, patch(
                "urllib.request.urlopen", side_effect=AssertionError("legacy transport disabled")):
            self.assertEqual(provider.generate("Harmless fixture"), "Advice")
            self.assertEqual(strict.call_count, 1)

    def test_generate_rejects_identity_stop_json_and_usage_failures(self):
        provider = NebiusProvider("fixture-key")
        valid = {"model": DEFAULT_NEBIUS_MODEL,
                 "choices": [{"finish_reason": "stop", "message": {"content": "Advice"}}]}
        cases = [
            (b"invalid-json", "INVALID_PROVIDER_RESPONSE"),
            (json.dumps(dict(valid, model="nvidia/other")).encode(), "MODEL_IDENTITY_MISMATCH"),
            (json.dumps(dict(valid, choices=[{"finish_reason": "length",
                                            "message": {"content": "Advice"}}])).encode(),
             "INCOMPLETE_COMPLETION"),
            (json.dumps(dict(valid, usage={"completion_tokens": 1201})).encode(), "USAGE_LIMIT_EXCEEDED"),
        ]
        for raw, code in cases:
            with self.subTest(code=code), patch.dict(os.environ, {}, clear=True), patch(
                    "providers.exact.generate_http_exact",
                    side_effect=lambda adapter, request, *args, **kwargs: decode_response(raw, request)) as strict, patch(
                    "urllib.request.urlopen", side_effect=AssertionError("legacy transport disabled")):
                with self.assertRaisesRegex(ExactCallError, code):
                    provider.generate("Harmless fixture")
                self.assertEqual(strict.call_count, 1)

    def test_generate_timeout_and_http_errors_are_not_retried(self):
        provider = NebiusProvider("fixture-key")
        for code in ("TRANSPORT_TIMEOUT", "PROVIDER_HTTP_401"):
            with self.subTest(code=code), patch.dict(os.environ, {}, clear=True), patch(
                    "providers.exact.generate_http_exact", side_effect=ExactCallError(code)) as strict, patch(
                    "urllib.request.urlopen", side_effect=AssertionError("legacy transport disabled")):
                with self.assertRaisesRegex(ExactCallError, code):
                    provider.generate("Harmless fixture")
                self.assertEqual(strict.call_count, 1)

    def test_generate_invalid_token_limit_is_rejected_before_transport(self):
        for value in ("0", "4097", "invalid"):
            with self.subTest(value=value), patch.dict(os.environ, {
                    "OPENAI_COMPATIBLE_MAX_TOKENS": value}, clear=True), patch(
                    "providers.exact.generate_http_exact") as strict, patch(
                    "urllib.request.urlopen", side_effect=AssertionError("legacy transport disabled")):
                with self.assertRaisesRegex(ExactCallError, "INVALID_REQUEST_LIMIT"):
                    NebiusProvider("fixture-key").generate("Harmless fixture")
                strict.assert_not_called()

    def test_authenticated_catalog_never_follows_redirects_or_environment_proxies(self):
        opener = catalog_opener()
        redirects = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        request = urllib.request.Request(DEFAULT_NEBIUS_BASE_URL+'/models',
                                         headers={'Authorization': 'Bearer fixture'})
        self.assertIsNone(redirects[0].redirect_request(request, None, 302, 'redirect', {},
                                                      'https://untrusted.example/models'))
        self.assertFalse(any(isinstance(h, urllib.request.ProxyHandler) and h.proxies
                             for h in opener.handlers))

    def test_default_provider_uses_token_factory_and_nemotron_super(self) -> None:
        provider = NebiusProvider("test-key-not-a-real-secret")
        self.assertEqual(provider.provider, "nebius")
        self.assertEqual(provider.model, DEFAULT_NEBIUS_MODEL)
        self.assertEqual(provider.base_url, DEFAULT_NEBIUS_BASE_URL)
        self.assertEqual(provider.full_name, f"nebius/{DEFAULT_NEBIUS_MODEL}")

    def test_official_regional_token_factory_host_is_allowed(self) -> None:
        self.assertEqual(
            normalize_nebius_base_url(
                "https://api.tokenfactory.us-central1.nebius.com/v1/"
            ),
            "https://api.tokenfactory.us-central1.nebius.com/v1",
        )

    def test_non_nebius_endpoint_is_rejected_before_any_request(self) -> None:
        for value in (
            "http://api.tokenfactory.nebius.com/v1",
            "https://example.com/v1",
            "https://api.tokenfactory.nebius.com/not-v1",
            "https://user:pass@api.tokenfactory.nebius.com/v1",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_nebius_base_url(value)

    def test_manager_alias_selects_nebius_nemotron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"AOIA_HOME": str(Path(tmp) / "state")},
                clear=True,
            ):
                manager = ProviderManager(Path(tmp) / "project")
                expected = f"nebius/{DEFAULT_NEBIUS_MODEL}"
                self.assertEqual(manager.normalize_model_name("nebius"), expected)
                self.assertEqual(manager.normalize_model_name("nemotron"), expected)

    def test_manager_builds_nebius_provider_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AOIA_HOME": str(Path(tmp) / "state"),
                "NEBIUS_API_KEY": "test-key-not-a-real-secret",
                "NEBIUS_BASE_URL": "https://api.tokenfactory.eu-west1.nebius.com/v1",
            }
            with patch.dict(os.environ, env, clear=True):
                manager = ProviderManager(Path(tmp) / "project")
                provider = manager._build_provider(
                    f"nebius/{DEFAULT_NEBIUS_MODEL}"
                )
                self.assertIsInstance(provider, NebiusProvider)
                self.assertEqual(provider.base_url, env["NEBIUS_BASE_URL"])

    def test_explicit_nebius_selection_never_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"AOIA_HOME": str(Path(tmp) / "state")},
                clear=True,
            ):
                manager = ProviderManager(Path(tmp) / "project")
                manager.current_model = f"nebius/{DEFAULT_NEBIUS_MODEL}"
                attempted: list[str] = []

                def fail(model_name: str):
                    attempted.append(model_name)
                    raise RuntimeError("synthetic-nebius-outage")

                with patch.object(manager, "_build_provider", side_effect=fail):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "synthetic-nebius-outage",
                    ):
                        manager.generate_with_fallback("hello")

                self.assertEqual(
                    attempted,
                    [f"nebius/{DEFAULT_NEBIUS_MODEL}"],
                )

    def test_missing_key_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ,
                {"AOIA_HOME": str(Path(tmp) / "state")},
                clear=True,
            ):
                manager = ProviderManager(Path(tmp) / "project")
                with self.assertRaisesRegex(
                    FileNotFoundError,
                    "NEBIUS_API_KEY",
                ):
                    manager._build_provider(
                        f"nebius/{DEFAULT_NEBIUS_MODEL}"
                    )

    def test_model_discovery_returns_exact_token_factory_ids(self) -> None:
        provider = NebiusProvider("test-key-not-a-real-secret")

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self, _limit):
                return json.dumps(
                    {
                        "data": [
                            {"id": "nvidia/nemotron-3-nano"},
                            {"id": DEFAULT_NEBIUS_MODEL},
                            {"id": "other/vendor-model"},
                            {"id": DEFAULT_NEBIUS_MODEL},
                        ]
                    }
                ).encode()

        def opener(request, timeout):
            self.assertEqual(request.full_url, f"{provider.base_url}/models")
            self.assertEqual(timeout, 3)
            self.assertTrue(request.headers["Authorization"].startswith("Bearer "))
            return Response()

        models = provider.discover_models(timeout_seconds=3, opener=opener)
        self.assertEqual(
            models,
            (
                "nvidia/nemotron-3-nano",
                DEFAULT_NEBIUS_MODEL,
                "other/vendor-model",
            ),
        )
        self.assertEqual(
            provider.discover_nemotron_models(timeout_seconds=3, opener=opener),
            ("nvidia/nemotron-3-nano", DEFAULT_NEBIUS_MODEL),
        )

    def test_competition_profile_locks_runtime_to_nebius_nemotron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AOIA_HOME": str(Path(tmp) / "state"),
                "AIOA_COMPETITION_PROFILE": NEBIUS_COMPETITION_PROFILE,
            }
            with patch.dict(os.environ, env, clear=True):
                manager = ProviderManager(Path(tmp) / "project")
                self.assertEqual(
                    manager.current_model,
                    f"nebius/{DEFAULT_NEBIUS_MODEL}",
                )
                self.assertEqual(
                    [(item.name, item.enabled) for item in manager.provider_chain],
                    [("nebius", True)],
                )
                with self.assertRaisesRegex(ValueError, "locked to Nebius"):
                    manager.switch_model("gemini")

    def test_competition_profile_rejects_non_nemotron_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AOIA_HOME": str(Path(tmp) / "state"),
                "AIOA_COMPETITION_PROFILE": NEBIUS_COMPETITION_PROFILE,
                "NEBIUS_MODEL": "meta-llama/Llama-3.3-70B-Instruct",
            }
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, "requires an NVIDIA Nemotron"):
                    ProviderManager(Path(tmp) / "project")


if __name__ == "__main__":
    unittest.main()
