"""NV10 disposable process/storage faults, no accepted state or external transport."""

import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from nv10_support import child, evidence
from runtime.core_admission import OwnerScope
from runtime.mission.lite_contracts import LiteProfile
from runtime.mission.lite_journal import LiteJournal
from runtime.nonzero_cloudops.state.files import (
    StateIntegrityError, open_local_payload, seal_local_payload, read_private_json,
)


class NV10RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_actual_process_exit_before_commit_has_no_partial_mutation(self):
        child({"mode": "crash-before-commit", "root": str(self.root)}, expected=75)
        fresh = child({"mode": "native-probe", "root": str(self.root)})
        self.assertNotEqual(os.getpid(), fresh["pid"])
        self.assertEqual([], fresh["ids"])
        evidence("crash-before-commit", label="FIXTURE", actual_process_exit=75,
                 fresh_pid=fresh["pid"], partial_accepted_mutations=0)

    def test_restart_after_durable_reservation_preserves_unknown_checkpoint(self):
        child({"mode": "crash-checkpoint", "root": str(self.root)}, expected=76)
        fresh = child({"mode": "checkpoint-probe", "root": str(self.root)})
        self.assertTrue(fresh["uncertain"])
        self.assertEqual("RECONCILE_READONLY_REQUIRED", fresh["state"]["state"])
        self.assertEqual(2, fresh["state"]["coordinator_epoch"])
        self.assertEqual(1, len(fresh["reservations"]))
        self.assertEqual("UNKNOWN", fresh["reservations"][0]["status"])
        second = child({"mode": "checkpoint-probe", "root": str(self.root)})
        self.assertNotEqual(fresh["state"]["lease_id"], second["state"]["lease_id"])
        self.assertEqual(3, second["state"]["coordinator_epoch"])
        self.assertEqual(fresh["reservations"], second["reservations"])
        evidence("restart-mid-checkpoint", label="LOCAL_CONTROLLED", exit_code=76,
                 fresh_pids=[fresh["pid"], second["pid"]], reservations=1, unknown_preserved=True)

    def test_corrupt_disposable_checkpoint_fails_instead_of_guessing_state(self):
        profile = LiteProfile(OwnerScope("nv10-t", "nv10-o", "nv10-s", "nv10-slot"),
                              "nv10-watch", "nv10-source", enabled=True)
        journal = LiteJournal(self.root, profile, 100)
        path = journal.path
        journal.close()
        with sqlite3.connect(path) as db:
            db.execute("UPDATE watch SET data='{' WHERE singleton=1")
        before = path.read_bytes()
        with self.assertRaises(json.JSONDecodeError):
            LiteJournal(self.root, profile, 101)
        self.assertEqual(before, path.read_bytes())

    def test_unknown_target_envelope_version_digest_and_truncation_reject(self):
        good = seal_local_payload({"scope": ["t", "o", "s", "slot"], "receipt": None},
                                  payload_type="AIOA_DISPOSABLE_SERVICE")
        for changes in ({"integrity_version": 999}, {"payload_type": "UNREVIEWED_V2"},
                        {"payload_sha256": "0" * 64}):
            with self.subTest(changes=changes), self.assertRaises(StateIntegrityError):
                open_local_payload({**good, **changes}, payload_type="AIOA_DISPOSABLE_SERVICE")
        path = self.root / "truncated-target-copy.json"
        path.write_text('{"integrity_version":1,')
        path.chmod(0o600)
        with self.assertRaises(StateIntegrityError):
            read_private_json(path)
        evidence("state-format", label="LOCAL_CONTROLLED", wrong_version="REJECTED",
                 corrupt_digest="REJECTED", truncated_payload="REJECTED")


if __name__ == "__main__":
    unittest.main()
