"""Private immutable domain records. Record construction never grants authority."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field, replace
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from runtime.memory_patch.contracts.enums import (
    ActionPolicy,
    ActorType,
    ApprovalDecision,
    ApprovalRequirement,
    ClaimVerdictStatus,
    CorrectionCandidateState,
    DeidentificationStatus,
    EvidenceStatus,
    HatAuthorityDeclaration,
    KnowledgeRoute,
    MemoryConflictType,
    MemoryContentKind,
    MemoryRetrievalStatus,
    MemoryTargetScope,
    MemoryTrustClass,
    MemoryVisibility,
    ModelExperienceOutcome,
    PatchState,
    PersonalMemorySpaceState,
    PrivateDataClassification,
    ProposalOrigin,
    SharedPromotionState,
    StableStringEnum,
    StorageClass,
)
from runtime.memory_patch.contracts.identities import (
    KernelRunIdentity,
    MemoryOwnership,
    verify_ownership,
    verify_run_ownership,
)
from runtime.memory_patch.contracts.scope import (
    HatScopeDimensionDefinition,
    ScopeDimension,
    scope_interval_is_valid,
)
from runtime.memory_patch.contracts.serialization import (
    CONTRACT_SCHEMA_VERSION,
    approval_proof_hash,
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
    freeze_json,
    freeze_string_tuple,
    freeze_typed_tuple,
    require_enum_member,
    require_non_empty,
    require_schema_version,
    require_sha256_hex,
    verify_canonical_hash,
)
from runtime.memory_patch.errors import (
    AuthorityViolation,
    ContractValidationError,
    IntegrityError,
    OwnershipViolation,
    QuotaExceeded,
)
from runtime.memory_patch.retrieval.embeddings import load_approved_model_spec
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)

_EVIDENCE_TRUST_CLASSES = frozenset(
    {
        MemoryTrustClass.CANONICAL_SOURCE_EVIDENCE,
        MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY,
    }
)


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    """A reference to source-version bytes; model experience is never evidence."""

    evidence_id: str
    source_id: str
    source_version_id: str
    citation_reference: str
    content_hash: str
    trust_class: MemoryTrustClass
    authority_rank: int
    scope_dimensions: tuple[ScopeDimension, ...]
    retrieved_at: datetime
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "source_id",
            "source_version_id",
            "citation_reference",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_sha256_hex(self.content_hash, "content_hash")
        require_enum_member(self.trust_class, MemoryTrustClass, "trust_class")
        if self.trust_class not in _EVIDENCE_TRUST_CLASSES:
            raise ContractValidationError(
                f"{self.trust_class.value} is memory or advice, not factual evidence"
            )
        if (
            not isinstance(self.authority_rank, int)
            or isinstance(self.authority_rank, bool)
            or self.authority_rank < 0
        ):
            raise ContractValidationError(
                "authority_rank must be a non-negative integer"
            )
        object.__setattr__(
            self,
            "scope_dimensions",
            freeze_typed_tuple(
                self.scope_dimensions, ScopeDimension, "scope_dimensions"
            ),
        )
        object.__setattr__(
            self, "retrieved_at", ensure_utc(self.retrieved_at, "retrieved_at")
        )
        for field_name in ("valid_from", "valid_until"):
            timestamp = getattr(self, field_name)
            if timestamp is not None:
                object.__setattr__(self, field_name, ensure_utc(timestamp, field_name))
        if not scope_interval_is_valid(self.valid_from, self.valid_until):
            raise ContractValidationError("evidence validity interval is inverted")
        scope_names = [dimension.name for dimension in self.scope_dimensions]
        if len(scope_names) != len(set(scope_names)):
            raise ContractValidationError(
                "evidence scope dimension names must be unique"
            )
        object.__setattr__(self, "metadata", freeze_json(self.metadata))


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Ordered, frozen evidence selected under one retrieval policy."""

    evidence_bundle_id: str
    kernel_run_id: str
    hat_id: str
    evidence_status: EvidenceStatus
    ordered_items: tuple[EvidenceItem, ...]
    retrieval_policy_version: str
    created_at: datetime
    bundle_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_bundle_id",
            "kernel_run_id",
            "hat_id",
            "retrieval_policy_version",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_enum_member(self.evidence_status, EvidenceStatus, "evidence_status")
        object.__setattr__(
            self,
            "ordered_items",
            freeze_typed_tuple(self.ordered_items, EvidenceItem, "ordered_items"),
        )
        ids = [item.evidence_id for item in self.ordered_items]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("Evidence Bundle item IDs must be unique")
        if self.evidence_status is EvidenceStatus.SUFFICIENT and (
            not self.ordered_items
        ):
            raise ContractValidationError(
                "SUFFICIENT evidence status requires at least one evidence item"
            )
        if self.evidence_status is EvidenceStatus.NOT_REQUIRED and self.ordered_items:
            raise ContractValidationError(
                "NOT_REQUIRED Evidence Bundle must not contain evidence items"
            )
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        object.__setattr__(self, "bundle_hash", compute_evidence_bundle_hash(self))


@dataclass(frozen=True, slots=True)
class ClaimCandidate:
    """A draft claim identified for verification."""

    claim_id: str
    draft_id: str
    statement: str
    claim_category: str
    scope_dimensions: tuple[ScopeDimension, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("claim_id", "draft_id", "statement", "claim_category"):
            require_non_empty(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "scope_dimensions",
            freeze_typed_tuple(
                self.scope_dimensions, ScopeDimension, "scope_dimensions"
            ),
        )


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    """Evidence-bound verification outcome for one claim."""

    claim_id: str
    verdict: ClaimVerdictStatus
    evidence_references: tuple[str, ...]
    verifier_id: str
    verified_at: datetime
    explanation_code: str

    def __post_init__(self) -> None:
        require_non_empty(self.claim_id, "claim_id")
        require_enum_member(self.verdict, ClaimVerdictStatus, "verdict")
        require_non_empty(self.verifier_id, "verifier_id")
        require_non_empty(self.explanation_code, "explanation_code")
        object.__setattr__(
            self,
            "evidence_references",
            freeze_string_tuple(
                self.evidence_references, "evidence_references", unique=True
            ),
        )
        if self.verdict is ClaimVerdictStatus.SUPPORTED and (
            not self.evidence_references
        ):
            raise ContractValidationError(
                "a supported claim requires evidence references"
            )
        object.__setattr__(
            self, "verified_at", ensure_utc(self.verified_at, "verified_at")
        )


def compute_evidence_bundle_hash(bundle: EvidenceBundle) -> str:
    """Calculate a bundle digest while excluding its own digest field."""
    return canonical_sha256(bundle, exclude_fields=("bundle_hash",))


def verify_evidence_bundle_hash(bundle: EvidenceBundle) -> None:
    """Verify the immutable bundle identity."""
    verify_canonical_hash(bundle, bundle.bundle_hash, exclude_fields=("bundle_hash",))


TRUST_PRECEDENCE: tuple[MemoryTrustClass, ...] = (
    MemoryTrustClass.CANONICAL_SOURCE_EVIDENCE,
    MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY,
    MemoryTrustClass.PERSONAL_VERIFIED_PATCH,
    MemoryTrustClass.USER_ASSERTED_MEMORY,
    MemoryTrustClass.MODEL_EXPERIENCE_HINT,
    MemoryTrustClass.SESSION_MEMORY,
)
_TRUST_RANK = {
    trust_class: len(TRUST_PRECEDENCE) - index
    for index, trust_class in enumerate(TRUST_PRECEDENCE)
}
_ALLOWED_PREFERENCE_KEYS = frozenset(
    {"language", "format", "explanation_depth", "presentation", "workflow_preference"}
)
_PERSONAL_MEMORY_LIFECYCLE_PERMIT = object()


@dataclass(frozen=True, slots=True)
class PersonalHatQuotaPolicy:
    """Configurable limits; ``None`` means the deployment has not set a cap."""

    maximum_total_spaces: int | None = None
    maximum_active_spaces: int | None = None
    maximum_archived_spaces: int | None = None
    maximum_bytes: int | None = None
    maximum_personal_sources: int | None = None
    maximum_active_memory_patches: int | None = None
    maximum_session_memory_bytes: int | None = None
    maximum_ingestion_jobs: int | None = None
    maximum_embedding_or_index_bytes: int | None = None

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ContractValidationError(
                    f"{field_name} must be a non-negative integer or None"
                )


@dataclass(frozen=True, slots=True)
class PersonalHatQuotaUsage:
    total_spaces: int = 0
    active_spaces: int = 0
    archived_spaces: int = 0
    bytes_used: int = 0
    personal_sources: int = 0
    active_memory_patches: int = 0
    session_memory_bytes: int = 0
    ingestion_jobs: int = 0
    embedding_or_index_bytes: int = 0

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ContractValidationError(
                    f"{field_name} must be a non-negative integer"
                )


@dataclass(frozen=True, slots=True)
class PersonalMemorySpace:
    """Data namespace marketed as a Personal Memory HAT; never executable code."""

    schema_version: str
    personal_memory_space_id: str
    tenant_id: str
    user_id: str
    state: PersonalMemorySpaceState
    display_name: str | None
    created_at: datetime
    updated_at: datetime
    model_binding_ids: tuple[str, ...] = ()
    export_requested_at: datetime | None = None
    deletion_requested_at: datetime | None = None
    deleted_at: datetime | None = None
    _lifecycle_permit: InitVar[object | None] = None

    def __post_init__(self, _lifecycle_permit: object | None) -> None:
        require_schema_version(self.schema_version)
        require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        require_non_empty(self.tenant_id, "tenant_id")
        require_non_empty(self.user_id, "user_id")
        require_enum_member(self.state, PersonalMemorySpaceState, "state")
        if (
            self.state is not PersonalMemorySpaceState.EMPTY
            and _lifecycle_permit is not _PERSONAL_MEMORY_LIFECYCLE_PERMIT
        ):
            raise ContractValidationError(
                "non-empty Personal Memory HAT states require the validated state-machine transition API"
            )
        object.__setattr__(
            self,
            "model_binding_ids",
            freeze_string_tuple(
                self.model_binding_ids, "model_binding_ids", unique=True
            ),
        )
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", ensure_utc(self.updated_at, "updated_at")
        )
        if self.updated_at < self.created_at:
            raise ContractValidationError("updated_at cannot precede created_at")
        if self.state is PersonalMemorySpaceState.EMPTY:
            if self.display_name is not None:
                raise ContractValidationError("an EMPTY space cannot already be named")
            if self.model_binding_ids:
                raise ContractValidationError(
                    "an EMPTY space must be inert and have no model binding"
                )
        elif self.state in {
            PersonalMemorySpaceState.CONFIGURED,
            PersonalMemorySpaceState.ACTIVE,
            PersonalMemorySpaceState.SUSPENDED,
            PersonalMemorySpaceState.ARCHIVED,
        }:
            require_non_empty(self.display_name or "", "display_name")
        for field_name in (
            "export_requested_at",
            "deletion_requested_at",
            "deleted_at",
        ):
            timestamp = getattr(self, field_name)
            if timestamp is not None:
                object.__setattr__(self, field_name, ensure_utc(timestamp, field_name))
        if (
            self.state is PersonalMemorySpaceState.DELETED_PENDING
            and self.deletion_requested_at is None
        ):
            raise ContractValidationError(
                "DELETED_PENDING requires deletion_requested_at"
            )
        if self.state is PersonalMemorySpaceState.DELETED and self.deleted_at is None:
            raise ContractValidationError("DELETED requires deleted_at")
        if self.state is not PersonalMemorySpaceState.DELETED and self.deleted_at:
            raise ContractValidationError("only a DELETED space may set deleted_at")

    @property
    def ownership(self) -> MemoryOwnership:
        return MemoryOwnership(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            personal_memory_space_id=self.personal_memory_space_id,
        )

    @property
    def retrieval_eligible(self) -> bool:
        return self.state is PersonalMemorySpaceState.ACTIVE


