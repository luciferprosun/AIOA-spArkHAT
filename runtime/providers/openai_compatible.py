from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .base import ModelProvider


class OpenAICompatibleProvider(ModelProvider):
    """Minimal OpenAI-compatible chat completions provider.

    This keeps provider switching independent from the agent runtime without
    adding another package dependency.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str,
    ) -> None:
        super().__init__(provider=provider, model=model)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def generate(self, prompt: str) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": int(os.getenv("OPENAI_COMPATIBLE_MAX_TOKENS", "1200")),
        }
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{self.provider} HTTP {error.code}: {detail}") from error

        return payload["choices"][0]["message"]["content"].strip()

    def generate_exact(self, request, cancel, deadline, *, fixture=False):
        """One bounded request with explicit response identity, no fallback."""
        from .exact import generate_http_exact

        return generate_http_exact(self, request, cancel, deadline, fixture=fixture)
