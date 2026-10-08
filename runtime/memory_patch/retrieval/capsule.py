"""Immutable metadata-only minimization of existing admitted retrieval lanes.

No text, authority, clock, store, retrieval engine or effect path is owned here.
Current admission reads reuse the native Core/source/temporal/personal ports.
"""
from dataclasses import dataclass, field, replace
import json

from runtime.core_admission import Capability
from collections.abc import Mapping

from runtime.memory_patch.contracts.records import (
    MAX_BUNDLE_ITEMS, MAX_CONTEXT_BUDGET_BYTES, ModalityContribution,
    verify_bundle_item_hash, verify_contribution_hash,
)
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256, freeze_json, require_sha256_hex
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.personal.retrieval import NativeMemoryRetrieval, OwnerMemoryContext
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle, HybridRetrievalRequest
from runtime.memory_patch.retrieval.temporal import TemporalQueryMode, TemporalSelection, resolve_temporal


def _require(condition, code=ErrorCode.INTEGRITY_FAILED):
    if not condition:
        raise MemoryPatchError(code)


@dataclass(frozen=True, slots=True, repr=False)
class ContextCapsule:
    request_hash: str
    bundle_hash: str
    scope_ref: str
    hat_ref: str
    context_refs: tuple
    byte_budget: int
    schema: str = field(default='aioa.context-capsule.v1', init=False)
    authority: str = field(default='NONE', init=False)
    purpose: str = field(default='ADVISORY_CONTEXT_ONLY', init=False)
    capsule_hash: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, 'context_refs', freeze_json(self.context_refs))
        object.__setattr__(self, 'context_refs', self._validated_refs())
        object.__setattr__(self, 'capsule_hash', canonical_sha256(self, exclude_fields=('capsule_hash',)))
        self._verify_export()

    def _validated_refs(self):
        _require(self.schema == 'aioa.context-capsule.v1'
                 and self.authority == 'NONE' and self.purpose == 'ADVISORY_CONTEXT_ONLY')
        for name in ('request_hash', 'bundle_hash', 'scope_ref', 'hat_ref'):
            require_sha256_hex(getattr(self, name), name)
        _require(type(self.byte_budget) is int and 1 <= self.byte_budget <= MAX_CONTEXT_BUDGET_BYTES)
        _require(type(self.context_refs) is tuple and len(self.context_refs) <= MAX_BUNDLE_ITEMS)
        keys = {'lane', 'binding_ref', 'reference_ref', 'source_binding_ref', 'canonical_evidence'}
        seen = set()
        for ref in self.context_refs:
            _require(isinstance(ref, Mapping) and set(ref) == keys)
            _require(ref['lane'] in ('CANONICAL_EVIDENCE', 'OWNER_CONTEXT'))
            _require(ref['canonical_evidence'] is (ref['lane'] == 'CANONICAL_EVIDENCE'))
            for name in ('binding_ref', 'reference_ref', 'source_binding_ref'):
                require_sha256_hex(ref[name], name)
            identity = (ref['lane'], ref['binding_ref'])
            _require(identity not in seen)
            seen.add(identity)
        return tuple(sorted(self.context_refs, key=lambda ref: (ref['lane'], ref['binding_ref'])))

    def _verify_export(self):
        _require(self.context_refs == self._validated_refs())
        require_sha256_hex(self.capsule_hash, 'capsule_hash')
        _require(self.capsule_hash == canonical_sha256(self, exclude_fields=('capsule_hash',)))
        _require(len(canonical_json_bytes(self)) <= self.byte_budget, ErrorCode.QUOTA_EXCEEDED)

    def as_dict(self):
        self._verify_export()
        return json.loads(canonical_json_bytes(self))


