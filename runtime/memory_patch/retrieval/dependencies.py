"""Selected admitted canonical metadata; a digest is never authority.

Ambient retrieval/ranking/registry/bundle hashes remain admission/provenance,
not the selected fact comparison key. Reuse the existing retrieval and capsule;
no store, discovery fallback, authority or effect dispatcher is owned here.
"""
from dataclasses import dataclass,field
from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_json_bytes,canonical_sha256,require_sha256_hex
from runtime.memory_patch.errors import ErrorCode,MemoryPatchError
from runtime.memory_patch.retrieval.contracts import HybridRetrievalRequest
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.mission.contracts import logical_id


def require(value):
    if not value:raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)


@dataclass(frozen=True,slots=True,repr=False)
class SelectedCanonicalSnapshot:
    scope_ref:str
    hat_ref:str
    selected:tuple
    request_ref:str
    bundle_ref:str
    capsule_ref:str
    dependency_digest:str=field(init=False)

    def __post_init__(self):
        self._validate()
        object.__setattr__(self,'dependency_digest',self._digest())

    def _validate(self):
        for value in (self.scope_ref,self.hat_ref,self.request_ref,self.bundle_ref,self.capsule_ref):
            require_sha256_hex(value,'selected context')
        require(type(self.selected) is tuple and 1<=len(self.selected)<=8
            and self.selected==tuple(sorted(set(self.selected))))
        for row in self.selected:
            require(type(row) is tuple and len(row)==5)
            for value in row[:3]:require_sha256_hex(value,'selected fact')
            require(all(type(v) is int and 0<=v<=8192 for v in row[3:]) and row[3]<=row[4])

    def _digest(self):
        return canonical_sha256(('native-selected-canonical-v1',self.scope_ref,self.hat_ref,self.request_ref,self.selected))

    def as_dict(self):
        self._validate()
        require(self.dependency_digest==self._digest())
        value={'schema':'aioa.selected-canonical-context.v1','authority':'NONE',
            'scope_ref':self.scope_ref,'hat_ref':self.hat_ref,'selected_refs':self.selected,
            'request_ref':self.request_ref,'bundle_ref':self.bundle_ref,'capsule_ref':self.capsule_ref,
            'dependency_digest':self.dependency_digest,'semantics':'ADMITTED_FACT_COMPARISON_NOT_AUTHORITY'}
        require(len(canonical_json_bytes(value))<=4096)
        return value


def selected_canonical_snapshot(retrieval,principal,request,lanes,*,selected_refs):
    require(type(retrieval) is NativeRetrieval)
    require(type(selected_refs) is tuple and 1<=len(selected_refs)<=8
        and all(type(row) is tuple and len(row)==2 and row[0]=='CANONICAL_EVIDENCE' for row in selected_refs))
    capsule=retrieval.context_capsule(principal,request,lanes,selected_refs=selected_refs)
    items={item.item_hash:item for item in lanes.canonical_evidence.items}
    rows=[]
    for _,ref in selected_refs:
        item=items[ref];excerpt=item.excerpt
        rows.append((canonical_sha256(item.identity),item.artifact_digest,excerpt.excerpt_sha256,
                     excerpt.start_byte,excerpt.end_byte))
    return SelectedCanonicalSnapshot(capsule.scope_ref,capsule.hat_ref,tuple(sorted(rows)),
        capsule.request_hash,capsule.bundle_hash,capsule.capsule_hash)


@dataclass(frozen=True,slots=True,repr=False)
class CoreSelectedContextReader:
    retrieval:NativeRetrieval
    request:HybridRetrievalRequest
    selected_slots:tuple

    def __post_init__(self):
        require(type(self.retrieval) is NativeRetrieval and type(self.request) is HybridRetrievalRequest)
        require(type(self.selected_slots) is tuple and 1<=len(self.selected_slots)<=8
            and self.selected_slots==tuple(sorted(set(self.selected_slots))))
        for row in self.selected_slots:
            require(type(row) is tuple and len(row)==2)
            for value in row:logical_id(value)

    @property
    def core(self):return self.retrieval.core

    def current(self,principal):
        self.core.require(principal,Capability.READ,scope=self.request.scope)
        lanes=self.retrieval.retrieve(principal,self.request,include_personal=False)
        chosen=[]
        for slot in self.selected_slots:
            matches=[item for item in lanes.temporal.applicable_items
                     if (item.identity.source_id,item.identity.chunk_id)==slot]
            # No newest-version guessing, context expansion or fallback.
            require(len(matches)==1);chosen.append(('CANONICAL_EVIDENCE',matches[0].item_hash))
        return selected_canonical_snapshot(self.retrieval,principal,self.request,lanes,
            selected_refs=tuple(chosen))
