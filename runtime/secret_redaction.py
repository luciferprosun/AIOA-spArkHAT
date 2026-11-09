# Shared stdlib-only policy, relocated without semantic changes from the existing MIT NonZero port.
# Native semantic port; MIT attribution: runtime/nonzero_cloudops/LICENSE-NONZERO.txt.
# Source: nz/redaction.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
# W7A token families: 392487849eddc7444f5159994b66b72e73f15934.
"""Provider-neutral secret detection and redaction for durable/public evidence."""

from __future__ import annotations

import json
import re
from heapq import merge
from typing import Final

REDACTION_MARKER: Final = "[REDACTED]"

_SENSITIVE_PATTERNS: Final = (
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\bAuthorization\s*:\s*[^\r\n,;]{4,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    # Provider key literals can appear beside non-ASCII text in diagnostics.
    re.compile(r"AIza[A-Za-z0-9_-]{35,}"),
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
    # Match the original text once per family; an earlier replacement must
    # never hide another family's overlapping credential or leave its tail.
    ordered = merge(*(
        (match.span() for match in pattern.finditer(value))
        for pattern in _SENSITIVE_PATTERNS
    ))
    pieces = []
    cursor = 0
    pending_start = pending_end = None
    for start, end in ordered:
        if pending_start is None:
            pending_start, pending_end = start, end
        elif start <= pending_end:
            pending_end = max(pending_end, end)
        else:
            pieces.extend((value[cursor:pending_start], REDACTION_MARKER))
            cursor = pending_end
            pending_start, pending_end = start, end
    if pending_start is None:
        return value
    pieces.extend((value[cursor:pending_start], REDACTION_MARKER, value[pending_end:]))
    return ''.join(pieces)
