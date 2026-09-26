from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .openai_compatible import OpenAICompatibleProvider


DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_NEBIUS_MODEL = "nvidia/nemotron-3-super-120b-a12b"
MAX_MODELS_RESPONSE_BYTES = 1_048_576


def normalize_nebius_base_url(value: str | None) -> str:
    """Return a canonical HTTPS Token Factory API base URL.

    Only official Nebius Token Factory API hosts are accepted so a
    competition/demo typo cannot send prompts or API keys elsewhere.
    """
    raw = (value or DEFAULT_NEBIUS_BASE_URL).strip().rstrip("/")
    parsed = urlparse(raw)

    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("NEBIUS_BASE_URL must use HTTPS")
    if parsed.username or parsed.password or parsed.port is not None:
        raise ValueError("NEBIUS_BASE_URL must not contain credentials or a custom port")
    if parsed.query or parsed.fragment:
        raise ValueError("NEBIUS_BASE_URL must not contain query or fragment components")

    host = parsed.hostname.lower()
    official_host = host == "api.tokenfactory.nebius.com"
    regional_host = host.startswith("api.tokenfactory.") and host.endswith(".nebius.com")
    if not (official_host or regional_host):
        raise ValueError(
            "NEBIUS_BASE_URL must point to an official Nebius Token Factory API host"
        )

    path = parsed.path.rstrip("/")
    if path not in ("", "/v1"):
        raise ValueError("NEBIUS_BASE_URL path must be /v1")

    return f"https://{host}/v1"


class NebiusProvider(OpenAICompatibleProvider):
    """OpenAI-compatible Nebius Token Factory provider.

    The provider has no fallback of its own. ProviderManager also treats an
    explicitly selected nebius model as fail-closed.
    """
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_NEBIUS_MODEL,
        base_url: str | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise FileNotFoundError("NEBIUS_API_KEY not found")

        selected_model = model.strip()
        if not selected_model:
            raise ValueError("Nebius model name cannot be empty")

        super().__init__(
            provider="nebius",
            api_key=key,
            model=selected_model,
            base_url=normalize_nebius_base_url(
                base_url if base_url is not None else os.getenv("NEBIUS_BASE_URL")
            ),
        )

    def discover_models(self, *, timeout_seconds: float = 20.0, opener=None) -> tuple[str, ...]:
        """Return exact model IDs advertised by Token Factory.

        The response is bounded and provider error bodies are never surfaced.
        """
        if opener is None:
            opener = urllib.request.urlopen
        request = urllib.request.Request(
            f"{self.base_url}/models",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="GET",
        )
        try:
            with opener(request, timeout=timeout_seconds) as response:
                raw = response.read(MAX_MODELS_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"nebius model discovery HTTP {error.code}") from None
        except (OSError, urllib.error.URLError, TimeoutError):
            raise RuntimeError("nebius model discovery transport error") from None

        if len(raw) > MAX_MODELS_RESPONSE_BYTES:
            raise RuntimeError("nebius model discovery response too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
            data = payload["data"]
            if not isinstance(data, list):
                raise ValueError
            values = []
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError
                model_id = item.get("id")
                if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 180:
                    raise ValueError
                values.append(model_id.strip())
        except (UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise RuntimeError("invalid nebius models response") from None

        if not values:
            raise RuntimeError("nebius model catalog is empty")
        return tuple(dict.fromkeys(values))

    def discover_nemotron_models(self, *, timeout_seconds: float = 20.0, opener=None) -> tuple[str, ...]:
        return tuple(
            model
            for model in self.discover_models(
                timeout_seconds=timeout_seconds,
                opener=opener,
            )
            if model.lower().startswith("nvidia/nemotron")
        )
