"""Real native terminal routes; serializable fixture races and fresh processes.

The JSON/file-lock backend demonstrates local transaction/process semantics,
not production database, power-loss durability or distributed exactly-once.
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import timedelta
import json
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

from lab.archaioa.faults import FaultKind, FaultTrace, classify_fault
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext, TransactionRunner
from runtime.mission.completion import TaskCompletionBinding, TaskDependency
from runtime.mission.governor import CoreDualGovernor
from runtime.mission import jobs
from mission_completion_support import MissionCompletionFixture, NOW
from nv03_support import DurableFactory, DurableTransaction
from test_memory_patch_persistence_ports import StructuredFailure
import test_dual_governor as native


RESTART_PROBE = r'''
import json, sys
from pathlib import Path
from datetime import timedelta
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, Limits
from runtime.mission.job_contracts import JobClaim, JobEnvelope
from runtime.mission.completion import TaskCompletionBinding
from runtime.mission.liability import CoreLiabilityLedger
from runtime.providers.nvidia import ProviderResponse
from mission_completion_support import NOW
from nv03_support import DurableFactory
import test_dual_governor as native
d=json.loads(sys.argv[1]); path=Path(d['path']); core=native.core()
runner=TransactionRunner(core,DurableFactory(path))
policy=GovernorPolicy(native.SCOPE,'local-core',Limits(100,10),Limits(150,15),Limits(200,20),
 failure_threshold=2,cooldown_seconds=10,recovery_successes=2,max_clock_step_seconds=120)
gov=CoreDualGovernor(core,runner,policy,clock=lambda:100)
p=core.local_operator(Capability.COMMIT); read=core.local_operator(Capability.READ)
claim=JobClaim(**d['claim']); response=ProviderResponse(**d['response']); calls=[]
def forbidden(*args):
 calls.append(1); raise AssertionError('external verifier repeated after stored closure')
ledger=CoreLiabilityLedger(core,runner,native.SCOPE,verifier=forbidden)
try:
 if d['mode']=='deny':
  try: gov.finish_job(p,claim,response)
  except ValueError as e: reason=str(e)
  else: raise AssertionError('required task unexpectedly completed after restart')
  assert d['reason'] in reason,reason
  assert gov.inspect_job(read,claim.task_id)['state']=='STARTED'
  assert not gov.begin_job(p,claim)['fixture_step_now']
 elif d['mode']=='closure':
  outcome=ledger.reconcile(p,claim.task_id,d['liability_id'],NOW+timedelta(seconds=2))
  assert not calls
  assert outcome.to_dict()['contract_type']==d['outcome']
  if d['outcome']=='Applied': assert gov.finish_job(p,claim,response)['task_completion']=='COMPLETED'
  else:
   try: gov.finish_job(p,claim,response)
   except ValueError as e: assert 'REQUIRED_GOAL_NOT_APPLIED' in str(e)
   else: raise AssertionError('NotApplied became goal success')
 else:
  before=path.read_bytes(); saved=gov.inspect_job(read,claim.task_id)
  host=core.local_operator(Capability.MANAGE)
  assert gov.submit_job(host,JobEnvelope.parse(d['envelope']),
    completion=TaskCompletionBinding.parse(d['binding']))==saved
  assert not gov.begin_job(p,claim)['fixture_step_now']
  assert gov.finish_job(p,claim,response)==saved
  assert path.read_bytes()==before
  assert not calls
 print(json.dumps({'status':'PASS','mode':d['mode'],'verifier_calls':len(calls),
  'state':gov.inspect_job(read,claim.task_id)['state']}))
finally: runner.close(); core.close()
'''


class MissionDependencyRecoveryTests(MissionCompletionFixture):
    def restart(self, task, mode, **extra):
        data = dict(path=str(self.fx.path), mode=mode, claim=asdict(task.claim),
                    response=asdict(task.response), envelope=task.envelope.as_dict(),
                    binding=task.binding.to_dict(), **extra)
        result = subprocess.run([sys.executable, '-B', '-c', RESTART_PROBE, json.dumps(data)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_verified_required_dependency_allows_actual_parent_done(self):
        child = self.task('verified-child')
        self.finish(child)
        parent = self.task('verified-parent', dependencies=(self.dependency(child),))
        result = self.finish(parent)
        self.assertEqual('COMPLETED', result['task_completion'])
        self.assertEqual({'verified-parent', 'verified-child'},
                         {t['task_id'] for t in result['completion_proof']['tasks']})

    def test_open_transitive_dependency_and_replan_block_until_verified(self):
        graph, trace, _ = self.effect_graph('dependency-c')
        child = self.task('dependency-c', graph=graph)
        self.open_unknown(child, trace)
        middle = self.task('dependency-b', dependencies=(self.dependency(child),))
        parent = self.task('dependency-a', dependencies=(self.dependency(middle),))
        replanned = self.task('dependency-a-prime', dependencies=(self.dependency(middle),))
        for task in (middle, parent, replanned):
            with self.assertRaises(ValueError): self.finish(task)
            self.assert_not_done(task)
        self.ledger.escalate(self.p, child.task_id, classify_fault(trace).liability_id)
        self.restart(parent, 'deny', reason='REQUIRED_LIABILITY_OPEN')
        self.assertEqual('COMPLETED', self.finish(self.task('unrelated-clean'))['task_completion'])
        self.close_unknown(child, trace)
        for task in (child, middle, parent, replanned):
            self.assertEqual('COMPLETED', self.finish(task)['task_completion'])

    def test_applied_ledger_without_child_terminal_result_is_not_sufficient(self):
        child = self.task('not-finished')
        parent = self.task('waiting-parent', dependencies=(self.dependency(child),))
        with self.assertRaisesRegex(ValueError, 'REQUIRED_TASK_NOT_COMPLETED'): self.finish(parent)
        self.assert_not_done(parent)

    def test_advisory_done_cannot_satisfy_required_dependency(self):
        child = self.task('advisory-dependency', required=False)
        self.finish(child)
        ref = TaskDependency(native.SCOPE, child.task_id,
                             canonical_sha256(child.graph.to_dict()), 'completion')
        parent = self.task('required-parent', dependencies=(ref,))
        with self.assertRaisesRegex(ValueError, 'REQUIRED_TASK_BINDING_REQUIRED'): self.finish(parent)
        self.assert_not_done(parent)
        with self.assertRaises(ValueError):
            self.gov.submit_job(self.host, child.envelope,
                completion=TaskCompletionBinding.for_graph(native.SCOPE, child.graph, 'completion'))

    def test_missing_and_drifted_task_references_fail_closed(self):
        child = self.task('reference-child'); self.finish(child)
        for suffix, ref in (
            ('missing', replace(self.dependency(child), task_id='absent-task')),
            ('graph', replace(self.dependency(child), graph_digest='e' * 64)),
            ('candidate', replace(self.dependency(child), candidate_id='absent')),
        ):
            with self.subTest(suffix=suffix):
                parent = self.task('reference-' + suffix, dependencies=(ref,))
                with self.assertRaises(ValueError): self.finish(parent)
                self.assert_not_done(parent)

    def test_foreign_owner_duplicate_and_self_references_are_rejected(self):
        graph = self.clean_graph('edge')
        ref = TaskDependency(native.SCOPE, 'other', canonical_sha256(graph.to_dict()), 'completion')
        for refs in ((ref, ref), (replace(ref, task_id='edge'),),
                     (replace(ref, scope=OwnerScope('foreign', 'owner', 'space', 'slot')),)):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                TaskCompletionBinding.for_graph(native.SCOPE, graph, 'completion', dependencies=refs)

    def test_cross_task_cycle_cannot_commit_success(self):
        ga, gb = self.clean_graph('cycle-a'), self.clean_graph('cycle-b')
        a = self.task('cycle-a', dependencies=(TaskDependency(native.SCOPE, 'cycle-b',
                      canonical_sha256(gb.to_dict()), 'completion'),))
        self.task('cycle-b', dependencies=(self.dependency(a),))
        with self.assertRaisesRegex(ValueError, 'TASK_DEPENDENCY_CYCLE'): self.finish(a)
        self.assert_not_done(a)

    def test_total_graph_node_and_reference_caps_are_not_silently_increased(self):
        previous = None
        for n in range(5):
            graph = DependencyGraph('bounded-' + str(n), tuple(
                DependencyNode('node-' + str(i), NodeKind.EVIDENCE) for i in range(102)
            ) + (DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
            task = self.task(graph.task_id, graph=graph,
                             dependencies=() if previous is None else (self.dependency(previous),))
            if n < 4: self.finish(task)
            else:
                with self.assertRaisesRegex(ValueError, 'COMPLETION_QUOTA'): self.finish(task)
                self.assert_not_done(task)
            previous = task
        refs = tuple(TaskDependency(native.SCOPE, 'ref-' + str(i), 'a' * 64, 'completion')
                     for i in range(129))
        with self.assertRaises(ValueError):
            TaskCompletionBinding.for_graph(native.SCOPE, self.clean_graph('cap'), 'completion', dependencies=refs)

    def test_partial_applied_does_not_clear_other_required_effect(self):
        first, second = [FaultTrace(FaultKind.LOST_ACK, 'partial', 'request-' + str(n),
                                   'sha256:' + canonical_sha256(('effect', n))) for n in (1, 2)]
        nodes = tuple(DependencyNode('effect-' + str(n), NodeKind.OPERATION,
                      liability_ids=(classify_fault(trace).liability_id,))
                      for n, trace in enumerate((first, second)))
        graph = DependencyGraph('partial', nodes + (DependencyNode('completion',
                    NodeKind.COMPLETION_CANDIDATE, ('effect-0', 'effect-1')),))
        task = self.task('partial', graph=graph)
        for trace in (first, second): self.open_unknown(task, trace)
        self.close_unknown(task, first)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_LIABILITY_OPEN'): self.finish(task)
        self.close_unknown(task, second, applied=False)
        with self.assertRaisesRegex(ValueError, 'REQUIRED_GOAL_NOT_APPLIED'): self.finish(task)
        self.assert_not_done(task)

    def test_unrelated_not_applied_is_allowed_but_missing_reference_is_not(self):
        for missing in (False, True):
            task_id = 'unrelated-branch-' + str(missing)
            graph, trace, _ = self.effect_graph(task_id)
            graph = DependencyGraph(task_id, tuple(node for node in graph.nodes
                if node.kind is not NodeKind.COMPLETION_CANDIDATE) + (
                DependencyNode('completion', NodeKind.COMPLETION_CANDIDATE),))
            task = self.task(task_id, graph=graph)
            if missing:
                with self.assertRaises(ValueError): self.finish(task)
                self.assert_not_done(task)
            else:
                self.open_unknown(task, trace); self.close_unknown(task, trace, applied=False)
                self.assertEqual('COMPLETED', self.finish(task)['task_completion'])

    def force_retry_with_competing_write(self, task, competitor, reason):
        original = DurableTransaction.commit
        conflicts, sleeps = [], []
        exposure_before = self.fx.inspect()['exposure']['global']['money_nano']
        def conflict_once(tx):
            if not conflicts:
                conflicts.append(1)
                raise StructuredFailure('40001')  # guaranteed rollback, before any commit
            return original(tx)
        def interleave(_delay):
            sleeps.append(1)
            # Runner's transaction context does not propagate into this new thread.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(competitor).result(timeout=5)
        with patch.object(DurableTransaction, 'commit', conflict_once), patch.object(self.runner, '_sleep', interleave):
            with self.assertRaisesRegex(ValueError, reason): self.finish(task)
        self.assertEqual([1], conflicts); self.assertEqual([1], sleeps)
        self.assertEqual('STARTED', self.inspect_task(task)['state'])
        if reason == 'STALE_EPOCH':
            with self.assertRaisesRegex(ValueError, 'STALE_EPOCH'): self.gov.begin_job(self.p, task.claim)
        else:
            self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])
        saved = self.inspect_task(task)
        self.assertIsNone(saved['completion_proof']); self.assertIsNone(saved['result_digest'])
        self.assertEqual(exposure_before, self.fx.inspect()['exposure']['global']['money_nano'])

    def test_serialization_retry_rereads_changed_dependency_evidence(self):
        child = self.task('race-child'); self.finish(child)
        parent = self.task('race-parent', dependencies=(self.dependency(child),))
        def changed_evidence():
            def write(tx):
                row = tx.get(RecordKind.OPERATION, self.ledger._key(child.task_id))
                data = json.loads(canonical_json_bytes(row.payload)); data['graph']['task_id'] = 'drift'
                tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, data),
                           expected_revision=row.revision)
            self.runner.run(TransactionContext(self.p, Capability.COMMIT), write)
        self.force_retry_with_competing_write(parent, changed_evidence, 'LIABILITY_INTEGRITY')

    def test_kill_between_evaluation_and_retry_blocks_promotion(self):
        task = self.task('kill-retry')
        self.force_retry_with_competing_write(task, lambda: self.gov.set_kill(self.host, True), 'KILL_SWITCH')

    def test_epoch_between_evaluation_and_retry_blocks_stale_writer(self):
        task = self.task('epoch-retry')
        self.force_retry_with_competing_write(task, lambda: self.gov.start_epoch(self.host), 'STALE_EPOCH')

    def test_revocation_after_evaluation_rolls_back_done_proof_and_settlement(self):
        historical = self.task('completed-before-revoke'); completed = self.finish(historical)
        task = self.task('revoked-after-check'); before = self.fx.path.read_bytes()
        original = jobs.write_job
        def revoke_after_write(*args):
            original(*args)
            self.core.close()
        with patch.object(jobs, 'write_job', revoke_after_write), self.assertRaisesRegex(MemoryPatchError, 'TRANSACTION_FAILED'):
            self.finish(task)
        self.assertEqual(before, self.fx.path.read_bytes())
        fresh_core = native.core(); self.addCleanup(fresh_core.close)
        fresh_runner = TransactionRunner(fresh_core, DurableFactory(self.fx.path)); self.addCleanup(fresh_runner.close)
        fresh_gov = CoreDualGovernor(fresh_core, fresh_runner, self.fx.policy, clock=lambda: 100)
        saved = fresh_gov.inspect_job(fresh_core.local_operator(Capability.READ), task.task_id)
        self.assertEqual('STARTED', saved['state']); self.assertIsNone(saved['completion_proof'])
        self.assertEqual(completed, fresh_gov.inspect_job(
            fresh_core.local_operator(Capability.READ), historical.task_id))
        with self.assertRaises(ValueError): self.gov.finish_job(self.p, task.claim, task.response)

    def test_competing_finalizers_commit_one_history_and_replay_without_redispatch(self):
        task = self.task('competing'); barrier = threading.Barrier(2)
        def finish():
            barrier.wait(timeout=5)
            return self.finish(task)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(finish) for _ in range(2)]
            results = [f.result(timeout=10) for f in futures]
        self.assertEqual(results[0], results[1]); self.assertEqual(4, results[0]['version'])
        self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])
        # Committed spend remains counted. Replay cannot release or charge it again.
        self.assertEqual(1, self.fx.inspect()['exposure']['global']['money_nano'])

    def test_open_and_escalated_denial_survive_fresh_process(self):
        for escalated in (False, True):
            graph, trace, identity = self.effect_graph('restart-' + str(escalated))
            task = self.task(graph.task_id, graph=graph); self.open_unknown(task, trace)
            if escalated: self.ledger.escalate(self.p, task.task_id, identity)
            self.restart(task, 'deny', reason='REQUIRED_LIABILITY_OPEN')

    def test_lost_closure_ack_readback_does_not_repeat_verifier_or_promote_not_applied(self):
        for applied in (True, False):
            graph, trace, identity = self.effect_graph('closure-ack-' + str(applied))
            task = self.task(graph.task_id, graph=graph); self.open_unknown(task, trace)
            original = DurableTransaction.commit; calls, lost = [], []
            def lose_closed_ack(tx):
                original(tx)
                row = tx.get(RecordKind.OPERATION, self.ledger._key(task.task_id))
                if not lost and row.payload['entries'][identity]['resolution'] is not None:
                    lost.append(1); raise CommitOutcomeUnknown()
            def verifier(*_):
                calls.append(1); return self.resolution(trace, applied=applied)
            with patch.object(DurableTransaction, 'commit', lose_closed_ack), self.assertRaises(CommitOutcomeUnknown):
                self.close_unknown(task, trace, applied=applied, verifier=verifier)
            self.assertEqual([1], calls); self.assertEqual([1], lost)
            self.restart(task, 'closure', liability_id=identity, outcome='Applied' if applied else 'NotApplied')

    def test_lost_done_ack_is_read_back_without_second_result_or_settlement(self):
        task = self.task('done-ack'); original = DurableTransaction.commit; lost = []
        def lose_ack(tx):
            original(tx)
            if not lost:
                lost.append(1); raise CommitOutcomeUnknown()
        with patch.object(DurableTransaction, 'commit', lose_ack), self.assertRaises(CommitOutcomeUnknown):
            self.finish(task)
        self.assertEqual([1], lost); self.restart(task, 'done-replay')

    def test_closed_redelivery_retains_historical_completion_and_conflict_evidence(self):
        graph, trace, _ = self.effect_graph('late-closed')
        task = self.task(graph.task_id, graph=graph); self.open_unknown(task, trace)
        self.close_unknown(task, trace); completed = self.finish(task); before = self.fx.path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'CLOSED_UNKNOWN_CONFLICT'):
            self.ledger.record_unknown(self.p, trace, graph, NOW + timedelta(seconds=2))
        self.assertEqual(before, self.fx.path.read_bytes()); self.assertEqual(completed, self.inspect_task(task))
        self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])
        print(json.dumps({'conflict_task':task.task_id,'observation':trace.to_dict(),
                          'reason':'CLOSED_UNKNOWN_CONFLICT','disposition':'HUMAN_REVIEW_REQUIRED'}))

    def test_required_done_cannot_gain_a_later_self_consistent_history_version(self):
        task = self.task('terminal-history'); completed = self.finish(task)
        def append_after_done(tx):
            before = jobs.load_job(self.gov, tx, task.task_id)
            after = json.loads(canonical_json_bytes(before))
            after['completion_proof']['tasks'][0]['ledger_revision'] += 1
            jobs.write_job(self.gov, tx, before, after, 100)
        self.runner.run(TransactionContext(self.p, Capability.COMMIT), append_after_done)
        with self.assertRaises(ValueError): self.inspect_task(task)
        self.assertEqual('DONE', completed['state'])

    def test_required_history_rejects_null_unknown_and_missing_metadata(self):
        for mutation in ('null', 'schema', 'missing', 'downgrade', 'changed-graph', 'changed-dependencies'):
            with self.subTest(mutation=mutation):
                # A separate store avoids intentionally corrupted history poisoning another case.
                fx = MissionCompletionFixture(); fx.setUp()
                try:
                    task = fx.task('metadata-' + mutation)
                    def poison(tx):
                        before = jobs.load_job(fx.gov, tx, task.task_id)
                        after = json.loads(canonical_json_bytes(before))
                        if mutation == 'null': after['completion_binding'] = None
                        elif mutation == 'schema': after['completion_binding']['schema'] = 'unknown'
                        elif mutation == 'missing': del after['completion_proof']
                        elif mutation == 'changed-graph': after['completion_binding']['graph_digest'] = 'f' * 64
                        elif mutation == 'changed-dependencies':
                            after['completion_binding']['dependencies'] = [
                                TaskDependency(native.SCOPE, 'new-required-ref', 'a' * 64, 'completion').to_dict()]
                        else:
                            del after['completion_binding']; del after['completion_proof']
                        jobs.write_job(fx.gov, tx, before, after, 100)
                    fx.runner.run(TransactionContext(fx.p, Capability.COMMIT), poison)
                    with self.assertRaises(ValueError): fx.inspect_task(task)
                finally: fx.doCleanups()

    def test_old_v1_history_loads_unchanged_and_cannot_be_upgraded(self):
        task = self.task('genuine-v1', required=False)
        before = self.fx.path.read_bytes()
        self.assertNotIn('completion_binding', self.inspect_task(task))
        self.assertEqual(before, self.fx.path.read_bytes())
        binding = TaskCompletionBinding.for_graph(native.SCOPE, task.graph, 'completion')
        with self.assertRaises(ValueError): self.gov.submit_job(self.host, task.envelope, completion=binding)
        result = self.finish(task); saved = self.fx.path.read_bytes()
        self.assertNotIn('task_completion', result)
        self.assertEqual(result, self.finish(task)); self.assertEqual(saved, self.fx.path.read_bytes())

    def test_required_replay_preserves_proof_and_history_after_kill(self):
        task = self.task('replay-proof'); completed = self.finish(task)
        self.gov.set_kill(self.host, True); before = self.fx.path.read_bytes()
        self.assertEqual(completed, self.gov.submit_job(self.host, task.envelope, completion=task.binding))
        self.assertFalse(self.gov.begin_job(self.p, task.claim)['fixture_step_now'])
        self.assertEqual(completed, self.finish(task))
        self.assertEqual(before, self.fx.path.read_bytes())
        with self.assertRaises(ValueError):
            self.gov.finish_job(self.p, task.claim, replace(task.response, received_at=102))

    def test_different_deployment_cannot_be_used_as_required_success(self):
        task = self.task('deployment-bound'); self.finish(task)
        foreign = CoreDualGovernor(self.core, self.runner,
                    replace(self.fx.policy, deployment_id='other-deployment'), clock=lambda: 100)
        before = self.fx.path.read_bytes()
        with self.assertRaises(ValueError): foreign.inspect_job(self.read, task.task_id)
        with self.assertRaises(ValueError): foreign.finish_job(self.p, task.claim, task.response)
        self.assertEqual(before, self.fx.path.read_bytes())
        self.assertEqual('DONE', self.inspect_task(task)['state'])

    def test_persisted_invalid_graph_edges_and_cycles_deny_actual_native_finish(self):
        for dependency in ('missing-node', 'completion'):
            task = self.task('invalid-graph-' + dependency)
            def corrupt(tx):
                row = tx.get(RecordKind.OPERATION, self.ledger._key(task.task_id))
                data = json.loads(canonical_json_bytes(row.payload))
                data['graph']['nodes'][0]['required_dependencies'] = [dependency]
                tx.replace(StoredRecord(row.kind, row.record_id, row.scope, row.revision + 1, data),
                           expected_revision=row.revision)
            self.runner.run(TransactionContext(self.p, Capability.COMMIT), corrupt)
            before = self.fx.path.read_bytes()
            with self.assertRaisesRegex(ValueError, 'LIABILITY_INTEGRITY'): self.finish(task)
            self.assertEqual(before, self.fx.path.read_bytes())
            self.assert_not_done(task)
