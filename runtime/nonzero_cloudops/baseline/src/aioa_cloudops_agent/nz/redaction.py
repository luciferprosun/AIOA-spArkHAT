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
    re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*[^\s,;]{4,}"),
    re.compile(r"(?i)https?://[^/\s:@]{1,128}:[^/\s@]{1,256}@"),
    re.compile(r"(?i)(?:/|\\)(?:\.aws(?:/|\\)credentials|\.ssh(?:/|\\)id_[a-z0-9_]+|\.env)(?:\b|$)"),
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
