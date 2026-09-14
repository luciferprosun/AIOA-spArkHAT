"""Private semantic parity against reviewed literals, separate from transport views."""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from runtime.memory_patch.contracts.enums import (
    ActorType,
    ApprovalDecision,
    PatchState,
    PersonalMemorySpaceState,
    StorageClass,
)
from runtime.memory_patch.contracts.records import (
    AuditEvent,
    HybridModality,
    MemoryPatchApproval,
    MemoryPatchCommit,
    modality_weight,
    verify_audit_chain,
)
from runtime.memory_patch.contracts.serialization import (
    approval_proof_hash,
    canonical_json,
    canonical_sha256,
)
from runtime.memory_patch.persistence.retry import RetryPolicy
from runtime.memory_patch.personal.contracts import instant
from runtime.memory_patch.personal.lifecycle import (
    memory_patch_transition_allowed,
    personal_memory_transition_allowed,
)
from runtime.memory_patch.retrieval.embeddings import (
    EmbeddingVector,
    load_approved_model_spec,
)

FIXTURE = Path(__file__).parent / "fixtures" / "memory_patch_semantic_v1.json"


class SourceSemanticParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_canonical_literal_bytes_and_root_only_exclusion(self):
        value = self.data["canonical"]
        self.assertEqual(value["expected"], canonical_json(value["input"]))
        self.assertEqual(
            value["expected"],
            canonical_json(
                {**value["input"], "content_hash": "ignored"},
                exclude_fields=("content_hash",),
            ),
        )
        changed = {**value["input"], "a": {"content_hash": "changed"}}
        self.assertNotEqual(canonical_sha256(value["input"]), canonical_sha256(changed))

    def approval(self):
        value = self.data["approval"]["binding"]
        return MemoryPatchApproval(
            "1.0.0",
            value["approval_id"],
            value["proposal_id"],
            value["proposal_hash"],
            value["tenant_id"],
            value["owner_user_id"],
            value["personal_memory_space_id"],
            ApprovalDecision(value["decision"]),
            ActorType(value["approver_type"]),
            value["approver_id"],
            value["reason_code"],
            instant(value["decided_at"]),
        )

    def test_approval_retains_every_private_binding_and_domain_separator(self):
        fixture = self.data["approval"]
        binding = fixture["binding"]
        record = self.approval()
        self.assertEqual(fixture["expected_proof"], record.approval_proof)
        self.assertEqual(fixture["expected_canonical"], canonical_json(binding))
        args = {
            k: v
            for k, v in binding.items()
            if k not in {"contract_type", "contract_version"}
        }
        args["decided_at"] = instant(args["decided_at"])
        self.assertEqual(fixture["expected_proof"], approval_proof_hash(**args))
        for field in (
            "approval_id",
            "proposal_id",
            "tenant_id",
            "owner_user_id",
            "personal_memory_space_id",
            "approver_id",
            "reason_code",
        ):
            self.assertNotEqual(
                record.approval_proof,
                replace(record, **{field: "changed-private-binding"}).approval_proof,
            )
        self.assertNotEqual(
            record.approval_proof,
            replace(record, decision=ApprovalDecision.REJECT).approval_proof,
        )

    def test_commit_exact_receipt_hash_is_separate_from_approval(self):
        fixture = self.data["commit"]
        fields = fixture["fields"]
        commit = MemoryPatchCommit(
            **{
                **fields,
                "committed_at": instant(fields["committed_at"]),
                "actor_type": ActorType(fields["actor_type"]),
                "storage_class": StorageClass(fields["storage_class"]),
            }
        )
        self.assertEqual(fixture["expected_hash"], commit.commit_hash)
        self.assertEqual(
            fixture["expected_canonical"],
            canonical_json(commit, exclude_fields=("commit_hash",)),
        )
        self.assertEqual(self.approval().approval_proof, commit.approval_proof)
        self.assertNotEqual(commit.commit_hash, commit.approval_proof)
        self.assertNotEqual(
            commit.commit_hash,
            replace(commit, owner_user_id="changed-private-owner").commit_hash,
        )

    def test_fixed_audit_chain_bytes_identity_and_previous_hash(self):
        records = []
        for fixture in self.data["audit"]:
            fields = fixture["fields"]
            record = AuditEvent(
                **{
                    **fields,
                    "created_at": instant(fields["created_at"]),
                    "actor_type": ActorType(fields["actor_type"]),
                }
            )
            self.assertEqual(fixture["expected_hash"], record.event_hash)
            self.assertEqual(
                fixture["expected_canonical"],
                canonical_json(record, exclude_fields=("event_hash",)),
            )
            records.append(record)
        verify_audit_chain(tuple(records))
        self.assertEqual(records[0].event_hash, records[1].previous_event_hash)
        self.assertNotEqual(
            records[0].event_hash,
            replace(records[0], user_id="changed-private-owner").event_hash,
        )

    def test_every_patch_and_slot_edge_matches_accepted_source_graph(self):
        for current in PatchState:
            for target in PatchState:
                self.assertEqual(
                    target.value in self.data["patch_edges"][current.value],
                    memory_patch_transition_allowed(current, target),
                    (current.value, target.value),
                )
        for current in PersonalMemorySpaceState:
            for target in PersonalMemorySpaceState:
                self.assertEqual(
                    target.value in self.data["space_edges"][current.value],
                    personal_memory_transition_allowed(current, target),
                    (current.value, target.value),
                )

    def test_fixed_float32_bytes_model_identity_and_integer_rrf(self):
        fixture = self.data["vector"]
        vector = EmbeddingVector(
            tuple(fixture["first_two"]) + (0,) * fixture["remaining_zeroes"]
        )
        self.assertEqual(fixture["dimension"] * 4, len(vector.float32_bytes))
        self.assertEqual(fixture["expected_float32_sha256"], vector.bytes_sha256)
        self.assertEqual(
            fixture["model_digest"], load_approved_model_spec().model_digest
        )
        for name, values in self.data["rrf"].items():
            weight = modality_weight(HybridModality(name))
            self.assertEqual(values["weight"], weight)
            self.assertEqual(values["rank_1"], 10**9 * weight // 61)
            self.assertEqual(values["rank_5"], 10**9 * weight // 65)

    def test_retry_exact_bound_and_backoff_are_not_statement_retries(self):
        policy = RetryPolicy()
        self.assertEqual(self.data["retry"]["attempts"], policy.max_attempts)
        self.assertEqual(
            self.data["retry"]["backoff_seconds_before_retries_2_through_10"],
            [policy.backoff_seconds(i) for i in range(1, 10)],
        )
        from runtime.memory_patch.errors import PersistenceConfigurationError

        self.assertEqual("RAISE_WITHOUT_SLEEP", self.data["retry"]["after_attempt_10"])
        with self.assertRaises(PersistenceConfigurationError):
            policy.backoff_seconds(10)

    def test_private_live_lifecycle_receipts_replay_and_audit_match_independent_rules(
        self,
    ):
        from test_memory_patch_lifecycle import MemoryFixture

        from runtime.core_admission import Capability
        from runtime.memory_patch.persistence.ports import RecordKind

        fixture = MemoryFixture()
        self.addCleanup(fixture.close)
        patch_id = fixture.activate()
        original = fixture.read(patch_id)
        self.assertEqual("ACTIVE", original.payload["state"])
        self.assertEqual(8, original.revision)
        self.assertEqual(1, len(fixture.rows(RecordKind.APPROVAL)))
        self.assertEqual(2, len(fixture.rows(RecordKind.RECEIPT)))
        approval = fixture.rows(RecordKind.APPROVAL)[0]
        self.assertEqual(fixture.core._session, approval.payload["actor_session_id"])
        self.assertTrue(approval.payload["nonce_hash"])
        self.assertEqual(
            original.payload["proposal"]["content_hash"],
            approval.payload["source_approval"]["proposal_content_hash"],
        )
        before = tuple(
            (record.record_id, record.payload_digest)
            for record in fixture.rows(RecordKind.AUDIT)
        )
        fixture.commit.activate(
            fixture.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key="patch-activate",
        )
        after = tuple(
            (record.record_id, record.payload_digest)
            for record in fixture.rows(RecordKind.AUDIT)
        )
        self.assertEqual(before, after)
        self.assertEqual(original.payload_digest, fixture.read(patch_id).payload_digest)
