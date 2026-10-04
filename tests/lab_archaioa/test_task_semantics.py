import unittest
from dataclasses import replace

from lab.archaioa import ContractValidationError, LiabilityStatus, Applied, NotApplied
from lab.archaioa.faults import FaultKind, classify_fault, open_liability, resolve_liability
from lab.archaioa.pre02_fixtures import fault_story, START, resolution_evidence
from lab.archaioa.taint import DependencyGraph, DependencyNode, NodeKind
from lab.archaioa.task_semantics import CompletionState, check_completion


class CompletionTests(unittest.TestCase):
    def test_all_ambiguous_stories_deny_completion(self):
        for kind in FaultKind:
            trace, record, graph = fault_story(kind)
            decision = check_completion(graph, 'candidate', (record,))
            self.assertIs(decision.state, CompletionState.BLOCKED)
            self.assertEqual(decision.blocking_liability_ids, (record.liability_id,))
            self.assertNotIsInstance(classify_fault(trace), (Applied, NotApplied))
            self.assertEqual(type(decision).from_json(decision.to_json()), decision)

    def test_escalated_denies_completion(self):
        _, record, graph = fault_story(FaultKind.LOST_ACK)
        self.assertIs(check_completion(graph, 'candidate', (replace(record, status=LiabilityStatus.ESCALATED),)).state, CompletionState.BLOCKED)

    def test_explicit_resolution_passes(self):
        for kind in FaultKind:
            _, record, graph = fault_story(kind)
            closed = resolve_liability(record, resolution_evidence(), START)
            decision = check_completion(graph, 'candidate', (closed,))
            self.assertIs(decision.state, CompletionState.COMPLETED)
            self.assertEqual(decision.blocking_liability_ids, ())

    def test_partial_resolution_still_blocks(self):
        trace, record, graph = fault_story(FaultKind.LOST_ACK)
        other = open_liability(replace(trace, request_ref='other'), START)
        graph = replace(graph, nodes=tuple(replace(n, liability_ids=(record.liability_id, other.liability_id)) if n.node_id == 'operation' else n for n in graph.nodes))
        decision = check_completion(graph, 'candidate', (resolve_liability(record, resolution_evidence(), START), other))
        self.assertEqual(decision.blocking_liability_ids, (other.liability_id,))
        self.assertIs(decision.state, CompletionState.BLOCKED)

    def test_unrelated_open_liability_not_required(self):
        trace, record, graph = fault_story(FaultKind.LOST_ACK)
        other = open_liability(replace(trace, request_ref='other'), START)
        closed = resolve_liability(record, resolution_evidence(), START)
        self.assertIs(check_completion(graph, 'candidate', (closed, other)).state, CompletionState.COMPLETED)

    def test_disconnected_open_node_not_required(self):
        _, record, graph = fault_story(FaultKind.LOST_ACK)
        graph = replace(graph, nodes=graph.nodes + (DependencyNode('independent', NodeKind.COMPLETION_CANDIDATE),))
        self.assertIs(check_completion(graph, 'independent', (record,)).state, CompletionState.COMPLETED)

    def test_candidate_missing_wrong_kind_and_missing_record_fail_closed(self):
        _, _, graph = fault_story(FaultKind.LOST_ACK)
        for candidate in ('missing', 'proposal', 'candidate'):
            with self.assertRaises(ContractValidationError):
                check_completion(graph, candidate, ())

    def test_empty_requirement_candidate_can_complete(self):
        graph = DependencyGraph('task-1', (DependencyNode('candidate', NodeKind.COMPLETION_CANDIDATE),))
        self.assertIs(check_completion(graph, 'candidate', ()).state, CompletionState.COMPLETED)

    def test_inconclusive_readback_references_original_open(self):
        trace, record, graph = fault_story(FaultKind.LOST_ACK)
        readback = replace(trace, kind=FaultKind.INCONCLUSIVE_READBACK)
        same = open_liability(readback, START, record)
        self.assertIs(same, record)
        self.assertIs(check_completion(graph, 'candidate', (same,)).state, CompletionState.BLOCKED)

    def test_decision_cannot_claim_completed_with_blockers(self):
        _, record, graph = fault_story(FaultKind.LOST_ACK)
        decision = check_completion(graph, 'candidate', (record,))
        with self.assertRaises(ContractValidationError):
            replace(decision, state=CompletionState.COMPLETED)
        with self.assertRaises(TypeError):
            bool(decision)
