from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace
from datetime import timedelta

from test_memory_patch_persistence_ports import NOW, make_admission

from runtime.core_admission import AdmissionError, Capability
from runtime.evidence_admission import (
    CoreEvidenceAdmission,
    EvidenceAdmissionError,
    InputOrigin,
    SourceCaptureSpec,
)


class FakeCoreEvidenceCatalog:
    """Explicit Core catalog double with a separate publication receipt set."""

    def __init__(self):
        self.records = {}
        self.receipts = {}
        self.admissions = 0
        self.publish = True

    def admit(self, record):
        self.admissions += 1
        self.records[record.evidence_id] = record
        if self.publish:
            self.receipts[record.evidence_id] = record.record_digest
        return record

    def get(self, scope, evidence_id):
        record = self.records.get(evidence_id)
        return record if record is not None and record.scope == scope else None

    def require_published(self, record):
        if self.receipts.get(record.evidence_id) != record.record_digest:
            raise EvidenceAdmissionError()


def source_spec(**changes):
    source = b"Reviewed immutable source bytes."
    digest = hashlib.sha256(source).hexdigest()
    fields = dict(
        source_id="source-one",
        source_version_id="source-version-one",
        source_fingerprint=digest,
        artifact_fingerprint=digest,
        transform_fingerprints=(),
        origin=InputOrigin.SOURCE_BYTES,
        license_id="MIT",
        license_reviewed=True,
        quarantined=False,
        hat_id="test-hat",
    )
    fields.update(changes)
    return SourceCaptureSpec(**fields), source


