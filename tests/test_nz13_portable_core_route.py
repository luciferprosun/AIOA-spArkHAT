"""One real SQLite Core and one existing PortableExecutor on private managed fixtures.

Fixture administration creates initial inventory explicitly. This is neither
product INIT/rearm nor production Native/model or remote-cloud certification.
"""
import importlib
import unittest
from datetime import timedelta
from unittest.mock import patch

import test_nz13_target_adoption as adoption
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
from test_dual_governor import MODEL

from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import LocalCoreTransaction, RecordKind
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.governor import ReservationRequest
from runtime.mission.job_contracts import JobEnvelope
from runtime.mission.sandbox_contracts import TOOL_POLICY_VERSIONS
from runtime.mission.tools import CoreToolRoute, LocalSessionGrant
from runtime.providers.exact import CancellationToken
from runtime.providers.nvidia import ProviderRequest


class PortableCoreRouteTests(unittest.TestCase):
    def setUp(self):
        self.assertIn(4, TOOL_POLICY_VERSIONS, 'SAME_CORE_PORTABLE_USD0_POLICY_NOT_IMPLEMENTED')
        target = importlib.import_module('runtime.mission.portable_target')
        self.assertTrue(hasattr(target, 'CorePortableTarget'), 'CORE_BOUND_PORTABLE_ADAPTER_NOT_IMPLEMENTED')
        self.target = target
        self.base = adoption.TargetAdoptionTests('test_owner_adoption_creates_only_joined_management_facts_in_one_core')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.workspace = 'workspace-1'
        self.target_id = 'portable-inventory-1'
        head_key = canonical_sha256(('aioa-core-target-head.v1', self.base.ledger.scope,
                                    self.workspace, self.target_id))
        named_key = canonical_sha256(('aioa-core-target-registration.v1', head_key))
        self.path = (self.base.path / 'managed' / '.aioa-core-managed-v1'
                     / canonical_sha256(self.base.ledger.scope) / named_key / 'inventory.json')
        # Explicit private fixture administration, never a product creation path.
        self.path.parent.mkdir(parents=True, mode=0o700)
        for directory in self.path.parents[:3]:
            directory.chmod(0o700)
        self.path.write_bytes(self.base.store.path.read_bytes())
        self.path.chmod(0o600)
        self.path.with_name('inventory.json.lock').write_bytes(b'')
        self.path.with_name('inventory.json.lock').chmod(0o600)
        self.base.store = portable.PortableStateStore(self.path)
        self.store = self.base.store
        self.before_bytes = self.path.read_bytes()
        self.port, management = self.base.prepare()
        self.base.adopt(self.port, management, self.base.approve(management))
        self.executor = portable.PortableExecutor(self.store, clock=lambda: self.base.now)
        self.adapter = target.CorePortableTarget(self.port, self.store, executor=self.executor,
                                                read_principal=self.p(Capability.READ),
                                                clock=lambda: self.base.now)
        self.route = self.make_route()
        self.task_id = 'portable-task'
        self.session_id = 'portable-task-grant'
        self.run = Run.new(run_id=generate_run_id(), trace_id=generate_trace_id(),
            correlation_id=generate_run_id(), idempotency_key='owned-portable-fixture-once',
            created_at=self.base.now, budget=BudgetCounters(max_turns=1, max_tokens=1))
        query = ResourceQuery(resource_type='AWS::EC2::EIP', resource_id='eipalloc-0123456789abcdef0')
        with self.store.target_guard():
            self.evidence = QueryResource(portable.PortableResourceReader(self.store)).execute(
                query, run=self.run, observed_at=self.base.now).value
            self.assertIsNotNone(self.evidence)
            proposal = RemediationProposal.create(proposal_id=generate_proposal_id(), evidence=self.evidence,
                operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
                normalized_parameters={'allocation_id': self.evidence.resource.resource_id},
                authority_class=AuthorityGate.PLAN_AND_CONFIRM, risk_summary='One owned local fixture address',
                created_at=self.base.now, expires_at=self.base.now + timedelta(minutes=2))
            self.proposal = proposal.model_copy(update={'status': ProposalState.AWAITING_APPROVAL})
            self.domain_request = LocalApprovalRequestRecord.create(request_id=generate_proposal_id(),
                proposal=self.proposal, actor_session_id=self.p().actor_session_id, decision_nonce_hash='b' * 64,
                requested_at=self.base.now, expires_at=self.base.now + timedelta(minutes=1))
            observed = self.store.observe_guarded_inventory()
            import json
            self.domain = target.PortableDomainInput(canonical_json_bytes({
                'schema': 'aioa.portable-domain-input.v1', 'proposal': self.proposal.model_dump(mode='json'),
                'evidence': self.evidence.model_dump(mode='json'),
                'request': self.domain_request.model_dump(mode='json'),
                'inventory': json.loads(observed.canonical_state)}))
            snapshot = self.adapter.probe()
        self.operation = target.PortableOperation.create(workspace=self.workspace, task_id=self.task_id,
            session_id=self.session_id, principal_session_id=self.p().actor_session_id, policy_epoch=1,
            target_binding_digest=self.port.binding.digest(), target_revision=snapshot.revision,
            domain_input=self.domain).to_dict()
        self.trace = FaultTrace(FaultKind.LOST_ACK, self.task_id, 'portable-request',
                                'sha256:' + canonical_sha256(self.operation))
        identity = classify_fault(self.trace).liability_id
        self.graph = DependencyGraph(self.task_id, (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(identity,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        self.completion = TaskCompletionBinding.for_graph(self.base.ledger.scope, self.graph, 'completion')
        self.base.liability.initialize(self.p(), self.graph)
        advisory = ProviderRequest('portable-advisory', 'portable-trace', 'nebius', MODEL,
                                   'inert fixture metadata only', 'portable-budget', 128, 20)
        envelope = JobEnvelope.from_request(self.base.ledger.scope, self.task_id, advisory,
                                            deadline_at=160, money_nano=1, risk_units=0)
        self.base.gov.submit_job(self.p(Capability.MANAGE), envelope, completion=self.completion)
        claim = self.base.gov.claim_job(self.p(), self.task_id, 'owned-fixture-worker', 1, lease_seconds=30)
        self.base.gov.begin_job(self.p(), claim)
        now = int(self.base.now.timestamp())
        self.grant = LocalSessionGrant(self.session_id, self.base.ledger.scope, self.workspace, 4,
            ('PORTABLE_RELEASE_ELASTIC_IP',), self.completion.digest, now, now + 120, 1, 0, 10, 20, 4096)
        self.route.create_session(self.p(Capability.OWNER_APPROVAL), self.grant)
        self.warrant = self.authorize()
        self.reservation = ReservationRequest(self.warrant.risk_reservation_id, self.task_id, 'portable-local',
                                               MODEL, canonical_sha256(self.operation), 0, 5)

    def p(self, purpose=Capability.COMMIT):
        return self.base.p(purpose)

    def make_route(self, **changes):
        arguments = {'workspace': self.workspace, 'policy_revision': 4, 'variant': 'portable',
            'probe': self.adapter.probe, 'executor': self.adapter, 'target_guard': self.adapter.target_guard,
            'verifier': self.adapter.verify, 'clock': lambda: int(self.base.now.timestamp()), 'target_settlement': self.port}
        arguments.update(changes)
        return CoreToolRoute(self.base.journal, self.base.liability, **arguments)

    def authorize(self, *, nonce='portable-once', principal=None, money=0, risk=5):
        return self.route.authorize_exact(self.p(Capability.OWNER_APPROVAL) if principal is None else principal,
            self.session_id, self.operation, self.completion, self.graph, self.trace,
            nonce=nonce, model_id=MODEL, money_nano=money, risk_units=risk)

    def dispatch(self, **changes):
        arguments = {'session_id': self.session_id, 'warrant': self.warrant, 'operation': self.operation,
                     'reservation': self.reservation, 'completion': self.completion}
        arguments.update(changes)
        return self.route.dispatch(self.p(), **arguments)

    def head(self):
        return self.base.run_tx(lambda tx: self.port.load(tx), Capability.READ)

    def unknown(self):
        self.assertEqual('Unknown', self.route.inspect(self.p(Capability.READ), self.warrant)['outcome']['contract_type'])

    def test_actual_owned_mutation_and_complete_readback_use_one_existing_core_and_executor(self):
        self.assertEqual('NONE', self.warrant.money_reservation_id)
        self.assertEqual(0, self.warrant.authority_scope.monetary_ceiling.amount)
        self.assertEqual('USD', self.warrant.authority_scope.monetary_ceiling.currency)
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.executor.counters())
        self.assertNotEqual(self.before_bytes, self.path.read_bytes())
        self.assertIs(self.adapter.projection.runner, self.base.journal.ledger.runner)
        self.assertIs(self.adapter.projection.core, self.base.liability.core)
        self.assertEqual('Applied', self.route.reconcile(self.p(), self.warrant, 1)['outcome']['contract_type'])
        row, head = self.head()
        self.assertEqual(5, row.revision)
        self.assertEqual(1, head['generation'])
        self.assertIsNone(head['in_flight'])
        self.assertEqual('CLOSED', self.base.liability.inspect(self.p(Capability.READ), self.task_id)[0].status.value)
        with self.store.target_guard():
            actual = self.store.observe_guarded_inventory()
        self.assertEqual((actual.state_root, actual.resources_root, actual.receipts_root),
                         (head['state_root'], head['resources_root'], head['receipts_root']))

    def test_legacy_authorize_cannot_bypass_exact_owner_policy4(self):
        before = self.base.records()
        with self.assertRaises(ValueError):
            self.route.authorize(self.p(), self.session_id, self.operation, self.completion,
                self.graph, self.trace, nonce='legacy-denied', model_id=MODEL, money_nano=0, risk_units=5)
        self.assertEqual(before, self.base.records())
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_commit_or_read_principal_cannot_make_a_new_exact_owner_decision(self):
        for purpose in [Capability.COMMIT, Capability.READ]:
            with self.subTest(purpose=purpose), self.assertRaises(ValueError):
                self.authorize(nonce='wrong-purpose', principal=self.p(purpose))
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_positive_money_or_zero_risk_cannot_change_the_closed_usd0_profile(self):
        for money, risk in [(1, 5), (0, 0), (True, 5)]:
            with self.subTest(money=money, risk=risk), self.assertRaises(ValueError):
                self.authorize(nonce='changed-budget', money=money, risk=risk)
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_revoked_owner_witness_denies_before_intent_or_target_effect(self):
        self.base.ledger.revoke(self.p(Capability.OWNER_APPROVAL), self.warrant)
        before = self.base.records()
        with self.assertRaisesRegex(ValueError, '^WARRANT_REVOKED$'):
            self.dispatch()
        self.assertEqual(before, self.base.records())
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_unbound_store_and_callable_executor_cannot_replace_the_registered_adapter(self):
        for changes in [{'executor': lambda *args: True}, {'target_settlement': None},
                        {'probe': lambda: True}, {'target_guard': lambda: True}]:
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError):
                self.make_route(**changes)
        self.assertEqual(self.before_bytes, self.path.read_bytes())

    def test_host_read_principal_must_be_explicit_and_cannot_be_a_model_flag(self):
        for principal in [None, {'approved': True}, self.p(Capability.COMMIT)]:
            with self.subTest(principal_type=type(principal).__name__), self.assertRaises(ValueError):
                self.target.CorePortableTarget(self.port, self.store, executor=self.executor,
                    read_principal=principal, clock=lambda: self.base.now)
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_stop_after_payload_seal_is_checked_at_write_not_during_early_prepare(self):
        seal = portable.seal_local_payload
        def stopped(*args, **kwargs):
            result = seal(*args, **kwargs)
            self.base.gov.set_kill(self.p(Capability.MANAGE), True)
            return result
        with patch.object(portable, 'seal_local_payload', new=stopped):
            self.dispatch()
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((1, 0, 0), self.executor.counters())
        self.assertEqual('STARTED', self.head()[1]['in_flight']['phase'])
        self.unknown()

    def test_cancel_after_payload_seal_prevents_write_and_keeps_unknown(self):
        cancel = CancellationToken()
        seal = portable.seal_local_payload
        def cancelled(*args, **kwargs):
            result = seal(*args, **kwargs)
            cancel.cancel()
            return result
        with patch.object(portable, 'seal_local_payload', new=cancelled):
            self.dispatch(cancel=cancel)
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((1, 0, 0), self.executor.counters())
        self.unknown()

    def lose_ack(self, *, phase, require_ack=False):
        commit = LocalCoreTransaction.commit
        lost = []
        def replacement(tx):
            row = tx.get(RecordKind.OPERATION, self.port.head_key)
            flight = None if row is None else row.payload['in_flight']
            selected = (flight is not None and flight['phase'] == phase
                        and (flight['ack'] is not None if require_ack else flight['ack'] is None))
            commit(tx)
            if selected and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        return patch.object(LocalCoreTransaction, 'commit', new=replacement), lost

    def test_committed_start_lost_ack_does_not_run_or_replay_any_executor(self):
        manager, lost = self.lose_ack(phase='STARTED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((0, 0, 0), self.executor.counters())
        self.unknown()

    def test_committed_release_lost_ack_never_writes_or_retries_target(self):
        manager, lost = self.lose_ack(phase='RELEASED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual('RELEASED', self.head()[1]['in_flight']['phase'])
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((1, 0, 0), self.executor.counters())
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((1, 0, 0), self.executor.counters())

    def test_committed_executor_ack_lost_ack_can_settle_by_readback_without_another_effect(self):
        manager, lost = self.lose_ack(phase='RELEASED', require_ack=True)
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual((1, 1, 0), self.executor.counters())
        self.assertEqual('Applied', self.route.reconcile(self.p(), self.warrant, 1)['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.executor.counters())

    def test_resolved_replay_retains_full_core_history_without_target_execution(self):
        self.dispatch()
        self.route.reconcile(self.p(), self.warrant, 1)
        before = self.path.read_bytes(), self.base.records()
        self.assertEqual('Applied', self.dispatch()['outcome']['contract_type'])
        self.assertEqual(before, (self.path.read_bytes(), self.base.records()))
        self.assertEqual((1, 1, 0), self.executor.counters())

    def test_another_unbound_store_cannot_use_a_previous_core_release(self):
        self.dispatch()
        other = portable.PortableStateStore(self.path)
        before = self.path.read_bytes()
        with other.target_guard():
            resources, receipts = other._load()
            with self.assertRaises(portable.PortablePolicyError):
                other._write(resources, receipts)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual((1, 1, 0), self.executor.counters())

    def test_untouched_resource_drift_after_effect_cannot_be_reported_as_applied(self):
        self.dispatch()
        with self.store.target_guard():
            resources, receipts = self.store._load()
            key = next(iter(resources))
            resources[key] = resources[key].model_copy(update={'tags': {'controlled': 'drift'}})
            # Explicit corruption of this private fixture, bypassing product APIs.
            files.atomic_write_private_json(self.path, files.seal_local_payload(
                self.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
        with self.assertRaises(ValueError):
            self.route.reconcile(self.p(), self.warrant, 1)
        self.assertEqual(0, self.head()[1]['generation'])
        self.unknown()

    def test_lock_substitution_is_refused_before_first_actual_executor(self):
        lock = self.path.with_name('inventory.json.lock')
        old = lock.with_name('old-private-guard')
        lock.rename(old)
        lock.write_bytes(b'')
        lock.chmod(0o600)
        with self.assertRaisesRegex(ValueError, '^PORTABLE_TARGET_GUARD_BINDING$'):
            self.dispatch()
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_duplicate_owner_nonce_for_same_task_operation_does_not_issue_an_alias(self):
        before = self.base.records()
        with self.assertRaisesRegex(ValueError, 'OPERATION_ALREADY_AUTHORIZED'):
            self.authorize(nonce='another-exact-nonce')
        self.assertEqual(before, self.base.records())
        self.assertEqual((0, 0, 0), self.executor.counters())


    def after_seal(self, action):
        seal = portable.seal_local_payload
        def boundary(*args, **kwargs):
            result = seal(*args, **kwargs)
            action()
            return result
        with patch.object(portable, 'seal_local_payload', new=boundary):
            result = self.dispatch()
        self.assertEqual('Unknown', result['outcome']['contract_type'])
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((1, 0, 0), self.executor.counters())
        self.assertEqual('STARTED', self.head()[1]['in_flight']['phase'])
        self.unknown()

    def test_owner_warrant_revocation_after_seal_is_checked_before_physical_release(self):
        self.after_seal(lambda: self.base.ledger.revoke(self.p(Capability.OWNER_APPROVAL), self.warrant))

    def test_session_revocation_after_seal_is_checked_before_physical_release(self):
        self.after_seal(lambda: self.route.revoke_session(self.p(Capability.MANAGE), self.session_id))

    def test_warrant_expiry_after_seal_is_checked_even_while_grant_is_still_live(self):
        self.assertLess(int(self.warrant.expires_at.timestamp()), self.grant.expires_at)
        def expire():
            self.base.now = self.warrant.expires_at
        self.after_seal(expire)

    def test_job_lease_expiry_after_seal_is_checked_before_physical_release(self):
        def expire():
            self.base.gov.clock = lambda: 131
        self.after_seal(expire)

    def test_owner_epoch_takeover_after_seal_cannot_release_the_old_warrant(self):
        self.after_seal(lambda: self.base.gov.start_epoch(self.p(Capability.MANAGE)))

    def test_clock_rollback_after_seal_cannot_release_a_write(self):
        def rollback():
            self.base.gov.clock = lambda: 99
        self.after_seal(rollback)

    def test_none_boolean_model_callback_and_detached_dict_are_not_live_store_ports(self):
        before = self.base.records()
        with self.store.target_guard():
            for value in [None, True, lambda: True, {'phase': 'RELEASED', 'approved': True}]:
                with (self.subTest(value_type=type(value).__name__),
                      self.assertRaises(portable.PortablePolicyError), self.store._core_write_lifetime(value)):
                    self.fail('UNBOUND_PORT_WAS_ACCEPTED')
        self.assertEqual(before, self.base.records())
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((0, 0, 0), self.executor.counters())

    def test_all_core_callbacks_are_db_only_and_do_not_read_or_write_the_store(self):
        run = self.base.runner.run
        def checked(context, callback):
            def sql(tx):
                with (patch.object(self.store, 'observe_guarded_inventory', side_effect=AssertionError('STORE_READ_IN_SQL')),
                      patch.object(self.store, '_write', side_effect=AssertionError('STORE_WRITE_IN_SQL')),
                      patch.object(portable, 'read_private_json', side_effect=AssertionError('FILE_READ_IN_SQL')),
                      patch.object(portable, 'atomic_write_private_json', side_effect=AssertionError('FILE_WRITE_IN_SQL'))):
                    return callback(tx)
            return run(context, sql)
        with patch.object(self.base.runner, 'run', side_effect=checked):
            self.dispatch()
            self.assertEqual('Applied', self.route.reconcile(self.p(), self.warrant, 1)['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.executor.counters())

    def test_release_sql_retry_reuses_one_immutable_candidate_and_one_executor_attempt(self):
        commit = LocalCoreTransaction.commit
        retried = []
        class Retry(Exception):
            sqlstate = '40001'
        def conflict(tx):
            row = tx.get(RecordKind.OPERATION, self.port.head_key)
            flight = None if row is None else row.payload['in_flight']
            if flight is not None and flight['phase'] == 'RELEASED' and flight['ack'] is None and not retried:
                retried.append(True)
                raise Retry()
            return commit(tx)
        with (patch.object(LocalCoreTransaction, 'commit', new=conflict),
              patch.object(self.port, 'before_release_in_transaction', wraps=self.port.before_release_in_transaction) as release,
              patch.object(self.adapter, 'candidate_observation', wraps=self.adapter.candidate_observation) as observe):
            self.dispatch()
            self.assertEqual(2, release.call_count)
            self.assertIs(release.call_args_list[0].kwargs['write_observation'],
                          release.call_args_list[1].kwargs['write_observation'])
            self.assertEqual(1, observe.call_count)
        self.assertEqual([True], retried)
        self.assertEqual((1, 1, 0), self.executor.counters())
        self.assertEqual('Applied', self.route.reconcile(self.p(), self.warrant, 1)['outcome']['contract_type'])

    def test_release_callback_failure_rolls_back_phase_and_never_retries_the_effect(self):
        release = self.port.before_release_in_transaction
        def rollback(*args, **kwargs):
            release(*args, **kwargs)
            raise ValueError('CONTROLLED_AFTER_RELEASE_BEFORE_COMMIT')
        with patch.object(self.port, 'before_release_in_transaction', side_effect=rollback):
            self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual('STARTED', self.head()[1]['in_flight']['phase'])
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual((1, 0, 0), self.executor.counters())

    def test_missing_receipt_after_release_ack_loss_is_not_a_no_effect_certificate(self):
        manager, lost = self.lose_ack(phase='RELEASED')
        with manager, self.assertRaises(CommitOutcomeUnknown):
            self.dispatch()
        self.assertEqual([True], lost)
        with self.assertRaises(ValueError):
            self.route.reconcile(self.p(), self.warrant, 1)
        self.assertEqual(0, self.head()[1]['generation'])
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.unknown()

    def test_direct_zero_journal_rejects_a_non_usd_warrant_without_consumption(self):
        from dataclasses import replace
        from decimal import Decimal

        from lab.archaioa.authority import Money
        from runtime.mission.warrant import approval_digest
        scope = replace(self.warrant.authority_scope, monetary_ceiling=Money(Decimal(0), 'XTS'))
        bad = replace(self.warrant, warrant_id='non-usd-warrant', nonce='non-usd-nonce', authority_scope=scope)
        bad = replace(bad, approval_digest=approval_digest(bad))
        self.base.ledger.approve(self.p(Capability.OWNER_APPROVAL), bad)
        before = self.base.records()
        with self.assertRaisesRegex(ValueError, '^LOCAL_ZERO_USD_REQUIRED$'):
            self.base.journal.start_local_zero(self.p(), bad, self.operation, self.reservation)
        self.assertEqual(before, self.base.records())
        self.assertIsNone(self.base.ledger.inspect(self.p(Capability.READ), bad))
        self.assertEqual(self.before_bytes, self.path.read_bytes())

    def test_extra_untouched_receipt_after_effect_cannot_hide_in_full_readback(self):
        import test_nz13_portable_domain_input as facts
        fixture = facts.PortableDomainInputTests('test_valid_exact_pack_is_facts_only_and_has_complete_storage_root')
        fixture.setUp()
        extra = fixture.historical_receipt()
        self.dispatch()
        with self.store.target_guard():
            resources, receipts = self.store._load()
            receipts[extra.idempotency_key] = extra
            files.atomic_write_private_json(self.path, files.seal_local_payload(
                self.store._payload(resources, receipts), payload_type=portable._INVENTORY_PAYLOAD_TYPE))
        with self.assertRaises(ValueError):
            self.route.reconcile(self.p(), self.warrant, 1)
        self.assertEqual(0, self.head()[1]['generation'])
        self.unknown()

    def test_deleted_settled_history_prevents_a_retained_success_or_another_write(self):
        self.dispatch()
        self.route.reconcile(self.p(), self.warrant, 1)
        self.base.delete(self.port.history_key(self.warrant))
        before = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, '^TARGET_HISTORY_INTEGRITY$'):
            self.dispatch()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual((1, 1, 0), self.executor.counters())

    def legacy_effect(self):
        import threading

        from lab.archaioa.decision_root import DecisionDependencyRoot
        from lab.archaioa.evidence import EvidenceRef
        from lab.archaioa.outcome import Applied
        from runtime.mission.liability import Reconciliation
        from runtime.mission.tools import SessionGrant, TargetSnapshot
        mutex = threading.RLock()
        snapshot = TargetSnapshot('sha256:' + 'f' * 64, 'legacy-revision', DecisionDependencyRoot())
        calls = []
        def execute(*args):
            calls.append(True)
        def verify(operation, warrant):
            self.assertEqual([True], calls)
            return Reconciliation(warrant.operation_hash, Applied('legacy-receipt'),
                EvidenceRef('legacy-receipt', 'receipt', 'sha256:' + '1' * 64, 'v1'),
                EvidenceRef('legacy-readback', 'independent-readback', 'sha256:' + '2' * 64, 'v1'))
        route = CoreToolRoute(self.base.journal, self.base.liability, workspace=self.workspace, policy_revision=1,
            probe=lambda: snapshot, executor=execute, target_guard=lambda: mutex, verifier=verify,
            clock=lambda: int(self.base.now.timestamp()))
        operation = route.operation({'action': 'write_file', 'path': 'src/legacy.py', 'content': 'inert'}, snapshot)
        trace = FaultTrace(FaultKind.LOST_ACK, 'legacy-task', 'legacy-request', 'sha256:' + canonical_sha256(operation))
        graph = DependencyGraph('legacy-task', (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(classify_fault(trace).liability_id,)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',))))
        completion = TaskCompletionBinding.for_graph(self.base.ledger.scope, graph, 'completion')
        self.base.liability.initialize(self.p(), graph)
        request = ProviderRequest('legacy-advisory', 'legacy-trace', 'nebius', MODEL,
                                  'inert fixture metadata', 'legacy-budget', 128, 20)
        envelope = JobEnvelope.from_request(self.base.ledger.scope, 'legacy-task', request,
                                            deadline_at=160, money_nano=1, risk_units=0)
        self.base.gov.submit_job(self.p(Capability.MANAGE), envelope, completion=completion)
        claim = self.base.gov.claim_job(self.p(), 'legacy-task', 'legacy-worker', 1, lease_seconds=30)
        self.base.gov.begin_job(self.p(), claim)
        now = int(self.base.now.timestamp())
        grant = SessionGrant('legacy-grant', self.base.ledger.scope, self.workspace, 1, ('PROJECT_WRITE',),
                             completion.digest, now, now + 120, 1, 100, 10, 20, 4096)
        route.create_session(self.p(Capability.OWNER_APPROVAL), grant)
        warrant = route.authorize(self.p(), grant.session_id, operation, completion, graph, trace,
                                  nonce='legacy-once', model_id=MODEL, money_nano=50, risk_units=5)
        reservation = ReservationRequest(warrant.money_reservation_id, 'legacy-task', 'synthetic', MODEL,
                                         canonical_sha256(operation), 50, 5)
        route.dispatch(self.p(), session_id=grant.session_id, warrant=warrant, operation=operation,
                       reservation=reservation, completion=completion)
        route.reconcile(self.p(), warrant, 1)
        self.assertEqual([True], calls)
        return route, warrant

    def test_mixed_closed_positive_money_context_and_usd0_use_the_existing_budget_join(self):
        self.legacy_effect()
        self.assertEqual('Unknown', self.dispatch()['outcome']['contract_type'])
        self.assertEqual('Applied', self.route.reconcile(self.p(), self.warrant, 1)['outcome']['contract_type'])
        self.assertEqual((1, 1, 0), self.executor.counters())
        budget = self.base.gov.inspect(self.p(Capability.READ))
        self.assertEqual(0, budget['reservations'][self.warrant.risk_reservation_id]['money_nano'])
        self.assertNotIn('NONE', budget['reservations'])

    def test_deleted_legacy_context_cannot_hide_charged_money_in_a_new_usd0_start(self):
        route, warrant = self.legacy_effect()
        self.base.delete(route._context_key(warrant))
        before = self.base.records()
        with self.assertRaisesRegex(ValueError, '^TOOL_CONTEXT_REQUIRED$'):
            self.dispatch()
        self.assertEqual(before, self.base.records())
        self.assertEqual(self.before_bytes, self.path.read_bytes())
        self.assertEqual((0, 0, 0), self.executor.counters())
