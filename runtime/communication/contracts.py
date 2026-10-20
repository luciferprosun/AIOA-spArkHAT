"""Strict, immutable Gmail-independent mail proposals. No effect authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import unicodedata


SCHEMA = "aioa.mail.proposal.v1"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_LOCAL = re.compile(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]{1,64}\Z")
_DOMAIN_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_BIDI_CONTROL = set(chr(i) for i in (*range(0x202A, 0x202F), *range(0x2066, 0x206A)))


class MailContractError(ValueError):
    """Fail-closed, transport-safe error (never echoes personal content)."""

    def __init__(self, reason: str = "MAIL_CONTRACT_DENIED") -> None:
        self.reason = reason
        super().__init__(reason)


def _ensure(condition: bool, reason: str = "MAIL_CONTRACT_DENIED") -> None:
    if not condition:
        raise MailContractError(reason)


def _identifier(value: object) -> str:
    _ensure(type(value) is str and _IDENTIFIER.fullmatch(value) is not None)
    return value


def _bounded_text(value: object, *, max_bytes: int, multiline: bool = False) -> str:
    _ensure(type(value) is str and value and len(value.encode("utf-8")) <= max_bytes)
    _ensure(unicodedata.normalize("NFC", value) == value)
    _ensure(not any(c in _BIDI_CONTROL or ord(c) == 127 for c in value))
    if multiline:
        _ensure("\r" not in value and "\x00" not in value)
        _ensure(all(ord(c) >= 32 or c in "\n\t" for c in value))
    else:
        _ensure(value.strip() == value and all(ord(c) >= 32 for c in value))
    return value


def _email(value: object) -> str:
    _ensure(type(value) is str and 3 <= len(value) <= 254 and value.isascii(), "MAIL_ADDRESS_DENIED")
    _ensure(value.count("@") == 1, "MAIL_ADDRESS_DENIED")
    local, domain = value.split("@")
    _ensure(_LOCAL.fullmatch(local) is not None and not local.startswith(".")
            and not local.endswith(".") and ".." not in local, "MAIL_ADDRESS_DENIED")
    labels = domain.split(".")
    _ensure(len(labels) >= 2 and all(_DOMAIN_LABEL.fullmatch(label) for label in labels),
            "MAIL_ADDRESS_DENIED")
    return local + "@" + domain.lower()


def _timestamp(value: object) -> datetime:
    _ensure(type(value) is str and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) is not None,
            "MAIL_TIME_DENIED")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise MailContractError("MAIL_TIME_DENIED") from exc
    _ensure(parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value, "MAIL_TIME_DENIED")
    return parsed


def _digest(value: object) -> str:
    _ensure(type(value) is str and _HEX64.fullmatch(value) is not None, "MAIL_DIGEST_DENIED")
    return value


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


@dataclass(frozen=True, slots=True, repr=False)
class MailProposalV1:
    """Advisory proposal. Neither the owner_scope_ref nor any field grants approval.

    CC/BCC/HTML/attachments/replies are recorded for exact binding, but the
    initial MIME builder deliberately REJECTS these until separate review.
    """

    task_id: str
    proposal_id: str
    owner_scope_ref: str
    sender: str
    to: tuple[str, ...]
    subject: str
    body_text: str = field(repr=False)
    nonce: str = ""
    created_at: str = ""
    expires_at: str = ""
    cc: tuple[str, ...] = ()
    bcc: tuple[str, ...] = ()
    body_html_sha256: str | None = None
    attachment_sha256: tuple[str, ...] = ()
    thread_id: str | None = None
    in_reply_to: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.task_id)
        _identifier(self.proposal_id)
        _identifier(self.owner_scope_ref)
        object.__setattr__(self, "sender", _email(self.sender))
        _ensure(type(self.to) is tuple and 1 <= len(self.to) <= 8, "MAIL_RECIPIENTS_DENIED")
        addresses = []
        for name in ("to", "cc", "bcc"):
            group = getattr(self, name)
            _ensure(type(group) is tuple and len(group) <= 8, "MAIL_RECIPIENTS_DENIED")
            normalized = tuple(_email(item) for item in group)
            object.__setattr__(self, name, normalized)
            addresses.extend(address.lower() for address in normalized)
        _ensure(len(addresses) <= 8 and len(set(addresses)) == len(addresses),
                "MAIL_RECIPIENTS_DENIED")
        _bounded_text(self.subject, max_bytes=512)
        _bounded_text(self.body_text, max_bytes=32768, multiline=True)
        _digest(self.nonce)
        created, expiry = _timestamp(self.created_at), _timestamp(self.expires_at)
        _ensure(0 < (expiry - created).total_seconds() <= 3600, "MAIL_TIME_DENIED")
        if self.body_html_sha256 is not None:
            _digest(self.body_html_sha256)
        _ensure(type(self.attachment_sha256) is tuple
                and len(self.attachment_sha256) <= 8, "MAIL_ATTACHMENTS_DENIED")
        for item in self.attachment_sha256:
            _digest(item)
        if self.thread_id is not None:
            _identifier(self.thread_id)
        if self.in_reply_to is not None:
            _bounded_text(self.in_reply_to, max_bytes=320)

    @property
    def fingerprint(self) -> str:
        """Immutable canonical identity; NOT a signature or human authorization."""
        record = {
            "domain": SCHEMA,
            "task_id": self.task_id,
            "proposal_id": self.proposal_id,
            "owner_scope_ref": self.owner_scope_ref,
            "sender": self.sender,
            "to": list(self.to),
            "cc": list(self.cc),
            "bcc": list(self.bcc),
            "subject": self.subject,
            "body_text": self.body_text,
            "body_html_sha256": self.body_html_sha256,
            "attachment_sha256": list(self.attachment_sha256),
            "thread_id": self.thread_id,
            "in_reply_to": self.in_reply_to,
            "nonce": self.nonce,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        return hashlib.sha256(canonical_bytes(record)).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class PreparedMimeV1:
    proposal_fingerprint: str
    mime_sha256: str
    raw_mime: bytes = field(repr=False)
    correlation_id: str = ""

    def __post_init__(self) -> None:
        _digest(self.proposal_fingerprint)
        _digest(self.mime_sha256)
        _ensure(type(self.raw_mime) is bytes and 0 < len(self.raw_mime) < 65536,
                "MAIL_MIME_DENIED")
        _ensure(hashlib.sha256(self.raw_mime).hexdigest() == self.mime_sha256,
                "MAIL_MIME_DIGEST_MISMATCH")
        _bounded_text(self.correlation_id, max_bytes=128)