@dataclass(frozen=True, slots=True)
class PersonalMemoryPool:
    """A tenant/user pool whose size is policy data, never a hardcoded constant."""

    tenant_id: str
    user_id: str
    quota_policy: PersonalHatQuotaPolicy
    spaces: tuple[PersonalMemorySpace, ...] = ()

    def __post_init__(self) -> None:
        require_non_empty(self.tenant_id, "tenant_id")
        require_non_empty(self.user_id, "user_id")
        if not isinstance(self.quota_policy, PersonalHatQuotaPolicy):
            raise ContractValidationError(
                "quota_policy must be a PersonalHatQuotaPolicy"
            )
        object.__setattr__(
            self,
            "spaces",
            freeze_typed_tuple(self.spaces, PersonalMemorySpace, "spaces"),
        )
        ids = [space.personal_memory_space_id for space in self.spaces]
        if len(ids) != len(set(ids)):
            raise ContractValidationError("personal memory space IDs must be unique")
        for space in self.spaces:
            if space.tenant_id != self.tenant_id or space.user_id != self.user_id:
                raise OwnershipViolation(
                    "a Personal Memory HAT pool cannot contain another owner"
                )
        enforce_quota(self.quota_policy, quota_usage(self.spaces))


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """Governed memory record; it never carries executable authority."""

    schema_version: str
    memory_item_id: str
    visibility: MemoryVisibility
    trust_class: MemoryTrustClass
    content_kind: MemoryContentKind
    content: Any
    scope_dimensions: tuple[ScopeDimension, ...]
    evidence_references: tuple[str, ...]
    created_at: datetime
    ownership: MemoryOwnership | None = None
    source_patch_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None
    active: bool = False
    revoked: bool = False

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        require_non_empty(self.memory_item_id, "memory_item_id")
        require_enum_member(self.visibility, MemoryVisibility, "visibility")
        require_enum_member(self.trust_class, MemoryTrustClass, "trust_class")
        require_enum_member(self.content_kind, MemoryContentKind, "content_kind")
        if self.active is not True and self.active is not False:
            raise ContractValidationError("active must be a boolean")
        if self.revoked is not True and self.revoked is not False:
            raise ContractValidationError("revoked must be a boolean")
        if self.active and self.trust_class in {
            MemoryTrustClass.PERSONAL_VERIFIED_PATCH,
            MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY,
        }:
            raise ContractValidationError(
                "verified MemoryItem activation requires a future approval-and-commit-bound materialization contract"
            )
        if self.source_patch_id is not None:
            require_non_empty(self.source_patch_id, "source_patch_id")
        if (
            self.trust_class
            in {
                MemoryTrustClass.PERSONAL_VERIFIED_PATCH,
                MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY,
            }
            and self.source_patch_id is None
        ):
            raise ContractValidationError(
                "verified memory requires its source_patch_id"
            )
        object.__setattr__(self, "content", freeze_json(self.content))
        object.__setattr__(
            self,
            "scope_dimensions",
            freeze_typed_tuple(
                self.scope_dimensions, ScopeDimension, "scope_dimensions"
            ),
        )
        object.__setattr__(
            self,
            "evidence_references",
            freeze_string_tuple(
                self.evidence_references, "evidence_references", unique=True
            ),
        )
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        for field_name in ("valid_from", "valid_until", "expires_at"):
            timestamp = getattr(self, field_name)
            if timestamp is not None:
                object.__setattr__(self, field_name, ensure_utc(timestamp, field_name))
        if not scope_interval_is_valid(self.valid_from, self.valid_until):
            raise ContractValidationError("memory validity interval is inverted")
        if self.expires_at is not None and self.expires_at <= self.created_at:
            raise ContractValidationError("memory expiry must follow creation")
        scope_names = [dimension.name for dimension in self.scope_dimensions]
        if len(scope_names) != len(set(scope_names)):
            raise ContractValidationError("memory scope dimension names must be unique")
        if (
            self.visibility in {MemoryVisibility.PERSONAL, MemoryVisibility.SESSION}
            and self.ownership is None
        ):
            raise ContractValidationError(
                "personal or session memory requires explicit ownership"
            )
        if self.visibility is MemoryVisibility.SHARED and self.ownership is not None:
            raise ContractValidationError(
                "shared memory cannot carry private-space ownership"
            )
        if self.trust_class is MemoryTrustClass.CANONICAL_SOURCE_EVIDENCE:
            raise ContractValidationError(
                "canonical evidence is not a MemoryItem or Memory Patch target"
            )
        if (
            self.content_kind is MemoryContentKind.MODEL_EXPERIENCE
            and self.trust_class is not MemoryTrustClass.MODEL_EXPERIENCE_HINT
        ):
            raise ContractValidationError(
                "model-experience content must remain an advisory hint"
            )
        if (
            self.content_kind is MemoryContentKind.FACTUAL
            and self.trust_class is MemoryTrustClass.PERSONAL_VERIFIED_PATCH
            and (not self.evidence_references)
        ):
            raise ContractValidationError(
                "personal verified factual memory requires evidence"
            )
        if self.content_kind is MemoryContentKind.PREFERENCE:
            validate_preference_content(self.content)


@dataclass(frozen=True, slots=True)
class MemoryConflict:
    """Explicit conflict record; resolution never silently overwrites memory."""

    conflict_type: MemoryConflictType
    higher_or_primary_item_id: str
    lower_or_secondary_item_id: str
    explanation: str
    resolved_by_precedence: bool

    def __post_init__(self) -> None:
        if (
            self.resolved_by_precedence is not True
            and self.resolved_by_precedence is not False
        ):
            raise ContractValidationError("resolved_by_precedence must be a boolean")
        require_non_empty(self.higher_or_primary_item_id, "higher_or_primary_item_id")
        require_enum_member(self.conflict_type, MemoryConflictType, "conflict_type")
        if self.conflict_type is not MemoryConflictType.NO_CONFLICT:
            require_non_empty(
                self.lower_or_secondary_item_id, "lower_or_secondary_item_id"
            )
            require_non_empty(self.explanation, "conflict explanation")
        if (
            self.conflict_type is MemoryConflictType.SAME_TRUST_CONFLICT
            and self.resolved_by_precedence
        ):
            raise ContractValidationError("a same-trust conflict must remain explicit")


def trust_rank(trust_class: MemoryTrustClass) -> int:
    """Return the deterministic factual precedence rank."""
    return _TRUST_RANK[trust_class]


def _replace_personal_memory_space(
    space: PersonalMemorySpace, **updates: object
) -> PersonalMemorySpace:
    """Internal constructor used only after lifecycle and owner validation."""
    return replace(
        space, **updates, _lifecycle_permit=_PERSONAL_MEMORY_LIFECYCLE_PERMIT
    )


def compare_memory_trust(left: MemoryTrustClass, right: MemoryTrustClass) -> int:
    """Return positive when left outranks right, zero when equal."""
    return trust_rank(left) - trust_rank(right)


def classify_memory_conflict(
    primary: MemoryItem, secondary: MemoryItem
) -> MemoryConflict:
    """Classify a content conflict using trust only, never by silent mutation."""
    comparison = compare_memory_trust(primary.trust_class, secondary.trust_class)
    if comparison == 0:
        return MemoryConflict(
            conflict_type=MemoryConflictType.SAME_TRUST_CONFLICT,
            higher_or_primary_item_id=primary.memory_item_id,
            lower_or_secondary_item_id=secondary.memory_item_id,
            explanation="items at the same trust class conflict",
            resolved_by_precedence=False,
        )
    higher, lower = (primary, secondary) if comparison > 0 else (secondary, primary)
    return MemoryConflict(
        conflict_type=MemoryConflictType.LOWER_TRUST_CONFLICT,
        higher_or_primary_item_id=higher.memory_item_id,
        lower_or_secondary_item_id=lower.memory_item_id,
        explanation="lower-trust memory cannot override higher-trust memory",
        resolved_by_precedence=True,
    )


def validate_preference_content(content: Any) -> None:
    """Allow presentation preferences, never factual or authority overrides."""
    if not isinstance(content, dict) and (not hasattr(content, "keys")):
        raise ContractValidationError("preference content must be an object")
    unsupported = set(content.keys()) - _ALLOWED_PREFERENCE_KEYS
    if unsupported:
        raise ContractValidationError(
            f"preference memory cannot override evidence, scope, policy, security, or approval: {', '.join(sorted(unsupported))}"
        )


def memory_item_is_retrieval_eligible(
    item: MemoryItem,
    *,
    at_time: datetime,
    tenant_id: str | None = None,
    user_id: str | None = None,
    personal_memory_space_id: str | None = None,
    personal_space_state: PersonalMemorySpaceState | None = None,
    shared_retrieval: bool = False,
) -> bool:
    """Apply visibility, ownership, lifecycle, revocation, and freshness guards."""
    return (
        memory_item_retrieval_status(
            item,
            at_time=at_time,
            tenant_id=tenant_id,
            user_id=user_id,
            personal_memory_space_id=personal_memory_space_id,
            personal_space_state=personal_space_state,
            shared_retrieval=shared_retrieval,
        )
        is MemoryRetrievalStatus.ELIGIBLE
    )


def memory_item_retrieval_status(
    item: MemoryItem,
    *,
    at_time: datetime,
    tenant_id: str | None = None,
    user_id: str | None = None,
    personal_memory_space_id: str | None = None,
    personal_space_state: PersonalMemorySpaceState | None = None,
    shared_retrieval: bool = False,
) -> MemoryRetrievalStatus:
    """Return an explicit exclusion reason while preserving ownership failures."""
    at_time = ensure_utc(at_time, "at_time")
    if item.revoked:
        return MemoryRetrievalStatus.REVOKED
    if not item.active:
        return MemoryRetrievalStatus.INACTIVE
    if item.valid_from is not None and at_time < item.valid_from:
        return MemoryRetrievalStatus.NOT_YET_VALID
    if item.valid_until is not None and at_time > item.valid_until:
        return MemoryRetrievalStatus.STALE
    if item.expires_at is not None and at_time >= item.expires_at:
        return MemoryRetrievalStatus.EXPIRED
    if item.visibility in {MemoryVisibility.PERSONAL, MemoryVisibility.SESSION}:
        if shared_retrieval:
            raise OwnershipViolation(
                "shared HAT retrieval cannot include private or session memory"
            )
        if item.ownership is None:
            raise OwnershipViolation("personal memory has no ownership context")
        verify_ownership(
            item.ownership,
            tenant_id=tenant_id,
            user_id=user_id,
            personal_memory_space_id=personal_memory_space_id,
        )
        if (
            item.visibility is MemoryVisibility.PERSONAL
            and personal_space_state is not PersonalMemorySpaceState.ACTIVE
        ):
            return MemoryRetrievalStatus.SPACE_NOT_ACTIVE
    return MemoryRetrievalStatus.ELIGIBLE


def quota_usage(spaces: tuple[PersonalMemorySpace, ...]) -> PersonalHatQuotaUsage:
    """Compute lifecycle counts represented directly by the current pool."""
    return PersonalHatQuotaUsage(
        total_spaces=sum(
            (space.state is not PersonalMemorySpaceState.DELETED for space in spaces)
        ),
        active_spaces=sum(
            (space.state is PersonalMemorySpaceState.ACTIVE for space in spaces)
        ),
        archived_spaces=sum(
            (space.state is PersonalMemorySpaceState.ARCHIVED for space in spaces)
        ),
    )


def enforce_quota(policy: PersonalHatQuotaPolicy, usage: PersonalHatQuotaUsage) -> None:
    """Reject a usage snapshot above any configured deployment quota."""
    mappings = (
        ("maximum_total_spaces", "total_spaces"),
        ("maximum_active_spaces", "active_spaces"),
        ("maximum_archived_spaces", "archived_spaces"),
        ("maximum_bytes", "bytes_used"),
        ("maximum_personal_sources", "personal_sources"),
        ("maximum_active_memory_patches", "active_memory_patches"),
        ("maximum_session_memory_bytes", "session_memory_bytes"),
        ("maximum_ingestion_jobs", "ingestion_jobs"),
        ("maximum_embedding_or_index_bytes", "embedding_or_index_bytes"),
    )
    for limit_name, usage_name in mappings:
        limit = getattr(policy, limit_name)
        current = getattr(usage, usage_name)
        if limit is not None and current > limit:
            raise QuotaExceeded(
                f"{usage_name}={current} exceeds configured {limit_name}={limit}"
            )


