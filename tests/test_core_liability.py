"""G2 native-port fixtures; no provider, credential or effect execution."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import tempfile
import unittest

from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.liability import LiabilityStatus
from lab.archaioa.outcome import Applied, NotApplied, Unknown
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind, TaintState
from lab.archaioa.task_semantics import CompletionState
from runtime.core_admission import Capability
from runtime.memory_patch.errors import CommitOutcomeUnknown
from runtime.memory_patch.persistence.ports import TransactionRunner
from native_subprocess_support import native_command
from nv03_support import DurableFactory, DurableTransaction
from test_dual_governor import core, SCOPE

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


class CoreLiabilityTests(unittest.TestCase):
    def setUp(self):
        from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
        self.Ledger, self.Resolution = CoreLiabilityLedger, Reconciliation
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'liabilities.json'
        self.core = core(); self.addCleanup(self.core.close)
        self.factory = DurableFactory(self.path)
        self.runner = TransactionRunner(self.core, self.factory); self.addCleanup(self.runner.close)
        self.trace = FaultTrace(FaultKind.LOST_ACK, 'task1', 'request1', 'sha256:' + 'a' * 64)
        self.identity = classify_fault(self.trace).liability_id
        self.graph = DependencyGraph('task1', (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(self.identity,)),
            DependencyNode('verification', NodeKind.CLAIM, ('effect',)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('verification',)),
        ))
        self.ledger = self.Ledger(self.core, self.runner, SCOPE)

    def principal(self, purpose=Capability.COMMIT):
        return self.core.local_operator(purpose)

    def open(self, ledger=None, trace=None):
        return (ledger or self.ledger).record_unknown(self.principal(), trace or self.trace, self.graph, NOW)

    def completion(self, ledger=None):
        return (ledger or self.ledger).completion(self.principal(Capability.READ), 'task1', 'completion')

    def resolution(self, outcome=None):
        receipt = EvidenceRef('receipt1', 'no-effect-certificate' if type(outcome) is NotApplied else 'receipt',
                              'sha256:' + 'b' * 64, 'v1')
        readback = EvidenceRef('readback1', 'independent-readback', 'sha256:' + 'c' * 64, 'v1')
        return self.Resolution(self.trace.operation_digest, outcome if outcome is not None else Applied('receipt1'), receipt, readback)

    def verified_ledger(self, verifier):
        return self.Ledger(self.core, self.runner, SCOPE, verifier=verifier)

    def test_all_ambiguous_faults_are_durable_unknown_and_block_completion(self):
        for fault in FaultKind:
            outcome = self.open(trace=replace(self.trace, kind=fault))
            self.assertIs(type(outcome), Unknown)
            self.assertEqual(self.identity, outcome.liability_id)
            self.assertEqual(CompletionState.BLOCKED, self.completion().state)
        with self.assertRaises(TypeError):
            bool(outcome)

    def test_idempotency_keeps_first_open_time_and_dependency_refs(self):
        ref = EvidenceRef('dependency1', 'dependency', 'sha256:' + 'd' * 64, 'v1')
        self.ledger.record_unknown(self.principal(), self.trace, self.graph, NOW, dependency_refs=(ref,))
        self.open()
        record = self.ledger.inspect(self.principal(Capability.READ), 'task1')[0]
        self.assertEqual(NOW, record.opened_at)
        self.assertEqual((ref,), record.dependency_refs)

    def test_dependency_taint_includes_verification(self):
        self.open()
        taint = self.ledger.taint(self.principal(Capability.READ), 'task1')
        self.assertTrue(all(node.state is TaintState.TAINTED_BY_LIABILITY for node in taint))

    def test_escalation_survives_reconstruction_and_remains_blocking(self):
        self.open()
        self.ledger.escalate(self.principal(), 'task1', self.identity)
        other = self.Ledger(self.core, self.runner, SCOPE)
        self.assertEqual(LiabilityStatus.ESCALATED, other.inspect(self.principal(Capability.READ), 'task1')[0].status)
        self.assertEqual(CompletionState.BLOCKED, self.completion(other).state)
        self.open()
        self.assertEqual(LiabilityStatus.ESCALATED, other.inspect(self.principal(Capability.READ), 'task1')[0].status)

    def test_no_verifier_no_closure(self):
        self.open()
        with self.assertRaisesRegex(ValueError, 'RECONCILIATION_DISABLED'):
            self.ledger.reconcile(self.principal(), 'task1', self.identity, NOW)
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_absent_or_ambiguous_readback_cannot_close(self):
        self.open()
        for result in (None, Unknown(self.identity), True):
            ledger = self.verified_ledger(lambda trace, record: result)
            with self.assertRaises(ValueError):
                ledger.reconcile(self.principal(), 'task1', self.identity, NOW)
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_verified_applied_and_not_applied_close_only_on_bound_readback(self):
        self.open()
        ledger = self.verified_ledger(lambda trace, record: self.resolution())
        self.assertEqual(Applied('receipt1'), ledger.reconcile(self.principal(), 'task1', self.identity, NOW))
        self.assertEqual(CompletionState.COMPLETED, self.completion().state)
        self.assertEqual(LiabilityStatus.CLOSED, ledger.inspect(self.principal(Capability.READ), 'task1')[0].status)
        self.assertEqual(Applied('receipt1'), ledger.reconcile(self.principal(), 'task1', self.identity, NOW))

    def test_not_applied_requires_independent_no_effect_evidence(self):
        self.open()
        ledger = self.verified_ledger(lambda trace, record: self.resolution(NotApplied()))
        self.assertEqual(NotApplied(), ledger.reconcile(self.principal(), 'task1', self.identity, NOW))
        self.assertEqual(CompletionState.COMPLETED, self.completion().state)

    def test_reconciliation_wrong_operation_or_receipt_denied(self):
        self.open()
        for result in (replace(self.resolution(), operation_digest='sha256:' + 'e' * 64),):
            ledger = self.verified_ledger(lambda trace, record: result)
            with self.assertRaises(ValueError):
                ledger.reconcile(self.principal(), 'task1', self.identity, NOW)
        with self.assertRaises(ValueError):
            replace(self.resolution(), outcome=Applied('wrong-receipt'))
        with self.assertRaises(ValueError):
            replace(self.resolution(), readback=self.resolution().receipt)
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_unknown_and_ordinary_receipt_cannot_form_no_effect_resolution(self):
        with self.assertRaises(ValueError):
            replace(self.resolution(), outcome=Unknown(self.identity))
        with self.assertRaisesRegex(ValueError, 'NO_EFFECT_CERTIFICATE_REQUIRED'):
            replace(self.resolution(), outcome=NotApplied())

    def test_verifier_failure_and_invalid_closing_time_keep_open(self):
        self.open()
        def failed(trace, record):
            raise TimeoutError('untrusted-private-error')
        ledger = self.verified_ledger(failed)
        with self.assertRaisesRegex(ValueError, '^INDEPENDENT_READBACK_UNAVAILABLE$'):
            ledger.reconcile(self.principal(), 'task1', self.identity, NOW)
        ledger = self.verified_ledger(lambda trace, record: self.resolution())
        with self.assertRaises(ValueError):
            ledger.reconcile(self.principal(), 'task1', self.identity, NOW - timedelta(seconds=1))
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_missing_referenced_liability_fails_closed(self):
        other = classify_fault(replace(self.trace, request_ref='request2')).liability_id
        self.graph = DependencyGraph('task1', self.graph.nodes + (
            DependencyNode('missing', NodeKind.OPERATION, liability_ids=(other,)),))
        self.open()
        with self.assertRaises(ValueError):
            self.completion()

    def test_valid_storage_digest_cannot_hide_corrupt_domain_state(self):
        from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
        from runtime.memory_patch.contracts.serialization import canonical_json_bytes
        import json
        self.open()
        def corrupt(tx):
            stored = tx.get(RecordKind.OPERATION, self.ledger._key('task1'))
            state = json.loads(canonical_json_bytes(stored.payload))
            state['entries'][self.identity]['record']['task_id'] = 'wrong-task'
            tx.replace(StoredRecord(stored.kind, stored.record_id, stored.scope, stored.revision + 1, state),
                       expected_revision=stored.revision)
        self.runner.run(TransactionContext(self.principal(), Capability.COMMIT), corrupt)
        with self.assertRaisesRegex(ValueError, 'LIABILITY_INTEGRITY'):
            self.completion()

    def test_partial_closure_cannot_clear_other_dependent_unknown(self):
        second_trace = replace(self.trace, request_ref='request2')
        second_id = classify_fault(second_trace).liability_id
        self.graph = DependencyGraph('task1', (
            DependencyNode('effect', NodeKind.OPERATION, liability_ids=(self.identity, second_id)),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE, ('effect',)),))
        self.open()
        self.open(trace=second_trace)
        self.verified_ledger(lambda trace, record: self.resolution()).reconcile(self.principal(), 'task1', self.identity, NOW)
        self.assertEqual((second_id,), self.completion().blocking_liability_ids)

    def test_stale_verification_cannot_overwrite_escalation(self):
        self.open()
        def verifier(trace, record):
            self.ledger.escalate(self.principal(), 'task1', self.identity)
            return self.resolution()
        with self.assertRaisesRegex(ValueError, 'STALE_RECONCILIATION'):
            self.verified_ledger(verifier).reconcile(self.principal(), 'task1', self.identity, NOW)
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_lost_closure_ack_readback_returns_same_outcome_without_verifier_replay(self):
        self.open()
        calls = []
        ledger = self.verified_ledger(lambda trace, record: calls.append('readback') or self.resolution())
        original = DurableTransaction.commit
        def lost_closure_ack(transaction):
            original(transaction)
            if any(record.payload.get('schema') == 'aioa-liability-ledger-v1'
                   and any(entry['record']['status'] == 'CLOSED' for entry in record.payload['entries'].values())
                   for record in transaction.snapshot.values()):
                raise CommitOutcomeUnknown()
        from unittest.mock import patch
        with patch.object(DurableTransaction, 'commit', lost_closure_ack), self.assertRaises(CommitOutcomeUnknown):
            ledger.reconcile(self.principal(), 'task1', self.identity, NOW)
        self.assertEqual(Applied('receipt1'), ledger.reconcile(self.principal(), 'task1', self.identity, NOW))
        self.assertEqual(['readback'], calls)
        self.assertEqual(CompletionState.COMPLETED, self.completion().state)

    def test_missing_state_or_graph_change_cannot_complete(self):
        with self.assertRaises(ValueError):
            self.completion()
        self.open()
        empty = DependencyGraph('task1', (DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
        with self.assertRaises(ValueError):
            self.ledger.record_unknown(self.principal(), self.trace, empty, NOW)
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)

    def test_closed_unknown_redelivery_is_not_automatically_success(self):
        self.open()
        self.verified_ledger(lambda trace, record: self.resolution()).reconcile(self.principal(), 'task1', self.identity, NOW)
        with self.assertRaisesRegex(ValueError, 'CLOSED_UNKNOWN_CONFLICT'):
            self.open()

    def test_read_principal_cannot_mutate(self):
        with self.assertRaises(ValueError):
            self.ledger.record_unknown(self.principal(Capability.READ), self.trace, self.graph, NOW)
        self.assertFalse(self.path.exists())

    def test_corrupt_durable_bytes_fail_closed(self):
        self.open()
        self.path.write_text('{broken')
        with self.assertRaises(Exception):
            self.completion()

    def test_lost_commit_ack_persists_unknown_without_replay_effect(self):
        original = DurableTransaction.commit
        def lost_ack(transaction):
            original(transaction)
            raise CommitOutcomeUnknown()
        from unittest.mock import patch
        with patch.object(DurableTransaction, 'commit', lost_ack), self.assertRaises(CommitOutcomeUnknown):
            self.open()
        self.assertEqual(CompletionState.BLOCKED, self.completion().state)
        self.assertIs(type(self.open()), Unknown)

    def test_fresh_process_durable_completion_and_taint(self):
        self.open()
        code = '''
import sys
from pathlib import Path
from test_dual_governor import core, SCOPE
from nv03_support import DurableFactory
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.liability import CoreLiabilityLedger
c = core()
r = TransactionRunner(c, DurableFactory(Path(sys.argv[1])))
l = CoreLiabilityLedger(c, r, SCOPE)
p = c.local_operator(Capability.READ)
assert l.completion(p, 'task1', 'completion').state.value == 'BLOCKED'
assert all(n.state.value == 'TAINTED_BY_LIABILITY' for n in l.taint(p, 'task1'))
print('FRESH_PROCESS_G2_BLOCKED')
r.close()
c.close()
'''
        result = subprocess.run(native_command(__file__, code, self.path), capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('FRESH_PROCESS_G2_BLOCKED', result.stdout)
        print(result.stdout.strip())
        self.verified_ledger(lambda trace, record: self.resolution()).reconcile(self.principal(), 'task1', self.identity, NOW)
        closed_code = code.replace("== 'BLOCKED'", "== 'COMPLETED'").replace(
            "== 'TAINTED_BY_LIABILITY'", "== 'CLEAR'").replace('FRESH_PROCESS_G2_BLOCKED', 'FRESH_PROCESS_G2_CLOSED_CLEAR')
        result = subprocess.run(native_command(__file__, closed_code, self.path),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn('FRESH_PROCESS_G2_CLOSED_CLEAR', result.stdout)
        print(result.stdout.strip())


if __name__ == '__main__':
    unittest.main()
