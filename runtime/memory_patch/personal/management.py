"""Owner-only slot lifecycle, revocation, bounded export and sharing intent."""

from __future__ import annotations

import secrets

from runtime.core_admission import Capability, CoreActor
from runtime.memory_patch.contracts.enums import PatchState, PersonalMemorySpaceState
from runtime.memory_patch.contracts.records import (
    PersonalHatQuotaPolicy,
    PersonalMemorySpace,
    _replace_personal_memory_space,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
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
    CandidateDraft,
    SlotConfiguration,
    instant,
    stamp,
)
from runtime.memory_patch.personal.lifecycle import (
    NativeMemoryLifecycle,
    personal_memory_transition_allowed,
)


class NativeMemoryManagement:
    def __init__(self, lifecycle: NativeMemoryLifecycle):
        self.lifecycle = lifecycle

    def _owner(self, principal):
        self.lifecycle.core.require(principal, Capability.MANAGE)
        if principal.actor is not CoreActor.OWNER_HUMAN:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)

    def create_slot(self, principal, *, operation_key):
        self._owner(principal)
        public_space_id = "space_" + secrets.token_hex(16)
        public_slot_id = "slot_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            if tx.get(RecordKind.SPACE, "owner-memory-slot") is not None:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            space = PersonalMemorySpace(
                "1.0.0",
                principal.scope.space_id,
                principal.scope.tenant_id,
                principal.scope.owner_id,
                PersonalMemorySpaceState.EMPTY,
                None,
                at,
                at,
            )
            record = StoredRecord(
                RecordKind.SPACE,
                "owner-memory-slot",
                principal.scope,
                1,
                {
                    "schema_version": "memory-patch-slot-v1",
                    "state": "EMPTY",
                    "public_space_id": public_space_id,
                    "public_slot_id": public_slot_id,
                    "source_space": to_canonical_data(space),
                    "hat_id": None,
                    "model_binding_ids": (),
                    "config_revision": 0,
                    "hat_manifest_digest": None,
                    "quota": to_canonical_data(PersonalHatQuotaPolicy()),
                    "created_at": stamp(at),
                    "updated_at": stamp(at),
                },
            )
            proof = save(record)
            return {
                "space_id": public_space_id,
                "slot_id": public_slot_id,
                "revision": 1,
                "state": "EMPTY",
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_slot_create",
            {},
            mutate,
        )

    def configure_slot(
        self,
        principal,
        configuration: SlotConfiguration,
        *,
        expected_revision,
        operation_key,
    ):
        self._owner(principal)
        if type(configuration) is not SlotConfiguration:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        hat = self.lifecycle.scoped_hat(principal, configuration.hat_id)
        if not set(configuration.model_binding_ids) <= principal.model_binding_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        for name in configuration.quota.__dataclass_fields__:
            approved = getattr(hat.quota, name)
            requested = getattr(configuration.quota, name)
            if approved is not None and (requested is None or requested > approved):
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.SPACE, "owner-memory-slot")
            current = PersonalMemorySpaceState(record.payload["state"])
            if (
                record.revision != expected_revision
                or not personal_memory_transition_allowed(
                    current, PersonalMemorySpaceState.CONFIGURED
                )
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            source = self._source_space(record)
            updated_source = _replace_personal_memory_space(
                source,
                state=PersonalMemorySpaceState.CONFIGURED,
                display_name="Owner memory",
                model_binding_ids=configuration.model_binding_ids,
                updated_at=at,
            )
            updated = StoredRecord(
                record.kind,
                record.record_id,
                record.scope,
                record.revision + 1,
                {
                    **record.payload,
                    "state": "CONFIGURED",
                    "source_space": to_canonical_data(updated_source),
                    "hat_id": configuration.hat_id,
                    "model_binding_ids": configuration.model_binding_ids,
                    "config_revision": record.payload["config_revision"] + 1,
                    "hat_manifest_digest": hat.manifest_digest,
                    "quota": to_canonical_data(configuration.quota),
                    "updated_at": stamp(at),
                },
            )
            proof = save(updated, record)
            return {
                "space_id": updated.payload["public_space_id"],
                "revision": updated.revision,
                "state": "CONFIGURED",
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_slot_configure",
            {
                "configuration": to_canonical_data(configuration),
                "expected_revision": expected_revision,
            },
            mutate,
        )

    @staticmethod
    def _source_space(record):
        data = record.payload["source_space"]
        source = PersonalMemorySpace(
            "1.0.0",
            record.scope.space_id,
            record.scope.tenant_id,
            record.scope.owner_id,
            PersonalMemorySpaceState.EMPTY,
            None,
            instant(data["created_at"]),
            instant(data["created_at"]),
        )
        source = _replace_personal_memory_space(
            source,
            state=PersonalMemorySpaceState(data["state"]),
            display_name=data["display_name"],
            updated_at=instant(data["updated_at"]),
            model_binding_ids=tuple(data["model_binding_ids"]),
            export_requested_at=instant(data["export_requested_at"]),
            deletion_requested_at=instant(data["deletion_requested_at"]),
            deleted_at=instant(data["deleted_at"]),
        )
        if (
            canonical_sha256(source) != canonical_sha256(data)
            or source.state.value != record.payload["state"]
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        return source

    def change_slot_state(
        self,
        principal,
        *,
        target: PersonalMemorySpaceState,
        expected_revision,
        operation_key,
    ):
        self._owner(principal)
        if (
            type(target) is not PersonalMemorySpaceState
            or target is PersonalMemorySpaceState.CONFIGURED
        ):
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.SPACE, "owner-memory-slot")
            source = self._source_space(record)
            if (
                record.revision != expected_revision
                or not personal_memory_transition_allowed(source.state, target)
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            updates = {"state": target, "updated_at": at}
            if target is PersonalMemorySpaceState.ACTIVE:
                self.lifecycle.scoped_hat(principal, record.payload["hat_id"])
                if (
                    not set(record.payload["model_binding_ids"])
                    <= principal.model_binding_ids
                ):
                    raise MemoryPatchError(ErrorCode.OWNER_DENIED)
            if target is PersonalMemorySpaceState.DELETED_PENDING:
                updates["deletion_requested_at"] = at
                for patch in tx.scan(RecordKind.PATCH, limit=1024):
                    self.lifecycle.get(tx, RecordKind.PATCH, patch.record_id)
                    if patch.payload["state"] == PatchState.ACTIVE.value:
                        self.lifecycle.transition(
                            tx,
                            save,
                            patch,
                            PatchState.REVOKED,
                            at,
                            updates={"logically_deleted": True},
                        )
                    elif not patch.payload["logically_deleted"]:
                        updated = StoredRecord(
                            patch.kind,
                            patch.record_id,
                            patch.scope,
                            patch.revision + 1,
                            {
                                **patch.payload,
                                "logically_deleted": True,
                                "updated_at": stamp(at),
                            },
                        )
                        save(updated, patch)
            if target is PersonalMemorySpaceState.DELETED:
                updates["deleted_at"] = at
            updated_source = _replace_personal_memory_space(source, **updates)
            updated = StoredRecord(
                record.kind,
                record.record_id,
                record.scope,
                record.revision + 1,
                {
                    **record.payload,
                    "state": target.value,
                    "source_space": to_canonical_data(updated_source),
                    "updated_at": stamp(at),
                },
            )
            proof = save(updated, record)
            return {
                "space_id": record.payload["public_space_id"],
                "revision": updated.revision,
                "state": target.value,
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_slot_state",
            {"target": target.value, "expected_revision": expected_revision},
            mutate,
        )

    def revoke(self, principal, patch_id, *, expected_revision, operation_key):
        self._owner(principal)

        def mutate(tx, save, at):
            record = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if record.revision != expected_revision:
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            updated, proof = self.lifecycle.transition(
                tx, save, record, PatchState.REVOKED, at
            )
            return {
                "patch_id": patch_id,
                "revision": updated.revision,
                "state": updated.payload["state"],
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_revoke",
            {"patch_id": patch_id, "expected_revision": expected_revision},
            mutate,
        )

    def supersede(
        self, principal, old_patch_id, new_patch_id, *, expected_revision, operation_key
    ):
        self._owner(principal)
        from runtime.memory_patch.personal.commit import require_active

        def mutate(tx, save, at):
            old = self.lifecycle.get(tx, RecordKind.PATCH, old_patch_id)
            new = self.lifecycle.get(tx, RecordKind.PATCH, new_patch_id)
            if (
                old.revision != expected_revision
                or old.record_id == new.record_id
                or CandidateDraft.from_private(
                    new.payload["candidate"]
                ).supersedes_patch_id
                != old_patch_id
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            require_active(self.lifecycle, tx, new)
            updated, proof = self.lifecycle.transition(
                tx, save, old, PatchState.SUPERSEDED, at
            )
            return {
                "patch_id": old_patch_id,
                "revision": updated.revision,
                "state": "SUPERSEDED",
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_supersede",
            {
                "old_patch_id": old_patch_id,
                "new_patch_id": new_patch_id,
                "expected_revision": expected_revision,
            },
            mutate,
        )

    def export_snapshot(self, principal, *, operation_key):
        self._owner(principal)

        def read(tx):
            space = self.lifecycle.get(tx, RecordKind.SPACE, "owner-memory-slot")
            records = tx.scan(RecordKind.PATCH, limit=1024)
            if len(records) >= 1024:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            for record in records:
                self.lifecycle.get(tx, RecordKind.PATCH, record.record_id)
            # This private return must pass named public views at CLI/HTTP.
            result = (space, tuple(sorted(records, key=lambda r: r.record_id)))
            if len(canonical_json_bytes(result)) > 4 * 1024 * 1024:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            return result

        def fingerprint(result):
            space, records = result
            return canonical_sha256(
                {
                    "scope": space.scope,
                    "state": space.payload["state"],
                    "config_revision": space.payload["config_revision"],
                    "patches": records,
                }
            )

        def audit_export(tx, save, at):
            snapshot = read(tx)
            space = snapshot[0]
            source = self._source_space(space)
            source = _replace_personal_memory_space(
                source, export_requested_at=at, updated_at=at
            )
            updated = StoredRecord(
                space.kind,
                space.record_id,
                space.scope,
                space.revision + 1,
                {
                    **space.payload,
                    "source_space": to_canonical_data(source),
                    "updated_at": stamp(at),
                },
            )
            proof = save(updated, space)
            return {"snapshot_digest": fingerprint(snapshot), "proof_id": proof}

        outcome = self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_export",
            {},
            audit_export,
        )
        snapshot = self.lifecycle.transactions.run(
            TransactionContext(principal, Capability.MANAGE), read
        )
        if fingerprint(snapshot) != outcome.outcome["snapshot_digest"]:
            raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
        return snapshot

    def propose_sharing(
        self,
        principal,
        patch_id,
        *,
        expected_revision,
        consent: bool,
        deidentified_summary: str,
        operation_key,
    ):
        self._owner(principal)
        from runtime.memory_patch.retrieval.contracts import bounded_text

        if consent is not True:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        bounded_text(deidentified_summary, 1024)
        sharing_id = "sharing_" + secrets.token_hex(16)

        def mutate(tx, save, at):
            patch = self.lifecycle.get(tx, RecordKind.PATCH, patch_id)
            if (
                patch.revision != expected_revision
                or patch.payload["logically_deleted"]
            ):
                raise MemoryPatchError(ErrorCode.STATE_CONFLICT)
            record = StoredRecord(
                RecordKind.SHARING,
                sharing_id,
                principal.scope,
                1,
                {
                    "state": "DOMAIN_REVIEW_REQUIRED",
                    "patch_id": patch_id,
                    "patch_revision": patch.revision,
                    "candidate_digest": patch.payload["candidate_digest"],
                    "consent": True,
                    "consent_actor_session_id": principal.actor_session_id,
                    "deidentified_summary": deidentified_summary,
                    "deidentification_status": "PENDING_REVIEW",
                    "publication_authorized": False,
                    "created_at": stamp(at),
                },
            )
            proof = save(record)
            return {
                "case_id": sharing_id,
                "state": "DOMAIN_REVIEW_REQUIRED",
                "proof_id": proof,
            }

        return self.lifecycle.operation(
            principal,
            Capability.MANAGE,
            operation_key,
            "memory_sharing_proposal",
            {
                "patch_id": patch_id,
                "expected_revision": expected_revision,
                "consent": True,
                "summary_digest": canonical_sha256(deidentified_summary),
            },
            mutate,
        )
