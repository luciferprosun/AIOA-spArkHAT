"""Future provider-neutral contracts; no production effect implementation exists."""

from __future__ import annotations

from typing import Protocol

from .contracts import MailProposalV1, PreparedMimeV1


class CoreMailEffectGate(Protocol):
    """Trusted EXISTING AIOA Core native authority, not a model boolean.

    No implementation is provided at G0/G1. Real use requires verification of
    owner session, action scope/nonce/expiry, signed warrant, STOP, source pin
    and durable one-time consumption at the original Core gate.
    """

    def validate_and_consume(self, proposal: MailProposalV1, prepared: PreparedMimeV1) -> None:
        ...


class MailProviderPort(Protocol):
    """A provider interface that must be wrapped by Core's effect gate."""

    def send_raw(self, prepared: PreparedMimeV1) -> tuple[str, str]:
        ...


class SelectedReplyReader(Protocol):
    """Future restricted-scope READ capability, unavailable in G0/G1."""

    def read_selected_thread(self, thread_id: str) -> object:
        ...