APPROVAL_ACTOR_TYPES = frozenset({ActorType.USER, ActorType.HUMAN_REVIEWER})
COMMIT_ACTOR_TYPES = frozenset({ActorType.COMMIT_SERVICE, ActorType.MIGRATION_SERVICE})
NON_AUTHORITY_PROPOSERS = frozenset(
    {
        ActorType.KNOWLEDGE_KERNEL,
        ActorType.KNOWLEDGE_HAT,
        ActorType.KNOWLEDGE_HUB,
        ActorType.CRITIC_PROMPT_LOOP,
        ActorType.MODEL,
        ActorType.MODEL_VERIFIER,
    }
)
_MEMORY_PATCH_LIFECYCLE_PERMIT = object()
_SHARED_PROMOTION_LIFECYCLE_PERMIT = object()


@dataclass(frozen=True, slots=True)
class MemoryPatchProposal:
    """Evidence-bound proposal whose origin never grants approval authority."""

    schema_version: str
    proposal_id: str
    tenant_id: str
    owner_user_id: str | None
    target_scope: MemoryTargetScope
    target_hat_id: str | None
    target_personal_memory_space_id: str | None
    origin: ProposalOrigin
    proposed_content: Any
    evidence_references: tuple[str, ...]
    scope_dimensions: tuple[ScopeDimension, ...]
    valid_from: datetime | None
    valid_until: datetime | None
    requested_trust_class: MemoryTrustClass
    approval_requirement: ApprovalRequirement
    lifecycle_state: PatchState
    content_kind: MemoryContentKind
    created_at: datetime
    _lifecycle_permit: InitVar[object | None] = None
    content_hash: str = field(init=False)

    def __post_init__(self, _lifecycle_permit: object | None) -> None:
        require_schema_version(self.schema_version)
        require_non_empty(self.proposal_id, "proposal_id")
        require_non_empty(self.tenant_id, "tenant_id")
        require_enum_member(self.target_scope, MemoryTargetScope, "target_scope")
        require_enum_member(self.origin, ProposalOrigin, "origin")
        require_enum_member(
            self.requested_trust_class, MemoryTrustClass, "requested_trust_class"
        )
        require_enum_member(
            self.approval_requirement, ApprovalRequirement, "approval_requirement"
        )
        require_enum_member(self.lifecycle_state, PatchState, "lifecycle_state")
        require_enum_member(self.content_kind, MemoryContentKind, "content_kind")
        if (
            self.lifecycle_state not in {PatchState.DETECTED, PatchState.PROPOSED}
            and _lifecycle_permit is not _MEMORY_PATCH_LIFECYCLE_PERMIT
        ):
            raise ContractValidationError(
                "privileged Memory Patch states require the validated state-machine transition API"
            )
        object.__setattr__(self, "proposed_content", freeze_json(self.proposed_content))
        object.__setattr__(
            self,
            "evidence_references",
            freeze_string_tuple(
                self.evidence_references, "evidence_references", unique=True
            ),
        )
        object.__setattr__(
            self,
            "scope_dimensions",
            freeze_typed_tuple(
                self.scope_dimensions, ScopeDimension, "scope_dimensions"
            ),
        )
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        for field_name in ("valid_from", "valid_until"):
            timestamp = getattr(self, field_name)
            if timestamp is not None:
                object.__setattr__(self, field_name, ensure_utc(timestamp, field_name))
        if not scope_interval_is_valid(self.valid_from, self.valid_until):
            raise ContractValidationError("patch validity interval is inverted")
        scope_names = [dimension.name for dimension in self.scope_dimensions]
        if len(scope_names) != len(set(scope_names)):
            raise ContractValidationError("patch scope dimension names must be unique")
        if self.requested_trust_class is MemoryTrustClass.CANONICAL_SOURCE_EVIDENCE:
            raise ContractValidationError(
                "canonical evidence is not a valid Memory Patch target"
            )
        if self.target_scope is MemoryTargetScope.USER_PERSONAL_HAT:
            require_non_empty(self.owner_user_id or "", "owner_user_id")
            require_non_empty(
                self.target_personal_memory_space_id or "",
                "target_personal_memory_space_id",
            )
            if self.target_hat_id is not None:
                raise ContractValidationError(
                    "personal patch cannot also target a shared Knowledge HAT"
                )
            if (
                self.requested_trust_class
                is MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY
            ):
                raise ContractValidationError(
                    "a personal patch cannot request shared-HAT trust"
                )
            if self.approval_requirement is not ApprovalRequirement.OWNER:
                raise ContractValidationError(
                    "a Personal Memory HAT patch requires exact owner approval"
                )
        elif self.target_scope is MemoryTargetScope.SHARED_KNOWLEDGE_HAT:
            require_non_empty(self.target_hat_id or "", "target_hat_id")
            if self.owner_user_id is not None:
                raise ContractValidationError(
                    "shared Knowledge HAT patch cannot carry a private owner"
                )
            if self.target_personal_memory_space_id is not None:
                raise ContractValidationError(
                    "shared patch cannot target a Personal Memory HAT"
                )
            if (
                self.requested_trust_class
                is not MemoryTrustClass.SHARED_HAT_VERIFIED_MEMORY
            ):
                raise ContractValidationError(
                    "shared patch must request shared-HAT verified trust"
                )
            if self.approval_requirement is not ApprovalRequirement.DOMAIN_REVIEWER:
                raise ContractValidationError(
                    "shared Knowledge HAT patch requires domain reviewer approval"
                )
        elif self.target_scope is MemoryTargetScope.SESSION:
            require_non_empty(self.owner_user_id or "", "owner_user_id")
            require_non_empty(
                self.target_personal_memory_space_id or "",
                "target_personal_memory_space_id",
            )
            if self.target_hat_id is not None:
                raise ContractValidationError(
                    "session patch cannot target a shared Knowledge HAT"
                )
            if self.requested_trust_class is not MemoryTrustClass.SESSION_MEMORY:
                raise ContractValidationError(
                    "session patch must request SESSION_MEMORY trust"
                )
            if self.approval_requirement is not ApprovalRequirement.OWNER:
                raise ContractValidationError(
                    "session patch requires exact owner approval"
                )
        if (
            self.content_kind is MemoryContentKind.MODEL_EXPERIENCE
            and self.requested_trust_class is not MemoryTrustClass.MODEL_EXPERIENCE_HINT
        ):
            raise ContractValidationError(
                "model experience can only request advisory hint trust"
            )
        if self.content_kind is MemoryContentKind.PREFERENCE:
            validate_preference_content(self.proposed_content)
        if (
            self.content_kind is MemoryContentKind.FACTUAL
            and self.lifecycle_state not in {PatchState.DETECTED, PatchState.PROPOSED}
            and (not self.evidence_references)
        ):
            raise ContractValidationError(
                "an evidence-bound factual patch requires evidence references"
            )
        object.__setattr__(
            self, "content_hash", compute_memory_patch_proposal_hash(self)
        )

    @property
    def ownership(self) -> MemoryOwnership | None:
        if self.owner_user_id is None or self.target_personal_memory_space_id is None:
            return None
        return MemoryOwnership(
            tenant_id=self.tenant_id,
            user_id=self.owner_user_id,
            personal_memory_space_id=self.target_personal_memory_space_id,
        )


