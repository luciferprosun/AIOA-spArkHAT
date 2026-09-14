"""Separate commit and activation, with durable receipts and Core publication."""

from __future__ import annotations

import secrets

from runtime.core_admission import Capability, CoreActor
from runtime.memory_patch.contracts.enums import (
    ActorType,
    ApprovalDecision,
    PatchState,
    StorageClass,
)
from runtime.memory_patch.contracts.records import (
    MemoryPatchCommit,
    verify_approval_binding,
    verify_commit_binding,
)
from runtime.memory_patch.contracts.serialization import to_canonical_data
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.persistence.ports import RecordKind, StoredRecord
from runtime.memory_patch.personal.contracts import (
    approval_from_record,
    authorization_binding,
    commit_from_record,
    proposal_from_record,
    stamp,
)
from runtime.memory_patch.personal.lifecycle import NativeMemoryLifecycle


def require_approval(lifecycle, tx, patch):
    approval = lifecycle.get(tx, RecordKind.APPROVAL, patch.payload["approval_id"])
    source = approval_from_record(approval)
    if (
        source.decision is not ApprovalDecision.APPROVE
        or approval.payload["authorization_binding"] != authorization_binding(patch)
        or approval.payload["state"] != PatchState.APPROVED.value
    ):
        raise MemoryPatchError(ErrorCode.CHALLENGE_DENIED)
    challenge = lifecycle.get(
        tx, RecordKind.CHALLENGE, approval.payload["challenge_id"]
    )
    if (
        challenge.payload_digest != approval.payload["challenge_digest"]
        or challenge.payload["state"] != "CONSUMED"
        or challenge.payload["decision"] != ApprovalDecision.APPROVE.value
        or challenge.payload["nonce_hash"] != approval.payload["nonce_hash"]
        or challenge.payload["actor_session_id"] != approval.payload["actor_session_id"]
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    verify_approval_binding(proposal_from_record(patch), source)
    lifecycle.require_published(tx, approval)
    return approval, source


def require_commit(lifecycle, tx, patch):
    approval, approved = require_approval(lifecycle, tx, patch)
    record = lifecycle.get(tx, RecordKind.RECEIPT, patch.payload["commit_id"])
    source = commit_from_record(record)
    if (
        record.payload["state"] != PatchState.COMMITTED.value
        or record.payload["patch_id"] != patch.record_id
        or record.payload["authorization_binding"] != authorization_binding(patch)
        or record.payload["approval_digest"] != approval.payload_digest
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    verify_commit_binding(proposal_from_record(patch), approved, source)
    lifecycle.require_published(tx, record)
    return record, source, approved


def require_active(lifecycle, tx, patch):
    if (
        patch.payload["state"] != PatchState.ACTIVE.value
        or patch.payload["logically_deleted"]
    ):
        raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
    lifecycle.require_current(tx, patch)
    commitment, source, approved = require_commit(lifecycle, tx, patch)
    activation = lifecycle.get(tx, RecordKind.RECEIPT, patch.payload["activation_id"])
    if (
        activation.payload["state"] != PatchState.ACTIVE.value
        or activation.payload["patch_id"] != patch.record_id
        or activation.payload["patch_revision"] != patch.revision
        or activation.payload["commit_digest"] != commitment.payload_digest
        or activation.payload["authorization_binding"] != authorization_binding(patch)
    ):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    lifecycle.require_published(tx, activation)
    return lifecycle.require_published(tx, patch)


class NativeCommit:
    def __init__(self, lifecycle: NativeMemoryLifecycle):
        self.lifecycle = lifecycle

    def commit(self, principal, patch_id, *, expected_revision, operation_key):
        self.lifecycle.core.require(principal, Capability.COMMIT)
        if principal.actor is not CoreActor.COMMIT_SERVICE:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        commit_id = "commit_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            patch = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if (
                patch.revision != expected_revision
                or patch.payload["state"] != PatchState.APPROVED.value
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            self.lifecycle.require_current(tx, patch)
            self.lifecycle.enforce_space_quota(tx)
            approval, approved = require_approval(self.lifecycle, tx, patch)
            if approval.payload["approved_patch_revision"] != patch.revision:
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
            source = MemoryPatchCommit(
                "1.0.0",
                commit_id,
                patch_id,
                patch.payload["proposal"]["content_hash"],
                approved.approval_id,
                approved.approval_proof,
                patch_id,
                principal.scope.tenant_id,
                principal.scope.owner_id,
                principal.scope.space_id,
                ActorType.COMMIT_SERVICE,
                principal.actor_session_id,
                StorageClass.CRDB_TRANSACTIONAL,
                at,
            )
            record = StoredRecord(
                RecordKind.RECEIPT,
                commit_id,
                principal.scope,
                1,
                {
                    "state": PatchState.COMMITTED.value,
                    "source_commit": to_canonical_data(source),
                    "patch_id": patch_id,
                    "patch_revision": patch.revision + 1,
                    "authorization_binding": authorization_binding(patch),
                    "approval_digest": approval.payload_digest,
                    "created_at": stamp(at),
                },
            )
            save(record)
            updated, proof = self.lifecycle.transition(
                tx,
                save,
                patch,
                PatchState.COMMITTED,
                at,
                updates={"commit_id": commit_id},
                approval=approved,
                commit=source,
            )
            return {
                "patch_id": patch_id,
                "revision": updated.revision,
                "state": PatchState.COMMITTED.value,
                "proof_id": proof,
                "commit_id": commit_id,
            }

        return self.lifecycle.operation(
            principal,
            Capability.COMMIT,
            operation_key,
            "memory_commit",
            {"patch_id": patch_id, "expected_revision": expected_revision},
            mutate,
        )

    def activate(self, principal, patch_id, *, expected_revision, operation_key):
        self.lifecycle.core.require(principal, Capability.ACTIVATE)
        if principal.actor is not CoreActor.COMMIT_SERVICE:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        activation_id = "activation_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            patch = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if (
                patch.revision != expected_revision
                or patch.payload["state"] != PatchState.COMMITTED.value
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            self.lifecycle.require_current(tx, patch)
            self.lifecycle.enforce_space_quota(tx, activate_id=patch_id)
            commitment, source, approved = require_commit(self.lifecycle, tx, patch)
            if commitment.payload["patch_revision"] != patch.revision:
                raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
            record = StoredRecord(
                RecordKind.RECEIPT,
                activation_id,
                principal.scope,
                1,
                {
                    "state": PatchState.ACTIVE.value,
                    "patch_id": patch_id,
                    "patch_revision": patch.revision + 1,
                    "authorization_binding": authorization_binding(patch),
                    "commit_digest": commitment.payload_digest,
                    "actor_session_id": principal.actor_session_id,
                    "created_at": stamp(at),
                },
            )
            save(record)
            updated, proof = self.lifecycle.transition(
                tx,
                save,
                patch,
                PatchState.ACTIVE,
                at,
                updates={"activation_id": activation_id},
                approval=approved,
                commit=source,
            )
            return {
                "patch_id": patch_id,
                "revision": updated.revision,
                "state": PatchState.ACTIVE.value,
                "proof_id": proof,
                "activation_id": activation_id,
            }

        return self.lifecycle.operation(
            principal,
            Capability.ACTIVATE,
            operation_key,
            "memory_activate",
            {"patch_id": patch_id, "expected_revision": expected_revision},
            mutate,
        )
