"""Offline G1 tests: no network, no OAuth, no mail effects."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import hashlib
import unittest

from runtime.communication.contracts import MailContractError, MailProposalV1
from runtime.communication.canonical_mime import prepare_mime


def proposal(**changes):
    now = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    args = dict(
        task_id="t01", proposal_id="p01", owner_scope_ref="scope-01",
        sender="test@example.org", to=("owner@example.org",),
        subject="Question for a collaborator",
        body_text="Hello.\nCan you review option A?\n",
        nonce="a" * 64,
        created_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=(now + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    args.update(changes)
    return MailProposalV1(**args)


class MailContractsTests(unittest.TestCase):
    def test_same_proposal_same_mime(self):
        a = prepare_mime(proposal())
        b = prepare_mime(proposal())
        self.assertEqual(a.raw_mime, b.raw_mime)
        self.assertEqual(a.mime_sha256, hashlib.sha256(a.raw_mime).hexdigest())
        self.assertEqual(a.proposal_fingerprint, proposal().fingerprint)
        self.assertNotIn(b"Authorization:", a.raw_mime)

    def test_exact_mime_headers(self):
        msg = BytesParser(policy=policy.SMTP).parsebytes(prepare_mime(proposal()).raw_mime)
        self.assertEqual(msg["To"], "owner@example.org")
        self.assertEqual(msg["From"], "test@example.org")
        self.assertTrue(str(msg["Message-ID"]).lstrip().startswith("<aioa-"))
        self.assertEqual(msg.get_content().replace("\r\n", "\n"), proposal().body_text)

    def test_content_scope_and_nonce_are_bound(self):
        initial = proposal().fingerprint
        for patch in ({"to": ("other@example.org",)}, {"subject": "Changed"},
                      {"body_text": "Different"}, {"owner_scope_ref": "scope-02"},
                      {"nonce": "b" * 64}, {"task_id": "other"}):
            with self.subTest(patch=patch):
                self.assertNotEqual(proposal(**patch).fingerprint, initial)

    def test_header_injection_denied(self):
        for patch in ({"subject": "subject\nBcc: bad@example.org"},
                      {"sender": "user@example.org\r\nBcc: bad@example.org"},
                      {"to": ("bad@host.invalid\nCc: x@attacker.tld",)},
                      {"body_text": "ok\x00invisible"}):
            with self.subTest(patch=patch), self.assertRaises(MailContractError):
                proposal(**patch)

    def test_duplicate_recipients_denied(self):
        with self.assertRaises(MailContractError):
            proposal(to=("OWNER@example.org", "owner@example.org"))

    def test_bidi_and_noncanonical_text_denied(self):
        for txt in ("Hi\u202e you", "e\u0301"):
            with self.subTest(txt=txt), self.assertRaises(MailContractError):
                proposal(subject=txt)

    def test_expired_interval_denied(self):
        with self.assertRaises(MailContractError):
            proposal(expires_at=proposal().created_at)

    def test_unreviewed_features_fail_closed(self):
        for patch in ({"bcc": ("hidden@example.org",)},
                      {"cc": ("copy@example.org",)},
                      {"attachment_sha256": ("f" * 64,)},
                      {"body_html_sha256": "b" * 64},
                      {"thread_id": "some-thread"}):
            with self.subTest(patch=patch), self.assertRaises(MailContractError):
                prepare_mime(proposal(**patch))

    def test_no_authority_flag_in_proposal(self):
        with self.assertRaises(TypeError):
            proposal(approved_by_owner=True)


if __name__ == "__main__":
    unittest.main()
