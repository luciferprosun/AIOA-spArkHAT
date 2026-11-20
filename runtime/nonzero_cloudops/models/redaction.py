# Compatibility import for the existing MIT NonZero semantic port.
# Canonical implementation: runtime.secret_redaction; no duplicate policy.
from runtime.secret_redaction import (
    _SENSITIVE_PATTERNS,
    REDACTION_MARKER,
    contains_sensitive_material,
    redact_sensitive_text,
)

__all__ = [
    "REDACTION_MARKER",
    "_SENSITIVE_PATTERNS",
    "contains_sensitive_material",
    "redact_sensitive_text",
]
