"""Private, immutable candidate/proposal/slot bindings supplied by Core."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from runtime.core_admission import CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.enums import (
    ActorType,
    ApprovalDecision,
    ApprovalRequirement,
    MemoryContentKind,
    MemoryTargetScope,
    MemoryTrustClass,
    PatchState,
    ProposalOrigin,
    StorageClass,
)
from runtime.memory_patch.contracts.records import (
    MemoryPatchApproval,
    MemoryPatchCommit,
    MemoryPatchProposal,
    PersonalHatQuotaPolicy,
    _replace_memory_patch_lifecycle,
    validate_preference_content,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    ensure_utc,
    freeze_json,
    normalize_utc_timestamp,
    to_canonical_data,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import bounded_text, trusted_dimensions


def stamp(value: datetime | None):
    return None if value is None else normalize_utc_timestamp(ensure_utc(value, "time"))


def instant(value: str | None):
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    try:
        result = ensure_utc(
            datetime.fromisoformat(value.replace("Z", "+00:00")), "time"
        )
    except ValueError:
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST) from None
    if normalize_utc_timestamp(result) != value:
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    return result


def identifiers(value, *, maximum=32):
    if (
        not isinstance(value, (tuple, list))
        or len(value) > maximum
        or len(set(value)) != len(value)
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    for item in value:
        bounded_text(item)
    return tuple(sorted(value))


@dataclass(frozen=True, slots=True, repr=False)
class CandidateDraft:
    title: str
    summary: str
    body: object
    content_kind: MemoryContentKind
    hat_id: str
    model_binding_ids: tuple[str, ...]
    evidence_references: tuple[str, ...] = ()
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expires_at: datetime | None = None
    supersedes_patch_id: str | None = None
    content_digest: str = field(init=False)

    def __post_init__(self):
        bounded_text(self.title, 160)
        bounded_text(self.summary, 2048)
        bounded_text(self.hat_id)
        if type(self.content_kind) is not MemoryContentKind:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        body = freeze_json(self.body)
        if self.content_kind is MemoryContentKind.PREFERENCE:
            validate_preference_content(body)
            if not body or any(not isinstance(v, str) for v in body.values()):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            for value in body.values():
                bounded_text(value, 1024)
        else:
            bounded_text(body, 16384)
        object.__setattr__(self, "body", body)
        object.__setattr__(
            self, "model_binding_ids", identifiers(self.model_binding_ids)
        )
        object.__setattr__(
            self, "evidence_references", identifiers(self.evidence_references)
        )
        if not self.model_binding_ids:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for name in ("valid_from", "valid_until", "expires_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from > self.valid_until
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if self.supersedes_patch_id is not None:
            bounded_text(self.supersedes_patch_id)
        object.__setattr__(
            self,
            "content_digest",
            canonical_sha256(self, exclude_fields=("content_digest",)),
        )

    def private_data(self):
        return to_canonical_data(self)

    @classmethod
    def from_private(cls, data):
        keys = {
            "title",
            "summary",
            "body",
            "content_kind",
            "hat_id",
            "model_binding_ids",
            "evidence_references",
            "valid_from",
            "valid_until",
            "expires_at",
            "supersedes_patch_id",
            "content_digest",
        }
        if not isinstance(data, Mapping) or set(data) != keys:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        result = cls(
            data["title"],
            data["summary"],
            data["body"],
            MemoryContentKind(data["content_kind"]),
            data["hat_id"],
            tuple(data["model_binding_ids"]),
            tuple(data["evidence_references"]),
            instant(data["valid_from"]),
            instant(data["valid_until"]),
            instant(data["expires_at"]),
            data["supersedes_patch_id"],
        )
        if result.content_digest != data["content_digest"]:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        return result


@dataclass(frozen=True, slots=True, repr=False)
class SlotConfiguration:
    hat_id: str
    model_binding_ids: tuple[str, ...]
    quota: PersonalHatQuotaPolicy

    def __post_init__(self):
        bounded_text(self.hat_id)
        object.__setattr__(
            self, "model_binding_ids", identifiers(self.model_binding_ids)
        )
        if not self.model_binding_ids or type(self.quota) is not PersonalHatQuotaPolicy:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)


@dataclass(frozen=True, slots=True, repr=False)
class EvidenceBinding:
    scope: OwnerScope
    candidate_digest: str
    references: tuple[str, ...]
    witness_digest: str
    verification_status: str
    binding_digest: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope or self.verification_status not in {
            "VERIFIED",
            "OWNER_CONTEXT_ONLY",
        }:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        object.__setattr__(self, "references", identifiers(self.references))
        from runtime.memory_patch.contracts.serialization import require_sha256_hex

        for value in (self.candidate_digest, self.witness_digest):
            require_sha256_hex(value, "binding")
        object.__setattr__(
            self,
            "binding_digest",
            canonical_sha256(self, exclude_fields=("binding_digest",)),
        )


class PersonalEvidenceValidationPort(Protocol):
    def validate(
        self, principal: CorePrincipal, candidate: CandidateDraft
    ) -> EvidenceBinding:
        """Revalidate Core evidence, exact content, scope, time and conflicts."""
        ...


def new_proposal(
    scope: OwnerScope,
    patch_id: str,
    draft: CandidateDraft,
    origin: ProposalOrigin,
    at: datetime,
):
    trust = {
        MemoryContentKind.FACTUAL: MemoryTrustClass.PERSONAL_VERIFIED_PATCH,
        MemoryContentKind.MODEL_EXPERIENCE: MemoryTrustClass.MODEL_EXPERIENCE_HINT,
        MemoryContentKind.SESSION: MemoryTrustClass.SESSION_MEMORY,
    }.get(draft.content_kind, MemoryTrustClass.USER_ASSERTED_MEMORY)
    return MemoryPatchProposal(
        "1.0.0",
        patch_id,
        scope.tenant_id,
        scope.owner_id,
        MemoryTargetScope.USER_PERSONAL_HAT,
        None,
        scope.space_id,
        origin,
        draft.body,
        draft.evidence_references,
        trusted_dimensions(scope, draft.hat_id),
        draft.valid_from,
        draft.valid_until,
        trust,
        ApprovalRequirement.OWNER,
        PatchState.DETECTED,
        draft.content_kind,
        at,
    )


def proposal_from_record(record):
    value = record.payload
    draft = CandidateDraft.from_private(value["candidate"])
    result = new_proposal(
        record.scope,
        record.record_id,
        draft,
        ProposalOrigin(value["origin"]),
        instant(value["created_at"]),
    )
    # Source state is only reconstructed after the native row and audit checks.
    result = _replace_memory_patch_lifecycle(
        result, lifecycle_state=PatchState(value["state"])
    )
    if canonical_sha256(result) != canonical_sha256(value["proposal"]):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return result


def approval_from_record(record):
    payload = record.payload["source_approval"]
    result = MemoryPatchApproval(
        payload["schema_version"],
        payload["approval_id"],
        payload["proposal_id"],
        payload["proposal_content_hash"],
        payload["tenant_id"],
        payload["owner_user_id"],
        payload["personal_memory_space_id"],
        ApprovalDecision(payload["decision"]),
        ActorType(payload["approver_type"]),
        payload["approver_id"],
        payload["reason_code"],
        instant(payload["decided_at"]),
    )
    if canonical_sha256(result) != canonical_sha256(payload):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return result


def commit_from_record(record):
    payload = record.payload["source_commit"]
    result = MemoryPatchCommit(
        payload["schema_version"],
        payload["commit_id"],
        payload["proposal_id"],
        payload["proposal_content_hash"],
        payload["approval_id"],
        payload["approval_proof"],
        payload["committed_patch_id"],
        payload["tenant_id"],
        payload["owner_user_id"],
        payload["personal_memory_space_id"],
        ActorType(payload["actor_type"]),
        payload["actor_id"],
        StorageClass(payload["storage_class"]),
        instant(payload["committed_at"]),
    )
    if canonical_sha256(result) != canonical_sha256(payload):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    return result


def authorization_binding(record):
    p = record.payload
    return canonical_sha256(
        {
            "scope": record.scope,
            "patch_id": record.record_id,
            "candidate": p["candidate_digest"],
            "proposal": p["proposal"]["content_hash"],
            "slot_config_revision": p["slot_config_revision"],
            "hat_manifest_digest": p["hat_manifest_digest"],
            "evidence": p["evidence_binding"],
        }
    )


PATCH_KEYS = frozenset(
    {
        "schema_version",
        "state",
        "candidate",
        "candidate_digest",
        "origin",
        "actor_session_id",
        "producer_metadata_digest",
        "proposal",
        "slot_config_revision",
        "hat_manifest_digest",
        "evidence_binding",
        "validated_revision",
        "approval_id",
        "commit_id",
        "activation_id",
        "created_at",
        "updated_at",
        "logically_deleted",
    }
)


def validate_patch_record(record):
    record.verify()
    p = record.payload
    if (
        set(p) != PATCH_KEYS
        or p["schema_version"] != "memory-patch-private-v1"
        or type(p["logically_deleted"]) is not bool
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    draft = CandidateDraft.from_private(p["candidate"])
    if draft.content_digest != p["candidate_digest"] or instant(
        p["updated_at"]
    ) < instant(p["created_at"]):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    proposal_from_record(record)
    return draft
