"""Bounded, descriptive comparison of the existing sanitized CPL responses.

Selective MIT port from 8e09457cf97669e5f7742a59adaf091ca705ca4f:
runtime/epistemic_orchestra/human_review_workspace.py (normalize_response_text
and compare_response_candidates). See the repository LICENSE. The historical
session/provider lifecycle is excluded. No text, authority or storage is added.
"""
from __future__ import annotations

import hashlib
import re


MAX_COMPARISON_CHARS = 20_000
_HORIZONTAL_WHITESPACE = re.compile(r"[ \t\f\v]+")


def _normalize_layout(value: str) -> str:
    lines = [
        _HORIZONTAL_WHITESPACE.sub(" ", line.rstrip(" \t\f\v"))
        for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ]
    # Slice once: repeated pop(0) in the historical version was quadratic.
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end])


def compare_responses(draft: object, final: object) -> dict | None:
    """Return fingerprints/counts, or withhold malformed/oversized input.

    Callers supply responses already redacted by the canonical service. Layout
    equality also collapses spaces inside quoted code; it is never a semantic
    equivalence, correctness, consensus or approval determination. Bounds apply
    before normalization; no truncation may manufacture equality.
    """
    if any(
        not isinstance(value, str)
        or len(value) > MAX_COMPARISON_CHARS
        or not value.strip()
        for value in (draft, final)
    ):
        return None
    normalized_draft, normalized_final = _normalize_layout(draft), _normalize_layout(final)
    draft_lines = {line for line in normalized_draft.split("\n") if line}
    final_lines = {line for line in normalized_final.split("\n") if line}
    return {
        "schema": "aioa.cpl.response-comparison.v1",
        "authority": "ADVISORY_ONLY",
        "semantic_equivalence": "NOT_EVALUATED",
        "exact_equal": draft == final,
        "layout_equal": normalized_draft == normalized_final,
        "draft_sha256": hashlib.sha256(draft.encode("utf-8")).hexdigest(),
        "final_sha256": hashlib.sha256(final.encode("utf-8")).hexdigest(),
        "draft_characters": len(draft),
        "final_characters": len(final),
        "shared_normalized_lines": len(draft_lines & final_lines),
        "draft_only_normalized_lines": len(draft_lines - final_lines),
        "final_only_normalized_lines": len(final_lines - draft_lines),
    }
