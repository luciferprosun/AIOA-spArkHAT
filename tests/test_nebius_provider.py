from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from providers.config import NEBIUS_COMPETITION_PROFILE, ProviderManager
from providers.nebius import (
    DEFAULT_NEBIUS_BASE_URL,
    DEFAULT_NEBIUS_MODEL,
    NebiusProvider,
    normalize_nebius_base_url,
)


class NebiusProviderTests(unittest.TestCase):
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
