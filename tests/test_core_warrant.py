"""Offline durable-port synthetic human decisions; no effect executor."""
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest

from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from runtime.core_admission import Capability, AdmissionError
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.mission.warrant import CoreWarrantLedger, approval_digest
from nv03_support import DurableFactory, DurableTransaction
from test_dual_governor import core, SCOPE
from lab_archaioa import test_warrant as lab_warrant
from unittest.mock import patch


class CoreWarrantTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'warrant.json'
        self.core = core(); self.addCleanup(self.core.close)
        self.runner = TransactionRunner(self.core, DurableFactory(self.path)); self.addCleanup(self.runner.close)
        original = lab_warrant.WarrantTests().fixture()
        owner = canonical_sha256(SCOPE)
        self.warrant = replace(original, owner_scope=owner,
            authority_scope=replace(original.authority_scope, owner_scope=owner))
        self.warrant = replace(self.warrant, approval_digest=approval_digest(self.warrant))
        self.now = self.warrant.issued_at
        self.ledger = CoreWarrantLedger(self.core, self.runner, SCOPE, clock=lambda: self.now)

    def p(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def approve(self):
        self.ledger.approve(self.p(Capability.OWNER_APPROVAL), self.warrant)

    def test_no_approval_no_consumption(self):
        with self.assertRaisesRegex(ValueError, 'HUMAN_APPROVAL_REQUIRED'):
            self.ledger.consume(self.p(), self.warrant)

    def test_model_github_unsealed_and_wrong_purpose_cannot_approve(self):
        human = self.p(Capability.OWNER_APPROVAL)
        for principal in (None, {'actor': 'github'}, self.core.critic_candidate(),
                          replace(human, _seal=b'forged'), self.p()):
            with self.assertRaises(AdmissionError):
                self.ledger.approve(principal, self.warrant)
        self.assertFalse(self.path.exists())

    def test_exact_human_approval_consumes_once_with_ledger_receipt(self):
        self.approve()
        receipt = self.ledger.consume(self.p(), self.warrant)
        self.assertFalse(receipt['effect_verified'])
        self.assertFalse(receipt['grants_replay'])
        self.assertEqual(receipt, self.ledger.inspect(self.p(Capability.READ), self.warrant))
        with self.assertRaisesRegex(ValueError, 'ALREADY_CONSUMED'):
            self.ledger.consume(self.p(), self.warrant)

    def test_restart_retains_barrier_and_nonce_cannot_change_task(self):
        self.approve(); self.ledger.consume(self.p(), self.warrant)
        runner = TransactionRunner(self.core, DurableFactory(self.path)); self.addCleanup(runner.close)
        other = CoreWarrantLedger(self.core, runner, SCOPE, clock=lambda: self.now)
        with self.assertRaisesRegex(ValueError, 'ALREADY_CONSUMED'):
            other.consume(self.p(), self.warrant)
        changed = replace(self.warrant, task_id='other',
                          authority_scope=replace(self.warrant.authority_scope, task_scope='other'))
        changed = replace(changed, approval_digest=approval_digest(changed))
        with self.assertRaisesRegex(ValueError, 'NONCE_ALREADY_REGISTERED'):
            other.approve(self.p(Capability.OWNER_APPROVAL), changed)

    def test_all_changed_exact_bindings_deny_without_consuming(self):
        self.approve()
        scope = self.warrant.authority_scope
        modifications = [dict(operation_hash='sha256:'+'d'*64), dict(expected_target_revision='r2'),
            dict(lease_epoch=1), dict(money_reservation_id='other'), dict(risk_reservation_id='other'),
            dict(approval_digest='sha256:'+'d'*64), dict(nonce='different'),
            dict(task_id='other', authority_scope=replace(scope, task_scope='other')),
            dict(target_fingerprint='sha256:'+'d'*64,
                 authority_scope=replace(scope, target_scope='sha256:'+'d'*64)),
            dict(decision_dependency_root=DecisionDependencyRoot((EvidenceRef('e','context','sha256:'+'e'*64,'v1'),)))]
        for change in modifications:
            with self.subTest(change=tuple(change)), self.assertRaises(ValueError):
                self.ledger.consume(self.p(), replace(self.warrant, **change))
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), self.warrant))

    def test_expired_and_future_decisions_deny(self):
        self.approve()
        for now in (self.warrant.expires_at, self.warrant.issued_at - timedelta(seconds=1)):
            self.now = now
            with self.assertRaisesRegex(ValueError, 'WARRANT_EXPIRED'):
                self.ledger.consume(self.p(), self.warrant)

    def test_child_replaces_parent_and_preserves_one_use(self):
        self.approve()
        child = replace(self.warrant, warrant_id='child', expires_at=self.warrant.expires_at-timedelta(minutes=1),
                        authority_scope=replace(self.warrant.authority_scope,
                            expires_at=self.warrant.expires_at-timedelta(minutes=1)))
        self.ledger.delegate(self.p(), self.warrant, child)
        with self.assertRaises(ValueError):self.ledger.consume(self.p(), self.warrant)
        self.ledger.consume(self.p(), child)
        with self.assertRaises(ValueError):self.ledger.consume(self.p(), child)
        with self.assertRaises(ValueError):self.ledger.delegate(self.p(), child, child)

    def test_delegation_escalation_denied(self):
        self.approve()
        for child in (replace(self.warrant, nonce='new'), replace(self.warrant, lease_epoch=1),
                      replace(self.warrant, expected_target_revision='r2'),
                      replace(self.warrant, authority_scope=replace(self.warrant.authority_scope,
                          operation_classes=('write','delete')))):
            with self.assertRaisesRegex(ValueError, 'WARRANT_ESCALATION'):
                self.ledger.delegate(self.p(), self.warrant, child)
        self.assertIsNone(self.ledger.inspect(self.p(Capability.READ), self.warrant))

    def test_ddr_reordering_and_unrelated_evidence_policy(self):
        a = EvidenceRef('a','context','sha256:'+'a'*64,'v1')
        b = EvidenceRef('b','context','sha256:'+'b'*64,'v1')
        self.assertEqual(DecisionDependencyRoot((a,b)), DecisionDependencyRoot((b,a)))
        self.warrant = replace(self.warrant, decision_dependency_root=DecisionDependencyRoot((a,b)))
        self.warrant = replace(self.warrant, approval_digest=approval_digest(self.warrant))
        self.approve()
        # Host excludes unrelated refs; changed selected version is stale.
        changed = replace(self.warrant, decision_dependency_root=DecisionDependencyRoot((a,replace(b,source_version='v2'))))
        with self.assertRaises(ValueError):self.ledger.consume(self.p(), changed)
        self.ledger.consume(self.p(), replace(self.warrant, decision_dependency_root=DecisionDependencyRoot((b,a))))

    def test_lost_commit_ack_readback_never_grants_second_use(self):
        self.approve()
        original = DurableTransaction.commit
        def lost(tx):
            original(tx)
            raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction, 'commit', lost):
            with self.assertRaises(CommitOutcomeUnknown):self.ledger.consume(self.p(), self.warrant)
        self.assertFalse(self.ledger.inspect(self.p(Capability.READ), self.warrant)['grants_replay'])
        with self.assertRaises(ValueError):self.ledger.consume(self.p(), self.warrant)

    def test_competing_consumers_have_only_one_success(self):
        import concurrent.futures
        self.approve()
        runner = TransactionRunner(self.core, DurableFactory(self.path)); self.addCleanup(runner.close)
        other = CoreWarrantLedger(self.core, runner, SCOPE, clock=lambda: self.now)
        def consume(ledger):
            try:
                ledger.consume(self.p(), self.warrant)
                return 'CONSUMED'
            except ValueError:
                return 'DENIED'
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(consume, (self.ledger, other)))
        self.assertEqual(['CONSUMED', 'DENIED'], sorted(results))

    def test_approval_digest_and_owner_must_match_exact_human_decision(self):
        for warrant in (replace(self.warrant, approval_digest='sha256:'+'f'*64),
                        replace(self.warrant, owner_scope='other-owner',
                            authority_scope=replace(self.warrant.authority_scope, owner_scope='other-owner'))):
            with self.assertRaises(ValueError):
                self.ledger.approve(self.p(Capability.OWNER_APPROVAL), warrant)
        self.assertFalse(self.path.exists())

    def test_fresh_process_reads_consumption_but_cannot_reconsume(self):
        import subprocess
        import sys
        self.approve(); self.ledger.consume(self.p(), self.warrant)
        fixture = Path(self.temp.name) / 'fixture.json'
        fixture.write_text(self.warrant.to_json())
        script = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'runtime'))
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_dual_governor import core, SCOPE
from nv03_support import DurableFactory
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.warrant import CoreWarrantLedger, WarrantError
from lab.archaioa.warrant import EffectWarrant
c=core()
w=EffectWarrant.from_json(Path(sys.argv[2]).read_text())
r=TransactionRunner(c, DurableFactory(Path(sys.argv[1])))
l=CoreWarrantLedger(c,r,SCOPE,clock=lambda:w.issued_at)
assert l.inspect(c.local_operator(Capability.READ),w)['grants_replay'] is False
try:
    l.consume(c.local_operator(Capability.COMMIT),w)
except WarrantError:
    pass
else:
    raise AssertionError('second consumption')
r.close();c.close()
"""
        result = subprocess.run([sys.executable, '-B', '-c', script, str(self.path), str(fixture)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
