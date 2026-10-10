"""Explicit required-task bindings on existing native jobs, never authority.

Ordinary v1 provider/advisory jobs keep their original meaning. These contracts
are supplied by an admitted host, not inferred from provider text or booleans.
"""
from dataclasses import dataclass
import json

from lab.archaioa.contracts import digest_id
from lab.archaioa.faults import opaque_id
from lab.archaioa.taint import DependencyGraph, NodeKind
from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.mission.liability import CoreLiabilityLedger, MAX_NODES, require

BINDING_SCHEMA = 'aioa.required-task-completion.v1'
MAX_REQUIRED_TASKS = 128
PROOF_SCHEMA = 'aioa.native-required-completion-proof.v1'


def _digest(value):
    require(type(value) is str and len(value) == 64
            and all(c in '0123456789abcdef' for c in value), 'INVALID_COMPLETION_BINDING')


@dataclass(frozen=True, slots=True)
class TaskDependency:
    scope: OwnerScope
    task_id: str
    graph_digest: str
    candidate_id: str

    def __post_init__(self):
        require(type(self.scope) is OwnerScope, 'INVALID_COMPLETION_BINDING')
        opaque_id(self.task_id, 'task_id')
        opaque_id(self.candidate_id, 'candidate_id')
        _digest(self.graph_digest)

    def to_dict(self):
        return {'scope': list(self.scope.binding()), 'task_id': self.task_id,
                'graph_digest': self.graph_digest, 'candidate_id': self.candidate_id}

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict and set(value) == {'scope', 'task_id', 'graph_digest', 'candidate_id'},
                'INVALID_COMPLETION_BINDING')
        require(type(value['scope']) is list and len(value['scope']) == 4, 'INVALID_COMPLETION_BINDING')
        return cls(OwnerScope(*value['scope']), value['task_id'], value['graph_digest'], value['candidate_id'])


@dataclass(frozen=True, slots=True)
class TaskCompletionBinding:
    scope: OwnerScope
    task_id: str
    graph_digest: str
    candidate_id: str
    dependencies: tuple[TaskDependency, ...] = ()

    def __post_init__(self):
        TaskDependency(self.scope, self.task_id, self.graph_digest, self.candidate_id)
        require(type(self.dependencies) in (tuple, list)
                and len(self.dependencies) <= MAX_REQUIRED_TASKS
                and all(type(ref) is TaskDependency for ref in self.dependencies), 'INVALID_COMPLETION_BINDING')
        require(all(ref.scope == self.scope for ref in self.dependencies), 'FOREIGN_TASK_REFERENCE')
        require(len({ref.task_id for ref in self.dependencies}) == len(self.dependencies)
                and all(ref.task_id != self.task_id for ref in self.dependencies), 'INVALID_TASK_DEPENDENCY')
        object.__setattr__(self, 'dependencies', tuple(sorted(self.dependencies, key=lambda ref: ref.task_id)))
        require(len(canonical_json_bytes(self.to_dict())) <= 65536, 'COMPLETION_QUOTA')

    @classmethod
    def for_graph(cls, scope, graph, candidate_id, *, dependencies=()):
        require(type(graph) is DependencyGraph and len(graph.nodes) <= 512, 'INVALID_COMPLETION_BINDING')
        require(any(node.node_id == candidate_id and node.kind is NodeKind.COMPLETION_CANDIDATE
                    for node in graph.nodes), 'COMPLETION_CANDIDATE_REQUIRED')
        return cls(scope, graph.task_id, canonical_sha256(graph.to_dict()), candidate_id, dependencies)

    @property
    def digest(self):
        return canonical_sha256(self.to_dict())

    def to_dict(self):
        return {'schema': BINDING_SCHEMA, 'scope': list(self.scope.binding()),
                'task_id': self.task_id, 'graph_digest': self.graph_digest,
                'candidate_id': self.candidate_id,
                'required_outcome': 'APPLIED_FOR_REQUIRED_EFFECTS',
                'dependencies': [ref.to_dict() for ref in self.dependencies]}

    @classmethod
    def parse(cls, value):
        value = json.loads(canonical_json_bytes(value))
        require(type(value) is dict and set(value) == {
            'schema', 'scope', 'task_id', 'graph_digest', 'candidate_id', 'required_outcome', 'dependencies'}
            and value['schema'] == BINDING_SCHEMA
            and value['required_outcome'] == 'APPLIED_FOR_REQUIRED_EFFECTS'
            and type(value['scope']) is list and len(value['scope']) == 4
            and type(value['dependencies']) is list, 'INVALID_COMPLETION_BINDING')
        return cls(OwnerScope(*value['scope']), value['task_id'], value['graph_digest'], value['candidate_id'],
                   tuple(TaskDependency.from_dict(ref) for ref in value['dependencies']))


