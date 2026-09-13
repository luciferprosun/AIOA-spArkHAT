from __future__ import annotations

import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from test_memory_patch_persistence_ports import NOW, FakeFactory, make_admission
from test_memory_patch_retrieval import RetrievalFixture

from runtime.core_admission import AdmissionError, Capability
from runtime.evidence_admission import CoreEvidenceAdmission, EvidenceAdmissionError
from runtime.memory_patch.audit import CoreLedgerPublication
from runtime.memory_patch.contracts.enums import (
    ApprovalDecision,
    MemoryContentKind,
    PatchState,
    PersonalMemorySpaceState,
)
from runtime.memory_patch.contracts.records import (
    HatManifest,
    HatSecurityPolicy,
    PersonalHatQuotaPolicy,
)
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.correction.claims import NativeClaims
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.hats import NativeHatAdmission
from runtime.memory_patch.persistence.ports import (
    RecordKind,
    StoredRecord,
    TransactionRunner,
)
from runtime.memory_patch.personal.approval import NativeOwnerApproval
from runtime.memory_patch.personal.candidates import NativeCandidates
from runtime.memory_patch.personal.commit import NativeCommit
from runtime.memory_patch.personal.contracts import CandidateDraft, SlotConfiguration
from runtime.memory_patch.personal.lifecycle import (
    NativeMemoryLifecycle,
    memory_patch_transition_allowed,
)
from runtime.memory_patch.personal.management import NativeMemoryManagement
from runtime.memory_patch.personal.proposals import (
    CorePersonalEvidence,
    NativeProposals,
)
from runtime.memory_patch.personal.retrieval import NativeMemoryRetrieval
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.tools.provenance import AppendOnlyProvenanceStore


def memory_hat_manifest():
    return HatManifest(
        "1.0.0",
        "test-hat",
        "1.0.0",
        "Reviewed fixture",
        ("fixture",),
        "1",
        ("en",),
        (),
        ("deterministic-retrieval",),
        {},
        {},
        {},
        {},
        {},
        HatSecurityPolicy(),
        {},
    )


