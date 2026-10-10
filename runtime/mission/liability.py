"""Durable G2 uncertainty on the existing owner-scoped Core transaction port.

This service has no executor, provider, credentials or default reconciliation
verifier. An explicitly bound host verifier must establish independent truth;
evidence metadata alone cannot close a liability. Completion is a read-only
decision recomputed from the stored graph, not a scheduler mutation.
"""
from dataclasses import dataclass, replace
import json

from lab.archaioa.contracts import ContractValidationError, digest_id
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.faults import FaultTrace, classify_fault, open_liability, resolve_liability
from lab.archaioa.liability import LiabilityRecord, LiabilityStatus
from lab.archaioa.outcome import Applied, NotApplied, Unknown
from lab.archaioa.taint import DependencyGraph, propagate_taint
from lab.archaioa.task_semantics import CompletionState, check_completion
from runtime.core_admission import Capability, CoreAdmission, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext, TransactionRunner

KIND = 'aioa-liability-ledger-v1'
MAX_LIABILITIES = 128
MAX_NODES = 512


class LiabilityError(MemoryPatchError, ValueError):
    """Only fixed reason codes cross the domain boundary."""
    def __init__(self, reason):
        super().__init__(ErrorCode.INTEGRITY_FAILED)
        self.args = (reason,)


def require(condition, reason='LIABILITY_INTEGRITY'):
    if not condition:
        raise LiabilityError(reason)


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """Output of the trusted independent verifier, never remote caller input.

    NotApplied still requires an independently verified no-effect certificate
    in the receipt slot. A timeout or missing receipt cannot form this value.
    """
    operation_digest: str
    outcome: Applied | NotApplied
    receipt: EvidenceRef
    readback: EvidenceRef

    def __post_init__(self):
        digest_id(self.operation_digest, 'operation_digest')
        require(type(self.outcome) in (Applied, NotApplied), 'UNRESOLVED_READBACK')
        require(type(self.receipt) is EvidenceRef and type(self.readback) is EvidenceRef,
                'INDEPENDENT_EVIDENCE_REQUIRED')
        require(self.receipt.evidence_id != self.readback.evidence_id
                and self.receipt.digest != self.readback.digest
                and self.readback.kind == 'independent-readback', 'INDEPENDENT_EVIDENCE_REQUIRED')
        if type(self.outcome) is Applied:
            require(self.outcome.receipt_ref == self.receipt.evidence_id
                    and self.receipt.kind == 'receipt', 'RECEIPT_BINDING')
        else:
            require(self.receipt.kind == 'no-effect-certificate', 'NO_EFFECT_CERTIFICATE_REQUIRED')

    def to_dict(self):
        return {'operation_digest': self.operation_digest, 'outcome': self.outcome.to_dict(),
                'receipt': self.receipt.to_dict(), 'readback': self.readback.to_dict()}

    @classmethod
    def from_dict(cls, value):
        require(type(value) is dict and set(value) == {'operation_digest', 'outcome', 'receipt', 'readback'})
        variant = {'Applied': Applied, 'NotApplied': NotApplied}.get(value['outcome'].get('contract_type'))
        require(variant is not None)
        return cls(value['operation_digest'], variant.from_dict(value['outcome']),
                   EvidenceRef.from_dict(value['receipt']), EvidenceRef.from_dict(value['readback']))


