"""ACTIVE owner-private context, never canonical evidence or executable intent."""

from __future__ import annotations

from dataclasses import dataclass

from runtime.core_admission import Capability
from runtime.evidence_admission import EvidenceAdmissionError
from runtime.memory_patch.contracts.enums import (
    MemoryContentKind,
    PersonalMemorySpaceState,
)
from runtime.memory_patch.correction.claims import (
    ClaimEvidenceRelation,
    NativeClaims,
    NativeDraft,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, TransactionContext
from runtime.memory_patch.personal.commit import require_active
from runtime.memory_patch.personal.contracts import CandidateDraft
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle


@dataclass(frozen=True, slots=True, repr=False)
class OwnerMemoryContext:
    patch_id: str
    revision: int
    content: object
    content_kind: str
    trust_class: str
    canonical_evidence: bool = False
    execution_authority: bool = False


class NativeMemoryRetrieval:
    def __init__(
        self, lifecycle: NativeMemoryLifecycle, claims: NativeClaims | None = None
    ):
        self.lifecycle, self.claims = lifecycle, claims

    def retrieve(self, principal, *, hat_id, at, canonical_bundle, limit=128, max_scan_records=1023):
        self.lifecycle.core.require(principal, Capability.READ)
        if (
            hat_id not in principal.hat_ids
            or type(limit) is not int
            or not 1 <= limit <= 128
            or type(max_scan_records) is not int
            or not 1 <= max_scan_records <= 1023
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if self.claims is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        self.claims.retrieval.require_bundle(principal, canonical_bundle)
        if canonical_bundle.hat_scope_id != hat_id:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)

        def read(tx):
            space = self.lifecycle.get(tx, RecordKind.SPACE, "owner-memory-slot")
            if space.payload["state"] != PersonalMemorySpaceState.ACTIVE.value:
                return ()
            records = tx.scan(RecordKind.PATCH, limit=max_scan_records + 1, states=("ACTIVE",))
            if len(records) > max_scan_records:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            result = []
            for record in sorted(
                records, key=lambda item: (item.payload["created_at"], item.record_id)
            ):
                record = self.lifecycle.get(tx, RecordKind.PATCH, record.record_id)
                candidate = CandidateDraft.from_private(record.payload["candidate"])
                if candidate.hat_id != hat_id or record.payload["logically_deleted"]:
                    continue
                try:
                    # Uses the lifecycle's trusted current clock; a caller's `at`
                    # value cannot revive an expired or revoked memory.
                    require_active(self.lifecycle, tx, record)
                    if (
                        candidate.content_kind is MemoryContentKind.FACTUAL
                        and canonical_bundle.items
                    ):
                        analysis = self.claims.assess_bound(
                            principal,
                            NativeDraft(
                                principal.scope,
                                hat_id,
                                "memory-conflict-check",
                                candidate.body,
                            ),
                            canonical_bundle,
                        )
                        if any(
                            link.relation is ClaimEvidenceRelation.REFUTES
                            for a in analysis.assessments
                            for link in a.links
                        ):
                            continue
                        if analysis.review_required and any(
                            a.links for a in analysis.assessments
                        ):
                            continue
                except EvidenceAdmissionError:
                    continue
                except MemoryPatchError as error:
                    if error.code in {
                        ErrorCode.STATE_CONFLICT,
                        ErrorCode.EVIDENCE_DENIED,
                        ErrorCode.PROVENANCE_PENDING,
                    }:
                        continue
                    raise
                result.append(
                    OwnerMemoryContext(
                        record.record_id,
                        record.revision,
                        candidate.body,
                        candidate.content_kind.value,
                        record.payload["proposal"]["requested_trust_class"],
                    )
                )
            return tuple(result[:limit])

        return self.lifecycle.transactions.run(
            TransactionContext(principal, Capability.READ), read
        )
