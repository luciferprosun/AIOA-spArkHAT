from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from test_memory_patch_persistence_ports import NOW, make_admission
from test_memory_patch_retrieval import RetrievalFixture

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.correction.answers import (
    UNKNOWN_ANSWER,
    NativeAnswerAssembler,
)
from runtime.memory_patch.correction.claims import (
    ClaimEvidenceCandidateStatus,
    NativeClaims,
    NativeDraft,
    exact_text_spans,
    extract_native_claims,
)
from runtime.memory_patch.correction.packets import (
    CorrectionAction,
    NativePacketIntegrity,
)
from runtime.memory_patch.correction.verification import (
    CitationBinding,
    CitedDraft,
    NativeVerifier,
    SemanticSignal,
)
from runtime.memory_patch.errors import MemoryPatchError


class CorrectionFixture:
    def __init__(self, source="The reviewed policy applies."):
        self.retrieval = RetrievalFixture()
        self.core = self.retrieval.core
        self.principal = self.retrieval.reader
        candidate = self.retrieval.candidate(content=source)
        self.bundle = self.retrieval.bundle([candidate])
        self.claims = NativeClaims(self.core, self.retrieval.service)
        self.current = NOW
        self.integrity = NativePacketIntegrity(
            self.core,
            self.claims,
            key_id="synthetic-integrity-test",
            key_material=b"c4-synthetic-test-material-only!!",
            clock=lambda: self.current,
        )
        self.verifier = NativeVerifier(self.claims, self.integrity)

    def draft(self, text):
        return NativeDraft(self.principal.scope, "test-hat", "draft-fixture", text)

    def cited(self, text):
        draft = self.draft(text)
        return CitedDraft(
            draft,
            tuple(
                CitationBinding(
                    c.start_offset, c.end_offset, self.bundle.items[0].item_hash
                )
                for c in extract_native_claims(draft)
            ),
        )


