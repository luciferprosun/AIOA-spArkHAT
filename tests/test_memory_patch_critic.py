from __future__ import annotations

import copy
import json
import unittest
from dataclasses import replace
from types import SimpleNamespace

from providers.exact import ProviderResult
from test_memory_patch_correction import CorrectionFixture
from test_memory_patch_lifecycle import MemoryFixture, memory_hat_manifest

from runtime.core_admission import AdmissionError, Capability
from runtime.memory_patch.contracts.enums import MemoryContentKind
from runtime.memory_patch.critic_adapter import NativeCriticAdapter
from runtime.memory_patch.domain_profiles import (
    GERMAN_LAW_FIXTURE_PROFILE,
    DomainProfile,
    require_domain_profile,
)
from runtime.memory_patch.errors import MemoryPatchError
from runtime.memory_patch.hats import NativeHatAdmission
from runtime.memory_patch.persistence.ports import RecordKind
from runtime.memory_patch.provider_adapter import (
    CoreProviderBinding,
    NativeProviderAdapter,
)
from runtime.memory_patch.review import NativeReview, ReviewDecision


class FakeExistingCritic:
    def __init__(self):
        self.calls = []
        self.view = {
            "run_id": "cpl-fixture",
            "execution_status": "COMPLETED",
            "authority": "ADVISORY_ONLY",
            "knowledge_promotion": "DISABLED",
            "human_review_required": True,
            "model_training": "NONE",
            "evidence_chain": {"terminal_hash": "1" * 64},
            "reviews": [],
        }
        for index in range(1, 4):
            self.view["reviews"].append(
                {
                    "slot_id": f"observer-{index}",
                    "role": "Evidence & Consistency",
                    "provider_id": "openrouter",
                    "model_id": "fixture/observer",
                    "execution_status": "COMPLETED",
                    "summary": "A bounded advisory observation.",
                    "findings": [],
                    "uncertainty": [],
                    "evidence_conflicts": [],
                    "snapshot_hash": "2" * 64,
                    "observer_configuration_hash": "3" * 64,
                    "error_category": None,
                    "authority": "METADATA_ONLY_NO_AUTHORITY",
                }
            )
        self.valid = True

    def get(self, run_id):
        self.calls.append("get")
        return copy.deepcopy(self.view)

    def verify(self, run_id, reference_manifest=None):
        self.calls.append("verify")
        return {
            "ok": self.valid,
            "run_id": run_id,
            "terminal_hash": "1" * 64,
            "issues": [],
            "authority": "INTEGRITY_ONLY_NOT_TRUTH",
        }

    def start(self, *args, **kwargs):
        raise AssertionError("Critic adapter must never execute a run")


class CriticAndReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx = MemoryFixture()
        self.addCleanup(self.fx.close)

    def test_existing_critic_is_read_only_and_creates_detected_advice(self):
        fx = self.fx
        port = FakeExistingCritic()
        adapter = NativeCriticAdapter(fx.core, fx.candidates, port)
        result = adapter.candidate_from_run(
            fx.p(Capability.CANDIDATE),
            "cpl-fixture",
            hat_id="test-hat",
            operation_key="critic",
        )
        patch = fx.read(result.outcome["patch_id"])
        self.assertEqual("DETECTED", patch.payload["state"])
        self.assertEqual("CRITIC_PROMPT_LOOP", patch.payload["origin"])
        self.assertEqual(
            MemoryContentKind.MODEL_EXPERIENCE.value,
            patch.payload["candidate"]["content_kind"],
        )
        self.assertEqual(
            "MODEL_EXPERIENCE_HINT", patch.payload["proposal"]["requested_trust_class"]
        )
        self.assertEqual([], fx.rows(RecordKind.APPROVAL))
        self.assertEqual([], fx.rows(RecordKind.RECEIPT))
        self.assertEqual(["get", "verify", "get"], port.calls)
        self.assertEqual(1, fx.rf.catalog.admissions)

    def test_metadata_flags_and_bad_trace_do_not_grant_authority(self):
        fx = self.fx
        for change in ("authority", "extra", "trace", "execution"):
            with self.subTest(change=change):
                port = FakeExistingCritic()
                if change == "authority":
                    port.view["reviews"][0]["authority"] = "APPROVED"
                if change == "extra":
                    port.view["reviews"][0]["approve"] = True
                if change == "trace":
                    port.valid = False
                if change == "execution":
                    port.view["execution_status"] = "FAILED"
                with self.assertRaises(MemoryPatchError):
                    NativeCriticAdapter(
                        fx.core, fx.candidates, port
                    ).candidate_from_run(
                        fx.p(Capability.CANDIDATE),
                        "cpl-fixture",
                        hat_id="test-hat",
                        operation_key=change,
                    )
        self.assertEqual([], fx.rows(RecordKind.PATCH))

    def test_missing_core_port_and_non_owner_requests_deny(self):
        fx = self.fx
        adapter = NativeCriticAdapter(fx.core, fx.candidates)
        with self.assertRaises(MemoryPatchError):
            adapter.candidate_from_run(
                fx.p(Capability.CANDIDATE),
                "cpl-fixture",
                hat_id="test-hat",
                operation_key="missing",
            )
        with self.assertRaises(AdmissionError):
            adapter.candidate_from_run(
                fx.p(Capability.OWNER_APPROVAL),
                "cpl-fixture",
                hat_id="test-hat",
                operation_key="wrong-purpose",
            )

    def test_review_claim_decision_cannot_approve_publish_or_change_patch(self):
        fx = self.fx
        patch_id = fx.detect()
        review = NativeReview(fx.lifecycle, fx.rf.evidence)
        case = review.open_case(
            fx.p(Capability.MANAGE),
            patch_id,
            expected_revision=1,
            operation_key="review-open",
        ).outcome["case_id"]
        reviewer = fx.p(Capability.REVIEW)
        self.assertEqual(1, len(review.queue(reviewer)))
        review.claim(reviewer, case, expected_revision=1, operation_key="review-claim")
        result = review.decide(
            reviewer,
            case,
            expected_revision=2,
            decision=ReviewDecision.ACCEPT_ADVISORY,
            operation_key="review-decision",
        )
        self.assertEqual("DECIDED", result.outcome["state"])
        self.assertEqual("DETECTED", fx.read(patch_id).payload["state"])
        self.assertEqual([], fx.rows(RecordKind.APPROVAL))
        self.assertEqual([], fx.rows(RecordKind.RECEIPT))
        row = fx.rows(RecordKind.REVIEW)[0]
        self.assertFalse(row.payload["approval_authority"])
        self.assertFalse(row.payload["publication_authority"])
        with self.assertRaises(AdmissionError):
            fx.approval.challenge(
                reviewer,
                patch_id,
                expected_revision=1,
                operation_key="reviewer-cannot-approve",
            )

    def test_review_visibility_and_stale_patch_revision(self):
        fx = self.fx
        patch_id = fx.detect()
        review = NativeReview(fx.lifecycle, fx.rf.evidence)
        case = review.open_case(
            fx.p(Capability.MANAGE), patch_id, expected_revision=1, operation_key="open"
        ).outcome["case_id"]
        with self.assertRaises(AdmissionError):
            review.claim(
                fx.p(Capability.MANAGE),
                case,
                expected_revision=1,
                operation_key="owner-not-reviewer",
            )
        fx.rf.catalog.receipts.clear()
        with self.assertRaises(Exception):
            review.queue(fx.p(Capability.REVIEW))

    def test_hat_selection_and_profile_are_bound_without_authority(self):
        fx = self.fx
        p = fx.p(Capability.READ)
        binding = fx.hats.selected(p, "test-hat")
        profile = DomainProfile("fixture", "1", "test-hat", "source-v1", "temporal-v1")
        require_domain_profile(fx.core, p, binding, profile)
        with self.assertRaises(MemoryPatchError):
            require_domain_profile(fx.core, p, binding, GERMAN_LAW_FIXTURE_PROFILE)
        with self.assertRaises(MemoryPatchError):
            replace(profile, version="latest")
        empty = NativeHatAdmission(
            fx.core,
            SimpleNamespace(active_hat=lambda: None),
            (memory_hat_manifest(),),
            quota=fx.quota,
        )
        with self.assertRaises(MemoryPatchError):
            empty.selected(p, "test-hat")
        with self.assertRaises(Exception):
            replace(memory_hat_manifest().security_policy, private_memory_access=True)


