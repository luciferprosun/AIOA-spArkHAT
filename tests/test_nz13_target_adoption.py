"""Exact owner adoption of administrator-prepared inventory into the existing Core.

Inventory preparation is explicit fixture administration, never product INIT.
Core writes are real SQLite transactions; no Portable effect is executed.
Physical release fencing, model authority and production composition stay open.
"""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from lab_archaioa import test_warrant as warrant_fixture
from nonzero_cloudops.adapters.portable import PortableStateStore
from test_dual_governor import SCOPE, core

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import Capability
from runtime.memory_patch.adapters.cockroach.repositories import canonical_record
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import (
    CommitOutcomeUnknown,
    MemoryPatchError,
)
from runtime.memory_patch.persistence.ports import (
    LocalCoreRecordFactory,
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
    TransactionContext,
    TransactionRunner,
    TransactionView,
)
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.liability import CoreLiabilityLedger
from runtime.mission.target_projection import CoreTargetProjection
from runtime.mission.warrant import CoreWarrantLedger, WarrantError, approval_digest


class TargetAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.core = core()
        self.addCleanup(self.core.close)
        self.factory = LocalCoreRecordFactory(self.path / 'core.sqlite', self.core)
        self.runner = TransactionRunner(self.core, self.factory)
        self.addCleanup(self.runner.close)
        self.now = datetime(2026, 11, 9, tzinfo=UTC)
        self.ledger = CoreWarrantLedger(self.core, self.runner, SCOPE, clock=lambda: self.now)
        limits = Limits(100, 10)
        self.policy = GovernorPolicy(SCOPE, 'adoption-test', limits, limits, limits)
        self.gov = CoreDualGovernor(self.core, self.runner, self.policy, clock=lambda: 100)
        self.gov.start_epoch(self.p(Capability.MANAGE))
        self.journal = CoreIntentJournal(self.ledger, self.gov)
        self.liability = CoreLiabilityLedger(self.core, self.runner, SCOPE)
        self.store = PortableStateStore(self.path / 'target/inventory.json')
        # Explicit administrator preparation, outside every Core transaction.
        with self.store._lock(exclusive=True):
            resources, receipts = self.store._initial_snapshot()
            self.store._write(resources, receipts)
        self.inventory_before = self.store._path.read_bytes()

    def p(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def run_tx(self, callback, purpose=Capability.COMMIT):
        return self.runner.run(TransactionContext(self.p(purpose), purpose), callback)

    def prepare(self):
        method = getattr(CoreTargetProjection, 'prepare_existing_adoption', None)
        self.assertTrue(callable(method), 'Same-Core approved existing-inventory adoption is missing')
        with self.store.target_guard():
            observed = self.store.observe_guarded_inventory()
            return method(self.journal, self.liability, self.p(), workspace='workspace-1',
                          target_id='portable-inventory-1', state_root=observed.state_root,
                          resources_root=observed.resources_root, receipts_root=observed.receipts_root,
                          guard_fingerprint=observed.guard_fingerprint)

    def warrant(self, request, *, nonce='adopt-once', currency='USD'):
        operation = request.operation()
        owner = canonical_sha256(SCOPE)
        scope = AuthorityScope(operation_classes=('TARGET_ADOPT_EXISTING',),
            target_scope=operation['target_fingerprint'], risk_ceiling=RiskLevel.LOW,
            monetary_ceiling=Money(Decimal(0), currency), not_before=self.now,
            expires_at=self.now + timedelta(minutes=1), owner_scope=owner, task_scope='adopt-task')
        warrant = EffectWarrant(warrant_id='warrant-' + nonce, task_id='adopt-task', owner_scope=owner,
            operation_class=operation['operation_class'], operation_hash='sha256:' + canonical_sha256(operation),
            target_fingerprint=operation['target_fingerprint'],
            expected_target_revision=operation['expected_target_revision'], revision_policy=RevisionPolicy.REQUIRE,
            decision_dependency_root=DecisionDependencyRoot((request.binding.evidence(), request.evidence())),
            lease_epoch=request.epoch, authority_scope=scope, approval_digest='sha256:' + '0' * 64,
            money_reservation_id='NONE', risk_reservation_id='NONE', nonce=nonce,
            issued_at=self.now, expires_at=self.now + timedelta(minutes=1))
        return replace(warrant, approval_digest=approval_digest(warrant))

    def approve(self, request, **kwargs):
        warrant = self.warrant(request, **kwargs)
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), warrant)
        return warrant

    def adopt(self, port, request, warrant, *, current=None):
        # Fresh facts are captured under the same held named guard before SQL.
        with self.store.target_guard():
            observed = self.store.observe_guarded_inventory()
            fresh = replace(request, state_root=observed.state_root, resources_root=observed.resources_root,
                            receipts_root=observed.receipts_root,
                            binding=replace(request.binding, guard_fingerprint=observed.guard_fingerprint))
            return self.run_tx(lambda tx: port.adopt_existing_in_transaction(
                tx, warrant, fresh if current is None else current))

    def head(self, port):
        return self.run_tx(lambda tx: port.load(tx), Capability.READ)

    def records(self):
        return self.run_tx(lambda tx: canonical_json_bytes({
            kind.value: [record.payload for record in tx.scan(kind, limit=128)]
            for kind in (RecordKind.OPERATION, RecordKind.APPROVAL)}), Capability.READ)

    def delete(self, identity):
        # Controlled damage to this test's private SQLite fixture only.
        self.factory.db.execute('DELETE FROM core_records_v1 WHERE scope_key=? AND kind=? AND record_id=?',
            (canonical_json_bytes(SCOPE.binding()).decode(), RecordKind.OPERATION.value, identity))

    def assert_inventory_unchanged(self):
        self.assertEqual(self.inventory_before, self.store._path.read_bytes())

    def test_owner_adoption_creates_only_joined_management_facts_in_one_core(self):
        port, request = self.prepare()
        self.assertIs(port.core, self.core)
        self.assertIs(port.runner, self.runner)
        warrant = self.approve(request)
        receipt = self.adopt(port, request, warrant)
        row, head = self.head(port)
        self.assertEqual(1, row.revision)
        self.assertEqual(0, head['generation'])
        self.assertEqual(request.state_root, head['state_root'])
        self.assertEqual('TARGET_ADOPTION_ONLY', receipt['kind'])
        self.assertFalse(receipt['effect_verified'])
        self.assertFalse(receipt['grants_replay'])
        self.assertEqual(warrant.digest(), receipt['warrant_digest'])
        self.assertFalse(self.ledger.inspect(self.p(Capability.READ), warrant)['effect_verified'])
        self.assertEqual({}, self.gov.inspect(self.p(Capability.READ))['reservations'])
        self.assert_inventory_unchanged()

    def test_zero_non_usd_is_refused_without_consumption_or_target_write(self):
        port, request = self.prepare()
        warrant = self.approve(request, currency='XTS')
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'TARGET_ADOPTION_ZERO_USD_REQUIRED'):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_missing_exact_owner_approval_is_refused(self):
        port, request = self.prepare()
        warrant = self.warrant(request)
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'HUMAN_APPROVAL_REQUIRED'):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_revoked_approval_cannot_register(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        self.ledger.revoke(self.p(Capability.OWNER_APPROVAL), warrant)
        before = self.records()
        with self.assertRaisesRegex(ValueError, 'WARRANT_REVOKED'):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_changed_full_roots_are_refused_before_consumption(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        before = self.records()
        for field in ('state_root', 'resources_root', 'receipts_root'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.adopt(port, request, warrant, current=replace(request, **{field: '0' * 64}))
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_prepared_named_target_cannot_be_reprepared_with_new_incarnation(self):
        self.prepare()
        before = self.records()
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_failure_after_genesis_insert_rolls_back_consumption_and_registration(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        before = self.records()
        insert = TransactionView.insert
        reached = []
        def fail_after_insert(tx, record):
            insert(tx, record)
            if record.record_id == port.genesis_key:
                reached.append(True)
                raise ValueError('AFTER_GENESIS_INSERT')
        with patch.object(TransactionView, 'insert', fail_after_insert), self.assertRaises(MemoryPatchError):
            self.adopt(port, request, warrant)
        self.assertEqual([True], reached)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_lost_commit_ack_retains_registration_and_never_permits_readoption(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        commit = LocalCoreTransaction.commit
        def lose_ack(tx):
            commit(tx)
            raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', lose_ack), self.assertRaises(CommitOutcomeUnknown):
            self.adopt(port, request, warrant)
        self.assertEqual(0, self.head(port)[1]['generation'])
        before = self.records()
        with self.assertRaises(ValueError):
            self.adopt(port, request, warrant)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_missing_registration_never_becomes_a_legacy_genesis_fallback(self):
        port, request = self.prepare()
        self.adopt(port, request, self.approve(request))
        self.delete(port.registration_key)
        before = self.records()
        with self.assertRaises(ValueError):
            self.head(port)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_missing_genesis_does_not_recreate_it_from_remaining_registration(self):
        port, request = self.prepare()
        self.adopt(port, request, self.approve(request))
        self.delete(port.genesis_key)
        before = self.records()
        with self.assertRaises(ValueError):
            self.head(port)
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(before, self.records())

    def test_consumed_stable_named_target_barrier_survives_loss_of_all_projection_rows(self):
        port, request = self.prepare()
        self.adopt(port, request, self.approve(request))
        for identity in (port.registration_key, port.genesis_key, port.head_key):
            self.delete(identity)
        before = self.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_ADOPTION_BARRIER$'):
            self.prepare()
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_adoption_has_no_permission_to_run_under_owner_approval_purpose(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        before = self.records()
        with self.assertRaises(ValueError):
            self.run_tx(lambda tx: port.adopt_existing_in_transaction(tx, warrant, request),
                        Capability.OWNER_APPROVAL)
        self.assertEqual(before, self.records())

    def test_current_stop_and_epoch_are_checked_before_management_consumption(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        self.gov.set_kill(self.p(Capability.MANAGE), True)
        before = self.records()
        with self.assertRaises(ValueError):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.gov.set_kill(self.p(Capability.MANAGE), False)
        self.gov.start_epoch(self.p(Capability.MANAGE))
        before = self.records()
        with self.assertRaises(ValueError):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_transaction_callback_never_reads_or_writes_portable_inventory(self):
        port, request = self.prepare()
        warrant = self.approve(request)
        with self.store.target_guard():
            fresh = self.store.observe_guarded_inventory()
            self.assertEqual(request.state_root, fresh.state_root)
            with (
                patch.object(self.store, 'observe_guarded_inventory', side_effect=AssertionError('IO_IN_SQL')),
                patch.object(self.store, '_write', side_effect=AssertionError('EFFECT_IN_SQL')),
            ):
                self.run_tx(lambda tx: port.adopt_existing_in_transaction(tx, warrant, request))
        self.assertEqual(0, self.head(port)[1]['generation'])
        self.assert_inventory_unchanged()

    def test_new_core_session_cannot_consume_previous_owner_witness(self):
        _port, request = self.prepare()
        warrant = self.approve(request)
        before = self.records()
        foreign = core()
        self.addCleanup(foreign.close)
        factory = LocalCoreRecordFactory(self.path / 'core.sqlite', foreign)
        runner = TransactionRunner(foreign, factory)
        self.addCleanup(runner.close)
        ledger = CoreWarrantLedger(foreign, runner, SCOPE, clock=lambda: self.now)
        governor = CoreDualGovernor(foreign, runner, self.policy, clock=lambda: 100)
        journal = CoreIntentJournal(ledger, governor)
        liability = CoreLiabilityLedger(foreign, runner, SCOPE)
        port = CoreTargetProjection(journal, liability, request.binding)
        context = TransactionContext(foreign.local_operator(Capability.COMMIT), Capability.COMMIT)
        with self.assertRaises(ValueError):
            runner.run(context, lambda tx: port.adopt_existing_in_transaction(tx, warrant, request))
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_missing_adoption_evidence_in_owner_warrant_is_refused(self):
        port, request = self.prepare()
        warrant = replace(self.warrant(request),
                          decision_dependency_root=DecisionDependencyRoot((request.binding.evidence(),)))
        warrant = replace(warrant, approval_digest=approval_digest(warrant))
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), warrant)
        before = self.records()
        with self.assertRaises(ValueError):
            self.adopt(port, request, warrant)
        self.assertEqual(before, self.records())
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def downgrade_projection_fixture(self, port):
        # Controlled, internally consistent corruption of this private fixture.
        # No product writer or real target is used for this attack control.
        import json
        rows = self.run_tx(lambda tx: [tx.get(RecordKind.OPERATION, key)
                           for key in (port.genesis_key, port.head_key)], Capability.READ)
        self.assertEqual([1, 1], [row.revision for row in rows])
        genesis, head = [json.loads(canonical_json_bytes(row.payload)) for row in rows]
        genesis.pop('adoption_digest')
        genesis['schema'] = 'aioa-core-target-genesis.v1'
        digest = canonical_sha256(genesis)
        head.pop('adoption_digest')
        head.update(schema='aioa-core-target-head.v1', genesis_digest=digest, history_digest=digest)
        self.factory.db.execute('BEGIN IMMEDIATE')
        try:
            for row, payload in zip(rows, (genesis, head), strict=True):
                replacement = StoredRecord(row.kind, row.record_id, row.scope, row.revision, payload)
                self.factory.db.execute('UPDATE core_records_v1 SET record_json=?,record_digest=? '
                    'WHERE scope_key=? AND kind=? AND record_id=? AND revision=?',
                    (canonical_record(replacement), replacement.payload_digest,
                     canonical_json_bytes(row.scope.binding()).decode(), row.kind.value, row.record_id, row.revision))
            self.factory.db.commit()
        except BaseException:
            self.factory.db.rollback()
            raise

    def test_joint_legacy_downgrade_is_denied_with_retained_registration(self):
        port, request = self.prepare()
        self.adopt(port, request, self.approve(request))
        self.downgrade_projection_fixture(port)
        before = self.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_ADOPTION_LEGACY_DOWNGRADE$'):
            self.head(port)
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def test_joint_legacy_downgrade_is_denied_after_registration_loss(self):
        port, request = self.prepare()
        self.adopt(port, request, self.approve(request))
        self.downgrade_projection_fixture(port)
        self.delete(port.registration_key)
        before = self.records()
        with self.assertRaisesRegex(ValueError, '^TARGET_ADOPTION_BARRIER$'):
            self.head(port)
        self.assertEqual(before, self.records())
        self.assert_inventory_unchanged()

    def approve_ordinary_warrant(self):
        original = warrant_fixture.WarrantTests().fixture()
        owner = canonical_sha256(SCOPE)
        end = self.now + timedelta(minutes=1)
        warrant = replace(original, owner_scope=owner, issued_at=self.now, expires_at=end,
            lease_epoch=1, nonce='ordinary-existing-warrant',
            authority_scope=replace(original.authority_scope, owner_scope=owner,
                                    not_before=self.now, expires_at=end))
        warrant = replace(warrant, approval_digest=approval_digest(warrant))
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), warrant)
        return warrant

    def test_valid_existing_ordinary_warrant_does_not_block_preparation(self):
        warrant = self.approve_ordinary_warrant()
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        try:
            port, request = self.prepare()
        except WarrantError as error:
            self.fail('Valid existing ordinary warrant blocked preparation: ' + str(error))
        self.assertEqual(port.binding, request.binding)
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), warrant))
        self.assert_inventory_unchanged()

    def test_malformed_existing_warrant_is_still_an_exact_integrity_denial(self):
        warrant = self.approve_ordinary_warrant()
        key = self.ledger._key(warrant)
        witness_before = self.run_tx(lambda tx: canonical_json_bytes(
            tx.get(RecordKind.APPROVAL, key)), Capability.READ)
        def corrupt_owned_operation(tx):
            row = tx.get(RecordKind.OPERATION, key)
            payload = json.loads(canonical_json_bytes(row.payload))
            payload['root'].pop('operation_hash')
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, payload),
                       expected_revision=row.revision)
        # Controlled corruption goes through exact-kind, owner-scoped Core API.
        self.run_tx(corrupt_owned_operation)
        witness_after = self.run_tx(lambda tx: canonical_json_bytes(
            tx.get(RecordKind.APPROVAL, key)), Capability.READ)
        self.assertEqual(witness_before, witness_after)
        before = self.records()
        with self.assertRaisesRegex(WarrantError, '^TARGET_ADOPTION_BARRIER_INTEGRITY$'):
            self.prepare()
        self.assertEqual(before, self.records())
        self.assertEqual(witness_before, self.run_tx(lambda tx: canonical_json_bytes(
            tx.get(RecordKind.APPROVAL, key)), Capability.READ))
        self.assert_inventory_unchanged()
