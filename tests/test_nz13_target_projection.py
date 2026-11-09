"""Same-Core target projection integration, with explicit inert baseline facts.

The baseline codec is not an approval API. These tests seed existing synthetic
state under a fixture owner principal; production registration, physical roots,
Portable release fencing and no-effect certification remain separate gates.
"""

import copy
import importlib
import importlib.util
import json
import unittest
from dataclasses import replace
from unittest.mock import patch

import test_nz13_target_settlement_port as support

from lab.archaioa.outcome import NotApplied
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.tools import CoreToolRoute, TargetSnapshot


class CoreTargetProjectionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.target_projection'),
                             'Same-Core target high-water projection is not implemented')
        self.module = importlib.import_module('runtime.mission.target_projection')
        self.fixture = support.TargetSettlementPortTests(
            'test_fresh_start_and_release_share_existing_journal_and_liability')
        self.addCleanup(self.fixture.doCleanups)
        with patch.object(support, 'FixtureTargetPort', new=self.make_projection):
            self.fixture.setUp()
        self.base, self.port = self.fixture.base, self.fixture.port

    def make_projection(self, base):
        types = importlib.import_module('runtime.mission.target_settlement')
        binding = types.TargetBinding(base.fx.ledger.scope, 'workspace-1', 'fixture-target',
                                      'fixture-incarnation', 'e' * 64)
        port = self.module.CoreTargetProjection(base.fx.journal, base.liability, binding)
        records = port.encode_existing_baseline(
            state_root=base.current.fingerprint.removeprefix('sha256:'),
            target_revision=base.current.revision, resources_root='c' * 64, receipts_root='d' * 64)
        def seed_fixture(tx):
            for record in records:
                tx.insert(record)
        base.fx.runner.run(TransactionContext(base.fx.p(Capability.OWNER_APPROVAL),
                                              Capability.OWNER_APPROVAL), seed_fixture)
        return port

    def head(self):
        return self.base.fx.runner.run(TransactionContext(self.base.fx.p(Capability.READ), Capability.READ),
                                       lambda tx: self.port.load(tx))

    def rewrite_head(self, transform):
        def change(tx):
            row = tx.get(RecordKind.OPERATION, self.port.head_key)
            state = json.loads(support.canonical_json_bytes(row.payload))
            replacement = transform(state)
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, replacement),
                       expected_revision=row.revision)
        self.base.fx.runner.run(TransactionContext(self.base.fx.p(), Capability.COMMIT), change)

    def raw_row(self, record_id):
        matches = [row for row in json.loads(self.base.path.read_text())
                   if json.loads(row[0])['record_id'] == record_id
                   and json.loads(row[0])['kind'] == RecordKind.OPERATION.value]
        self.assertEqual(1, len(matches))
        return matches[0]

    def remove_fixture_record(self, record_id):
        # Controlled corruption of this test's private durable fixture only.
        rows = json.loads(self.base.path.read_text())
        kept = [row for row in rows if not (json.loads(row[0])['record_id'] == record_id
                    and json.loads(row[0])['kind'] == RecordKind.OPERATION.value)]
        self.assertEqual(len(rows) - 1, len(kept))
        self.base.path.write_text(json.dumps(kept, sort_keys=True, separators=(',', ':')))

    def require_unknown(self):
        self.assertEqual('Unknown', self.base.fx.journal.inspect(
            self.base.fx.p(Capability.READ), self.base.warrant)['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))

    def require_no_new_effect(self):
        before = self.base.path.read_bytes()
        with self.assertRaises(ValueError):
            self.base.dispatch()
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual([], self.base.calls)

    def test_start_release_ack_are_facts_in_existing_core(self):
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        row, state = self.head()
        self.assertEqual(4, row.revision)
        self.assertEqual(0, state['generation'])
        self.assertEqual('RELEASED', state['in_flight']['phase'])
        self.assertEqual(self.base.warrant.digest(), state['in_flight']['warrant_digest'])
        self.assertIsNotNone(state['in_flight']['ack'])
        self.assertIs(self.port.runner, self.base.liability.runner)
        self.require_unknown()

    def test_settlement_advances_history_journal_and_liability_together(self):
        self.base.dispatch()
        self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        row, state = self.head()
        self.assertEqual(5, row.revision)
        self.assertEqual(1, state['generation'])
        self.assertIsNone(state['in_flight'])
        self.assertEqual('CLOSED', self.base.liability.inspect(
            self.base.fx.p(Capability.READ), self.base.binding.task_id)[0].status.value)
        self.assertEqual(self.base.warrant.digest(), json.loads(
            self.raw_row(self.port.history_key(self.base.warrant))[0])['payload']['warrant_digest'])

    def test_failure_after_journal_write_rolls_back_real_history_and_head(self):
        self.base.dispatch()
        before = self.base.path.read_bytes()
        apply = self.base.fx.journal.apply_resolution_in_transaction
        def fail(*args):
            apply(*args)
            raise ValueError('AFTER_JOURNAL_BEFORE_COMMIT')
        with (patch.object(self.base.fx.journal, 'apply_resolution_in_transaction', side_effect=fail),
              self.assertRaises(MemoryPatchError) as failure):
            self.fixture.reconcile()
        self.assertIsInstance(failure.exception.__cause__, ValueError)
        self.assertEqual('AFTER_JOURNAL_BEFORE_COMMIT', str(failure.exception.__cause__))
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(0, self.head()[1]['generation'])
        self.require_unknown()

    def test_failure_after_target_head_write_rolls_back_history_insert(self):
        self.base.dispatch()
        before = self.base.path.read_bytes()
        save = self.port._save_head
        def fail(tx, row, state):
            save(tx, row, state)
            if state['generation'] == 1:
                raise ValueError('AFTER_HEAD_BEFORE_LIABILITY')
        with patch.object(self.port, '_save_head', side_effect=fail), self.assertRaises(MemoryPatchError) as failure:
            self.fixture.reconcile()
        self.assertIsInstance(failure.exception.__cause__, ValueError)
        self.assertEqual('AFTER_HEAD_BEFORE_LIABILITY', str(failure.exception.__cause__))
        self.assertEqual(before, self.base.path.read_bytes())
        self.require_unknown()

    def test_lost_settlement_ack_reads_committed_generation_without_new_attempt(self):
        self.base.dispatch()
        commit = support.legacy.DurableTransaction.commit
        lost = []
        def lose_ack(tx):
            settled = any(row.record_id == self.port.head_key and row.payload.get('generation') == 1
                          for row in tx.snapshot.values())
            commit(tx)
            if settled and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        with patch.object(support.legacy.DurableTransaction, 'commit', new=lose_ack), self.assertRaises(CommitOutcomeUnknown):
            self.fixture.reconcile()
        before = self.base.path.read_bytes()
        with patch.object(self.base.route, 'verifier', side_effect=AssertionError('NO_NEW_OBSERVATION')):
            self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(1, self.head()[1]['generation'])
        self.assertEqual(1, len(self.base.calls))

    def test_serialization_retry_reuses_one_proof_and_one_generation(self):
        self.base.dispatch()
        commit = support.legacy.DurableTransaction.commit
        retried = []
        class Retry(Exception):
            sqlstate = '40001'
        def retry(tx):
            if not retried and any(row.record_id == self.port.head_key and row.payload.get('generation') == 1
                                   for row in tx.snapshot.values()):
                retried.append(True)
                raise Retry()
            return commit(tx)
        with (patch.object(support.legacy.DurableTransaction, 'commit', new=retry),
              patch.object(self.port, 'apply_resolution_in_transaction', wraps=self.port.apply_resolution_in_transaction) as settle):
            self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        self.assertEqual(2, settle.call_count)
        self.assertIs(settle.call_args_list[0].args[-1], settle.call_args_list[1].args[-1])
        self.assertEqual(1, self.head()[1]['generation'])
        self.assertEqual(1, len(self.base.calls))

    def test_changed_state_root_cannot_start(self):
        self.rewrite_head(lambda state: {**state, 'state_root': '0' * 64})
        self.require_no_new_effect()

    def test_changed_untouched_resources_root_cannot_start(self):
        self.rewrite_head(lambda state: {**state, 'resources_root': '0' * 64})
        self.require_no_new_effect()

    def test_changed_all_receipts_root_cannot_start(self):
        self.rewrite_head(lambda state: {**state, 'receipts_root': '0' * 64})
        self.require_no_new_effect()

    def test_missing_genesis_is_not_lazily_recreated(self):
        self.remove_fixture_record(self.port.genesis_key)
        self.require_no_new_effect()

    def test_missing_head_is_not_lazily_recreated(self):
        self.remove_fixture_record(self.port.head_key)
        self.require_no_new_effect()

    def test_missing_settled_history_denies_all_resolved_early_returns(self):
        self.base.dispatch()
        self.fixture.reconcile()
        self.remove_fixture_record(self.port.history_key(self.base.warrant))
        for operation in ('inspect', 'dispatch', 'reconcile'):
            before = self.base.path.read_bytes()
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                if operation == 'inspect':
                    self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)
                elif operation == 'dispatch':
                    self.base.dispatch()
                else:
                    self.fixture.reconcile()
            self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(1, len(self.base.calls))

    def test_orphan_forked_history_is_not_ignored(self):
        self.base.dispatch()
        self.fixture.reconcile()
        raw = json.loads(self.raw_row(self.port.history_key(self.base.warrant))[0])
        def insert(tx):
            tx.insert(StoredRecord(RecordKind.OPERATION, canonical_sha256('orphan-history'), self.port.scope, 1, raw['payload']))
        self.base.fx.runner.run(TransactionContext(self.base.fx.p(), Capability.COMMIT), insert)
        with self.assertRaises(ValueError):
            self.fixture.reconcile()
        self.assertEqual(1, len(self.base.calls))

    def test_replayed_old_head_cannot_hide_retained_history(self):
        original = self.raw_row(self.port.head_key)
        self.base.dispatch()
        self.fixture.reconcile()
        rows = json.loads(self.base.path.read_text())
        self.base.path.write_text(json.dumps([original if json.loads(row[0])['record_id'] == self.port.head_key
                                               else row for row in rows], sort_keys=True, separators=(',', ':')))
        with self.assertRaises(ValueError):
            self.fixture.reconcile()
        self.assertEqual(1, len(self.base.calls))

    def test_boolean_generation_is_not_revision_zero_or_one(self):
        self.rewrite_head(lambda state: {**state, 'generation': True})
        self.require_no_new_effect()

    def test_foreign_incarnation_cannot_read_or_adopt_same_named_target(self):
        port = self.module.CoreTargetProjection(self.base.fx.journal, self.base.liability,
                                               replace(self.port.binding, incarnation='another-incarnation'))
        with self.assertRaises(ValueError):
            self.base.fx.runner.run(TransactionContext(self.base.fx.p(Capability.READ), Capability.READ),
                                    lambda tx: port.load(tx))
        self.assertEqual([], self.base.calls)

    def test_projection_constructor_rejects_another_runner(self):
        liability = copy.copy(self.base.liability)
        liability.runner = object()
        with self.assertRaises(ValueError):
            self.module.CoreTargetProjection(self.base.fx.journal, liability, self.port.binding)

    def test_late_ack_makes_a_previously_valid_observation_stale(self):
        self.base.route.executor = self.base.execute  # Explicit missing ACK, effect still runs once.
        self.base.dispatch()
        verify = self.fixture.verify
        def observe(operation, warrant):
            proof = verify(operation, warrant)
            ack = self.fixture.types.TargetExecutionAck(warrant.operation_hash, warrant.digest(),
                self.port.binding.digest(), canonical_sha256(self.base.effects), 'late-ack', 'f' * 64)
            self.base.fx.runner.run(TransactionContext(self.base.fx.p(), Capability.COMMIT),
                                    lambda tx: self.port.record_ack_in_transaction(tx, warrant, ack))
            return proof
        self.base.route.verifier = observe
        with self.assertRaises(ValueError):
            self.fixture.reconcile()
        self.require_unknown()
        self.assertEqual(0, self.head()[1]['generation'])

    def test_executor_ack_root_mismatch_cannot_settle(self):
        self.base.dispatch()
        verify = self.fixture.verify
        def foreign(operation, warrant):
            proof = verify(operation, warrant)
            return replace(proof, target=replace(proof.target, after_root='f' * 64))
        self.base.route.verifier = foreign
        with self.assertRaises(ValueError):
            self.fixture.reconcile()
        self.require_unknown()

    def test_owned_independent_receipt_can_settle_when_executor_ack_is_missing(self):
        self.base.route.executor = self.base.execute
        self.base.dispatch()
        self.assertIsNone(self.head()[1]['in_flight']['ack'])
        self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        self.assertEqual(1, self.head()[1]['generation'])
        self.assertEqual(1, len(self.base.calls))

    def test_history_scan_quota_cannot_be_pruned_to_success(self):
        def fill(tx):
            for index in range(1024):
                tx.insert(StoredRecord(RecordKind.OPERATION, canonical_sha256(('quota', index)),
                                       self.port.scope, 1, {'schema': 'fixture-unused'}))
        self.base.fx.runner.run(TransactionContext(self.base.fx.p(), Capability.COMMIT), fill)
        self.require_no_new_effect()

    def test_projection_load_is_read_only(self):
        before = self.base.path.read_bytes()
        self.assertEqual(0, self.head()[1]['generation'])
        self.assertEqual(before, self.base.path.read_bytes())

    def test_missing_old_liability_cannot_return_a_settled_success(self):
        self.base.dispatch()
        self.fixture.reconcile()
        self.remove_fixture_record(self.base.liability._key(self.base.binding.task_id))
        with self.assertRaises(ValueError):
            self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)
        self.assertEqual(1, len(self.base.calls))

    def test_missing_old_intent_cannot_return_a_settled_success(self):
        self.base.dispatch()
        self.fixture.reconcile()
        self.remove_fixture_record(self.base.fx.journal._key(self.base.warrant))
        with self.assertRaises(ValueError):
            self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)
        self.assertEqual(1, len(self.base.calls))

    def test_not_applied_after_release_never_follows_from_missing_receipt(self):
        self.base.dispatch()
        proof = self.fixture.verify(self.base.operation, self.base.warrant)
        certificate = replace(proof.resolution.receipt, kind='no-effect-certificate')
        resolution = replace(proof.resolution, outcome=NotApplied(), receipt=certificate)
        self.base.route.verifier = lambda operation, warrant: replace(proof, resolution=resolution)
        with self.assertRaises(ValueError):
            self.fixture.reconcile()
        self.require_unknown()

    def test_old_settlement_replay_after_later_generation_does_not_rewind_or_probe(self):
        self.base.dispatch()
        self.fixture.reconcile()
        old_warrant, old_request, old_grant, old_binding, old_operation = (
            self.base.warrant, self.base.request, self.base.grant, self.base.binding,
            copy.deepcopy(self.base.operation))
        state = self.head()[1]
        self.base.current = TargetSnapshot('sha256:' + state['state_root'], state['target_revision'],
                                           self.base.current.ddr)
        self.base.operation = self.base.route.operation(
            {'action': 'write_file', 'path': 'src/later.py', 'content': 'print(2)\n'}, self.base.current)
        exact = importlib.import_module('test_nz13_exact_mock_authority')
        owner = exact.ExactMockAuthorityTests(
            'test_exact_owner_witness_precedes_unknown_one_attempt_and_independent_readback')
        owner.case, owner.fx = self.base, self.base.fx
        owner.strict()
        self.base.route = CoreToolRoute(
            self.base.fx.journal, self.base.liability, workspace='workspace-1', policy_revision=3,
            probe=lambda: self.base.current, executor=self.fixture.execute,
            target_guard=lambda: self.base.lifecycle, verifier=self.fixture.verify,
            clock=lambda: self.base.now, target_settlement=self.port)
        # Two 1-unit advisory jobs plus 50 and 40 stay below the unchanged100 ceiling.
        self.base.warrant = self.base.route.authorize_exact(self.base.fx.p(Capability.OWNER_APPROVAL),
            self.base.grant.session_id, self.base.operation, self.base.binding, self.base.graph,
            self.base.trace, nonce='later-generation', model_id=support.legacy.MODEL, money_nano=40, risk_units=5)
        self.base.request = support.legacy.ReservationRequest(self.base.warrant.money_reservation_id,
            self.base.binding.task_id, 'synthetic', support.legacy.MODEL, canonical_sha256(self.base.operation),40,5)
        verify = self.fixture.verify
        def current_generation(operation, warrant):
            proof = verify(operation, warrant)
            return replace(proof, target=replace(proof.target, generation=self.head()[1]['generation']))
        self.base.route.verifier = current_generation
        self.base.dispatch()
        self.fixture.reconcile()
        self.assertEqual(2, self.head()[1]['generation'])
        before = self.base.path.read_bytes()
        with patch.object(self.base.route, 'probe', side_effect=AssertionError('NO_NEW_PROBE')):
            self.assertEqual('Applied', self.base.route.dispatch(self.base.fx.p(),
                session_id=old_grant.session_id, warrant=old_warrant, operation=old_operation,
                reservation=old_request, completion=old_binding)['outcome']['contract_type'])
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(2, self.head()[1]['generation'])
        self.assertEqual(2, len(self.base.calls))

    def direct_start_must_deny(self, route, nonce):
        warrant = route.authorize(self.base.fx.p(), self.base.grant.session_id,
            self.base.operation, self.base.binding, self.base.graph, self.base.trace,
            nonce=nonce, model_id=support.legacy.MODEL, money_nano=50, risk_units=5)
        reservation = support.legacy.ReservationRequest(warrant.money_reservation_id,
            self.base.binding.task_id, 'synthetic', support.legacy.MODEL,
            canonical_sha256(self.base.operation), 50, 5)
        snapshot = replace(self.base.current, ddr=support.legacy.DecisionDependencyRoot(
            self.base.current.ddr.evidence_refs + (self.port.binding.evidence(),)))
        def start(tx):
            self.base.fx.journal.start_in_transaction(tx, warrant, self.base.operation, reservation)
            self.port.start_in_transaction(tx, warrant, self.base.operation, snapshot)
            self.base.liability.record_unknown_in_transaction(tx, self.base.trace, self.base.graph, warrant.issued_at)
        before = self.base.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'TARGET_WARRANT_BINDING_REQUIRED'):
            self.base.fx.runner.run(TransactionContext(self.base.fx.p(), Capability.COMMIT), start)
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual([], self.base.calls)
        self.assertIsNone(self.head()[1]['in_flight'])

    def test_direct_hook_rejects_legacy_warrant_even_with_bound_snapshot(self):
        self.direct_start_must_deny(self.fixture.new_route(None), 'legacy-direct-hook')

    def test_direct_hook_rejects_warrant_approved_for_another_named_target(self):
        other = self.module.CoreTargetProjection(self.base.fx.journal, self.base.liability,
                                                 replace(self.port.binding, target_id='another-target'))
        self.direct_start_must_deny(self.fixture.new_route(other), 'foreign-direct-hook')
