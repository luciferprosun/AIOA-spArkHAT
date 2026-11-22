"""Cold read of an unresolved Core intent through the existing journal."""
import json
import os
import subprocess
import sys
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from q09_support import Fixture

from lab.archaioa.authority import Money
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.warrant import approval_digest

CAS_REF = "refs/heads/offline-cas"


def git(repository, *args, input=None):
    return subprocess.run(
        ["git", "-C", str(repository), *args], input=input, text=True,
        capture_output=True, check=True, timeout=10,
        env={"PATH": os.defpath, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
             "GIT_AUTHOR_NAME": "Fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
             "GIT_COMMITTER_NAME": "Fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"},
    ).stdout.strip()


def git_intent(fixture, commit, session):
    fixture.operation.update(operation_class="GIT_COMMIT", payload={
        "schema": "aioa.local-operation.v2", "session_id": session,
        "policy_epoch": 1, "ref": CAS_REF, "commit_sha": commit, "expected_old_sha": "0" * 40,
    })
    digest = canonical_sha256(fixture.operation)
    scope = replace(fixture.warrant.authority_scope, operation_classes=("GIT_COMMIT",),
                    monetary_ceiling=Money(Decimal(0), "USD"))
    warrant = replace(fixture.warrant, operation_class="GIT_COMMIT", authority_scope=scope,
                      money_reservation_id="NONE", operation_hash="sha256:" + digest)
    fixture.warrant = replace(warrant, approval_digest=approval_digest(warrant))
    fixture.request = replace(fixture.request, money_nano=0, request_digest=digest)
    return CoreIntentJournal(fixture.ledger, fixture.gov)


class ColdIntentReadTests(unittest.TestCase):
    def test_cold_git_intent_has_no_replay_or_writer_proof_from_ref(self):
        scenarios = ("before-cas", "after-cas", "after-ref-drift", "matching-ref-from-another-writer")
        for scenario in scenarios:
            with self.subTest(scenario=scenario), TemporaryDirectory() as scratch:
                root = Path(scratch)
                repository = root / "target.git"
                repository.mkdir()
                git(repository, "init", "--bare", "--object-format=sha1")
                tree = git(repository, "mktree", input="")
                commit = git(repository, "commit-tree", tree, "-m", "Intended CAS")
                later = git(repository, "commit-tree", tree, "-p", commit, "-m", "Later ref update")
                path = root / "intent.json"
                producer = self.run_process("produce", path, repository, commit, scenario)
                self.assertEqual(producer.returncode, 75, producer.stderr)
                original_session = producer.stdout.decode().strip()
                self.assertTrue(original_session)
                ref_file = repository / CAS_REF
                if scenario == "after-ref-drift":
                    git(repository, "update-ref", CAS_REF, later, commit)
                if scenario == "matching-ref-from-another-writer":
                    git(repository, "update-ref", CAS_REF, commit, "0" * 40)
                expected = {
                    "before-cas": None, "after-cas": commit, "after-ref-drift": later,
                    "matching-ref-from-another-writer": commit,
                }[scenario]
                self.assertEqual(ref_file.read_text().strip() if ref_file.exists() else None, expected)
                before = path.read_bytes()
                reader = self.run_process("read", path, commit, original_session)
                self.assertEqual(reader.returncode, 0, reader.stderr)
                self.assertEqual(json.loads(reader.stdout), {
                    "outcome": "Unknown", "grants_replay": False, "reservation": "UNKNOWN",
                    "outbox": "HELD", "effect_verified": False,
                    "retry_denial": "LOCAL_ZERO_BINDING",
                    "reconciliation_denial": "INDEPENDENT_READBACK_REQUIRED",
                })
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(ref_file.read_text().strip() if ref_file.exists() else None, expected)

    def run_process(self, *args):
        return subprocess.run([sys.executable, "-B", __file__, *map(str, args)],
                              capture_output=True, timeout=20, check=False)

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


def crash_git_intent(path, repository, commit, scenario):
    fixture = Fixture(path)
    principal = fixture.p()
    journal = git_intent(fixture, commit, principal.actor_session_id)
    fixture.init()
    args = (principal, fixture.warrant, fixture.operation, fixture.request)
    started = journal.start_local_zero(*args)
    assert started["local_step_now"]
    assert not journal.start_local_zero(*args)["local_step_now"]
    if scenario in {"after-cas", "after-ref-drift"}:
        git(repository, "update-ref", CAS_REF, commit, "0" * 40)
    print(principal.actor_session_id, flush=True)
    os._exit(75)


def cold_read_git_intent(path, commit, original_session):
    fixture = Fixture(path)
    try:
        journal = git_intent(fixture, commit, original_session)
        fixture.ledger.clock = lambda: fixture.warrant.expires_at
        reader = fixture.p(Capability.READ)
        view = journal.inspect(reader, fixture.warrant)
        reservation = fixture.gov.inspect(reader)["reservations"][fixture.warrant.risk_reservation_id]
        warrant = fixture.ledger.inspect(reader, fixture.warrant)
        outbox = fixture.runner.run(TransactionContext(reader, Capability.READ),
                                     lambda tx: tx.get(RecordKind.OUTBOX, journal._key(fixture.warrant)))
        result = {
            "outcome": view["outcome"]["contract_type"], "grants_replay": view["grants_replay"],
            "reservation": reservation["state"], "outbox": outbox.payload["state"],
            "effect_verified": warrant["effect_verified"],
        }
        try:
            journal.start_local_zero(fixture.p(), fixture.warrant, fixture.operation, fixture.request)
        except ValueError as denied:
            result["retry_denial"] = str(denied)
        try:
            journal.reconcile(fixture.p(), fixture.warrant, 1)
        except ValueError as denied:
            result["reconciliation_denial"] = str(denied)
        print(json.dumps(result))
    finally:
        fixture.close()


if __name__ == "__main__":
    if sys.argv[1] == "produce":
        _, _, path, repository, commit, scenario = sys.argv
        crash_git_intent(Path(path), Path(repository), commit, scenario)
    elif sys.argv[1] == "read":
        cold_read_git_intent(Path(sys.argv[2]), sys.argv[3], sys.argv[4])
    else:
        cold_read(Path(sys.argv[1]))