class ClaimBindingTests(unittest.TestCase):
    def test_exact_unicode_codepoint_spans_abbreviations_and_decimal(self):
        text = "  • Café costs 3.50 units.\nArt. 2 applies; Why?"
        spans = exact_text_spans(text)
        self.assertEqual(
            ["Café costs 3.50 units.", "Art. 2 applies;", "Why?"],
            [s.text for s in spans],
        )
        for span in spans:
            self.assertEqual(span.text, text[span.start_offset : span.end_offset])
        with self.assertRaises(Exception):
            exact_text_spans("Cafe\u0301 applies.")

    def test_supported_refuted_and_unverified_are_distinct(self):
        fx = CorrectionFixture()
        for text, status in [
            ("The reviewed policy applies.", ClaimEvidenceCandidateStatus.SUPPORTED),
            (
                "The reviewed policy does not apply.",
                ClaimEvidenceCandidateStatus.UNVERIFIED,
            ),
            ("The reviewed policy not applies.", ClaimEvidenceCandidateStatus.REFUTED),
            (
                "An unrelated assertion is certainly true.",
                ClaimEvidenceCandidateStatus.UNVERIFIED,
            ),
        ]:
            with self.subTest(status=status, text=text):
                analysis = fx.claims.assess(fx.principal, fx.draft(text), fx.bundle)
                self.assertEqual(status, analysis.assessments[0].status)
        # Confidence and fluency never fill a missing deterministic counterpart.

    def test_wrong_date_is_refuted_and_bound_to_exact_source(self):
        fx = CorrectionFixture("The reviewed policy starts on 1 January 2030.")
        analysis = fx.claims.assess(
            fx.principal,
            fx.draft("The reviewed policy starts on 2 January 2030."),
            fx.bundle,
        )
        self.assertEqual(
            ClaimEvidenceCandidateStatus.REFUTED, analysis.assessments[0].status
        )
        link = analysis.assessments[0].links[0]
        self.assertEqual(
            "The reviewed policy starts on 1 January 2030.", link.exact_source_text
        )
        self.assertEqual(fx.bundle.items[0].item_hash, link.item_hash)

    def test_foreign_owner_and_critic_cannot_validate(self):
        fx = CorrectionFixture()
        foreign = make_admission(owner="foreign-owner").local_operator(Capability.READ)
        with self.assertRaises(AdmissionError):
            fx.claims.assess(
                foreign, fx.draft("The reviewed policy applies."), fx.bundle
            )
        with self.assertRaises(MemoryPatchError):
            fx.claims.assess(
                fx.core.critic_candidate(),
                fx.draft("The reviewed policy applies."),
                fx.bundle,
            )


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.fx = CorrectionFixture("The reviewed policy starts on 1 January 2030.")
        self.draft = self.fx.draft("The reviewed policy starts on 2 January 2030.")
        self.packet, self.receipt = self.fx.integrity.build(
            self.fx.principal, self.draft, self.fx.bundle
        )

    def test_packet_requires_correction_and_prohibits_original_without_approval(self):
        self.assertEqual(CorrectionAction.REPLACE, self.packet.corrections[0].action)
        self.assertEqual(self.draft.text, self.packet.prohibitions[0])
        self.assertEqual(
            "The reviewed policy starts on 1 January 2030.",
            self.packet.corrections[0].required_text,
        )
        self.fx.integrity.verify(self.fx.principal, self.packet, self.receipt)
        self.assertNotIn("key_material", repr(self.fx.integrity))
        with self.assertRaises(MemoryPatchError):
            self.fx.integrity.verify(
                self.fx.core.local_operator(Capability.OWNER_APPROVAL),
                self.packet,
                self.receipt,
            )

    def test_tamper_wrong_key_scope_and_expiry_are_denied(self):
        changed = replace(self.packet, prohibitions=())
        with self.assertRaises(MemoryPatchError):
            self.fx.integrity.verify(self.fx.principal, changed, self.receipt)
        other = NativePacketIntegrity(
            self.fx.core,
            self.fx.claims,
            key_id="synthetic-integrity-test",
            key_material=b"x" * 32,
            clock=lambda: NOW,
        )
        with self.assertRaises(MemoryPatchError):
            other.verify(self.fx.principal, self.packet, self.receipt)
        with self.assertRaises(MemoryPatchError):
            self.fx.integrity.verify(
                self.fx.principal,
                self.packet,
                replace(self.receipt, domain_id="different-domain"),
            )
        self.fx.current = NOW + timedelta(minutes=5)
        with self.assertRaises(MemoryPatchError):
            self.fx.integrity.verify(self.fx.principal, self.packet, self.receipt)

    def test_one_operation_two_attempts_no_replay_or_third_attempt(self):
        fx = self.fx
        fx.integrity.consume_attempt(
            fx.principal,
            self.packet,
            self.receipt,
            operation_id="answer-one",
            attempt=1,
        )
        for operation, attempt in [
            ("answer-two", 2),
            ("answer-one", 1),
            ("answer-one", 3),
        ]:
            with (
                self.subTest(operation=operation, attempt=attempt),
                self.assertRaises(MemoryPatchError),
            ):
                fx.integrity.consume_attempt(
                    fx.principal,
                    self.packet,
                    self.receipt,
                    operation_id=operation,
                    attempt=attempt,
                )
        fx.integrity.consume_attempt(
            fx.principal,
            self.packet,
            self.receipt,
            operation_id="answer-one",
            attempt=2,
        )
        with self.assertRaises(MemoryPatchError):
            fx.integrity.consume_attempt(
                fx.principal,
                self.packet,
                self.receipt,
                operation_id="answer-one",
                attempt=2,
            )


