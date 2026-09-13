from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from runtime.memory_patch.contracts.enums import (
    ActorType,
    EvidenceStatus,
    KnowledgeRoute,
    MemoryTrustClass,
)
from runtime.memory_patch.contracts.identities import MemoryOwnership, verify_ownership
from runtime.memory_patch.contracts.records import (
    EvidenceBundle,
    EvidenceItem,
    HatSecurityPolicy,
    build_audit_event,
    deduplicate_audit_events,
    verify_audit_chain,
    verify_evidence_bundle_hash,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_json,
    canonical_sha256,
)
from runtime.memory_patch.errors import (
    AuthorityViolation,
    ContractValidationError,
    IntegrityError,
    OwnershipViolation,
)


class DomainContractTests(unittest.TestCase):
    def setUp(self):
        self.stamp = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)

    def evidence(self, **changes):
        fields = dict(
            evidence_id="evidence-1",
            source_id="source-1",
            source_version_id="version-1",
            citation_reference="citation-1",
            content_hash="1" * 64,
            trust_class=MemoryTrustClass.CANONICAL_SOURCE_EVIDENCE,
            authority_rank=1,
            scope_dimensions=(),
            retrieved_at=self.stamp,
        )
        fields.update(changes)
        return EvidenceItem(**fields)

    def test_reviewed_canonical_literal_vectors(self):
        self.assertEqual(
            '{"route":"HAT_ENFORCE"}',
            canonical_json({"route": KnowledgeRoute.HAT_ENFORCE}),
        )
        self.assertEqual(
            '{"values":["a","m","z"]}', canonical_json({"values": {"z", "a", "m"}})
        )
        self.assertEqual('"2030-01-02T12:00:00.000000Z"', canonical_json(self.stamp))
        self.assertEqual(
            canonical_sha256({"a": 1, "b": 2}), canonical_sha256({"b": 2, "a": 1})
        )

    def test_invalid_canonical_inputs(self):
        for value in (
            float("nan"),
            float("inf"),
            {1: "bad"},
            datetime(2030, 1, 2),
            {"path": "/home/private/data"},
        ):
            with (
                self.subTest(type=type(value).__name__),
                self.assertRaises(ContractValidationError),
            ):
                canonical_json(value)

    def test_hash_exclusion_is_only_at_root(self):
        first = {"hash": "ignored", "nested": {"hash": "one"}}
        second = {"hash": "also ignored", "nested": {"hash": "two"}}
        self.assertNotEqual(
            canonical_sha256(first, exclude_fields=("hash",)),
            canonical_sha256(second, exclude_fields=("hash",)),
        )

    def test_closed_enums_and_constructor_fields(self):
        with self.assertRaises(ValueError):
            EvidenceStatus("INVENTED")
        with self.assertRaises(TypeError):
            self.evidence(extra_authority=True)
        with self.assertRaises(ContractValidationError):
            self.evidence(trust_class="CANONICAL_SOURCE_EVIDENCE")

    def test_memory_and_model_hint_never_evidence(self):
        for trust in (
            MemoryTrustClass.PERSONAL_VERIFIED_PATCH,
            MemoryTrustClass.MODEL_EXPERIENCE_HINT,
            MemoryTrustClass.USER_ASSERTED_MEMORY,
            MemoryTrustClass.SESSION_MEMORY,
        ):
            with (
                self.subTest(trust=trust.value),
                self.assertRaises(ContractValidationError),
            ):
                self.evidence(trust_class=trust)

    def test_immutable_evidence_metadata_and_validity(self):
        original = {"classification": ["fixture"]}
        item = self.evidence(metadata=original)
        original["classification"].append("changed")
        self.assertEqual(("fixture",), item.metadata["classification"])
        with self.assertRaises(ContractValidationError):
            self.evidence(
                valid_from=self.stamp, valid_until=self.stamp - timedelta(seconds=1)
            )

    def test_bundle_order_integrity_and_status_constraints(self):
        bundle = EvidenceBundle(
            "bundle-1",
            "run-1",
            "hat-1",
            EvidenceStatus.SUFFICIENT,
            (self.evidence(),),
            "policy-1",
            self.stamp,
        )
        verify_evidence_bundle_hash(bundle)
        object.__setattr__(bundle, "bundle_hash", "0" * 64)
        with self.assertRaises(IntegrityError):
            verify_evidence_bundle_hash(bundle)
        with self.assertRaises(ContractValidationError):
            EvidenceBundle(
                "bundle-1",
                "run-1",
                "hat-1",
                EvidenceStatus.SUFFICIENT,
                (),
                "policy-1",
                self.stamp,
            )

    def test_missing_and_wrong_owner_fail_closed(self):
        owner = MemoryOwnership("tenant-a", "owner-a", "space-a")
        for values in (
            {"tenant_id": None, "user_id": None},
            {
                "tenant_id": "tenant-b",
                "user_id": "owner-a",
                "personal_memory_space_id": "space-a",
            },
        ):
            with self.assertRaises(OwnershipViolation):
                verify_ownership(owner, **values)

    def test_hat_declares_no_executable_or_private_authority(self):
        with self.assertRaises(AuthorityViolation):
            HatSecurityPolicy(executable_user_code=True)
        with self.assertRaises(AuthorityViolation):
            HatSecurityPolicy(private_memory_access=True)

    def event(self, identity, previous=None):
        return build_audit_event(
            audit_event_id=identity,
            tenant_id="tenant-a",
            user_id="owner-a",
            kernel_run_id=None,
            event_type="DETECTED",
            sequence_number=0 if previous is None else previous.sequence_number + 1,
            previous_event=previous,
            resource_type="patch",
            resource_id="patch-1",
            state_before=None,
            state_after="DETECTED",
            actor_type=ActorType.USER,
            actor_id="owner-a",
            content_hashes={"content": "1" * 64},
            created_at=self.stamp,
            personal_memory_space_id="space-a",
        )

    def test_audit_chain_dedup_and_tamper(self):
        first = self.event("audit-1")
        second = self.event("audit-2", first)
        verify_audit_chain((first, second))
        self.assertEqual(
            (first, second), deduplicate_audit_events((second, first, first))
        )
        with self.assertRaises(IntegrityError):
            verify_audit_chain((first, first))
        object.__setattr__(second, "previous_event_hash", "0" * 64)
        with self.assertRaises(IntegrityError):
            verify_audit_chain((first, second))
