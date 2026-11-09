"""Atomic extension of the existing Core route; synthetic target facts only.

This does not certify a Portable adapter, INIT, STOP or physical target fencing.
"""
import copy
import importlib
import importlib.util
import inspect
import json
import unittest
from dataclasses import fields as dataclass_fields
from dataclasses import replace
from unittest.mock import patch

import test_core_tool_composition as legacy

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.mission.warrant import WarrantError, require


class FixtureTargetPort:
    """DB-only instrumented test port, not a physical target implementation."""
    profile = 'aioa.target-settlement.v1'

    def __init__(self, base):
        self.base = base
        self.core, self.runner, self.scope = base.fx.core, base.fx.runner, base.fx.ledger.scope
        self.workspace, self.target_id = 'workspace-1', 'fixture-target'
        self.types = importlib.import_module('runtime.mission.target_settlement')
        self.binding = self.types.TargetBinding(self.scope, self.workspace, self.target_id,
                                               'fixture-incarnation', 'e' * 64)
        self.reject_ack = False
        self.key = canonical_sha256(('test-target-fact', self.scope, self.workspace, self.target_id))
        self.reject_start = self.reject_release = self.reject_settlement = self.reject_history = False

    def load(self, tx):
        row = tx.get(RecordKind.OPERATION, self.key)
        require(row is not None, 'TARGET_FACT_REQUIRED')
        return row, json.loads(canonical_json_bytes(row.payload))

    def save(self, tx, row, payload):
        record = StoredRecord(RecordKind.OPERATION, self.key, self.scope, 1 if row is None else row.revision + 1, payload)
        if row is None:
            tx.insert(record)
        else:
            tx.replace(record, expected_revision=row.revision)

    def start_in_transaction(self, tx, warrant, operation, snapshot):
        require(not self.reject_start, 'TARGET_START_DENIED')
        require(tx.get(RecordKind.OPERATION, self.key) is None, 'TARGET_IN_FLIGHT')
        self.save(tx, None, {'schema': 'fixture-target-fact.v1', 'state': 'STARTED',
                            'warrant_digest': warrant.digest(), 'generation': 0, 'resolution': None})

    def before_release_in_transaction(self, tx, warrant, operation, snapshot):
        row, state = self.load(tx)
        require(not self.reject_release and state['state'] == 'STARTED'
                and state['warrant_digest'] == warrant.digest(), 'TARGET_RELEASE_DENIED')
        state['state'] = 'RELEASED'
        self.save(tx, row, state)

    def record_ack_in_transaction(self, tx, warrant, acknowledgment):
        self.binding.require_ack(warrant, acknowledgment)
        row, state = self.load(tx)
        require(state['state'] == 'RELEASED' and state['warrant_digest'] == warrant.digest(), 'TARGET_ACK_PHASE')
        state['ack'] = acknowledgment.to_dict()
        self.save(tx, row, state)
        require(not self.reject_ack, 'TARGET_ACK_DENIED_AFTER_WRITE')

    def apply_resolution_in_transaction(self, tx, warrant, epoch, verified):
        row, state = self.load(tx)
        target = verified.target
        require(state['state'] == 'RELEASED' and state['warrant_digest'] == warrant.digest(), 'TARGET_START_BINDING')
        require(target.scope == self.scope and target.workspace == self.workspace
                and target.target_id == self.target_id and target.incarnation == 'fixture-incarnation'
                and target.operation_digest == warrant.operation_hash
                and target.expected_head_revision == row.revision and target.generation == state['generation']
                and target.before_root == warrant.target_fingerprint.removeprefix('sha256:'), 'TARGET_PROOF_BINDING')
        state.update(state='RESOLVED', generation=state['generation'] + 1,
                     resolution=verified.resolution.to_dict())
        self.save(tx, row, state)
        require(not self.reject_settlement, 'TARGET_SETTLEMENT_DENIED_AFTER_WRITE')

    def check_history_in_transaction(self, tx, warrant, intent):
        _row, state = self.load(tx)
        require(not self.reject_history and state['warrant_digest'] == warrant.digest(), 'TARGET_HISTORY_REQUIRED')
        if intent['resolution'] is not None:
            require(state['state'] == 'RESOLVED' and state['resolution'] == intent['resolution'], 'TARGET_HISTORY_REQUIRED')


class TargetSettlementPortTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime.mission.target_settlement'),
                             'Typed same-Core target settlement port is not implemented')
        self.types = importlib.import_module('runtime.mission.target_settlement')
        from runtime.mission.tools import CoreToolRoute
        self.route_type = CoreToolRoute
        self.assertIn('target_settlement', inspect.signature(CoreToolRoute).parameters)
        self.base = legacy.CoreToolCompositionTests('test_real_synthetic_attempt_opens_required_g2_and_holds_exposure')
        self.addCleanup(self.base.doCleanups)
        # Install the typed route before the fixture's real initial authorization.
        # Two nonce aliases for the same task/operation are separate warrants but
        # share the journal key; creating both would mask the pending barrier
        # with the existing fail-closed INTENT_BINDING check during accounting.
        authorize = self.base.authorize
        def initial_authorize(nonce='target-bound-nonce'):
            self.port = FixtureTargetPort(self.base)
            self.base.route = self.new_route(self.port)
            return authorize(nonce)
        self.base.authorize = initial_authorize
        self.base.setUp()
        self.base.authorize = authorize

    def new_route(self, port):
        return self.route_type(self.base.fx.journal, self.base.liability, workspace='workspace-1',
            policy_revision=1, probe=lambda: self.base.current, executor=self.execute,
            target_guard=lambda: self.base.lifecycle, verifier=self.verify,
            clock=lambda: self.base.now, target_settlement=port)

    def execute(self, operation, warrant, limits=None):
        self.base.execute(operation, warrant, limits)
        root = canonical_sha256(self.base.effects)
        return self.types.TargetExecutionAck(warrant.operation_hash, warrant.digest(), self.port.binding.digest(),
            root, 'fixture-write-ack', canonical_sha256({'nonce': warrant.nonce, 'root': root}))

    def verify(self, operation, warrant):
        resolution = self.base.verify(operation, warrant)
        if resolution is None:
            return None
        observation = self.types.TargetObservation(
            scope=self.port.scope, workspace=self.port.workspace, target_id=self.port.target_id,
            incarnation='fixture-incarnation', expected_head_revision=self.fact()[0].revision, generation=0,
            operation_digest=warrant.operation_hash,
            before_root=warrant.target_fingerprint.removeprefix('sha256:'),
            after_root=canonical_sha256(self.base.effects), resources_root='c' * 64,
            receipts_root='d' * 64, guard_fingerprint='e' * 64,
            receipt_id=resolution.receipt.evidence_id,
            receipt_digest=resolution.receipt.digest.removeprefix('sha256:'),
            readback_digest=resolution.readback.digest.removeprefix('sha256:'))
        return self.types.VerifiedTargetSettlement(resolution, observation)

    def fact(self):
        return self.base.fx.runner.run(TransactionContext(self.base.fx.p(Capability.READ), Capability.READ),
                                       lambda tx: self.port.load(tx))

    def reconcile(self):
        return self.base.route.reconcile(self.base.fx.p(), self.base.warrant, 1)

    def test_fresh_start_and_release_share_existing_journal_and_liability(self):
        result = self.base.dispatch()
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual('RELEASED', self.fact()[1]['state'])
        self.assertEqual('OPEN', self.base.liability.inspect(self.base.fx.p(Capability.READ), 'tool-task')[0].status.value)
        self.assertEqual(1, len(self.base.calls))

    def test_target_start_denial_rolls_back_warrant_journal_and_liability(self):
        before = self.base.path.read_bytes()
        self.port.reject_start = True
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.base.dispatch()
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual([], self.base.calls)
        self.assertIsNone(self.base.fx.ledger.inspect(self.base.fx.p(Capability.READ), self.base.warrant))

    def test_release_denial_holds_unknown_and_never_calls_target(self):
        self.port.reject_release = True
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.base.dispatch()
        self.assertEqual('STARTED', self.fact()[1]['state'])
        self.assertEqual([], self.base.calls)
        self.assertEqual('Unknown', self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)['outcome']['contract_type'])

    def test_full_typed_observation_settles_existing_core_records_together(self):
        self.base.dispatch()
        self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])
        self.assertEqual(('RESOLVED', 1), (self.fact()[1]['state'], self.fact()[1]['generation']))
        self.assertEqual('CLOSED', self.base.liability.inspect(self.base.fx.p(Capability.READ), 'tool-task')[0].status.value)
        self.assertEqual(1, len(self.base.calls))

    def test_failure_after_target_fact_write_rolls_back_entire_settlement(self):
        self.base.dispatch()
        before = self.base.path.read_bytes()
        self.port.reject_settlement = True
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.reconcile()
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual('RELEASED', self.fact()[1]['state'])
        self.assertEqual(1, len(self.base.calls))

    def test_failure_after_journal_write_also_rolls_back_target_and_liability(self):
        self.base.dispatch()
        before = self.base.path.read_bytes()
        original = self.base.fx.journal.apply_resolution_in_transaction
        def fail_after(*positional, **keywords):
            original(*positional, **keywords)
            raise WarrantError('INJECTED_AFTER_JOURNAL_WRITE')
        with (patch.object(self.base.fx.journal, 'apply_resolution_in_transaction', side_effect=fail_after),
              self.assertRaises((MemoryPatchError, ValueError))):
            self.reconcile()
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual('RELEASED', self.fact()[1]['state'])

    def test_reconciliation_can_repair_fact_failure_without_repeating_effect(self):
        self.base.dispatch()
        self.port.reject_settlement = True
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.reconcile()
        self.port.reject_settlement = False
        self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))

    def test_committed_settlement_lost_ack_is_read_back_without_new_attempt(self):
        self.base.dispatch()
        original = legacy.DurableTransaction.commit
        injected = []
        target_key = self.port.key
        def lose_ack(transaction):
            is_settlement = any(record.record_id == target_key and record.payload.get('state') == 'RESOLVED'
                                for record in transaction.snapshot.values())
            original(transaction)
            if is_settlement and not injected:
                injected.append(True)
                raise CommitOutcomeUnknown()
        with (patch.object(legacy.DurableTransaction, 'commit', new=lose_ack),
              self.assertRaises(CommitOutcomeUnknown)):
            self.reconcile()
        self.assertEqual([True], injected)
        self.assertEqual('RESOLVED', self.fact()[1]['state'])
        self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))
        self.assertEqual(1, len(self.base.verifications))

    def test_serialization_retry_reuses_one_observation_and_never_repeats_target(self):
        self.base.dispatch()
        original = legacy.DurableTransaction.commit
        injected = []
        target_key = self.port.key
        class SerializationFailure(Exception):
            sqlstate = '40001'
        def retry_once(transaction):
            is_settlement = any(record.record_id == target_key and record.payload.get('state') == 'RESOLVED'
                                for record in transaction.snapshot.values())
            if is_settlement and not injected:
                injected.append(True)
                raise SerializationFailure()
            return original(transaction)
        with patch.object(legacy.DurableTransaction, 'commit', new=retry_once), patch.object(
                self.port, 'apply_resolution_in_transaction', wraps=self.port.apply_resolution_in_transaction) as settle:
            self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])
        self.assertEqual(2, settle.call_count)
        self.assertIs(settle.call_args_list[0].args[-1], settle.call_args_list[1].args[-1])
        self.assertEqual(1, self.fact()[1]['generation'])
        self.assertEqual(1, len(self.base.calls))
        self.assertEqual(1, len(self.base.verifications))

    def test_resolved_replay_reads_history_without_verifier_or_execution(self):
        self.base.dispatch()
        self.reconcile()
        before = self.base.path.read_bytes()
        count = len(self.base.verifications)
        self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(count, len(self.base.verifications))
        self.assertEqual(1, len(self.base.calls))

    def test_resolved_history_denial_cannot_return_applied(self):
        self.base.dispatch()
        self.reconcile()
        self.port.reject_history = True
        for read in (self.reconcile,
                     lambda: self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant),
                     self.base.dispatch):
            with self.subTest(read=read.__name__), self.assertRaises((MemoryPatchError, ValueError)):
                read()
        self.assertEqual(1, len(self.base.calls))

    def test_plain_reconciliation_cannot_replace_complete_target_observation(self):
        self.base.dispatch()
        self.base.route.verifier = self.base.verify
        before = self.base.path.read_bytes()
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.reconcile()
        self.assertEqual(before, self.base.path.read_bytes())

    def test_foreign_target_observation_is_denied_without_settlement(self):
        self.base.dispatch()
        original = self.base.route.verifier
        def foreign(operation, warrant):
            verified = original(operation, warrant)
            return self.types.VerifiedTargetSettlement(verified.resolution, replace(verified.target, target_id='foreign-target'))
        self.base.route.verifier = foreign
        before = self.base.path.read_bytes()
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.reconcile()
        self.assertEqual(before, self.base.path.read_bytes())

    def test_target_core_runner_scope_and_workspace_must_match_existing_route(self):
        for field, value in (('core', object()), ('runner', object()), ('scope', object()), ('workspace', 'foreign-workspace')):
            with self.subTest(field=field):
                port = copy.copy(self.port)
                setattr(port, field, value)
                with self.assertRaises(ValueError):
                    self.new_route(port)

    def test_binding_drift_is_rechecked_before_new_core_transaction(self):
        self.port.workspace = 'foreign-workspace'
        before = self.base.path.read_bytes()
        with self.assertRaises((MemoryPatchError, ValueError)):
            self.base.dispatch()
        self.assertEqual([], self.base.calls)
        self.assertEqual(before, self.base.path.read_bytes())

    def test_incomplete_host_port_is_denied_at_construction(self):
        with self.assertRaises(ValueError):
            self.new_route(object())

    def test_immutable_observation_rejects_boolean_or_negative_revisions(self):
        self.base.dispatch()
        observed = self.verify(self.base.operation, self.base.warrant).target
        for fields in ({'expected_head_revision': True}, {'generation': True},
                       {'expected_head_revision': 0}, {'generation': -1}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(observed, **fields)

    def test_inconsistent_receipt_or_readback_digest_cannot_form_verified_envelope(self):
        self.base.dispatch()
        observed = self.verify(self.base.operation, self.base.warrant)
        for fields in ({'receipt_digest': '0' * 64}, {'readback_digest': '0' * 64}, {'receipt_id': 'foreign-receipt'}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.types.VerifiedTargetSettlement(observed.resolution, replace(observed.target, **fields))

    def test_verified_observation_is_immutable_and_contains_no_mutable_collections(self):
        self.base.dispatch()
        observed = self.verify(self.base.operation, self.base.warrant)
        with self.assertRaises((AttributeError, TypeError)):
            observed.target.after_root = '0' * 64
        values = [getattr(observed.target, field.name) for field in dataclass_fields(observed.target)]
        self.assertTrue(all(isinstance(value, (str, int)) or value is self.port.scope for value in values))

    def test_committed_start_lost_ack_keeps_barrier_without_target_attempt(self):
        original = legacy.DurableTransaction.commit
        injected = []
        target_key = self.port.key
        def lose_start_ack(transaction):
            is_start = any(record.record_id == target_key and record.payload.get('state') == 'STARTED'
                           for record in transaction.snapshot.values())
            original(transaction)
            if is_start and not injected:
                injected.append(True)
                raise CommitOutcomeUnknown()
        with (patch.object(legacy.DurableTransaction, 'commit', new=lose_start_ack),
              self.assertRaises(CommitOutcomeUnknown)):
            self.base.dispatch()
        self.assertEqual('STARTED', self.fact()[1]['state'])
        self.assertEqual([], self.base.calls)
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual([], self.base.calls)

    def test_different_task_cannot_pass_pending_barrier_after_target_rewind(self):
        from runtime.mission.job_contracts import JobEnvelope
        from runtime.providers.nvidia import ProviderRequest
        self.base.dispatch()
        self.base.effects.clear()  # Controlled target/receipt rollback before Core settlement.
        operation = self.base.route.operation({'action': 'write_file', 'path': 'src/other.py',
                                               'content': 'print(2)\n'}, self.base.current)
        trace = legacy.FaultTrace(legacy.FaultKind.LOST_ACK, 'other-task', 'other-request',
                                  'sha256:' + canonical_sha256(operation))
        identity = legacy.classify_fault(trace).liability_id
        graph = legacy.DependencyGraph('other-task', (
            legacy.DependencyNode('effect', legacy.NodeKind.OPERATION, liability_ids=(identity,)),
            legacy.DependencyNode('completion', legacy.NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        binding = legacy.TaskCompletionBinding.for_graph(self.port.scope, graph, 'completion')
        self.base.liability.initialize(self.base.fx.p(), graph)
        request = ProviderRequest('other-advisory', 'other-trace', 'nebius', legacy.MODEL,
                                  'fixture metadata only', 'other-budget', 128, 20)
        envelope = JobEnvelope.from_request(self.port.scope, 'other-task', request,
                                            deadline_at=160, money_nano=1, risk_units=0)
        self.base.fx.gov.submit_job(self.base.fx.p(Capability.MANAGE), envelope, completion=binding)
        claim = self.base.fx.gov.claim_job(self.base.fx.p(), 'other-task', 'fixture-worker', 1, lease_seconds=30)
        self.base.fx.gov.begin_job(self.base.fx.p(), claim)
        grant = replace(self.base.grant, session_id='other-session', completion_digest=binding.digest)
        self.base.route.create_session(self.base.fx.p(Capability.OWNER_APPROVAL), grant)
        warrant = self.base.route.authorize(self.base.fx.p(), grant.session_id, operation, binding, graph,
            trace, nonce='other-nonce', model_id=legacy.MODEL, money_nano=10, risk_units=5)
        reservation = legacy.ReservationRequest(warrant.money_reservation_id, 'other-task', 'synthetic',
            legacy.MODEL, canonical_sha256(operation), 10, 5)
        before = self.base.path.read_bytes()
        with (patch.object(self.port, 'start_in_transaction', wraps=self.port.start_in_transaction) as begin,
              self.assertRaisesRegex(ValueError, 'UNRESOLVED_INTENT')):
            self.base.route.dispatch(self.base.fx.p(), session_id=grant.session_id, warrant=warrant,
                operation=operation, reservation=reservation, completion=binding)
        self.assertEqual(0, begin.call_count, 'Existing journal/governor barrier must decide before the target hook')
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(1, len(self.base.calls))
        self.assertEqual({}, self.base.effects)
        self.assertIsNone(self.base.fx.ledger.inspect(self.base.fx.p(Capability.READ), warrant))

    def test_plain_none_route_cannot_reconcile_port_bound_unknown(self):
        self.base.dispatch()
        unbound = self.new_route(None)
        unbound.verifier = self.base.verify
        before = self.base.path.read_bytes()
        with self.assertRaises(ValueError):
            unbound.reconcile(self.base.fx.p(), self.base.warrant, 1)
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual('RELEASED', self.fact()[1]['state'])

    def test_plain_none_route_cannot_bypass_resolved_target_history(self):
        self.base.dispatch()
        self.reconcile()
        self.port.reject_history = True
        unbound = self.new_route(None)
        for read in (lambda: unbound.inspect(self.base.fx.p(Capability.READ), self.base.warrant),
                     lambda: unbound.dispatch(self.base.fx.p(), session_id=self.base.grant.session_id,
                        warrant=self.base.warrant, operation=self.base.operation,
                        reservation=self.base.request, completion=self.base.binding)):
            with self.subTest(read=read.__name__), self.assertRaises(ValueError):
                read()

    def test_successful_executor_ack_is_recorded_as_fact_while_intent_remains_unknown(self):
        result = self.base.dispatch()
        state = self.fact()[1]
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertIn('ack', state)
        self.assertEqual(self.base.warrant.digest(), state['ack']['warrant_digest'])
        self.assertEqual(self.port.binding.digest(), state['ack']['binding_digest'])
        self.assertEqual(1, len(self.base.calls))

    def test_ack_write_failure_rolls_back_ack_fact_without_repeating_target(self):
        self.port.reject_ack = True
        with patch.object(self.port, 'record_ack_in_transaction', wraps=self.port.record_ack_in_transaction) as record:
            result = self.base.dispatch()
        self.assertEqual(1, record.call_count)
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertNotIn('ack', self.fact()[1])
        self.assertEqual('RELEASED', self.fact()[1]['state'])
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))

    def test_ack_commit_lost_ack_is_retained_without_another_target_attempt(self):
        original = legacy.DurableTransaction.commit
        injected = []
        target_key = self.port.key
        def lose_ack(transaction):
            is_ack = any(record.record_id == target_key and 'ack' in record.payload
                         and record.payload.get('state') != 'RESOLVED' for record in transaction.snapshot.values())
            original(transaction)
            if is_ack and not injected:
                injected.append(True)
                raise CommitOutcomeUnknown()
        with patch.object(legacy.DurableTransaction, 'commit', new=lose_ack):
            self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual([True], injected)
        self.assertIn('ack', self.fact()[1])
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))

    def test_ack_serialization_retry_uses_one_immutable_ack_without_target_retry(self):
        original = legacy.DurableTransaction.commit
        injected = []
        target_key = self.port.key
        class SerializationFailure(Exception):
            sqlstate = '40001'
        def retry_ack(transaction):
            is_ack = any(record.record_id == target_key and 'ack' in record.payload
                         and record.payload.get('state') != 'RESOLVED' for record in transaction.snapshot.values())
            if is_ack and not injected:
                injected.append(True)
                raise SerializationFailure()
            return original(transaction)
        with patch.object(legacy.DurableTransaction, 'commit', new=retry_ack), patch.object(
                self.port, 'record_ack_in_transaction', wraps=self.port.record_ack_in_transaction) as record:
            self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual(2, record.call_count)
        self.assertIs(record.call_args_list[0].args[-1], record.call_args_list[1].args[-1])
        self.assertEqual(1, len(self.base.calls))
        self.assertIn('ack', self.fact()[1])

    def test_foreign_or_mutable_executor_ack_cannot_enter_core(self):
        original = self.execute
        def foreign(operation, warrant, limits):
            return replace(original(operation, warrant, limits), binding_digest='0' * 64)
        self.base.route.executor = foreign
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertNotIn('ack', self.fact()[1])
        self.assertEqual(1, len(self.base.calls))

    def test_matching_route_can_recover_the_same_durable_target_binding(self):
        self.base.dispatch()
        rebound = self.new_route(self.port)
        self.assertEqual('Applied', rebound.reconcile(self.base.fx.p(), self.base.warrant, 1)['outcome']['contract_type'])
        self.assertEqual(1, len(self.base.calls))

    def test_changed_target_binding_cannot_adopt_bound_warrant(self):
        self.base.dispatch()
        changed = copy.copy(self.port)
        changed.binding = replace(changed.binding, incarnation='different-incarnation')
        rebound = self.new_route(changed)
        with self.assertRaises(ValueError):
            rebound.inspect(self.base.fx.p(Capability.READ), self.base.warrant)
        self.assertEqual(1, len(self.base.calls))

    def test_participation_binding_is_committed_by_existing_warrant_ddr(self):
        context = self.base.fx.runner.run(TransactionContext(self.base.fx.p(Capability.READ), Capability.READ),
            lambda tx: self.base.route._context(tx, self.base.warrant)[0])
        ddr = legacy.DecisionDependencyRoot.from_dict(context['target_ddr'])
        self.assertIn(self.port.binding.evidence(), ddr.evidence_refs)
        self.assertIn(self.port.binding.evidence(), self.base.warrant.decision_dependency_root.evidence_refs)

    def test_port_route_cannot_silently_adopt_a_legacy_authorization(self):
        unbound = self.new_route(None)
        warrant = unbound.authorize(self.base.fx.p(), self.base.grant.session_id,
            self.base.operation, self.base.binding, self.base.graph, self.base.trace,
            nonce='legacy-adoption-control', model_id=legacy.MODEL, money_nano=50, risk_units=5)
        before = self.base.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'TARGET_PORT_DURABLE_BINDING_MISMATCH'):
            self.base.route.inspect(self.base.fx.p(Capability.READ), warrant)
        self.assertEqual(before, self.base.path.read_bytes())

    def test_ack_fact_is_immutable_and_cannot_bind_another_operation(self):
        acknowledgment = self.types.TargetExecutionAck(self.base.warrant.operation_hash, self.base.warrant.digest(),
            self.port.binding.digest(), 'a' * 64, 'ack-control', 'b' * 64)
        with self.assertRaises((AttributeError, TypeError)):
            acknowledgment.target_root = '0' * 64
        with self.assertRaises(ValueError):
            self.port.binding.require_ack(self.base.warrant, replace(acknowledgment, operation_digest='sha256:' + '0' * 64))

    def test_default_none_preserves_existing_legacy_reconciliation(self):
        self.base.route = self.new_route(None)
        self.base.warrant, self.base.request = self.base.authorize('legacy-compat-nonce')
        self.base.route.verifier = self.base.verify
        self.base.dispatch()
        self.assertEqual('Applied', self.reconcile()['outcome']['contract_type'])


if __name__ == '__main__':
    unittest.main()
