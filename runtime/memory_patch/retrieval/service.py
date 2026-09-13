"""Compose Core-admitted sources without mixing personal memory into evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal
from runtime.evidence_admission import CoreEvidenceAdmission
from runtime.memory_patch.contracts.records import MAX_MERGED_CANDIDATES
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import (
    AuthorizedSourceRetrievalPort,
    FrozenEvidenceBundle,
    HybridRetrievalRequest,
    SourceCandidate,
)
from runtime.memory_patch.retrieval.ranking import (
    assemble_budgeted_items,
    merge_and_rank_candidates,
    select_diverse_candidates,
)
from runtime.memory_patch.retrieval.temporal import (
    FreshnessPolicy,
    TemporalQueryMode,
    TemporalSelection,
    resolve_temporal,
)


class OwnerMemoryRetrievalPort(Protocol):
    def retrieve(
        self,
        principal: CorePrincipal,
        *,
        hat_id: str,
        at: datetime,
        canonical_bundle: FrozenEvidenceBundle,
    ) -> tuple: ...


@dataclass(frozen=True, slots=True, repr=False)
class RetrievalLanes:
    canonical_evidence: FrozenEvidenceBundle
    temporal: TemporalSelection
    personal_context: tuple
    context_bytes: int
    truncated: bool


class NativeRetrieval:
    def __init__(
        self,
        core: CoreAdmission,
        evidence: CoreEvidenceAdmission,
        sources: AuthorizedSourceRetrievalPort | None = None,
        personal: OwnerMemoryRetrievalPort | None = None,
        freshness: FreshnessPolicy | None = None,
        *,
        clock=None,
    ):
        self.core, self.evidence, self.sources, self.personal = (
            core,
            evidence,
            sources,
            personal,
        )
        # Missing source-kind freshness is UNKNOWN, never an implicit fresh pass.
        self.freshness = freshness or FreshnessPolicy(
            "native-unconfigured-freshness", "1", {}
        )
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _port(self):
        if self.sources is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        return self.sources

    def _check_candidate(self, principal, request, value: SourceCandidate):
        self.core.require(principal, Capability.READ, scope=value.scope)
        if value.scope != request.scope or value.hat_scope_id != request.hat_scope_id:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if value.candidate_hash != canonical_sha256(
            value, exclude_fields=("candidate_hash",)
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        record = self.evidence.require_evidence(principal, value.core_evidence_id)
        if (
            value.source_id != record.source.source_id
            or value.knowledge_version_id != record.source.source_version_id
            or value.artifact_digest != record.source.artifact_fingerprint
            or value.content.encode("utf-8") not in record.artifact_bytes
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        self._port().require_binding(principal, value, value.core_evidence_id)

    def require_bundle(self, principal: CorePrincipal, bundle: FrozenEvidenceBundle):
        self.core.require(principal, principal.capability, scope=bundle.scope)
        if (
            bundle.hat_scope_id not in principal.hat_ids
            or bundle.bundle_hash
            != canonical_sha256(bundle, exclude_fields=("bundle_hash",))
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        bindings = dict(bundle.core_evidence_bindings)
        for item in bundle.items:
            record = self.evidence.require_evidence(principal, bindings[item.item_hash])
            if (
                item.identity.source_id != record.source.source_id
                or item.identity.knowledge_version_id != record.source.source_version_id
                or item.artifact_digest != record.source.artifact_fingerprint
                or item.excerpt.text.encode() not in record.artifact_bytes
            ):
                raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
            self._port().require_binding(principal, item, record.evidence_id)
        return bundle

    def retrieve(
        self,
        principal: CorePrincipal,
        request: HybridRetrievalRequest,
        *,
        mode: TemporalQueryMode = TemporalQueryMode.CURRENT,
        as_of=None,
        include_personal: bool = True,
    ) -> RetrievalLanes:
        self.core.require(principal, Capability.READ, scope=request.scope)
        if (
            request.hat_scope_id not in principal.hat_ids
            or request.request_hash
            != canonical_sha256(request, exclude_fields=("request_hash",))
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if type(include_personal) is not bool:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        values = self._port().candidates(principal, request)
        if type(values) is not tuple or len(values) > MAX_MERGED_CANDIDATES:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        identities = {}
        for value in values:
            self._check_candidate(principal, request, value.candidate)
            c = value.candidate
            key = (c.source_id, c.knowledge_version_id, c.chunk_id, c.content_sha256)
            if key in identities and identities[key] != c.core_evidence_id:
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
            identities[key] = c.core_evidence_id
        ranked = merge_and_rank_candidates(request, values)
        diverse = select_diverse_candidates(ranked)
        budget = assemble_budgeted_items(
            diverse.selected[: request.limit],
            context_budget_bytes=request.context_budget_bytes,
        )
        bindings = tuple(
            (
                item.item_hash,
                identities[
                    (
                        item.identity.source_id,
                        item.identity.knowledge_version_id,
                        item.identity.chunk_id,
                        item.identity.content_sha256,
                    )
                ],
            )
            for item in budget.items
        )
        bundle = FrozenEvidenceBundle(
            request.scope,
            request.hat_scope_id,
            budget.items,
            request.request_hash,
            bindings,
        )
        self.require_bundle(principal, bundle)
        now = self.clock()
        temporal = resolve_temporal(
            bundle, mode=mode, trusted_now=now, as_of=as_of, freshness=self.freshness
        )
        personal = ()
        if include_personal and self.personal is not None:
            personal = self.personal.retrieve(
                principal, hat_id=request.hat_scope_id, at=now, canonical_bundle=bundle
            )
        self.core.require(principal, Capability.READ, scope=request.scope)
        return RetrievalLanes(
            bundle,
            temporal,
            personal,
            budget.context_bytes_used,
            budget.truncated or len(budget.items) < len(ranked),
        )
