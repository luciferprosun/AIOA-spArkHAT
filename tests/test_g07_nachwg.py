"""Bounded German-law contract tests, isolated fixtures, zero live evidence."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from nachwg_support import NachwgFixture, correct_answer
from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.learning.nachwg_contract import HISTORICAL_QUESTION, parse_legal_answer


class NachwgCoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.counter = 0

    def fixture(self, **kwargs):
        self.counter += 1
        fx = NachwgFixture(self.root / str(self.counter), **kwargs)
        self.addCleanup(fx.close)
        return fx

    def test_exact_historical_question_and_initial_wrapper_contains_no_answer_key(self):
        self.assertEqual(
            "As of today, can an employer in Germany validly hire an employee under an oral "
            "employment agreement? Must the essential employment terms be provided on paper "
            "and signed, or can they be sent electronically? Explain the rules introduced in 2022, "
            "the change effective from 1 January 2025, all important conditions and exceptions, "
            "and cite the controlling provisions.", HISTORICAL_QUESTION)
        fx = self.fixture()
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        prompt = json.loads(fx.transport.calls[0]["messages"][-1]["content"])
        self.assertEqual(HISTORICAL_QUESTION, prompt["question"])
        self.assertEqual({"question", "phase", "actor_output_contract"}, set(prompt))
        self.assertNotIn("required_facts", json.dumps(prompt))
        self.assertNotIn("2025-01-01", json.dumps(prompt["actor_output_contract"]))

    def test_all_eight_correct_is_zero_write_even_with_write_consent(self):
        fx = self.fixture()
        fx.consent()
        before = fx.factory.path.read_bytes()
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("LIVE_CORRECT_ZERO_WRITE", result["acceptance_route"])
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual(1, result["actor_calls"])
        self.assertEqual(8, len(result["final_checks"]))
        self.assertTrue(all(c["supported"] for c in result["final_checks"].values()))
        self.assertIsNone(result["correction_packet"])
        self.assertEqual(before, fx.factory.path.read_bytes())

    def test_each_false_boolean_is_rejected_as_the_exact_claim(self):
        fx = self.fixture()
        for identifier, values in correct_answer()["claims"].items():
            for field, value in values.items():
                if type(value) is not bool:
                    continue
                answer = correct_answer()
                answer["claims"][identifier][field] = not value
                with self.subTest(claim=identifier, field=field):
                    review = fx.learning.review_nachwg(answer)
                    self.assertEqual((identifier,), review["failed_claim_ids"])
                    self.assertEqual([field], review["checks"][identifier]["failed_fields"])

    def test_stale_paper_only_rule_missing_receipt_sector_and_wrong_provision(self):
        fx = self.fixture()
        cases = []
        stale = correct_answer()
        stale["claims"]["ELECTRONIC_TEXT_FORM"].update(
            electronic_transmission_permitted=False, proof_form="signed_paper_only", effective_from="2022-08-01",
            signed_paper_always_required=True)
        cases.append((stale, "ELECTRONIC_TEXT_FORM"))
        for key in ("RECEIPT_CONFIRMATION_REQUEST", "SECTOR_EXCEPTION"):
            answer = correct_answer()
            del answer["claims"][key]
            cases.append((answer, key))
        wrong = correct_answer()
        wrong["claims"]["CONTROLLING_PROVISION"]["section"] = "3"
        cases.append((wrong, "CONTROLLING_PROVISION"))
        for answer, key in cases:
            with self.subTest(key=key):
                self.assertEqual((key,), fx.learning.review_nachwg(answer)["failed_claim_ids"])

    def test_null_and_missing_field_never_self_verify(self):
        fx = self.fixture()
        for operation in ("null", "missing"):
            answer = correct_answer()
            value = answer["claims"]["SAVE_AND_PRINT"]
            if operation == "null": value["printing_required"] = None
            else: del value["printing_required"]
            self.assertEqual(("SAVE_AND_PRINT",), fx.learning.review_nachwg(answer)["failed_claim_ids"])

    def test_schema_rejects_duplicate_keys_unknown_fields_boolean_as_int_and_free_prose(self):
        invalid = ['{"claims":{},"claims":{}}', '{"claims":{"ACCESSIBILITY":{},"ACCESSIBILITY":{}}}']
        answer = correct_answer()
        answer["claims"]["CONTROLLING_PROVISION"]["paragraph"] = True
        invalid.append(json.dumps(answer))
        for field in ("VERIFIED", "consent", "execution_authority", "free_text"):
            answer = correct_answer(); answer[field] = True
            invalid.append(json.dumps(answer))
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises((ValueError, TypeError)):
                parse_legal_answer(raw)

    def test_packet_only_failed_claims_and_one_repair_then_minimal_durable_delta(self):
        wrong = correct_answer()
        wrong["claims"]["RECEIPT_CONFIRMATION_REQUEST"]["employer_requests_receipt"] = False
        fx = self.fixture(replies=[wrong, correct_answer()])
        fx.consent()
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("LIVE_ERROR_REPAIRED", result["acceptance_route"])
        self.assertEqual(2, result["actor_calls"])
        self.assertEqual(["RECEIPT_CONFIRMATION_REQUEST"], result["failed_claim_ids_initial"])
        self.assertFalse(result["initial_checks"]["RECEIPT_CONFIRMATION_REQUEST"]["supported"])
        packet = result["correction_packet"]
        self.assertEqual(["RECEIPT_CONFIRMATION_REQUEST"], [c["claim_id"] for c in packet["corrections"]])
        rows = fx.learning.records("DELTA")
        self.assertEqual(1, len(rows))
        delta = fx.learning.delta(rows[0])
        self.assertEqual({"RECEIPT_CONFIRMATION_REQUEST"}, set(json.loads(delta.verified_claim)["claims"]))
        self.assertNotIn(HISTORICAL_QUESTION, fx.factory.path.read_text())
        before = hashlib.sha256(fx.factory.path.read_bytes()).hexdigest()
        self.assertEqual("REPLAY", fx.ask()["status"])
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual(before, hashlib.sha256(fx.factory.path.read_bytes()).hexdigest())

    def test_repair_packet_rejects_cross_owner_cross_case_and_second_consumption(self):
        fx = self.fixture()
        wrong = correct_answer(); del wrong["claims"]["SECTOR_EXCEPTION"]
        native = fx.learning.native
        principal = fx.core.local_operator(Capability.READ)
        packet, receipt, _ = native.integrity.build_nachwg(principal, fx.learning, wrong, trace_id="one-case")
        other = self.fixture(scope=OwnerScope("other-tenant", "other-owner", "other-space", "other-slot"))
        with self.assertRaises(Exception):
            native.integrity.consume_nachwg(other.core.local_operator(Capability.READ), fx.learning,
                                            packet, receipt, wrong, trace_id="one-case")
        with self.assertRaises(Exception):
            native.integrity.consume_nachwg(principal, fx.learning, packet, receipt, wrong, trace_id="another-case")
        native.integrity.consume_nachwg(principal, fx.learning, packet, receipt, wrong, trace_id="one-case")
        with self.assertRaises(Exception):
            native.integrity.consume_nachwg(principal, fx.learning, packet, receipt, wrong, trace_id="one-case")
        self.assertEqual([], fx.transport.calls)

    def test_failed_repair_has_no_third_call_and_no_knowledge_write(self):
        wrong = correct_answer(); del wrong["claims"]["ACCESSIBILITY"]
        fx = self.fixture(replies=[wrong, wrong]); fx.consent()
        result = fx.ask()
        self.assertEqual("STOP", result["status"])
        self.assertEqual("CORE_FINAL_CHECK_FAILED", result["reason"])
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_actor_self_authorization_is_unknown_and_blocks_subsequent_episode(self):
        wrong = correct_answer(); wrong["VERIFIED"] = True
        fx = self.fixture(replies=[wrong])
        self.assertEqual("INVALID_PROVIDER_RESPONSE", fx.ask()["reason"])
        journal = fx.runtime._lite_scheduler.journal
        before = journal.reservations()
        self.assertEqual("UNKNOWN", before[0]["status"])
        self.assertEqual("RECONCILE_READONLY_REQUIRED", fx.ask("new-episode")["reason"])
        self.assertEqual(before, journal.reservations())
        self.assertEqual(1, len(fx.transport.calls))

    def test_revoked_evidence_cannot_produce_packet_or_verified_answer(self):
        fx = self.fixture()
        evidence_id, record = next(iter(fx.catalog.records.items()))
        fx.catalog.records[evidence_id] = replace(record, withdrawn=True)
        with self.assertRaises(Exception): fx.learning.review_nachwg(correct_answer())
        wrong = correct_answer(); del wrong["claims"]["ACCESSIBILITY"]
        with self.assertRaises(Exception):
            fx.learning.native.integrity.build_nachwg(fx.core.local_operator(Capability.READ),
                                                      fx.learning, wrong, trace_id="revoked")

    def test_case_uses_existing_scheduler_mutex(self):
        fx = self.fixture()
        scheduler = fx.runtime._lite_scheduler
        scheduler._mutex.acquire()
        try:
            with self.assertRaisesRegex(Exception, "SCHEDULER_BUSY"): fx.ask()
        finally:
            scheduler._mutex.release()
        self.assertEqual([], fx.transport.calls)

    def test_changed_source_with_same_anchors_cannot_reuse_reviewed_rule(self):
        fx = self.fixture()
        review = fx.learning.review_nachwg(correct_answer())
        sources = tuple((*s[:3], s[3] + " This document now contradicts the prior rule.")
                        if s[0] == "nachwg_2" else s for s in review["sources"])
        self.assertFalse(fx.learning.verify(json.dumps(correct_answer()), sources)[0])

    def test_forged_learning_callback_cannot_obtain_integrity_receipt(self):
        from types import SimpleNamespace
        fx = self.fixture()
        fake = SimpleNamespace(native=fx.learning.native, policy=fx.learning.policy,
                               review_nachwg=lambda answer: {"status": "REPAIR_REQUIRED"})
        with self.assertRaises(Exception):
            fx.learning.native.integrity.build_nachwg(fx.core.local_operator(Capability.READ),
                                                      fake, correct_answer(), trace_id="forged")
        self.assertEqual([], fx.transport.calls)

    def test_restart_preserves_initial_replay_without_second_call(self):
        fx = self.fixture()
        self.assertEqual("VERIFIED", fx.ask()["status"])
        fx.runtime.close()
        resumed = NachwgFixture(fx.root)
        self.addCleanup(resumed.close)
        self.assertEqual("REPLAY", resumed.ask()["status"])
        self.assertEqual([], resumed.transport.calls)
