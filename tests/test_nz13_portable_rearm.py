"""Owner-approved local REARM using real SQLite, inventory, and the existing guard.

Fixture administration is explicit. A declared synthetic budget supports three
separate effects at risk5 each; production policy/defaults are unchanged.
"""
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

import test_nz13_portable_core_route as support
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from nonzero_cloudops.adapters import portable
from nonzero_cloudops.investigation import QueryResource
from nonzero_cloudops.models import (
    BudgetCounters,
    LocalApprovalRequestRecord,
    ProposalState,
    RemediationOperation,
    RemediationProposal,
    ResourceQuery,
    Run,
    generate_proposal_id,
    generate_run_id,
    generate_trace_id,
)
from nonzero_cloudops.models.public_enums import AuthorityGate
from nonzero_cloudops.state import files
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    LocalCoreTransaction,
    RecordKind,
    StoredRecord,
)
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import Limits, ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.tools import LocalSessionGrant
from runtime.providers.exact import CancellationToken
from runtime.providers.nvidia import ProviderRequest
from test_dual_governor import MODEL


class PortableRearmTests(unittest.TestCase):
    def setUp(self):
        self.f = support.PortableCoreRouteTests('runTest')
        # Three separate effects reserve >=15 risk units. This is fixture-only
        # bootstrap capacity, established before the first Core policy record.
        with patch.object(support.adoption, 'Limits', side_effect=lambda *_: Limits(1000, 100)):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.dispatch()
        self.assertEqual('Applied', self.f.route.reconcile(self.f.p(), self.f.warrant, 1)['outcome']['contract_type'])
        self.query = ResourceQuery(resource_type='AWS::EC2::EIP', resource_id='eipalloc-0123456789abcdef0')
        self.assertTrue(callable(getattr(self.f.adapter, 'prepare_rearm', None)), 'EXPLICIT_CORE_REARM_PREPARATION_NOT_IMPLEMENTED')
        with self.f.adapter.target_guard():
            self.domain = self.f.adapter.prepare_rearm(self.query)
        self.task = self.new_rearm()
        self.before_bytes = self.f.path.read_bytes()

    def new_task(self, *, policy, operation_builder, label):
        f = self.f
        route = f.make_route(policy_revision=policy)
        task_id, session_id, nonce = label + '-task', label + '-grant', label + '-once'
        operation = operation_builder(task_id, session_id, nonce)
        trace = FaultTrace(FaultKind.LOST_ACK, task_id, label + '-request', 'sha256:' + canonical_sha256(operation))
        graph = DependencyGraph(task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        completion = TaskCompletionBinding.for_graph(f.base.ledger.scope, graph, 'completion')
        f.base.liability.initialize(f.p(), graph)
        advisory = ProviderRequest(label + '-advisory', label + '-trace', 'nebius', MODEL,
                                   'inert local fixture metadata', label + '-budget', 128, 20)
        envelope = JobEnvelope.from_request(f.base.ledger.scope, task_id, advisory,
                                            deadline_at=160, money_nano=1, risk_units=0)
        f.base.gov.submit_job(f.p(Capability.MANAGE), envelope, completion=completion)
        claim = f.base.gov.claim_job(f.p(), task_id, label + '-worker', 1, lease_seconds=30)
        f.base.gov.begin_job(f.p(), claim)
        now = int(f.base.now.timestamp())
        operation_class = 'PORTABLE_REARM_DEMO_V1' if policy == 5 else 'PORTABLE_RELEASE_ELASTIC_IP'
        grant = LocalSessionGrant(session_id, f.base.ledger.scope, f.workspace, policy,
            (operation_class,), completion.digest, now, now + 120, 1, 0, 10, 20, 4096)
        route.create_session(f.p(Capability.OWNER_APPROVAL), grant)
        return SimpleNamespace(route=route, task_id=task_id, session_id=session_id, nonce=nonce,
            operation=operation, graph=graph, trace=trace, completion=completion, grant=grant)

    def new_rearm(self, *, label='rearm', domain=None):
        f = self.f
        domain = self.domain if domain is None else domain
        def operation(task_id, session_id, nonce):
            request = f.target.PortableRearmRequest.create(domain_input=domain,
                request_id=label + '-request', run_id=generate_run_id(),
                actor_session_id=f.p().actor_session_id, assignment_revision=f.p().assignment_revision,
                decision_nonce_hash=canonical_sha256(nonce), requested_at=f.base.now,
                expires_at=f.base.now + timedelta(seconds=60))
            return f.target.PortableRearmOperation.create(workspace=f.workspace, task_id=task_id,
                session_id=session_id, principal_session_id=f.p().actor_session_id, policy_epoch=1,
                target_binding_digest=f.port.binding.digest(), target_revision=domain.to_dict()['target_revision'],
                domain_input=domain, request=request).to_dict()
        return self.new_task(policy=5, operation_builder=operation, label=label)

    def new_release(self, *, label='release-again'):
        f = self.f
        def operation(task_id, session_id, nonce):
            run = Run.new(run_id=generate_run_id(), trace_id=generate_trace_id(), correlation_id=generate_run_id(),
                idempotency_key='owned-rearm-fixture-' + label, created_at=f.base.now, budget=BudgetCounters(max_turns=1, max_tokens=1))
            with f.store.target_guard():
                evidence = QueryResource(portable.PortableResourceReader(f.store)).execute(
                    self.query, run=run, observed_at=f.base.now).value
                self.assertIsNotNone(evidence)
                proposal = RemediationProposal.create(proposal_id=generate_proposal_id(), evidence=evidence,
                    operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
                    normalized_parameters={'allocation_id': self.query.resource_id},
                    authority_class=AuthorityGate.PLAN_AND_CONFIRM, risk_summary='A distinct owned local run',
                    created_at=f.base.now, expires_at=f.base.now + timedelta(minutes=2))
                proposal = proposal.model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
                request = LocalApprovalRequestRecord.create(request_id=generate_proposal_id(), proposal=proposal,
                    actor_session_id=f.p().actor_session_id, decision_nonce_hash=canonical_sha256(nonce),
                    requested_at=f.base.now, expires_at=f.base.now + timedelta(minutes=1))
                observed = f.store.observe_guarded_inventory()
                domain = f.target.PortableDomainInput(canonical_json_bytes({
                    'schema': 'aioa.portable-domain-input.v1', 'proposal': proposal.model_dump(mode='json'),
                    'evidence': evidence.model_dump(mode='json'), 'request': request.model_dump(mode='json'),
                    'inventory': json.loads(observed.canonical_state)}))
                snapshot = f.adapter.probe()
            return f.target.PortableOperation.create(workspace=f.workspace, task_id=task_id, session_id=session_id,
                principal_session_id=f.p().actor_session_id, policy_epoch=1,
                target_binding_digest=f.port.binding.digest(), target_revision=snapshot.revision,
                domain_input=domain).to_dict()
        return self.new_task(policy=4, operation_builder=operation, label=label)

    def approve(self, task=None, **changes):
        task = self.task if task is None else task
        arguments = {'nonce': task.nonce, 'model_id': MODEL, 'money_nano': 0, 'risk_units': 5}
        arguments.update(changes)
        task.warrant = task.route.authorize_exact(self.f.p(Capability.OWNER_APPROVAL), task.session_id,
            task.operation, task.completion, task.graph, task.trace, **arguments)
        task.reservation = ReservationRequest(task.warrant.risk_reservation_id, task.task_id, 'portable-local',
                                             MODEL, canonical_sha256(task.operation), 0, 5)
        return task.warrant

    def dispatch(self, task=None, **changes):
        task = self.task if task is None else task
        arguments = {'session_id': task.session_id, 'warrant': task.warrant, 'operation': task.operation,
                     'reservation': task.reservation, 'completion': task.completion}
        arguments.update(changes)
        return task.route.dispatch(self.f.p(), **arguments)

    def settle(self, task=None):
        task = self.task if task is None else task
        result = task.route.reconcile(self.f.p(), task.warrant, 1)
        self.assertEqual('Applied', result['outcome']['contract_type'])
        return result

    def history(self, task=None):
        task = self.task if task is None else task
        return self.f.base.run_tx(lambda tx: tx.get(RecordKind.OPERATION,
            self.f.port.history_key(task.warrant)), Capability.READ)

    def replace_record(self, kind, key, change):
        def mutate(tx):
            row = tx.get(kind, key)
            payload = json.loads(canonical_json_bytes(row.payload))
            change(payload)
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, payload),
                       expected_revision=row.revision)
        self.f.base.run_tx(mutate)

    def test_owner_release_rearm_new_separately_approved_release_preserves_every_receipt(self):
        original_receipts = self.domain.to_dict()['inventory']['receipts']
        self.approve()
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((2, 2, 0), self.f.executor.counters())
        self.settle()
        with self.f.store.target_guard():
            current = json.loads(self.f.store.observe_guarded_inventory().canonical_state)
        self.assertEqual(original_receipts, current['receipts'])
        self.assertEqual(4, len(current['resources']))
        next_release = self.new_release()
        self.approve(next_release)
        self.dispatch(next_release)
        self.settle(next_release)
        self.assertEqual((3, 3, 0), self.f.executor.counters())
        self.assertEqual(3, self.f.head()[1]['generation'])
        with self.f.adapter.target_guard():
            again = self.f.adapter.prepare_rearm(self.query)
        self.assertEqual(2, len(again.to_dict()['release_receipt_hashes']))
        self.assertIn(original_receipts[0], again.to_dict()['inventory']['receipts'])
        self.assertEqual('Applied', self.task.route.inspect(self.f.p(Capability.READ), self.task.warrant)['outcome']['contract_type'])

    def test_prepare_and_typed_request_are_immutable_facts_without_authority(self):
        self.assertEqual('NONE', self.domain.authority)
        self.assertEqual('NONE', self.f.target.PortableRearmOperation.parse(self.task.operation).authority)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            self.domain.canonical_input = b'{}'
        detached = self.domain.to_dict()
        detached['release_receipt_hashes'].clear()
        self.assertEqual(1, len(self.domain.to_dict()['release_receipt_hashes']))
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_preparation_requires_the_current_named_guard(self):
        before = self.f.path.read_bytes(), self.f.base.records()
        with self.assertRaises((ValueError, portable.PortableMutationError)):
            self.f.adapter.prepare_rearm(self.query)
        self.assertEqual(before, (self.f.path.read_bytes(), self.f.base.records()))

    def test_host_fixed_query_and_region_cannot_choose_another_resource(self):
        invalid = [None, True, self.query.model_dump(mode='json'),
            ResourceQuery(resource_type='AWS::EC2::EIP', resource_id=self.query.resource_id, region='us-east-1'),
            ResourceQuery(resource_type='AWS::EC2::EIP', resource_id='eipalloc-11111111111111111')]
        for query in invalid:
            with self.subTest(query=type(query).__name__), self.f.adapter.target_guard(), self.assertRaises((TypeError, ValueError)):
                self.f.adapter.prepare_rearm(query)
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_typed_rearm_codec_rejects_noncanonical_or_extra_or_wrong_template_facts(self):
        original = self.domain.to_dict()
        variants = []
        for change in [lambda v: v.update(extra=True), lambda v: v.update(template_digest='f' * 64),
                       lambda v: v.update(template_version='caller-template'),
                       lambda v: v.update(release_receipt_hashes=[]),
                       lambda v: v.update(generation=True), lambda v: v.update(head_revision=True)]:
            value = json.loads(canonical_json_bytes(original))
            change(value)
            variants.append(canonical_json_bytes(value))
        variants.extend([json.dumps(original, indent=2).encode(), b'{}', b'x' * 49153, True])
        for raw in variants:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                self.f.target.PortableRearmDomainInput(raw)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())

    def test_policy4_route_rejects_rearm_and_policy5_rejects_release(self):
        with self.f.adapter.target_guard():
            snapshot = self.f.adapter.probe()
        with self.assertRaises(ValueError):
            self.f.route.operation(self.task.operation, snapshot)
        with self.assertRaises(ValueError):
            self.task.route.operation(self.f.operation, snapshot)
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_commit_principal_and_legacy_authorize_cannot_issue_rearm_approval(self):
        task = self.task
        before = self.f.base.records()
        with self.assertRaises(ValueError):
            task.route.authorize(self.f.p(), task.session_id, task.operation, task.completion,
                task.graph, task.trace, nonce=task.nonce, model_id=MODEL, money_nano=0, risk_units=5)
        with self.assertRaises(ValueError):
            task.route.authorize_exact(self.f.p(), task.session_id, task.operation, task.completion,
                task.graph, task.trace, nonce=task.nonce, model_id=MODEL, money_nano=0, risk_units=5)
        self.assertEqual(before, self.f.base.records())

    def test_rearm_nonce_digest_cannot_approve_a_different_owner_nonce(self):
        before = self.f.base.records()
        with self.assertRaises(ValueError):
            self.approve(nonce='different-owner-decision')
        self.assertEqual(before, self.f.base.records())

    def test_rearm_minimum_risk_and_true_usd0_are_not_lowered(self):
        before = self.f.base.records()
        for changes in [{'risk_units': 4}, {'risk_units': True}, {'money_nano': 1}, {'money_nano': True}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.approve(**changes)
        self.assertEqual(before, self.f.base.records())

    def test_all_consuming_release_history_is_required_before_another_prepare(self):
        self.f.base.delete(self.f.port.history_key(self.f.warrant))
        with self.assertRaises(ValueError), self.f.adapter.target_guard():
            self.f.adapter.prepare_rearm(self.query)
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_a_settled_rearm_without_its_retained_ack_is_not_returned_as_applied(self):
        self.approve()
        self.dispatch()
        self.settle()
        row = self.history()
        self.assertEqual('aioa-core-target-history-portable-rearm.v1', row.payload['schema'])
        self.assertIsNotNone(row.payload['execution_ack'])
        self.replace_record(RecordKind.OPERATION, row.record_id, lambda p: p.pop('execution_ack'))
        with self.assertRaises(ValueError):
            self.task.route.inspect(self.f.p(Capability.READ), self.task.warrant)
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_duplicate_retained_rearm_calls_do_not_attempt_another_effect(self):
        self.approve()
        self.dispatch()
        result = self.settle()
        before = self.f.path.read_bytes(), self.f.base.records()
        self.assertEqual(result, self.settle())
        self.assertEqual('Applied', self.dispatch()['outcome']['contract_type'])
        self.assertEqual(before, (self.f.path.read_bytes(), self.f.base.records()))
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_policy5_started_ack_loss_stays_unknown_and_never_replays(self):
        self.approve()
        manager, lost = self.f.lose_ack(phase='STARTED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        with self.assertRaises(ValueError):
            self.settle()
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_policy5_release_permission_ack_loss_stays_unknown_even_with_no_effect(self):
        self.approve()
        manager, lost = self.f.lose_ack(phase='RELEASED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        with self.assertRaises(ValueError):
            self.settle()
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((2, 1, 0), self.f.executor.counters())

    def test_physical_rearm_followed_by_missing_execution_ack_cannot_settle_desired_state(self):
        self.approve()
        def no_ack(*_args, **_kwargs):
            raise ValueError('CONTROLLED_UNCOMMITTED_EXECUTOR_ACK')
        with patch.object(self.f.port, 'record_ack_in_transaction', side_effect=no_ack):
            self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertNotEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertIsNone(self.f.head()[1]['in_flight']['ack'])
        with self.assertRaises(ValueError):
            self.settle()
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_committed_execution_ack_ack_loss_can_settle_without_another_write(self):
        self.approve()
        manager, lost = self.f.lose_ack(phase='RELEASED', require_ack=True)
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.settle()
        self.assertIsNotNone(self.history().payload['execution_ack'])
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_store_false_return_cannot_create_an_execution_ack_or_applied(self):
        self.approve()
        with patch.object(self.f.store, 'rearm_verified_demo_resource', return_value=False):
            self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertIsNone(self.f.head()[1]['in_flight']['ack'])
        with self.assertRaises(ValueError):
            self.settle()

    def boundary(self, action, *, cancel=None):
        self.approve()
        seal = portable.seal_local_payload
        def changed(*args, **kwargs):
            result = seal(*args, **kwargs)
            action()
            return result
        with patch.object(portable, 'seal_local_payload', new=changed):
            self.assertEqual('Unknown', self.dispatch(cancel=cancel)['outcome']['contract_type'])
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((2, 1, 0), self.f.executor.counters())
        self.assertEqual('STARTED', self.f.head()[1]['in_flight']['phase'])

    def test_stop_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: self.f.base.gov.set_kill(self.f.p(Capability.MANAGE), True))

    def test_cancel_is_rechecked_at_the_actual_rearm_write_boundary(self):
        cancel = CancellationToken()
        self.boundary(cancel.cancel, cancel=cancel)

    def test_owner_warrant_revoke_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: self.f.base.ledger.revoke(self.f.p(Capability.OWNER_APPROVAL), self.task.warrant))

    def test_session_revoke_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: self.task.route.revoke_session(self.f.p(Capability.MANAGE), self.task.session_id))

    def test_expiry_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: setattr(self.f.base, 'now', self.task.warrant.expires_at))

    def test_epoch_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: self.f.base.gov.start_epoch(self.f.p(Capability.MANAGE)))

    def test_lease_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: setattr(self.f.base.gov, 'clock', lambda: 131))

    def test_clock_regression_is_rechecked_at_the_actual_rearm_write_boundary(self):
        self.boundary(lambda: setattr(self.f.base.gov, 'clock', lambda: 99))

    def test_deleted_release_context_cannot_hide_its_risk_accounting_from_policy5(self):
        self.approve()
        self.f.base.delete(self.f.route._context_key(self.f.warrant))
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_release_callback_rollback_preserves_unknown_without_replaying_rearm(self):
        self.approve()
        release = self.f.port.before_release_in_transaction
        def rollback(*args, **kwargs):
            release(*args, **kwargs)
            raise ValueError('CONTROLLED_REARM_RELEASE_CALLBACK_ROLLBACK')
        with patch.object(self.f.port, 'before_release_in_transaction', side_effect=rollback):
            self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual('STARTED', self.f.head()[1]['in_flight']['phase'])
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((2, 1, 0), self.f.executor.counters())

    def test_serializable_release_retry_reuses_one_observation_and_one_attempt(self):
        self.approve()
        commit = LocalCoreTransaction.commit
        retried = []
        seen = []
        class Retry(Exception):
            sqlstate = '40001'
        def conflict(tx):
            row = tx.get(RecordKind.OPERATION, self.f.port.head_key)
            flight = row.payload['in_flight']
            if flight is not None and flight['phase'] == 'RELEASED' and flight['ack'] is None and not retried:
                retried.append(True)
                raise Retry()
            return commit(tx)
        release = self.f.port.before_release_in_transaction
        def capture(*args, **kwargs):
            seen.append(kwargs['write_observation'])
            return release(*args, **kwargs)
        with patch.object(LocalCoreTransaction, 'commit', new=conflict), \
                patch.object(self.f.port, 'before_release_in_transaction', side_effect=capture):
            self.dispatch()
        self.assertEqual([True], retried)
        self.assertEqual(2, len(seen))
        self.assertIs(seen[0], seen[1])
        self.settle()
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_final_callback_rollback_leaves_one_frozen_proof_and_all_core_facts_unknown(self):
        self.approve()
        self.dispatch()
        before = self.f.base.records()
        apply = self.f.base.liability.apply_resolution_in_transaction
        def rollback(*args, **kwargs):
            apply(*args, **kwargs)
            raise ValueError('CONTROLLED_REARM_FINAL_CALLBACK_ROLLBACK')
        with patch.object(self.f.base.liability, 'apply_resolution_in_transaction', side_effect=rollback), self.assertRaises(MemoryPatchError):
            self.settle()
        self.assertEqual(before, self.f.base.records())
        self.assertEqual(1, self.f.head()[1]['generation'])
        self.settle()
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_final_commit_ack_loss_requires_only_retained_readback(self):
        self.approve()
        self.dispatch()
        commit = LocalCoreTransaction.commit
        lost = []
        def replacement(tx):
            row = tx.get(RecordKind.OPERATION, self.f.port.head_key)
            selected = row.payload['generation'] == 2 and row.payload['in_flight'] is None
            commit(tx)
            if selected and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', new=replacement), self.assertRaises(CommitOutcomeUnknown):
            self.settle()
        self.assertEqual([True], lost)
        before = self.f.path.read_bytes(), self.f.base.records()
        self.settle()
        self.assertEqual(before, (self.f.path.read_bytes(), self.f.base.records()))
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_rearm_core_callbacks_do_not_read_write_or_verify_the_store(self):
        self.approve()
        run = self.f.base.runner.run
        def checked(context, callback):
            def sql(tx):
                with patch.object(self.f.store, 'observe_guarded_inventory', side_effect=AssertionError('STORE_READ_IN_SQL')), \
                     patch.object(self.f.store, '_write', side_effect=AssertionError('STORE_WRITE_IN_SQL')), \
                     patch.object(self.f.store, 'verify', side_effect=AssertionError('STORE_VERIFY_IN_SQL')), \
                     patch.object(portable, 'read_private_json', side_effect=AssertionError('FILE_READ_IN_SQL')), \
                     patch.object(portable, 'atomic_write_private_json', side_effect=AssertionError('FILE_WRITE_IN_SQL')):
                    return callback(tx)
            return run(context, sql)
        with patch.object(self.f.base.runner, 'run', side_effect=checked):
            self.dispatch()
            self.settle()
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_preapproved_other_task_cannot_restore_after_first_rearm_already_settled(self):
        other = self.new_rearm(label='other-rearm')
        self.approve(other)
        self.approve()
        self.dispatch()
        self.settle()
        before = self.f.path.read_bytes(), self.f.base.records()
        with self.assertRaises(ValueError):
            self.dispatch(other)
        self.assertEqual(before, (self.f.path.read_bytes(), self.f.base.records()))
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_unresolved_owner_intent_blocks_another_task_at_canonical_start(self):
        other = self.new_rearm(label='other-rearm')
        self.approve(other)
        self.approve()
        manager, _lost = self.f.lose_ack(phase='STARTED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        before = self.f.base.records()
        with self.assertRaisesRegex(ValueError, '^UNRESOLVED_INTENT$'):
            self.f.base.journal.start_local_zero(self.f.p(), other.warrant, other.operation, other.reservation)
        self.assertEqual(before, self.f.base.records())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_partial_head_rewind_cannot_make_a_stale_rearm_approval_current(self):
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        original_row, original_head = self.f.head()
        other = self.new_rearm(label='other-rearm')
        self.approve(other)
        self.approve()
        self.dispatch()
        self.settle()
        current, _head = self.f.head()
        record = StoredRecord(current.kind, current.record_id, current.scope, original_row.revision, original_head)
        cursor = self.f.base.factory.db.execute('UPDATE core_records_v1 SET record_json=?,record_digest=?,revision=? '
            'WHERE scope_key=? AND kind=? AND record_id=? AND revision=?',
            (canonical_record(record), record.payload_digest, record.revision,
             canonical_json_bytes(current.scope.binding()).decode(), current.kind.value, current.record_id, current.revision))
        self.assertEqual(1, cursor.rowcount)
        with self.assertRaises(ValueError):
            self.dispatch(other)
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_unknown_or_wrong_template_resource_or_extra_receipt_drifts_deny_prepare(self):
        with self.f.store.target_guard():
            resources, receipts = self.f.store._load()
            key = next(iter(resources))
            resources[key] = resources[key].model_copy(update={'tags': {'controlled': 'rearm-drift'}})
            files.atomic_write_private_json(self.f.path, files.seal_local_payload(
                self.f.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
        before = self.f.path.read_bytes()
        with self.assertRaises(ValueError), self.f.adapter.target_guard():
            self.f.adapter.prepare_rearm(self.query)
        self.assertEqual(before, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_policy5_context_cannot_be_relabelled_as_policy4_or_legacy(self):
        self.approve()
        key = self.task.route._context_key(self.task.warrant)
        self.replace_record(RecordKind.OPERATION, key, lambda p: p.update(schema='aioa-local-portable-effect-context-v1'))
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_policy5_session_cannot_be_relabelled_as_policy4(self):
        key = self.task.route.session_key(self.task.session_id)
        self.replace_record(RecordKind.OPERATION, key, lambda p: p.update(schema='aioa-local-portable-session-v1'))
        before = self.f.base.records()
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(before, self.f.base.records())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_retained_rearm_readback_remains_possible_after_session_revocation(self):
        self.approve()
        self.dispatch()
        self.settle()
        self.task.route.revoke_session(self.f.p(Capability.MANAGE), self.task.session_id)
        self.settle()
        self.assertEqual('Applied', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_rearm_history_marker_fences_a_new_adoption_even_without_named_records(self):
        import test_nz13_portable_history_barriers as support_history
        fixture = support_history.PortableHistoryBarrierTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.check_prepare('aioa-core-target-history-portable-rearm.v1')

    def test_adoption_commit_refuses_a_new_rearm_history_marker(self):
        import test_nz13_portable_history_barriers as support_history
        fixture = support_history.PortableHistoryBarrierTests('runTest')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.check_adopt('aioa-core-target-history-portable-rearm.v1')

    def fresh_process(self, mode, *, expected, generation):
        import os
        import subprocess
        import sys
        from dataclasses import asdict
        from pathlib import Path
        binding = asdict(self.f.port.binding)
        del binding['scope']
        self.f.base.runner.close()
        self.f.base.core.close()
        helper = Path(__file__).with_name('nz13_rearm_process_r1.py')
        payload = json.dumps({'root': str(self.f.base.path), 'binding': binding,
                              'warrant': self.task.warrant.to_dict(), 'mode': mode}) + '\n'
        environment = {'PATH': '/usr/bin:/bin', 'HOME': str(self.f.base.path), 'TMPDIR': os.environ['TMPDIR'],
            'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1', 'PYTHONDONTWRITEBYTECODE': '1',
            'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'}
        completed = subprocess.run([sys.executable, '-I', '-B', str(helper)], input=payload,
            capture_output=True, text=True, cwd=self.f.base.path, env=environment, timeout=30, check=False)
        self.assertEqual(0, completed.returncode, completed.stderr[-3000:])
        value = json.loads(completed.stdout)
        self.assertEqual('result', value['event'])
        self.assertNotEqual(os.getpid(), value['pid'])
        self.assertEqual(expected, value['outcome'])
        self.assertEqual(generation, value['generation'])
        self.assertEqual('NONE', value['authority'])
        self.assertIs(False, value['grants_replay'])
        self.assertEqual([0, 0, 0], value['executor_counters'])
        self.assertEqual(0, value['network_attempts'])
        self.assertTrue(value['source_only_checkout'])
        self.assertTrue(value['dont_write_bytecode_flag'])
        self.assertEqual('_SourceOnlyLoader', value['checkout_loader'])
        evidence_dir = os.environ.get('REARM_PROCESS_EVIDENCE_DIR')
        if evidence_dir is not None:
            path = Path(evidence_dir) / (self._testMethodName + '.json')
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump({'schema': 'nz13.rearm.process-evidence.v1', 'case': self._testMethodName,
                    'parent_pid': os.getpid(), 'child': value, 'fixture_only': True, 'qualification': False}, stream, indent=2)
                stream.write('\n')
        return value

    def test_fresh_exec_started_ack_loss_preserves_unknown_without_a_new_attempt(self):
        self.approve()
        manager, _lost = self.f.lose_ack(phase='STARTED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.fresh_process('unresolved', expected='Unknown', generation=1)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())

    def test_fresh_exec_release_permission_ack_loss_preserves_unknown_without_a_write(self):
        self.approve()
        manager, _lost = self.f.lose_ack(phase='RELEASED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.fresh_process('unresolved', expected='Unknown', generation=1)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())

    def test_fresh_exec_physical_write_without_executor_ack_cannot_reconstruct_an_ack(self):
        self.approve()
        with patch.object(self.f.port, 'record_ack_in_transaction', side_effect=ValueError('CONTROLLED_ACK_LOSS')):
            self.dispatch()
        self.assertNotEqual(self.before_bytes, self.f.path.read_bytes())
        self.fresh_process('unresolved', expected='Unknown', generation=1)

    def test_fresh_exec_committed_executor_ack_loss_settles_without_target_replay(self):
        self.approve()
        manager, _lost = self.f.lose_ack(phase='RELEASED', require_ack=True)
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.fresh_process('reconcile', expected='Applied', generation=2)

    def test_fresh_exec_final_commit_ack_loss_reads_retained_applied_without_replay(self):
        self.approve()
        self.dispatch()
        commit = LocalCoreTransaction.commit
        lost = []
        def replacement(tx):
            row = tx.get(RecordKind.OPERATION, self.f.port.head_key)
            selected = row.payload['generation'] == 2 and row.payload['in_flight'] is None
            commit(tx)
            if selected and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        with patch.object(LocalCoreTransaction, 'commit', new=replacement), self.assertRaises(CommitOutcomeUnknown):
            self.settle()
        self.assertEqual([True], lost)
        self.fresh_process('inspect', expected='Applied', generation=2)

    def damage_record(self, kind, key, change):
        from runtime.memory_patch.adapters.cockroach.repositories import (
            canonical_record,
        )
        row = self.f.base.run_tx(lambda tx: tx.get(kind, key), Capability.READ)
        payload = json.loads(canonical_json_bytes(row.payload))
        change(payload)
        record = StoredRecord(row.kind, row.record_id, row.scope, row.revision, payload)
        cursor = self.f.base.factory.db.execute('UPDATE core_records_v1 SET record_json=?,record_digest=? '
            'WHERE scope_key=? AND kind=? AND record_id=? AND revision=?',
            (canonical_record(record), record.payload_digest, canonical_json_bytes(record.scope.binding()).decode(),
             record.kind.value, record.record_id, record.revision))
        self.assertEqual(1, cursor.rowcount)
        return payload

    def test_foreign_executor_ack_in_coherently_rehashed_history_denies_all_retained_returns(self):
        self.approve()
        self.dispatch()
        self.settle()
        def changed(history):
            ack = history['execution_ack']
            ack['ack_digest'] = 'f' * 64
            ack['ack_id'] = 'portable-rearm-ack-' + 'f' * 64
        history = self.damage_record(RecordKind.OPERATION, self.history().record_id, changed)
        self.damage_record(RecordKind.OPERATION, self.f.port.head_key,
                           lambda p: p.update(history_digest=canonical_sha256(history)))
        for retained in [lambda: self.task.route.inspect(self.f.p(Capability.READ), self.task.warrant),
                         lambda: self.task.route.reconcile(self.f.p(), self.task.warrant, 1), lambda: self.dispatch()]:
            with self.subTest(call=retained), self.assertRaises(ValueError):
                retained()
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_rearm_candidate_must_preserve_complete_receipt_bytes_and_unrelated_resources(self):
        self.approve()
        inventory = self.domain.to_dict()['inventory']
        valid = json.loads(canonical_json_bytes(inventory))
        valid['resources'].append(self.f.evidence.resource.model_dump(mode='json'))
        resources, receipts = self.f.target._inventory({
            **valid, 'resources': sorted(valid['resources'], key=lambda r: (r['resource_type'], r['resource_id'], r['region']))})
        valid = self.f.store._payload(resources, receipts)
        mutations = [lambda v: v['receipts'].clear(),
                     lambda v: v['resources'][0]['tags'].update(unapproved='drift'),
                     lambda v: v['resources'].pop()]
        for mutate in mutations:
            value = json.loads(canonical_json_bytes(valid))
            mutate(value)
            candidate = portable._canonical_inventory_bytes(value)
            with self.subTest(mutation=mutate), self.f.store.target_guard(), self.assertRaises(ValueError):
                self.f.adapter.candidate_observation(self.task.operation, self.task.warrant, candidate,
                                                     self.f.port.binding.guard_fingerprint)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_adopted_release_receipt_and_legacy_key_with_typed_store_proof_do_not_prove_core_applied(self):
        from nonzero_cloudops.models import LocalExecutionReceipt
        from nonzero_cloudops.models.digest import compute_evidence_digest
        for legacy in [False, True]:
            with self.subTest(legacy=legacy):
                base = support.adoption.TargetAdoptionTests('runTest')
                base.setUp()
                self.addCleanup(base.doCleanups)
                head_key = canonical_sha256(('aioa-core-target-head.v1', base.ledger.scope,
                                             self.f.workspace, self.f.target_id))
                named = canonical_sha256(('aioa-core-target-registration.v1', head_key))
                path = base.path / 'managed/.aioa-core-managed-v1' / canonical_sha256(base.ledger.scope) / named / 'inventory.json'
                path.parent.mkdir(parents=True, mode=0o700)
                for directory in path.parents[:3]:
                    directory.chmod(0o700)
                path.write_bytes(base.store.path.read_bytes())
                path.chmod(0o600)
                lock = path.with_name('inventory.json.lock')
                lock.write_bytes(b'')
                lock.chmod(0o600)
                base.store = portable.PortableStateStore(path)
                receipt = LocalExecutionReceipt.model_validate(self.domain.to_dict()['inventory']['receipts'][0])
                if legacy:
                    values = receipt.model_dump()
                    values['before_resource'] = receipt.before_resource
                    values.pop('receipt_hash')
                    values['idempotency_key'] = 'local-exec:' + receipt.proposal_hash
                    provisional = LocalExecutionReceipt.model_construct(**values, receipt_hash='0' * 64)
                    receipt = LocalExecutionReceipt(**values,
                        receipt_hash=compute_evidence_digest(provisional.receipt_payload()))
                with base.store.target_guard():
                    resources, receipts = base.store._load()
                    resources.pop((self.query.resource_type, self.query.resource_id, self.query.region))
                    receipts[receipt.idempotency_key] = receipt
                    files.atomic_write_private_json(path, files.seal_local_payload(
                        base.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
                port, management = base.prepare()
                base.adopt(port, management, base.approve(management))
                executor = portable.PortableExecutor(base.store, clock=lambda base=base: base.now)
                adapter = self.f.target.CorePortableTarget(port, base.store, executor=executor,
                    read_principal=base.p(Capability.READ), clock=lambda base=base: base.now)
                with adapter.target_guard():
                    proof = executor.verify(receipt)
                    self.assertTrue(proof.observed_absent)
                    before = path.read_bytes(), base.records()
                    with self.assertRaises(ValueError):
                        adapter.prepare_rearm(self.query)
                self.assertEqual(before, (path.read_bytes(), base.records()))
                self.assertEqual((0, 0, 0), executor.counters())

        # Generation1 is essential here: the generation0 precondition must not
        # accidentally substitute for complete consuming-release history joins.
        # Explicit fixture administration seeds valid old/legacy receipts while
        # leaving the EIP present. One real Core release then consumes it.
        seed = LocalExecutionReceipt.model_validate(self.domain.to_dict()['inventory']['receipts'][0])
        adopted = []
        for index in range(3):
            values = {name: getattr(seed, name) for name in LocalExecutionReceipt.model_fields if name != 'receipt_hash'}
            values['run_id'] = generate_run_id()
            values['idempotency_key'] = ('local-exec:' + seed.proposal_hash if index == 0 else
                'local-exec:' + str(values['run_id']) + ':' + seed.proposal_hash)
            # Equal time, then backwards-ordered older runs must all be joined.
            values['executed_at'] = self.f.base.now - timedelta(seconds=5 * index)
            provisional = LocalExecutionReceipt.model_construct(**values, receipt_hash='0' * 64)
            adopted.append(LocalExecutionReceipt(**values,
                receipt_hash=compute_evidence_digest(provisional.receipt_payload())))
        prepare = support.adoption.TargetAdoptionTests.prepare
        def seeded_inventory(base):
            with base.store.target_guard():
                resources, receipts = base.store._load()
                self.assertIn((self.query.resource_type, self.query.resource_id, self.query.region), resources)
                receipts.update((receipt.idempotency_key, receipt) for receipt in adopted)
                files.atomic_write_private_json(base.store.path, files.seal_local_payload(
                    base.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
            return prepare(base)
        current = support.PortableCoreRouteTests('runTest')
        self.addCleanup(current.doCleanups)
        with patch.object(support.adoption.TargetAdoptionTests, 'prepare', new=seeded_inventory):
            current.setUp()
        current.dispatch()
        self.assertEqual('Applied', current.route.reconcile(current.p(), current.warrant, 1)['outcome']['contract_type'])
        self.assertEqual(1, current.head()[1]['generation'])
        with current.adapter.target_guard():
            relevant = current.store.released_default_resource_receipts(self.query)
            self.assertEqual(4, len(relevant))
            proofs = tuple(current.executor.verify(receipt) for receipt in relevant)
            self.assertTrue(all(proof.observed_absent and proof.observed_resource is None for proof in proofs))
            before = current.path.read_bytes(), current.base.records()
            with self.assertRaisesRegex(ValueError, '^PORTABLE_REARM_COMPLETE_CORE_HISTORY$'):
                current.adapter.prepare_rearm(self.query)
            self.assertEqual(before, (current.path.read_bytes(), current.base.records()))
        self.assertEqual((1, 1, 0), current.executor.counters())

    def test_real_history_scan_quota_denies_preparation_before_any_rearm_attempt(self):
        def fill(tx):
            count = len(tx.scan(RecordKind.OPERATION, limit=1024))
            for index in range(count, 1024):
                tx.insert(StoredRecord(RecordKind.OPERATION, 'owned-rearm-quota-' + str(index),
                    self.f.base.ledger.scope, 1, {'schema': 'owned-test-padding'}))
        self.f.base.run_tx(fill)
        with self.assertRaises(ValueError), self.f.adapter.target_guard():
            self.f.adapter.prepare_rearm(self.query)
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_mixed_legacy_positive_money_policy4_and_policy5_share_existing_accounting(self):
        self.f.legacy_effect()
        self.approve()
        self.dispatch()
        self.settle()
        state = self.f.base.gov.inspect(self.f.p(Capability.READ))
        self.assertEqual(0, state['reservations'][self.task.warrant.risk_reservation_id]['money_nano'])
        self.assertNotIn('NONE', state['reservations'])
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_missing_policy5_context_blocks_a_later_distinct_release_start(self):
        self.approve()
        self.dispatch()
        self.settle()
        release = self.new_release()
        self.approve(release)
        self.f.base.delete(self.task.route._context_key(self.task.warrant))
        before = self.f.path.read_bytes()
        with self.assertRaises(ValueError):
            self.dispatch(release)
        self.assertEqual(before, self.f.path.read_bytes())
        self.assertEqual((2, 2, 0), self.f.executor.counters())

    def test_reverse_rearm_tool_intent_scan_cannot_ignore_an_unmapped_closed_profile(self):
        self.approve()
        self.f.base.run_tx(lambda tx: tx.insert(StoredRecord(RecordKind.OPERATION,
            'owned-unmapped-rearm-intent', self.f.base.ledger.scope, 1,
            {'schema': 'aioa-effect-intent-local-zero-v2', 'warrant_digest': 'unmapped-owned-fixture',
             'operation': {'payload': {'tool': 'rearm_demo'}}, 'resolution': {'owned': 'corrupt-closed-marker'}})))
        before = self.f.base.records()
        with self.assertRaises(ValueError):
            self.dispatch()
        self.assertEqual(before, self.f.base.records())
        self.assertEqual(self.before_bytes, self.f.path.read_bytes())
        self.assertEqual((1, 1, 0), self.f.executor.counters())

    def test_direct_zero_journal_rejects_non_usd_rearm_warrant_without_consuming_it(self):
        from decimal import Decimal

        from lab.archaioa.authority import Money
        from runtime.mission.warrant import approval_digest
        self.approve()
        scope = replace(self.task.warrant.authority_scope, monetary_ceiling=Money(Decimal(0), 'XTS'))
        bad = replace(self.task.warrant, warrant_id='non-usd-rearm', nonce='non-usd-rearm', authority_scope=scope)
        bad = replace(bad, approval_digest=approval_digest(bad))
        self.f.base.ledger.approve(self.f.p(Capability.OWNER_APPROVAL), bad)
        before = self.f.base.records()
        with self.assertRaisesRegex(ValueError, '^LOCAL_ZERO_USD_REQUIRED$'):
            self.f.base.journal.start_local_zero(self.f.p(), bad, self.task.operation, self.task.reservation)
        self.assertEqual(before, self.f.base.records())
        self.assertIsNone(self.f.base.ledger.inspect(self.f.p(Capability.READ), bad))
        self.assertEqual((1, 1, 0), self.f.executor.counters())