class CoreLiabilityLedger:
    """No second authority: all reads/writes require the supplied Core principal.

    Graphs are immutable per task identity. Replanning uses a new task identity
    with its required liability references; silently dropping dependencies is
    prohibited. No live composition enables this service by default.
    """
    def __init__(self, core, runner, scope, *, verifier=None):
        require(type(core) is CoreAdmission and type(runner) is TransactionRunner
                and type(scope) is OwnerScope and (verifier is None or callable(verifier)),
                'INVALID_LIABILITY_BINDINGS')
        self.core, self.runner, self.scope, self.verifier = core, runner, scope, verifier

    def _key(self, task_id):
        from lab.archaioa.faults import opaque_id
        opaque_id(task_id, 'task_id')
        return canonical_sha256((KIND, self.scope, task_id))

    def _run(self, principal, purpose, callback):
        self.core.require(principal, purpose, scope=self.scope)
        def guarded(tx):
            try:
                return callback(tx)
            except ContractValidationError:
                # Preserve a typed domain denial across the native runner;
                # plain lab ValueError would be wrapped as TRANSACTION_FAILED.
                raise LiabilityError('LIABILITY_CONTRACT_INVALID') from None
        return self.runner.run(TransactionContext(principal, purpose), guarded)

    def _load(self, tx, task_id, *, optional=False):
        stored = tx.get(RecordKind.OPERATION, self._key(task_id))
        if stored is None:
            require(optional, 'LIABILITY_STATE_REQUIRED')
            return None, None
        try:
            state = json.loads(canonical_json_bytes(stored.payload))
            require(set(state) == {'schema', 'graph', 'entries'} and state['schema'] == KIND)
            graph = DependencyGraph.from_dict(state['graph'])
            require(graph.task_id == task_id and len(graph.nodes) <= MAX_NODES)
            require(type(state['entries']) is dict and len(state['entries']) <= MAX_LIABILITIES)
            referenced = {identity for node in graph.nodes for identity in node.liability_ids}
            for identity, entry in state['entries'].items():
                require(set(entry) == {'trace', 'record', 'resolution'})
                trace = FaultTrace.from_dict(entry['trace'])
                record = LiabilityRecord.from_dict(entry['record'])
                require(identity in referenced and identity == classify_fault(trace).liability_id
                        and record.liability_id == identity and trace.task_id == task_id
                        and record.task_id == task_id and record.request_ref == trace.request_ref
                        and record.kind == 'UNKNOWN_EFFECT')
                if record.status is LiabilityStatus.CLOSED:
                    resolution = Reconciliation.from_dict(entry['resolution'])
                    require(resolution.operation_digest == trace.operation_digest
                            and record.resolution_ref == resolution.readback.evidence_id
                            and resolution.readback in record.evidence_refs
                            and resolution.receipt in record.evidence_refs)
                else:
                    require(entry['resolution'] is None)
            return stored, state
        except (KeyError, TypeError, AttributeError, ContractValidationError, ValueError):
            raise LiabilityError('LIABILITY_INTEGRITY') from None

    def _save(self, tx, task_id, stored, state):
        record = StoredRecord(RecordKind.OPERATION, self._key(task_id), self.scope,
                              stored.revision + 1 if stored else 1, state)
        if stored is None:
            tx.insert(record)
        else:
            tx.replace(record, expected_revision=stored.revision)

    def initialize(self, principal, graph):
        """Explicit immutable graph initialization; absent state never means clean.

        Planned effects need predeclared references. Missing referenced records
        still deny completion; this method does not fabricate Applied results.
        """
        require(type(graph) is DependencyGraph and len(graph.nodes) <= MAX_NODES,
                'INVALID_UNKNOWN_BINDING')
        def mutation(tx):
            stored, state = self._load(tx, graph.task_id, optional=True)
            if state is None:
                self._save(tx, graph.task_id, stored,
                           {'schema': KIND, 'graph': graph.to_dict(), 'entries': {}})
            else:
                require(state['graph'] == graph.to_dict(), 'DEPENDENCY_GRAPH_CONFLICT')
        return self._run(principal, Capability.COMMIT, mutation)

    def record_unknown(self, principal, trace, graph, opened_at, *, dependency_refs=()):
        require(type(trace) is FaultTrace and type(graph) is DependencyGraph
                and trace.task_id == graph.task_id and len(graph.nodes) <= MAX_NODES,
                'INVALID_UNKNOWN_BINDING')
        record = replace(open_liability(trace, opened_at), dependency_refs=dependency_refs)
        outcome = classify_fault(trace)
        require(any(outcome.liability_id in node.liability_ids for node in graph.nodes),
                'LIABILITY_DEPENDENCY_REQUIRED')
        def mutation(tx):
            stored, state = self._load(tx, trace.task_id, optional=True)
            if state is None:
                state = {'schema': KIND, 'graph': graph.to_dict(), 'entries': {}}
            require(state['graph'] == graph.to_dict(), 'DEPENDENCY_GRAPH_CONFLICT')
            existing = state['entries'].get(outcome.liability_id)
            if existing is not None:
                require(existing['record']['status'] != 'CLOSED', 'CLOSED_UNKNOWN_CONFLICT')
                # Same operation's different ambiguous observations do not reset
                # escalation, time, dependency references or the nonce barrier.
                return outcome
            require(len(state['entries']) < MAX_LIABILITIES, 'LIABILITY_QUOTA')
            state['entries'][outcome.liability_id] = {'trace': trace.to_dict(),
                'record': record.to_dict(), 'resolution': None}
            self._save(tx, trace.task_id, stored, state)
            return outcome
        return self._run(principal, Capability.COMMIT, mutation)

    def inspect(self, principal, task_id):
        def read(tx):
            _, state = self._load(tx, task_id)
            return self._records(state)
        return self._run(principal, Capability.READ, read)

    @staticmethod
    def _records(state):
        return tuple(LiabilityRecord.from_dict(entry['record'])
                     for _, entry in sorted(state['entries'].items()))

    def taint(self, principal, task_id):
        def read(tx):
            _, state = self._load(tx, task_id)
            return propagate_taint(DependencyGraph.from_dict(state['graph']), self._records(state))
        return self._run(principal, Capability.READ, read)

    def completion(self, principal, task_id, candidate_id):
        def read(tx):
            _, state = self._load(tx, task_id)
            return check_completion(DependencyGraph.from_dict(state['graph']), candidate_id, self._records(state))
        return self._run(principal, Capability.READ, read)

    def require_completion_in_transaction(self, tx, task_id, candidate_id, graph_digest):
        """Evaluate required goal evidence within the caller's native transaction.

        The caller must commit its terminal write in this same serializable
        transaction. This helper opens no runner and grants no effect authority.
        Legacy `completion` remains a read-only uncertainty decision.
        """
        self.core.require(tx.context.principal, tx.context.purpose, scope=self.scope)
        require(tx.context.purpose in (Capability.READ, Capability.COMMIT), 'INVALID_COMPLETION_BINDING')
        stored, state = self._load(tx, task_id)
        require(canonical_sha256(state['graph']) == graph_digest, 'DEPENDENCY_GRAPH_CONFLICT')
        try:
            graph = DependencyGraph.from_dict(state['graph'])
            decision = check_completion(graph, candidate_id, self._records(state))
            require(decision.state is CompletionState.COMPLETED, 'REQUIRED_LIABILITY_OPEN')
            by_id = {node.node_id: node for node in graph.nodes}
            ancestors, pending = set(), [candidate_id]
            while pending:
                node_id = pending.pop()
                if node_id in ancestors:
                    continue
                ancestors.add(node_id)
                pending.extend(by_id[node_id].required_dependencies)
            required_ids = sorted({identity for node_id in ancestors
                                   for identity in by_id[node_id].liability_ids})
            for identity in required_ids:
                resolution = Reconciliation.from_dict(state['entries'][identity]['resolution'])
                require(type(resolution.outcome) is Applied, 'REQUIRED_GOAL_NOT_APPLIED')
            return {'task_id': task_id, 'graph_digest': graph_digest, 'candidate_id': candidate_id,
                    'ledger_revision': stored.revision, 'node_count': len(graph.nodes),
                    'applied_liability_ids': required_ids}
        except ContractValidationError:
            raise LiabilityError('LIABILITY_CONTRACT_INVALID') from None

    def escalate(self, principal, task_id, liability_id):
        def mutation(tx):
            stored, state = self._load(tx, task_id)
            require(liability_id in state['entries'], 'LIABILITY_REFERENCE_REQUIRED')
            entry = state['entries'][liability_id]
            record = LiabilityRecord.from_dict(entry['record'])
            require(record.status is not LiabilityStatus.CLOSED, 'CLOSED_UNKNOWN_CONFLICT')
            if record.status is LiabilityStatus.OPEN:
                entry['record'] = replace(record, status=LiabilityStatus.ESCALATED).to_dict()
                self._save(tx, task_id, stored, state)
        return self._run(principal, Capability.COMMIT, mutation)

    def reconcile(self, principal, task_id, liability_id, closed_at):
        require(self.verifier is not None, 'RECONCILIATION_DISABLED')
        # Verify independently outside the retried transaction callback. A lost
        # commit ACK is propagated; callers read back, never repeat an effect.
        def snapshot(tx):
            _, state = self._load(tx, task_id)
            require(liability_id in state['entries'], 'LIABILITY_REFERENCE_REQUIRED')
            return state['entries'][liability_id]
        entry = self._run(principal, Capability.COMMIT, snapshot)
        if entry['resolution'] is not None:
            return Reconciliation.from_dict(entry['resolution']).outcome
        trace = FaultTrace.from_dict(entry['trace'])
        record = LiabilityRecord.from_dict(entry['record'])
        try:
            resolution = self.verifier(trace, record)
        except Exception:
            raise LiabilityError('INDEPENDENT_READBACK_UNAVAILABLE') from None
        require(type(resolution) is Reconciliation, 'INDEPENDENT_EVIDENCE_REQUIRED')
        require(resolution.operation_digest == trace.operation_digest, 'RECONCILIATION_BINDING')
        def mutation(tx):
            stored, state = self._load(tx, task_id)
            current = state['entries'][liability_id]
            if current['resolution'] is not None:
                prior = Reconciliation.from_dict(current['resolution'])
                require(prior == resolution, 'RECONCILIATION_CONFLICT')
                return prior.outcome
            require(current == entry, 'STALE_RECONCILIATION')
            resolved = resolve_liability(replace(record, evidence_refs=record.evidence_refs + (resolution.receipt,)),
                                         resolution.readback, closed_at)
            current['record'] = resolved.to_dict()
            current['resolution'] = resolution.to_dict()
            self._save(tx, task_id, stored, state)
            return resolution.outcome
        return self._run(principal, Capability.COMMIT, mutation)
