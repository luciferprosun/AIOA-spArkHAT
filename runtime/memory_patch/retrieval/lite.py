"""LITE eligibility before relevance, using the existing temporal/evidence path."""

from __future__ import annotations

import json
from dataclasses import replace

from runtime.core_admission import Capability
from runtime.evidence_admission import EvidenceAdmissionError
from runtime.memory_patch.contracts.records import HybridModality
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.personal.contracts import CandidateDraft, stamp
from runtime.memory_patch.retrieval.contracts import (
    FrozenEvidenceBundle,
    HybridRetrievalRequest,
    RetrievalCandidate,
    RetrievalMode,
)
from runtime.memory_patch.retrieval.ranking import (
    RankedCandidateInput,
    assemble_budgeted_items,
    merge_and_rank_candidates,
)
from runtime.memory_patch.retrieval.temporal import TemporalQueryMode, resolve_temporal
from runtime.memory_patch.source_lineage import SourcePublicationState


def _identity_item(request, source, ordinal):
    # Wrap one source at a time in native evidence DTOs. The constant one-item
    # contribution is framing, not query relevance or a comparison of sources.
    source = replace(source, retrieval_mode=RetrievalMode.KEYWORD, retrieval_score=None)
    entry = RankedCandidateInput(
        HybridModality.KEYWORD,
        request.request_hash,
        canonical_sha256({"scoped_scan": source.candidate_hash}),
        1,
        source,
    )
    wrapped = merge_and_rank_candidates(request, (entry,))
    item = assemble_budgeted_items(wrapped, context_budget_bytes=262144).items[0]
    return replace(item, item_ordinal=ordinal)


def retrieve_eligible(service, principal, request, max_records):
    """No query/ranking is passed to scan_scope; a legacy ranked port cannot substitute."""
    from runtime.memory_patch.lite import ContextReference

    core, retrieval = service.core, service.retrieval
    if (
        type(request) is not HybridRetrievalRequest
        or type(max_records) is not int
        or not 1 <= max_records <= 40
        or canonical_sha256(request, exclude_fields=("request_hash",))
        != request.request_hash
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    core.require(principal, Capability.READ, scope=request.scope)
    if request.hat_scope_id not in principal.hat_ids:
        raise MemoryPatchError(ErrorCode.OWNER_DENIED)
    scan = getattr(retrieval.sources, "scan_scope", None)
    if not callable(scan) or not service.transactions.configured:
        raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
    sources = scan(principal, hat_id=request.hat_scope_id, limit=max_records + 1)
    if type(sources) is not tuple or len(sources) > max_records:
        raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
    bindings, items, originals, reasons = [], [], {}, []
    for source in sources:
        if type(source) is not RetrievalCandidate:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        core.require(principal, Capability.READ, scope=source.scope)
        if source.hat_scope_id != request.hat_scope_id:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if source.publication_state is not SourcePublicationState.PUBLISHED:
            reasons.append("SOURCE_NOT_PUBLISHED")
            continue
        item = _identity_item(request, source, len(items) + 1)
        if item.identity.identity_hash in originals:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        originals[item.identity.identity_hash] = source
        items.append(item)
        bindings.append((item.item_hash, source.core_evidence_id))
    scan_bundle = FrozenEvidenceBundle(
        request.scope,
        request.hat_scope_id,
        tuple(items),
        request.request_hash,
        tuple(bindings),
    )
    temporal = resolve_temporal(
        scan_bundle,
        mode=TemporalQueryMode.CURRENT,
        trusted_now=retrieval.clock(),
        freshness=retrieval.freshness,
    )
    eligible_ids = {i.item_hash for i in temporal.applicable_items}
    for state in temporal.states:
        if state.item.item_hash not in eligible_ids:
            reasons.extend(reason.value for reason in state.reasons)
    verified, refs, context = [], [], []
    for item in temporal.applicable_items:
        source = originals[item.identity.identity_hash]
        try:
            retrieval._check_candidate(principal, request, source)
        except (EvidenceAdmissionError, MemoryPatchError):
            reasons.append("EVIDENCE_OR_PROVENANCE_INELIGIBLE")
            continue
        verified.append(item)
        refs.append((item.item_hash, source.core_evidence_id))
        context.append(
            ContextReference(
                source.core_evidence_id,
                "CANONICAL_EVIDENCE",
                item.excerpt.text,
                (source.core_evidence_id,),
                ((source.source_id, source.knowledge_version_id),),
                1,
                str(source.structured_metadata.get("effective_from") or "") or None,
                str(source.structured_metadata.get("effective_to") or "") or None,
            )
        )
    bundle = FrozenEvidenceBundle(
        request.scope,
        request.hat_scope_id,
        tuple(verified),
        request.request_hash,
        tuple(refs),
    )
    retrieval.require_bundle(principal, bundle)
    remaining = max_records - len(sources)
    personal = ()
    if remaining:
        try:
            personal = service.personal.retrieve(
                principal,
                hat_id=request.hat_scope_id,
                at=retrieval.clock(),
                canonical_bundle=bundle,
                limit=remaining,
                max_scan_records=remaining,
            )
        except MemoryPatchError as error:
            if error.code is not ErrorCode.NOT_FOUND:
                raise
            reasons.append("PERSONAL_SPACE_UNCONFIGURED")
    else:
        reasons.append("PERSONAL_READ_BUDGET_EXHAUSTED")
    for value in personal:
        patch = service.lifecycle.read(principal, value.patch_id)
        draft = CandidateDraft.from_private(patch.payload["candidate"])
        versions = []
        for reference in draft.evidence_references:
            record = service.evidence.require_evidence(principal, reference)
            versions.append((record.source.source_id, record.source.source_version_id))
        context.append(
            ContextReference(
                value.patch_id,
                "OWNER_CONTEXT",
                value.content
                if isinstance(value.content, str)
                else json.dumps(dict(value.content), sort_keys=True),
                draft.evidence_references,
                tuple(versions),
                value.revision,
                stamp(draft.valid_from),
                stamp(draft.valid_until),
            )
        )
    core.require(principal, Capability.READ, scope=request.scope)
    return tuple(context), bundle, tuple(sorted(set(reasons)))
