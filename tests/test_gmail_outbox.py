"""Hermetic fake Gmail, replay and persistence tests. No credentials/network."""

from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sqlite3
import stat
import tempfile
import unittest

from runtime.communication.canonical_mime import prepare_mime
from runtime.communication.outbox import MailLedgerError, OutboxLedger, OutboxState
from runtime.communication.fakes.gmail import (
    FakeGmail, OfflineFixtureAdmission, simulate_once,
)
from test_gmail_contracts import proposal


class GmailOutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "mail.sqlite3"
        self.ledger = OutboxLedger(self.path)
        self.addCleanup(lambda: self.ledger.close())
        self.p = proposal()

    def approval(self, p=None):
        p = p or self.p
        return OfflineFixtureAdmission(
            p.fingerprint, prepare_mime(p).mime_sha256, p.expires_at
        )

    def run_fake(self, behavior="ok", *, p=None):
        p = p or self.p
        fake = FakeGmail(behavior)
        now = datetime(2026, 10, 20, 8, 1, tzinfo=timezone.utc)
        view = simulate_once(p, self.approval(p), self.ledger, fake, now=now)
        return view, fake

    def test_success_is_api_acceptance_not_delivery(self):
        row, fake = self.run_fake()
        self.assertEqual(fake.calls, 1)
        self.assertEqual(row.state, OutboxState.SENT_ACCEPTED_BY_API)
        self.assertTrue(row.provider_message_id.startswith("fixture-msg-"))

    def test_lost_ack_after_acceptance_is_unknown_and_no_retry(self):
        row, fake = self.run_fake("accept_then_timeout")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(len(fake.accepted_digests), 1)
        self.assertEqual(row.state, OutboxState.UNKNOWN_SEND)
        with self.assertRaises(MailLedgerError):
            simulate_once(self.p, self.approval(), self.ledger, fake,
                          now=datetime(2026, 10, 20, 8, 2, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 1)

    def test_even_known_fake_rejection_is_conservative(self):
        row, fake = self.run_fake("reject_before_accept")
        self.assertEqual(row.state, OutboxState.UNKNOWN_SEND)
        self.assertEqual(fake.calls, 1)

    def test_crash_recovery_latches_unknown_and_blocks_begin(self):
        self.ledger.prepare(self.p, prepare_mime(self.p))
        self.ledger.begin_attempt(self.p.proposal_id)
        self.ledger.close()
        self.ledger = OutboxLedger(self.path)
        recovered = self.ledger.recover_interrupted()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].state, OutboxState.UNKNOWN_SEND)
        with self.assertRaises(MailLedgerError):
            self.ledger.begin_attempt(self.p.proposal_id)
        self.assertEqual(self.ledger.recover_interrupted(), ())

    def test_duplicate_proposal_rejected_even_if_content_changes(self):
        mime = prepare_mime(self.p)
        self.ledger.prepare(self.p, mime)
        with self.assertRaises(MailLedgerError):
            self.ledger.prepare(self.p, mime)
        with self.assertRaises(MailLedgerError):
            p2 = replace(self.p, subject="Changed subject")
            self.ledger.prepare(p2, prepare_mime(p2))

    def test_no_second_send_after_success(self):
        _, fake = self.run_fake()
        with self.assertRaises(MailLedgerError):
            simulate_once(self.p, self.approval(), self.ledger, fake,
                          now=datetime(2026, 10, 20, 8, 2, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 1)

    def test_stop_denies_before_outbox_and_transport(self):
        fake = FakeGmail()
        with self.assertRaisesRegex(MailLedgerError, "MAIL_OFFLINE_STOPPED"):
            simulate_once(self.p, self.approval(), self.ledger, fake,
                          now=datetime(2026, 10, 20, 8, 1, tzinfo=timezone.utc),
                          stop_requested=True)
        self.assertIsNone(self.ledger.read(self.p.proposal_id))
        self.assertEqual(fake.calls, 0)

    def test_untrusted_boolean_cannot_create_fake_admission(self):
        fake = FakeGmail()
        with self.assertRaises(MailLedgerError):
            simulate_once(self.p, {"approved": True}, self.ledger, fake,
                          now=datetime(2026, 10, 20, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 0)

    def test_changed_mime_digest_is_rejected_before_attempt(self):
        fake = FakeGmail()
        wrong = OfflineFixtureAdmission(self.p.fingerprint, "c" * 64, self.p.expires_at)
        with self.assertRaisesRegex(MailLedgerError, "MAIL_FIXTURE_BINDING_DENIED"):
            simulate_once(self.p, wrong, self.ledger, fake,
                          now=datetime(2026, 10, 20, 8, 1, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 0)

    def test_expired_fixture_denied(self):
        fake = FakeGmail()
        with self.assertRaises(MailLedgerError):
            simulate_once(self.p, self.approval(), self.ledger, fake,
                          now=datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(fake.calls, 0)

    def test_receipts_do_not_store_content_or_addresses(self):
        self.run_fake()
        self.ledger.close()
        data = self.path.read_bytes()
        self.assertNotIn(b"owner@example.org", data)
        self.assertNotIn(b"Question for a collaborator", data)
        self.assertNotIn(b"Can you review", data)

    def test_db_private_permissions(self):
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_unsafe_parent_permissions_denied(self):
        open_dir = Path(self.tmp.name) / "wide"
        open_dir.mkdir(mode=0o755)
        os.chmod(open_dir, 0o755)
        with self.assertRaises(MailLedgerError):
            OutboxLedger(open_dir / "unsafe.sqlite3")

    def test_record_corruption_detected(self):
        self.run_fake()
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("UPDATE gmail_outbox_v1 SET state='PREPARED'")
        with self.assertRaisesRegex(MailLedgerError, "MAIL_LEDGER_RECORD_CHANGED"):
            self.ledger.read(self.p.proposal_id)

    def test_two_connections_cannot_reuse_attempt(self):
        self.ledger.prepare(self.p, prepare_mime(self.p))
        second = OutboxLedger(self.path)
        self.addCleanup(second.close)
        self.ledger.begin_attempt(self.p.proposal_id)
        with self.assertRaises(MailLedgerError):
            second.begin_attempt(self.p.proposal_id)

    def test_read_and_recovery_cannot_send(self):
        row, fake = self.run_fake("accept_then_timeout")
        for _ in range(3):
            self.assertEqual(self.ledger.read(self.p.proposal_id).state,
                             OutboxState.UNKNOWN_SEND)
            self.assertEqual(self.ledger.recover_interrupted(), ())
        self.assertEqual(fake.calls, 1)


if __name__ == "__main__":
    unittest.main()
