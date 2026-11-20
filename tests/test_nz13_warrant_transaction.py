"""Canonical warrant consumption composed with real Core SQLite transactions.

Only local management facts are written. No target, executor or model is used;
these tests do not certify Portable registration or physical effect release.
"""
import unittest
from unittest.mock import Mock, patch

import test_core_warrant as legacy

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    LocalCoreRecordFactory,
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
    TransactionContext,
    TransactionRunner,
)
from runtime.mission.warrant import CoreWarrantLedger


class WarrantTransactionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = legacy.CoreWarrantTests('test_no_approval_no_consumption')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.core = self.fixture.core
        self.scope = self.fixture.ledger.scope
        self.factory = LocalCoreRecordFactory(self.fixture.path.with_suffix('.sqlite'), self.core)
        self.runner = TransactionRunner(self.core, self.factory)
        self.addCleanup(self.runner.close)
        self.ledger = CoreWarrantLedger(self.core, self.runner, self.scope,
                                        clock=lambda: self.fixture.now)
        self.warrant = self.fixture.warrant
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), self.warrant)
        self.companion = StoredRecord(RecordKind.OPERATION, 'management-companion', self.scope, 1,
                                      {'schema': 'test.management-fact.v1', 'effect_verified': False})

    def p(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def run_tx(self, callback, purpose=Capability.COMMIT):
        return self.runner.run(TransactionContext(self.p(purpose), purpose), callback)

    def hook(self):
        value = getattr(self.ledger, 'consume_in_transaction', None)
        self.assertTrue(callable(value), 'Canonical transaction-local warrant consumption is missing')
        return value

    def records(self):
        return self.run_tx(lambda tx: canonical_json_bytes({
            kind.value: [record.payload for record in tx.scan(kind, limit=32)]
            for kind in (RecordKind.OPERATION, RecordKind.APPROVAL)}), Capability.READ)

    def consumption(self):
        return self.ledger.inspect(self.p(Capability.READ), self.warrant)

    def test_hook_uses_existing_transaction_without_opening_a_runner(self):
        consume = self.hook()
        def body(tx):
            with patch.object(self.runner, 'run', side_effect=AssertionError('NESTED_RUNNER')):
                receipt = consume(tx, self.warrant)
                tx.insert(self.companion)
                return receipt
        receipt = self.run_tx(body)
        self.assertEqual(receipt, self.consumption())
        self.assertFalse(receipt['effect_verified'])
        self.assertFalse(receipt['grants_replay'])
        self.assertIsNotNone(self.run_tx(lambda tx: tx.get(self.companion.kind, self.companion.record_id),
                                        Capability.READ))

    def test_public_consume_delegates_to_the_same_transaction_hook(self):
        original = getattr(self.ledger, 'consume_in_transaction', None)
        hook = Mock(wraps=original)
        with patch.object(self.ledger, 'consume_in_transaction', hook, create=True):
            receipt = self.ledger.consume(self.p(), self.warrant)
        self.assertEqual(1, hook.call_count,
                         'Public consumption must reuse the canonical in-transaction implementation')
        self.assertEqual(receipt, self.consumption())

    def test_failure_after_consumption_rolls_back_the_companion_and_warrant(self):
        consume = self.hook()
        before = self.records()
        def body(tx):
            consume(tx, self.warrant)
            tx.insert(self.companion)
            raise ValueError('AFTER_CONSUMPTION_BEFORE_COMMIT')
        with self.assertRaises(MemoryPatchError):
            self.run_tx(body)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.consumption())

    def test_conflicting_companion_insert_cannot_leave_partial_consumption(self):
        consume = self.hook()
        self.run_tx(lambda tx: tx.insert(self.companion))
        before = self.records()
        def body(tx):
            consume(tx, self.warrant)
            tx.insert(self.companion)
        with self.assertRaises(MemoryPatchError):
            self.run_tx(body)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.consumption())

    def test_two_consumptions_in_one_transaction_fail_and_roll_back(self):
        consume = self.hook()
        before = self.records()
        def body(tx):
            consume(tx, self.warrant)
            consume(tx, self.warrant)
        with self.assertRaisesRegex(ValueError, 'WARRANT_ALREADY_CONSUMED'):
            self.run_tx(body)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.consumption())

    def test_owner_approval_purpose_cannot_be_used_as_commit_authority(self):
        consume = self.hook()
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'WARRANT_CONSUMPTION_CONTEXT'):
            self.run_tx(lambda tx: consume(tx, self.warrant), Capability.OWNER_APPROVAL)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.consumption())

    def test_lost_commit_ack_keeps_both_facts_without_granting_another_use(self):
        consume = self.hook()
        original = LocalCoreTransaction.commit
        def lose_ack(tx):
            original(tx)
            raise CommitOutcomeUnknown()
        def body(tx):
            consume(tx, self.warrant)
            tx.insert(self.companion)
        with patch.object(LocalCoreTransaction, 'commit', lose_ack), self.assertRaises(CommitOutcomeUnknown):
            self.run_tx(body)
        receipt = self.consumption()
        self.assertFalse(receipt['grants_replay'])
        self.assertFalse(receipt['effect_verified'])
        self.assertIsNotNone(self.run_tx(lambda tx: tx.get(self.companion.kind, self.companion.record_id),
                                        Capability.READ))
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'WARRANT_ALREADY_CONSUMED'):
            self.run_tx(lambda tx: consume(tx, self.warrant))
        self.assertEqual(before, self.records())

    def test_revoked_approval_cannot_be_consumed_in_a_composed_transaction(self):
        consume = self.hook()
        self.ledger.revoke(self.p(Capability.OWNER_APPROVAL), self.warrant)
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'WARRANT_REVOKED'):
            self.run_tx(lambda tx: consume(tx, self.warrant))
        self.assertEqual(before, self.records())
        self.assertIsNone(self.consumption())
