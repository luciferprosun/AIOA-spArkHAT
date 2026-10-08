"""Immutable FIXTURE expected/readback certificate; owns no effect or state."""
from collections.abc import Mapping
from dataclasses import dataclass,field
import json
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256,freeze_json,require_sha256_hex
from runtime.service_guard.contracts import GuardError,ServicePolicy,check_observation
from runtime.service_guard.receipt_graph import project_receipt_graph


def require(value):
    if not value:raise GuardError('SHADOW_DELTA_INTEGRITY')


@dataclass(frozen=True,slots=True,repr=False)
class ShadowDeltaCertificate:
    payload:object
    certificate_digest:str=field(init=False)

    def __post_init__(self):
        object.__setattr__(self,'payload',freeze_json(self.payload))
        self._validate()
        object.__setattr__(self,'certificate_digest',canonical_sha256(self.payload))
        self.as_dict()

    def _validate(self):
        require(isinstance(self.payload,Mapping) and set(self.payload)=={'schema','mode','authority',
            'execution_authority','status','dependent_completion_blocked','scope_ref','operation_ref','target_ref',
            'expected','observed','discrepancies','receipt_ref','graph_ref','decision_context_before',
            'decision_context_current','readback_ref','next_action','assumptions'})
        require(self.payload.get('schema')=='aioa.shadow-delta-certificate.v1'
            and self.payload.get('mode')=='FIXTURE' and self.payload.get('authority')=='NONE'
            and self.payload.get('execution_authority') is False
            and self.payload.get('status') in ('VERIFIED_FIXTURE_DELTA','UNKNOWN')
            and self.payload.get('dependent_completion_blocked') is (self.payload['status']=='UNKNOWN'))
        for name in ('scope_ref','operation_ref','target_ref','receipt_ref','graph_ref',
                'decision_context_before','decision_context_current','readback_ref'):
            value=self.payload[name]
            require(value is not None or name not in ('scope_ref','operation_ref','target_ref'))
            if value is not None:require_sha256_hex(value,'shadow reference')
        codes={'RECEIPT_EXPECTED_DELTA_MISMATCH','STORED_READBACK_EXPECTED_DELTA_MISMATCH',
            'INDEPENDENT_READBACK_EXPECTED_DELTA_MISMATCH','DECISION_CONTEXT_UNAVAILABLE',
            'SELECTED_EVIDENCE_REVISION_MISMATCH','MISSING_OR_CORRUPT_CAUSAL_READBACK_PROOF'}
        errors=self.payload['discrepancies']
        require(type(errors) is tuple and errors==tuple(sorted(set(errors))) and set(errors)<=codes
            and bool(errors)==(self.payload['status']=='UNKNOWN'))
        for name in ('expected','observed'):
            row=self.payload[name]
            require(row is None or (isinstance(row,Mapping) and set(row)=={'revision','effect_count','mode'}
                and type(row['revision']) is int and 1<=row['revision']<=2**53
                and type(row['effect_count']) is int and 0<=row['effect_count']<row['revision']
                and row['mode'] in ('NORMAL','MAINTENANCE')))
        require(self.payload['next_action']==('RECONCILE_READ_ONLY_NO_REDISPATCH' if errors else 'INSPECT_EXISTING_PROOF'))
        require(self.payload['assumptions']==('EXACT_EXISTING_LOOPBACK_DISPOSABLE_TARGET',
            'NATIVE_JSON_DB_IS_TEST_FIXTURE','HOST_OWNED_NATIVE_SELECTED_CONTEXT_READER',
            'READBACK_AND_DB_NOT_ONE_DISTRIBUTED_SNAPSHOT','NO_PRODUCTION_WARRANT_OR_FORMAL_PROOF_CLAIM'))
        if not errors:
            require(self.payload['expected']==self.payload['observed'] and all(self.payload[name] is not None
                for name in ('receipt_ref','graph_ref','decision_context_before','decision_context_current','readback_ref')))

    def as_dict(self):
        self._validate()
        require(self.certificate_digest==canonical_sha256(self.payload))
        value={**json.loads(canonical_json_bytes(self.payload)),'certificate_digest':self.certificate_digest}
        require(len(canonical_json_bytes(value))<=8192)
        return value