@dataclass(frozen=True, slots=True)
class MemoryPatchApproval:
    """Claimed human/owner decision digest-bound to exact proposal scope.

    Construction validates the record shape and binding; it does not
    authenticate the claimed actor.
    """

    schema_version: str
    approval_id: str
    proposal_id: str
    proposal_content_hash: str
    tenant_id: str
    owner_user_id: str | None
    personal_memory_space_id: str | None
    decision: ApprovalDecision
    approver_type: ActorType
    approver_id: str
    reason_code: str
    decided_at: datetime
    approval_proof: str = field(init=False)

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        for field_name in (
            "approval_id",
            "proposal_id",
            "tenant_id",
            "approver_id",
            "reason_code",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_sha256_hex(self.proposal_content_hash, "proposal_content_hash")
        require_enum_member(self.decision, ApprovalDecision, "decision")
        require_enum_member(self.approver_type, ActorType, "approver_type")
        if self.approver_type not in APPROVAL_ACTOR_TYPES:
            raise AuthorityViolation(
                f"{self.approver_type.value} cannot approve a Memory Patch"
            )
        if (self.owner_user_id is None) != (self.personal_memory_space_id is None):
            raise ContractValidationError(
                "approval owner and Personal Memory HAT scope must be both present or both absent"
            )
        if self.personal_memory_space_id is not None:
            require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        if self.owner_user_id is not None:
            require_non_empty(self.owner_user_id, "owner_user_id")
        object.__setattr__(
            self, "decided_at", ensure_utc(self.decided_at, "decided_at")
        )
        object.__setattr__(
            self,
            "approval_proof",
            approval_proof_hash(
                approval_id=self.approval_id,
                proposal_id=self.proposal_id,
                proposal_hash=self.proposal_content_hash,
                tenant_id=self.tenant_id,
                owner_user_id=self.owner_user_id,
                personal_memory_space_id=self.personal_memory_space_id,
                decision=self.decision.value,
                approver_type=self.approver_type.value,
                approver_id=self.approver_id,
                reason_code=self.reason_code,
                decided_at=self.decided_at,
            ),
        )


@dataclass(frozen=True, slots=True)
class MemoryPatchCommit:
    """Claimed technical receipt, structurally separate from human approval."""

    schema_version: str
    commit_id: str
    proposal_id: str
    proposal_content_hash: str
    approval_id: str
    approval_proof: str
    committed_patch_id: str
    tenant_id: str
    owner_user_id: str | None
    personal_memory_space_id: str | None
    actor_type: ActorType
    actor_id: str
    storage_class: StorageClass
    committed_at: datetime
    commit_hash: str = field(init=False)

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        for field_name in (
            "commit_id",
            "proposal_id",
            "approval_id",
            "committed_patch_id",
            "tenant_id",
            "actor_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_sha256_hex(self.proposal_content_hash, "proposal_content_hash")
        require_sha256_hex(self.approval_proof, "approval_proof")
        require_enum_member(self.actor_type, ActorType, "actor_type")
        require_enum_member(self.storage_class, StorageClass, "storage_class")
        if self.actor_type not in COMMIT_ACTOR_TYPES:
            raise AuthorityViolation(
                f"{self.actor_type.value} has no technical commit authority"
            )
        if (self.owner_user_id is None) != (self.personal_memory_space_id is None):
            raise ContractValidationError(
                "commit owner and Personal Memory HAT scope must be both present or both absent"
            )
        if self.personal_memory_space_id is not None:
            require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        if self.owner_user_id is not None:
            require_non_empty(self.owner_user_id, "owner_user_id")
        if self.storage_class is not StorageClass.CRDB_TRANSACTIONAL:
            raise ContractValidationError(
                "active patch commitment is future transactional state, not a snapshot, cache, or session object"
            )
        object.__setattr__(
            self, "committed_at", ensure_utc(self.committed_at, "committed_at")
        )
        object.__setattr__(
            self, "commit_hash", canonical_sha256(self, exclude_fields=("commit_hash",))
        )


@dataclass(frozen=True, slots=True)
class SharedPromotionProposal:
    """Separate review object; the originating personal patch is unchanged."""

    schema_version: str
    shared_promotion_proposal_id: str
    originating_personal_patch_id: str
    originating_personal_patch_hash: str
    originating_personal_memory_space_id: str
    tenant_id: str
    owner_user_id: str
    target_hat_id: str
    private_data_classification: PrivateDataClassification
    deidentification_status: DeidentificationStatus
    independent_evidence_references: tuple[str, ...]
    independent_evidence_validated: bool
    hat_scope_dimensions: tuple[ScopeDimension, ...]
    valid_from: datetime | None
    valid_until: datetime | None
    domain_approval_id: str | None
    shared_commit_id: str | None
    state: SharedPromotionState
    created_at: datetime
    updated_at: datetime
    _lifecycle_permit: InitVar[object | None] = None
    proposal_hash: str = field(init=False)

    def __post_init__(self, _lifecycle_permit: object | None) -> None:
        require_schema_version(self.schema_version)
        for field_name in (
            "shared_promotion_proposal_id",
            "originating_personal_patch_id",
            "originating_personal_memory_space_id",
            "tenant_id",
            "owner_user_id",
            "target_hat_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_sha256_hex(
            self.originating_personal_patch_hash, "originating_personal_patch_hash"
        )
        require_enum_member(
            self.private_data_classification,
            PrivateDataClassification,
            "private_data_classification",
        )
        require_enum_member(
            self.deidentification_status,
            DeidentificationStatus,
            "deidentification_status",
        )
        require_enum_member(self.state, SharedPromotionState, "state")
        if (
            self.state is not SharedPromotionState.SHARED_PROMOTION_PROPOSED
            and _lifecycle_permit is not _SHARED_PROMOTION_LIFECYCLE_PERMIT
        ):
            raise ContractValidationError(
                "reviewed or committed shared-promotion states require the validated state-machine transition API"
            )
        if not isinstance(self.independent_evidence_validated, bool):
            raise ContractValidationError(
                "independent_evidence_validated must be a boolean"
            )
        object.__setattr__(
            self,
            "independent_evidence_references",
            freeze_string_tuple(
                self.independent_evidence_references,
                "independent_evidence_references",
                unique=True,
            ),
        )
        object.__setattr__(
            self,
            "hat_scope_dimensions",
            freeze_typed_tuple(
                self.hat_scope_dimensions, ScopeDimension, "hat_scope_dimensions"
            ),
        )
        if self.shared_promotion_proposal_id == self.originating_personal_patch_id:
            raise ContractValidationError(
                "shared promotion must receive a new proposal ID"
            )
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        object.__setattr__(
            self, "updated_at", ensure_utc(self.updated_at, "updated_at")
        )
        if self.updated_at < self.created_at:
            raise ContractValidationError("updated_at cannot precede created_at")
        for field_name in ("valid_from", "valid_until"):
            timestamp = getattr(self, field_name)
            if timestamp is not None:
                object.__setattr__(self, field_name, ensure_utc(timestamp, field_name))
        if not scope_interval_is_valid(self.valid_from, self.valid_until):
            raise ContractValidationError("promotion validity interval is inverted")
        if self.domain_approval_id is not None and self.state not in {
            SharedPromotionState.APPROVED_FOR_SHARED,
            SharedPromotionState.SHARED_PATCH_COMMITTED,
        }:
            raise ContractValidationError(
                "advisory shared-promotion states cannot carry domain approval"
            )
        if (
            self.shared_commit_id is not None
            and self.state is not SharedPromotionState.SHARED_PATCH_COMMITTED
        ):
            raise ContractValidationError(
                "uncommitted shared-promotion states cannot carry a commit"
            )
        if self.state in {
            SharedPromotionState.EVIDENCE_REVALIDATED,
            SharedPromotionState.DOMAIN_REVIEW_REQUIRED,
            SharedPromotionState.APPROVED_FOR_SHARED,
            SharedPromotionState.SHARED_PATCH_COMMITTED,
        } and (
            not self.independent_evidence_validated
            or not self.independent_evidence_references
        ):
            raise ContractValidationError(
                "shared promotion requires independent evidence revalidation"
            )
        if self.state in {
            SharedPromotionState.APPROVED_FOR_SHARED,
            SharedPromotionState.SHARED_PATCH_COMMITTED,
        } and (not self.domain_approval_id):
            raise ContractValidationError(
                "user approval alone is insufficient for shared activation"
            )
        if (
            self.private_data_classification is not PrivateDataClassification.NONE
            and self.deidentification_status is not DeidentificationStatus.COMPLETE
            and (
                self.state
                in {
                    SharedPromotionState.APPROVED_FOR_SHARED,
                    SharedPromotionState.SHARED_PATCH_COMMITTED,
                }
            )
        ):
            raise ContractValidationError(
                "private personal data must be de-identified before shared approval"
            )
        if self.state is SharedPromotionState.SHARED_PATCH_COMMITTED and (
            not self.shared_commit_id
        ):
            raise ContractValidationError(
                "shared promotion commitment requires a separate commit ID"
            )
        if self.shared_commit_id is not None:
            require_non_empty(self.shared_commit_id, "shared_commit_id")
        if self.domain_approval_id is not None:
            require_non_empty(self.domain_approval_id, "domain_approval_id")
        object.__setattr__(self, "proposal_hash", compute_shared_promotion_hash(self))


def compute_memory_patch_proposal_hash(proposal: MemoryPatchProposal) -> str:
    """Hash immutable proposal content, not its lifecycle cursor or own hash."""
    return canonical_sha256(
        proposal, exclude_fields=("content_hash", "lifecycle_state")
    )


def verify_memory_patch_proposal_hash(proposal: MemoryPatchProposal) -> None:
    """Verify proposal content identity across state transitions."""
    verify_canonical_hash(
        proposal,
        proposal.content_hash,
        exclude_fields=("content_hash", "lifecycle_state"),
    )


def verify_approval_binding(
    proposal: MemoryPatchProposal, approval: MemoryPatchApproval
) -> None:
    """Validate proposal identity, ownership, and proof binding."""
    if not isinstance(proposal, MemoryPatchProposal):
        raise ContractValidationError("proposal must be a MemoryPatchProposal")
    if not isinstance(approval, MemoryPatchApproval):
        raise ContractValidationError("approval must be a MemoryPatchApproval")
    verify_memory_patch_proposal_hash(proposal)
    if approval.proposal_id != proposal.proposal_id:
        raise ContractValidationError("approval references another proposal")
    if approval.proposal_content_hash != proposal.content_hash:
        raise ContractValidationError("approval is bound to different content")
    if approval.tenant_id != proposal.tenant_id:
        raise ContractValidationError("approval tenant mismatch")
    if proposal.target_scope in {
        MemoryTargetScope.USER_PERSONAL_HAT,
        MemoryTargetScope.SESSION,
    } and (
        approval.owner_user_id != proposal.owner_user_id
        or approval.personal_memory_space_id != proposal.target_personal_memory_space_id
    ):
        raise ContractValidationError("personal patch approval owner mismatch")
    if proposal.target_scope is MemoryTargetScope.SHARED_KNOWLEDGE_HAT and (
        approval.owner_user_id is not None
        or approval.personal_memory_space_id is not None
    ):
        raise ContractValidationError(
            "shared patch approval cannot carry private ownership"
        )
    if approval.decided_at < proposal.created_at:
        raise ContractValidationError("approval cannot precede proposal creation")
    expected = approval_proof_hash(
        approval_id=approval.approval_id,
        proposal_id=approval.proposal_id,
        proposal_hash=approval.proposal_content_hash,
        tenant_id=approval.tenant_id,
        owner_user_id=approval.owner_user_id,
        personal_memory_space_id=approval.personal_memory_space_id,
        decision=approval.decision.value,
        approver_type=approval.approver_type.value,
        approver_id=approval.approver_id,
        reason_code=approval.reason_code,
        decided_at=approval.decided_at,
    )
    if expected != approval.approval_proof:
        raise ContractValidationError("approval proof does not verify")


def verify_commit_binding(
    proposal: MemoryPatchProposal,
    approval: MemoryPatchApproval,
    commit: MemoryPatchCommit,
) -> None:
    """Validate technical commit receipt binding to content and approval."""
    if not isinstance(commit, MemoryPatchCommit):
        raise ContractValidationError("commit must be a MemoryPatchCommit")
    verify_approval_binding(proposal, approval)
    if approval.decision is not ApprovalDecision.APPROVE:
        raise ContractValidationError("a rejection cannot authorize commitment")
    if commit.proposal_id != proposal.proposal_id:
        raise ContractValidationError("commit references another proposal")
    if commit.proposal_content_hash != proposal.content_hash:
        raise ContractValidationError("commit is bound to different content")
    if commit.tenant_id != proposal.tenant_id:
        raise ContractValidationError("commit tenant mismatch")
    if commit.owner_user_id != proposal.owner_user_id:
        raise ContractValidationError("commit owner mismatch")
    if commit.personal_memory_space_id != proposal.target_personal_memory_space_id:
        raise ContractValidationError("commit personal memory space mismatch")
    if commit.committed_at < proposal.created_at:
        raise ContractValidationError("commit cannot precede proposal creation")
    if commit.approval_id != approval.approval_id:
        raise ContractValidationError("commit references another approval")
    if commit.approval_proof != approval.approval_proof:
        raise ContractValidationError("commit approval proof mismatch")
    if commit.committed_at < approval.decided_at:
        raise ContractValidationError(
            "technical commitment cannot precede bound approval"
        )
    verify_canonical_hash(commit, commit.commit_hash, exclude_fields=("commit_hash",))


def compute_shared_promotion_hash(proposal: SharedPromotionProposal) -> str:
    """Hash the complete current promotion review record."""
    return canonical_sha256(proposal, exclude_fields=("proposal_hash",))


def verify_shared_promotion_hash(proposal: SharedPromotionProposal) -> None:
    """Verify a promotion record without modifying the personal source patch."""
    verify_canonical_hash(
        proposal, proposal.proposal_hash, exclude_fields=("proposal_hash",)
    )


def _replace_memory_patch_lifecycle(
    proposal: MemoryPatchProposal, *, lifecycle_state: PatchState
) -> MemoryPatchProposal:
    """Internal constructor used only after state-machine validation."""
    return replace(
        proposal,
        lifecycle_state=lifecycle_state,
        _lifecycle_permit=_MEMORY_PATCH_LIFECYCLE_PERMIT,
    )


def _replace_shared_promotion_lifecycle(
    proposal: SharedPromotionProposal, **updates: object
) -> SharedPromotionProposal:
    """Internal constructor used only after shared review validation."""
    return replace(
        proposal, **updates, _lifecycle_permit=_SHARED_PROMOTION_LIFECYCLE_PERMIT
    )


_CORRECTION_PRODUCERS = frozenset(
    {
        ActorType.KNOWLEDGE_KERNEL,
        ActorType.KNOWLEDGE_HAT,
        ActorType.KNOWLEDGE_HUB,
        ActorType.CRITIC_PROMPT_LOOP,
        ActorType.MODEL_VERIFIER,
        ActorType.USER,
        ActorType.HUMAN_REVIEWER,
    }
)


@dataclass(frozen=True, slots=True)
class CorrectionCandidate:
    """Proposal-only correction signal; never approval, memory, or authority."""

    event_id: str
    tenant_id: str
    user_id: str
    personal_memory_space_id: str
    source_component: ActorType
    run_id: str
    model_binding_id: str
    draft_v1_reference: str
    detected_claims: tuple[ClaimCandidate, ...]
    proposed_correction: str
    available_evidence_references: tuple[str, ...]
    uncertainty: float
    created_at: datetime
    state: CorrectionCandidateState
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "event_id",
            "tenant_id",
            "user_id",
            "personal_memory_space_id",
            "run_id",
            "model_binding_id",
            "draft_v1_reference",
            "proposed_correction",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_enum_member(self.source_component, ActorType, "source_component")
        require_enum_member(self.state, CorrectionCandidateState, "state")
        if self.source_component not in _CORRECTION_PRODUCERS:
            raise ContractValidationError(
                f"{self.source_component.value} cannot produce Correction Candidates"
            )
        object.__setattr__(
            self,
            "detected_claims",
            freeze_typed_tuple(self.detected_claims, ClaimCandidate, "detected_claims"),
        )
        object.__setattr__(
            self,
            "available_evidence_references",
            freeze_string_tuple(
                self.available_evidence_references,
                "available_evidence_references",
                unique=True,
            ),
        )
        if not self.detected_claims:
            raise ContractValidationError(
                "a Correction Candidate requires at least one detected claim"
            )
        claim_ids = [claim.claim_id for claim in self.detected_claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ContractValidationError(
                "Correction Candidate claim IDs must be unique"
            )
        if not isinstance(self.uncertainty, (int, float)) or isinstance(
            self.uncertainty, bool
        ):
            raise ContractValidationError("uncertainty must be numeric")
        if not 0.0 <= float(self.uncertainty) <= 1.0:
            raise ContractValidationError("uncertainty must be between 0 and 1")
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        object.__setattr__(
            self,
            "content_hash",
            canonical_sha256(self, exclude_fields=("content_hash",)),
        )

    @property
    def ownership(self) -> MemoryOwnership:
        return MemoryOwnership(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            personal_memory_space_id=self.personal_memory_space_id,
        )


@dataclass(frozen=True, slots=True)
class CorrectionRequirement:
    """A declarative, evidence-bound correction instruction."""

    requirement_id: str
    claim_id: str
    instruction: str
    evidence_references: tuple[str, ...]
    mandatory: bool

    def __post_init__(self) -> None:
        require_non_empty(self.requirement_id, "requirement_id")
        require_non_empty(self.claim_id, "claim_id")
        require_non_empty(self.instruction, "instruction")
        if self.mandatory is not True and self.mandatory is not False:
            raise ContractValidationError("mandatory must be a boolean")
        object.__setattr__(
            self,
            "evidence_references",
            freeze_string_tuple(
                self.evidence_references, "evidence_references", unique=True
            ),
        )
        if self.mandatory and (not self.evidence_references):
            raise ContractValidationError(
                "mandatory factual correction requires evidence references"
            )


@dataclass(frozen=True, slots=True)
class CorrectionPacket:
    """Frozen evidence and correction input for a future Draft V2 generator."""

    schema_version: str
    kernel_run_id: str
    draft_v1_id: str
    selected_hat_id: str
    knowledge_route: KnowledgeRoute
    action_policy: ActionPolicy
    evidence_status: EvidenceStatus
    scope_dimensions: tuple[ScopeDimension, ...]
    knowledge_as_of: datetime | None
    claims_under_review: tuple[ClaimCandidate, ...]
    ordered_evidence_items: tuple[EvidenceItem, ...]
    source_version_ids: tuple[str, ...]
    validity_or_version_scopes: tuple[ScopeDimension, ...]
    conflicts: tuple[MemoryConflict, ...]
    required_corrections: tuple[CorrectionRequirement, ...]
    prohibited_claims: tuple[str, ...]
    uncertainty: float
    citation_requirements: tuple[str, ...]
    retrieval_policy_version: str
    embedding_model_version: str | None
    packet_hash: str = field(init=False)

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        for field_name in (
            "kernel_run_id",
            "draft_v1_id",
            "selected_hat_id",
            "retrieval_policy_version",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_enum_member(self.knowledge_route, KnowledgeRoute, "knowledge_route")
        require_enum_member(self.action_policy, ActionPolicy, "action_policy")
        require_enum_member(self.evidence_status, EvidenceStatus, "evidence_status")
        for field_name, expected_type in (
            ("scope_dimensions", ScopeDimension),
            ("claims_under_review", ClaimCandidate),
            ("ordered_evidence_items", EvidenceItem),
            ("validity_or_version_scopes", ScopeDimension),
            ("conflicts", MemoryConflict),
            ("required_corrections", CorrectionRequirement),
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_typed_tuple(
                    getattr(self, field_name), expected_type, field_name
                ),
            )
        for field_name in (
            "source_version_ids",
            "prohibited_claims",
            "citation_requirements",
        ):
            object.__setattr__(
                self,
                field_name,
                freeze_string_tuple(
                    getattr(self, field_name),
                    field_name,
                    unique=field_name == "source_version_ids",
                ),
            )
        if self.embedding_model_version is not None:
            require_non_empty(self.embedding_model_version, "embedding_model_version")
        if self.knowledge_route not in {
            KnowledgeRoute.HAT_ASSIST,
            KnowledgeRoute.HAT_ENFORCE,
        }:
            raise ContractValidationError(
                "a Correction Packet requires a HAT-assisted or enforced route"
            )
        if self.knowledge_as_of is not None:
            object.__setattr__(
                self,
                "knowledge_as_of",
                ensure_utc(self.knowledge_as_of, "knowledge_as_of"),
            )
        if not self.claims_under_review:
            raise ContractValidationError(
                "Correction Packet requires claims under review"
            )
        claim_ids = [claim.claim_id for claim in self.claims_under_review]
        if len(claim_ids) != len(set(claim_ids)):
            raise ContractValidationError("Correction Packet claim IDs must be unique")
        evidence_ids = [item.evidence_id for item in self.ordered_evidence_items]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ContractValidationError(
                "Correction Packet evidence IDs must be unique"
            )
        requirement_ids = [
            requirement.requirement_id for requirement in self.required_corrections
        ]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ContractValidationError("Correction requirement IDs must be unique")
        if not isinstance(self.uncertainty, (int, float)) or isinstance(
            self.uncertainty, bool
        ):
            raise ContractValidationError("uncertainty must be numeric")
        if not 0.0 <= float(self.uncertainty) <= 1.0:
            raise ContractValidationError("uncertainty must be between 0 and 1")
        ordered_versions = tuple(
            (item.source_version_id for item in self.ordered_evidence_items)
        )
        if set(ordered_versions) != set(self.source_version_ids):
            raise ContractValidationError(
                "source_version_ids must exactly cover ordered evidence"
            )
        if len(self.source_version_ids) != len(set(self.source_version_ids)):
            raise ContractValidationError("source_version_ids must be unique")
        if self.evidence_status is EvidenceStatus.SUFFICIENT and (
            not self.ordered_evidence_items
        ):
            raise ContractValidationError(
                "sufficient Correction Packet requires evidence"
            )
        object.__setattr__(self, "packet_hash", compute_correction_packet_hash(self))


def validate_correction_candidate_ownership(
    candidate: CorrectionCandidate,
    *,
    run: KernelRunIdentity,
    target_ownership: MemoryOwnership,
) -> None:
    """Block a Critic or Kernel event from creating memory for another owner."""
    if candidate.run_id != run.kernel_run_id:
        raise OwnershipViolation("Correction Candidate references another run")
    if candidate.model_binding_id != run.model_binding_id:
        raise OwnershipViolation("model binding mismatch")
    verify_run_ownership(run, target_ownership)
    if candidate.ownership != target_ownership:
        raise OwnershipViolation("Correction Candidate target ownership mismatch")


def compute_correction_candidate_hash(candidate: CorrectionCandidate) -> str:
    """Compute a candidate digest excluding its own hash."""
    return canonical_sha256(candidate, exclude_fields=("content_hash",))


def verify_correction_candidate_hash(candidate: CorrectionCandidate) -> None:
    """Verify candidate integrity."""
    verify_canonical_hash(
        candidate, candidate.content_hash, exclude_fields=("content_hash",)
    )


def compute_correction_packet_hash(packet: CorrectionPacket) -> str:
    """Compute deterministic identity for the frozen packet."""
    return canonical_sha256(packet, exclude_fields=("packet_hash",))


def verify_correction_packet_hash(packet: CorrectionPacket) -> None:
    """Verify frozen packet integrity."""
    verify_canonical_hash(packet, packet.packet_hash, exclude_fields=("packet_hash",))


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Metadata-only audit record suitable for future at-least-once export."""

    schema_version: str
    audit_event_id: str
    tenant_id: str
    user_id: str | None
    kernel_run_id: str | None
    event_type: str
    sequence_number: int
    previous_event_hash: str | None
    resource_type: str
    resource_id: str
    state_before: str | None
    state_after: str | None
    actor_type: ActorType
    actor_id: str
    content_hashes: Mapping[str, str]
    created_at: datetime
    personal_memory_space_id: str | None = None
    protected_payload_reference: str | None = None
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        require_schema_version(self.schema_version)
        for field_name in (
            "audit_event_id",
            "tenant_id",
            "event_type",
            "resource_type",
            "resource_id",
            "actor_id",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        for field_name in ("user_id", "kernel_run_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_non_empty(value, field_name)
        require_enum_member(self.actor_type, ActorType, "actor_type")
        if (
            not isinstance(self.sequence_number, int)
            or isinstance(self.sequence_number, bool)
            or self.sequence_number < 0
        ):
            raise ContractValidationError(
                "sequence_number must be a non-negative integer"
            )
        if self.sequence_number == 0 and self.previous_event_hash is not None:
            raise ContractValidationError(
                "first audit event must not have a previous hash"
            )
        if self.sequence_number > 0:
            require_sha256_hex(self.previous_event_hash or "", "previous_event_hash")
        if not self.content_hashes:
            raise ContractValidationError(
                "audit metadata requires at least one content hash"
            )
        if not isinstance(self.content_hashes, Mapping):
            raise ContractValidationError("content_hashes must be a mapping")
        for name, digest in self.content_hashes.items():
            require_non_empty(name, "content hash label")
            require_sha256_hex(digest, f"content hash {name}")
        object.__setattr__(self, "content_hashes", freeze_json(self.content_hashes))
        if self.protected_payload_reference is not None:
            require_non_empty(
                self.protected_payload_reference, "protected_payload_reference"
            )
            if self.protected_payload_reference.startswith("data:"):
                raise ContractValidationError(
                    "audit payload must be referenced, not embedded"
                )
        if self.personal_memory_space_id is not None:
            if self.user_id is None:
                raise ContractValidationError("personal audit scope requires user_id")
            require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        object.__setattr__(self, "event_hash", compute_audit_event_hash(self))


def compute_audit_event_hash(event: AuditEvent) -> str:
    """Calculate a deterministic audit digest excluding its own hash."""
    return canonical_sha256(event, exclude_fields=("event_hash",))


def verify_audit_event_hash(event: AuditEvent) -> None:
    """Verify one audit record's deterministic identity."""
    verify_canonical_hash(event, event.event_hash, exclude_fields=("event_hash",))


def verify_audit_chain(events: tuple[AuditEvent, ...]) -> None:
    """Verify sequence order, content integrity, and previous-hash linkage."""
    seen_ids: set[str] = set()
    previous: AuditEvent | None = None
    for event in events:
        if event.audit_event_id in seen_ids:
            raise IntegrityError("duplicate audit_event_id in audit chain")
        seen_ids.add(event.audit_event_id)
        verify_audit_event_hash(event)
        if previous is None:
            if event.sequence_number != 0 or event.previous_event_hash is not None:
                raise IntegrityError("audit chain must start at sequence zero")
        else:
            if event.sequence_number != previous.sequence_number + 1:
                raise IntegrityError("audit sequence is not contiguous")
            if event.previous_event_hash != previous.event_hash:
                raise IntegrityError("audit previous-event hash mismatch")
            if event.tenant_id != previous.tenant_id:
                raise IntegrityError("an audit chain cannot cross tenants")
            if event.created_at < previous.created_at:
                raise IntegrityError("audit event time cannot move backwards")
        previous = event


def deduplicate_audit_events(events: tuple[AuditEvent, ...]) -> tuple[AuditEvent, ...]:
    """Deduplicate at-least-once exports by stable audit_event_id."""
    by_id: dict[str, AuditEvent] = {}
    for event in events:
        existing = by_id.get(event.audit_event_id)
        if existing is not None and existing.event_hash != event.event_hash:
            raise IntegrityError(
                "same audit_event_id was observed with different content"
            )
        by_id[event.audit_event_id] = event
    return tuple(
        sorted(
            by_id.values(),
            key=lambda event: (event.sequence_number, event.audit_event_id),
        )
    )


def build_audit_event(
    *,
    audit_event_id: str,
    tenant_id: str,
    user_id: str | None,
    kernel_run_id: str | None,
    event_type: str,
    sequence_number: int,
    previous_event: AuditEvent | None,
    resource_type: str,
    resource_id: str,
    state_before: str | None,
    state_after: str | None,
    actor_type: ActorType,
    actor_id: str,
    content_hashes: Mapping[str, str],
    created_at: datetime,
    personal_memory_space_id: str | None = None,
    protected_payload_reference: str | None = None,
) -> AuditEvent:
    """Build the next event using only metadata and protected references."""
    if previous_event is None:
        if sequence_number != 0:
            raise ContractValidationError(
                "first audit event sequence_number must be zero"
            )
        previous_hash = None
    else:
        if tenant_id != previous_event.tenant_id:
            raise ContractValidationError("audit event cannot cross tenants")
        if sequence_number != previous_event.sequence_number + 1:
            raise ContractValidationError("audit sequence must be contiguous")
        previous_hash = previous_event.event_hash
    return AuditEvent(
        schema_version=CONTRACT_SCHEMA_VERSION,
        audit_event_id=audit_event_id,
        tenant_id=tenant_id,
        user_id=user_id,
        kernel_run_id=kernel_run_id,
        event_type=event_type,
        sequence_number=sequence_number,
        previous_event_hash=previous_hash,
        resource_type=resource_type,
        resource_id=resource_id,
        state_before=state_before,
        state_after=state_after,
        actor_type=actor_type,
        actor_id=actor_id,
        content_hashes=content_hashes,
        created_at=created_at,
        personal_memory_space_id=personal_memory_space_id,
        protected_payload_reference=protected_payload_reference,
    )


_IDENTIFIER = re.compile("^[a-z0-9][a-z0-9._-]*$")
_LANGUAGE = re.compile("^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
_FORBIDDEN_CAPABILITY_TOKENS = (
    "EXTERNAL_ACTION",
    "SHELL",
    "FILE_WRITE",
    "MESSAGE_SEND",
    "PAYMENT",
    "CANONICAL_WRITE",
    "PATCH_APPROVAL",
    "PATCH_COMMIT",
    "MEMORY_ACTIVATION",
    "CAPABILITY_GRANT",
)
_RESERVED_SECURITY_KEYS = frozenset(
    {
        "external_action_authority",
        "canonical_write_authority",
        "patch_approval_authority",
        "patch_commit_authority",
        "executable_user_code",
        "private_memory_access",
    }
)
HAT_MANIFEST_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class HatSecurityPolicy:
    """Knowledge HATs declare zero authority at all consequential boundaries."""

    external_action_authority: HatAuthorityDeclaration = HatAuthorityDeclaration.NONE
    canonical_write_authority: HatAuthorityDeclaration = HatAuthorityDeclaration.NONE
    patch_approval_authority: HatAuthorityDeclaration = HatAuthorityDeclaration.NONE
    patch_commit_authority: HatAuthorityDeclaration = HatAuthorityDeclaration.NONE
    executable_user_code: bool = False
    private_memory_access: bool = False

    def __post_init__(self) -> None:
        for name, declaration in (
            ("external_action_authority", self.external_action_authority),
            ("canonical_write_authority", self.canonical_write_authority),
            ("patch_approval_authority", self.patch_approval_authority),
            ("patch_commit_authority", self.patch_commit_authority),
        ):
            try:
                require_enum_member(declaration, HatAuthorityDeclaration, name)
            except ContractValidationError as exc:
                raise AuthorityViolation(f"{name} must be declared as NONE") from exc
        declarations = (
            self.external_action_authority,
            self.canonical_write_authority,
            self.patch_approval_authority,
            self.patch_commit_authority,
        )
        if any((value is not HatAuthorityDeclaration.NONE for value in declarations)):
            raise AuthorityViolation("a Knowledge HAT must declare all authority NONE")
        if self.executable_user_code is not False:
            raise AuthorityViolation("a Knowledge HAT cannot execute user code")
        if self.private_memory_access is not False:
            raise AuthorityViolation(
                "shared Knowledge HAT retrieval cannot access private memory"
            )


@dataclass(frozen=True, slots=True)
class HatManifest:
    """Domain-neutral, versioned declaration consumed by Kernel Core."""

    schema_version: str
    hat_id: str
    hat_version: str
    display_name: str
    domain_ids: tuple[str, ...]
    kernel_api_compatibility: str
    supported_languages: tuple[str, ...]
    scope_dimension_definitions: tuple[HatScopeDimensionDefinition, ...]
    capabilities: tuple[str, ...]
    source_authority_policy: Mapping[str, Any]
    retrieval_contract: Mapping[str, Any]
    claim_contract: Mapping[str, Any]
    conflict_contract: Mapping[str, Any]
    memory_policy: Mapping[str, Any]
    security_policy: HatSecurityPolicy
    extension_points: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in (
            "schema_version",
            "hat_id",
            "hat_version",
            "display_name",
            "kernel_api_compatibility",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        if self.schema_version != HAT_MANIFEST_SCHEMA_VERSION:
            raise ContractValidationError(
                f"unsupported HAT manifest schema_version {self.schema_version!r}"
            )
        if not _IDENTIFIER.fullmatch(self.hat_id):
            raise ContractValidationError(
                "hat_id must use lowercase letters, digits, dots, underscores, or hyphens"
            )
        object.__setattr__(
            self,
            "domain_ids",
            freeze_string_tuple(self.domain_ids, "domain_ids", unique=True),
        )
        object.__setattr__(
            self,
            "supported_languages",
            freeze_string_tuple(
                self.supported_languages, "supported_languages", unique=True
            ),
        )
        object.__setattr__(
            self,
            "scope_dimension_definitions",
            freeze_typed_tuple(
                self.scope_dimension_definitions,
                HatScopeDimensionDefinition,
                "scope_dimension_definitions",
            ),
        )
        object.__setattr__(
            self,
            "capabilities",
            freeze_string_tuple(self.capabilities, "capabilities", unique=True),
        )
        if not self.domain_ids:
            raise ContractValidationError("domain_ids must be non-empty and unique")
        if any((not _IDENTIFIER.fullmatch(item) for item in self.domain_ids)):
            raise ContractValidationError("domain_ids contain an invalid identifier")
        if not self.supported_languages:
            raise ContractValidationError(
                "supported_languages must be non-empty and unique"
            )
        if any(
            (not _LANGUAGE.fullmatch(language) for language in self.supported_languages)
        ):
            raise ContractValidationError("supported_languages contain an invalid tag")
        names = [definition.name for definition in self.scope_dimension_definitions]
        if len(names) != len(set(names)):
            raise ContractValidationError(
                "scope_dimension_definitions must have unique names"
            )
        if not self.capabilities:
            raise ContractValidationError(
                "capabilities must contain non-empty declarations"
            )
        for capability in self.capabilities:
            normalized = capability.upper()
            if any((token in normalized for token in _FORBIDDEN_CAPABILITY_TOKENS)):
                raise AuthorityViolation(
                    f"Knowledge HAT capability {capability!r} declares forbidden authority"
                )
        if not isinstance(self.security_policy, HatSecurityPolicy):
            raise ContractValidationError("security_policy must be a HatSecurityPolicy")
        for field_name in (
            "source_authority_policy",
            "retrieval_contract",
            "claim_contract",
            "conflict_contract",
            "memory_policy",
            "extension_points",
        ):
            object.__setattr__(self, field_name, freeze_json(getattr(self, field_name)))
            _assert_no_hidden_security_declaration(
                getattr(self, field_name), field_name=field_name
            )
        validate_hat_manifest(self)


def _assert_no_hidden_security_declaration(value: Any, *, field_name: str) -> None:
    """Reserve all authority declarations for the closed security policy."""
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key.casefold() in _RESERVED_SECURITY_KEYS:
                raise AuthorityViolation(
                    f"{field_name} cannot redeclare HAT security key {key!r}"
                )
            _assert_no_hidden_security_declaration(nested, field_name=field_name)
    elif isinstance(value, (tuple, frozenset)):
        for nested in value:
            _assert_no_hidden_security_declaration(nested, field_name=field_name)


def validate_hat_manifest(manifest: HatManifest) -> None:
    """Validate a manifest without loading or executing HAT implementation code."""
    if not isinstance(manifest, HatManifest):
        raise ContractValidationError("manifest must be a HatManifest")
    policy = manifest.security_policy
    if policy.external_action_authority is not HatAuthorityDeclaration.NONE:
        raise AuthorityViolation("HAT external-action authority must be NONE")
    if policy.canonical_write_authority is not HatAuthorityDeclaration.NONE:
        raise AuthorityViolation("HAT canonical-write authority must be NONE")
    if policy.patch_approval_authority is not HatAuthorityDeclaration.NONE:
        raise AuthorityViolation("HAT patch-approval authority must be NONE")
    if policy.patch_commit_authority is not HatAuthorityDeclaration.NONE:
        raise AuthorityViolation("HAT patch-commit authority must be NONE")


@runtime_checkable
class HatSdk(Protocol):
    """Static interface for trusted, system-installed future Knowledge HATs.

    The contract is intentionally not a loader. Kernel Core never imports
    arbitrary user-provided modules through this protocol.
    """

    @property
    def manifest(self) -> HatManifest:
        """Return the immutable installed manifest."""

    def validate_manifest(self) -> None:
        """Validate the installed manifest and declared compatibility."""

    def normalize_request(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Normalize request data without executing external actions."""

    def derive_scope_requirements(
        self, request: Mapping[str, Any]
    ) -> tuple[ScopeDimension, ...]:
        """Derive typed scope constraints for the request."""

    def build_retrieval_constraints(
        self, dimensions: tuple[ScopeDimension, ...]
    ) -> Mapping[str, Any]:
        """Build a declarative retrieval constraint record."""

    def rank_source_authority(
        self, source_metadata: tuple[Mapping[str, Any], ...]
    ) -> tuple[str, ...]:
        """Return source identifiers in declared authority order."""

    def extract_candidate_claims(
        self, draft_reference: str
    ) -> tuple[ClaimCandidate, ...]:
        """Describe candidate claims; it does not call a model."""

    def detect_conflicts(
        self, evidence_references: tuple[str, ...]
    ) -> tuple[MemoryConflict, ...]:
        """Return explicit candidate conflicts."""

    def create_correction_requirements(
        self, claim_references: tuple[str, ...]
    ) -> tuple[CorrectionRequirement, ...]:
        """Create declarative correction requirements."""

    def create_memory_patch_proposal(
        self, correction_reference: str
    ) -> MemoryPatchProposal:
        """Propose, but never approve, commit, or activate, a Memory Patch."""


def assert_system_installed_hat(instance: object) -> None:
    """Validate SDK shape only; dynamic loading is deliberately unsupported."""
    if not isinstance(instance, HatSdk):
        raise ContractValidationError("installed HAT does not implement HatSdk")
    validate_hat_manifest(instance.manifest)


@dataclass(frozen=True, slots=True)
class ModelExperienceEvent:
    """A bounded hint about model behavior, scoped to model identity and owner."""

    model_experience_event_id: str
    tenant_id: str | None
    user_id: str | None
    personal_memory_space_id: str | None
    provider: str
    model_family: str
    exact_model_version: str
    failure_category: str
    kernel_run_id: str
    claim_category: str
    correction_outcome: ModelExperienceOutcome
    verifier_outcome: str
    created_at: datetime
    expires_at: datetime | None
    retention_policy: str
    event_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "model_experience_event_id",
            "provider",
            "model_family",
            "exact_model_version",
            "failure_category",
            "kernel_run_id",
            "claim_category",
            "verifier_outcome",
            "retention_policy",
        ):
            require_non_empty(getattr(self, field_name), field_name)
        require_enum_member(
            self.correction_outcome, ModelExperienceOutcome, "correction_outcome"
        )
        if (self.tenant_id is None) != (self.user_id is None):
            raise ContractValidationError(
                "tenant and user scope must be both present or both absent"
            )
        if self.tenant_id is not None:
            require_non_empty(self.tenant_id, "tenant_id")
            require_non_empty(self.user_id or "", "user_id")
        if self.personal_memory_space_id is not None:
            if self.tenant_id is None or self.user_id is None:
                raise ContractValidationError(
                    "personal memory space requires tenant and user scope"
                )
            require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )
        if self.expires_at is not None:
            object.__setattr__(
                self, "expires_at", ensure_utc(self.expires_at, "expires_at")
            )
            if self.expires_at <= self.created_at:
                raise ContractValidationError(
                    "model experience expiry must follow creation"
                )
        object.__setattr__(
            self, "event_hash", canonical_sha256(self, exclude_fields=("event_hash",))
        )


def assert_model_experience_is_advisory(
    event: ModelExperienceEvent,
    *,
    used_as_evidence: bool = False,
    used_for_approval: bool = False,
    used_for_action_authorization: bool = False,
) -> None:
    """Reject forbidden uses while leaving prioritization as a future seam."""
    if not isinstance(event, ModelExperienceEvent):
        raise ContractValidationError("event must be a ModelExperienceEvent")
    if used_as_evidence:
        raise ContractValidationError("model experience is never factual evidence")
    if used_for_approval:
        raise ContractValidationError("model experience cannot approve memory")
    if used_for_action_authorization:
        raise ContractValidationError("model experience cannot authorize actions")


RANKING_POLICY_ID = "hybrid-retrieval-ranking-1a"
RANKING_POLICY_VERSION = "1"
RRF_K = 60
RRF_SCALE = 1000000000
MAX_UPSTREAM_RESULTS_PER_MODALITY = 100
MAX_MERGED_CANDIDATES = 500
MAX_BUNDLE_ITEMS = 40
MAX_ITEMS_PER_SOURCE = 3
MAX_ITEMS_PER_KNOWLEDGE_VERSION = 4
MAX_EXACT_PRIORITY_ITEMS = 8
MAX_CONTEXT_BUDGET_BYTES = 262144
MAX_EXCERPT_BYTES_PER_ITEM = 8192
MIN_PARTIAL_EXCERPT_BYTES = 256


class HybridModality(StableStringEnum):
    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    STATUTE_SECTION = "STATUTE_SECTION"
    FULL_TEXT = "FULL_TEXT"
    KEYWORD = "KEYWORD"
    VECTOR = "VECTOR"


_hybrid_MODALITY_ORDER = {
    HybridModality.STATUTE_SECTION: 0,
    HybridModality.EXACT_IDENTIFIER: 1,
    HybridModality.FULL_TEXT: 2,
    HybridModality.VECTOR: 3,
    HybridModality.KEYWORD: 4,
}
_hybrid_MODALITY_WEIGHTS = {
    HybridModality.STATUTE_SECTION: 8,
    HybridModality.EXACT_IDENTIFIER: 8,
    HybridModality.FULL_TEXT: 4,
    HybridModality.VECTOR: 3,
    HybridModality.KEYWORD: 2,
}


class RetrievalCoverageStatus(StableStringEnum):
    """Completeness relative only to the bounded Step 20 request."""

    EMPTY = "EMPTY"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"
    INVALID = "INVALID"


class Step20ReasonCode(StableStringEnum):
    HYBRID_OK = "HYBRID_OK"
    NO_HAT_SELECTED = "NO_HAT_SELECTED"
    AMBIGUOUS_ROUTE = "AMBIGUOUS_ROUTE"
    HYBRID_INPUT_REQUIRED = "HYBRID_INPUT_REQUIRED"
    HYBRID_INPUT_HASH_INVALID = "HYBRID_INPUT_HASH_INVALID"
    HYBRID_INPUT_BINDING_MISMATCH = "HYBRID_INPUT_BINDING_MISMATCH"
    HYBRID_MODEL_MISMATCH = "HYBRID_MODEL_MISMATCH"
    HYBRID_SCOPE_MISMATCH = "HYBRID_SCOPE_MISMATCH"
    HYBRID_CANDIDATE_INVALID = "HYBRID_CANDIDATE_INVALID"
    HYBRID_CANDIDATE_METADATA_CONFLICT = "HYBRID_CANDIDATE_METADATA_CONFLICT"
    HYBRID_DUPLICATE_MERGED = "HYBRID_DUPLICATE_MERGED"
    HYBRID_EXACT_PRIORITY = "HYBRID_EXACT_PRIORITY"
    HYBRID_MULTI_MODAL_SUPPORT = "HYBRID_MULTI_MODAL_SUPPORT"
    HYBRID_VECTOR_ONLY = "HYBRID_VECTOR_ONLY"
    HYBRID_RANKED = "HYBRID_RANKED"
    DIVERSITY_SOURCE_CAP = "DIVERSITY_SOURCE_CAP"
    DIVERSITY_VERSION_CAP = "DIVERSITY_VERSION_CAP"
    DIVERSITY_EXACT_CAP = "DIVERSITY_EXACT_CAP"
    DIVERSITY_GLOBAL_LIMIT = "DIVERSITY_GLOBAL_LIMIT"
    CONTEXT_BUDGET_EXCLUDED = "CONTEXT_BUDGET_EXCLUDED"
    CONTEXT_EXCERPT_TRUNCATED = "CONTEXT_EXCERPT_TRUNCATED"
    BUNDLE_TRUNCATED = "BUNDLE_TRUNCATED"
    NO_ADMISSIBLE_EVIDENCE = "NO_ADMISSIBLE_EVIDENCE"
    EVIDENCE_BUNDLE_INVALID = "EVIDENCE_BUNDLE_INVALID"
    EVIDENCE_BUNDLE_PERSISTENCE_ERROR = "EVIDENCE_BUNDLE_PERSISTENCE_ERROR"
    EVIDENCE_BUNDLE_REPLAY_CONFLICT = "EVIDENCE_BUNDLE_REPLAY_CONFLICT"


class Step20BoundaryError(RuntimeError):
    """Sanitized fail-closed Step 20 error."""

    def __init__(self, reason_code: Step20ReasonCode) -> None:
        if not isinstance(reason_code, Step20ReasonCode):
            raise TypeError("reason_code must be a Step20ReasonCode")
        super().__init__(f"Step 20 evidence assembly denied: {reason_code.value}")
        self.reason_code = reason_code
        self.retrieval_coverage = RetrievalCoverageStatus.INVALID
        self.evidence_status = EvidenceStatus.INVALID


_hybrid_CONTROL = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]")
_hybrid_FORBIDDEN_METADATA_KEYS = (
    "api_key",
    "authorization",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_hybrid_SUPPORTED_AUTHORITY = frozenset(
    {
        SourceAuthorityLevel.OFFICIAL_PRIMARY,
        SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    }
)


def modality_order(value: HybridModality) -> int:
    require_enum_member(value, HybridModality, "modality")
    return _hybrid_MODALITY_ORDER[value]


def modality_weight(value: HybridModality) -> int:
    require_enum_member(value, HybridModality, "modality")
    return _hybrid_MODALITY_WEIGHTS[value]


def _hybrid_text(value: object, field_name: str, maximum_bytes: int = 1024) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractValidationError(f"{field_name} must be canonical text")
    if unicodedata.normalize("NFC", value) != value or _hybrid_CONTROL.search(value):
        raise ContractValidationError(f"{field_name} must be NFC without controls")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ContractValidationError(f"{field_name} exceeds its byte limit")
    return value


def _hybrid_content(value: object, field_name: str, maximum_bytes: int) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError(f"{field_name} must be non-empty text")
    if unicodedata.normalize("NFC", value) != value:
        raise ContractValidationError(f"{field_name} must use Unicode NFC")
    for character in value:
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}:
            raise ContractValidationError(f"{field_name} contains a prohibited control")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ContractValidationError(f"{field_name} exceeds its byte limit")
    return value


def _hybrid_optional_text(
    value: object | None, field_name: str, maximum_bytes: int = 1024
) -> str | None:
    return None if value is None else _hybrid_text(value, field_name, maximum_bytes)


def _hybrid_scope_tuple(value: object, field_name: str) -> tuple[ScopeDimension, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must be an ordered scope")
    result = tuple(value)
    if any((not isinstance(item, ScopeDimension) for item in result)):
        raise ContractValidationError(f"{field_name} must contain ScopeDimension")
    names = tuple((item.name for item in result))
    if names != tuple(sorted(names)) or len(names) != len(set(names)):
        raise ContractValidationError(f"{field_name} must be sorted and unique")
    return result


def _hybrid_reject_float_or_secret(value: Any, path: str = "metadata") -> None:
    if isinstance(value, float):
        raise ContractValidationError(
            f"{path} must not contain native float hash material"
        )
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = str(key).lower()
            if any((marker in lowered for marker in _hybrid_FORBIDDEN_METADATA_KEYS)):
                raise ContractValidationError(
                    f"{path} contains forbidden secret metadata"
                )
            _hybrid_reject_float_or_secret(child, f"{path}.{key}")
    elif isinstance(value, (tuple, list, set, frozenset)):
        for index, child in enumerate(value):
            _hybrid_reject_float_or_secret(child, f"{path}[{index}]")


def _hybrid_mapping(
    value: object, field_name: str, maximum_bytes: int
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or not all(
        (isinstance(key, str) for key in value)
    ):
        raise ContractValidationError(f"{field_name} must be a string-keyed object")
    _hybrid_reject_float_or_secret(value, field_name)
    frozen = freeze_json(value)
    if len(canonical_json_bytes(frozen)) > maximum_bytes:
        raise ContractValidationError(f"{field_name} exceeds its byte limit")
    return frozen


def _hybrid_reason_tuple(value: object) -> tuple[Step20ReasonCode, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError("reason_codes must be ordered")
    result = tuple(value)
    if any((not isinstance(item, Step20ReasonCode) for item in result)):
        raise ContractValidationError("reason_codes must use Step20ReasonCode")
    if len(result) != len(set(result)):
        raise ContractValidationError("reason_codes must be unique")
    return result


def _hybrid_expected_match_class(
    contributions: tuple[ModalityContribution, ...],
) -> int:
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


def _hybrid_expected_candidate_reasons(
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


@dataclass(frozen=True, slots=True)
class RankingPolicy:
    policy_id: str = field(init=False, default=RANKING_POLICY_ID)
    policy_version: str = field(init=False, default=RANKING_POLICY_VERSION)
    rrf_k: int = field(init=False, default=RRF_K)
    rrf_scale: int = field(init=False, default=RRF_SCALE)
    modality_weights: Mapping[str, int] = field(init=False)
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        weights = freeze_json(
            {
                modality.value: _hybrid_MODALITY_WEIGHTS[modality]
                for modality in sorted(HybridModality, key=modality_order)
            }
        )
        object.__setattr__(self, "modality_weights", weights)
        object.__setattr__(
            self,
            "policy_digest",
            canonical_sha256(self, exclude_fields=("policy_digest",)),
        )


@dataclass(frozen=True, slots=True)
class DiversityPolicy:
    policy_id: str = field(init=False, default="hybrid-diversity-1a")
    policy_version: str = field(init=False, default="1")
    maximum_bundle_items: int = field(init=False, default=MAX_BUNDLE_ITEMS)
    maximum_items_per_source: int = field(init=False, default=MAX_ITEMS_PER_SOURCE)
    maximum_items_per_knowledge_version: int = field(
        init=False, default=MAX_ITEMS_PER_KNOWLEDGE_VERSION
    )
    maximum_exact_priority_items: int = field(
        init=False, default=MAX_EXACT_PRIORITY_ITEMS
    )
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_digest",
            canonical_sha256(self, exclude_fields=("policy_digest",)),
        )


def load_ranking_policy() -> RankingPolicy:
    return RankingPolicy()


def load_diversity_policy() -> DiversityPolicy:
    return DiversityPolicy()


@dataclass(frozen=True, slots=True)
class CandidateIdentity:
    tenant_id: str
    hat_scope_id: str
    source_id: str
    knowledge_version_id: str
    chunk_id: str
    content_sha256: str
    identity_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.tenant_id, "tenant_id"),
            (self.hat_scope_id, "hat_scope_id"),
            (self.source_id, "source_id"),
            (self.knowledge_version_id, "knowledge_version_id"),
            (self.chunk_id, "chunk_id"),
        ):
            _hybrid_text(value, name, 255)
        require_sha256_hex(self.content_sha256, "content_sha256")
        object.__setattr__(
            self,
            "identity_hash",
            canonical_sha256(self, exclude_fields=("identity_hash",)),
        )


@dataclass(frozen=True, slots=True)
class ModalityContribution:
    modality: HybridModality
    upstream_request_hash: str
    upstream_result_hash: str
    upstream_candidate_hash: str
    one_based_rank: int
    retrieval_local_value: str | None
    fixed_point_contribution: int
    contribution_hash: str = field(init=False)

    def __post_init__(self) -> None:
        require_enum_member(self.modality, HybridModality, "modality")
        for value, name in (
            (self.upstream_request_hash, "upstream_request_hash"),
            (self.upstream_result_hash, "upstream_result_hash"),
            (self.upstream_candidate_hash, "upstream_candidate_hash"),
        ):
            require_sha256_hex(value, name)
        if (
            isinstance(self.one_based_rank, bool)
            or not isinstance(self.one_based_rank, int)
            or (not 1 <= self.one_based_rank <= MAX_UPSTREAM_RESULTS_PER_MODALITY)
        ):
            raise ContractValidationError("one_based_rank is outside Step 20 bounds")
        if self.retrieval_local_value is not None:
            _hybrid_text(self.retrieval_local_value, "retrieval_local_value", 128)
        expected = (
            RRF_SCALE * modality_weight(self.modality) // (RRF_K + self.one_based_rank)
        )
        if self.fixed_point_contribution != expected:
            raise ContractValidationError(
                "fixed-point contribution differs from policy"
            )
        object.__setattr__(
            self,
            "contribution_hash",
            canonical_sha256(self, exclude_fields=("contribution_hash",)),
        )


@dataclass(frozen=True, slots=True)
class HybridCandidate:
    identity: CandidateIdentity
    chunk_ordinal: int
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
    vector_model_digest: str | None
    vector_embedding_bytes_sha256: str | None
    contributions: tuple[ModalityContribution, ...]
    match_class: int
    fused_score: int
    reason_codes: tuple[Step20ReasonCode, ...]
    modality_count: int = field(init=False)
    candidate_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CandidateIdentity):
            raise ContractValidationError("identity must be CandidateIdentity")
        verify_candidate_identity_hash(self.identity)
        if (
            isinstance(self.chunk_ordinal, bool)
            or not isinstance(self.chunk_ordinal, int)
            or self.chunk_ordinal < 0
        ):
            raise ContractValidationError("chunk_ordinal must be non-negative")
        content = _hybrid_content(self.content, "content", 64 * 1024)
        if (
            hashlib.sha256(content.encode("utf-8")).hexdigest()
            != self.identity.content_sha256
        ):
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        object.__setattr__(self, "content", content)
        object.__setattr__(
            self,
            "language_tag",
            _hybrid_optional_text(self.language_tag, "language_tag", 64),
        )
        require_enum_member(
            self.authority_level, SourceAuthorityLevel, "authority_level"
        )
        if self.authority_level not in _hybrid_SUPPORTED_AUTHORITY:
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        object.__setattr__(
            self,
            "authority_basis",
            _hybrid_mapping(self.authority_basis, "authority_basis", 16 * 1024),
        )
        _hybrid_text(self.source_kind, "source_kind", 1024)
        _hybrid_text(self.source_reference, "source_reference", 2048)
        require_enum_member(
            self.publication_state, SourcePublicationState, "publication_state"
        )
        if self.publication_state is not SourcePublicationState.PUBLISHED:
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        require_enum_member(self.access_class, SourceAccessClass, "access_class")
        require_enum_member(self.target_scope, MemoryTargetScope, "target_scope")
        owner = _hybrid_optional_text(self.owner_user_id, "owner_user_id", 255)
        personal = _hybrid_optional_text(
            self.personal_memory_space_id, "personal_memory_space_id", 255
        )
        if self.access_class is SourceAccessClass.USER_PRIVATE:
            if (
                owner is None
                or personal is None
                or self.target_scope is not MemoryTargetScope.USER_PERSONAL_HAT
            ):
                raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        elif (
            owner is not None
            or personal is not None
            or self.target_scope is not MemoryTargetScope.SHARED_KNOWLEDGE_HAT
        ):
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "personal_memory_space_id", personal)
        for value, name in (
            (self.scope_digest, "scope_digest"),
            (self.registry_digest, "registry_digest"),
            (self.artifact_digest, "artifact_digest"),
        ):
            require_sha256_hex(value, name)
        _hybrid_text(self.snapshot_id, "snapshot_id", 255)
        metadata = _hybrid_mapping(
            self.structured_metadata, "structured_metadata", 32 * 1024
        )
        redaction_state = metadata.get("redaction_state")
        if redaction_state not in {None, "NOT_REQUIRED", "VERIFIED"}:
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        if metadata.get("model_generated") is True:
            raise Step20BoundaryError(Step20ReasonCode.HYBRID_CANDIDATE_INVALID)
        object.__setattr__(self, "structured_metadata", metadata)
        object.__setattr__(
            self,
            "effective_scope",
            _hybrid_scope_tuple(self.effective_scope, "effective_scope"),
        )
        vector_values = (self.vector_model_digest, self.vector_embedding_bytes_sha256)
        if any((value is not None for value in vector_values)):
            if any((value is None for value in vector_values)):
                raise ContractValidationError("vector identity must be complete")
            require_sha256_hex(self.vector_model_digest, "vector_model_digest")
            require_sha256_hex(
                self.vector_embedding_bytes_sha256, "vector_embedding_bytes_sha256"
            )
            if self.vector_model_digest != load_approved_model_spec().model_digest:
                raise Step20BoundaryError(Step20ReasonCode.HYBRID_MODEL_MISMATCH)
        if not isinstance(self.contributions, (tuple, list)):
            raise ContractValidationError("contributions must be ordered")
        contributions = tuple(
            sorted(self.contributions, key=lambda item: modality_order(item.modality))
        )
        if not contributions or any(
            (not isinstance(item, ModalityContribution) for item in contributions)
        ):
            raise ContractValidationError("contributions must be typed and non-empty")
        if len({item.modality for item in contributions}) != len(contributions):
            raise ContractValidationError("candidate modalities must be unique")
        for contribution in contributions:
            verify_contribution_hash(contribution)
        has_vector = any(
            (item.modality is HybridModality.VECTOR for item in contributions)
        )
        if has_vector != (self.vector_model_digest is not None):
            raise ContractValidationError("vector contribution and identity must agree")
        object.__setattr__(self, "contributions", contributions)
        if (
            isinstance(self.match_class, bool)
            or not isinstance(self.match_class, int)
            or self.match_class != _hybrid_expected_match_class(contributions)
        ):
            raise ContractValidationError("match_class is invalid")
        expected_score = sum((item.fixed_point_contribution for item in contributions))
        if self.fused_score != expected_score:
            raise ContractValidationError("fused_score differs from contributions")
        reasons = _hybrid_reason_tuple(self.reason_codes)
        if reasons != _hybrid_expected_candidate_reasons(
            contributions, self.match_class
        ):
            raise ContractValidationError("candidate reason codes differ from policy")
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "modality_count", len(contributions))
        object.__setattr__(
            self,
            "candidate_hash",
            canonical_sha256(self, exclude_fields=("candidate_hash",)),
        )


@dataclass(frozen=True, slots=True)
class EvidenceExcerpt:
    text: str
    full_content_sha256: str
    start_byte: int
    end_byte: int
    utf8_byte_length: int
    excerpt_sha256: str
    truncated: bool

    def __post_init__(self) -> None:
        text = _hybrid_content(self.text, "excerpt text", MAX_EXCERPT_BYTES_PER_ITEM)
        payload = text.encode("utf-8")
        require_sha256_hex(self.full_content_sha256, "full_content_sha256")
        for value, name in (
            (self.start_byte, "start_byte"),
            (self.end_byte, "end_byte"),
            (self.utf8_byte_length, "utf8_byte_length"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be non-negative")
        if self.start_byte != 0 or self.end_byte != len(payload):
            raise ContractValidationError("excerpt offsets do not match UTF-8 bytes")
        if self.utf8_byte_length != len(payload):
            raise ContractValidationError("excerpt byte length is inconsistent")
        require_sha256_hex(self.excerpt_sha256, "excerpt_sha256")
        if hashlib.sha256(payload).hexdigest() != self.excerpt_sha256:
            raise ContractValidationError("excerpt_sha256 does not match excerpt")
        if not isinstance(self.truncated, bool):
            raise ContractValidationError("excerpt truncated must be boolean")
        if not self.truncated and self.excerpt_sha256 != self.full_content_sha256:
            raise ContractValidationError(
                "complete excerpt must match full content hash"
            )
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class EvidenceBundleItem:
    item_ordinal: int
    evidence_id: str
    identity: CandidateIdentity
    citation_reference: str
    excerpt: EvidenceExcerpt
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
    contributions: tuple[ModalityContribution, ...]
    match_class: int
    fused_score: int
    ranking_policy_id: str
    ranking_policy_version: str
    ranking_policy_digest: str
    item_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            isinstance(self.item_ordinal, bool)
            or not isinstance(self.item_ordinal, int)
            or self.item_ordinal < 1
        ):
            raise ContractValidationError("item_ordinal must be one-based")
        if not isinstance(self.identity, CandidateIdentity):
            raise ContractValidationError("identity must be CandidateIdentity")
        verify_candidate_identity_hash(self.identity)
        expected_evidence_id = evidence_id_for(self.identity)
        if self.evidence_id != expected_evidence_id:
            raise ContractValidationError("evidence_id differs from candidate identity")
        _hybrid_text(self.citation_reference, "citation_reference", 4096)
        if not isinstance(self.excerpt, EvidenceExcerpt):
            raise ContractValidationError("excerpt must be EvidenceExcerpt")
        if self.excerpt.full_content_sha256 != self.identity.content_sha256:
            raise ContractValidationError("excerpt and evidence identity differ")
        require_enum_member(
            self.authority_level, SourceAuthorityLevel, "authority_level"
        )
        if self.authority_level not in _hybrid_SUPPORTED_AUTHORITY:
            raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        object.__setattr__(
            self,
            "authority_basis",
            _hybrid_mapping(self.authority_basis, "authority_basis", 16 * 1024),
        )
        _hybrid_text(self.source_kind, "source_kind", 1024)
        _hybrid_text(self.source_reference, "source_reference", 2048)
        if self.citation_reference != citation_reference_for(
            self.identity, self.source_reference
        ):
            raise ContractValidationError("citation_reference differs from lineage")
        require_enum_member(
            self.publication_state, SourcePublicationState, "publication_state"
        )
        if self.publication_state is not SourcePublicationState.PUBLISHED:
            raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        require_enum_member(self.access_class, SourceAccessClass, "access_class")
        require_enum_member(self.target_scope, MemoryTargetScope, "target_scope")
        owner = _hybrid_optional_text(self.owner_user_id, "owner_user_id", 255)
        personal = _hybrid_optional_text(
            self.personal_memory_space_id, "personal_memory_space_id", 255
        )
        if self.access_class is SourceAccessClass.USER_PRIVATE:
            if (
                owner is None
                or personal is None
                or self.target_scope is not MemoryTargetScope.USER_PERSONAL_HAT
            ):
                raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        elif (
            owner is not None
            or personal is not None
            or self.target_scope is not MemoryTargetScope.SHARED_KNOWLEDGE_HAT
        ):
            raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        object.__setattr__(self, "owner_user_id", owner)
        object.__setattr__(self, "personal_memory_space_id", personal)
        for value, name in (
            (self.scope_digest, "scope_digest"),
            (self.registry_digest, "registry_digest"),
            (self.artifact_digest, "artifact_digest"),
        ):
            require_sha256_hex(value, name)
        _hybrid_text(self.snapshot_id, "snapshot_id", 255)
        metadata = _hybrid_mapping(
            self.structured_metadata, "structured_metadata", 32 * 1024
        )
        if metadata.get("redaction_state") not in {None, "NOT_REQUIRED", "VERIFIED"}:
            raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        if metadata.get("model_generated") is True:
            raise Step20BoundaryError(Step20ReasonCode.EVIDENCE_BUNDLE_INVALID)
        object.__setattr__(self, "structured_metadata", metadata)
        object.__setattr__(
            self,
            "effective_scope",
            _hybrid_scope_tuple(self.effective_scope, "effective_scope"),
        )
        if not isinstance(self.contributions, (tuple, list)):
            raise ContractValidationError("contributions must be ordered")
        contributions = tuple(
            sorted(self.contributions, key=lambda item: modality_order(item.modality))
        )
        if not contributions or any(
            (not isinstance(item, ModalityContribution) for item in contributions)
        ):
            raise ContractValidationError("contributions must be typed and non-empty")
        if len({item.modality for item in contributions}) != len(contributions):
            raise ContractValidationError("item modalities must be unique")
        for contribution in contributions:
            verify_contribution_hash(contribution)
        object.__setattr__(self, "contributions", contributions)
        if (
            isinstance(self.match_class, bool)
            or not isinstance(self.match_class, int)
            or self.match_class != _hybrid_expected_match_class(contributions)
        ):
            raise ContractValidationError("match_class is invalid")
        if self.fused_score != sum(
            (item.fixed_point_contribution for item in contributions)
        ):
            raise ContractValidationError("fused score is inconsistent")
        policy = load_ranking_policy()
        if (
            self.ranking_policy_id != policy.policy_id
            or self.ranking_policy_version != policy.policy_version
            or self.ranking_policy_digest != policy.policy_digest
        ):
            raise ContractValidationError("ranking policy identity is invalid")
        object.__setattr__(
            self, "item_hash", canonical_sha256(self, exclude_fields=("item_hash",))
        )


def evidence_id_for(identity: CandidateIdentity) -> str:
    if not isinstance(identity, CandidateIdentity):
        raise ContractValidationError("identity must be CandidateIdentity")
    return f"evidence:{identity.identity_hash}"


def citation_reference_for(identity: CandidateIdentity, source_reference: str) -> str:
    _hybrid_text(source_reference, "source_reference", 2048)
    return f"{source_reference}#source={identity.source_id};version={identity.knowledge_version_id};chunk={identity.chunk_id}"


def verify_candidate_identity_hash(value: CandidateIdentity) -> None:
    verify_canonical_hash(value, value.identity_hash, exclude_fields=("identity_hash",))


def verify_contribution_hash(value: ModalityContribution) -> None:
    verify_canonical_hash(
        value, value.contribution_hash, exclude_fields=("contribution_hash",)
    )


def verify_bundle_item_hash(value: EvidenceBundleItem) -> None:
    verify_canonical_hash(value, value.item_hash, exclude_fields=("item_hash",))