def project_context_capsule(retrieval, principal, request, lanes, *, selected_refs=None):
    """Validate existing inputs and project only their selected references.

Availability after admission never adds a reference. No candidates()/ranking or
context fetch fallback occurs. Hashes and construction never confer admission.
"""
    from runtime.memory_patch.retrieval.service import RetrievalLanes

    _require(type(request) is HybridRetrievalRequest and type(lanes) is RetrievalLanes)
    retrieval.core.require(principal, Capability.READ, scope=request.scope)
    _require(request.hat_scope_id in principal.hat_ids, ErrorCode.OWNER_DENIED)
    _require(request == replace(request))
    _require(request.request_hash == canonical_sha256(request, exclude_fields=('request_hash',)))
    bundle, temporal = lanes.canonical_evidence, lanes.temporal
    _require(type(bundle) is FrozenEvidenceBundle and type(temporal) is TemporalSelection)
    _require(bundle.scope == request.scope and bundle.hat_scope_id == request.hat_scope_id, ErrorCode.OWNER_DENIED)
    _require(bundle.request_hash == request.request_hash)
    _require(bundle.bundle_hash == canonical_sha256(bundle, exclude_fields=('bundle_hash',)))
    _require(type(bundle.items) is tuple and len(bundle.items) <= request.limit)
    _require(type(bundle.core_evidence_bindings) is tuple
             and len(bundle.core_evidence_bindings) == len(bundle.items)
             and {k for k, _ in bundle.core_evidence_bindings} == {i.item_hash for i in bundle.items})
    for item in bundle.items:
        verify_bundle_item_hash(item)
        _require(type(item.contributions) is tuple and bool(item.contributions)
                 and all(type(c) is ModalityContribution for c in item.contributions))
        for contribution in item.contributions:
            verify_contribution_hash(contribution)
            _require(contribution.upstream_request_hash == request.request_hash)
        _require(item.effective_scope == request.effective_scope
                 and item.identity.hat_scope_id == request.hat_scope_id, ErrorCode.OWNER_DENIED)
    retrieval.require_bundle(principal, bundle)
    now = retrieval.clock()
    _require(temporal.mode is TemporalQueryMode.CURRENT and temporal.as_of <= now)
    admitted = resolve_temporal(bundle, mode=TemporalQueryMode.CURRENT,
                                trusted_now=temporal.as_of, freshness=retrieval.freshness)
    _require(canonical_sha256(admitted) == canonical_sha256(temporal))
    current = resolve_temporal(bundle, mode=TemporalQueryMode.CURRENT,
                               trusted_now=now, freshness=retrieval.freshness)
    _require({i.item_hash for i in admitted.applicable_items}
             <= {i.item_hash for i in current.applicable_items})
    pool = {}
    for item in admitted.applicable_items:
        pool[('CANONICAL_EVIDENCE', item.item_hash)] = {
            'lane': 'CANONICAL_EVIDENCE', 'binding_ref': item.item_hash,
            'reference_ref': canonical_sha256(dict(bundle.core_evidence_bindings)[item.item_hash]),
            'source_binding_ref': canonical_sha256((item.identity, item.registry_digest, item.snapshot_id)),
            'canonical_evidence': True}
    _require(type(lanes.personal_context) is tuple and len(lanes.personal_context) <= 128)
    if lanes.personal_context:
        _require(type(retrieval.personal) is NativeMemoryRetrieval
                 and retrieval.personal.lifecycle.core is retrieval.core, ErrorCode.BACKEND_UNCONFIGURED)
        current_personal = retrieval.personal.retrieve(principal, hat_id=request.hat_scope_id,
            at=now, canonical_bundle=bundle, limit=128)
        seen = set()
        for value in lanes.personal_context:
            _require(type(value) is OwnerMemoryContext and value in current_personal)
            _require(value.canonical_evidence is False and value.execution_authority is False)
            _require(value.patch_id not in seen)
            seen.add(value.patch_id)
            pool[('OWNER_CONTEXT', value.patch_id)] = {
                'lane': 'OWNER_CONTEXT', 'binding_ref': canonical_sha256(value),
                'reference_ref': canonical_sha256(value.patch_id),
                'source_binding_ref': canonical_sha256((bundle.bundle_hash, value.patch_id, value.revision)),
                'canonical_evidence': False}
    keys = tuple(sorted(pool)) if selected_refs is None else selected_refs
    _require(type(keys) is tuple and all(type(k) is tuple and len(k) == 2
             and all(type(x) is str for x in k) for k in keys), ErrorCode.INVALID_REQUEST)
    _require(len(keys) == len(set(keys)) and all(k in pool for k in keys))
    _require(len(keys) <= request.limit, ErrorCode.QUOTA_EXCEEDED)
    retrieval.core.require(principal, Capability.READ, scope=request.scope)
    return ContextCapsule(request.request_hash, bundle.bundle_hash, canonical_sha256(request.scope),
                          canonical_sha256(request.hat_scope_id),
                          tuple(pool[k] for k in sorted(keys)), request.context_budget_bytes)
