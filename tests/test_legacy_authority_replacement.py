"""Behavioral acceptance of the single Core across legacy authority domains."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lab.archaioa.authority import Money
from q09_support import Fixture
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.mission.warrant import approval_digest

OPERATIONS = ("GIT_COMMIT", "WORKSPACE_WRITE")


def local_effect(fixture, operation_class, suffix):
    operation = {
        **fixture.operation,
        "operation_class": operation_class,
        "payload": {
            "schema": "aioa.local-operation.v2",
            "principal_session_id": fixture.p().actor_session_id,
            "policy_epoch": 1,
            "fixture_intent": suffix,
        },
    }
    digest = canonical_sha256(operation)
    scope = replace(fixture.warrant.authority_scope, operation_classes=(operation_class,),
                    monetary_ceiling=Money(Decimal(0), "USD"))
    warrant = replace(fixture.warrant, operation_class=operation_class, authority_scope=scope,
                      nonce="nonce-" + suffix, warrant_id="warrant-" + suffix,
                      money_reservation_id="NONE", risk_reservation_id="risk-" + suffix,
                      operation_hash="sha256:" + digest)
    warrant = replace(warrant, approval_digest=approval_digest(warrant))
    reservation = replace(fixture.request, request_id=warrant.risk_reservation_id,
                          money_nano=0, request_digest=digest)
    return warrant, operation, reservation


class LegacyAuthorityReplacementTests(unittest.TestCase):
    def test_git_and_workspace_cannot_bypass_each_others_durable_hold(self):
        for first, second in (OPERATIONS, OPERATIONS[::-1]):
            with self.subTest(first=first), TemporaryDirectory() as scratch:
                db = Path(scratch) / "core.json"
                fixture = Fixture(db)
                try:
                    fixture.gov.start_epoch(fixture.p(Capability.MANAGE))
                    held = local_effect(fixture, first, "held")
                    competing = local_effect(fixture, second, "competing")
                    for warrant, _, _ in (held, competing):
                        fixture.ledger.approve(fixture.p(Capability.OWNER_APPROVAL), warrant)
                    result = fixture.journal.start_local_zero(fixture.p(), *held)
                    self.assertTrue(result["local_step_now"])
                    self.assertFalse(result["grants_replay"])
                    self.assertFalse(fixture.journal.start_local_zero(fixture.p(), *held)["local_step_now"])
                    with self.assertRaisesRegex(ValueError, "^UNRESOLVED_INTENT$"):
                        fixture.journal.start_local_zero(fixture.p(), *competing)
                    preserved = db.read_bytes()
                finally:
                    fixture.close()

                reopened = Fixture(db)
                try:
                    self.assertEqual(preserved, db.read_bytes())
                    reader = reopened.p(Capability.READ)
                    intent = reopened.journal.inspect(reader, held[0])
                    self.assertEqual("Unknown", intent["outcome"]["contract_type"])
                    box = reopened.runner.run(
                        TransactionContext(reader, Capability.READ),
                        lambda tx: tx.get(RecordKind.OUTBOX, reopened.journal._key(held[0])),
                    )
                    self.assertEqual("HELD", box.payload["state"])
                    reservations = reopened.gov.inspect(reader)["reservations"]
                    self.assertEqual("UNKNOWN", reservations["risk-held"]["state"])
                    self.assertNotIn("risk-competing", reservations)
                    # The second approved domain has a fresh nonce and reservation,
                    # but uses the same durable owner-scoped START boundary.
                    renewed_binding = local_effect(reopened, second, "new-session")
                    reopened.ledger.approve(reopened.p(Capability.OWNER_APPROVAL), renewed_binding[0])
                    before = db.read_bytes()
                    with self.assertRaisesRegex(ValueError, "^UNRESOLVED_INTENT$"):
                        reopened.journal.start_local_zero(reopened.p(), *renewed_binding)
                    self.assertIsNone(reopened.ledger.inspect(reader, competing[0]))
                    self.assertIsNone(reopened.ledger.inspect(reader, renewed_binding[0]))
                    self.assertEqual(before, db.read_bytes())
                finally:
                    reopened.close()
