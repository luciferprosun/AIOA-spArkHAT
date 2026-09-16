"""Canonical correction instructions; HMAC integrity never grants approval."""

from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256, ensure_utc
from runtime.memory_patch.correction.claims import (
    ClaimEvidenceCandidateStatus,
    ClaimEvidenceRelation,
    NativeClaims,
    NativeDraft,
    extract_native_claims,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle
from runtime.memory_patch.retrieval.temporal import TemporalQueryMode

PACKET_HMAC_DOMAIN_ID = "MEMORY_PATCH_CORRECTION_PACKET_V1"


class CorrectionAction(str, Enum):
    RETAIN = "RETAIN"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"


@dataclass(frozen=True, slots=True, repr=False)
class RequiredCorrection:
    claim_id: str
    action: CorrectionAction
    original_text: str
    required_text: str | None
    evidence_item_hashes: tuple[str, ...]


@dataclass(frozen=True, slots=True, repr=False)
class NativeCorrectionPacket:
    scope: OwnerScope
    hat_id: str
    draft_hash: str
    bundle_hash: str
    analysis_hash: str
    corrections: tuple[RequiredCorrection, ...]
    prohibitions: tuple[str, ...]
    review_required: bool
    issued_at: datetime
    expires_at: datetime
    temporal_mode: TemporalQueryMode
    as_of: datetime | None
    schema_version: str = "memory-patch-correction-v1"
    packet_hash: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.scope) is not OwnerScope
            or type(self.corrections) is not tuple
            or len(self.corrections) > 128
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if self.schema_version != "memory-patch-correction-v1":
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        ensure_utc(self.issued_at, "issued_at")
        ensure_utc(self.expires_at, "expires_at")
        if (
            not self.issued_at
            < self.expires_at
            <= self.issued_at + timedelta(minutes=5)
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        object.__setattr__(
            self, "packet_hash", canonical_sha256(self, exclude_fields=("packet_hash",))
        )


@dataclass(frozen=True, slots=True, repr=False)
class PacketIntegrityReceipt:
    packet_hash: str
    key_id: str
    authenticator: str
    domain_id: str = PACKET_HMAC_DOMAIN_ID


class NativePacketIntegrity:
    """Core injects ephemeral key material explicitly; no secret resolution."""

    def __init__(
        self,
        core: CoreAdmission,
        claims: NativeClaims,
        *,
        key_id: str,
        key_material: bytes,
        clock=None,
    ):
        if (
            not isinstance(key_material, bytes)
            or len(key_material) < 32
            or not isinstance(key_id, str)
            or not 1 <= len(key_id) <= 128
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self.core, self.claims = core, claims
        self._key_id, self._key = key_id, bytes(key_material)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._uses = {}
        self._lock = threading.Lock()
        self._closed = False

    def __repr__(self):
        return "NativePacketIntegrity(<private>)"

    def _mac(self, digest):
        return hmac.new(
            self._key,
            PACKET_HMAC_DOMAIN_ID.encode("ascii") + b"\x00" + digest.encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def build(
        self,
        principal: CorePrincipal,
        draft: NativeDraft,
        bundle: FrozenEvidenceBundle,
        *,
        mode=TemporalQueryMode.CURRENT,
        as_of=None,
    ):
        if self._closed:
            raise MemoryPatchError(ErrorCode.MODULE_CLOSED)
        analysis = self.claims.assess(principal, draft, bundle, mode=mode, as_of=as_of)
        corrections = []
        prohibitions = []
        for value in analysis.assessments:
            supported = value.status is ClaimEvidenceCandidateStatus.SUPPORTED
            alternatives = sorted(
                {
                    link.exact_source_text
                    for link in value.links
                    if link.relation is ClaimEvidenceRelation.REFUTES
                }
            )
            action = (
                CorrectionAction.RETAIN
                if supported
                else CorrectionAction.REPLACE
                if len(alternatives) == 1
                else CorrectionAction.REMOVE
            )
            required = (
                value.claim.exact_claim_text
                if supported
                else alternatives[0]
                if action is CorrectionAction.REPLACE
                else None
            )
            refs = tuple(
                sorted(
                    {
                        link.item_hash
                        for link in value.links
                        if link.relation
                        in {
                            ClaimEvidenceRelation.SUPPORTS,
                            ClaimEvidenceRelation.REFUTES,
                        }
                    }
                )
            )
            corrections.append(
                RequiredCorrection(
                    value.claim.claim_id,
                    action,
                    value.claim.exact_claim_text,
                    required,
                    refs,
                )
            )
            if not supported:
                prohibitions.append(value.claim.exact_claim_text)
        now = ensure_utc(self.clock(), "trusted_now")
        packet = NativeCorrectionPacket(
            draft.scope,
            draft.hat_id,
            draft.draft_hash,
            bundle.bundle_hash,
            analysis.analysis_hash,
            tuple(corrections),
            tuple(sorted(set(prohibitions))),
            analysis.review_required,
            now,
            now + timedelta(minutes=5),
            mode,
            as_of,
        )
        return packet, PacketIntegrityReceipt(
            packet.packet_hash, self._key_id, self._mac(packet.packet_hash)
        )

    def verify(
        self,
        principal: CorePrincipal,
        packet: NativeCorrectionPacket,
        receipt: PacketIntegrityReceipt,
    ):
        self.core.require(principal, principal.capability, scope=packet.scope)
        if principal.capability not in {
            Capability.READ,
            Capability.VALIDATE,
            Capability.PROPOSE,
        }:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        now = ensure_utc(self.clock(), "trusted_now")
        if (
            self._closed
            or packet.hat_id not in principal.hat_ids
            or not packet.issued_at <= now < packet.expires_at
            or packet.packet_hash
            != canonical_sha256(packet, exclude_fields=("packet_hash",))
            or receipt.domain_id != PACKET_HMAC_DOMAIN_ID
            or receipt.packet_hash != packet.packet_hash
            or receipt.key_id != self._key_id
            or not hmac.compare_digest(
                receipt.authenticator, self._mac(packet.packet_hash)
            )
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)

    def build_required(self, principal, draft, bundle, correction):
        """Bind a Core-reviewed atomic correction to the existing signed packet.

        The normal lexical detector cannot propose every missing condition.
        This operation requires native support for the complete replacement.
        Its caller must separately apply its independent factual evidence policy;
        this receipt authenticates packet integrity, never truth or permission.
        """
        claims = extract_native_claims(draft)
        if (
            type(correction) is not RequiredCorrection
            or len(claims) != 1
            or correction.claim_id != claims[0].claim_id
            or correction.original_text != draft.text
            or correction.action is not CorrectionAction.REPLACE
            or not correction.required_text
            or not correction.evidence_item_hashes
            or not set(correction.evidence_item_hashes)
            <= {i.item_hash for i in bundle.items}
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        corrected = NativeDraft(
            draft.scope,
            draft.hat_id,
            draft.draft_id + "-corrected",
            correction.required_text,
        )
        supported = self.claims.assess(principal, corrected, bundle)
        if supported.review_required or len(supported.assessments) != 1:
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        base, _ = self.build(principal, draft, bundle)
        packet = replace(
            base,
            corrections=(correction,),
            prohibitions=(draft.text,),
            review_required=False,
            analysis_hash=canonical_sha256(
                (base.analysis_hash, supported.analysis_hash)
            ),
        )
        return packet, PacketIntegrityReceipt(
            packet.packet_hash, self._key_id, self._mac(packet.packet_hash)
        )

    def consume_attempt(
        self, principal, packet, receipt, *, operation_id: str, attempt: int
    ):
        self.verify(principal, packet, receipt)
        if (
            not isinstance(operation_id, str)
            or not 1 <= len(operation_id) <= 128
            or type(attempt) is not int
            or attempt not in (1, 2)
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        with self._lock:
            previous = self._uses.get(packet.packet_hash)
            if attempt == 1:
                if previous is not None:
                    raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
                if len(self._uses) >= 1024:
                    raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            elif previous != (operation_id, 1):
                raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
            self._uses[packet.packet_hash] = (operation_id, attempt)

    def close(self):
        self._closed = True
        self._key = b""
        with self._lock:
            self._uses.clear()