def project_shadow_delta(records,audits,*,policy,operation_id,readback,current_dependency,context_error=False):
    require(type(policy) is ServicePolicy)
    graph=None;outcomes={};errors=[];expected=None;observed=None;receipt_ref=None;before_root=None;now_root=None
    try:
        graph=project_receipt_graph(records,audits,policy=policy,operation_id=operation_id)
        outcomes={name:json.loads(canonical_json_bytes(record.payload['outcome'])) for name,record in records.items()}
        require(graph['projection_status']=='COMPLETE')
        approval=outcomes['approval'];intent=outcomes['intent'];receipt=outcomes['receipt'];verified=outcomes['verified']
        require(approval['scope']==list(policy.scope.binding()) and approval['target_id']==policy.target_id
            and approval['policy_digest']==policy.digest and approval['effect_class']==policy.effect_class
            and approval['policy_decision']=='ALLOW' and approval['max_effects']==1
            and type(approval['approved_revision']) is int and type(approval['before_effect_count']) is int
            and 1<=approval['approved_revision']<2**53 and 0<=approval['before_effect_count']<approval['approved_revision'])
        require(intent['expected_revision']==approval['approved_revision']
            and intent['before_effect_count']==approval['before_effect_count']
            and intent['policy_digest']==policy.digest and intent['effect_class']==policy.effect_class
            and type(receipt['dispatched_at']) is int
            and approval['approved_at']<=receipt['dispatched_at']<approval['expires_at'])
        expected={'revision':approval['approved_revision']+1,'effect_count':approval['before_effect_count']+1,
            'mode':'MAINTENANCE'}
        stored=check_observation(verified['measurement'],policy)
        fresh=check_observation(readback,policy)
        observed={name:fresh[name] for name in ('revision','effect_count','mode')}
        if any(receipt.get('new_revision' if name=='revision' else name)!=value for name,value in expected.items()):
            errors.append('RECEIPT_EXPECTED_DELTA_MISMATCH')
        if any(stored[name]!=value for name,value in expected.items()):errors.append('STORED_READBACK_EXPECTED_DELTA_MISMATCH')
        if observed!=expected:errors.append('INDEPENDENT_READBACK_EXPECTED_DELTA_MISMATCH')
        receipt_ref=canonical_sha256(receipt)
        root=approval.get('decision_context_root')
        if root is not None:require_sha256_hex(root,'decision context')
        before_root=root
        if context_error or current_dependency is None or before_root is None:
            errors.append('DECISION_CONTEXT_UNAVAILABLE')
        else:
            from runtime.memory_patch.retrieval.dependencies import SelectedCanonicalSnapshot
            require(type(current_dependency) is SelectedCanonicalSnapshot)
            current_dependency.as_dict()
            require(current_dependency.scope_ref==canonical_sha256(policy.scope))
            now_root=current_dependency.dependency_digest
            if now_root!=before_root:errors.append('SELECTED_EVIDENCE_REVISION_MISMATCH')
    except Exception:
        # Return only closed discrepancy codes, never exception text/input.
        errors.append('MISSING_OR_CORRUPT_CAUSAL_READBACK_PROOF')
    status='UNKNOWN' if errors else 'VERIFIED_FIXTURE_DELTA'
    value={'schema':'aioa.shadow-delta-certificate.v1','mode':'FIXTURE','authority':'NONE',
        'execution_authority':False,'status':status,'dependent_completion_blocked':bool(errors),
        'scope_ref':canonical_sha256(policy.scope),'operation_ref':canonical_sha256((policy.scope,operation_id)),
        'target_ref':canonical_sha256((policy.scope,policy.target_id)),'expected':expected,'observed':observed,
        'discrepancies':sorted(set(errors)),'receipt_ref':receipt_ref,
        'graph_ref':graph['graph_digest'] if graph else None,
        'decision_context_before':before_root,'decision_context_current':now_root,
        'readback_ref':canonical_sha256(readback) if observed is not None else None,
        'next_action':'INSPECT_EXISTING_PROOF' if not errors else 'RECONCILE_READ_ONLY_NO_REDISPATCH',
        'assumptions':['EXACT_EXISTING_LOOPBACK_DISPOSABLE_TARGET','NATIVE_JSON_DB_IS_TEST_FIXTURE',
            'HOST_OWNED_NATIVE_SELECTED_CONTEXT_READER','READBACK_AND_DB_NOT_ONE_DISTRIBUTED_SNAPSHOT',
            'NO_PRODUCTION_WARRANT_OR_FORMAL_PROOF_CLAIM']}
    return ShadowDeltaCertificate(value)
