"""Exact owner authority on the existing synthetic Core route; no host effects.

The target is the existing inert in-memory fixture. Physical containment,
portable inventory and Native HTTP admission require separate acceptance.
"""

import unittest
from dataclasses import replace
from unittest.mock import patch

import test_core_tool_composition as support
from q09_support import Fixture

from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.governor import ReservationRequest
from runtime.mission.liability import CoreLiabilityLedger
from runtime.mission.sandbox_contracts import TOOL_POLICY_VERSIONS
from runtime.mission.tools import CoreToolRoute


class ExactMockAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.case = support.CoreToolCompositionTests(
            'test_real_synthetic_attempt_opens_required_g2_and_holds_exposure'
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.fx = self.case.fx

    def strict(self, *, new_task=True):
        self.assertIn(3, TOOL_POLICY_VERSIONS,
                      'Missing opt-in exact-owner policy on the existing Core route')
        case = self.case
        case.route = CoreToolRoute(
            self.fx.journal, case.liability, workspace='workspace-1',
            policy_revision=3, probe=lambda: case.current, executor=case.execute,
            target_guard=lambda: case.lifecycle, verifier=case.verify,
            clock=lambda: case.now,
        )
        if new_task:
            from runtime.mission.job_contracts import JobEnvelope
            from runtime.providers.nvidia import ProviderRequest

            task_id = 'exact-tool-task'
            case.trace = support.FaultTrace(
                support.FaultKind.LOST_ACK, task_id, 'exact-owner-request',
                'sha256:' + support.canonical_sha256(case.operation),
            )
            case.identity = support.classify_fault(case.trace).liability_id
            case.graph = support.DependencyGraph(task_id, (
                support.DependencyNode('effect', support.NodeKind.OPERATION,
                                       liability_ids=(case.identity,)),
                support.DependencyNode('completion', support.NodeKind.COMPLETION_CANDIDATE,
                                       ('effect',)),
            ))
            case.binding = support.TaskCompletionBinding.for_graph(
                self.fx.ledger.scope, case.graph, 'completion')
            case.liability.initialize(self.fx.p(), case.graph)
            request = ProviderRequest('exact-advisory', 'exact-trace', 'nebius',
                                      support.MODEL, 'fixture', 'budget', 128, 20)
            envelope = JobEnvelope.from_request(self.fx.ledger.scope, task_id, request,
                                                deadline_at=160, money_nano=1, risk_units=0)
            self.fx.gov.submit_job(self.fx.p(Capability.MANAGE), envelope,
                                   completion=case.binding)
            case.claim = self.fx.gov.claim_job(self.fx.p(), task_id, 'fixture-worker',
                                               1, lease_seconds=30)
            self.fx.gov.begin_job(self.fx.p(), case.claim)
        case.grant = replace(case.grant, session_id=self.fx.p().actor_session_id,
                             completion_digest=case.binding.digest, policy_revision=3)
        case.route.create_session(self.fx.p(Capability.OWNER_APPROVAL), case.grant)
        return case

    def approve(self, nonce='exact-owner-nonce'):
        case = self.case
        method = getattr(case.route, 'authorize_exact', None)
        self.assertTrue(callable(method), 'Missing exact owner approval entrypoint')
        case.warrant = method(
            self.fx.p(Capability.OWNER_APPROVAL), case.grant.session_id,
            case.operation, case.binding, case.graph, case.trace, nonce=nonce,
            model_id=support.MODEL, money_nano=50, risk_units=5,
        )
        case.request = ReservationRequest(
            case.warrant.money_reservation_id, case.binding.task_id, 'synthetic', support.MODEL,
            support.canonical_sha256(case.operation), 50, 5,
        )
        return case.warrant

    def corrupt_witness(self, **updates):
        case = self.case

        def change(tx):
            row = tx.get(RecordKind.APPROVAL, self.fx.ledger._key(case.warrant))
            self.assertIsNotNone(row, 'No canonical owner witness was written')
            tx.replace(StoredRecord(
                row.kind, row.record_id, row.scope, row.revision + 1,
                {**row.payload, **updates},
            ), expected_revision=row.revision)

        self.fx.ledger._run(self.fx.p(Capability.OWNER_APPROVAL),
                            Capability.OWNER_APPROVAL, change)

    def test_exact_owner_witness_precedes_unknown_one_attempt_and_independent_readback(self):
        case = self.strict()
        warrant = self.approve()
        row = self.fx.journal._run(
            self.fx.p(Capability.READ), Capability.READ,
            lambda tx: tx.get(RecordKind.APPROVAL, self.fx.ledger._key(warrant)),
        )
        self.assertEqual('aioa.warrant-owner-witness.v1', row.payload['schema'])
        self.assertEqual(self.fx.p().actor_session_id, row.payload['session_id'])
        self.assertEqual(warrant.digest(), row.payload['warrant_digest'])
        self.assertEqual([], case.calls)
        self.assertEqual('Unknown', case.dispatch()['outcome']['contract_type'])
        self.assertEqual(1, len(case.calls))
        self.assertEqual('Applied', case.route.reconcile(
            self.fx.p(), warrant, 1)['outcome']['contract_type'])
        before = case.path.read_bytes()
        self.assertEqual('Applied', case.dispatch()['outcome']['contract_type'])
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_old_authorize_cannot_delegate_around_exact_owner_policy(self):
        case = self.strict()
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.authorize('unauthorized-delegation')
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_exact_approval_rejects_commit_read_critic_and_caller_flags(self):
        case = self.strict()
        method = getattr(case.route, 'authorize_exact', None)
        self.assertTrue(callable(method))
        for principal in (self.fx.p(), self.fx.p(Capability.READ),
                          self.fx.core.critic_candidate(), {'approved': True}):
            before = case.path.read_bytes()
            with self.subTest(principal_type=type(principal).__name__), self.assertRaises(ValueError):
                method(principal, case.grant.session_id, case.operation,
                       case.binding, case.graph, case.trace, nonce='wrong-purpose',
                       model_id=support.MODEL, money_nano=50, risk_units=5)
            self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_current_owner_can_register_separate_task_scoped_grants(self):
        case = self.strict()
        try:
            case.route.create_session(self.fx.p(Capability.OWNER_APPROVAL),
                                      replace(case.grant, session_id='second-task-grant'))
        except ValueError as error:
            self.fail(f'One owner session cannot be limited to one lifetime task grant: {error}')
        self.assertEqual([], case.calls)

    def test_witness_revocation_denies_before_start(self):
        case = self.strict()
        self.approve()
        self.corrupt_witness(revoked=True)
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.dispatch()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_owner_session_substitution_denies_before_start(self):
        case = self.strict()
        self.approve()
        self.corrupt_witness(session_id='foreign-owner-session')
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.dispatch()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_revocation_after_start_is_unknown_without_target_attempt(self):
        case = self.strict()
        self.approve()
        probes = []

        def probe():
            probes.append(1)
            if len(probes) == 2:
                self.fx.ledger.revoke(self.fx.p(Capability.OWNER_APPROVAL), case.warrant)
            return case.current

        case.route.probe = probe
        with self.assertRaises(ValueError):
            case.dispatch()
        self.assertEqual([], case.calls)
        self.assertEqual('Unknown', case.route.inspect(
            self.fx.p(Capability.READ), case.warrant)['outcome']['contract_type'])
        self.assertEqual('OPEN', case.liability.inspect(
            self.fx.p(Capability.READ), case.binding.task_id)[0].status.value)
        reservations = self.fx.gov.inspect(self.fx.p(Capability.READ))['reservations']
        self.assertEqual('UNKNOWN', reservations[case.warrant.risk_reservation_id]['state'])

    def test_lost_start_ack_never_replays_even_with_exact_human_witness(self):
        case = self.strict()
        self.approve()
        original = support.DurableTransaction.commit

        def lost(tx):
            changed = tx.snapshot != tx.factory.state
            original(tx)
            if changed:
                raise CommitOutcomeUnknown()

        with patch.object(support.DurableTransaction, 'commit', lost), self.assertRaises(CommitOutcomeUnknown):
            case.dispatch()
        self.assertEqual([], case.calls)
        self.assertEqual('Unknown', case.dispatch()['outcome']['contract_type'])
        self.assertEqual([], case.calls)

    def test_restart_keeps_readback_but_old_approval_cannot_start_new_effect(self):
        case = self.strict()
        self.approve()
        fresh = Fixture(case.path)
        self.addCleanup(fresh.close)
        liability = CoreLiabilityLedger(fresh.core, fresh.runner, fresh.ledger.scope)
        route = CoreToolRoute(
            fresh.journal, liability, workspace='workspace-1', policy_revision=3,
            probe=lambda: case.current, executor=case.execute,
            target_guard=lambda: case.lifecycle, verifier=case.verify,
            clock=lambda: case.now,
        )
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            route.dispatch(fresh.p(), session_id=case.grant.session_id,
                           warrant=case.warrant, operation=case.operation,
                           reservation=case.request, completion=case.binding)
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_completed_effect_can_be_read_after_restart_without_new_executor_call(self):
        case = self.strict()
        self.approve()
        case.dispatch()
        case.route.reconcile(self.fx.p(), case.warrant, 1)
        fresh = Fixture(case.path)
        self.addCleanup(fresh.close)
        route = CoreToolRoute(
            fresh.journal,
            CoreLiabilityLedger(fresh.core, fresh.runner, fresh.ledger.scope),
            workspace='workspace-1', policy_revision=3,
            probe=lambda: self.fail('Historical readback must not probe target'),
            executor=lambda *_: self.fail('Historical readback must not execute'),
            target_guard=lambda: case.lifecycle,
            verifier=lambda *_: self.fail('Resolved readback must not reverify'),
            clock=lambda: case.now,
        )
        before = case.path.read_bytes()
        self.assertEqual('Applied', route.inspect(
            fresh.p(Capability.READ), case.warrant)['outcome']['contract_type'])
        self.assertEqual('Applied', route.reconcile(
            fresh.p(), case.warrant, 1)['outcome']['contract_type'])
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_duplicate_exact_nonce_is_denied_without_rewriting_owner_witness(self):
        case = self.strict()
        self.approve()
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_changed_operation_cannot_reuse_original_completion_approval(self):
        case = self.strict()
        case.operation = {**case.operation, 'payload': {
            **case.operation['payload'], 'content': 'changed target bytes',
        }}
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def two_effects(self, **kwargs):
        case = self.strict()
        method = getattr(case.route, 'authorize_exact', None)
        self.assertTrue(callable(method))

        def approve(_commit_principal, *args, **options):
            return method(self.fx.p(Capability.OWNER_APPROVAL), *args, **options)

        # Only the existing fixture's setup API is translated to exact owner
        # approval. Product dispatch/ledger/context/accounting are unchanged.
        with patch.object(case.route, 'authorize', side_effect=approve):
            try:
                values = case.two_effects(**kwargs)
            except ValueError as error:
                self.fail(f'Exact owner fixture setup was denied: {error}')
        return case, values

    def test_exact_context_money_cap_includes_settled_effects(self):
        case, values = self.two_effects(second_money=60)
        case.route.dispatch(self.fx.p(), **values[0])
        case.route.reconcile(self.fx.p(), values[0]['warrant'], 1)
        before = case.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'SESSION_BUDGET_EXCEEDED'):
            case.route.dispatch(self.fx.p(), **values[1])
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_exact_context_risk_cap_includes_settled_effects(self):
        case, values = self.two_effects(second_money=50, second_risk=6)
        case.route.dispatch(self.fx.p(), **values[0])
        case.route.reconcile(self.fx.p(), values[0]['warrant'], 1)
        before = case.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'SESSION_BUDGET_EXCEEDED'):
            case.route.dispatch(self.fx.p(), **values[1])
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_renamed_exact_context_cannot_hide_settled_exposure(self):
        case, values = self.two_effects(second_money=40)
        case.route.dispatch(self.fx.p(), **values[0])
        case.route.reconcile(self.fx.p(), values[0]['warrant'], 1)

        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION,
                         case.route._context_key(values[0]['warrant']))
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1,
                                   {**row.payload, 'schema': 'hidden-exact-context'}),
                       expected_revision=row.revision)

        self.fx.journal._run(self.fx.p(), Capability.COMMIT, corrupt)
        before = case.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'TOOL_CONTEXT_REQUIRED'):
            case.route.dispatch(self.fx.p(), **values[1])
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_exact_context_cannot_be_downgraded_to_delegated_context(self):
        from runtime.mission.tools import CONTEXT

        case = self.strict()
        self.approve()

        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION, case.route._context_key(case.warrant))
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1,
                                   {**row.payload, 'schema': CONTEXT}),
                       expected_revision=row.revision)

        self.fx.journal._run(self.fx.p(), Capability.COMMIT, corrupt)
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.dispatch()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_historical_owner_witness_must_match_grant_assignment_revision(self):
        case = self.strict()
        self.approve()
        case.dispatch()
        case.route.reconcile(self.fx.p(), case.warrant, 1)
        self.corrupt_witness(assignment_revision=2)
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.route.inspect(self.fx.p(Capability.READ), case.warrant)
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual(1, len(case.calls))

    def test_strict_grant_schema_cannot_be_downgraded_to_legacy_session(self):
        from runtime.mission.tools import SESSION

        case = self.strict()
        self.approve()

        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION,
                         case.route.session_key(case.grant.session_id))
            payload = {key: value for key, value in row.payload.items()
                       if key != 'owner_session_id'}
            payload['schema'] = SESSION
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope,
                                   row.revision + 1, payload),
                       expected_revision=row.revision)

        self.fx.journal._run(self.fx.p(), Capability.COMMIT, corrupt)
        before = case.path.read_bytes()
        with self.assertRaises(ValueError):
            case.dispatch()
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_exact_approval_cannot_alias_dormant_legacy_authorization(self):
        case = self.strict(new_task=False)
        before = case.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'OPERATION_ALREADY_AUTHORIZED'):
            self.approve('duplicate-of-dormant-legacy')
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_second_nonce_cannot_alias_an_unused_exact_approval(self):
        case = self.strict()
        self.approve('first-unused-exact')
        before = case.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'OPERATION_ALREADY_AUTHORIZED'):
            self.approve('second-unused-exact')
        self.assertEqual(before, case.path.read_bytes())
        self.assertEqual([], case.calls)

    def test_concurrent_duplicate_exact_approvals_write_only_one_owner_witness(self):
        from concurrent.futures import ThreadPoolExecutor

        case = self.strict()
        method = getattr(case.route, 'authorize_exact', None)
        self.assertTrue(callable(method))

        def approve_once(nonce):
            try:
                method(self.fx.p(Capability.OWNER_APPROVAL), case.grant.session_id,
                       case.operation, case.binding, case.graph, case.trace, nonce=nonce,
                       model_id=support.MODEL, money_nano=50, risk_units=5)
            except ValueError as error:
                return str(error)
            return 'APPROVED'

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(approve_once, ('concurrent-exact-1', 'concurrent-exact-2')))
        self.assertEqual(['APPROVED', 'OPERATION_ALREADY_AUTHORIZED'], sorted(results))
        witnesses = self.fx.journal._run(self.fx.p(Capability.READ), Capability.READ,
                                         lambda tx: tx.scan(RecordKind.APPROVAL, limit=1024))
        self.assertEqual(1, len(witnesses))
        self.assertEqual([], case.calls)