class ExactProviderTests(unittest.TestCase):
    def setUp(self):
        self.fx = CorrectionFixture()
        self.packet, self.receipt = self.fx.integrity.build(
            self.fx.principal,
            self.fx.draft("The reviewed policy applies."),
            self.fx.bundle,
        )
        fx = self.fx

        class ExistingManager:
            def __init__(self):
                self.requests = []
                self.result = None

            def generate_exact(self, request, cancel, deadline):
                self.requests.append(request)
                request.validate()
                cancel.check(deadline)
                text = "The reviewed policy applies."
                content = json.dumps(
                    {
                        "text": text,
                        "citations": [
                            {"start": 0, "end": len(text), "source": "citation_1"}
                        ],
                    }
                )
                return self.result or ProviderResult(
                    content,
                    "openrouter",
                    request.requested_model,
                    request.requested_model,
                    "EXACT_MATCH",
                    None,
                    None,
                    "stop",
                    "TEST",
                )

            def generate(self, *args):
                raise AssertionError("No fallback provider path")

        self.manager = ExistingManager()
        self.binding = CoreProviderBinding("test-model", "fixture/primary")
        self.adapter = NativeProviderAdapter(fx.core, self.manager, self.binding)

    def test_same_manager_exact_model_no_private_scope_in_prompt(self):
        fx = self.fx
        value = self.adapter.draft(fx.principal, self.packet, fx.bundle, attempt=1)
        self.assertIs(self.manager, self.adapter.manager)
        self.assertEqual(1, len(self.manager.requests))
        request = self.manager.requests[0]
        self.assertEqual("TEST", request.transport_scope)
        self.assertEqual("fixture/primary", request.requested_model)
        text = "\n".join(m.content for m in request.messages)
        for private in fx.principal.scope.binding() + (fx.principal.actor_session_id,):
            self.assertNotIn(private, text)
        self.assertTrue(
            fx.verifier.verify(
                fx.principal, value, self.packet, self.receipt, fx.bundle
            ).verified
        )

    def test_unconfigured_live_and_wrong_model_binding_deny_before_call(self):
        fx = self.fx
        with self.assertRaises(MemoryPatchError):
            NativeProviderAdapter(fx.core, self.manager).draft(
                fx.principal, self.packet, fx.bundle, attempt=1
            )
        with self.assertRaises(MemoryPatchError):
            CoreProviderBinding("test-model", "fixture/primary", transport_scope="LIVE")
        wrong = NativeProviderAdapter(
            fx.core, self.manager, replace(self.binding, binding_id="other-model")
        )
        with self.assertRaises(MemoryPatchError):
            wrong.draft(fx.principal, self.packet, fx.bundle, attempt=1)
        self.assertEqual([], self.manager.requests)

    def test_response_identity_and_closed_json_fail_without_fallback(self):
        fx = self.fx
        good = ProviderResult(
            "{}",
            "openrouter",
            "fixture/primary",
            "fixture/primary",
            "EXACT_MATCH",
            None,
            None,
            "stop",
            "TEST",
        )
        for changed in (
            replace(good, reported_model="fixture/other"),
            replace(good, identity_status="UNKNOWN"),
            replace(good, content='{"text":"one","text":"two","citations":[]}'),
            replace(good, content='{"text":"one","citations":[],"approve":true}'),
        ):
            self.manager.result = changed
            with self.assertRaises(MemoryPatchError):
                self.adapter.draft(fx.principal, self.packet, fx.bundle, attempt=1)
        self.assertEqual(4, len(self.manager.requests))
