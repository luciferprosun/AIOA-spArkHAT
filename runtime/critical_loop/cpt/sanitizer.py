# MIT, Copyright (c) 2026 Lukasz Zuchowski.
# Selective port from 8f9b14b7ea0f7d5a963244c62d27d3f3dcbeb26c:runtime/cpt/sanitizer.py
# Pure preview only; historical audit writer and provider boundary excluded.
from __future__ import annotations

import unicodedata

MAX_ORIGINAL_PROMPT_CHARS = 20_000
UNTRUSTED_BLOCK_START = "[BEGIN_UNTRUSTED_USER_PROMPT]"
UNTRUSTED_BLOCK_END = "[END_UNTRUSTED_USER_PROMPT]"
ESCAPED_BLOCK_START = "[USER_TEXT_CONTAINED_BEGIN_UNTRUSTED_USER_PROMPT]"
ESCAPED_BLOCK_END = "[USER_TEXT_CONTAINED_END_UNTRUSTED_USER_PROMPT]"
REMOVED_INVISIBLE_OR_DIRECTIONAL_CHARS = frozenset(
    {
        "\u200b",
        "\u200c",
        "\u200d",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2060",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)


def sanitize_original_prompt(original_prompt: str) -> str:
    if not isinstance(original_prompt, str):
        raise TypeError("original_prompt must be a string")
    if not original_prompt.strip():
        raise ValueError("original_prompt must not be empty or whitespace-only")
    if len(original_prompt) > MAX_ORIGINAL_PROMPT_CHARS:
        raise ValueError(f"original_prompt exceeds {MAX_ORIGINAL_PROMPT_CHARS} characters")

    normalized = unicodedata.normalize("NFC", original_prompt)
    cleaned = "".join(char for char in normalized if _is_allowed_character(char))
    cleaned = escape_untrusted_delimiters(cleaned)

    if not cleaned.strip():
        raise ValueError("original_prompt has no usable text after sanitization")
    return cleaned


def escape_untrusted_delimiters(text: str) -> str:
    previous = None
    escaped = text
    while previous != escaped:
        previous = escaped
        escaped = escaped.replace(UNTRUSTED_BLOCK_START, ESCAPED_BLOCK_START)
        escaped = escaped.replace(UNTRUSTED_BLOCK_END, ESCAPED_BLOCK_END)
    return escaped


def wrap_untrusted_prompt(sanitized_prompt: str) -> str:
    if not isinstance(sanitized_prompt, str) or not sanitized_prompt.strip():
        raise ValueError("sanitized_prompt must be a non-empty string")
    return f"{UNTRUSTED_BLOCK_START}\n{sanitized_prompt}\n{UNTRUSTED_BLOCK_END}"


quote_untrusted_prompt = wrap_untrusted_prompt


def _is_allowed_character(char: str) -> bool:
    if char in REMOVED_INVISIBLE_OR_DIRECTIONAL_CHARS:
        return False
    if char in "\n\r\t":
        return True
    return char >= " " and char != "\x7f"
