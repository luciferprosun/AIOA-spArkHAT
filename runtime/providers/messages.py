"""Provider-neutral messages, ported from the historical desktop contract.

MIT, Copyright (c) 2026 Lukasz Zuchowski.
Source 5ec74f85256c260dadbc795143eb132b4119aab6:
apps/aoia_desktop_demo/providers/base.py (ChatMessage and ChatResult).
ChatResult is only the legacy review-parser bridge; strict calls return the
complete ProviderResult including actual reported identity and optional usage.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatResult:
    content: str
    model: str
