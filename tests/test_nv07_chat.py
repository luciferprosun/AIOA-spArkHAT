"""NV07 contract acceptance with explicit offline actors, never G07_LIVE."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from nv07_support import ChatFixture, QUESTION, RIGHT, TASK, WRONG
from runtime.core_admission import AdmissionError, Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.learning.personal_contracts import (
    ConsentMode, CorrectionMode, DomainSemantics, SemanticDeltaKind,
)
from runtime.mission.contracts import MissionError
from runtime.mission.lite_chat import ACTOR_REPAIR_JSON_EXAMPLE


class NativeAtomicBoundaryTests(unittest.TestCase):
    def test_repository_compound_denied_and_atomic_required_packet_supported(self):
        from nv07_support import SOURCE
        from runtime.memory_patch.correction.claims import (
            ClaimAtomicity, ClaimEvidenceCandidateStatus, ClaimEvidenceRelation,
            ClaimType, NativeDraft, classify_claim, extract_native_claims,
        )
        from runtime.memory_patch.correction.packets import (
            CorrectionAction, RequiredCorrection,
        )
        from runtime.memory_patch.errors import ErrorCode, MemoryPatchError

        for text, atomicity in (
            (SOURCE["examples"][0]["expected_effect"], ClaimAtomicity.COMPOUND),
            (SOURCE["description"], ClaimAtomicity.ATOMIC),
        ):
            with self.subTest(atomicity=atomicity.value), tempfile.TemporaryDirectory() as root:
                class SourceFixture(ChatFixture):
                    def add_source(self, source_id, version, value, **kwargs):
                        if value == "The reviewed policy applies.":
                            value = text
                        return super().add_source(source_id, version, value, **kwargs)

                fx = SourceFixture(Path(root), oracle=text, proposal=text)
                try:
                    review = fx.learning.review_claim(WRONG, CorrectionMode.HAT_ONLY)
                    self.assertEqual("VERIFIED_CORRECTION", review["status"])
                    bundle = review["context"].canonical_bundle
                    self.assertEqual(1, len(bundle.items))
                    self.assertEqual(text, bundle.items[0].excerpt.text)
                    self.assertEqual("OFFICIAL_PRIMARY", bundle.items[0].authority_level.value)
                    self.assertEqual((ClaimType.FACTUAL, atomicity), classify_claim(text))
                    native = fx.learning.native
                    principal = fx.core.local_operator(Capability.READ)
                    corrected = NativeDraft(fx.scope, "test-hat", "atomic-boundary", text)
                    analysis = native.claims.assess(principal, corrected, bundle)
                    self.assertEqual(1, len(analysis.assessments))
                    assessment = analysis.assessments[0]
                    self.assertTrue(any(link.relation is ClaimEvidenceRelation.SUPPORTS
                                        and link.exact_source_text == text
                                        for link in assessment.links))
                    original = NativeDraft(fx.scope, "test-hat", "original-boundary", WRONG)
                    correction = RequiredCorrection(
                        extract_native_claims(original)[0].claim_id,
                        CorrectionAction.REPLACE, WRONG, text,
                        (bundle.items[0].item_hash,),
                    )
                    if atomicity is ClaimAtomicity.COMPOUND:
                        self.assertEqual(ClaimEvidenceCandidateStatus.UNVERIFIED, assessment.status)
                        self.assertTrue(analysis.review_required)
                        with self.assertRaises(MemoryPatchError) as denied:
                            native.integrity.build_required(principal, original, bundle, correction)
                        self.assertEqual(ErrorCode.EVIDENCE_DENIED, denied.exception.code)
                    else:
                        self.assertEqual(ClaimEvidenceCandidateStatus.SUPPORTED, assessment.status)
                        self.assertFalse(analysis.review_required)
                        packet, receipt = native.integrity.build_required(
                            principal, original, bundle, correction)
                        native.integrity.verify(principal, packet, receipt)
                        self.assertEqual((correction,), packet.corrections)
                        self.assertFalse(packet.review_required)
                finally:
                    fx.close()


class PrivateChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.count = 0

    def fixture(self, **kwargs):
        self.count += 1
        fx = ChatFixture(self.root / str(self.count), **kwargs)
        self.addCleanup(fx.close)
        return fx

    def test_new_private_user_has_no_implicit_grant_or_delta(self):
        fx = self.fixture(replies=(RIGHT,))
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        self.assertEqual((), fx.learning.records("DELTA"))
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual("PRIVATE", result["privacy_scope"])
        self.assertFalse(result["execution_authority"])

    def test_unknown_or_forged_user_cannot_reach_actor_or_memory(self):
        fx = self.fixture()
        principal = fx.core.local_operator(Capability.READ)
        for invalid in (None, {"owner": fx.scope.owner_id},
                        replace(principal, scope=replace(fx.scope, owner_id="attacker")),
                        fx.core.critic_candidate()):
            with self.subTest(kind=type(invalid).__name__), self.assertRaises(AdmissionError):
                fx.runtime.lite_chat(invalid, QUESTION, operation_id="forged",
                                     mode=CorrectionMode.HAT_ONLY)
        self.assertEqual([], fx.transport.calls)
        self.assertEqual([], fx.runtime._lite_scheduler.journal.reservations())
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_linux_packet_returns_to_same_bound_actor_before_minimal_write(self):
        fx = self.fixture()
        fx.consent()
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("CREATED", result["knowledge_write"])
        self.assertEqual(2, result["actor_calls"])
        self.assertEqual(("ACTOR_INITIAL", "CORE_CLAIM_CHECK", "CORRECTION_PACKET",
                          "ACTOR_REPAIR", "CORE_FINAL_CHECK"), result["phases"])
        requests = [json.loads(v["messages"][-1]["content"]) for v in fx.transport.calls]
        self.assertEqual("ACTOR_INITIAL", requests[0]["phase"])
        self.assertEqual("ACTOR_REPAIR", requests[1]["phase"])
        self.assertEqual(fx.transport.calls[0]["model"], fx.transport.calls[1]["model"])
        self.assertEqual(fx.profile.model_id, fx.transport.calls[1]["model"])
        self.assertEqual({"type": "json_object"}, fx.transport.calls[0]["response_format"])
        self.assertEqual({"type": "json_object"}, fx.transport.calls[1]["response_format"])
        self.assertEqual(requests[0]["actor_output_contract"],
                         requests[1]["actor_output_contract"])
        contract = requests[1]["actor_output_contract"]
        self.assertEqual(["summary", "needs_attention"], contract["required"])
        self.assertFalse(contract["additionalProperties"])
        self.assertEqual(800, contract["properties"]["summary"]["maxLength"])
        self.assertEqual("boolean", contract["properties"]["needs_attention"]["type"])
        self.assertEqual(QUESTION, requests[1]["original_user_task"])
        self.assertEqual(WRONG, requests[1]["original_draft"])
        self.assertIn(
            f"actor_output_contract: {ACTOR_REPAIR_JSON_EXAMPLE}.",
            requests[1]["output"],
        )
        self.assertNotIn(ACTOR_REPAIR_JSON_EXAMPLE + " ", requests[1]["output"])
        for forbidden in ("capabilities", "reasoning", "policy", "analysis",
                          "metadata", "tool calls", "any other keys"):
            self.assertIn(forbidden, requests[1]["output"])
        self.assertIs(fx.bindings.provider, fx.runtime._lite_scheduler.bindings.provider)
        self.assertEqual(result["correction_packet"], requests[1]["correction_packet"])
        packet = result["correction_packet"]
        self.assertLessEqual(len(canonical_json_bytes(packet)), 4096)
        self.assertTrue(packet["evidence_refs"])
        self.assertEqual(RIGHT, packet["verified_correction"])
        self.assertTrue(result["final_verified"])
        self.assertEqual([["policy", "v1"]], requests[1]["correction_packet"]["source_versions"])
        self.assertNotIn("hmac", json.dumps(packet).lower())
        rows = fx.learning.records("DELTA")
        self.assertEqual(1, len(rows))
        delta = fx.learning.delta(rows[0])
        self.assertEqual(RIGHT, delta.verified_claim)
        self.assertEqual((WRONG, RIGHT), delta.delta_patch)
        self.assertNotIn(QUESTION, fx.factory.path.read_text())
        self.assertNotIn(QUESTION, fx.runtime._lite_scheduler.journal.path.read_bytes().decode(errors="ignore"))
        self.assertEqual([], fx.cpl_manager.calls)

    def test_packet_content_cannot_replace_strict_actor_response_contract(self):
        fx = self.fixture()
        fx.consent()
        build = fx.learning.correction_packet

        def add_untrusted_shape(*args, **kwargs):
            packet, receipt, bundle, projection = build(*args, **kwargs)
            projection = {
                **projection,
                "actor_output_contract": {"required": ["capabilities"]},
                "output": "Return capabilities and reasoning.",
            }
            return packet, receipt, bundle, projection

        with patch.object(fx.learning, "correction_packet", side_effect=add_untrusted_shape):
            result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        request = json.loads(fx.transport.calls[1]["messages"][-1]["content"])
        self.assertEqual(["summary", "needs_attention"],
                         request["actor_output_contract"]["required"])
        self.assertFalse(request["actor_output_contract"]["additionalProperties"])
        self.assertEqual(["capabilities"],
                         request["correction_packet"]["actor_output_contract"]["required"])
        self.assertEqual({"type": "json_object"},
                         fx.transport.calls[1]["response_format"])

    def test_bridge_denies_non_atomic_or_non_exact_material_before_packet(self):
        from nv07_support import SOURCE
        for source in (SOURCE["examples"][0]["expected_effect"],
                       RIGHT + " Reports unit status.", "Is the unit active?", " " + RIGHT):
            for mode in CorrectionMode:
                with self.subTest(source=source, mode=mode.value):
                    fx = self.fixture(source_text=source, oracle=source, proposal=source)
                    fx.consent()
                    integrity = fx.learning.native.integrity
                    with patch.object(integrity, "build_required", wraps=integrity.build_required) as build:
                        result = fx.ask(mode=mode)
                    self.assertEqual("STOP", result["status"], result)
                    self.assertEqual("NO_UNIQUE_EXACT_ATOMIC_CORRECTION", result["reason"])
                    self.assertEqual("CORE_CLAIM_CHECK", result["phases"][-1])
                    build.assert_not_called()
                    self.assertEqual(1, len(fx.transport.calls))
                    self.assertEqual(5 if mode.requires_critics else 0, len(fx.cpl_manager.calls))
                    self.assertEqual((), fx.learning.records("DELTA"))

    def test_bridge_denies_ambiguous_exact_atomic_candidates_before_packet(self):
        from runtime.memory_patch.learning.contracts import RegisteredRuleVerifier, VerificationVerdict
        other = "Reports current service state."
        fx = self.fixture()
        fx.add_source("other", "v1", other)
        fx.learning.policy = replace(fx.learning.policy, source_ids=("other", "policy"))
        rules = tuple(RegisteredRuleVerifier(
            fx.scope, TASK, text, (("other", "v1"), ("policy", "v1")),
            fx.now + timedelta(days=1)) for text in (RIGHT, other))

        class ControlledRuleSet:
            def verify(self, request):
                return VerificationVerdict(request.digest,
                                           any(rule.verify(request).supported for rule in rules))

        fx.learning.verifiers = tuple(
            replace(binding, verifier=ControlledRuleSet())
            if binding.verifier_ref == "controlled-domain-rule" else binding
            for binding in fx.learning.verifiers)
        review = fx.learning.review_claim(WRONG, CorrectionMode.CPL_ONLY, proposal=RIGHT)
        self.assertEqual("VERIFIED_CORRECTION", review["status"])
        self.assertEqual(2, len(review["context"].canonical_bundle.items))
        integrity = fx.learning.native.integrity
        with patch.object(integrity, "build_required", wraps=integrity.build_required) as build:
            with self.assertRaisesRegex(MissionError, "NO_UNIQUE_EXACT_ATOMIC_CORRECTION"):
                fx.learning.correction_packet(review, "ambiguous-atomic")
        build.assert_not_called()
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_correct_answer_does_not_force_a_repair(self):
        fx = self.fixture(replies=(RIGHT,))
        fx.consent()
        result = fx.ask(mode=CorrectionMode.HYBRID)
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual([], fx.cpl_manager.calls)
        self.assertNotIn("ACTOR_REPAIR", result["phases"])
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_explicit_style_alias_is_zero_write(self):
        scope = OwnerScope("nv03-tenant", "nv03-owner", "nv03-space", "nv03-slot")
        from test_memory_patch_persistence_ports import NOW
        style = "Reports service manager status for a unit."
        semantics = DomainSemantics(scope, "test-hat", TASK, (("policy", "v1"),),
                                    NOW + timedelta(days=1), ((style, RIGHT),))
        fx = self.fixture(replies=(style,), semantics=semantics)
        fx.consent()
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_each_semantic_kind_survives_closed_loop(self):
        from test_memory_patch_persistence_ports import NOW
        scope = OwnerScope("nv03-tenant", "nv03-owner", "nv03-space", "nv03-slot")
        for kind in SemanticDeltaKind:
            with self.subTest(kind=kind.value):
                condition = ("for a unit" if kind in (
                    SemanticDeltaKind.ADD_MISSING_CONDITION, SemanticDeltaKind.QUALIFY) else None)
                semantics = DomainSemantics(scope, "test-hat", TASK, (("policy", "v1"),),
                                            NOW + timedelta(days=1), delta_kind=kind,
                                            required_condition=condition)
                fx = self.fixture(semantics=semantics)
                fx.consent()
                result = fx.ask()
                self.assertEqual("CREATED", result["knowledge_write"], result)
                self.assertEqual("VERIFIED", result["status"])
                self.assertEqual(2, result["actor_calls"])
                self.assertTrue(result["final_verified"])
                self.assertEqual(kind.value, result["correction_packet"]["delta_kind"])
                self.assertEqual(condition, result["correction_packet"]["required_condition"])
                if condition is not None:
                    self.assertIn(condition, result["answer"])
                self.assertEqual(kind, fx.learning.delta(fx.learning.records("DELTA")[0]).delta_kind)

    def test_cpl_and_hybrid_keep_five_calls_plus_distinct_actor_repair(self):
        for mode in (CorrectionMode.CPL_ONLY, CorrectionMode.HYBRID):
            with self.subTest(mode=mode.value):
                fx = self.fixture()
                fx.consent()
                result = fx.ask(mode=mode)
                self.assertEqual("CREATED", result["knowledge_write"], result)
                self.assertEqual(5, len(fx.cpl_manager.calls))
                self.assertEqual(2, len(fx.transport.calls))
                self.assertEqual(3, sum(r.response_schema_json is not None for r in fx.cpl_manager.calls))
                self.assertEqual(0, result["critic_independent_proofs"])

    def test_hat_only_works_without_critics(self):
        fx = self.fixture(critic=False)
        fx.consent()
        result = fx.ask()
        self.assertEqual("CREATED", result["knowledge_write"], result)
        self.assertEqual([], fx.cpl_manager.calls)

    def test_cpl_outage_does_not_fall_back_or_learn(self):
        fx = self.fixture(critic=False)
        fx.consent()
        result = fx.ask(mode=CorrectionMode.CPL_ONLY)
        self.assertEqual("STOP", result["status"])
        self.assertEqual("CPL_PROPOSAL_UNAVAILABLE", result["reason"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_critic_agreement_without_independent_proof_is_zero_write(self):
        fx = self.fixture(oracle="Unsupported controlled rule.")
        fx.consent()
        result = fx.ask(mode=CorrectionMode.HYBRID)
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("INDEPENDENT_VERIFICATION_NOT_MET", result["reason"])
        self.assertEqual(5, len(fx.cpl_manager.calls))
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_bad_actor_repair_stops_without_delta_or_second_repair(self):
        fx = self.fixture(replies=(WRONG, WRONG), dynamics=True)
        fx.consent()
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("ACTOR_REPAIR_UNVERIFIED", result["reason"])
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual((), fx.learning.records("PHEROMONE_EVENT"))
        self.assertEqual("REPLAY", fx.ask()["status"])
        self.assertEqual(2, len(fx.transport.calls))

    def test_replay_changes_no_delta_reward_counter_or_journal(self):
        fx = self.fixture(dynamics=True)
        fx.consent()
        result = fx.ask()
        self.assertEqual("CREATED", result["knowledge_write"], result)
        before = fx.factory.path.read_bytes()
        reservations = fx.runtime._lite_scheduler.journal.reservations()
        result = fx.ask(question="A different wording with the same operation id.")
        self.assertEqual("REPLAY", result["status"])
        self.assertEqual(0, result["actor_calls"])
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual(reservations, fx.runtime._lite_scheduler.journal.reservations())

    def test_off_and_manual_never_auto_write(self):
        for mode in (ConsentMode.OFF, ConsentMode.MANUAL):
            with self.subTest(mode=mode.value):
                fx = self.fixture(dynamics=True)
                if mode is ConsentMode.MANUAL:
                    fx.consent(mode)
                result = fx.ask()
                self.assertEqual("VERIFIED", result["status"], result)
                self.assertEqual("ZERO_WRITE", result["knowledge_write"])
                for state in ("DELTA", "OVERLAY", "PHEROMONE_EVENT"):
                    self.assertEqual((), fx.learning.records(state))

    def test_revocation_hides_previously_approved_delta_from_actor(self):
        fx = self.fixture(dynamics=True)
        fx.consent()
        result = fx.ask()
        self.assertEqual("CREATED", result["knowledge_write"], result)
        fx.consent(ConsentMode.OFF)
        before = fx.factory.path.read_bytes()
        result = fx.ask("after-revoke")
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        request = json.loads(fx.transport.calls[-1]["messages"][-1]["content"])
        self.assertNotIn("VERIFIED_DELTA_ADVISORY", json.dumps(request))
        self.assertEqual(before, fx.factory.path.read_bytes())

    def test_revocation_during_repair_prevents_write(self):
        fx = self.fixture()
        fx.consent()
        def before():
            if len(fx.transport.calls) == 1:
                fx.consent(ConsentMode.OFF)
        fx.transport.before = before
        result = fx.ask()
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual(2, len(fx.transport.calls))
        self.assertTrue(result["final_verified"])
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        self.assertEqual("ZERO_WRITE", result["knowledge_write"], result)
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_final_core_check_rejects_source_withdrawn_during_repair(self):
        fx = self.fixture()
        fx.consent()
        def before():
            if len(fx.transport.calls) == 1:
                for key, record in list(fx.catalog.records.items()):
                    fx.catalog.records[key] = replace(record, withdrawn=True)
        fx.transport.before = before
        native = fx.learning.native
        with patch.object(native.claims, "assess", wraps=native.claims.assess) as assess:
            result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("ACTOR_REPAIR_UNVERIFIED", result["reason"])
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual("CORE_FINAL_CHECK", result["phases"][-1])
        self.assertEqual(RIGHT, assess.call_args.args[1].text)
        self.assertTrue(all(record.withdrawn for record in fx.catalog.records.values()))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_version_change_blocks_stale_delta_despite_dynamics(self):
        fx = self.fixture(dynamics=True)
        fx.consent()
        first = fx.ask()
        self.assertEqual("CREATED", first["knowledge_write"], first)
        fx.change_source_version()
        context = fx.runtime.lite_memory_retrieve(QUESTION)
        self.assertFalse(any(r.lane == "VERIFIED_DELTA_ADVISORY" for r in context.selected))
        row = fx.learning.records("DELTA")[0]
        self.assertEqual("REVALIDATION_REQUIRED", row.payload["reuse_status"])
        result = fx.ask("source-v2")
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("INDEPENDENT_VERIFICATION_NOT_MET", result["reason"])
        self.assertEqual(1, result["actor_calls"])
        self.assertEqual(1, len(fx.learning.records("DELTA")))

    def test_protected_values_block_question_and_actor_output(self):
        secret = "controlled\nprivate\"value"
        fx = self.fixture(private_values=(secret,))
        with self.assertRaisesRegex(MissionError, "FORBIDDEN_SECRET_MATERIAL"):
            fx.ask(question="Question " + secret)
        self.assertEqual([], fx.transport.calls)
        self.assertEqual([], fx.runtime._lite_scheduler.journal.reservations())
        from nv07_support import reply
        fx.transport.replies = [reply(secret)]
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("FORBIDDEN_SECRET_MATERIAL", result["reason"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_unknown_provider_outcome_is_not_replayed_after_restart(self):
        fx = self.fixture(replies=(TimeoutError(),))
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        fx.close()
        restarted = ChatFixture(fx.root, replies=(RIGHT,))
        self.addCleanup(restarted.close)
        self.assertEqual("REPLAY", restarted.ask()["status"])
        self.assertEqual("RECONCILE_READONLY_REQUIRED", restarted.ask("other")["reason"])
        self.assertEqual([], restarted.transport.calls)

    def test_truncated_actor_repair_is_unknown_immutable_and_never_retried(self):
        from nv07_support import reply
        from test_nv02_lite import success

        fx = self.fixture()
        fx.consent()
        fx.transport.replies = [
            reply(WRONG),
            success(choices=[{"finish_reason": "length", "message": {
                "content": '{"capabilities":["PERSON_INFO","PERSONAL',
            }}]),
        ]
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("ACTOR_REPAIR_UNVERIFIED", result["reason"])
        self.assertEqual("TRUNCATED_RESPONSE", result["provider_cause"])
        self.assertEqual(2, result["actor_calls"])
        reservations = fx.runtime._lite_scheduler.journal.reservations()
        self.assertEqual(["COMMITTED", "UNKNOWN"],
                         [record["status"] for record in reservations])
        self.assertEqual("TRUNCATED_RESPONSE", reservations[1]["reason"])
        self.assertIsNone(reservations[1]["actual_units"])
        with self.assertRaisesRegex(MissionError, "INVALID_RESERVATION_TRANSITION"):
            fx.runtime._lite_scheduler.journal.settle(
                reservations[1]["reservation_id"], "RELEASED",
                reason="INVALID_CLEAR_ATTEMPT",
            )
        self.assertEqual(reservations,
                         fx.runtime._lite_scheduler.journal.reservations())
        followup = fx.ask("fresh-after-unknown")
        self.assertEqual("STOP", followup["status"], followup)
        self.assertEqual("RECONCILE_READONLY_REQUIRED", followup["reason"])
        self.assertEqual(2, len(fx.transport.calls))

    def test_budget_is_committed_before_both_actor_transports(self):
        import sqlite3
        fx = self.fixture()
        fx.consent()
        observed = []
        def before():
            with sqlite3.connect(fx.runtime._lite_scheduler.journal.path) as db:
                observed.append(db.execute("SELECT count(*) FROM reservations WHERE status='RESERVED'").fetchone()[0])
        fx.transport.before = before
        result = fx.ask()
        self.assertEqual("CREATED", result["knowledge_write"], result)
        self.assertEqual([1, 1], observed)

    def test_exhausted_actor_budget_cannot_reach_repair_or_learning(self):
        fx = self.fixture(requests=1)
        fx.consent()
        journal = fx.runtime._lite_scheduler.journal
        rejected = []
        reserve = journal.reserve_actor_repair
        def observe_budget(*args):
            try:
                return reserve(*args)
            except MissionError as error:
                rejected.append(error.code)
                raise
        with patch.object(journal, "reserve_actor_repair", side_effect=observe_budget):
            result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual(["BUDGET_EXHAUSTED"], rejected)
        self.assertIn("CORRECTION_PACKET", result["phases"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_byte_limit_rolls_back_delta(self):
        from runtime.memory_patch.errors import MemoryPatchError
        fx = self.fixture(max_bytes=1024)
        fx.consent()
        before = fx.factory.path.read_bytes()
        rejected = []
        transactions = fx.learning.native.transactions
        run = transactions.run
        def observe_transaction(*args, **kwargs):
            try:
                return run(*args, **kwargs)
            except MemoryPatchError as error:
                if isinstance(error.__cause__, MissionError):
                    rejected.append(error.__cause__.code)
                raise
        with patch.object(transactions, "run", side_effect=observe_transaction):
            result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("TRANSACTION_FAILED", result["reason"])
        self.assertEqual(["PERSONAL_DELTA_BYTE_QUOTA"], rejected)
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual("CORE_FINAL_CHECK", result["phases"][-1])
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual((), fx.learning.records("OVERLAY"))

    def test_actor_binding_change_after_packet_blocks_repair_transport(self):
        fx = self.fixture()
        other = self.fixture()
        fx.consent()
        build = fx.learning.correction_packet
        def change_binding(*args):
            packet = build(*args)
            scheduler = fx.runtime._lite_scheduler
            scheduler.bindings = replace(scheduler.bindings, provider=other.bindings.provider)
            return packet
        with patch.object(fx.learning, "correction_packet", side_effect=change_binding):
            result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("ACTOR_BINDING_CHANGED", result["reason"])
        self.assertIn("CORRECTION_PACKET", result["phases"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual([], other.transport.calls)
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_final_core_rule_check_can_reject_native_supported_actor_repair(self):
        fx = self.fixture()
        fx.consent()
        def before():
            if len(fx.transport.calls) == 1:
                fx.learning.verifiers = tuple(
                    replace(binding, verifier=replace(binding.verifier, expected_claim=WRONG))
                    if binding.verifier_ref == "controlled-domain-rule" else binding
                    for binding in fx.learning.verifiers)
        fx.transport.before = before
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("CORE_FINAL_CHECK_FAILED", result["reason"])
        self.assertEqual(2, len(fx.transport.calls))
        self.assertEqual("CORE_FINAL_CHECK", result["phases"][-1])
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_protected_value_from_core_alias_cannot_escape_chat(self):
        fx = self.fixture(replies=("The controlled alias.",))
        fx.consent()
        fx.personal.policy = replace(fx.personal.policy, semantics=DomainSemantics(
            fx.scope, "test-hat", TASK, (("policy", "v1"),),
            fx.now + timedelta(hours=1), (("The controlled alias.", RIGHT),)))
        def protect_after_initial_request():
            fx.learning.native.dependencies = replace(
                fx.learning.native.dependencies, private_values=(RIGHT,))
        fx.transport.before = protect_after_initial_request
        result = fx.ask()
        self.assertEqual("STOP", result["status"], result)
        self.assertEqual("FORBIDDEN_SECRET_MATERIAL", result["reason"])
        self.assertEqual(1, len(fx.transport.calls))
        self.assertEqual(("ACTOR_INITIAL",), result["phases"])
        self.assertNotIn(RIGHT, json.dumps(result))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_neutral_delta_reused_under_new_model_version_without_new_delta(self):
        fx = self.fixture()
        fx.consent()
        first = fx.ask()
        self.assertEqual("CREATED", first["knowledge_write"], first)
        original_model = fx.learning.delta(fx.learning.records("DELTA")[0]).model
        fx.close()
        restarted = ChatFixture(fx.root, replies=(RIGHT,), revision=2,
                                model_version="controlled-new-model-version")
        self.addCleanup(restarted.close)
        self.assertNotEqual(original_model, restarted.learning.policy.actor)
        result = restarted.ask("new-model-session")
        self.assertEqual("VERIFIED", result["status"], result)
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual(1, len(restarted.learning.records("DELTA")))
        request = json.loads(restarted.transport.calls[0]["messages"][-1]["content"])
        self.assertIn(first["delta_id"], json.dumps(request["quoted_advisory_context"]))

    def test_concurrent_users_share_store_without_read_cache_score_or_log_leak(self):
        a = self.fixture(dynamics=True)
        b = self.fixture(scope=replace(a.scope, owner_id="user-b"), replies=(RIGHT,), dynamics=True)
        shared = self.root / "shared-memory.json"
        a.factory.path = b.factory.path = shared
        a.consent()
        b.consent()
        with ThreadPoolExecutor(max_workers=2) as pool:
            fa, fb = pool.submit(a.ask), pool.submit(b.ask)
            ra, rb = fa.result(timeout=20), fb.result(timeout=20)
        self.assertEqual("CREATED", ra["knowledge_write"], ra)
        self.assertEqual("ZERO_WRITE", rb["knowledge_write"], rb)
        self.assertEqual((), b.learning.records("DELTA"))
        self.assertEqual((), b.learning.records("OVERLAY"))
        self.assertEqual((), b.learning.records("PHEROMONE_EVENT"))
        context = b.runtime.lite_memory_retrieve(QUESTION)
        observable = json.dumps({"result": rb, "context": context.prompt_json,
                                  "scores": b.learning.storage_metrics(),
                                  "log": b.runtime._lite_scheduler.journal.evidence(),
                                  "calls": b.transport.calls})
        self.assertNotIn(ra["delta_id"], observable)
        self.assertNotIn(ra["personal_space_ref"], observable)
        with self.assertRaises(AdmissionError):
            b.ask("cross-principal", principal=a.core.local_operator(Capability.READ))
        a.close()
        b.close()
        # A separate interpreter must retain the same owner isolation in the
        # shared durable store, including context, scores and journal projection.
        code = '''import json,sys
from pathlib import Path
from nv07_support import ChatFixture, RIGHT, QUESTION
from runtime.core_admission import OwnerScope
fx=ChatFixture(Path(sys.argv[1]), scope=OwnerScope(**json.loads(sys.argv[3])), replies=(RIGHT,), dynamics=True)
fx.factory.path=Path(sys.argv[2])
replay=fx.ask()
result=fx.ask("user-b-after-restart")
context=fx.runtime.lite_memory_retrieve(QUESTION)
print(json.dumps({"replay":replay["status"],"result":result,"deltas":len(fx.learning.records("DELTA")),"context":context.prompt_json,"scores":fx.learning.storage_metrics(),"log":fx.runtime._lite_scheduler.journal.evidence(),"calls":fx.transport.calls}))
fx.close()
'''
        from dataclasses import asdict
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(__file__).parent))
        child = subprocess.run(
            [sys.executable, "-B", "-c", "import runtime\n" + code,
             str(b.root), str(shared), json.dumps(asdict(b.scope))],
            env=env, text=True, capture_output=True, timeout=30, check=True)
        observed = json.loads(child.stdout)
        self.assertEqual("REPLAY", observed["replay"])
        self.assertEqual("VERIFIED", observed["result"]["status"], observed)
        self.assertEqual("ZERO_WRITE", observed["result"]["knowledge_write"])
        self.assertEqual(0, observed["deltas"])
        self.assertNotIn(ra["delta_id"], child.stdout)
        self.assertNotIn(ra["personal_space_ref"], child.stdout)

    def test_fresh_process_recovers_delta_and_replay_without_chat_retention(self):
        fx = self.fixture(dynamics=True)
        fx.consent()
        first = fx.ask(question="Private ephemeral question about systemctl status sshd.")
        self.assertEqual("CREATED", first["knowledge_write"], first)
        root = fx.root
        fx.close()
        code = '''import json,sys
from pathlib import Path
from nv07_support import ChatFixture, RIGHT
fx=ChatFixture(Path(sys.argv[1]), replies=(RIGHT,), dynamics=True)
replay=fx.ask()
result=fx.ask("fresh-session", question="Explain the effect of systemctl status sshd.")
request=json.loads(fx.transport.calls[0]["messages"][-1]["content"])
print(json.dumps({"replay":replay["status"],"result":result,"delta_count":len(fx.learning.records("DELTA")),"context":request["quoted_advisory_context"]}))
fx.close()
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]) + os.pathsep + str(Path(__file__).parent))
        child = subprocess.run([sys.executable, "-B", "-c", "import runtime\n" + code, str(root)],
                               env=env, text=True, capture_output=True, timeout=30, check=True)
        observed = json.loads(child.stdout)
        self.assertEqual("REPLAY", observed["replay"])
        self.assertEqual("VERIFIED", observed["result"]["status"], observed)
        self.assertEqual("ZERO_WRITE", observed["result"]["knowledge_write"])
        self.assertEqual(1, observed["delta_count"])
        self.assertIn(first["delta_id"], json.dumps(observed["context"]))
        self.assertNotIn("Private ephemeral question", (root / "memory.json").read_text())


if __name__ == "__main__":
    unittest.main()
