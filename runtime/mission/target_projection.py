"""Host-owned target integrity facts in the existing Core transaction.

No runner, executor, file access or approval API is provided here. A production
registration route and physical Portable binding are not implemented. The pure
baseline codec does not authorize persistence or prove an INIT effect. Only
owned Applied observations are supported; no-effect certification stays closed.
"""

import json
from dataclasses import asdict

from lab.archaioa.faults import FaultTrace, opaque_id
from lab.archaioa.outcome import Applied
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.intent import CoreIntentJournal
from runtime.mission.liability import CoreLiabilityLedger, Reconciliation
from runtime.mission.target_settlement import (
    TARGET_BINDING_KIND,
    TARGET_SETTLEMENT_PROFILE,
    TargetBinding,
    TargetExecutionAck,
    TargetObservation,
    VerifiedTargetSettlement,
)
from runtime.mission.warrant import WarrantError, require

GENESIS = 'aioa-core-target-genesis.v1'
HEAD = 'aioa-core-target-head.v1'
HISTORY = 'aioa-core-target-history.v1'
MAX_TARGET_HISTORY = 128


def _json(value):
    return json.loads(canonical_json_bytes(value))


def _digest(value):
    require(type(value) is str and len(value) == 64
            and all(character in '0123456789abcdef' for character in value), 'TARGET_PROJECTION_INTEGRITY')
    return value


