"""Bounded READ projection of native records; hashes never grant authority.

Valid time comes only from an existing event timestamp. Transaction time is the
native local journal timestamp, not a database commit/linearization timestamp.
Missing historical timestamps remain UNKNOWN. This module owns no persistence,
authority, transport, clock, provider or effect executor.
"""
from collections.abc import Mapping
import json

from runtime.memory_patch.audit import decode_audit
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.contracts import logical_id
from runtime.service_guard.contracts import GuardError, ServicePolicy, check_observation


PHASES = ('approval', 'revocation', 'proposal', 'intent', 'receipt', 'verified', 'blocked')
EVENT_TIMES = {'approval': 'approved_at', 'revocation': 'revoked_at', 'receipt': 'dispatched_at'}


def _require(condition):
    if not condition:
        raise GuardError('RECEIPT_GRAPH_INTEGRITY')


def _timestamp(value):
    _require(type(value) is int and 0 <= value <= 2**53)
    return value


def project_receipt_graph(records, audits, *, policy, operation_id):
    """Project one scoped operation's existing records, without authorizing it.

Only the native Core READ surface resolves records. A caller-created graph or
consistent hash is data, not a signature, human approval or effect permission.
"""
    _require(type(policy) is ServicePolicy)
    logical_id(operation_id)
    _require(isinstance(records, Mapping) and isinstance(audits, Mapping))
    _require(set(records) <= set(PHASES) and set(audits) == set(records))
    outcomes, nodes, edges = {}, [], []
    for phase in PHASES:
        if phase not in records:
            continue
        record, audit = records[phase], audits[phase]
        key = canonical_sha256(('nv09-service', policy.scope, operation_id, phase))
        _require(type(record) is StoredRecord and type(audit) is StoredRecord)
        _require(record.kind is RecordKind.OPERATION and audit.kind is RecordKind.AUDIT)
        _require(record.scope == audit.scope == policy.scope and record.revision == audit.revision == 1)
        _require(record.record_id == key and audit.record_id == 'nv09-'+key)
        record.verify(); audit.verify()
        payload = record.payload
        _require(set(payload) == {'operation_kind', 'payload_digest', 'outcome'})
        _require(payload['operation_kind'] == 'nv09-'+phase and isinstance(payload['outcome'], Mapping))
        outcome = json.loads(canonical_json_bytes(payload['outcome']))
        digest = canonical_sha256(outcome)
        _require(digest == payload['payload_digest'])
        a = audit.payload
        required = {'state', 'phase', 'operation_id', 'outcome_digest'}
        if set(a) in (required, required | {'recorded_at'}):
            # Historical receipts remain readable. No legacy row is rewritten
            # or silently adopted into a shared native domain audit chain.
            _require(a['state'] == 'SERVICE_GUARD' and a['phase'] == phase
                     and a['operation_id'] == operation_id and a['outcome_digest'] == digest)
            transaction_time = _timestamp(a['recorded_at']) if 'recorded_at' in a else None
        else:
            try:
                event = decode_audit(audit)
            except (ValueError, TypeError, MemoryPatchError) as error:
                raise GuardError('RECEIPT_GRAPH_INTEGRITY') from error
            _require(event.event_type == 'nv09-'+phase and event.resource_id == key
                     and event.state_after == phase
                     and event.content_hashes.get('content') == digest
                     and event.content_hashes.get('operation') == payload['payload_digest'])
            transaction_time = _timestamp(int(event.created_at.timestamp()))
        event_field = EVENT_TIMES.get(phase)
        event_time = _timestamp(outcome.get(event_field)) if event_field else None
        outcomes[phase] = outcome
        nodes.append({'id': phase, 'content_digest': digest, 'record_digest': record.payload_digest,
            'audit_digest': audit.payload_digest, 'source': 'NATIVE_SERVICE_GUARD_RECORD',
            'valid_time': event_time, 'valid_time_source': event_field,
            'transaction_time': transaction_time,
            'transaction_time_status': 'RECORDED' if transaction_time is not None else 'UNKNOWN_LEGACY',
            'transaction_time_source': 'LEGACY_RECORDED_AT' if set(a) <= required | {'recorded_at'} else 'NATIVE_AUDIT_ORDERING_TIMESTAMP'})

    def bind(parent, child, field, relation):
        _require(parent in outcomes and child in outcomes)
        digest = canonical_sha256(outcomes[parent])
        _require(outcomes[child].get(field) == digest)
        edges.append({'source': parent, 'target': child, 'relation': relation, 'binding_digest': digest})

    if 'revocation' in outcomes:
        bind('approval', 'revocation', 'approval_digest', 'REVOCATION_BINDING')
    if 'intent' in outcomes:
        intent = outcomes['intent']
        _require(intent.get('operation_id') == operation_id and intent.get('scope') == list(policy.scope.binding())
                 and intent.get('target_id') == policy.target_id)
        _require(intent.get('request_digest') == canonical_sha256({k: v for k, v in intent.items() if k != 'request_digest'}))
        bind('approval', 'intent', 'approval_digest', 'APPROVAL_BINDING')
        bind('proposal', 'intent', 'proposal_digest', 'PROPOSAL_BINDING')
    if 'receipt' in outcomes:
        _require('intent' in outcomes)
        intent, receipt = outcomes['intent'], outcomes['receipt']
        _require(all(receipt.get(k) == v for k, v in intent.items()))
        edges.append({'source': 'intent', 'target': 'receipt', 'relation': 'REQUEST_BINDING',
                      'binding_digest': intent['request_digest']})
    if 'verified' in outcomes:
        _require('intent' in outcomes)
        verified = outcomes['verified']
        _require(verified.get('operation_id') == operation_id and verified.get('verified_effect') is True)
        _require(verified.get('request_digest') == outcomes['intent']['request_digest'])
        bind('receipt', 'verified', 'receipt_digest', 'RECEIPT_BINDING')
        try:
            measurement = check_observation(verified.get('measurement'), policy)
        except GuardError as error:
            raise GuardError('RECEIPT_GRAPH_INTEGRITY') from error
        receipt = outcomes['receipt']
        _require(measurement['revision'] == receipt.get('new_revision')
                 and measurement['effect_count'] == receipt.get('effect_count')
                 and measurement['mode'] == receipt.get('mode') == 'MAINTENANCE')
        digest = canonical_sha256(measurement)
        _require(digest == verified.get('measurement_digest'))
        source = next(n for n in nodes if n['id'] == 'verified')
        nodes.append({**source, 'id': 'measurement', 'content_digest': digest,
            'source': 'MEASUREMENT_WITHIN_NATIVE_VERIFIED_RECORD', 'valid_time': None, 'valid_time_source': None})
        edges.extend([
            {'source': 'intent', 'target': 'verified', 'relation': 'REQUEST_BINDING', 'binding_digest': verified['request_digest']},
            {'source': 'receipt', 'target': 'measurement', 'relation': 'READBACK_AFTER_RECEIPT', 'binding_digest': verified['receipt_digest']},
            {'source': 'measurement', 'target': 'verified', 'relation': 'MEASUREMENT_BINDING', 'binding_digest': digest},
        ])
    complete = {'approval', 'proposal', 'intent', 'receipt', 'verified'} <= set(outcomes)
    result = {'schema': 'aioa.service-receipt-graph.v1', 'authority': 'NONE', 'verification': 'PROVENANCE_ONLY',
        'read_only_projection': True, 'scope_ref': canonical_sha256(policy.scope),
        'operation_ref': canonical_sha256((policy.scope, operation_id)),
        'projection_status': 'COMPLETE' if complete else 'PARTIAL',
        'outcome_status': 'VERIFIED_RECORD_PRESENT' if 'verified' in outcomes else 'UNKNOWN' if 'intent' in outcomes else 'NO_EFFECT_EVIDENCE',
        'next_action': 'INSPECT_EXISTING_EVIDENCE' if 'verified' in outcomes else 'RECONCILE_READ_ONLY' if 'intent' in outcomes else 'AWAIT_EXISTING_HUMAN_GATED_PATH',
        'transaction_time_semantics': 'LOCAL_JOURNAL_RECORD_TIMESTAMP_NOT_DB_COMMIT_TIME',
        'nodes': sorted(nodes, key=lambda n: n['id']),
        'edges': sorted(edges, key=lambda e: (e['source'], e['target'], e['relation']))}
    result['graph_digest'] = canonical_sha256(result)
    _require(len(canonical_json_bytes(result)) <= 8192)
    return result
