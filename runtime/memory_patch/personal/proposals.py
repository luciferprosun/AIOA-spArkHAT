"""Separate proposal, evidence binding, validation and awaiting-owner edges."""

from __future__ import annotations

from typing import Protocol

from runtime.core_admission import Capability, CorePrincipal
from runtime.memory_patch.contracts.enums import MemoryContentKind, PatchState
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    to_canonical_data,
)
from runtime.memory_patch.correction.claims import (
    ClaimEvidenceCandidateStatus,
    NativeClaims,
    NativeDraft,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.personal.contracts import CandidateDraft, EvidenceBinding
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle


class CoreBundleResolver(Protocol):
    def resolve(
        self, principal: CorePrincipal, references: tuple[str, ...]
    ) -> FrozenEvidenceBundle:
        """Read the exact approved bundle; never resolve a latest alias."""
        ...


class CorePersonalEvidence:
    def __init__(
        self, claims: NativeClaims, resolver: CoreBundleResolver | None = None
    ):
        self.claims, self.resolver = claims, resolver

    def validate(self, principal: CorePrincipal, candidate: CandidateDraft):
        self.claims.core.require(principal, principal.capability)
        if (
            candidate.hat_id not in principal.hat_ids
            or not set(candidate.model_binding_ids) <= principal.model_binding_ids
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if candidate.content_kind is not MemoryContentKind.FACTUAL:
            # These lanes are owner context even when they contain factual-looking text.
            return EvidenceBinding(
                principal.scope,
                candidate.content_digest,
                candidate.evidence_references,
                canonical_sha256(
                    {
                        "content_kind": candidate.content_kind.value,
                        "content": candidate.body,
                        "authority": "OWNER_CONTEXT_ONLY",
                    }
                ),
                "OWNER_CONTEXT_ONLY",
            )
        if not candidate.evidence_references or self.resolver is None:
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        bundle = self.resolver.resolve(principal, candidate.evidence_references)
        self.claims.retrieval.require_bundle(principal, bundle)
        if (
            tuple(sorted({value for _, value in bundle.core_evidence_bindings}))
            != candidate.evidence_references
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        # Commit and activation may revalidate, but cannot mint a validation role.
        # The deterministic verifier uses the same already authenticated scope.
        draft = NativeDraft(
            principal.scope,
            candidate.hat_id,
            "memory-candidate-" + candidate.content_digest[:32],
            candidate.body,
        )
        analysis = self.claims.assess_bound(principal, draft, bundle)
        if (
            analysis.review_required
            or not analysis.assessments
            or any(
                a.status is not ClaimEvidenceCandidateStatus.SUPPORTED
                for a in analysis.assessments
            )
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        return EvidenceBinding(
            principal.scope,
            candidate.content_digest,
            candidate.evidence_references,
            canonical_sha256(
                {"bundle": bundle.bundle_hash, "claims": analysis.analysis_hash}
            ),
            "VERIFIED",
        )


class NativeProposals:
    def __init__(self, lifecycle: NativeMemoryLifecycle):
        self.lifecycle = lifecycle

    def advance(
        self,
        principal,
        patch_id,
        *,
        expected_revision,
        operation_key,
        target: PatchState,
    ):
        capabilities = {
            PatchState.PROPOSED: Capability.PROPOSE,
            PatchState.EVIDENCE_BOUND: Capability.PROPOSE,
            PatchState.VALIDATED: Capability.VALIDATE,
            PatchState.AWAITING_APPROVAL: Capability.VALIDATE,
        }
        if target not in capabilities:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        capability = capabilities[target]

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if record.revision != expected_revision:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            candidate = CandidateDraft.from_private(record.payload["candidate"])
            self.lifecycle.require_configuration(tx, candidate, record)
            self.lifecycle.enforce_space_quota(tx)
            updates = {}
            if target is not PatchState.PROPOSED:
                _, binding = self.lifecycle.require_current(tx, record)
                updates["evidence_binding"] = to_canonical_data(binding)
            if target is PatchState.VALIDATED:
                updates["validated_revision"] = record.revision + 1
            if (
                target is PatchState.AWAITING_APPROVAL
                and record.payload["validated_revision"] != record.revision
            ):
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
            updated, proof = self.lifecycle.transition(
                tx, save, record, target, at, updates=updates
            )
            return {
                "patch_id": patch_id,
                "revision": updated.revision,
                "state": target.value,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            capability,
            operation_key,
            "memory_" + target.value.lower(),
            {
                "patch_id": patch_id,
                "expected_revision": expected_revision,
                "target": target.value,
            },
            mutate,
        )
