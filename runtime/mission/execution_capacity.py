"""Finite retained capacity data and equations; no host I/O or live authority."""
import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal

from lab.archaioa.authority import AuthorityScope, Money, RiskLevel
from lab.archaioa.decision_root import DecisionDependencyRoot
from lab.archaioa.evidence import EvidenceRef
from lab.archaioa.warrant import EffectWarrant, RevisionPolicy
from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.mission.warrant import approval_digest

MAX_AMOUNT = 2**63 - 1
REVIEW_SCHEMA = 'aioa.governor.execution-capacity-review.v1'
TRANSITION_SCHEMA = 'aioa.governor.execution-capacity-transition.v1'
CAPACITY_SCHEMA = 'aioa.governor.execution-capacity.v1'
QUIESCENCE_SCHEMA = 'aioa.native-quiescence.v1'
CORE_VIEW_SCHEMA = 'aioa.native-capacity-core-view.v1'
ROLES = ('LEGACY_MISSION', 'NATIVE_GITHUB', 'CODING_WORKER', 'CODING_HTTP_EFFECT',
         'SANDBOX_BROKER', 'LOCAL_GIT_EFFECT', 'PORTABLE_EFFECT')
PROPOSAL_FIELDS = {'risk_limits', 'sandbox_exec_failure_threshold'}
RISK_FIELDS = {'task_limit', 'owner_provider_limit', 'global_limit'}
REVIEW_FIELDS = {'schema', 'request_id', 'scope', 'deployment_id', 'bootstrap_policy_digest',
    'expected_version', 'expected_epoch', 'expected_state_digest', 'expected_exposure_digest',
    'prior_effective_capacity', 'proposed_capacity', 'host_source_sha', 'host_source_capsule_digest',
    'composition_digest', 'native_admission_revision', 'native_admission_digest', 'admission_generation',
    'composition_generation', 'actor_session_id', 'assignment_revision', 'quiescence',
    'issued_at', 'expires_at', 'review_digest'}
QUIESCENCE_FIELDS = {'schema', 'instance_id', 'admission_generation', 'composition_generation',
    'fence_sequence', 'work_generation', 'role_coverage', 'owned_work_ids', 'quarantined_work_ids',
    'core_view_digest'}
CORE_VIEW_FIELDS = {'schema', 'governor_version', 'governor_epoch', 'governor_state_digest',
    'governor_exposure_digest', 'native_admission_record_digest', 'live_job_ids',
    'unresolved_reservation_ids', 'unresolved_intent_ids', 'unresolved_liability_ids', 'in_flight_target_ids'}


class CapacityError(MemoryPatchError, ValueError):
    def __init__(self, reason='EXECUTION_CAPACITY_DENIED'):
        super().__init__(ErrorCode.INTEGRITY_FAILED)
        self.args = (reason,)


class CapacityAcknowledgedButFenced(CapacityError):
    """A committed management fact requires fresh canonical READ only."""


def require(value, reason='EXECUTION_CAPACITY_INTEGRITY'):
    if not value:
        raise CapacityError(reason)


def exact(value, fields):
    require(type(value) is dict and set(value) == fields)
    return value


def integer(value, low=0, high=MAX_AMOUNT):
    require(type(value) is int and low <= value <= high)
    return value


def hexdigest(value, length=64):
    require(type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None)
    return value


def plain(value):
    return json.loads(canonical_json_bytes(value))


def same_json(actual, expected):
    return canonical_json_bytes(actual) == canonical_json_bytes(expected)


def strict_json(raw, *, maximum=32768):
    require(type(raw) is bytes and len(raw) <= maximum)
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'DUPLICATE_CAPACITY_FIELD')
            value[key] = item
        return value
    def constant(_):
        raise CapacityError('NONFINITE_CAPACITY_VALUE')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise CapacityError() from error


