"""Hermetic mailbox and simulated effects; NEVER imports HTTP/OAuth libraries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from runtime.communication.contracts import (
    MailContractError, MailProposalV1, PreparedMimeV1, _digest, _timestamp,
)
from runtime.communication.canonical_mime import prepare_mime
from runtime.communication.outbox import MailLedgerError, OutboxLedger, OutboxReceipt


class FakeLostAcknowledgement(RuntimeError):
    pass


class FakeDeniedBeforeAcceptance(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OfflineFixtureAdmission:
    """Synthetic input with grants_effect_authority=False; CANNOT sign a real effect."""

    proposal_fingerprint: str
    mime_sha256: str
    expires_at: str
    grants_effect_authority: bool = False

    def __post_init__(self):
        # Even a synthetic fixture must not quietly become authority-shaped.
        try:
            _digest(self.proposal_fingerprint)
            _digest(self.mime_sha256)
            _timestamp(self.expires_at)
        except MailContractError:
            raise MailLedgerError("MAIL_FIXTURE_ADMISSION_DENIED") from None
        if self.grants_effect_authority is not False:
            raise MailLedgerError("MAIL_FIXTURE_ADMISSION_DENIED")


class FakeGmail:
    """A fake that can demonstrate a lost ACK after accepting exactly one request."""

    def __init__(self, behavior: str = "ok") -> None:
        if behavior not in ("ok", "accept_then_timeout", "reject_before_accept"):
            raise ValueError("UNKNOWN_FAKE_GMAIL_BEHAVIOR")
        self.behavior = behavior
        self.calls = 0
        self.accepted_digests: list[str] = []

    def send_raw(self, prepared: PreparedMimeV1) -> tuple[str, str]:
        if type(prepared) is not PreparedMimeV1:
            raise MailLedgerError("FAKE_GMAIL_INPUT_DENIED")
        prepared.__post_init__()
        self.calls += 1
        if self.behavior == "reject_before_accept":
            raise FakeDeniedBeforeAcceptance()
        self.accepted_digests.append(prepared.mime_sha256)
        if self.behavior == "accept_then_timeout":
            raise FakeLostAcknowledgement()
        return ("fixture-msg-" + prepared.mime_sha256[:20],
                "fixture-thread-" + prepared.proposal_fingerprint[:20])


def simulate_once(proposal: MailProposalV1, approval: OfflineFixtureAdmission,
                  ledger: OutboxLedger, fake: FakeGmail, *, now: datetime,
                  stop_requested: bool = False) -> OutboxReceipt:
    """A bounded offline proof. It has no live Gmail transport or Core signer."""
    if (type(proposal) is not MailProposalV1
            or type(approval) is not OfflineFixtureAdmission
            or type(ledger) is not OutboxLedger
            or type(fake) is not FakeGmail
            or type(now) is not datetime or now.tzinfo is None
            or now.utcoffset() is None):
        raise MailLedgerError("MAIL_OFFLINE_TYPES_DENIED")
    if stop_requested is not False:
        raise MailLedgerError("MAIL_OFFLINE_STOPPED")
    approval.__post_init__()
    mime = prepare_mime(proposal)
    expiry = _timestamp(approval.expires_at)
    not_before = _timestamp(proposal.created_at)
    if (approval.proposal_fingerprint != proposal.fingerprint
            or approval.mime_sha256 != mime.mime_sha256
            or expiry != datetime.strptime(
                proposal.expires_at, "%Y-%m-%dT%H:%M:%SZ"
            ).replace(tzinfo=timezone.utc)
            or not not_before <= now.astimezone(timezone.utc) < expiry):
        raise MailLedgerError("MAIL_FIXTURE_BINDING_DENIED")
    ledger.prepare(proposal, mime)
    ledger.begin_attempt(proposal.proposal_id)
    try:
        message_id, thread_id = fake.send_raw(mime)
    except (FakeLostAcknowledgement, FakeDeniedBeforeAcceptance, OSError):
        return ledger.mark_unknown(proposal.proposal_id)
    return ledger.provider_accepted(proposal.proposal_id, message_id, thread_id)