class CoreTargetProjection:
    profile = TARGET_SETTLEMENT_PROFILE

    def __init__(self, journal, liability, binding):
        require(type(journal) is CoreIntentJournal and type(liability) is CoreLiabilityLedger
                and type(binding) is TargetBinding and journal.ledger.core is liability.core
                and journal.ledger.runner is liability.runner
                and journal.ledger.scope == liability.scope == binding.scope, 'TARGET_PROJECTION_BINDING')
        self.journal, self.liability, self.binding = journal, liability, binding
        self.core, self.runner, self.scope = liability.core, liability.runner, liability.scope
        self.workspace, self.target_id = binding.workspace, binding.target_id
        # Exclude incarnation: a new object/epoch must not adopt the same name.
        self.head_key = canonical_sha256((HEAD, self.scope, self.workspace, self.target_id))
        self.genesis_key = canonical_sha256((GENESIS, self.head_key))

    def history_key(self, warrant):
        require(type(warrant) is EffectWarrant, 'INVALID_TARGET_WARRANT')
        return canonical_sha256((HISTORY, self.head_key, warrant.digest()))

    def _revision(self, generation):
        return 'core-target-' + self.binding.digest()[:16] + '-' + format(generation, '08x')

    def _context(self, tx, *, write=False):
        require(self.journal.ledger.core is self.liability.core is self.core
                and self.journal.ledger.runner is self.liability.runner is self.runner
                and self.journal.ledger.scope == self.liability.scope == self.scope == self.binding.scope
                and self.workspace == self.binding.workspace and self.target_id == self.binding.target_id
                and self.head_key == canonical_sha256((HEAD, self.scope, self.workspace, self.target_id))
                and self.genesis_key == canonical_sha256((GENESIS, self.head_key)),
                'TARGET_PROJECTION_BINDING')
        self.core.require(tx.context.principal, tx.context.purpose, scope=self.scope)
        require(tx.context.purpose is Capability.COMMIT if write else tx.context.purpose in (
            Capability.READ, Capability.COMMIT, Capability.OWNER_APPROVAL), 'TARGET_PROJECTION_CONTEXT')

    def encode_existing_baseline(self, *, state_root, target_revision, resources_root, receipts_root):
        """Encode facts only; caller still needs the approved registration path."""
        opaque_id(target_revision, 'target_revision')
        genesis = {'schema': GENESIS, 'target_key': self.head_key, 'binding_digest': self.binding.digest(),
                   'state_root': _digest(state_root), 'target_revision': target_revision,
                   'resources_root': _digest(resources_root), 'receipts_root': _digest(receipts_root)}
        genesis_digest = canonical_sha256(genesis)
        head = {**genesis, 'schema': HEAD, 'generation': 0, 'genesis_digest': genesis_digest,
                'history_digest': genesis_digest, 'in_flight': None}
        return (StoredRecord(RecordKind.OPERATION, self.genesis_key, self.scope, 1, genesis),
                StoredRecord(RecordKind.OPERATION, self.head_key, self.scope, 1, head))

    def _require_warrant_binding(self, warrant):
        require(type(warrant) is EffectWarrant and warrant.owner_scope == canonical_sha256(self.scope),
                'TARGET_WARRANT_BINDING_REQUIRED')
        refs = [ref for ref in warrant.decision_dependency_root.evidence_refs if ref.kind == TARGET_BINDING_KIND]
        require(refs == [self.binding.evidence()], 'TARGET_WARRANT_BINDING_REQUIRED')

    def _liability_entry(self, tx, warrant, resolution):
        _, state = self.liability._load(tx, warrant.task_id)
        matches = [(identity, entry) for identity, entry in state['entries'].items()
                   if FaultTrace.from_dict(entry['trace']).operation_digest == warrant.operation_hash]
        require(len(matches) == 1, 'TARGET_LIABILITY_BINDING')
        identity, entry = matches[0]
        require(entry['resolution'] == resolution
                and (entry['record']['status'] == 'CLOSED') == (resolution is not None), 'TARGET_LIABILITY_BINDING')
        return identity

    def _observation(self, value):
        require(type(value) is dict and type(value.get('scope')) is dict, 'TARGET_HISTORY_INTEGRITY')
        observation = TargetObservation(**{**value, 'scope': OwnerScope(**value['scope'])})
        self.binding.require_observation(observation)
        return observation

    def _details(self, tx):
        self._context(tx)
        try:
            return self._checked_details(tx)
        except (KeyError, TypeError, AttributeError):
            raise WarrantError('TARGET_PROJECTION_INTEGRITY') from None

    def _checked_details(self, tx):
        row = tx.get(RecordKind.OPERATION, self.head_key)
        initial = tx.get(RecordKind.OPERATION, self.genesis_key)
        require(row is not None and initial is not None, 'TARGET_REGISTERED_BASELINE_REQUIRED')
        head, genesis = _json(row.payload), _json(initial.payload)
        baseline_fields = {'schema', 'target_key', 'binding_digest', 'state_root', 'target_revision',
                           'resources_root', 'receipts_root'}
        require(set(genesis) == baseline_fields and genesis['schema'] == GENESIS and initial.revision == 1,
                'TARGET_GENESIS_INTEGRITY')
        require(set(head) == baseline_fields | {'generation', 'genesis_digest', 'history_digest', 'in_flight'}
                and head['schema'] == HEAD and head['target_key'] == genesis['target_key'] == self.head_key
                and head['binding_digest'] == genesis['binding_digest'] == self.binding.digest(),
                'TARGET_PROJECTION_BINDING')
        for value in (head, genesis):
            for name in ('state_root', 'resources_root', 'receipts_root'):
                _digest(value[name])
            opaque_id(value['target_revision'], 'target_revision')
        require(type(head['generation']) is int and 0 <= head['generation'] <= MAX_TARGET_HISTORY,
                'TARGET_HISTORY_QUOTA')
        digest = canonical_sha256(genesis)
        require(head['genesis_digest'] == digest, 'TARGET_GENESIS_INTEGRITY')
        rows = tx.scan(RecordKind.OPERATION, limit=1024)
        require(len(rows) < 1024, 'TARGET_HISTORY_SCAN_QUOTA')
        history_rows = [candidate for candidate in rows if candidate.payload.get('schema') == HISTORY
                        and candidate.payload.get('target_key') == self.head_key]
        require(len(history_rows) == head['generation'], 'TARGET_HISTORY_INTEGRITY')
        history_rows.sort(key=lambda candidate: candidate.payload['generation'])
        root, resources, receipts, revision = (genesis[name] for name in (
            'state_root', 'resources_root', 'receipts_root', 'target_revision'))
        last_head_revision = 1
        histories = {}
        for generation, record in enumerate(history_rows, 1):
            history = _json(record.payload)
            require(set(history) == {'schema', 'target_key', 'binding_digest', 'generation', 'previous_digest',
                    'warrant_digest', 'warrant', 'liability_id', 'observation', 'resolution', 'head_revision_after'}
                    and record.revision == 1 and type(history['generation']) is int
                    and history['generation'] == generation and history['previous_digest'] == digest
                    and history['binding_digest'] == self.binding.digest(), 'TARGET_HISTORY_INTEGRITY')
            warrant = EffectWarrant.from_dict(history['warrant'])
            self._require_warrant_binding(warrant)
            observation = self._observation(history['observation'])
            resolution = Reconciliation.from_dict(history['resolution'])
            require(type(resolution.outcome) is Applied and record.record_id == self.history_key(warrant)
                    and history['warrant_digest'] == warrant.digest() and warrant.digest() not in histories
                    and observation.generation == generation - 1 and observation.before_root == root
                    and observation.operation_digest == resolution.operation_digest == warrant.operation_hash
                    and warrant.target_fingerprint == 'sha256:' + root
                    and warrant.expected_target_revision == revision
                    and observation.expected_head_revision > last_head_revision
                    and type(history['head_revision_after']) is int
                    and history['head_revision_after'] == observation.expected_head_revision + 1,
                    'TARGET_HISTORY_INTEGRITY')
            # Reconstruct the closed proof envelope as well as its raw fields.
            VerifiedTargetSettlement(resolution, observation)
            intent_row, intent = self.journal._load(tx, warrant)
            require(intent_row is not None and intent['resolution'] == history['resolution'],
                    'TARGET_HISTORY_INTENT_REQUIRED')
            require(self._liability_entry(tx, warrant, history['resolution']) == history['liability_id'],
                    'TARGET_HISTORY_LIABILITY_REQUIRED')
            histories[warrant.digest()] = history
            digest = canonical_sha256(history)
            root, resources, receipts = observation.after_root, observation.resources_root, observation.receipts_root
            revision, last_head_revision = self._revision(generation), history['head_revision_after']
        require((head['state_root'], head['resources_root'], head['receipts_root'], head['target_revision'],
                 head['history_digest']) == (root, resources, receipts, revision, digest), 'TARGET_HEAD_HISTORY_LINK')
        flight = head['in_flight']
        if flight is None:
            require(row.revision == last_head_revision, 'TARGET_HEAD_REVISION')
        else:
            require(type(flight) is dict and set(flight) == {'phase', 'warrant', 'warrant_digest', 'ack'}
                    and flight['phase'] in ('STARTED', 'RELEASED'), 'TARGET_IN_FLIGHT_INTEGRITY')
            warrant = EffectWarrant.from_dict(flight['warrant'])
            self._require_warrant_binding(warrant)
            require(flight['warrant_digest'] == warrant.digest() and warrant.digest() not in histories
                    and warrant.target_fingerprint == 'sha256:' + root
                    and warrant.expected_target_revision == revision, 'TARGET_IN_FLIGHT_INTEGRITY')
            _, intent = self.journal._load(tx, warrant)
            require(intent is not None and intent['resolution'] is None, 'TARGET_IN_FLIGHT_INTENT_REQUIRED')
            self._liability_entry(tx, warrant, None)
            offset = 1 if flight['phase'] == 'STARTED' else 2
            if flight['ack'] is not None:
                require(flight['phase'] == 'RELEASED', 'TARGET_ACK_PHASE')
                self.binding.require_ack(warrant, TargetExecutionAck(**flight['ack']))
                offset += 1
            require(row.revision == last_head_revision + offset, 'TARGET_HEAD_REVISION')
        return row, head, histories

    def load(self, tx):
        row, state, _ = self._details(tx)
        return row, state

    def _save_head(self, tx, row, state):
        tx.replace(StoredRecord(row.kind, row.record_id, self.scope, row.revision + 1, state),
                   expected_revision=row.revision)

    def _flight(self, tx, warrant):
        self._require_warrant_binding(warrant)
        row, state, histories = self._details(tx)
        require(type(warrant) is EffectWarrant and state['in_flight'] is not None
                and state['in_flight']['warrant_digest'] == warrant.digest()
                and warrant.digest() not in histories, 'TARGET_IN_FLIGHT_REQUIRED')
        return row, state

    def start_in_transaction(self, tx, warrant, operation, snapshot):
        self._context(tx, write=True)
        self._require_warrant_binding(warrant)
        row, state = self.load(tx)
        require(state['in_flight'] is None and state['generation'] < MAX_TARGET_HISTORY, 'TARGET_IN_FLIGHT_OR_QUOTA')
        require(snapshot.fingerprint == warrant.target_fingerprint == 'sha256:' + state['state_root']
                and snapshot.revision == warrant.expected_target_revision == state['target_revision']
                and 'sha256:' + canonical_sha256(operation) == warrant.operation_hash
                and self.binding.evidence() in snapshot.ddr.evidence_refs, 'TARGET_START_BINDING')
        intent_row, intent = self.journal._load(tx, warrant)
        require(intent_row is not None and intent['resolution'] is None, 'TARGET_START_INTENT_REQUIRED')
        state['in_flight'] = {'phase': 'STARTED', 'warrant': warrant.to_dict(),
                              'warrant_digest': warrant.digest(), 'ack': None}
        self._save_head(tx, row, state)

    def before_release_in_transaction(self, tx, warrant, operation, snapshot):
        self._context(tx, write=True)
        row, state = self._flight(tx, warrant)
        require(state['in_flight']['phase'] == 'STARTED'
                and snapshot.fingerprint == 'sha256:' + state['state_root']
                and snapshot.revision == state['target_revision']
                and 'sha256:' + canonical_sha256(operation) == warrant.operation_hash, 'TARGET_RELEASE_BINDING')
        state['in_flight']['phase'] = 'RELEASED'
        self._save_head(tx, row, state)

    def record_ack_in_transaction(self, tx, warrant, acknowledgment):
        self._context(tx, write=True)
        self._require_warrant_binding(warrant)
        self.binding.require_ack(warrant, acknowledgment)
        row, state = self._flight(tx, warrant)
        require(state['in_flight']['phase'] == 'RELEASED' and state['in_flight']['ack'] is None, 'TARGET_ACK_PHASE')
        state['in_flight']['ack'] = acknowledgment.to_dict()
        self._save_head(tx, row, state)

    def apply_resolution_in_transaction(self, tx, warrant, epoch, verified):
        self._context(tx, write=True)
        require(type(verified) is VerifiedTargetSettlement, 'VERIFIED_TARGET_OBSERVATION_REQUIRED')
        self.binding.require_observation(verified.target)
        row, state = self._flight(tx, warrant)
        target, resolution = verified.target, verified.resolution
        self.journal.governor._epoch(self.journal.governor._load(tx), epoch)
        require(state['in_flight']['phase'] == 'RELEASED' and type(resolution.outcome) is Applied,
                'TARGET_OWNED_APPLIED_CERTIFICATE_REQUIRED')
        require(target.expected_head_revision == row.revision and target.generation == state['generation']
                and target.before_root == state['state_root']
                and target.operation_digest == warrant.operation_hash, 'STALE_TARGET_OBSERVATION')
        acknowledgment = state['in_flight']['ack']
        require(acknowledgment is None or acknowledgment['target_root'] == target.after_root, 'TARGET_ACK_READBACK_MISMATCH')
        generation = state['generation'] + 1
        history = {'schema': HISTORY, 'target_key': self.head_key, 'binding_digest': self.binding.digest(),
                   'generation': generation, 'previous_digest': state['history_digest'],
                   'warrant_digest': warrant.digest(), 'warrant': warrant.to_dict(),
                   'liability_id': self._liability_entry(tx, warrant, None),
                   'observation': asdict(target), 'resolution': resolution.to_dict(),
                   'head_revision_after': row.revision + 1}
        tx.insert(StoredRecord(RecordKind.OPERATION, self.history_key(warrant), self.scope, 1, history))
        state.update(generation=generation, state_root=target.after_root,
                     resources_root=target.resources_root, receipts_root=target.receipts_root,
                     target_revision=self._revision(generation), history_digest=canonical_sha256(history), in_flight=None)
        self._save_head(tx, row, state)

    def check_history_in_transaction(self, tx, warrant, intent):
        self._require_warrant_binding(warrant)
        _, state, histories = self._details(tx)
        if intent['resolution'] is None:
            require(state['in_flight'] is not None
                    and state['in_flight']['warrant_digest'] == warrant.digest(), 'TARGET_IN_FLIGHT_REQUIRED')
        else:
            history = histories.get(warrant.digest())
            require(history is not None and history['resolution'] == intent['resolution'], 'TARGET_HISTORY_REQUIRED')
