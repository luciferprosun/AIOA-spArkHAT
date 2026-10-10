"""Offline G4 journal on the native transaction port; no executor or live wiring.

START atomically consumes the warrant, reserves both budget dimensions and
persists the exact intent plus outbox. START is pessimistically UNKNOWN even
when the host crashes before sending. Redelivery never grants another step.
A host-owned independent verifier is required to publish a known outcome.
Serializable transactions and scoped revision CAS are adapter requirements;
there is no atomic database/target transaction or distributed exactly-once claim.
"""
import json

from lab.archaioa.outcome import Applied, NotApplied, Unknown
from lab.archaioa.warrant import EffectWarrant
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord, TransactionContext
from runtime.mission.governor import CoreDualGovernor, ReservationRequest
from runtime.mission.liability import Reconciliation
from runtime.mission.warrant import CoreWarrantLedger, require

KIND = 'aioa-effect-intent-v1'


class CoreIntentJournal:
    def __init__(self, ledger, governor, *, verifier=None):
        require(type(ledger) is CoreWarrantLedger and type(governor) is CoreDualGovernor
                and ledger.core is governor.core and ledger.runner is governor.runner
                and ledger.scope == governor.policy.scope
                and (verifier is None or callable(verifier)), 'INVALID_INTENT_BINDINGS')
        self.ledger, self.governor, self.verifier = ledger, governor, verifier

    def _key(self, warrant):
        require(type(warrant) is EffectWarrant, 'INVALID_INTENT_WARRANT')
        return canonical_sha256((KIND, self.ledger.scope, warrant.task_id, warrant.operation_hash))

    def _run(self, principal, purpose, callback):
        self.ledger.core.require(principal, purpose, scope=self.ledger.scope)
        return self.ledger.runner.run(TransactionContext(principal, purpose), callback)

    def _load(self, tx, warrant):
        row = tx.get(RecordKind.OPERATION, self._key(warrant))
        if row is None:
            return None, None
        state = json.loads(canonical_json_bytes(row.payload))
        require(set(state) == {'schema', 'warrant_digest', 'operation', 'reservation',
                               'epoch', 'outcome', 'liability_id', 'resolution'}
                and state['schema'] == KIND and state['warrant_digest'] == warrant.digest(),
                'INTENT_BINDING')
        require('sha256:' + canonical_sha256(state['operation']) == warrant.operation_hash
                and type(state['epoch']) is int and state['epoch'] == warrant.lease_epoch
                and state['liability_id'] == 'intent-' + row.record_id, 'INTENT_INTEGRITY')
        variant = state['outcome'].get('contract_type')
        if variant == 'Unknown':
            require(Unknown.from_dict(state['outcome']).liability_id == state['liability_id']
                    and state['resolution'] is None, 'INTENT_INTEGRITY')
        else:
            require(variant in ('Applied', 'NotApplied') and state['resolution'] is not None,
                    'INTENT_INTEGRITY')
            resolution = Reconciliation.from_dict(state['resolution'])
            require(resolution.operation_digest == warrant.operation_hash
                    and resolution.outcome.to_dict() == state['outcome'], 'INTENT_INTEGRITY')
        outbox = tx.get(RecordKind.OUTBOX, self._key(warrant))
        require(outbox is not None and set(outbox.payload) == {'state', 'intent_digest'}
                and outbox.payload['state'] in ('HELD', 'PENDING', 'DELIVERED')
                and outbox.payload['intent_digest'] == canonical_sha256(state)
                and (outbox.payload['state'] == 'HELD') == (variant == 'Unknown'),
                'INTENT_OUTBOX_INTEGRITY')
        _, approval, active = self.ledger._load(tx, warrant)
        require(active == warrant and approval['consumption'] == self.ledger._receipt(warrant),
                'INTENT_WARRANT_INTEGRITY')
        reservation = self.governor._load(tx)['reservations'].get(warrant.money_reservation_id)
        require(reservation is not None and reservation['binding_digest'] == state['reservation']
                and reservation['request_digest'] == canonical_sha256(state['operation'])
                and reservation['task_id'] == warrant.task_id
                and reservation['epoch'] == state['epoch']
                and reservation['state'] == ('UNKNOWN' if variant == 'Unknown' else 'COMMITTED')
                and reservation['evidence_digest'] == canonical_sha256(
                    state['liability_id'] if variant == 'Unknown' else resolution),
                'INTENT_RESERVATION_INTEGRITY')
        return row, state

    def _save(self, tx, warrant, state, row=None):
        key = self._key(warrant)
        record = StoredRecord(RecordKind.OPERATION, key, self.ledger.scope,
                              row.revision + 1 if row else 1, state)
        outbox = tx.get(RecordKind.OUTBOX, key)
        box = StoredRecord(RecordKind.OUTBOX, key, self.ledger.scope,
                           outbox.revision + 1 if outbox else 1,
                           {'state': 'HELD' if state['resolution'] is None else 'PENDING',
                            'intent_digest': canonical_sha256(state)})
        if row is None:
            tx.insert(record); tx.insert(box)
        else:
            tx.replace(record, expected_revision=row.revision)
            tx.replace(box, expected_revision=outbox.revision)

    @staticmethod
    def _public(state):
        return {'outcome': state['outcome'], 'liability_id': state['liability_id'],
                'authority': 'NONE', 'grants_replay': False}

    def start(self, principal, warrant, operation, reservation):
        return self._run(principal, Capability.COMMIT,
                         lambda tx: self.start_in_transaction(tx, warrant, operation, reservation))

    def start_in_transaction(self, tx, warrant, operation, reservation):
        """One fixture step marker, never authority to WRITE_LOCAL/EXEC_LOCAL.

        This initial adapter supports a single paired money/risk reservation ID.
        Separate reservation ledgers require a new reviewed atomic adapter.
        money_nano is interpreted in the warrant's currency; risk units require
        the trusted host's calibrated policy. This is not a live risk adapter.
        The trusted host supplies freshly verified target revision/fingerprint/DDR.
        """
        principal = tx.context.principal
        require(tx.context.purpose is Capability.COMMIT, 'INVALID_INTENT_CONTEXT')
        self.ledger.core.require(principal, Capability.COMMIT, scope=self.ledger.scope)
        require(type(warrant) is EffectWarrant, 'INVALID_INTENT_WARRANT')
        require(type(operation) is dict and len(canonical_json_bytes(operation)) <= 4096,
                'INVALID_INTENT')
        operation = json.loads(canonical_json_bytes(operation))
        require(set(operation) == {'operation_class', 'target_fingerprint',
                                   'expected_target_revision', 'payload'}
                and operation['operation_class'] == warrant.operation_class
                and operation['target_fingerprint'] == warrant.target_fingerprint
                and operation['expected_target_revision'] == warrant.expected_target_revision
                and 'sha256:' + canonical_sha256(operation) == warrant.operation_hash,
                'INTENT_BINDING')
        require(type(reservation) is ReservationRequest
                and reservation.request_id == warrant.money_reservation_id == warrant.risk_reservation_id
                and reservation.task_id == warrant.task_id
                and reservation.request_digest == canonical_sha256(operation)
                and 0 < reservation.money_nano <= warrant.authority_scope.monetary_ceiling.amount * 10**9
                and reservation.risk_units > 0, 'RESERVATION_BINDING')
        gov = self.governor
        gov._require(principal, Capability.COMMIT)
        require(reservation.model_id in principal.model_binding_ids, 'MODEL_BINDING_DENIED')
        now = gov._now()
        before = gov._load(tx)
        gov._epoch(before, warrant.lease_epoch)
        row, existing = self._load(tx, warrant)
        if row is not None:
            require(existing['operation'] == operation
                    and existing['reservation'] == canonical_sha256(reservation), 'INTENT_BINDING')
            return {'fixture_step_now': False, **self._public(existing)}
        self.ledger._check(warrant)
        # Conservative owner-wide barrier: revised intent/nonce cannot bypass
        # an unresolved send. A new effect requires independent resolution.
        # UNKNOWN budget holds remain authoritative even if an older intent's
        # resolution marker is malformed. No new START until reconciliation.
        require(not any(entry['state'] == 'UNKNOWN'
                        for entry in before['reservations'].values()), 'UNRESOLVED_INTENT')
        rows = tx.scan(RecordKind.OPERATION, limit=1024)
        require(len(rows) < 1024, 'INTENT_HISTORY_QUOTA')
        require(not any(r.payload.get('schema') == KIND and r.payload.get('resolution') is None
                        for r in rows), 'UNRESOLVED_INTENT')
        stored, approval, active = self.ledger._load(tx, warrant)
        require(active == warrant and approval['consumption'] is None, 'WARRANT_INACTIVE')
        state = json.loads(canonical_json_bytes(before))
        gov._clock(state, now)
        entry, _ = gov._reserve_state(state, reservation, warrant.lease_epoch, now)
        require(entry['state'] == 'RESERVED', 'RESERVATION_INACTIVE')
        marker, _ = gov._dispatch_state(state, reservation.request_id, warrant.lease_epoch, now)
        require(marker['dispatch_now'], 'RESERVATION_INACTIVE')
        liability_id = 'intent-' + self._key(warrant)
        gov._unknown_state(state, reservation.request_id, warrant.lease_epoch,
                           canonical_sha256(liability_id), now)
        approval['consumption'] = self.ledger._receipt(warrant)
        self.ledger._save(tx, warrant, approval, stored)
        intent = {'schema': KIND, 'warrant_digest': warrant.digest(), 'operation': operation,
                  'reservation': canonical_sha256(reservation), 'epoch': warrant.lease_epoch,
                  'outcome': Unknown(liability_id).to_dict(), 'liability_id': liability_id,
                  'resolution': None}
        self._save(tx, warrant, intent)
        gov._write(tx, before, state, now)
        return {'fixture_step_now': True, **self._public(intent)}

    def inspect(self, principal, warrant):
        def read(tx):
            _, state = self._load(tx, warrant)
            require(state is not None, 'INTENT_REQUIRED')
            return self._public(state)
        return self._run(principal, Capability.READ, read)

    def reconcile(self, principal, warrant, epoch):
        """Independent readback outside the transaction; takeover is reconcile-only.

        A timeout/missing receipt leaves UNKNOWN and its reservation intact.
        A stale leader cannot commit a verifier result after epoch takeover.
        """
        self.ledger.core.require(principal, Capability.COMMIT, scope=self.ledger.scope)
        require(self.verifier is not None, 'INDEPENDENT_READBACK_REQUIRED')
        # Read validated immutable intent first; never accept remote resolution input.
        def read(tx):
            _, state = self._load(tx, warrant)
            require(state is not None, 'INTENT_REQUIRED')
            return state['operation']
        operation = self._run(principal, Capability.COMMIT, read)
        resolution = self.verifier(operation)
        require(type(resolution) is Reconciliation
                and resolution.operation_digest == warrant.operation_hash, 'UNRESOLVED_READBACK')
        return self._run(principal, Capability.COMMIT,
                         lambda tx: self.apply_resolution_in_transaction(tx, warrant, epoch, resolution))

    def apply_resolution_in_transaction(self, tx, warrant, epoch, resolution):
        """Apply independently verified truth inside the caller's existing tx."""
        require(tx.context.purpose is Capability.COMMIT, 'INVALID_INTENT_CONTEXT')
        self.ledger.core.require(tx.context.principal, Capability.COMMIT, scope=self.ledger.scope)
        require(type(resolution) is Reconciliation
                and resolution.operation_digest == warrant.operation_hash, 'UNRESOLVED_READBACK')
        gov = self.governor
        now = gov._now()
        before = gov._load(tx); gov._epoch(before, epoch)
        row, intent = self._load(tx, warrant)
        if intent['resolution'] is not None:
            require(intent['resolution'] == resolution.to_dict(), 'RESOLUTION_CONFLICT')
            return self._public(intent)
        state = json.loads(canonical_json_bytes(before)); gov._clock(state, now)
        gov._settle_state(state, warrant.money_reservation_id, epoch, canonical_sha256(resolution))
        intent.update(outcome=resolution.outcome.to_dict(), resolution=resolution.to_dict())
        self._save(tx, warrant, intent, row); gov._write(tx, before, state, now)
        return self._public(intent)

    def delivery(self, principal, warrant):
        """Read-only minimal publication projection. Retry delivery, never effect."""
        def read(tx):
            _, state = self._load(tx, warrant)
            require(state is not None and state['resolution'] is not None, 'OUTCOME_UNKNOWN')
            box = tx.get(RecordKind.OUTBOX, self._key(warrant))
            return {**self._public(state), 'delivery_revision': box.revision,
                    'delivery_state': box.payload['state']}
        return self._run(principal, Capability.READ, read)

    def acknowledge_delivery(self, principal, warrant, epoch, revision):
        def change(tx):
            self.governor._epoch(self.governor._load(tx), epoch)
            _, state = self._load(tx, warrant)
            require(state is not None and state['resolution'] is not None, 'OUTCOME_UNKNOWN')
            box = tx.get(RecordKind.OUTBOX, self._key(warrant))
            require(type(revision) is int and revision == box.revision, 'STALE_DELIVERY_REVISION')
            if box.payload['state'] == 'DELIVERED':
                return
            tx.replace(StoredRecord(RecordKind.OUTBOX, box.record_id, box.scope, box.revision + 1,
                       {**box.payload, 'state': 'DELIVERED'}), expected_revision=box.revision)
        return self._run(principal, Capability.COMMIT, change)