def validate_completion_proof(value, binding):
    """Validate stored bounded proof metadata; hashes are not human authority."""
    value = json.loads(canonical_json_bytes(value))
    require(type(value) is dict and set(value) == {'schema', 'binding_digest', 'tasks'}
            and value['schema'] == PROOF_SCHEMA and value['binding_digest'] == binding.digest
            and type(value['tasks']) is list and 1 <= len(value['tasks']) <= MAX_REQUIRED_TASKS,
            'COMPLETION_PROOF_INTEGRITY')
    seen, nodes = set(), 0
    for evidence in value['tasks']:
        require(type(evidence) is dict and set(evidence) == {
            'task_id', 'graph_digest', 'candidate_id', 'ledger_revision', 'node_count',
            'applied_liability_ids', 'binding_digest'}, 'COMPLETION_PROOF_INTEGRITY')
        TaskDependency(binding.scope, evidence['task_id'], evidence['graph_digest'], evidence['candidate_id'])
        _digest(evidence['binding_digest'])
        require(type(evidence['ledger_revision']) is int and evidence['ledger_revision'] >= 1
                and type(evidence['node_count']) is int and 1 <= evidence['node_count'] <= MAX_NODES
                and type(evidence['applied_liability_ids']) is list
                and len(evidence['applied_liability_ids']) <= 128
                and len(set(evidence['applied_liability_ids'])) == len(evidence['applied_liability_ids'])
                and evidence['task_id'] not in seen, 'COMPLETION_PROOF_INTEGRITY')
        for identity in evidence['applied_liability_ids']:
            digest_id(identity, 'liability_id')
        nodes += evidence['node_count']
        seen.add(evidence['task_id'])
        if evidence['task_id'] == binding.task_id:
            require(evidence['binding_digest'] == binding.digest
                    and evidence['graph_digest'] == binding.graph_digest
                    and evidence['candidate_id'] == binding.candidate_id, 'COMPLETION_PROOF_INTEGRITY')
    require(binding.task_id in seen and nodes <= MAX_NODES, 'COMPLETION_PROOF_INTEGRITY')
    return value


def require_task_completion(gov, tx, job):
    """Required goal check called only inside the existing terminal mutation."""
    binding = TaskCompletionBinding.parse(job['completion_binding'])
    require(binding.scope == gov.policy.scope and binding.task_id == job['envelope']['task_id'],
            'INVALID_COMPLETION_BINDING')
    require(not binding.dependencies, 'TASK_DEPENDENCY_NOT_INTEGRATED')
    ledger = CoreLiabilityLedger(gov.core, gov.runner, gov.policy.scope)
    evidence = ledger.require_completion_in_transaction(
        tx, binding.task_id, binding.candidate_id, binding.graph_digest)
    evidence['binding_digest'] = binding.digest
    return validate_completion_proof({'schema': PROOF_SCHEMA, 'binding_digest': binding.digest,
                                      'tasks': [evidence]}, binding)
