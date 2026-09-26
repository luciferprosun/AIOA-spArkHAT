from __future__ import annotations

import os
from urllib.parse import urlparse

from .openai_compatible import OpenAICompatibleProvider


DEFAULT_NEBIUS_BASE_URL = "https://api.tokenfactory.nebius.com/v1"
DEFAULT_NEBIUS_MODEL = "nvidia/nemotron-3-super-120b-a12b"


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
