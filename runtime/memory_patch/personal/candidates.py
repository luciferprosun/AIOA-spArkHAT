"""Core-admitted DETECTED candidates, with producer metadata kept private."""

from __future__ import annotations

import secrets

from runtime.core_admission import Capability, CoreActor
from runtime.memory_patch.contracts.enums import PatchState, ProposalOrigin
from runtime.memory_patch.contracts.serialization import (
    require_sha256_hex,
    to_canonical_data,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.memory_patch.personal.contracts import CandidateDraft, new_proposal, stamp
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle


class NativeCandidates:
    def __init__(self, lifecycle: NativeMemoryLifecycle):
        self.lifecycle = lifecycle

    def intake(
        self,
        principal,
        draft: CandidateDraft,
        *,
        operation_key: str,
        producer_metadata_digest: str | None = None,
    ):
        core = self.lifecycle.core
        core.require(principal, Capability.CANDIDATE)
        if type(draft) is not CandidateDraft:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if principal.actor not in {CoreActor.OWNER_HUMAN, CoreActor.CRITIC}:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        if principal.actor is CoreActor.CRITIC:
            require_sha256_hex(producer_metadata_digest, "producer metadata")
        elif producer_metadata_digest is not None:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        origin = (
            ProposalOrigin.CRITIC_PROMPT_LOOP
            if principal.actor is CoreActor.CRITIC
            else ProposalOrigin.USER_ENTRY
        )
        binding = {
            "candidate": draft.content_digest,
            "origin": origin.value,
            "producer_metadata_digest": producer_metadata_digest,
        }
        patch_id = "patch_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            space, hat = self.lifecycle.require_configuration(tx, draft)
            for record in tx.scan(RecordKind.PATCH, limit=1024):
                self.lifecycle.get(tx, RecordKind.PATCH, record.record_id)
                if (
                    record.payload["candidate_digest"] == draft.content_digest
                    and record.payload["origin"] == origin.value
                    and not record.payload["logically_deleted"]
                ):
                    return {
                        "patch_id": record.record_id,
                        "revision": record.revision,
                        "state": record.payload["state"],
                        "deduplicated": True,
                    }
            self.lifecycle.enforce_space_quota(tx, extra=draft)
            proposal = new_proposal(principal.scope, patch_id, draft, origin, at)
            record = StoredRecord(
                RecordKind.PATCH,
                patch_id,
                principal.scope,
                1,
                {
                    "schema_version": "memory-patch-private-v1",
                    "state": PatchState.DETECTED.value,
                    "candidate": draft.private_data(),
                    "candidate_digest": draft.content_digest,
                    "origin": origin.value,
                    "actor_session_id": principal.actor_session_id,
                    "producer_metadata_digest": producer_metadata_digest,
                    "proposal": to_canonical_data(proposal),
                    "slot_config_revision": space.payload["config_revision"],
                    "hat_manifest_digest": hat.manifest_digest,
                    "evidence_binding": None,
                    "validated_revision": None,
                    "approval_id": None,
                    "commit_id": None,
                    "activation_id": None,
                    "created_at": stamp(at),
                    "updated_at": stamp(at),
                    "logically_deleted": False,
                },
            )
            proof = save(record)
            return {
                "patch_id": patch_id,
                "revision": 1,
                "state": PatchState.DETECTED.value,
                "proof_id": proof,
                "deduplicated": False,
            }

        return self.lifecycle.operation(
            principal,
            Capability.CANDIDATE,
            operation_key,
            "memory_candidate",
            binding,
            mutate,
        )