class EvidencePromotionTests(unittest.TestCase):
    def setUp(self):
        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        self.catalog = FakeCoreEvidenceCatalog()
        self.current = NOW
        self.boundary = CoreEvidenceAdmission(
            self.core, self.catalog, clock=lambda: self.current
        )
        self.source, self.data = source_spec()

    def capture(self):
        intent = self.boundary.approve_capture(self.principal, self.source)
        return self.boundary.capture(
            self.principal, intent, source_bytes=self.data, artifact_bytes=self.data
        )

    def test_explicit_source_bytes_and_publication_receipt_required(self):
        record = self.capture()
        reader = self.core.local_operator(Capability.READ)
        self.assertEqual(
            record, self.boundary.require_evidence(reader, record.evidence_id)
        )
        self.assertEqual(1, self.catalog.admissions)
        self.catalog.receipts.clear()
        with self.assertRaises(EvidenceAdmissionError):
            self.boundary.require_evidence(reader, record.evidence_id)

    def test_logs_reasoning_models_personal_memory_and_critic_rejected(self):
        for origin in InputOrigin:
            if origin is InputOrigin.SOURCE_BYTES:
                continue
            with (
                self.subTest(origin=origin.value),
                self.assertRaises(EvidenceAdmissionError),
            ):
                self.boundary.approve_capture(
                    self.principal, replace(self.source, origin=origin)
                )
        self.assertEqual(0, self.catalog.admissions)

    def test_source_marker_is_not_capture_authority(self):
        with self.assertRaises(EvidenceAdmissionError):
            self.boundary.capture(
                self.principal,
                {"origin": "source_bytes"},
                source_bytes=self.data,
                artifact_bytes=self.data,
            )
        critic = self.core.critic_candidate()
        with self.assertRaises(AdmissionError):
            self.boundary.approve_capture(critic, self.source)

    def test_missing_backend_does_not_create_implicit_evidence_store(self):
        boundary = CoreEvidenceAdmission(self.core, clock=lambda: NOW)
        intent = boundary.approve_capture(self.principal, self.source)
        with self.assertRaises(EvidenceAdmissionError):
            boundary.capture(
                self.principal, intent, source_bytes=self.data, artifact_bytes=self.data
            )

    def test_mismatched_source_and_transformed_bytes_denied_before_storage(self):
        intent = self.boundary.approve_capture(self.principal, self.source)
        for source, artifact in (
            (b"changed", self.data),
            (self.data, b"changed"),
            (b"", self.data),
        ):
            with self.assertRaises(EvidenceAdmissionError):
                self.boundary.capture(
                    self.principal, intent, source_bytes=source, artifact_bytes=artifact
                )
        self.assertEqual(0, self.catalog.admissions)

    def test_quarantine_and_unreviewed_license_deny(self):
        for source in (
            replace(self.source, quarantined=True),
            replace(self.source, license_reviewed=False),
        ):
            with self.assertRaises(EvidenceAdmissionError):
                self.boundary.approve_capture(self.principal, source)

    def test_tampered_scope_and_transform_invalidate_intent(self):
        intent = self.boundary.approve_capture(self.principal, self.source)
        for change in (
            {"scope": replace(intent.scope, owner_id="other-owner")},
            {"source": replace(self.source, transform_fingerprints=("f" * 64,))},
            {"expires_at": NOW + timedelta(days=1)},
        ):
            with self.assertRaises(EvidenceAdmissionError):
                self.boundary.capture(
                    self.principal,
                    replace(intent, **change),
                    source_bytes=self.data,
                    artifact_bytes=self.data,
                )
        self.assertEqual(0, self.catalog.admissions)

    def test_expiry_and_replay_do_not_readmit(self):
        intent = self.boundary.approve_capture(self.principal, self.source)
        self.boundary.capture(
            self.principal, intent, source_bytes=self.data, artifact_bytes=self.data
        )
        with self.assertRaises(EvidenceAdmissionError):
            self.boundary.capture(
                self.principal, intent, source_bytes=self.data, artifact_bytes=self.data
            )
        other = self.boundary.approve_capture(self.principal, self.source)
        self.current += timedelta(minutes=5)
        with self.assertRaises(EvidenceAdmissionError):
            self.boundary.capture(
                self.principal, other, source_bytes=self.data, artifact_bytes=self.data
            )
        self.assertEqual(1, self.catalog.admissions)

    def test_pending_core_publication_is_not_evidence_success(self):
        self.catalog.publish = False
        with self.assertRaises(EvidenceAdmissionError):
            self.capture()
        self.assertEqual(1, self.catalog.admissions)
        record = next(iter(self.catalog.records.values()))
        with self.assertRaises(EvidenceAdmissionError):
            self.boundary.require_evidence(self.principal, record.evidence_id)

    def test_withdrawn_tampered_and_other_owner_evidence_deny(self):
        record = self.capture()
        for invalid in (
            replace(record, withdrawn=True),
            replace(record, source_bytes=b"tampered"),
            replace(record, scope=replace(record.scope, owner_id="other-owner")),
        ):
            self.catalog.records[record.evidence_id] = invalid
            with self.assertRaises(EvidenceAdmissionError):
                self.boundary.require_evidence(self.principal, record.evidence_id)

    def test_foreign_core_capture_intent_cannot_be_reused(self):
        intent = self.boundary.approve_capture(self.principal, self.source)
        restarted = CoreEvidenceAdmission(self.core, self.catalog, clock=lambda: NOW)
        with self.assertRaises(EvidenceAdmissionError):
            restarted.capture(
                self.principal, intent, source_bytes=self.data, artifact_bytes=self.data
            )


