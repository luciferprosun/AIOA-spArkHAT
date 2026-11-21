"""Cold read of an unresolved Core intent through the existing journal."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from q09_support import Fixture


class ColdIntentReadTests(unittest.TestCase):
    def test_restart_without_verifier_keeps_held_intent_read_only(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "intent.json"
            fixture = Fixture(path)
            try:
                fixture.init()
            finally:
                fixture.close()
            producer = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).with_name("q09_support.py")),
                 "crash-after-start", str(path)],
                capture_output=True, timeout=20, check=False,
            )
            self.assertEqual(producer.returncode, 75, producer.stderr)
            before = path.read_bytes()
            reader = subprocess.run(
                [sys.executable, "-B", str(Path(__file__)), str(path)],
                capture_output=True, timeout=20, check=False,
            )
            self.assertEqual(reader.returncode, 0, reader.stderr)
            self.assertEqual(json.loads(reader.stdout), {
                "outcome": "Unknown",
                "authority": "NONE",
                "grants_replay": False,
                "reservation": "UNKNOWN",
                "warrant": "WARRANT_CONSUMPTION_ONLY",
                "warrant_effect_verified": False,
                "delivery_denial": "OUTCOME_UNKNOWN",
                "reconciliation_denial": "INDEPENDENT_READBACK_REQUIRED",
            })
            self.assertEqual(path.read_bytes(), before)


def cold_read(path):
    from runtime.core_admission import Capability
    from runtime.mission.intent import CoreIntentJournal

    fixture = Fixture(path)
    try:
        journal = CoreIntentJournal(fixture.ledger, fixture.gov)
        reader = fixture.p(Capability.READ)
        view = journal.inspect(reader, fixture.warrant)
        reservation = fixture.gov.inspect(reader)["reservations"]["paired-1"]
        warrant = fixture.ledger.inspect(reader, fixture.warrant)
        result = {
            "outcome": view["outcome"]["contract_type"],
            "authority": view["authority"],
            "grants_replay": view["grants_replay"],
            "reservation": reservation["state"],
            "warrant": warrant["kind"],
            "warrant_effect_verified": warrant["effect_verified"],
        }
        for field, call in (
            ("delivery_denial", lambda: journal.delivery(reader, fixture.warrant)),
            ("reconciliation_denial",
             lambda: journal.reconcile(fixture.p(), fixture.warrant, 1)),
        ):
            try:
                call()
            except ValueError as denied:
                result[field] = str(denied)
        print(json.dumps(result))
    finally:
        fixture.close()


if __name__ == "__main__":
    cold_read(Path(sys.argv[1]))
