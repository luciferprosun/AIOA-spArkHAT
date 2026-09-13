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