class SourceLineageTests(unittest.TestCase):
    def setUp(self):
        from runtime.memory_patch import source_lineage as lineage
        from runtime.memory_patch.contracts.enums import MemoryTargetScope

        self.lineage = lineage
        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        self.catalog = FakeCoreEvidenceCatalog()
        self.evidence = CoreEvidenceAdmission(
            self.core, self.catalog, clock=lambda: NOW
        )
        self.bridge = lineage.NativeSourceBridge(self.core, self.evidence)
        self.data = b"Reviewed immutable source bytes."
        digest = hashlib.sha256(self.data).hexdigest()
        parser = lineage.ParserIdentity("plain", "1.0.0", "1.0.0")
        transform = lineage.TransformationIdentity("identity", "1.0.0", "1.0.0")
        origin = lineage.OriginMetadata(
            "SOURCE_CAPTURE", "core-fixture", "1.0.0", "1.0.0", "fixture-source", NOW
        )
        artifact = lineage.ProvenanceArtifactIdentity(
            "source",
            digest,
            len(self.data),
            "text/plain",
            origin,
            parser,
            transform,
            NOW,
            exact_source_bytes=True,
        )
        scope = lineage.SourceScopeDimensions(
            self.principal.scope.tenant_id,
            "test-hat",
            MemoryTargetScope.USER_PERSONAL_HAT,
            self.principal.scope.owner_id,
            self.principal.scope.space_id,
        )
        self.record = lineage.SourceRegistryRecord(
            self.principal.scope.tenant_id,
            "source-one",
            "test-hat",
            "text",
            "fixture-source",
            scope,
            lineage.SourceAuthorityAssessment(
                lineage.SourceAuthorityLevel.OFFICIAL_PRIMARY,
                {"basis": "synthetic-reviewed-source"},
            ),
            lineage.SourceLicenseAssessment(
                lineage.SourceLicenseStatus.CONFIRMED_PERMISSIVE, "MIT"
            ),
            lineage.SourceAccessClass.USER_PRIVATE,
            lineage.RedactionState.NOT_REQUIRED,
            parser,
            transform,
            origin,
            artifact,
            "snapshot-one",
            "source-version-one",
            lineage.SourcePublicationState.REGISTERED,
            0,
            lineage.PUBLICATION_GENESIS_DIGEST,
            NOW,
            NOW,
        )
        self.graph = lineage.ProvenanceGraph()
        self.events = []
        actor = lineage.SourceRegistryActor(
            lineage.SourceRegistryActorType.HUMAN_REVIEWER, "fixture-review"
        )
        for index, state in enumerate(
            (
                lineage.SourcePublicationState.REVIEW_REQUIRED,
                lineage.SourcePublicationState.ELIGIBLE,
            )
        ):
            decision = lineage.evaluate_publication_eligibility(
                self.record, self.graph, evaluated_at=NOW
            )
            event = lineage.build_publication_event(
                self.record,
                event_id="publication-" + str(index),
                target_state=state,
                eligibility=decision,
                actor=actor,
                reason_codes=(),
                reviewer_reference="review-one",
                created_at=NOW,
            )
            self.record = lineage.advance_registry_state(self.record, event)
            self.events.append(event)
        self.events = tuple(self.events)

    def intent(self):
        return self.bridge.request_capture(
            self.principal,
            self.record,
            self.graph,
            self.events,
            root_fingerprint=self.record.artifact.artifact_digest,
            at=NOW,
        )

    def test_published_source_requires_independent_core_capture(self):
        intent = self.intent()
        self.assertEqual(0, self.catalog.admissions)
        evidence = self.bridge.capture(
            self.principal,
            intent,
            self.record,
            self.graph,
            self.events,
            source_bytes=self.data,
            artifact_bytes=self.data,
            at=NOW,
        )
        self.assertEqual(
            self.record.artifact.artifact_digest, evidence.source.artifact_fingerprint
        )
        self.assertEqual(
            evidence,
            self.bridge.require_published(self.principal, evidence.evidence_id),
        )

    def test_missing_or_tampered_publication_chain_denies_core_intent(self):
        with self.assertRaises(self.lineage.PublicationEventChainError):
            self.bridge.request_capture(
                self.principal,
                self.record,
                self.graph,
                (),
                root_fingerprint=self.record.artifact.artifact_digest,
                at=NOW,
            )
        object.__setattr__(self.events[0], "event_digest", "0" * 64)
        with self.assertRaises(self.lineage.PublicationEventChainError):
            self.intent()
        self.assertEqual(0, self.catalog.admissions)

    def test_unknown_root_and_stale_source_bytes_fail(self):
        from runtime.memory_patch.errors import MemoryPatchError

        with self.assertRaises(MemoryPatchError):
            self.bridge.request_capture(
                self.principal,
                self.record,
                self.graph,
                self.events,
                root_fingerprint="0" * 64,
                at=NOW,
            )
        with self.assertRaises(EvidenceAdmissionError):
            self.bridge.capture(
                self.principal,
                self.intent(),
                self.record,
                self.graph,
                self.events,
                source_bytes=b"changed source",
                artifact_bytes=self.data,
                at=NOW,
            )

    def test_graph_identity_dedup_scope_and_cycle(self):
        edge = self.lineage.ProvenanceEdge(
            self.record.tenant_id,
            self.record.source_id,
            self.record.hat_scope_id,
            "edge-one",
            "1" * 64,
            "2" * 64,
            "normalized",
            self.record.parser,
            self.record.transformation,
            {},
            NOW,
        )
        graph = self.lineage.ProvenanceGraph((edge, edge))
        self.assertEqual(("1" * 64,), graph.root_digests("2" * 64))
        self.assertEqual(1, len(graph.edges))
        with self.assertRaises(self.lineage.ProvenanceCycleError):
            graph.add_edge(
                replace(
                    edge,
                    edge_id="edge-two",
                    parent_artifact_digest="2" * 64,
                    child_artifact_digest="1" * 64,
                    edge_digest="",
                )
            )
        with self.assertRaises(self.lineage.SourceRegistryValidationError):
            graph.add_edge(
                replace(
                    edge,
                    tenant_id="different-tenant",
                    edge_id="edge-two",
                    edge_digest="",
                )
            )


