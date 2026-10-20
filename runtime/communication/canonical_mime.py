"""Deterministic, plain-text MIME preparation; NEVER sends or grants permission."""

from __future__ import annotations

from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import format_datetime
import hashlib

from .contracts import MailContractError, MailProposalV1, PreparedMimeV1


def prepare_mime(proposal: MailProposalV1) -> PreparedMimeV1:
    if type(proposal) is not MailProposalV1:
        raise MailContractError("MAIL_PROPOSAL_REQUIRED")
    proposal.__post_init__()
    # These features require separate Bcc privacy, attachment, HTML and
    # threading tests before enabling external delivery.
    if (proposal.cc or proposal.bcc or proposal.body_html_sha256 is not None
            or proposal.attachment_sha256 or proposal.thread_id or proposal.in_reply_to):
        raise MailContractError("MAIL_FEATURE_NOT_QUALIFIED")

    content_key = proposal.fingerprint
    correlation_id = "aioa-" + content_key[:40] + "@gateway.aioa.invalid"
    when = datetime.strptime(proposal.created_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    message = EmailMessage(policy=SMTP)
    message["From"] = proposal.sender
    message["To"] = ", ".join(proposal.to)
    message["Subject"] = proposal.subject
    message["Date"] = format_datetime(when, usegmt=True)
    message["Message-ID"] = "<" + correlation_id + ">"
    message.set_content(proposal.body_text, charset="utf-8")
    raw = message.as_bytes(policy=SMTP)
    return PreparedMimeV1(
        proposal_fingerprint=content_key,
        mime_sha256=hashlib.sha256(raw).hexdigest(),
        raw_mime=raw,
        correlation_id=correlation_id,
    )
