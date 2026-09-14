"""Bounded source retrieval, with tenant/owner/slot supplied by Core."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.enums import (
    MemoryTargetScope,
    ScopeComparisonMode,
    ScopeValueType,
)
from runtime.memory_patch.contracts.records import (
    EvidenceBundleItem,
    verify_bundle_item_hash,
)
from runtime.memory_patch.contracts.scope import ScopeDimension
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    freeze_json,
    require_sha256_hex,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.embeddings import load_approved_model_spec
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)


def bounded_text(value: str, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value.encode("utf-8")) > maximum
        or any(ord(c) < 32 and c not in "\n\t" for c in value)
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    return value


def trusted_dimensions(scope: OwnerScope, hat_id: str) -> tuple[ScopeDimension, ...]:
    return tuple(
        ScopeDimension(
            name,
            value,
            ScopeValueType.STRING,
            ScopeComparisonMode.EXACT,
            "core-admission",
            True,
        )
        for name, value in sorted(
            {
                "tenant": scope.tenant_id,
                "owner": scope.owner_id,
                "space": scope.space_id,
                "slot": scope.slot_id,
                "hat": hat_id,
            }.items()
        )
    )


class RetrievalMode(str, Enum):
    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    STATUTE_SECTION = "STATUTE_SECTION"
    FULL_TEXT = "FULL_TEXT"
    KEYWORD = "KEYWORD"


@dataclass(frozen=True, slots=True, repr=False)
class HybridRetrievalRequest:
    scope: OwnerScope
    hat_scope_id: str
    query: str
    private_sources: bool = True
    limit: int = 20
    context_budget_bytes: int = 65536
    embedding_model_digest: str = field(init=False)
    effective_scope: tuple[ScopeDimension, ...] = field(init=False)
    request_hash: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope or type(self.private_sources) is not bool:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        bounded_text(self.hat_scope_id)
        bounded_text(self.query, 4096)
        if (
            type(self.limit) is not int
            or not 1 <= self.limit <= 40
            or type(self.context_budget_bytes) is not int
            or not 1 <= self.context_budget_bytes <= 262144
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        object.__setattr__(
            self, "embedding_model_digest", load_approved_model_spec().model_digest
        )
        object.__setattr__(
            self, "effective_scope", trusted_dimensions(self.scope, self.hat_scope_id)
        )
        object.__setattr__(
            self,
            "request_hash",
            canonical_sha256(self, exclude_fields=("request_hash",)),
        )

    @property
    def tenant_id(self):
        return self.scope.tenant_id

    @property
    def user_id(self):
        return self.scope.owner_id

    @property
    def personal_memory_space_id(self):
        return self.scope.space_id if self.private_sources else None

    @classmethod
    def admitted(
        cls,
        core: CoreAdmission,
        principal: CorePrincipal,
        *,
        hat_id: str,
        query: str,
        limit: int = 20,
        context_budget_bytes: int = 65536,
        private_sources: bool = True,
    ):
        core.require(principal, Capability.READ)
        if hat_id not in principal.hat_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        return cls(
            principal.scope, hat_id, query, private_sources, limit, context_budget_bytes
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class SourceCandidate:
    scope: OwnerScope
    core_evidence_id: str
    tenant_id: str
    hat_scope_id: str
    source_id: str
    knowledge_version_id: str
    chunk_id: str
    chunk_ordinal: int
    content_sha256: str
    content: str
    language_tag: str | None
    authority_level: SourceAuthorityLevel
    authority_basis: Mapping[str, Any]
    source_kind: str
    source_reference: str
    publication_state: SourcePublicationState
    access_class: SourceAccessClass
    target_scope: MemoryTargetScope
    owner_user_id: str | None
    personal_memory_space_id: str | None
    scope_digest: str
    registry_digest: str
    artifact_digest: str
    snapshot_id: str
    structured_metadata: Mapping[str, Any]
    effective_scope: tuple[ScopeDimension, ...]
    candidate_hash: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope or self.tenant_id != self.scope.tenant_id:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        for name in (
            "core_evidence_id",
            "tenant_id",
            "hat_scope_id",
            "source_id",
            "knowledge_version_id",
            "chunk_id",
            "source_kind",
            "source_reference",
            "snapshot_id",
        ):
            bounded_text(
                getattr(self, name), 1024 if name == "source_reference" else 256
            )
        bounded_text(self.content, 65536)
        if (
            type(self.chunk_ordinal) is not int
            or self.chunk_ordinal < 0
            or self.chunk_ordinal > 1000000
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if hashlib.sha256(self.content.encode()).hexdigest() != self.content_sha256:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        for name in (
            "content_sha256",
            "scope_digest",
            "registry_digest",
            "artifact_digest",
        ):
            require_sha256_hex(getattr(self, name), name)
        if self.effective_scope != trusted_dimensions(
            self.scope, self.hat_scope_id
        ) or self.scope_digest != canonical_sha256(self.effective_scope):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        for name in ("authority_basis", "structured_metadata"):
            object.__setattr__(self, name, freeze_json(getattr(self, name)))
        object.__setattr__(
            self,
            "candidate_hash",
            canonical_sha256(self, exclude_fields=("candidate_hash",)),
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class RetrievalCandidate(SourceCandidate):
    retrieval_mode: RetrievalMode
    retrieval_score: str | None = None

    def __post_init__(self):
        if type(self.retrieval_mode) is not RetrievalMode:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if self.retrieval_score is not None:
            bounded_text(self.retrieval_score, 128)
        SourceCandidate.__post_init__(self)


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class VectorRetrievalCandidate(SourceCandidate):
    model_digest: str
    embedding_bytes_sha256: str
    vector_distance: str

    def __post_init__(self):
        from decimal import Decimal, InvalidOperation

        if self.model_digest != load_approved_model_spec().model_digest:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        require_sha256_hex(self.embedding_bytes_sha256, "embedding_bytes_sha256")
        bounded_text(self.vector_distance, 128)
        try:
            value = Decimal(self.vector_distance)
            if not value.is_finite() or value < 0 or value > 2.00001:
                raise ValueError()
        except (InvalidOperation, ValueError):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST) from None
        SourceCandidate.__post_init__(self)


@dataclass(frozen=True, slots=True, repr=False)
class FrozenEvidenceBundle:
    """Selected Core-admitted evidence. Construction alone is not admission."""

    scope: OwnerScope
    hat_scope_id: str
    items: tuple[EvidenceBundleItem, ...]
    request_hash: str
    core_evidence_bindings: tuple[tuple[str, str], ...]
    bundle_hash: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.scope) is not OwnerScope
            or type(self.items) is not tuple
            or len(self.items) > 40
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        require_sha256_hex(self.request_hash, "request_hash")
        if len(self.core_evidence_bindings) != len(self.items) or len(
            set(k for k, v in self.core_evidence_bindings)
        ) != len(self.items):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        for item in self.items:
            verify_bundle_item_hash(item)
            if (
                item.identity.tenant_id != self.scope.tenant_id
                or item.identity.hat_scope_id != self.hat_scope_id
                or item.effective_scope != self.effective_scope
            ):
                raise MemoryPatchError(ErrorCode.OWNER_DENIED)
            if item.item_hash not in dict(self.core_evidence_bindings):
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        object.__setattr__(
            self, "bundle_hash", canonical_sha256(self, exclude_fields=("bundle_hash",))
        )

    @property
    def tenant_id(self):
        return self.scope.tenant_id

    @property
    def user_id(self):
        return self.scope.owner_id

    @property
    def effective_scope(self):
        return trusted_dimensions(self.scope, self.hat_scope_id)


class AuthorizedSourceRetrievalPort(Protocol):
    """Implementations apply the full Core scope before limits or ranking."""

    def candidates(
        self, principal: CorePrincipal, request: HybridRetrievalRequest
    ) -> tuple: ...
    def require_binding(
        self,
        principal: CorePrincipal,
        value: SourceCandidate | EvidenceBundleItem,
        core_evidence_id: str,
    ) -> None:
        """Verify registry/metadata/chunk identity against Core-approved lineage."""
        ...
