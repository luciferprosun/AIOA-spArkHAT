"""Gmail REST wire tests using synthetic raw MIME only; no HTTP requests."""

import base64
import hashlib
import json
import unittest

from runtime.communication.canonical_mime import prepare_mime
from runtime.communication.contracts import MailContractError, PreparedMimeV1
from runtime.communication.gmail.wire import (
    GmailAccepted, SEND_ENDPOINT, encode_send_request, parse_send_ack,
)
from test_gmail_contracts import proposal


class GmailWireTests(unittest.TestCase):
    def test_send_body_contains_only_raw_base64url(self):
        mime = prepare_mime(proposal())
        wire = encode_send_request(mime)
        obj = json.loads(wire)
        self.assertEqual(set(obj), {"raw"})
        encoded = obj["raw"]
        decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        self.assertEqual(decoded, mime.raw_mime)
        self.assertIn(b"To: owner@example.org\r\n", decoded)

    def test_wire_is_deterministic(self):
        m = prepare_mime(proposal())
        self.assertEqual(encode_send_request(m), encode_send_request(m))
        self.assertEqual(SEND_ENDPOINT,
                         "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")

    def test_wire_does_not_contain_provider_credential_fields(self):
        wire = encode_send_request(prepare_mime(proposal()))
        self.assertNotIn(b"Bearer", wire)
        self.assertNotIn(b"client_secret", wire)
        self.assertNotIn(b"refresh_token", wire)
        self.assertNotIn(b"authorized", wire)

    def test_reject_forged_mime_digest(self):
        mime = prepare_mime(proposal())
        forged = PreparedMimeV1.__new__(PreparedMimeV1)
        object.__setattr__(forged, "proposal_fingerprint", mime.proposal_fingerprint)
        object.__setattr__(forged, "mime_sha256", "b" * 64)
        object.__setattr__(forged, "raw_mime", mime.raw_mime)
        object.__setattr__(forged, "correlation_id", mime.correlation_id)
        with self.assertRaisesRegex(MailContractError, "MAIL_MIME_DIGEST_MISMATCH"):
            encode_send_request(forged)

    def test_success_ack_is_not_recipient_delivery(self):
        ack = parse_send_ack(200, b'{"id":"abcdef123456","threadId":"thread1","labelIds":["SENT"]}')
        self.assertEqual(ack, GmailAccepted("abcdef123456", "thread1"))
        self.assertTrue(ack.accepted_by_api)
        self.assertFalse(ack.delivered_to_recipient)

    def test_unknown_http_status_does_not_prove_absence(self):
        for status in (0, 201, 401, 403, 429, 500, 503):
            with self.subTest(status=status), self.assertRaisesRegex(
                MailContractError, "MAIL_GMAIL_ACK_UNCERTAIN"
            ):
                parse_send_ack(status, b'{"id":"x","threadId":"y"}')

    def test_missing_or_bad_ids_fail_closed(self):
        for body in (b"{}", b'{"id":"123"}', b'{"id":false,"threadId":"th"}',
                     b'{"id":"x","threadId":null}', b'{"id":"x\n","threadId":"th"}'):
            with self.subTest(body=body), self.assertRaises(MailContractError):
                parse_send_ack(200, body)

    def test_duplicate_json_fields_fail_closed(self):
        with self.assertRaisesRegex(MailContractError, "MAIL_GMAIL_ACK_INVALID"):
            parse_send_ack(200, b'{"id":"a","id":"b","threadId":"c"}')

    def test_error_body_rejected_even_with_200(self):
        with self.assertRaises(MailContractError):
            parse_send_ack(200, b'{"error":{"code":401},"message":"invalid"}')

    def test_ack_never_leaks_provider_extra_message_content(self):
        response = b'{"id":"one","threadId":"two","snippet":"private text","payload":{"body":"secret"}}'
        ack = parse_send_ack(200, response)
        self.assertNotIn("private text", repr(ack))
        self.assertNotIn("secret", repr(ack))

    def test_large_ack_rejected(self):
        with self.assertRaises(MailContractError):
            parse_send_ack(200, b"x" * 16385)


if __name__ == "__main__":
    unittest.main()
