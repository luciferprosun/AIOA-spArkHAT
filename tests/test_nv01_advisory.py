"""NV-01 C10–C13: native DTO reuse, fail-closed evidence and replay contracts."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import Mock

from test_memory_patch_evidence_promotion import FakeCoreEvidenceCatalog, source_spec
from test_memory_patch_persistence_ports import NOW, make_admission

from runtime.core_admission import AdmissionError, Capability
from runtime.evidence_admission import CoreEvidenceAdmission, EvidenceAdmissionError
from runtime.memory_patch.contracts.enums import (
    ActorType,
    CorrectionCandidateState,
    ModelExperienceOutcome,
)
from runtime.memory_patch.contracts.records import (
    ClaimCandidate,
    CorrectionCandidate,
    ModelExperienceEvent,
    assert_model_experience_is_advisory,
)
from runtime.memory_patch.errors import ContractValidationError
from runtime.mission.advisory import (
    CorrectionDeltaLink,
    PheromoneEvent,
    PheromoneKind,
    PheromoneSnapshotRef,
    compare_episode_reuse,
    compare_event_replay,
    require_verified_reuse,
)
from runtime.mission.contracts import MissionError, MissionTrace


class AdvisoryTests(unittest.TestCase):
    def setUp(self):
        self.core = make_admission()
        self.reader = self.core.local_operator(Capability.READ)
        self.scope = self.reader.scope
        self.trace = MissionTrace(
            "existing-core-run",
            "mission-one",
            "episode-one",
            "event-one",
            "test-model",
            1,
        )

    def candidate(
        self, original="The reviewed value is 2.", corrected="The reviewed value is 3."
    ):
        return CorrectionCandidate(
            self.trace.event_id,
            self.scope.tenant_id,
            self.scope.owner_id,
            self.scope.space_id,
            ActorType.CRITIC_PROMPT_LOOP,
            self.trace.trace_id,
            self.trace.model_profile_ref,
            "draft-ref",
            (ClaimCandidate("claim-one", "draft-ref", original, "synthetic-fact"),),
            corrected,
            self.trace.evidence_refs,
            0.5,
            NOW,
            CorrectionCandidateState.PROPOSED,
        )

    def experience(self):
        return ModelExperienceEvent(
            self.trace.event_id,
            self.scope.tenant_id,
            self.scope.owner_id,
            self.scope.space_id,
            "synthetic-provider",
            "synthetic-family",
            "synthetic-version-1",
            "synthetic-failure",
            self.trace.trace_id,
            "synthetic-fact",
            ModelExperienceOutcome.CORRECTED,
            "MODEL_HINT_ONLY",
            NOW,
            None,
            "synthetic-retention-v1",
        )

    def event(self, kind=PheromoneKind.VERIFIED_REUSE):
        return PheromoneEvent(
            self.experience(),
            "trail-one",
            self.scope,
            self.trace,
            kind,
            "core-verifier-unbound",
            "source-version-one",
        )

    def captured(self):
        self.catalog = FakeCoreEvidenceCatalog()
        evidence = CoreEvidenceAdmission(self.core, self.catalog, clock=lambda: NOW)
        source, data = source_spec()
        actor = self.core.local_operator(Capability.EVIDENCE_CAPTURE)
        intent = evidence.approve_capture(actor, source)
        record = evidence.capture(actor, intent, source_bytes=data, artifact_bytes=data)
        self.trace = replace(self.trace, evidence_refs=(record.evidence_id,))
        return evidence, record

    def test_C10_existing_candidate_and_no_change_audit_survive(self):
        candidate = self.candidate("Café applies.", " Cafe\u0301 applies. ")
        link = CorrectionDeltaLink(
            candidate, self.scope, self.trace, "source-version-one"
        )
        self.assertIs(candidate, link.candidate)
        result = link.audit_decision()
        self.assertEqual("NO_CHANGE", result["status"])
        self.assertIsNone(result["delta_id"])
        self.assertEqual(candidate.content_hash, result["candidate_hash"])
        self.assertEqual(candidate.event_id, result["event_id"])
        self.assertEqual("NONE", result["authority"])

    def test_C10_correction_is_minimal_unverified_and_not_fuzzy_equivalence(self):
        candidate = self.candidate('Value "A  B" applies.', 'Value "A B" applies.')
        link = CorrectionDeltaLink(
            candidate, self.scope, self.trace, "source-version-one"
        )
        self.assertEqual("CANDIDATE_ONLY", link.audit_decision()["status"])
        self.assertEqual(64, len(link.audit_decision()["delta_id"]))
        self.assertEqual((), link.applicability)
        with self.assertRaises(MissionError):
            replace(link, verification_method="MODEL_SELF_VERIFIED")

    def test_C10_wrong_owner_trace_evidence_and_multiclaim_are_denied(self):
        candidate = self.candidate()
        for change in (
            {"scope": replace(self.scope, owner_id="foreign")},
            {"trace": replace(self.trace, trace_id="different-trace")},
            {"trace": replace(self.trace, evidence_refs=("forged",))},
            {
                "candidate": replace(
                    candidate,
                    detected_claims=candidate.detected_claims * 1
                    + (ClaimCandidate("claim-two", "draft", "Extra claim.", "fact"),),
                )
            },
        ):
            with self.subTest(change=list(change)), self.assertRaises(MissionError):
                replace(
                    CorrectionDeltaLink(
                        candidate, self.scope, self.trace, "source-version-one"
                    ),
                    **change,
                )

    def test_C11_empty_evidence_or_missing_verifier_cannot_be_verified_reuse(self):
        evidence = CoreEvidenceAdmission(
            self.core, FakeCoreEvidenceCatalog(), clock=lambda: NOW
        )
        verifier = Mock()
        with self.assertRaises(MissionError):
            require_verified_reuse(
                self.event(),
                core=self.core,
                principal=self.reader,
                evidence=evidence,
                verifier=verifier,
            )
        self.assertFalse(verifier.mock_calls)
        evidence, _ = self.captured()
        with self.assertRaises(MissionError):
            require_verified_reuse(
                self.event(),
                core=self.core,
                principal=self.reader,
                evidence=evidence,
                verifier=None,
            )

    def test_C11_existing_core_evidence_gate_and_trusted_verifier_are_both_required(
        self,
    ):
        evidence, _ = self.captured()
        verifier = Mock()
        event = self.event()
        verifier.require_verified_reuse.return_value = None
        self.assertEqual(
            "ADVISORY_REUSE_VERIFIED",
            require_verified_reuse(
                event,
                core=self.core,
                principal=self.reader,
                evidence=evidence,
                verifier=verifier,
            ),
        )
        verifier.require_verified_reuse.assert_called_once_with(self.reader, event)
        self.assertIs(type(event.experience), ModelExperienceEvent)
        self.assertEqual("UTILITY_POSITIVE_CANDIDATE", event.signal_channel)

    def test_C11_boolean_or_model_text_is_not_a_verifier_receipt(self):
        evidence, _ = self.captured()
        for value in (True, False, "VERIFIED", {"approved": True}):
            verifier = Mock()
            verifier.require_verified_reuse.return_value = value
            with self.subTest(value=value), self.assertRaises(MissionError):
                require_verified_reuse(
                    self.event(),
                    core=self.core,
                    principal=self.reader,
                    evidence=evidence,
                    verifier=verifier,
                )

    def test_C11_foreign_scope_wrong_principal_and_source_revision_fail_closed(self):
        evidence, _ = self.captured()
        verifier = Mock()
        foreign = make_admission(owner="foreign").local_operator(Capability.READ)
        for principal in (foreign, self.core.critic_candidate()):
            with self.assertRaises(AdmissionError):
                require_verified_reuse(
                    self.event(),
                    core=self.core,
                    principal=principal,
                    evidence=evidence,
                    verifier=verifier,
                )
        with self.assertRaises(MissionError):
            require_verified_reuse(
                replace(self.event(), source_revision="other-revision"),
                core=self.core,
                principal=self.reader,
                evidence=evidence,
                verifier=verifier,
            )
        self.assertFalse(verifier.mock_calls)

    def test_C12_duplicate_event_does_not_deposit_and_changed_payload_conflicts(self):
        first = self.event()
        self.assertEqual("DUPLICATE_NO_DEPOSIT", compare_event_replay(first, first))
        with self.assertRaises(MissionError) as caught:
            compare_event_replay(first, replace(first, kind=PheromoneKind.FAILED_REUSE))
        self.assertEqual("CONFLICT", caught.exception.code)

    def test_C12_new_event_id_same_episode_does_not_reinforce_again(self):
        first = self.event()
        second = replace(
            first,
            experience=replace(first.experience, model_experience_event_id="event-two"),
            trace=replace(first.trace, event_id="event-two"),
        )
        self.assertEqual(
            "EPISODE_ALREADY_ACCOUNTED_NO_POSITIVE_DEPOSIT",
            compare_episode_reuse(first, second),
        )
        with self.assertRaises(MissionError):
            compare_episode_reuse(
                first,
                replace(second, trace=replace(second.trace, episode_id="episode-two")),
            )

    def test_C11_three_critics_share_one_evidence_lineage_not_three_votes(self):
        _evidence, record = self.captured()
        refs = [self.event().trace.evidence_refs for _ in range(3)]
        self.assertEqual(
            {record.evidence_id}, {ref for critic in refs for ref in critic}
        )
        with self.assertRaises(MissionError):
            replace(self.trace, evidence_refs=(record.evidence_id,) * 3)

    def test_C13_error_recurrence_is_not_truth_and_failed_reuse_is_distinct(self):
        expected = {
            PheromoneKind.VERIFIED_REUSE: "UTILITY_POSITIVE_CANDIDATE",
            PheromoneKind.USEFUL_PROBE: "UTILITY_POSITIVE_CANDIDATE",
            PheromoneKind.ERROR_RECURRED: "RECHECK_SALIENCE_ONLY",
            PheromoneKind.FAILED_REUSE: "UTILITY_NEGATIVE_CANDIDATE",
            PheromoneKind.CONFLICT: "REUSE_BLOCKED",
            PheromoneKind.REVOKED: "REUSE_BLOCKED",
        }
        for kind, channel in expected.items():
            self.assertEqual(channel, self.event(kind).signal_channel)

    def test_C13_experience_cannot_be_evidence_approval_or_action_authority(self):
        for use in (
            "used_as_evidence",
            "used_for_approval",
            "used_for_action_authorization",
        ):
            with self.subTest(use=use), self.assertRaises(ContractValidationError):
                assert_model_experience_is_advisory(self.experience(), **{use: True})

    def test_C13_conflict_revoked_and_withdrawn_evidence_never_revive(self):
        evidence, record = self.captured()
        verifier = Mock()
        for kind in (
            PheromoneKind.CONFLICT,
            PheromoneKind.REVOKED,
            PheromoneKind.ERROR_RECURRED,
            PheromoneKind.FAILED_REUSE,
            PheromoneKind.USEFUL_PROBE,
        ):
            with self.subTest(kind=kind), self.assertRaises(MissionError):
                require_verified_reuse(
                    self.event(kind),
                    core=self.core,
                    principal=self.reader,
                    evidence=evidence,
                    verifier=verifier,
                )
        self.catalog.records[record.evidence_id] = replace(record, withdrawn=True)
        with self.assertRaises(EvidenceAdmissionError):
            require_verified_reuse(
                self.event(),
                core=self.core,
                principal=self.reader,
                evidence=evidence,
                verifier=verifier,
            )
        self.assertFalse(verifier.mock_calls)

    def test_C13_snapshot_separates_tau_and_has_no_score_authority_escape(self):
        snapshot = PheromoneSnapshotRef(
            "snapshot-one",
            "trail-one",
            self.scope,
            "event-one",
            NOW,
            "not-implemented-v1",
            "tau-positive-ref",
            "tau-negative-ref",
        )
        self.assertNotEqual(snapshot.tau_positive_ref, snapshot.tau_negative_ref)
        with self.assertRaises(MissionError):
            replace(snapshot, tau_negative_ref=snapshot.tau_positive_ref)
        for forbidden in ("approved", "authority", "verified", "score", "tau_positive"):
            with self.subTest(forbidden=forbidden), self.assertRaises(TypeError):
                replace(snapshot, **{forbidden: 999999})


if __name__ == "__main__":
    unittest.main()