def utc(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', value) is not None)
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise CapacityError() from error
    require(stamp.strftime('%Y-%m-%dT%H:%M:%S.%fZ') == value)
    return stamp


def timestamp(value):
    require(type(value) is datetime and value.tzinfo is UTC)
    return value.isoformat(timespec='microseconds').replace('+00:00', 'Z')


def proposal(value):
    exact(value, PROPOSAL_FIELDS)
    exact(value['risk_limits'], RISK_FIELDS)
    for amount in value['risk_limits'].values():
        integer(amount)
    integer(value['sandbox_exec_failure_threshold'], 1, 86400)
    return plain(value)


def quiescence(value):
    exact(value, QUIESCENCE_FIELDS)
    require(value['schema'] == QUIESCENCE_SCHEMA)
    hexdigest(value['instance_id'])
    for name in ('admission_generation', 'composition_generation', 'fence_sequence'):
        integer(value[name], 1)
    integer(value['work_generation'])
    hexdigest(value['core_view_digest'])
    require(value['owned_work_ids'] == [] and type(value['owned_work_ids']) is list
            and value['quarantined_work_ids'] == [] and type(value['quarantined_work_ids']) is list)
    require(type(value['role_coverage']) is list and len(value['role_coverage']) == len(ROLES))
    for role, row in zip(ROLES, value['role_coverage'], strict=True):
        exact(row, {'role', 'state'})
        require(row['role'] == role and row['state'] in ('BOUND_IDLE', 'ABSENT_FENCED'))
    return plain(value)


def core_view(value):
    exact(value, CORE_VIEW_FIELDS)
    require(value['schema'] == CORE_VIEW_SCHEMA)
    integer(value['governor_version'], 0, 1023); integer(value['governor_epoch'])
    for name in ('governor_state_digest', 'governor_exposure_digest', 'native_admission_record_digest'):
        hexdigest(value[name])
    for name in ('live_job_ids', 'unresolved_reservation_ids', 'unresolved_intent_ids',
                 'unresolved_liability_ids', 'in_flight_target_ids'):
        values = value[name]
        require(type(values) is list and len(values) <= 1023 and values == sorted(set(values))
                and all(type(item) is str and 0 < len(item) <= 256 for item in values))
    return plain(value)


def empty_core_view(review):
    return {'schema': CORE_VIEW_SCHEMA, 'governor_version': review['expected_version'],
        'governor_epoch': review['expected_epoch'], 'governor_state_digest': review['expected_state_digest'],
        'governor_exposure_digest': review['expected_exposure_digest'],
        'native_admission_record_digest': review['native_admission_digest'], 'live_job_ids': [],
        'unresolved_reservation_ids': [], 'unresolved_intent_ids': [], 'unresolved_liability_ids': [],
        'in_flight_target_ids': []}


@dataclass(frozen=True, slots=True, repr=False)
class ExecutionCapacityReview:
    _bytes: bytes

    def __post_init__(self):
        value = strict_json(self._bytes, maximum=16384)
        exact(value, REVIEW_FIELDS)
        require(value['schema'] == REVIEW_SCHEMA)
        hexdigest(value['request_id'], 32); hexdigest(value['host_source_sha'], 40)
        require(type(value['scope']) is list and len(value['scope']) == 4
                and all(type(item) is str for item in value['scope']))
        OwnerScope(*value['scope'])
        require(type(value['deployment_id']) is str and 1 <= len(value['deployment_id']) <= 180)
        for name in ('bootstrap_policy_digest', 'expected_state_digest', 'expected_exposure_digest',
                     'host_source_capsule_digest', 'composition_digest', 'native_admission_digest',
                     'actor_session_id', 'review_digest'):
            hexdigest(value[name])
        integer(value['expected_version'], 1, 1022); integer(value['expected_epoch'], 1)
        for name in ('native_admission_revision', 'admission_generation', 'composition_generation', 'assignment_revision'):
            integer(value[name], 1)
        proposal(value['prior_effective_capacity']); proposal(value['proposed_capacity'])
        q = quiescence(value['quiescence'])
        require(q['instance_id'] == value['actor_session_id']
                and q['admission_generation'] == value['admission_generation']
                and q['composition_generation'] == value['composition_generation']
                and q['core_view_digest'] == canonical_sha256(empty_core_view(value)))
        issued, expires = utc(value['issued_at']), utc(value['expires_at'])
        require(0 < (expires - issued).total_seconds() <= 300)
        require(value['review_digest'] == canonical_sha256({k:v for k,v in value.items() if k != 'review_digest'}))
        require(canonical_json_bytes(value) == self._bytes)

    @classmethod
    def from_dict(cls, value):
        return cls(canonical_json_bytes(exact(value, REVIEW_FIELDS)))

    def to_dict(self):
        return strict_json(self._bytes, maximum=16384)


@dataclass(frozen=True, slots=True)
class CapacityTransitionReceipt:
    status: str
    version: int
    epoch: int
    review_digest: str
    warrant_digest: str
    consumption: dict

    def to_dict(self):
        return plain({'status': self.status, 'version': self.version, 'epoch': self.epoch,
            'review_digest': self.review_digest, 'warrant_digest': self.warrant_digest,
            'consumption': self.consumption, 'authority': 'NONE', 'automatic_retry': False})


def capacity_warrant(review):
    require(type(review) is ExecutionCapacityReview)
    r = review.to_dict(); scope = OwnerScope(*r['scope'])
    owner = canonical_sha256(scope)
    target = 'sha256:' + canonical_sha256((scope, r['deployment_id'], r['bootstrap_policy_digest']))
    task = 'native-policy-' + r['request_id']
    issued, expires = utc(r['issued_at']), utc(r['expires_at'])
    refs = (
        EvidenceRef('capacity-review', 'governor-capacity-review', 'sha256:' + r['review_digest'], 'v1'),
        EvidenceRef('capacity-state', 'governor-state', 'sha256:' + r['expected_state_digest'], str(r['expected_version'])),
        EvidenceRef('capacity-exposure', 'governor-exposure', 'sha256:' + r['expected_exposure_digest'], str(r['expected_version'])),
        EvidenceRef('native-source', 'host-source', 'sha256:' + r['host_source_capsule_digest'], r['host_source_sha']),
        EvidenceRef('native-composition', 'host-config', 'sha256:' + r['composition_digest'], 'v1'),
        EvidenceRef('native-quiescence', 'host-quiescence', 'sha256:' + canonical_sha256(r['quiescence']), 'v1'))
    warrant = EffectWarrant(warrant_id='warrant-native-capacity-' + r['request_id'], task_id=task,
        owner_scope=owner, operation_class='GOVERNOR_EXECUTION_CAPACITY_V1',
        operation_hash='sha256:' + r['review_digest'], target_fingerprint=target,
        expected_target_revision='governor-' + str(r['expected_version']), revision_policy=RevisionPolicy.REQUIRE,
        decision_dependency_root=DecisionDependencyRoot(refs), lease_epoch=r['expected_epoch'],
        authority_scope=AuthorityScope(('GOVERNOR_EXECUTION_CAPACITY_V1',), target, RiskLevel.LOW,
            Money(Decimal(0), 'USD'), issued, expires, owner, task),
        approval_digest='sha256:' + '0' * 64, money_reservation_id='NONE', risk_reservation_id='NONE',
        nonce='native-capacity-' + r['request_id'], issued_at=issued, expires_at=expires)
    return replace(warrant, approval_digest=approval_digest(warrant))


def consumption(warrant):
    return {'kind': 'WARRANT_CONSUMPTION_ONLY', 'warrant_digest': warrant.digest(),
            'grants_replay': False, 'effect_verified': False}


def override(review, warrant, receipt):
    r = review.to_dict()
    require(same_json(receipt, consumption(warrant)))
    return {'schema': CAPACITY_SCHEMA, 'capacity': r['proposed_capacity'], 'request_id': r['request_id'],
        'review_digest': r['review_digest'], 'warrant_digest': warrant.digest(),
        'consumption_digest': canonical_sha256(receipt)}


def validate_override(value):
    exact(value, {'schema', 'capacity', 'request_id', 'review_digest', 'warrant_digest', 'consumption_digest'})
    require(value['schema'] == CAPACITY_SCHEMA)
    proposal(value['capacity']); hexdigest(value['request_id'], 32)
    hexdigest(value['review_digest']); hexdigest(value['consumption_digest'])
    require(type(value['warrant_digest']) is str and value['warrant_digest'].startswith('sha256:'))
    hexdigest(value['warrant_digest'][7:])


def snapshot(row):
    require(type(row) is StoredRecord)
    row.verify()
    return {'kind': row.kind.value, 'record_id': row.record_id, 'scope': list(row.scope.binding()),
            'revision': row.revision, 'payload': plain(row.payload), 'payload_digest': row.payload_digest}


def decode_snapshot(value, kind, key, scope):
    exact(value, {'kind', 'record_id', 'scope', 'revision', 'payload', 'payload_digest'})
    require(value['kind'] == kind.value and value['record_id'] == key and value['scope'] == list(scope.binding()))
    hexdigest(value['payload_digest'])
    row = StoredRecord(kind, key, scope, integer(value['revision'], 1), value['payload'])
    row.verify(); require(row.payload_digest == value['payload_digest'])
    return row


def validate_transition(before, after, transition, *, scope, deployment_id, policy_digest,
                        prior_capacity, exposure_digest, current_operation, current_witness):
    """Historical consent is checked from retained causal facts, without clocks/captures."""
    require(len(canonical_json_bytes(transition)) <= 32768)
    exact(transition, {'schema', 'review', 'warrant', 'applied_at', 'approval_at_apply', 'consumption'})
    require(transition['schema'] == TRANSITION_SCHEMA)
    review = ExecutionCapacityReview.from_dict(plain(transition['review']))
    r = review.to_dict(); warrant = capacity_warrant(review)
    require(same_json(transition['warrant'], warrant.to_dict()))
    applied = utc(transition['applied_at'])
    require(utc(r['issued_at']) <= applied < utc(r['expires_at'])
            and warrant.issued_at <= applied < warrant.expires_at)
    require(r['scope'] == list(scope.binding()) and r['deployment_id'] == deployment_id
            and r['bootstrap_policy_digest'] == policy_digest
            and r['expected_version'] == before['version'] and r['expected_epoch'] == before['epoch']
            and r['expected_state_digest'] == canonical_sha256(before)
            and r['expected_exposure_digest'] == exposure_digest
            and r['prior_effective_capacity'] == prior_capacity)
    key = canonical_sha256(('aioa-linear-warrant-v1', scope, warrant.nonce))
    evidence = exact(plain(transition['approval_at_apply']),
                     {'owner_witness', 'warrant_state_before', 'warrant_state_after_digest'})
    witness = decode_snapshot(evidence['owner_witness'], RecordKind.APPROVAL, key, scope)
    prior = decode_snapshot(evidence['warrant_state_before'], RecordKind.OPERATION, key, scope)
    witness_payload = {'schema': 'aioa.warrant-owner-witness.v1', 'warrant_digest': warrant.digest(),
        'session_id': r['actor_session_id'], 'assignment_revision': r['assignment_revision'], 'revoked': False}
    require(same_json(witness.payload, witness_payload) and witness.revision == 1)
    prior_payload = {'schema': 'aioa-linear-warrant-v1', 'root': warrant.to_dict(),
                     'active': warrant.to_dict(), 'consumption': None}
    require(same_json(prior.payload, prior_payload) and prior.revision == 1)
    receipt = consumption(warrant)
    require(same_json(transition['consumption'], receipt))
    post = StoredRecord(RecordKind.OPERATION, key, scope, prior.revision + 1,
                        {**prior_payload, 'consumption': receipt})
    require(post.payload_digest == evidence['warrant_state_after_digest'])
    require(type(current_operation) is StoredRecord and type(current_witness) is StoredRecord)
    current_operation.verify(); current_witness.verify()
    require(current_operation.payload_digest == post.payload_digest and current_operation.kind is post.kind
            and current_operation.record_id == key and current_operation.scope == scope
            and current_operation.revision == post.revision)
    current = plain(current_witness.payload)
    require(type(current.get('revoked')) is bool and current_witness.kind is RecordKind.APPROVAL
            and current_witness.record_id == key and current_witness.scope == scope
            and current_witness.revision >= witness.revision
            and same_json(current, {**witness_payload, 'revoked': current['revoked']})
            and (current_witness.payload_digest == witness.payload_digest
                 if current_witness.revision == witness.revision else current['revoked'] is True))
    expected = plain(before)
    now = int(applied.timestamp())
    require(before['last_now'] is None or now >= before['last_now'], 'CLOCK_UNSAFE')
    expected.update(version=before['version'] + 1, epoch=before['epoch'] + 1,
                    last_now=now, execution_capacity=override(review, warrant, receipt))
    require(same_json(after, expected))
    return review, warrant
