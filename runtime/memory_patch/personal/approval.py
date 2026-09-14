"""One-use owner-human challenge bound to exact candidate, evidence and revision."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta

from runtime.core_admission import Capability, CoreActor
from runtime.memory_patch.contracts.enums import ActorType, ApprovalDecision, PatchState
from runtime.memory_patch.contracts.records import MemoryPatchApproval
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    to_canonical_data,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionContext,
)
from runtime.memory_patch.personal.contracts import (
    authorization_binding,
    instant,
    stamp,
)
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle


@dataclass(frozen=True, slots=True, repr=False)
class FreshOwnerChallenge:
    record: StoredRecord
    decision_nonce: str | None
    replayed: bool


def nonce_binding(challenge, nonce):
    if not isinstance(nonce, str) or not 32 <= len(nonce) <= 128:
        raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
    return hashlib.sha256(
        (
            "memory-patch-owner-decision-v1\x00"
            + canonical_sha256(
                {
                    "scope": challenge.scope,
                    "challenge_id": challenge.record_id,
                    "patch_id": challenge.payload["patch_id"],
                    "patch_revision": challenge.payload["patch_revision"],
                    "authorization_binding": challenge.payload["authorization_binding"],
                    "actor_session_id": challenge.payload["actor_session_id"],
                    "expires_at": challenge.payload["expires_at"],
                }
            )
            + "\x00"
            + nonce
        ).encode()
    ).hexdigest()


class NativeOwnerApproval:
    def __init__(self, lifecycle: NativeMemoryLifecycle):
        self.lifecycle = lifecycle

    def _owner(self, principal):
        self.lifecycle.core.require(principal, Capability.OWNER_APPROVAL)
        if principal.actor is not CoreActor.OWNER_HUMAN:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)

    def challenge(self, principal, patch_id, *, expected_revision, operation_key):
        self._owner(principal)
        challenge_id = "challenge_" + secrets.token_hex(16)
        nonce = secrets.token_urlsafe(32)

        def mutate(tx, save, at):
            patch = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if (
                patch.revision != expected_revision
                or patch.payload["state"] != PatchState.AWAITING_APPROVAL.value
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            self.lifecycle.require_current(tx, patch)
            open_challenges = tx.scan(
                RecordKind.CHALLENGE, limit=1024, states=("OPEN",)
            )
            if len(open_challenges) >= 1024:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            for previous in open_challenges:
                previous = self.lifecycle.get(
                    tx, RecordKind.CHALLENGE, previous.record_id
                )
                if previous.payload["patch_id"] == patch_id:
                    superseded = StoredRecord(
                        previous.kind,
                        previous.record_id,
                        previous.scope,
                        previous.revision + 1,
                        {
                            **previous.payload,
                            "state": "SUPERSEDED",
                            "decided_at": stamp(at),
                        },
                    )
                    save(superseded, previous)
            payload = {
                "state": "OPEN",
                "patch_id": patch_id,
                "patch_revision": patch.revision,
                "candidate_digest": patch.payload["candidate_digest"],
                "proposal_hash": patch.payload["proposal"]["content_hash"],
                "authorization_binding": authorization_binding(patch),
                "actor_session_id": principal.actor_session_id,
                "created_at": stamp(at),
                "expires_at": stamp(at + timedelta(minutes=5)),
                "nonce_hash": None,
                "decision": None,
                "decided_at": None,
            }
            provisional = StoredRecord(
                RecordKind.CHALLENGE, challenge_id, principal.scope, 1, payload
            )
            payload["nonce_hash"] = nonce_binding(provisional, nonce)
            record = StoredRecord(
                RecordKind.CHALLENGE, challenge_id, principal.scope, 1, payload
            )
            proof = save(record)
            return {
                "challenge_id": challenge_id,
                "patch_id": patch_id,
                "revision": patch.revision,
                "state": "OPEN",
                "proof_id": proof,
            }

        result = self.lifecycle.operation(
            principal,
            Capability.OWNER_APPROVAL,
            operation_key,
            "memory_owner_challenge",
            {"patch_id": patch_id, "expected_revision": expected_revision},
            mutate,
        )
        record = self.lifecycle.transactions.run(
            TransactionContext(principal, Capability.OWNER_APPROVAL),
            lambda tx: self.lifecycle.get(
                tx, RecordKind.CHALLENGE, result.outcome["challenge_id"]
            ),
        )
        # Raw nonce exists only on the protected first successful return. It is
        # absent from operation storage, readback, replay and uncertain outcomes.
        return FreshOwnerChallenge(
            record,
            None if result.replayed or record.payload["state"] != "OPEN" else nonce,
            result.replayed,
        )

    def decide(
        self,
        principal,
        challenge_id,
        *,
        expected_revision,
        decision: ApprovalDecision,
        decision_nonce,
        operation_key,
    ):
        self._owner(principal)
        if (
            type(decision) is not ApprovalDecision
            or not isinstance(decision_nonce, str)
            or not 32 <= len(decision_nonce) <= 128
        ):
            raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
        raw_digest = hashlib.sha256(decision_nonce.encode()).hexdigest()
        approval_id = "approval_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            challenge = self.lifecycle.get(tx, RecordKind.CHALLENGE, challenge_id)
            data = challenge.payload
            patch = self.lifecycle.get(tx, RecordKind.PATCH, data["patch_id"])
            if (
                data["state"] != "OPEN"
                or data["patch_revision"] != expected_revision
                or patch.revision != expected_revision
                or data["actor_session_id"] != principal.actor_session_id
                or patch.payload["state"] != PatchState.AWAITING_APPROVAL.value
                or data["authorization_binding"] != authorization_binding(patch)
                or not hmac.compare_digest(
                    data["nonce_hash"], nonce_binding(challenge, decision_nonce)
                )
            ):
                raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
            if at >= instant(data["expires_at"]):
                expired = StoredRecord(
                    challenge.kind,
                    challenge.record_id,
                    challenge.scope,
                    challenge.revision + 1,
                    {**data, "state": "EXPIRED", "decided_at": stamp(at)},
                )
                proof = save(expired, challenge)
                return {
                    "challenge_id": challenge_id,
                    "patch_id": patch.record_id,
                    "revision": patch.revision,
                    "state": "EXPIRED",
                    "proof_id": proof,
                }
            if at < instant(data["created_at"]):
                raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
            self.lifecycle.require_current(tx, patch)
            self.lifecycle.enforce_space_quota(tx)
            source = MemoryPatchApproval(
                "1.0.0",
                approval_id,
                patch.record_id,
                patch.payload["proposal"]["content_hash"],
                principal.scope.tenant_id,
                principal.scope.owner_id,
                principal.scope.space_id,
                decision,
                ActorType.USER,
                principal.scope.owner_id,
                "OWNER_" + decision.value,
                at,
            )
            target = (
                PatchState.APPROVED
                if decision is ApprovalDecision.APPROVE
                else PatchState.REJECTED
            )
            consumed = StoredRecord(
                challenge.kind,
                challenge.record_id,
                challenge.scope,
                challenge.revision + 1,
                {
                    **data,
                    "state": "CONSUMED",
                    "decision": decision.value,
                    "decided_at": stamp(at),
                },
            )
            save(consumed, challenge)
            approval = StoredRecord(
                RecordKind.APPROVAL,
                approval_id,
                principal.scope,
                1,
                {
                    "state": target.value,
                    "source_approval": to_canonical_data(source),
                    "authorization_binding": data["authorization_binding"],
                    "approved_patch_revision": patch.revision + 1,
                    "challenge_id": challenge_id,
                    "challenge_digest": consumed.payload_digest,
                    "nonce_hash": data["nonce_hash"],
                    "actor_session_id": principal.actor_session_id,
                    "created_at": stamp(at),
                },
            )
            save(approval)
            updated, proof = self.lifecycle.transition(
                tx,
                save,
                patch,
                target,
                at,
                updates={"approval_id": approval_id},
                approval=source,
            )
            return {
                "challenge_id": challenge_id,
                "patch_id": patch.record_id,
                "revision": updated.revision,
                "state": target.value,
                "decision": decision.value,
                "approval_id": approval_id,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.OWNER_APPROVAL,
            operation_key,
            "memory_owner_decision",
            {
                "challenge_id": challenge_id,
                "expected_revision": expected_revision,
                "decision": decision.value,
                "nonce_digest": raw_digest,
            },
            mutate,
        )
