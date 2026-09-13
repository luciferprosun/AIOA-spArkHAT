"""Deterministic fact, date, source and citation checks with evidence ceilings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from runtime.core_admission import CorePrincipal
from runtime.memory_patch.correction.claims import (
    ClaimEvidenceCandidateStatus,
    ClaimEvidenceRelation,
    NativeClaims,
    NativeDraft,
    normalize_claim_for_match,
)
from runtime.memory_patch.correction.packets import (
    CorrectionAction,
    NativeCorrectionPacket,
    NativePacketIntegrity,
    PacketIntegrityReceipt,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle


class SemanticSignal(str, Enum):
    NOT_USED = "NOT_USED"
    SUPPORTS = "SUPPORTS"
    DISAGREES = "DISAGREES"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True, repr=False)
class CitationBinding:
    start_offset: int
    end_offset: int
    evidence_item_hash: str


@dataclass(frozen=True, slots=True, repr=False)
class CitedDraft:
    draft: NativeDraft
    citations: tuple[CitationBinding, ...]

    def __post_init__(self):
        if (
            type(self.draft) is not NativeDraft
            or type(self.citations) is not tuple
            or len(self.citations) > 256
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for citation in self.citations:
            if (
                type(citation) is not CitationBinding
                or type(citation.start_offset) is not int
                or type(citation.end_offset) is not int
                or not 0
                <= citation.start_offset
                < citation.end_offset
                <= len(self.draft.text)
            ):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if len(set(self.citations)) != len(self.citations):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)


@dataclass(frozen=True, slots=True, repr=False)
class LayeredVerification:
    verified: bool
    review_required: bool
    reason_codes: tuple[str, ...]
    draft_hash: str
    packet_hash: str
    bundle_hash: str
    citation_item_hashes: tuple[str, ...]


class NativeVerifier:
    def __init__(self, claims: NativeClaims, integrity: NativePacketIntegrity):
        self.claims, self.integrity = claims, integrity

    def verify(
        self,
        principal: CorePrincipal,
        value: CitedDraft,
        packet: NativeCorrectionPacket,
        receipt: PacketIntegrityReceipt,
        bundle: FrozenEvidenceBundle,
        *,
        semantic_signal=SemanticSignal.NOT_USED,
    ) -> LayeredVerification:
        self.integrity.verify(principal, packet, receipt)
        if type(semantic_signal) is not SemanticSignal:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if (
            bundle.bundle_hash != packet.bundle_hash
            or value.draft.scope != packet.scope
            or value.draft.hat_id != packet.hat_id
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        analysis = self.claims.assess(
            principal,
            value.draft,
            bundle,
            mode=packet.temporal_mode,
            as_of=packet.as_of,
        )
        reasons = set()
        if analysis.review_required:
            reasons.add("EVIDENCE_OR_TEMPORAL_CEILING")
        normalized = {
            normalize_claim_for_match(a.claim.exact_claim_text)
            for a in analysis.assessments
        }
        for correction in packet.corrections:
            if correction.action in {CorrectionAction.RETAIN, CorrectionAction.REPLACE}:
                if (
                    normalize_claim_for_match(correction.required_text)
                    not in normalized
                ):
                    reasons.add("REQUIRED_CORRECTION_MISSING")
        if any(
            normalize_claim_for_match(text) in normalized
            for text in packet.prohibitions
        ):
            reasons.add("PROHIBITED_CLAIM_PRESENT")
        spans = {
            (a.claim.start_offset, a.claim.end_offset): a for a in analysis.assessments
        }
        cited = set()
        for citation in value.citations:
            assessment = spans.get((citation.start_offset, citation.end_offset))
            if assessment is None:
                reasons.add("CITATION_SPAN_MISMATCH")
                continue
            if not any(
                link.item_hash == citation.evidence_item_hash
                and link.relation is ClaimEvidenceRelation.SUPPORTS
                for link in assessment.links
            ):
                reasons.add("CITATION_SOURCE_MISMATCH")
                continue
            cited.add((citation.start_offset, citation.end_offset))
        for span, assessment in spans.items():
            if assessment.status is not ClaimEvidenceCandidateStatus.SUPPORTED:
                reasons.add("CLAIM_UNVERIFIED")
            if span not in cited:
                reasons.add("CITATION_REQUIRED")
        if not spans:
            reasons.add("CLAIM_UNVERIFIED")
        # Model agreement cannot remove any deterministic failure.
        if semantic_signal in {SemanticSignal.DISAGREES, SemanticSignal.UNKNOWN}:
            reasons.add("SEMANTIC_REVIEW_REQUIRED")
        return LayeredVerification(
            not reasons,
            bool(reasons),
            tuple(sorted(reasons)),
            value.draft.draft_hash,
            packet.packet_hash,
            bundle.bundle_hash,
            tuple(sorted({c.evidence_item_hash for c in value.citations})),
        )
