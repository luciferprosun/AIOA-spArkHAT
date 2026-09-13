"""Case-scoped human review, with no owner approval or publication side effect."""

from __future__ import annotations

import secrets
from datetime import timedelta
from enum import Enum

from runtime.core_admission import Capability, CoreActor
from runtime.evidence_admission import CoreEvidenceAdmission
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.memory_patch.personal.contracts import CandidateDraft, instant, stamp
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle


class ReviewDecision(str, Enum):
    ACCEPT_ADVISORY = "ACCEPT_ADVISORY"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class NativeReview:
    def __init__(
        self,
        lifecycle: NativeMemoryLifecycle,
        evidence: CoreEvidenceAdmission | None = None,
    ):
        self.lifecycle, self.evidence = lifecycle, evidence

    def _visible(self, principal, patch):
        candidate = CandidateDraft.from_private(patch.payload["candidate"])
        if candidate.hat_id not in principal.hat_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        for reference in candidate.evidence_references:
            if self.evidence is None:
                raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
            self.evidence.require_evidence(principal, reference)

    def open_case(self, principal, patch_id, *, expected_revision, operation_key):
        self.lifecycle.core.require(principal, Capability.MANAGE)
        case_id = "case_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            patch = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if (
                patch.revision != expected_revision
                or patch.payload["logically_deleted"]
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            self._visible(principal, patch)
            record = StoredRecord(
                RecordKind.REVIEW,
                case_id,
                principal.scope,
                1,
                {
                    "state": "OPEN",
                    "patch_id": patch_id,
                    "patch_revision": patch.revision,
                    "candidate_digest": patch.payload["candidate_digest"],
                    "bounded_summary": "Owner memory candidate requires review.",
                    "claim_actor_session_id": None,
                    "claim_expires_at": None,
                    "decision": None,
                    "created_at": stamp(at),
                    "updated_at": stamp(at),
                    "approval_authority": False,
                    "publication_authority": False,
                },
            )
            proof = save(record)
            return {
                "case_id": case_id,
                "state": "OPEN",
                "revision": 1,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_review_open",
            {"patch_id": patch_id, "expected_revision": expected_revision},
            mutate,
        )

    def _reviewer(self, principal):
        self.lifecycle.core.require(principal, Capability.REVIEW)
        if principal.actor is not CoreActor.HUMAN_REVIEWER:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)

    def queue(self, principal):
        self._reviewer(principal)

        def read(tx):
            records = tx.scan(RecordKind.REVIEW, limit=128)
            result = []
            for record in records:
                record = self.lifecycle.get(tx, RecordKind.REVIEW, record.record_id)
                patch = self.lifecycle.get(
                    tx, RecordKind.PATCH, record.payload["patch_id"]
                )
                self._visible(principal, patch)
                result.append(record)
            return tuple(result)

        return self.lifecycle.transactions.run(
            TransactionContext(principal, Capability.REVIEW), read
        )

    def claim(self, principal, case_id, *, expected_revision, operation_key):
        self._reviewer(principal)

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.REVIEW, case_id)
            patch = self.lifecycle.get(tx, RecordKind.PATCH, record.payload["patch_id"])
            self._visible(principal, patch)
            expired = record.payload["state"] == "CLAIMED" and at >= instant(
                record.payload["claim_expires_at"]
            )
            if record.revision != expected_revision or (
                record.payload["state"] != "OPEN" and not expired
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            if patch.revision != record.payload["patch_revision"]:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            updated = StoredRecord(
                record.kind,
                record.record_id,
                record.scope,
                record.revision + 1,
                {
                    **record.payload,
                    "state": "CLAIMED",
                    "claim_actor_session_id": principal.actor_session_id,
                    "claim_expires_at": stamp(at + timedelta(minutes=5)),
                    "updated_at": stamp(at),
                },
            )
            proof = save(updated, record)
            return {
                "case_id": case_id,
                "state": "CLAIMED",
                "revision": updated.revision,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.REVIEW,
            operation_key,
            "memory_review_claim",
            {"case_id": case_id, "expected_revision": expected_revision},
            mutate,
        )

    def decide(
        self,
        principal,
        case_id,
        *,
        expected_revision,
        decision: ReviewDecision,
        operation_key,
    ):
        self._reviewer(principal)
        if type(decision) is not ReviewDecision:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.REVIEW, case_id)
            p = record.payload
            patch = self.lifecycle.get(tx, RecordKind.PATCH, p["patch_id"])
            self._visible(principal, patch)
            if (
                record.revision != expected_revision
                or p["state"] != "CLAIMED"
                or p["claim_actor_session_id"] != principal.actor_session_id
                or at >= instant(p["claim_expires_at"])
                or patch.revision != p["patch_revision"]
                or patch.payload["candidate_digest"] != p["candidate_digest"]
            ):
                raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
            updated = StoredRecord(
                record.kind,
                record.record_id,
                record.scope,
                record.revision + 1,
                {
                    **p,
                    "state": "DECIDED",
                    "decision": decision.value,
                    "updated_at": stamp(at),
                },
            )
            proof = save(updated, record)
            return {
                "case_id": case_id,
                "state": "DECIDED",
                "revision": updated.revision,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.REVIEW,
            operation_key,
            "memory_review_decision",
            {
                "case_id": case_id,
                "expected_revision": expected_revision,
                "decision": decision.value,
            },
            mutate,
        )