def acquisition_fixture(
    core, payload=b"A reviewed source paragraph.\n", media_type="text/plain"
):
    from runtime.memory_patch.acquisition import AcquiredSnapshot, AcquisitionManifest
    from runtime.memory_patch.source_lineage import SourceLicenseStatus
    from runtime.memory_patch.storage_ports import (
        SnapshotBinding,
        StorageHandle,
        StoragePurpose,
    )

    scope = core.local_operator(Capability.READ).scope
    handle = StorageHandle(
        "fixture-object", scope, StoragePurpose.SOURCE_SNAPSHOT, "version-one"
    )
    snapshot = SnapshotBinding(
        scope,
        "source-one",
        "snapshot-one",
        "source-version-one",
        1,
        "test-hat",
        handle,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        media_type,
        InputOrigin.SOURCE_BYTES,
        NOW,
    )
    manifest = AcquisitionManifest(
        snapshot,
        SourceLicenseStatus.CONFIRMED_PERMISSIVE,
        "MIT",
        "fixture-license-review",
        False,
    )
    return AcquiredSnapshot(manifest, payload)


class SourceAcquisitionTests(unittest.TestCase):
    def setUp(self):
        from runtime.memory_patch.acquisition import NativeAcquisition

        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        self.acquired = acquisition_fixture(self.core)
        self.reads = 0
        outer = self

        class ExplicitStorage:
            def require_locked(self, snapshot):
                if snapshot != outer.acquired.manifest.snapshot:
                    raise EvidenceAdmissionError()

            def read_snapshot(self, snapshot):
                outer.reads += 1
                return outer.acquired.payload

        self.service = NativeAcquisition(self.core, ExplicitStorage())

    def test_exact_locked_storage_identity(self):
        self.assertEqual(
            self.acquired, self.service.acquire(self.principal, self.acquired.manifest)
        )
        self.assertEqual(1, self.reads)

    def test_quarantine_unknown_license_model_and_wrong_owner_deny_before_storage(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.source_lineage import SourceLicenseStatus

        manifest = self.acquired.manifest
        for invalid in (
            replace(manifest, quarantined=True),
            replace(manifest, license_status=SourceLicenseStatus.UNKNOWN),
            replace(
                manifest,
                snapshot=replace(manifest.snapshot, origin=InputOrigin.MODEL_OUTPUT),
            ),
        ):
            with self.assertRaises(MemoryPatchError):
                self.service.acquire(self.principal, invalid)
        foreign = make_admission(owner="foreign-owner")
        with self.assertRaises(AdmissionError):
            self.service.acquire(
                foreign.local_operator(Capability.EVIDENCE_CAPTURE), manifest
            )
        self.assertEqual(0, self.reads)

    def test_default_storage_unconfigured_and_corpus_duplicates_denied(self):
        from runtime.memory_patch.acquisition import NativeAcquisition, corpus_identity
        from runtime.memory_patch.errors import MemoryPatchError

        with self.assertRaises(MemoryPatchError):
            NativeAcquisition(self.core).acquire(self.principal, self.acquired.manifest)
        self.assertEqual(64, len(corpus_identity((self.acquired.manifest,))))
        with self.assertRaises(MemoryPatchError):
            corpus_identity((self.acquired.manifest, self.acquired.manifest))


class IngestionContractTests(unittest.TestCase):
    def setUp(self):
        from test_memory_patch_persistence_ports import FakeFactory

        from runtime.memory_patch.ingestion import NativeIngestion
        from runtime.memory_patch.persistence.ports import TransactionRunner

        self.core = make_admission()
        self.principal = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        self.factory = FakeFactory()
        self.runner = TransactionRunner(self.core, self.factory)
        self.acquired = acquisition_fixture(self.core)
        self.manifest = self.acquired.manifest
        self.known_receipts = set()
        outer = self

        class ExplicitEffects:
            def require_receipt(self, principal, receipt):
                if receipt.receipt_digest not in outer.known_receipts:
                    raise EvidenceAdmissionError()

        self.service = NativeIngestion(
            self.core, self.runner, effects=ExplicitEffects()
        )
        self.registration = self.service.register(
            self.principal, self.manifest, operation_key="register-fixture", at=NOW
        )
        self.saga_id = self.registration.outcome["saga_id"]

    def receipt(self, milestone):
        from runtime.memory_patch.ingestion import MilestoneReceipt

        snapshot = self.manifest.snapshot
        receipt = MilestoneReceipt(
            snapshot.scope,
            self.saga_id,
            milestone,
            snapshot.binding_digest,
            snapshot.content_sha256,
            hashlib.sha256(milestone.value.encode()).hexdigest(),
            "fixture-effect",
        )
        self.known_receipts.add(receipt.receipt_digest)
        return receipt

    def test_registration_exact_replay_is_one_logical_saga(self):
        from runtime.memory_patch.persistence.ports import RecordKind

        result = self.service.register(
            self.principal, self.manifest, operation_key="register-fixture", at=NOW
        )
        self.assertTrue(result.replayed)
        self.assertEqual(self.registration.outcome, result.outcome)
        self.assertEqual(
            1,
            sum(
                record.kind is RecordKind.INGESTION
                for record in self.factory.state.values()
            ),
        )

    def test_each_forward_step_requires_bound_receipt_and_publication_authority(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.ingestion import MILESTONE_ORDER, SagaMilestone

        for index, milestone in enumerate(MILESTONE_ORDER[1:-1], 1):
            receipt = self.receipt(milestone)
            result = self.service.advance(
                self.principal,
                receipt,
                expected_revision=index,
                operation_key="step-" + str(index),
                at=NOW,
            )
            self.assertEqual(milestone.value, result.outcome["state"])
            replay = self.service.advance(
                self.principal,
                receipt,
                expected_revision=index,
                operation_key="step-" + str(index),
                at=NOW,
            )
            self.assertTrue(replay.replayed)
        with self.assertRaises(MemoryPatchError):
            self.service.advance(
                self.principal,
                self.receipt(SagaMilestone.PUBLISHED),
                expected_revision=8,
                operation_key="publish",
                at=NOW,
            )
        record = self.service.inspect(
            self.core.local_operator(Capability.READ), self.saga_id
        )
        self.assertEqual("VALIDATED", record.payload["state"])

    def test_skipped_edge_and_untrusted_receipt_deny(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.ingestion import SagaMilestone

        receipt = self.receipt(SagaMilestone.PARSED)
        with self.assertRaises(MemoryPatchError):
            self.service.advance(
                self.principal,
                receipt,
                expected_revision=1,
                operation_key="skip",
                at=NOW,
            )
        receipt = self.receipt(SagaMilestone.ACQUIRED_LOCAL)
        self.known_receipts.clear()
        with self.assertRaises(EvidenceAdmissionError):
            self.service.advance(
                self.principal,
                receipt,
                expected_revision=1,
                operation_key="forged",
                at=NOW,
            )

    def test_quarantine_is_durable_and_restart_inspection_never_resumes(self):
        from runtime.memory_patch.errors import MemoryPatchError
        from runtime.memory_patch.ingestion import NativeIngestion, SagaMilestone

        self.service.quarantine(
            self.principal,
            self.saga_id,
            expected_revision=1,
            operation_key="quarantine",
            reason="SOURCE_CHANGED",
            at=NOW,
        )
        restarted = NativeIngestion(self.core, self.runner)
        record = restarted.inspect(
            self.core.local_operator(Capability.READ), self.saga_id
        )
        self.assertTrue(record.payload["quarantined"])
        self.assertEqual("REGISTERED", record.payload["state"])
        with self.assertRaises(MemoryPatchError):
            self.service.advance(
                self.principal,
                self.receipt(SagaMilestone.ACQUIRED_LOCAL),
                expected_revision=2,
                operation_key="after-quarantine",
                at=NOW,
            )
