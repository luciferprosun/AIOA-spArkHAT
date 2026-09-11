"""CPL privacy helpers, selectively adapted from the MIT desktop source.

Copyright (c) 2026 Lukasz Zuchowski.
Source 5ec74f85256c260dadbc795143eb132b4119aab6:apps/aoia_desktop_demo/security/secret_redaction.py
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "api-key",
    "apikey",
    "bearer",
    "credential",
    "secret",
    "token",
)

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bor-[A-Za-z0-9_-]{16,}"),  # OpenRouter-style key prefix
    re.compile(r"(?i)\b(?:authorization|api[_ -]?key|token|secret)\s*[:=]\s*[^\s,;\"']+"),
)


def redact_secret_text(text: object, *, known_secrets: Sequence[str] = ()) -> str:
    """Return ``text`` with any known secret values and common key-shaped
    substrings replaced with a fixed placeholder. Never raises."""
    try:
        value = str(text)
    except Exception:  # pragma: no cover - defensive
        return REDACTED
    for secret in known_secrets:
        if isinstance(secret, str) and secret:
            value = value.replace(secret, REDACTED)
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub(REDACTED, value)
    return value


def redact_secret_data(value: object, *, known_secrets: Sequence[str] = ()) -> Any:
    """Recursively redact secret-shaped values inside dicts/lists/strings."""
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).casefold()
            if (key_text in _SENSITIVE_KEY_PARTS or key_text in {"nonce", "csrf_token", "access_token", "password"}
                    or key_text.endswith(("_api_key", "_secret", "_credential"))):
                redacted[str(key)] = REDACTED
            else:
                redacted[str(key)] = redact_secret_data(item, known_secrets=known_secrets)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_secret_data(item, known_secrets=known_secrets) for item in value]
    if isinstance(value, str):
        return redact_secret_text(value, known_secrets=known_secrets)
    return value


def redact_exception(exc: BaseException, *, known_secrets: Sequence[str] = ()) -> str:
    """Return a redacted, user-safe string for an exception."""
    return redact_secret_text(str(exc), known_secrets=known_secrets)

