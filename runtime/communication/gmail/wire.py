"""Pure Gmail users.messages.send JSON encoding/ACK validation.

No credential loading, sockets, HTTP calls, retries or approval logic live here.
This is a protocol codec, NOT an active provider adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import re

from runtime.communication.contracts import MailContractError, PreparedMimeV1


SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,180}\Z")
MAX_ACK_BYTES = 16384


@dataclass(frozen=True, slots=True)
class GmailAccepted:
    provider_message_id: str
    provider_thread_id: str
    accepted_by_api: bool = True
    delivered_to_recipient: bool = False

    def __post_init__(self) -> None:
        if (type(self.provider_message_id) is not str
                or _ID.fullmatch(self.provider_message_id) is None
                or type(self.provider_thread_id) is not str
                or _ID.fullmatch(self.provider_thread_id) is None
                or self.accepted_by_api is not True
                or self.delivered_to_recipient is not False):
            raise MailContractError("MAIL_GMAIL_ACK_INVALID")


def encode_send_request(prepared: PreparedMimeV1) -> bytes:
    """Return strictly encoded JSON body. Callers must separately obtain Core authority."""
    if type(prepared) is not PreparedMimeV1:
        raise MailContractError("MAIL_GMAIL_MIME_REQUIRED")
    prepared.__post_init__()
    raw = base64.urlsafe_b64encode(prepared.raw_mime).decode("ascii").rstrip("=")
    # Gmail does not support an idempotency-key in this request.
    return json.dumps({"raw": raw}, separators=(",", ":"), sort_keys=True).encode("utf-8")


def parse_send_ack(http_status: int, data: bytes) -> GmailAccepted:
    """Parse only a definitive success ACK; other statuses are NOT proof of no effect.

    The future transport must latch ambiguity to UNKNOWN_SEND, not retry.
    """
    if type(http_status) is not int or http_status != 200:
        raise MailContractError("MAIL_GMAIL_ACK_UNCERTAIN")
    if type(data) is not bytes or not 1 <= len(data) <= MAX_ACK_BYTES:
        raise MailContractError("MAIL_GMAIL_ACK_INVALID")

    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise MailContractError("MAIL_GMAIL_ACK_INVALID")
            result[key] = value
        return result

    def no_nonfinite_constant(_value):
        raise MailContractError("MAIL_GMAIL_ACK_INVALID")

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicate_keys,
                           parse_constant=no_nonfinite_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise MailContractError("MAIL_GMAIL_ACK_INVALID") from exc
    if type(value) is not dict or "error" in value:
        raise MailContractError("MAIL_GMAIL_ACK_INVALID")
    message_id, thread_id = value.get("id"), value.get("threadId")
    if (type(message_id) is not str or _ID.fullmatch(message_id) is None
            or type(thread_id) is not str or _ID.fullmatch(thread_id) is None):
        raise MailContractError("MAIL_GMAIL_ACK_INVALID")
    # Ignore provider-added metadata (labels/snippet/history) to prevent
    # accidental propagation of third-party message bodies into Core receipts.
    return GmailAccepted(message_id, thread_id)
