import unittest
from dataclasses import replace, FrozenInstanceError
from itertools import permutations
import os
from pathlib import Path
import subprocess
import sys

from lab.archaioa import ContractValidationError
from lab.archaioa.faults import FaultKind, open_liability, resolve_liability
from lab.archaioa.pre02_fixtures import fault_story, START, resolution_evidence
from lab.archaioa.taint import DependencyNode, DependencyGraph, NodeKind, TaintState, propagate_taint


class TaintTests(unittest.TestCase):
    def fixture(self):
        return fault_story(FaultKind.LOST_ACK)

    def test_claim_proposal_candidate_inherit_same_ids(self):
        _, record, graph = self.fixture()
        for result in propagate_taint(graph, (record,)):
            self.assertIs(result.state, TaintState.TAINTED_BY_LIABILITY)
            self.assertEqual(result.liability_ids, (record.liability_id,))

    def test_multiple_liabilities_union_and_duplicates(self):
        trace, record, graph = self.fixture()
        other = open_liability(replace(trace, request_ref='request-2'), START)
        nodes = list(graph.nodes)
        index = next(i for i, node in enumerate(nodes) if node.node_id == 'operation')
        nodes[index] = replace(nodes[index], liability_ids=(other.liability_id, record.liability_id, other.liability_id))
        graph = replace(graph, nodes=nodes + nodes)
        results = propagate_taint(graph, (other, record, other))
        self.assertEqual(results[-1].liability_ids, tuple(sorted((other.liability_id, record.liability_id))))

    def test_order_independent(self):
        _, record, graph = self.fixture()
        expected = propagate_taint(graph, (record,))
        for order in permutations(graph.nodes):
            self.assertEqual(propagate_taint(replace(graph, nodes=order), (record,)), expected)

    def test_dependencies_duplicate_and_sorted(self):
        node = DependencyNode('proposal', NodeKind.PROPOSAL, ['claim', 'claim'])
        self.assertEqual(node.required_dependencies, ('claim',))
        self.assertEqual(node, replace(node, required_dependencies=('claim',)))

    def test_missing_edges_cycles_self_loop_conflicts_rejected(self):
        _, _, graph = self.fixture()
        cases = (
            (DependencyNode('x', NodeKind.CLAIM, ('missing',)),),
            (DependencyNode('x', NodeKind.CLAIM, ('x',)),),
            (DependencyNode('x', NodeKind.CLAIM, ('y',)), DependencyNode('y', NodeKind.CLAIM, ('x',))),
            graph.nodes + (replace(graph.nodes[0], kind=NodeKind.PROPOSAL),),
        )
        for nodes in cases:
            with self.assertRaises(ContractValidationError):
                replace(graph, nodes=nodes)

    def test_missing_liability_conflicting_and_wrong_task_rejected(self):
        _, record, graph = self.fixture()
        for records in ((), (record, replace(record, kind='other')), (replace(record, task_id='other'),)):
            with self.assertRaises(ContractValidationError):
                propagate_taint(graph, records)

    def test_closed_recomputes_clear_without_mutating_old_result(self):
        _, record, graph = self.fixture()
        old = propagate_taint(graph, (record,))
        closed = resolve_liability(record, resolution_evidence(), START)
        self.assertTrue(all(result.state is TaintState.CLEAR for result in propagate_taint(graph, (closed,))))
        self.assertTrue(all(result.liability_ids for result in old))

    def test_unrelated_closure_does_not_clear(self):
        trace, record, graph = self.fixture()
        other = open_liability(replace(trace, request_ref='other'), START)
        closed = resolve_liability(other, resolution_evidence(), START)
        self.assertEqual(propagate_taint(graph, (record, closed)), propagate_taint(graph, (record,)))

    def test_immutable_roundtrips_and_input_copies(self):
        _, record, graph = self.fixture()
        nodes = list(graph.nodes)
        clone = replace(graph, nodes=nodes)
        nodes.clear()
        self.assertEqual(graph, clone)
        for value in (graph, *graph.nodes, *propagate_taint(graph, (record,))):
            self.assertEqual(type(value).from_json(value.to_json()), value)
            with self.assertRaises(FrozenInstanceError):
                value.extra = 1

    def test_malformed_collections_and_enum(self):
        for operation in (lambda: DependencyNode('x', 'CLAIM'),
                          lambda: DependencyNode('x', NodeKind.CLAIM, 'raw'),
                          lambda: DependencyNode('x', NodeKind.CLAIM, (None,)),
                          lambda: DependencyGraph('task-1', (None,)),
                          lambda: propagate_taint(None, ()),
                          lambda: propagate_taint(self.fixture()[2], None)):
            with self.assertRaises(ContractValidationError):
                operation()

    def test_long_graph_iterative(self):
        nodes = tuple(DependencyNode('n' + str(i), NodeKind.CLAIM, ('n' + str(i-1),) if i else ()) for i in range(1500))
        graph = DependencyGraph('task-1', nodes)
        self.assertEqual(len(propagate_taint(graph, ())), 1500)
        with self.assertRaises(ContractValidationError):
            replace(graph, nodes=(replace(nodes[0], required_dependencies=('n1499',)),) + nodes[1:])

    def test_hash_seed_stability_and_import_isolation(self):
        code = '''
import sys
class Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('runtime', 'deploy', 'web', 'requests', 'httpx', 'openai', 'nebius'):
            raise AssertionError('forbidden import')
sys.meta_path.insert(0, Block())
from lab.archaioa.pre02_fixtures import fault_story, START, resolution_evidence
from lab.archaioa.faults import FaultKind, resolve_liability
from lab.archaioa.taint import propagate_taint
from lab.archaioa.task_semantics import check_completion
for kind in FaultKind:
    t, l, g = fault_story(kind)
    c = resolve_liability(l, resolution_evidence(), START)
    values = (t, l, c, g, *g.nodes, *propagate_taint(g, (l,)), check_completion(g, 'candidate', (l,)), check_completion(g, 'candidate', (c,)))
    for value in values:
        print(value.to_json(), value.contract_digest(), hash(value))
'''
        outputs = []
        for seed in ('1', '98765', 'random'):
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=Path(__file__).resolve().parents[2], env={'PATH': os.defpath, 'PYTHONPATH': '.', 'PYTHONHASHSEED': seed}, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0], outputs[2])

    def test_diamond_union_all_status_combinations_against_oracle(self):
        from itertools import product
        from lab.archaioa import LiabilityStatus
        trace, _, _ = self.fixture()
        base = tuple(open_liability(replace(trace, request_ref='request-' + str(i)), START) for i in range(3))
        graph = DependencyGraph('task-1', (
            DependencyNode('a', NodeKind.EVIDENCE, liability_ids=(base[0].liability_id,)),
            DependencyNode('b', NodeKind.OPERATION, liability_ids=(base[1].liability_id,)),
            DependencyNode('c', NodeKind.CLAIM, ('a', 'b', 'a')),
            DependencyNode('p', NodeKind.PROPOSAL, ('a', 'c')),
            DependencyNode('done', NodeKind.COMPLETION_CANDIDATE, ('p',)),
            DependencyNode('unrelated', NodeKind.OPERATION, liability_ids=(base[2].liability_id,)),
        ))
        for statuses in product(tuple(LiabilityStatus), repeat=3):
            records = tuple(resolve_liability(record, resolution_evidence(), START) if status is LiabilityStatus.CLOSED else replace(record, status=status) for record, status in zip(base, statuses))
            expected = tuple(sorted(r.liability_id for r in records[:2] if r.status is not LiabilityStatus.CLOSED))
            actual = {r.node_id: r for r in propagate_taint(graph, records)}
            for node_id in ('c', 'p', 'done'):
                self.assertEqual(actual[node_id].liability_ids, expected)
            self.assertEqual(propagate_taint(graph, records), propagate_taint(replace(graph, nodes=tuple(reversed(graph.nodes))), tuple(reversed(records))))

    def test_new_contracts_strict_wire_and_sanitized_errors(self):
        from lab.archaioa.task_semantics import check_completion
        trace, record, graph = self.fixture()
        values = (trace, graph, *graph.nodes, *propagate_taint(graph, (record,)), check_completion(graph, 'candidate', (record,)))
        for value in values:
            for extra in ({'payload': 'private-fixture'}, {'schema_version': True}, {'contract_type': 'private-fixture'}):
                with self.assertRaises(ContractValidationError) as caught:
                    type(value).from_dict(value.to_dict() | extra)
                self.assertNotIn('private-fixture', str(caught.exception))
            for field in value.to_dict():
                wire = value.to_dict()
                del wire[field]
                with self.assertRaises(ContractValidationError):
                    type(value).from_dict(wire)

    def test_public_api_exports(self):
        import lab.archaioa as api
        for name in ('FaultKind', 'FaultTrace', 'open_liability', 'classify_fault', 'ambiguity_liability',
                     'is_blocking', 'resolve_liability', 'DependencyNode', 'DependencyGraph',
                     'NodeKind', 'NodeTaint', 'TaintState', 'propagate_taint',
                     'CompletionDecision', 'CompletionState', 'check_completion'):
            self.assertIn(name, api.__all__)
            self.assertTrue(hasattr(api, name))
