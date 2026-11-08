# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: nz/redaction.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
# W7A token families: 392487849eddc7444f5159994b66b72e73f15934.
"""Provider-neutral secret detection and redaction for durable/public evidence."""

from __future__ import annotations

import json
import re
from typing import Final

REDACTION_MARKER: Final = "[REDACTED]"

_SENSITIVE_PATTERNS: Final = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bAuthorization\s*:\s*[^\r\n,;]{4,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    # Stateless GitHub App tokens (2026) include three base64url segments.
    # Match these first so no JWT signature survives a shorter prefix match.
    re.compile(r"ghs_[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),
    # No Unicode word boundary: adjacent non-ASCII text is not a safe delimiter.
    re.compile(r"(?:gh[pousr]|github_pat)_[A-Za-z0-9_]{8,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]{4,}"
    ),
    re.compile(r"(?i)https?://[^/\s:@]{1,128}:[^/\s@]{1,256}@"),
    re.compile(
        r"(?i)(?:/|\\)(?:\.aws(?:/|\\)credentials|\.ssh(?:/|\\)id_[a-z0-9_]+|\.env)(?:\b|$)"
    ),
)


def contains_sensitive_material(value: object) -> bool:
    """Return true for common provider-neutral credential material."""

    try:
        rendered = (
            value
            if isinstance(value, str)
            else json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError):
        return True
    return any(pattern.search(rendered) is not None for pattern in _SENSITIVE_PATTERNS)


def redact_sensitive_text(value: str) -> str:
    """Replace recognized credentials without retaining matched material."""

    if not isinstance(value, str):
        raise TypeError("redaction input must be text")
    redacted = value
    for pattern in _SENSITIVE_PATTERNS:
        redacted = pattern.sub(REDACTION_MARKER, redacted)
    return redacted
