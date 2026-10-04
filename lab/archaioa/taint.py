"""Immutable required-dependency DAG and iterative liability propagation."""
from dataclasses import dataclass
from enum import Enum
import heapq
from typing import ClassVar

from .authority import decode_enum
from .contracts import Contract, ContractValidationError, identifier
from .faults import is_blocking, liability_index


def normalized_ids(value, field):
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(field, 'identifier_sequence_required')
    for item in value:
        identifier(item, field)
    return tuple(sorted(set(value)))


class NodeKind(Enum):
    EVIDENCE = 'EVIDENCE'
    OPERATION = 'OPERATION'
    CLAIM = 'CLAIM'
    PROPOSAL = 'PROPOSAL'
    COMPLETION_CANDIDATE = 'COMPLETION_CANDIDATE'


class TaintState(Enum):
    CLEAR = 'CLEAR'
    TAINTED_BY_LIABILITY = 'TAINTED_BY_LIABILITY'


@dataclass(frozen=True)
class DependencyNode(Contract):
    TYPE: ClassVar[str] = 'DependencyNode'
    __hash__ = Contract.__hash__
    node_id: str
    kind: NodeKind
    required_dependencies: tuple[str, ...] = ()
    liability_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.node_id, 'node_id')
        if type(self.kind) is not NodeKind:
            raise ContractValidationError('kind', 'invalid_node_kind')
        for field in ('required_dependencies', 'liability_ids'):
            object.__setattr__(self, field, normalized_ids(getattr(self, field), field))

    @classmethod
    def _decode(cls, payload):
        payload['kind'] = decode_enum(NodeKind, payload['kind'], 'kind')
        return payload


def topological_nodes(nodes):
    """Kahn traversal; fail closed for dangling dependencies and all cycles."""
    by_id = {node.node_id: node for node in nodes}
    indegrees = {node.node_id: len(node.required_dependencies) for node in nodes}
    children = {node.node_id: [] for node in nodes}
    for node in nodes:
        for parent in node.required_dependencies:
            if parent not in by_id:
                raise ContractValidationError('graph', 'missing_dependency')
            children[parent].append(node.node_id)
    ready = [node_id for node_id, degree in indegrees.items() if degree == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(by_id[node_id])
        for child in children[node_id]:
            indegrees[child] -= 1
            if indegrees[child] == 0:
                heapq.heappush(ready, child)
    if len(order) != len(nodes):
        raise ContractValidationError('graph', 'dependency_cycle')
    return tuple(order)


@dataclass(frozen=True)
class DependencyGraph(Contract):
    TYPE: ClassVar[str] = 'DependencyGraph'
    __hash__ = Contract.__hash__
    task_id: str
    nodes: tuple[DependencyNode, ...]

    def __post_init__(self):
        identifier(self.task_id, 'task_id')
        if not isinstance(self.nodes, (tuple, list)) or any(type(n) is not DependencyNode for n in self.nodes):
            raise ContractValidationError('nodes', 'dependency_nodes_required')
        by_id = {}
        for node in self.nodes:
            if node.node_id in by_id and by_id[node.node_id] != node:
                raise ContractValidationError('nodes', 'conflicting_node_id')
            by_id[node.node_id] = node
        nodes = tuple(sorted(by_id.values(), key=lambda n: n.node_id))
        topological_nodes(nodes)
        object.__setattr__(self, 'nodes', nodes)

    @classmethod
    def _decode(cls, payload):
        if not isinstance(payload['nodes'], list):
            raise ContractValidationError('nodes', 'dependency_nodes_required')
        payload['nodes'] = tuple(DependencyNode.from_dict(n) for n in payload['nodes'])
        return payload


@dataclass(frozen=True)
class NodeTaint(Contract):
    TYPE: ClassVar[str] = 'NodeTaint'
    __hash__ = Contract.__hash__
    node_id: str
    liability_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.node_id, 'node_id')
        object.__setattr__(self, 'liability_ids', normalized_ids(self.liability_ids, 'liability_ids'))

    @property
    def state(self) -> TaintState:
        return TaintState.TAINTED_BY_LIABILITY if self.liability_ids else TaintState.CLEAR


def propagate_taint(graph: DependencyGraph, records) -> tuple[NodeTaint, ...]:
    """Recompute blocking-id unions from current records; missing refs are errors.

    Every node reference in the supplied graph must exist and match its task.
    Result order is node_id order; only required ancestors contribute taint.
    """
    if type(graph) is not DependencyGraph:
        raise ContractValidationError('graph', 'dependency_graph_required')
    index = liability_index(records)
    results = {}
    for node in topological_nodes(graph.nodes):
        blocking = set()
        for liability_id in node.liability_ids:
            record = index.get(liability_id)
            if record is None:
                raise ContractValidationError('liability', 'missing_reference')
            if record.task_id != graph.task_id:
                raise ContractValidationError('liability', 'task_binding_mismatch')
            if is_blocking(record):
                blocking.add(liability_id)
        for parent in node.required_dependencies:
            blocking.update(results[parent].liability_ids)
        results[node.node_id] = NodeTaint(node.node_id, tuple(blocking))
    return tuple(results[node.node_id] for node in graph.nodes)
