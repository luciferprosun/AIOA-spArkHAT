"""Pure completion gate; no executor, approval, scheduler or storage."""
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from .authority import decode_enum
from .contracts import Contract, ContractValidationError, identifier
from .taint import DependencyGraph, NodeKind, normalized_ids, propagate_taint


class CompletionState(Enum):
    BLOCKED = 'BLOCKED'
    COMPLETED = 'COMPLETED'


@dataclass(frozen=True)
class CompletionDecision(Contract):
    TYPE: ClassVar[str] = 'CompletionDecision'
    __hash__ = Contract.__hash__
    candidate_id: str
    state: CompletionState
    blocking_liability_ids: tuple[str, ...] = ()

    def __post_init__(self):
        identifier(self.candidate_id, 'candidate_id')
        if type(self.state) is not CompletionState:
            raise ContractValidationError('state', 'invalid_completion_state')
        object.__setattr__(self, 'blocking_liability_ids', normalized_ids(self.blocking_liability_ids, 'blocking_liability_ids'))
        if (self.state is CompletionState.BLOCKED) != bool(self.blocking_liability_ids):
            raise ContractValidationError('state', 'blocking_state_mismatch')

    def __bool__(self):
        raise TypeError('CompletionDecision requires explicit state inspection')

    @classmethod
    def _decode(cls, payload):
        payload['state'] = decode_enum(CompletionState, payload['state'], 'state')
        return payload


def check_completion(graph: DependencyGraph, candidate_id: str, records) -> CompletionDecision:
    """Compute a decision from the graph and records, never from a stale cache."""
    if type(graph) is not DependencyGraph:
        raise ContractValidationError('graph', 'dependency_graph_required')
    identifier(candidate_id, 'candidate_id')
    candidate = next((node for node in graph.nodes if node.node_id == candidate_id), None)
    if candidate is None or candidate.kind is not NodeKind.COMPLETION_CANDIDATE:
        raise ContractValidationError('candidate', 'completion_candidate_required')
    results = propagate_taint(graph, records)
    blocking = next(result.liability_ids for result in results if result.node_id == candidate_id)
    state = CompletionState.BLOCKED if blocking else CompletionState.COMPLETED
    return CompletionDecision(candidate_id, state, blocking)