class MemoryFixture:
    def __init__(self, *, quota=None, factory=None):
        self.rf = RetrievalFixture()
        self.core = self.rf.core
        self.now = NOW
        self.source = self.rf.candidate(content="The reviewed policy applies.")
        self.bundle = self.rf.bundle([self.source])
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        (root / "provenance").mkdir(mode=0o700)
        self.store = AppendOnlyProvenanceStore(root, clock=lambda: self.now)
        self.factory = factory or FakeFactory()
        self.quota = quota or PersonalHatQuotaPolicy(
            maximum_total_spaces=1,
            maximum_active_spaces=1,
            maximum_active_memory_patches=10,
            maximum_bytes=262144,
            maximum_personal_sources=32,
        )
        self.selection = SimpleNamespace(
            active_hat=lambda: SimpleNamespace(name="test-hat")
        )
        self.bind_services(initialize=True)
        manager = self.p(Capability.MANAGE)
        self.management.create_slot(manager, operation_key="slot-create")
        self.management.configure_slot(
            manager,
            SlotConfiguration("test-hat", ("test-model",), self.quota),
            expected_revision=1,
            operation_key="slot-configure",
        )
        self.management.change_slot_state(
            manager,
            target=PersonalMemorySpaceState.ACTIVE,
            expected_revision=2,
            operation_key="slot-active",
        )

    def p(self, cap):
        return self.core.local_operator(cap)

    def bind_services(self, *, initialize=False):
        self.runner = TransactionRunner(
            self.core, self.factory, sleep=lambda delay: None
        )
        self.publisher = CoreLedgerPublication(self.core, self.store)
        if initialize:
            self.publisher.initialize(self.p(Capability.MANAGE))
        self.hats = NativeHatAdmission(
            self.core, self.selection, (memory_hat_manifest(),), quota=self.quota
        )
        claims = NativeClaims(self.core, self.rf.service)
        fixture = self

        class Resolver:
            def resolve(self, principal, references):
                if set(references) != {
                    value for _, value in fixture.bundle.core_evidence_bindings
                }:
                    raise MemoryPatchError(
                        __import__(
                            "runtime.memory_patch.errors", fromlist=["ErrorCode"]
                        ).ErrorCode.EVIDENCE_DENIED
                    )
                return fixture.bundle

        self.evidence = CorePersonalEvidence(claims, Resolver())
        self.lifecycle = NativeMemoryLifecycle(
            self.core,
            self.runner,
            hats=self.hats,
            evidence=self.evidence,
            publication=self.publisher,
            clock=lambda: self.now,
        )
        self.candidates = NativeCandidates(self.lifecycle)
        self.proposals = NativeProposals(self.lifecycle)
        self.approval = NativeOwnerApproval(self.lifecycle)
        self.commit = NativeCommit(self.lifecycle)
        self.management = NativeMemoryManagement(self.lifecycle)
        self.retrieval = NativeMemoryRetrieval(self.lifecycle, claims)

    def restart(self):
        self.core = make_admission()
        self.rf.core = self.core
        self.rf.reader = self.p(Capability.READ)
        self.rf.capture_actor = self.p(Capability.EVIDENCE_CAPTURE)
        self.rf.evidence = CoreEvidenceAdmission(
            self.core, self.rf.catalog, clock=lambda: NOW
        )
        self.rf.service = NativeRetrieval(
            self.core,
            self.rf.evidence,
            self.rf.sources,
            freshness=self.rf.service.freshness,
            clock=lambda: NOW,
        )
        self.factory = FakeFactory(state=self.factory.state)
        self.bind_services()

    def close(self):
        self.directory.cleanup()

    def publish(self):
        return self.lifecycle.publish_pending(self.p(Capability.MANAGE))

    def read(self, patch_id):
        return self.lifecycle.read(self.p(Capability.READ), patch_id)

    def rows(self, kind):
        return [r for r in self.factory.state.values() if r.kind is kind]

    def draft(self, **changes):
        value = CandidateDraft(
            "Reviewed memory",
            "Owner-private reviewed context.",
            "The reviewed policy applies.",
            MemoryContentKind.FACTUAL,
            "test-hat",
            ("test-model",),
            tuple(sorted({v for _, v in self.bundle.core_evidence_bindings})),
        )
        return replace(value, **changes)

    def detect(self, draft=None, key="candidate"):
        return self.candidates.intake(
            self.p(Capability.CANDIDATE), draft or self.draft(), operation_key=key
        ).outcome["patch_id"]

    def prepare(self, draft=None, key="patch"):
        patch_id = self.detect(draft, key + "-detect")
        for target, cap in [
            (PatchState.PROPOSED, Capability.PROPOSE),
            (PatchState.EVIDENCE_BOUND, Capability.PROPOSE),
            (PatchState.VALIDATED, Capability.VALIDATE),
            (PatchState.AWAITING_APPROVAL, Capability.VALIDATE),
        ]:
            self.proposals.advance(
                self.p(cap),
                patch_id,
                expected_revision=self.read(patch_id).revision,
                operation_key=key + "-" + target.value,
                target=target,
            )
        return patch_id

    def approve(self, patch_id, key="patch", decision=ApprovalDecision.APPROVE):
        revision = self.read(patch_id).revision
        challenge = self.approval.challenge(
            self.p(Capability.OWNER_APPROVAL),
            patch_id,
            expected_revision=revision,
            operation_key=key + "-challenge",
        )
        result = self.approval.decide(
            self.p(Capability.OWNER_APPROVAL),
            challenge.record.record_id,
            expected_revision=revision,
            decision=decision,
            decision_nonce=challenge.decision_nonce,
            operation_key=key + "-decision",
        )
        return challenge, result

    def activate(self, draft=None, key="patch"):
        patch_id = self.prepare(draft, key)
        self.approve(patch_id, key)
        self.publish()
        self.commit.commit(
            self.p(Capability.COMMIT),
            patch_id,
            expected_revision=6,
            operation_key=key + "-commit",
        )
        self.publish()
        self.commit.activate(
            self.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key=key + "-activate",
        )
        self.publish()
        return patch_id

    def retrieve(self, bundle=None, **kwargs):
        return self.retrieval.retrieve(
            self.p(Capability.READ),
            hat_id="test-hat",
            at=self.now,
            canonical_bundle=bundle or self.bundle,
            **kwargs,
        )


