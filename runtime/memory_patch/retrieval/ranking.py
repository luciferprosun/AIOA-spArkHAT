"""Reviewed pure domain semantics with native, inert dependencies."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from runtime.memory_patch.contracts.enums import MemoryTargetScope
from runtime.memory_patch.contracts.records import (
    MAX_BUNDLE_ITEMS,
    MAX_CONTEXT_BUDGET_BYTES,
    MAX_EXACT_PRIORITY_ITEMS,
    MAX_EXCERPT_BYTES_PER_ITEM,
    MAX_ITEMS_PER_KNOWLEDGE_VERSION,
    MAX_ITEMS_PER_SOURCE,
    MAX_MERGED_CANDIDATES,
    MAX_UPSTREAM_RESULTS_PER_MODALITY,
    MIN_PARTIAL_EXCERPT_BYTES,
    RRF_K,
    RRF_SCALE,
    CandidateIdentity,
    EvidenceBundleItem,
    EvidenceExcerpt,
    HybridCandidate,
    HybridModality,
    ModalityContribution,
    Step20BoundaryError,
    Step20ReasonCode,
    citation_reference_for,
    evidence_id_for,
    load_ranking_policy,
    modality_order,
    modality_weight,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.retrieval.contracts import (
    HybridRetrievalRequest,
    RetrievalCandidate,
    RetrievalMode,
    VectorRetrievalCandidate,
)
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)

UpstreamCandidate = RetrievalCandidate | VectorRetrievalCandidate
_RETRIEVAL_MODALITY = {
    RetrievalMode.EXACT_IDENTIFIER: HybridModality.EXACT_IDENTIFIER,
    RetrievalMode.STATUTE_SECTION: HybridModality.STATUTE_SECTION,
    RetrievalMode.FULL_TEXT: HybridModality.FULL_TEXT,
    RetrievalMode.KEYWORD: HybridModality.KEYWORD,
}


@dataclass(frozen=True, slots=True)
class RankedCandidateInput:
    modality: HybridModality
    upstream_request_hash: str
    upstream_result_hash: str
    one_based_rank: int
    candidate: UpstreamCandidate


@dataclass(slots=True)
class _Accumulator:
    candidate: UpstreamCandidate
    semantic_fingerprint: str
    contributions: dict[HybridModality, ModalityContribution]
    vector_model_digest: str | None
    vector_embedding_bytes_sha256: str | None


def modality_for_retrieval_mode(value: RetrievalMode) -> HybridModality:
    try:
        return _RETRIEVAL_MODALITY[value]
    except KeyError as exc:
        raise Step20BoundaryError(
            Step20ReasonCode.HYBRID_INPUT_BINDING_MISMATCH
        ) from exc


def _identity(candidate: UpstreamCandidate) -> CandidateIdentity:
    return CandidateIdentity(
        tenant_id=candidate.tenant_id,
        hat_scope_id=candidate.hat_scope_id,
        source_id=candidate.source_id,
        knowledge_version_id=candidate.knowledge_version_id,
        chunk_id=candidate.chunk_id,
        content_sha256=candidate.content_sha256,
    )


def _common_semantics(candidate: UpstreamCandidate) -> dict[str, Any]:
    return {
        "tenant_id": candidate.tenant_id,
        "hat_scope_id": candidate.hat_scope_id,
        "source_id": candidate.source_id,
        "knowledge_version_id": candidate.knowledge_version_id,
        "chunk_id": candidate.chunk_id,
        "chunk_ordinal": candidate.chunk_ordinal,
        "content_sha256": candidate.content_sha256,
        "content": candidate.content,
        "language_tag": candidate.language_tag,
        "authority_level": candidate.authority_level,
        "authority_basis": candidate.authority_basis,
        "source_kind": candidate.source_kind,
        "source_reference": candidate.source_reference,
        "publication_state": candidate.publication_state,
        "access_class": candidate.access_class,
        "target_scope": candidate.target_scope,
        "owner_user_id": candidate.owner_user_id,
        "personal_memory_space_id": candidate.personal_memory_space_id,
        "scope_digest": candidate.scope_digest,
        "registry_digest": candidate.registry_digest,
        "artifact_digest": candidate.artifact_digest,
        "snapshot_id": candidate.snapshot_id,
        "structured_metadata": candidate.structured_metadata,
        "effective_scope": candidate.effective_scope,
    }


def _validate_eligibility(
    request: HybridRetrievalRequest,
    candidate: UpstreamCandidate,
    modality: HybridModality,
) -> None:
    if candidate.tenant_id != request.tenant_id:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    if candidate.hat_scope_id != request.hat_scope_id:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    if candidate.effective_scope != request.effective_scope:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_SCOPE_MISMATCH)
    if candidate.publication_state is not SourcePublicationState.PUBLISHED:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    if candidate.authority_level not in {
        SourceAuthorityLevel.OFFICIAL_PRIMARY,
        SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    }:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    expected_target = (
        MemoryTargetScope.USER_PERSONAL_HAT
        if request.personal_memory_space_id is not None
        else MemoryTargetScope.SHARED_KNOWLEDGE_HAT
    )
    if candidate.target_scope is not expected_target:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    if candidate.access_class is SourceAccessClass.USER_PRIVATE:
        if (
            candidate.owner_user_id != request.user_id
            or candidate.personal_memory_space_id != request.personal_memory_space_id
        ):
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    elif (
        candidate.owner_user_id is not None
        or candidate.personal_memory_space_id is not None
    ):
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
    if modality is HybridModality.VECTOR:
        if not isinstance(candidate, VectorRetrievalCandidate):
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_INPUT_BINDING_MISMATCH)
        if candidate.model_digest != request.embedding_model_digest:
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_MODEL_MISMATCH)
    elif not isinstance(candidate, RetrievalCandidate):
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_INPUT_BINDING_MISMATCH)
    elif modality_for_retrieval_mode(candidate.retrieval_mode) is not modality:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_INPUT_BINDING_MISMATCH)


def _contribution(value: RankedCandidateInput) -> ModalityContribution:
    local_value = (
        value.candidate.vector_distance
        if isinstance(value.candidate, VectorRetrievalCandidate)
        else value.candidate.retrieval_score
    )
    return ModalityContribution(
        modality=value.modality,
        upstream_request_hash=value.upstream_request_hash,
        upstream_result_hash=value.upstream_result_hash,
        upstream_candidate_hash=value.candidate.candidate_hash,
        one_based_rank=value.one_based_rank,
        retrieval_local_value=local_value,
        fixed_point_contribution=RRF_SCALE
        * modality_weight(value.modality)
        // (RRF_K + value.one_based_rank),
    )


def _match_class(contributions: tuple[ModalityContribution, ...]) -> int:
    modalities = {item.modality for item in contributions}
    if HybridModality.STATUTE_SECTION in modalities:
        return 0
    if HybridModality.EXACT_IDENTIFIER in modalities:
        return 1
    if len(modalities) >= 2:
        return 2
    if modalities & {HybridModality.FULL_TEXT, HybridModality.KEYWORD}:
        return 3
    return 4


def _reason_codes(
    contributions: tuple[ModalityContribution, ...], match_class: int
) -> tuple[Step20ReasonCode, ...]:
    reasons: list[Step20ReasonCode] = []
    if len(contributions) > 1:
        reasons.append(Step20ReasonCode.HYBRID_DUPLICATE_MERGED)
    if match_class in {0, 1}:
        reasons.append(Step20ReasonCode.HYBRID_EXACT_PRIORITY)
    elif match_class == 2:
        reasons.append(Step20ReasonCode.HYBRID_MULTI_MODAL_SUPPORT)
    elif match_class == 4:
        reasons.append(Step20ReasonCode.HYBRID_VECTOR_ONLY)
    reasons.append(Step20ReasonCode.HYBRID_RANKED)
    return tuple(reasons)


def candidate_rank_key(candidate: HybridCandidate) -> tuple[object, ...]:
    ranks = {item.modality: item.one_based_rank for item in candidate.contributions}
    sentinel = MAX_UPSTREAM_RESULTS_PER_MODALITY + 1
    return (
        candidate.match_class,
        -candidate.fused_score,
        -candidate.modality_count,
        ranks.get(
            HybridModality.STATUTE_SECTION,
            ranks.get(HybridModality.EXACT_IDENTIFIER, sentinel),
        ),
        ranks.get(HybridModality.FULL_TEXT, sentinel),
        ranks.get(HybridModality.VECTOR, sentinel),
        candidate.identity.source_id,
        candidate.identity.knowledge_version_id,
        candidate.chunk_ordinal,
        candidate.identity.chunk_id,
        candidate.identity.content_sha256,
    )


def merge_and_rank_candidates(
    request: HybridRetrievalRequest, inputs: tuple[RankedCandidateInput, ...]
) -> tuple[HybridCandidate, ...]:
    """Revalidate, deduplicate, fuse, and rank verified upstream candidates."""
    if len(inputs) > MAX_MERGED_CANDIDATES:
        raise Step20BoundaryError(Step20ReasonCode.HYBRID_INPUT_REQUIRED)
    accumulators: dict[str, _Accumulator] = {}
    for value in sorted(
        inputs,
        key=lambda item: (
            modality_order(item.modality),
            item.upstream_result_hash,
            item.one_based_rank,
            item.candidate.candidate_hash,
        ),
    ):
        _validate_eligibility(request, value.candidate, value.modality)
        identity = _identity(value.candidate)
        fingerprint = canonical_sha256(_common_semantics(value.candidate))
        contribution = _contribution(value)
        existing = accumulators.get(identity.identity_hash)
        if existing is None:
            vector_model = (
                value.candidate.model_digest
                if isinstance(value.candidate, VectorRetrievalCandidate)
                else None
            )
            embedding_hash = (
                value.candidate.embedding_bytes_sha256
                if isinstance(value.candidate, VectorRetrievalCandidate)
                else None
            )
            accumulators[identity.identity_hash] = _Accumulator(
                candidate=value.candidate,
                semantic_fingerprint=fingerprint,
                contributions={value.modality: contribution},
                vector_model_digest=vector_model,
                vector_embedding_bytes_sha256=embedding_hash,
            )
            continue
        if existing.semantic_fingerprint != fingerprint:
            raise Step20BoundaryError(
                Step20ReasonCode.HYBRID_CANDIDATE_METADATA_CONFLICT
            )
        prior = existing.contributions.get(value.modality)
        if prior is not None:
            if prior.contribution_hash == contribution.contribution_hash:
                continue
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_INPUT_BINDING_MISMATCH)
        existing.contributions[value.modality] = contribution
        if isinstance(value.candidate, VectorRetrievalCandidate):
            vector_identity = (
                value.candidate.model_digest,
                value.candidate.embedding_bytes_sha256,
            )
            existing_identity = (
                existing.vector_model_digest,
                existing.vector_embedding_bytes_sha256,
            )
            if (
                existing.vector_model_digest is not None
                and existing_identity != vector_identity
            ):
                raise Step20BoundaryError(
                    Step20ReasonCode.HYBRID_CANDIDATE_METADATA_CONFLICT
                )
            existing.vector_model_digest, existing.vector_embedding_bytes_sha256 = (
                vector_identity
            )
    merged: list[HybridCandidate] = []
    for identity_hash in sorted(accumulators):
        accumulator = accumulators[identity_hash]
        source = accumulator.candidate
        identity = _identity(source)
        contributions = tuple(
            sorted(
                accumulator.contributions.values(),
                key=lambda item: modality_order(item.modality),
            )
        )
        match_class = _match_class(contributions)
        merged.append(
            HybridCandidate(
                identity=identity,
                chunk_ordinal=source.chunk_ordinal,
                content=source.content,
                language_tag=source.language_tag,
                authority_level=source.authority_level,
                authority_basis=source.authority_basis,
                source_kind=source.source_kind,
                source_reference=source.source_reference,
                publication_state=source.publication_state,
                access_class=source.access_class,
                target_scope=source.target_scope,
                owner_user_id=source.owner_user_id,
                personal_memory_space_id=source.personal_memory_space_id,
                scope_digest=source.scope_digest,
                registry_digest=source.registry_digest,
                artifact_digest=source.artifact_digest,
                snapshot_id=source.snapshot_id,
                structured_metadata=source.structured_metadata,
                effective_scope=source.effective_scope,
                vector_model_digest=accumulator.vector_model_digest,
                vector_embedding_bytes_sha256=accumulator.vector_embedding_bytes_sha256,
                contributions=contributions,
                match_class=match_class,
                fused_score=sum(
                    (item.fixed_point_contribution for item in contributions)
                ),
                reason_codes=_reason_codes(contributions, match_class),
            )
        )
    return tuple(sorted(merged, key=candidate_rank_key))


@dataclass(frozen=True, slots=True)
class DiversitySelection:
    selected: tuple[HybridCandidate, ...]
    excluded_counts: Mapping[str, int]
    truncated: bool


def select_diverse_candidates(
    ranked_candidates: tuple[HybridCandidate, ...],
    *,
    maximum_items: int = MAX_BUNDLE_ITEMS,
) -> DiversitySelection:
    """Keep exact evidence first, then round-robin stable source groups."""
    if not isinstance(maximum_items, int) or isinstance(maximum_items, bool):
        raise TypeError("maximum_items must be an integer")
    if not 1 <= maximum_items <= MAX_BUNDLE_ITEMS:
        raise ValueError("maximum_items exceeds the fixed Step 20 policy")
    ordered = tuple(sorted(ranked_candidates, key=candidate_rank_key))
    selected: list[HybridCandidate] = []
    source_counts: dict[str, int] = defaultdict(int)
    version_counts: dict[str, int] = defaultdict(int)
    excluded: dict[str, int] = defaultdict(int)
    exact = tuple(
        (candidate for candidate in ordered if candidate.match_class in {0, 1})
    )
    remaining = tuple(
        (candidate for candidate in ordered if candidate.match_class not in {0, 1})
    )

    def admit(candidate: HybridCandidate) -> bool:
        if source_counts[candidate.identity.source_id] >= MAX_ITEMS_PER_SOURCE:
            excluded[Step20ReasonCode.DIVERSITY_SOURCE_CAP.value] += 1
            return False
        if (
            version_counts[candidate.identity.knowledge_version_id]
            >= MAX_ITEMS_PER_KNOWLEDGE_VERSION
        ):
            excluded[Step20ReasonCode.DIVERSITY_VERSION_CAP.value] += 1
            return False
        if len(selected) >= maximum_items:
            excluded[Step20ReasonCode.DIVERSITY_GLOBAL_LIMIT.value] += 1
            return False
        selected.append(candidate)
        source_counts[candidate.identity.source_id] += 1
        version_counts[candidate.identity.knowledge_version_id] += 1
        return True

    for index, candidate in enumerate(exact):
        if index >= MAX_EXACT_PRIORITY_ITEMS:
            excluded[Step20ReasonCode.DIVERSITY_EXACT_CAP.value] += 1
            continue
        admit(candidate)
    grouped: dict[str, list[HybridCandidate]] = {}
    for candidate in remaining:
        grouped.setdefault(candidate.identity.source_id, []).append(candidate)
    source_order = tuple(
        sorted(grouped, key=lambda source_id: candidate_rank_key(grouped[source_id][0]))
    )
    offsets = {source_id: 0 for source_id in source_order}
    while len(selected) < maximum_items:
        progressed = False
        for source_id in source_order:
            offset = offsets[source_id]
            group = grouped[source_id]
            if offset >= len(group):
                continue
            candidate = group[offset]
            offsets[source_id] = offset + 1
            progressed = True
            admit(candidate)
            if len(selected) >= maximum_items:
                break
        if not progressed:
            break
    if len(selected) >= maximum_items:
        for source_id in source_order:
            count = len(grouped[source_id]) - offsets[source_id]
            if count > 0:
                excluded[Step20ReasonCode.DIVERSITY_GLOBAL_LIMIT.value] += count
    frozen_excluded = MappingProxyType(dict(sorted(excluded.items())))
    return DiversitySelection(
        selected=tuple(selected),
        excluded_counts=frozen_excluded,
        truncated=bool(frozen_excluded),
    )


@dataclass(frozen=True, slots=True)
class BudgetAssembly:
    items: tuple[EvidenceBundleItem, ...]
    context_bytes_used: int
    excluded_counts: Mapping[str, int]
    truncated: bool


def utf8_safe_prefix(value: str, maximum_bytes: int) -> str:
    """Return the longest deterministic prefix that is valid UTF-8."""
    if not isinstance(value, str):
        raise TypeError("value must be text")
    if not isinstance(maximum_bytes, int) or isinstance(maximum_bytes, bool):
        raise TypeError("maximum_bytes must be an integer")
    if maximum_bytes < 0:
        raise ValueError("maximum_bytes must be non-negative")
    payload = value.encode("utf-8")
    if len(payload) <= maximum_bytes:
        return value
    return payload[:maximum_bytes].decode("utf-8", errors="ignore")


def assemble_budgeted_items(
    candidates: tuple[HybridCandidate, ...], *, context_budget_bytes: int
) -> BudgetAssembly:
    if (
        not isinstance(context_budget_bytes, int)
        or isinstance(context_budget_bytes, bool)
        or (not 1 <= context_budget_bytes <= MAX_CONTEXT_BUDGET_BYTES)
    ):
        raise ValueError("context budget exceeds Step 20 bounds")
    policy = load_ranking_policy()
    items: list[EvidenceBundleItem] = []
    excluded: dict[str, int] = defaultdict(int)
    used = 0
    for candidate in candidates:
        payload = candidate.content.encode("utf-8")
        remaining = context_budget_bytes - used
        allowed = min(MAX_EXCERPT_BYTES_PER_ITEM, remaining)
        if len(payload) <= allowed:
            excerpt_text = candidate.content
        else:
            excerpt_text = utf8_safe_prefix(candidate.content, allowed)
            if len(excerpt_text.encode("utf-8")) < MIN_PARTIAL_EXCERPT_BYTES:
                excluded[Step20ReasonCode.CONTEXT_BUDGET_EXCLUDED.value] += 1
                continue
        excerpt_payload = excerpt_text.encode("utf-8")
        truncated = len(excerpt_payload) < len(payload)
        if truncated:
            excluded[Step20ReasonCode.CONTEXT_EXCERPT_TRUNCATED.value] += 1
        excerpt = EvidenceExcerpt(
            text=excerpt_text,
            full_content_sha256=candidate.identity.content_sha256,
            start_byte=0,
            end_byte=len(excerpt_payload),
            utf8_byte_length=len(excerpt_payload),
            excerpt_sha256=hashlib.sha256(excerpt_payload).hexdigest(),
            truncated=truncated,
        )
        items.append(
            EvidenceBundleItem(
                item_ordinal=len(items) + 1,
                evidence_id=evidence_id_for(candidate.identity),
                identity=candidate.identity,
                citation_reference=citation_reference_for(
                    candidate.identity, candidate.source_reference
                ),
                excerpt=excerpt,
                authority_level=candidate.authority_level,
                authority_basis=candidate.authority_basis,
                source_kind=candidate.source_kind,
                source_reference=candidate.source_reference,
                publication_state=candidate.publication_state,
                access_class=candidate.access_class,
                target_scope=candidate.target_scope,
                owner_user_id=candidate.owner_user_id,
                personal_memory_space_id=candidate.personal_memory_space_id,
                scope_digest=candidate.scope_digest,
                registry_digest=candidate.registry_digest,
                artifact_digest=candidate.artifact_digest,
                snapshot_id=candidate.snapshot_id,
                structured_metadata=candidate.structured_metadata,
                effective_scope=candidate.effective_scope,
                contributions=candidate.contributions,
                match_class=candidate.match_class,
                fused_score=candidate.fused_score,
                ranking_policy_id=policy.policy_id,
                ranking_policy_version=policy.policy_version,
                ranking_policy_digest=policy.policy_digest,
            )
        )
        used += len(excerpt_payload)
    frozen_excluded = MappingProxyType(dict(sorted(excluded.items())))
    return BudgetAssembly(
        items=tuple(items),
        context_bytes_used=used,
        excluded_counts=frozen_excluded,
        truncated=bool(frozen_excluded),
    )