class VerificationAndAnswerTests(unittest.TestCase):
    def setUp(self):
        self.fx = CorrectionFixture("The reviewed policy starts on 1 January 2030.")
        self.good = "The reviewed policy starts on 1 January 2030."
        self.bad = "The reviewed policy starts on 2 January 2030."
        self.packet, self.receipt = self.fx.integrity.build(
            self.fx.principal, self.fx.draft(self.bad), self.fx.bundle
        )

    def verify(self, value, **kwargs):
        return self.fx.verifier.verify(
            self.fx.principal,
            value,
            self.packet,
            self.receipt,
            self.fx.bundle,
            **kwargs,
        )

    def test_fact_date_correction_citation_and_model_ceiling(self):
        good = self.fx.cited(self.good)
        self.assertTrue(self.verify(good).verified)
        self.assertFalse(
            self.verify(
                self.fx.cited(self.bad), semantic_signal=SemanticSignal.SUPPORTS
            ).verified
        )
        self.assertFalse(
            self.verify(good, semantic_signal=SemanticSignal.UNKNOWN).verified
        )
        self.assertFalse(self.verify(replace(good, citations=())).verified)
        wrong = replace(
            good, citations=(replace(good.citations[0], evidence_item_hash="0" * 64),)
        )
        self.assertIn("CITATION_SOURCE_MISMATCH", self.verify(wrong).reason_codes)
        wrong_span = replace(
            good, citations=(replace(good.citations[0], start_offset=1),)
        )
        self.assertIn("CITATION_SPAN_MISMATCH", self.verify(wrong_span).reason_codes)

    def test_same_packet_retry_full_reverification_and_idempotent_readback(self):
        fx = self.fx
        good = self.good
        bad = self.bad

        class Provider:
            def __init__(self):
                self.calls = []

            def draft(self, principal, packet, bundle, *, attempt):
                self.calls.append((packet.packet_hash, bundle.bundle_hash, attempt))
                return fx.cited(bad if attempt == 1 else good)

        provider = Provider()
        assembler = NativeAnswerAssembler(fx.verifier, provider)
        answer = assembler.answer(
            fx.principal,
            self.packet,
            self.receipt,
            fx.bundle,
            operation_id="one-answer",
        )
        self.assertEqual("VERIFIED", answer.status)
        self.assertEqual(2, answer.attempts)
        self.assertEqual(2, len(provider.calls))
        self.assertEqual(provider.calls[0][:2], provider.calls[1][:2])
        self.assertEqual(
            answer,
            assembler.answer(
                fx.principal,
                self.packet,
                self.receipt,
                fx.bundle,
                operation_id="one-answer",
            ),
        )
        self.assertEqual(2, len(provider.calls))
        fx.retrieval.catalog.receipts.clear()
        with self.assertRaises(Exception):
            assembler.answer(
                fx.principal,
                self.packet,
                self.receipt,
                fx.bundle,
                operation_id="one-answer",
            )
        self.assertEqual(2, len(provider.calls))

    def test_exhaustion_or_provider_failure_is_explicit_unknown(self):
        fx = self.fx
        bad = self.bad

        class Provider:
            def __init__(self):
                self.calls = 0

            def draft(self, principal, packet, bundle, *, attempt):
                self.calls += 1
                return fx.cited(bad)

        provider = Provider()
        assembler = NativeAnswerAssembler(fx.verifier, provider)
        answer = assembler.answer(
            fx.principal,
            self.packet,
            self.receipt,
            fx.bundle,
            operation_id="two-failures",
        )
        self.assertEqual("UNVERIFIED", answer.status)
        self.assertEqual(UNKNOWN_ANSWER, answer.answer)
        self.assertEqual(2, provider.calls)
        self.assertTrue(answer.review_required)
        self.assertEqual((), answer.citations)

    def test_default_provider_is_unconfigured_and_never_falls_back(self):
        fx = self.fx
        answer = NativeAnswerAssembler(fx.verifier).answer(
            fx.principal, self.packet, self.receipt, fx.bundle, operation_id="none"
        )
        self.assertEqual("UNVERIFIED", answer.status)
        self.assertEqual(0, answer.attempts)