class LifecycleTests(unittest.TestCase):
    def test_lost_challenge_is_superseded_by_fresh_issue(self):
        fx = self.fx
        patch = fx.prepare()
        first = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch,
            expected_revision=5,
            operation_key="lost",
        )
        second = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch,
            expected_revision=5,
            operation_key="replacement",
        )
        self.assertNotEqual(first.decision_nonce, second.decision_nonce)
        with self.assertRaises(MemoryPatchError):
            fx.approval.decide(
                fx.p(Capability.OWNER_APPROVAL),
                first.record.record_id,
                expected_revision=5,
                decision=ApprovalDecision.APPROVE,
                decision_nonce=first.decision_nonce,
                operation_key="old-nonce",
            )
        first_row = next(
            r
            for r in fx.rows(RecordKind.CHALLENGE)
            if r.record_id == first.record.record_id
        )
        self.assertEqual("SUPERSEDED", first_row.payload["state"])
        fx.approval.decide(
            fx.p(Capability.OWNER_APPROVAL),
            second.record.record_id,
            expected_revision=5,
            decision=ApprovalDecision.APPROVE,
            decision_nonce=second.decision_nonce,
            operation_key="new-nonce",
        )
        self.assertEqual(1, len(fx.rows(RecordKind.APPROVAL)))

    def setUp(self):
        self.fx = MemoryFixture()
        self.addCleanup(self.fx.close)

    def test_all_source_edges_and_illegal_pairs(self):
        edges = set(zip(list(PatchState)[:8], list(PatchState)[1:8])) | {
            (PatchState.AWAITING_APPROVAL, PatchState.REJECTED),
            (PatchState.ACTIVE, PatchState.SUPERSEDED),
            (PatchState.ACTIVE, PatchState.REVOKED),
        }
        for current in PatchState:
            for target in PatchState:
                self.assertEqual(
                    (current, target) in edges,
                    memory_patch_transition_allowed(current, target),
                )

    def test_full_separate_lifecycle_receipts_and_core_publication(self):
        fx = self.fx
        patch_id = fx.prepare()
        self.assertEqual("AWAITING_APPROVAL", fx.read(patch_id).payload["state"])
        fx.approve(patch_id)
        self.assertEqual("APPROVED", fx.read(patch_id).payload["state"])
        self.assertEqual([], fx.rows(RecordKind.RECEIPT))
        with self.assertRaises(MemoryPatchError):
            fx.commit.commit(
                fx.p(Capability.COMMIT),
                patch_id,
                expected_revision=6,
                operation_key="commit-before-publication",
            )
        fx.publish()
        fx.commit.commit(
            fx.p(Capability.COMMIT),
            patch_id,
            expected_revision=6,
            operation_key="commit",
        )
        self.assertEqual("COMMITTED", fx.read(patch_id).payload["state"])
        self.assertEqual((), fx.retrieve())
        with self.assertRaises(MemoryPatchError):
            fx.commit.activate(
                fx.p(Capability.ACTIVATE),
                patch_id,
                expected_revision=7,
                operation_key="activate-before-publication",
            )
        fx.publish()
        fx.commit.activate(
            fx.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key="activate",
        )
        self.assertEqual((), fx.retrieve())
        fx.publish()
        context = fx.retrieve()
        self.assertEqual(1, len(context))
        self.assertFalse(context[0].canonical_evidence)
        self.assertFalse(context[0].execution_authority)
        self.assertEqual(2, len(fx.rows(RecordKind.RECEIPT)))
        self.assertEqual(len(fx.rows(RecordKind.OUTBOX)), len(fx.store.read_all()))
        before = len(fx.store.read_all())
        fx.publish()
        self.assertEqual(before, len(fx.store.read_all()))

    def test_dedup_and_full_retry_create_one_candidate_and_audit(self):
        fx = self.fx
        before = len(fx.rows(RecordKind.AUDIT))
        fx.factory.commit_faults = ["40001"]
        patch_id = fx.detect()
        self.assertEqual(patch_id, fx.detect(key="another-operation"))
        self.assertEqual(1, len(fx.rows(RecordKind.PATCH)))
        self.assertEqual(before + 1, len(fx.rows(RecordKind.AUDIT)))

    def test_no_skip_and_wrong_capability_before_mutation(self):
        fx = self.fx
        patch_id = fx.detect()
        before = len(fx.rows(RecordKind.AUDIT))
        with self.assertRaises(Exception):
            fx.proposals.advance(
                fx.p(Capability.VALIDATE),
                patch_id,
                expected_revision=1,
                operation_key="skip",
                target=PatchState.VALIDATED,
            )
        with self.assertRaises(AdmissionError):
            fx.commit.activate(
                fx.p(Capability.OWNER_APPROVAL),
                patch_id,
                expected_revision=1,
                operation_key="owner-not-activation",
            )
        with self.assertRaises(AdmissionError):
            fx.approval.challenge(
                fx.core.critic_candidate(),
                patch_id,
                expected_revision=1,
                operation_key="critic-approval",
            )
        self.assertEqual(before, len(fx.rows(RecordKind.AUDIT)))

    def test_nonce_private_one_use_and_challenge_replay_never_returns_raw(self):
        fx = self.fx
        patch_id = fx.prepare()
        fresh = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch_id,
            expected_revision=5,
            operation_key="fresh",
        )
        again = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch_id,
            expected_revision=5,
            operation_key="fresh",
        )
        self.assertTrue(again.replayed)
        self.assertIsNone(again.decision_nonce)
        self.assertNotIn(
            fresh.decision_nonce.encode(),
            canonical_json_bytes(tuple(fx.factory.state.values())),
        )
        with self.assertRaises(MemoryPatchError):
            fx.approval.decide(
                fx.p(Capability.OWNER_APPROVAL),
                fresh.record.record_id,
                expected_revision=5,
                decision=ApprovalDecision.APPROVE,
                decision_nonce="x" * 43,
                operation_key="wrong-nonce",
            )
        first = fx.approval.decide(
            fx.p(Capability.OWNER_APPROVAL),
            fresh.record.record_id,
            expected_revision=5,
            decision=ApprovalDecision.APPROVE,
            decision_nonce=fresh.decision_nonce,
            operation_key="decision",
        )
        replay = fx.approval.decide(
            fx.p(Capability.OWNER_APPROVAL),
            fresh.record.record_id,
            expected_revision=5,
            decision=ApprovalDecision.APPROVE,
            decision_nonce=fresh.decision_nonce,
            operation_key="decision",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(first.outcome, replay.outcome)
        self.assertEqual(1, len(fx.rows(RecordKind.APPROVAL)))
        with self.assertRaises(MemoryPatchError):
            fx.approval.decide(
                fx.p(Capability.OWNER_APPROVAL),
                fresh.record.record_id,
                expected_revision=5,
                decision=ApprovalDecision.REJECT,
                decision_nonce=fresh.decision_nonce,
                operation_key="decision",
            )

    def test_expired_challenge_denial_is_durable(self):
        fx = self.fx
        patch_id = fx.prepare()
        fresh = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch_id,
            expected_revision=5,
            operation_key="expiry",
        )
        fx.now = NOW + timedelta(minutes=5)
        result = fx.approval.decide(
            fx.p(Capability.OWNER_APPROVAL),
            fresh.record.record_id,
            expected_revision=5,
            decision=ApprovalDecision.APPROVE,
            decision_nonce=fresh.decision_nonce,
            operation_key="expiry-decision",
        )
        self.assertEqual("EXPIRED", result.outcome["state"])
        self.assertEqual("AWAITING_APPROVAL", fx.read(patch_id).payload["state"])
        self.assertEqual("EXPIRED", fx.rows(RecordKind.CHALLENGE)[0].payload["state"])
        self.assertEqual([], fx.rows(RecordKind.APPROVAL))

    def test_restart_does_not_accept_old_challenge_or_resume_activation(self):
        fx = self.fx
        patch_id = fx.prepare()
        fresh = fx.approval.challenge(
            fx.p(Capability.OWNER_APPROVAL),
            patch_id,
            expected_revision=5,
            operation_key="pre-restart",
        )
        before = len(fx.rows(RecordKind.AUDIT))
        fx.restart()
        self.assertEqual("AWAITING_APPROVAL", fx.read(patch_id).payload["state"])
        with self.assertRaises(MemoryPatchError):
            fx.approval.decide(
                fx.p(Capability.OWNER_APPROVAL),
                fresh.record.record_id,
                expected_revision=5,
                decision=ApprovalDecision.APPROVE,
                decision_nonce=fresh.decision_nonce,
                operation_key="post-restart",
            )
        self.assertEqual(before, len(fx.rows(RecordKind.AUDIT)))
        self.assertEqual([], fx.rows(RecordKind.RECEIPT))

    def test_rejection_cannot_commit_or_activate(self):
        fx = self.fx
        patch_id = fx.prepare()
        fx.approve(patch_id, decision=ApprovalDecision.REJECT)
        fx.publish()
        self.assertEqual("REJECTED", fx.read(patch_id).payload["state"])
        for capability, method in [
            (Capability.COMMIT, fx.commit.commit),
            (Capability.ACTIVATE, fx.commit.activate),
        ]:
            with self.assertRaises(MemoryPatchError):
                method(
                    fx.p(capability),
                    patch_id,
                    expected_revision=6,
                    operation_key=capability.value,
                )

    def test_revocation_survives_restart_and_old_activation_replay(self):
        fx = self.fx
        patch_id = fx.activate()
        fx.management.revoke(
            fx.p(Capability.MANAGE),
            patch_id,
            expected_revision=8,
            operation_key="revoke",
        )
        self.assertEqual((), fx.retrieve())
        fx.publish()
        fx.restart()
        replay = fx.commit.activate(
            fx.p(Capability.ACTIVATE),
            patch_id,
            expected_revision=7,
            operation_key="patch-activate",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual("REVOKED", fx.read(patch_id).payload["state"])
        self.assertEqual((), fx.retrieve())
        self.assertEqual(2, len(fx.rows(RecordKind.RECEIPT)))

    def test_cross_owner_and_tenant_deny_without_exposing_row(self):
        fx = self.fx
        patch_id = fx.detect()
        for other in (
            make_admission(owner="owner-b"),
            make_admission(tenant="tenant-b"),
        ):
            with self.assertRaises(AdmissionError):
                fx.lifecycle.read(other.local_operator(Capability.READ), patch_id)
            other_lifecycle = NativeMemoryLifecycle(
                other, TransactionRunner(other, fx.factory)
            )
            with self.assertRaises(MemoryPatchError):
                other_lifecycle.read(other.local_operator(Capability.READ), patch_id)

    def test_row_rehash_without_audit_binding_is_denied(self):
        fx = self.fx
        patch_id = fx.prepare()
        record = fx.read(patch_id)
        changed = StoredRecord(
            record.kind,
            record.record_id,
            record.scope,
            record.revision,
            {**record.payload, "actor_session_id": "forged-session"},
        )
        fx.factory.state[(record.scope.binding(), record.kind, record.record_id)] = (
            changed
        )
        with self.assertRaises(MemoryPatchError):
            fx.read(patch_id)

    def test_evidence_withdrawal_blocks_approval_and_active_retrieval(self):
        fx = self.fx
        patch_id = fx.activate()
        fx.rf.catalog.receipts.clear()
        with self.assertRaises(EvidenceAdmissionError):
            fx.retrieve()
        empty = replace(fx.bundle, items=(), core_evidence_bindings=())
        self.assertEqual((), fx.retrieve(empty))
        self.assertEqual("ACTIVE", fx.read(patch_id).payload["state"])

    def test_concurrent_exact_commit_is_one_logical_receipt(self):
        fx = self.fx
        patch_id = fx.prepare()
        fx.approve(patch_id)
        fx.publish()
        results = []
        errors = []

        def commit():
            try:
                results.append(
                    fx.commit.commit(
                        fx.p(Capability.COMMIT),
                        patch_id,
                        expected_revision=6,
                        operation_key="concurrent",
                    )
                )
            except Exception as error:
                errors.append(type(error).__name__)

        threads = [threading.Thread(target=commit) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual([], errors)
        self.assertEqual(4, len(results))
        self.assertEqual(1, len(fx.rows(RecordKind.RECEIPT)))
        self.assertEqual(1, sum(not result.replayed for result in results))

    def test_ambiguous_commit_requires_explicit_reconciliation_without_retry(self):
        fx = self.fx
        patch_id = fx.prepare()
        fx.approve(patch_id)
        fx.publish()
        fx.factory.commit_faults = ["unknown_after_commit"]
        opens = fx.factory.opens
        with self.assertRaises(CommitOutcomeUnknown):
            fx.commit.commit(
                fx.p(Capability.COMMIT),
                patch_id,
                expected_revision=6,
                operation_key="ambiguous",
            )
        self.assertEqual(opens + 1, fx.factory.opens)
        self.assertEqual(1, len(fx.rows(RecordKind.RECEIPT)))
        self.assertEqual("COMMITTED", fx.read(patch_id).payload["state"])
        replay = fx.commit.commit(
            fx.p(Capability.COMMIT),
            patch_id,
            expected_revision=6,
            operation_key="ambiguous",
        )
        self.assertTrue(replay.replayed)
        self.assertEqual(1, len(fx.rows(RecordKind.RECEIPT)))

    def test_slot_suspend_resume_and_logical_deletion(self):
        fx = self.fx
        patch_id = fx.activate()
        manager = fx.p(Capability.MANAGE)
        fx.management.change_slot_state(
            manager,
            target=PersonalMemorySpaceState.SUSPENDED,
            expected_revision=3,
            operation_key="suspend",
        )
        self.assertEqual((), fx.retrieve())
        fx.management.change_slot_state(
            manager,
            target=PersonalMemorySpaceState.ACTIVE,
            expected_revision=4,
            operation_key="resume-slot",
        )
        self.assertEqual(1, len(fx.retrieve()))
        fx.management.change_slot_state(
            manager,
            target=PersonalMemorySpaceState.DELETED_PENDING,
            expected_revision=5,
            operation_key="delete-slot",
        )
        self.assertEqual((), fx.retrieve())
        self.assertEqual("REVOKED", fx.read(patch_id).payload["state"])
        self.assertTrue(fx.read(patch_id).payload["logically_deleted"])
        fx.management.change_slot_state(
            manager,
            target=PersonalMemorySpaceState.DELETED,
            expected_revision=6,
            operation_key="finish-logical-delete",
        )
        self.assertEqual("DELETED", fx.rows(RecordKind.SPACE)[0].payload["state"])

    def test_supersession_preserves_both_versions(self):
        fx = self.fx
        old = fx.activate()
        new = fx.activate(fx.draft(supersedes_patch_id=old), key="new")
        fx.management.supersede(
            fx.p(Capability.MANAGE),
            old,
            new,
            expected_revision=8,
            operation_key="supersede",
        )
        self.assertEqual("SUPERSEDED", fx.read(old).payload["state"])
        self.assertEqual([new], [v.patch_id for v in fx.retrieve()])
        self.assertEqual(2, len(fx.rows(RecordKind.PATCH)))

    def test_sharing_requires_separate_consent_and_is_review_only(self):
        fx = self.fx
        patch_id = fx.activate()
        with self.assertRaises(MemoryPatchError):
            fx.management.propose_sharing(
                fx.p(Capability.MANAGE),
                patch_id,
                expected_revision=8,
                consent=False,
                deidentified_summary="Reviewed summary",
                operation_key="no-consent",
            )
        fx.management.propose_sharing(
            fx.p(Capability.MANAGE),
            patch_id,
            expected_revision=8,
            consent=True,
            deidentified_summary="Reviewed summary",
            operation_key="consent",
        )
        sharing = fx.rows(RecordKind.SHARING)[0]
        self.assertEqual("DOMAIN_REVIEW_REQUIRED", sharing.payload["state"])
        self.assertFalse(sharing.payload["publication_authorized"])
        self.assertEqual(1, fx.rf.catalog.admissions)

    def test_canonical_conflict_suppresses_private_context(self):
        fx = self.fx
        fx.activate()
        other = fx.rf.candidate(content="The reviewed policy not applies.")
        canonical = fx.rf.bundle([other])
        self.assertEqual((), fx.retrieve(canonical))

    def test_owner_preferences_require_full_approval_and_remain_advisory(self):
        fx = self.fx
        draft = fx.draft(
            body={"language": "pl"},
            content_kind=MemoryContentKind.PREFERENCE,
            evidence_references=(),
        )
        fx.activate(draft)
        context = fx.retrieve()
        self.assertEqual(1, len(context))
        self.assertEqual("USER_ASSERTED_MEMORY", context[0].trust_class)
        self.assertFalse(context[0].execution_authority)
        with self.assertRaises(Exception):
            replace(draft, body={"canonical_write_authority": "yes"})

    def test_private_export_is_bounded_deterministic_and_owner_only(self):
        fx = self.fx
        fx.detect()
        first = fx.management.export_snapshot(
            fx.p(Capability.MANAGE), operation_key="export"
        )
        second = fx.management.export_snapshot(
            fx.p(Capability.MANAGE), operation_key="export"
        )
        self.assertEqual(canonical_json_bytes(first), canonical_json_bytes(second))
        with self.assertRaises(AdmissionError):
            fx.management.export_snapshot(
                fx.p(Capability.READ), operation_key="denied-export"
            )

    def test_wrong_model_or_hat_and_unconfigured_production_deny(self):
        fx = self.fx
        for draft in (
            fx.draft(hat_id="foreign-hat"),
            fx.draft(model_binding_ids=("foreign-model",)),
        ):
            with self.assertRaises(MemoryPatchError):
                fx.detect(draft)
        unconfigured = NativeMemoryLifecycle(fx.core, TransactionRunner(fx.core))
        with self.assertRaises(MemoryPatchError):
            NativeCandidates(unconfigured).intake(
                fx.p(Capability.CANDIDATE), fx.draft(), operation_key="unconfigured"
            )


class QuotaAndValidityTests(unittest.TestCase):
    def test_active_quota_is_rechecked_at_activation(self):
        fx = MemoryFixture(
            quota=PersonalHatQuotaPolicy(
                maximum_active_memory_patches=1, maximum_bytes=65536
            )
        )
        self.addCleanup(fx.close)
        fx.activate()
        patch = fx.prepare(fx.draft(title="Second patch"), key="second")
        fx.approve(patch, key="second")
        fx.publish()
        fx.commit.commit(
            fx.p(Capability.COMMIT),
            patch,
            expected_revision=6,
            operation_key="second-commit",
        )
        fx.publish()
        with self.assertRaises(Exception):
            fx.commit.activate(
                fx.p(Capability.ACTIVATE),
                patch,
                expected_revision=7,
                operation_key="second-activate",
            )
        self.assertEqual("COMMITTED", fx.read(patch).payload["state"])
        self.assertEqual(1, len(fx.retrieve()))

    def test_personal_valid_until_inclusive_but_expiry_exclusive(self):
        fx = MemoryFixture()
        self.addCleanup(fx.close)
        fx.activate(
            fx.draft(
                valid_until=NOW + timedelta(seconds=1),
                expires_at=NOW + timedelta(seconds=2),
            )
        )
        fx.now = NOW + timedelta(seconds=1)
        self.assertEqual(1, len(fx.retrieve()))
        fx.now += timedelta(microseconds=1)
        self.assertEqual((), fx.retrieve())
