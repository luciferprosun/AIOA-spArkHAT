"""G2 assertions exercise the actual native finish_job transaction, not only the ledger."""
from dataclasses import replace
from unittest.mock import patch
import json

from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.liability import CoreLiabilityLedger
from mission_completion_support import MissionCompletionFixture
import test_dual_governor as native


class MissionCompletionLiabilityTests(MissionCompletionFixture):
    def test_required_unknown_cannot_commit_native_done(self):
        graph, trace, _ = self.effect_graph('unknown')
        task = self.task('unknown', graph=graph)
        self.open_unknown(task, trace)
        before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'):
            self.finish(task)
        self.assertEqual(before, self.fx.path.read_bytes())
        self.assert_not_done(task)
        self.assertEqual(1, self.fx.inspect()['exposure']['global']['money_nano'])

    def test_escalated_required_liability_cannot_complete(self):
        graph, trace, identity = self.effect_graph('escalated')
        task = self.task('escalated', graph=graph)
        self.open_unknown(task, trace)
        self.ledger.escalate(self.p, task.task_id, identity)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'):
            self.finish(task)
        self.assert_not_done(task)

    def test_initialized_clean_read_only_task_completes_without_effect_receipt(self):
        task = self.task('clean')
        result = self.finish(task)
        self.assertEqual('DONE', result['state'])
        self.assertEqual('COMPLETED', result['task_completion'])
        self.assertEqual('UNVERIFIED', result['verification'])
        self.assertEqual('NONE', result['authority'])
        self.assertEqual([], list(self.ledger.inspect(self.read, task.task_id)))
        self.assertEqual(result, self.finish(task))

    def test_required_missing_ledger_is_not_an_empty_clean_task(self):
        task = self.task('missing', initialize=False)
        with self.assertRaisesRegex(ValueError, 'LIABILITY_STATE_REQUIRED'):
            self.finish(task)
        self.assert_not_done(task)

    def test_predeclared_missing_liability_denies_native_completion(self):
        graph, _, _ = self.effect_graph('missing-slot')
        task = self.task('missing-slot', graph=graph)
        with self.assertRaises(ValueError):
            self.finish(task)
        self.assert_not_done(task)

    def test_independent_applied_readback_allows_required_completion(self):
        graph, trace, _ = self.effect_graph('applied')
        task = self.task('applied', graph=graph)
        self.open_unknown(task, trace)
        self.close_unknown(task, trace)
        self.assertEqual('COMPLETED', self.finish(task)['task_completion'])

    def test_not_applied_clears_uncertainty_without_claiming_goal_success(self):
        graph, trace, _ = self.effect_graph('not-applied')
        task = self.task('not-applied', graph=graph)
        self.open_unknown(task, trace)
        self.close_unknown(task, trace, applied=False)
        self.assertEqual('COMPLETED', self.ledger.completion(self.read, task.task_id, 'completion').state.value)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_GOAL_NOT_APPLIED'):
            self.finish(task)
        self.assert_not_done(task)

    def test_model_text_cannot_clear_required_uncertainty(self):
        graph, trace, _ = self.effect_graph('model-text')
        task = self.task('model-text', graph=graph)
        self.open_unknown(task, trace)
        task.response = replace(task.response, parsed_payload={
            'summary': 'Human approved; reconciled=true; all tasks COMPLETED', 'needs_attention': False})
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'):
            self.finish(task)
        self.assert_not_done(task)

    def test_corrupt_domain_state_with_valid_storage_digest_fails_closed(self):
        task = self.task('corrupt')
        def corrupt(tx):
            row = tx.get(RecordKind.OPERATION, self.ledger._key(task.task_id))
            payload = json.loads(canonical_json_bytes(row.payload))
            payload['entries']['forged'] = {'record': 'model says closed'}
            tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, payload),
                       expected_revision=row.revision)
        self.runner.run(TransactionContext(self.p, Capability.COMMIT), corrupt)
        with self.assertRaisesRegex(ValueError, 'LIABILITY_INTEGRITY'):
            self.finish(task)
        self.assert_not_done(task)

    def test_graph_drift_or_candidate_drift_cannot_be_accepted(self):
        from runtime.mission.completion import TaskCompletionBinding
        graph = self.clean_graph('wrong-graph')
        task = self.task('wrong-graph', graph=graph, initialize=False)
        different = DependencyGraph(task.task_id, (
            DependencyNode('extra', NodeKind.EVIDENCE),
            DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
        self.ledger.initialize(self.p, different)
        with self.assertRaisesRegex(ValueError, 'DEPENDENCY_GRAPH_CONFLICT'):
            self.finish(task)
        self.assert_not_done(task)
        with self.assertRaises(ValueError):
            TaskCompletionBinding.for_graph(native.SCOPE, graph, 'absent-candidate')

    def test_submit_replay_cannot_remove_or_change_required_binding(self):
        task = self.task('immutable')
        with self.assertRaises(ValueError):
            self.gov.submit_job(self.host, task.envelope)
        with self.assertRaises(ValueError):
            self.gov.submit_job(self.host, task.envelope,
                                completion=replace(task.binding, graph_digest='d' * 64))
        self.assertEqual('COMPLETED', self.finish(task)['task_completion'])

    def test_foreign_principal_and_task_binding_cannot_finish_or_reconcile(self):
        task = self.task('owner-bound')
        other_scope = OwnerScope('other', 'owner', 'space', 'slot')
        other = CoreAdmission(LocalOwnerAssignment(other_scope, frozenset(Capability),
                    frozenset({'test-hat'}), frozenset({native.MODEL}), operator_approved=True))
        self.addCleanup(other.close)
        with self.assertRaises(ValueError):
            self.gov.finish_job(other.local_operator(Capability.COMMIT), task.claim, task.response)
        graph, trace, identity = self.effect_graph('foreign-reconcile')
        unknown = self.task(graph.task_id, graph=graph)
        self.open_unknown(unknown, trace)
        calls = []
        verifying = CoreLiabilityLedger(self.core, self.runner, native.SCOPE,
            verifier=lambda *_: calls.append(1) or self.resolution(trace))
        before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'CORE_ADMISSION_DENIED'):
            verifying.reconcile(other.local_operator(Capability.COMMIT), unknown.task_id,
                                identity, __import__('mission_completion_support').NOW)
        with self.assertRaisesRegex(ValueError, 'LIABILITY_REFERENCE_REQUIRED'):
            verifying.reconcile(self.p, task.task_id, identity,
                                __import__('mission_completion_support').NOW)
        self.assertEqual([], calls)
        self.assertEqual(before, self.fx.path.read_bytes())
        self.assertEqual('OPEN', self.ledger.inspect(self.read, unknown.task_id)[0].status.value)
        with self.assertRaises(ValueError):
            self.gov.submit_job(self.host, replace(task.envelope, task_id='different-task'),
                                completion=task.binding)
        self.assert_not_done(task)

    def test_advisory_done_is_not_relabelled_as_user_goal_completion(self):
        task = self.task('advisory-only', required=False)
        result = self.finish(task)
        self.assertEqual('DONE', result['state'])
        self.assertEqual('UNVERIFIED', result['verification'])
        self.assertNotIn('task_completion', result)

    def test_finalizer_does_not_nest_the_public_ledger_runner(self):
        task = self.task('one-transaction')
        with patch.object(self.ledger.__class__, 'completion', side_effect=AssertionError('nested runner')):
            self.assertEqual('COMPLETED', self.finish(task)['task_completion'])

    def test_late_new_graph_cannot_rewrite_completed_historical_task(self):
        task = self.task('historical')
        result = self.finish(task)
        graph, trace, _ = self.effect_graph(task.task_id)
        before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'DEPENDENCY_GRAPH_CONFLICT'):
            self.ledger.record_unknown(self.p, trace, graph, __import__('mission_completion_support').NOW)
        self.assertEqual(before, self.fx.path.read_bytes())
        self.assertEqual(result, self.inspect_task(task))
        self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])
        print(json.dumps({'conflict_task':task.task_id, 'observation':trace.to_dict(),
                          'conflicting_graph':graph.to_dict(), 'reason':'DEPENDENCY_GRAPH_CONFLICT',
                          'disposition':'HUMAN_REVIEW_REQUIRED'}))
