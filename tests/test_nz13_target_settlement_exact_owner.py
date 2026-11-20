"""Composition of the existing exact owner witness and synthetic target facts.

No Portable mutation, production approval or model certification is asserted.
"""

import unittest
from unittest.mock import patch

import test_nz13_exact_mock_authority as exact
import test_nz13_target_settlement_port as target

from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.mission.tools import CoreToolRoute


class ExactOwnerTargetSettlementTests(unittest.TestCase):
    def setUp(self):
        self.fixture = target.TargetSettlementPortTests(
            'test_fresh_start_and_release_share_existing_journal_and_liability')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.base = self.fixture.base
        self.owner = exact.ExactMockAuthorityTests(
            'test_exact_owner_witness_precedes_unknown_one_attempt_and_independent_readback')
        self.owner.case, self.owner.fx = self.base, self.base.fx
        self.owner.strict()  # Creates another real task, not an alias of a started intent.
        self.port = self.fixture.port
        self.base.route = CoreToolRoute(
            self.base.fx.journal, self.base.liability, workspace='workspace-1',
            policy_revision=3, probe=lambda: self.base.current,
            executor=self.fixture.execute, target_guard=lambda: self.base.lifecycle,
            verifier=self.fixture.verify, clock=lambda: self.base.now,
            target_settlement=self.port,
        )
        self.owner.approve('exact-target-owner-nonce')

    def inspect(self):
        return self.base.route.inspect(self.base.fx.p(Capability.READ), self.base.warrant)

    def test_exact_owner_witness_and_durable_target_are_bound_before_start(self):
        witness = self.base.fx.ledger._run(
            self.base.fx.p(Capability.READ), Capability.READ,
            lambda tx: tx.get(RecordKind.APPROVAL, self.base.fx.ledger._key(self.base.warrant)),
        )
        self.assertEqual(self.base.warrant.digest(), witness.payload['warrant_digest'])
        self.assertIn(self.port.binding.evidence(), self.base.warrant.decision_dependency_root.evidence_refs)
        self.assertEqual([], self.base.calls)
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertIn('ack', self.fixture.fact()[1])
        self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        self.assertEqual('RESOLVED', self.fixture.fact()[1]['state'])
        self.assertEqual(1, len(self.base.calls))

    def test_commit_principal_cannot_issue_an_exact_bound_warrant(self):
        before = self.base.path.read_bytes()
        with self.assertRaises(ValueError):
            self.base.route.authorize_exact(
                self.base.fx.p(), self.base.grant.session_id, self.base.operation,
                self.base.binding, self.base.graph, self.base.trace,
                nonce='no-owner-capability', model_id=target.legacy.MODEL,
                money_nano=50, risk_units=5,
            )
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual([], self.base.calls)

    def test_revoked_witness_prevents_target_start(self):
        self.owner.corrupt_witness(revoked=True)
        before = self.base.path.read_bytes()
        with (patch.object(self.port, 'start_in_transaction', wraps=self.port.start_in_transaction) as begin,
              self.assertRaises(ValueError)):
            self.base.dispatch()
        self.assertEqual(0, begin.call_count)
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual([], self.base.calls)

    def test_revocation_between_start_and_release_keeps_unknown_without_effect(self):
        probes = []
        def probe():
            probes.append(True)
            if len(probes) == 2:
                self.base.fx.ledger.revoke(self.base.fx.p(Capability.OWNER_APPROVAL), self.base.warrant)
            return self.base.current
        self.base.route.probe = probe
        with self.assertRaises(ValueError):
            self.base.dispatch()
        self.assertEqual('STARTED', self.fixture.fact()[1]['state'])
        self.assertEqual('Unknown', self.inspect()['outcome']['contract_type'])
        self.assertEqual([], self.base.calls)
        self.assertEqual('OPEN', self.base.liability.inspect(
            self.base.fx.p(Capability.READ), self.base.binding.task_id)[0].status.value)

    def test_expiry_between_start_and_release_never_calls_executor(self):
        probes = []
        def probe():
            probes.append(True)
            if len(probes) == 2:
                self.base.now = self.base.grant.expires_at
            return self.base.current
        self.base.route.probe = probe
        with self.assertRaises(ValueError):
            self.base.dispatch()
        self.assertEqual('STARTED', self.fixture.fact()[1]['state'])
        self.assertEqual([], self.base.calls)
        self.assertEqual('Unknown', self.inspect()['outcome']['contract_type'])

    def test_lost_start_ack_does_not_release_even_with_owner_witness(self):
        commit = target.legacy.DurableTransaction.commit
        lost = []
        def lose_start(transaction):
            started = any(row.record_id == self.port.key and row.payload.get('state') == 'STARTED'
                          for row in transaction.snapshot.values())
            commit(transaction)
            if started and not lost:
                lost.append(True)
                raise CommitOutcomeUnknown()
        with (patch.object(target.legacy.DurableTransaction, 'commit', new=lose_start),
              self.assertRaises(CommitOutcomeUnknown)):
            self.base.dispatch()
        self.assertEqual([True], lost)
        self.assertEqual('Unknown', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual([], self.base.calls)

    def test_plain_route_cannot_reconcile_an_exact_bound_intent(self):
        self.base.dispatch()
        unbound = CoreToolRoute(
            self.base.fx.journal, self.base.liability, workspace='workspace-1',
            policy_revision=3, probe=lambda: self.base.current, executor=self.base.execute,
            target_guard=lambda: self.base.lifecycle, verifier=self.base.verify,
            clock=lambda: self.base.now,
        )
        before = self.base.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'TARGET_PORT_REQUIRED_FOR_DURABLE_CONTEXT'):
            unbound.reconcile(self.base.fx.p(), self.base.warrant, 1)
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(1, len(self.base.calls))
        self.assertEqual([], self.base.verifications)

    def test_revocation_after_effect_allows_fact_reconciliation_without_new_authority(self):
        self.base.dispatch()
        self.base.fx.ledger.revoke(self.base.fx.p(Capability.OWNER_APPROVAL), self.base.warrant)
        with patch.object(self.base.route, 'authorize_exact', side_effect=AssertionError('NO_REAPPROVAL')):
            self.assertEqual('Applied', self.fixture.reconcile()['outcome']['contract_type'])
        self.assertEqual('RESOLVED', self.fixture.fact()[1]['state'])
        self.assertEqual(1, len(self.base.calls))

    def test_resolved_exact_replay_requires_history_without_probe_or_effect(self):
        self.base.dispatch()
        self.fixture.reconcile()
        before = self.base.path.read_bytes()
        with patch.object(self.base.route, 'probe', side_effect=AssertionError('NO_NEW_PROBE')):
            self.assertEqual('Applied', self.base.dispatch()['outcome']['contract_type'])
        self.assertEqual(before, self.base.path.read_bytes())
        self.assertEqual(1, len(self.base.calls))
        self.port.reject_history = True
        with self.assertRaises(ValueError):
            self.base.dispatch()
