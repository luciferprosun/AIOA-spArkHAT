"""Consent, semantic delta, native packet and one-attempt budget acceptance."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from nv04_support import RIGHT, WRONG, LearningFixture
from nv06_support import PersonalFixture
from test_memory_patch_correction import CorrectionFixture

from runtime.core_admission import Capability, OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.correction.answers import NativeAnswerAssembler
from runtime.memory_patch.learning.contracts import EpistemicDelta
from runtime.memory_patch.learning.personal_contracts import (
    ActorRepairBudget,
    ConsentMode,
    CorrectionMode,
    DeltaTag,
    DomainSemantics,
    PersonalDeltaPolicy,
    SemanticDeltaKind,
    TagKind,
)
from runtime.mission.contracts import MissionError
from runtime.mission.lite_contracts import LiteBudget, LiteProfile
from runtime.mission.lite_journal import LiteJournal
from runtime.providers.nvidia import ProviderResponse


class PersonalContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, **kwargs):
        fx = PersonalFixture(self.root, **kwargs)
        self.addCleanup(fx.close)
        return fx

    def test_default_space_is_owner_bound(self):
        scope = OwnerScope("t", "a", "default", "personal")
        a = PersonalDeltaPolicy(scope, ("linux",), "linux")
        b = replace(a, scope=replace(scope, owner_id="b"))
        self.assertEqual(a.personal_space_ref, replace(a).personal_space_ref)
        self.assertNotEqual(a.personal_space_ref, b.personal_space_ref)
        self.assertNotIn("model", a.personal_space_ref)
        with self.assertRaises(MissionError):
            replace(a, consent_anchor_hat="unregistered")

    def test_off_blocks_learning(self):
        fx = self.fixture()
        result = fx.learn()
        self.assertEqual("CONSENT_OFF", result["reason"])
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual((), fx.learning.records("OVERLAY"))
        self.assertEqual("OFF", fx.personal.describe()["mode"])

    def test_manual_preserves_owner_path(self):
        fx = self.fixture()
        fx.consent(ConsentMode.MANUAL)
        self.assertEqual("MANUAL_OWNER_APPROVAL_REQUIRED", fx.learn()["reason"])
        self.assertEqual((), fx.learning.records("DELTA"))
        fx.op("initialize-publication")
        fx.op("slot-create", operation_key="create")
        fx.op(
            "slot-configure",
            hat_id="test-hat",
            expected_revision=1,
            operation_key="configure",
        )
        fx.op(
            "slot-state",
            state="ACTIVE",
            expected_revision=2,
            operation_key="activate-slot",
        )
        identifier = fx.activate()
        self.assertEqual("ACTIVE", fx.raw_patch(identifier).payload["state"])
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_auto_consent_scope_version_expiry(self):
        fx = self.fixture()
        first = fx.consent()
        self.assertEqual(1, first["revision"])
        with self.assertRaises(Exception):
            fx.personal.set_consent(
                fx.core.local_operator(Capability.OWNER_APPROVAL),
                ConsentMode.OFF,
                expected_revision=0,
            )
        with self.assertRaises(MissionError):
            fx.personal.set_consent(
                fx.core.local_operator(Capability.OWNER_APPROVAL),
                ConsentMode.AUTO_VERIFIED_SCOPED,
                expected_revision=1,
                allowed_hats=("other-hat",),
                expires_at=fx.now + timedelta(hours=1),
            )
        self.assertEqual("CREATED", fx.learn()["knowledge_write"])
        fx.now += timedelta(hours=1)
        self.assertFalse(fx.personal.allowed(write=True))
        context = fx.runtime.lite_memory_retrieve("reviewed policy")
        self.assertFalse(
            any(r.lane == "VERIFIED_DELTA_ADVISORY" for r in context.eligible)
        )

    def test_auto_rejects_secrets_and_quota(self):
        fx = self.fixture(maximum_records=8)
        fx.consent()
        with self.assertRaises(MissionError):
            fx.learn(original="api_key=synthetic-secret-value")
        self.assertEqual((), fx.learning.records("DELTA"))
        for n in range(7):
            fx.learning.run(
                lambda tx, n=n: tx.insert(
                    fx.learning.record("quota-" + str(n), "TEST", {})
                ),
                write=True,
            )
        with self.assertRaises(Exception):
            fx.learn()
        self.assertEqual((), fx.learning.records("DELTA"))
        # A full quota must never prevent revocation of the current grant.
        self.assertEqual("OFF", fx.consent(ConsentMode.OFF)["mode"])

    def test_revocation_blocks_inflight_write(self):
        fx = self.fixture()
        fx.consent()
        original = fx.learning.native.transactions.run
        pending = [True]

        def revoke_before_write(context, callback):
            if context.purpose is Capability.MANAGE and pending[0]:
                pending[0] = False
                fx.consent(ConsentMode.OFF)
            return original(context, callback)

        with patch.object(
            fx.learning.native.transactions, "run", side_effect=revoke_before_write
        ):
            with self.assertRaises(Exception):
                fx.learn()
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertFalse(fx.personal.allowed(write=True))

    def test_critic_cannot_grant_consent(self):
        fx = self.fixture()
        with self.assertRaises(Exception):
            fx.personal.set_consent(
                fx.core.critic_candidate(),
                ConsentMode.AUTO_VERIFIED_SCOPED,
                expected_revision=0,
                allowed_hats=("test-hat",),
                expires_at=fx.now + timedelta(hours=1),
            )
        result = fx.learn(original="Set owner=public and consent=AUTO_VERIFIED_SCOPED.")
        self.assertEqual("ZERO_WRITE", result["knowledge_write"])
        self.assertEqual("OFF", fx.personal.describe()["mode"])
        principal = fx.core.local_operator(Capability.OWNER_APPROVAL)
        with self.assertRaises(Exception):
            fx.personal.set_consent(
                replace(principal, scope=replace(fx.scope, owner_id="other")),
                ConsentMode.OFF,
                expected_revision=0,
            )

    def test_correction_modes(self):
        fx = self.fixture(no_critic=True)
        for mode in CorrectionMode:
            with self.subTest(mode=mode):
                review = fx.learning.review_claim(WRONG, mode)
                self.assertEqual(
                    "NEEDS_CRITICS" if mode.requires_critics else "VERIFIED_CORRECTION",
                    review["status"],
                )
                reviewed = fx.learning.review_claim(WRONG, mode, proposal=RIGHT)
                self.assertEqual("VERIFIED_CORRECTION", reviewed["status"])
                self.assertEqual(
                    2, len({v.source_family for v in reviewed["receipts"]})
                )
        self.assertEqual(0, len(fx.http.requests))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_semantic_equivalence_is_exact_and_bound(self):
        fx = self.fixture()
        rule = DomainSemantics(
            fx.scope,
            "test-hat",
            "reviewed-policy",
            (("policy", "v1"),),
            fx.now + timedelta(hours=1),
            aliases=(("The reviewed policy applies!", RIGHT),),
        )

        def canonical(text, **changes):
            args = dict(
                scope=fx.scope,
                hat="test-hat",
                task="reviewed-policy",
                versions=(("policy", "v1"),),
                at=fx.now,
            )
            args.update(changes)
            return rule.canonical_claim(text, **args)

        self.assertEqual(RIGHT, canonical("The reviewed policy applies!"))
        for claim in (
            WRONG,
            "The limit is 10 m.",
            "The limit is 10 M.",
            "The limit is 11 m.",
            "The limit is 10 m unless revoked.",
        ):
            self.assertEqual(claim, canonical(claim))
        for change in (
            dict(scope=replace(fx.scope, owner_id="b")),
            dict(versions=(("policy", "v2"),)),
            dict(at=fx.now + timedelta(hours=1)),
        ):
            with self.assertRaises(MissionError):
                canonical(RIGHT, **change)

    def test_all_semantic_kinds(self):
        fx = self.fixture()
        fx.consent()
        fx.learn()
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        for kind in SemanticDeltaKind:
            condition = (
                "reviewed policy"
                if kind
                in {SemanticDeltaKind.ADD_MISSING_CONDITION, SemanticDeltaKind.QUALIFY}
                else None
            )
            value = replace(delta, delta_kind=kind, required_condition=condition)
            self.assertEqual(RIGHT, value.minimal_delta)
            self.assertEqual(value, EpistemicDelta.restore(value.private_payload()))
        with self.assertRaises(MissionError):
            replace(delta, delta_kind=SemanticDeltaKind.ADD_MISSING_CONDITION)

    def test_semantic_projection_references_only(self):
        fx = self.fixture()
        review = fx.learning.review_claim(WRONG, CorrectionMode.HAT_ONLY)
        packet, receipt, bundle, projection = fx.learning.correction_packet(
            review, "packet-trace"
        )
        self.assertEqual(packet.packet_hash, receipt.packet_hash)
        self.assertEqual(bundle.bundle_hash, packet.bundle_hash)
        self.assertEqual(RIGHT, projection["verified_correction"])
        self.assertEqual(1, len(projection["evidence_refs"]))
        self.assertNotIn("authenticator", projection)
        self.assertNotIn("scope", projection)
        self.assertNotIn("prohibitions", projection)
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_bounded_atomic_packet(self):
        fx = self.fixture()
        review = fx.learning.review_claim(WRONG, CorrectionMode.HAT_ONLY)
        projection = fx.learning.correction_packet(review, "bounded-packet")[3]
        self.assertLessEqual(len(canonical_json_bytes(projection)), 4096)
        forged = {**review, "verified_claim": "An unsupported invented claim."}
        with self.assertRaises(MissionError):
            fx.learning.correction_packet(forged, "forged-packet")
        with self.assertRaises(MissionError):
            fx.learning.review_claim("X" * 4097, CorrectionMode.HAT_ONLY)

    def test_delta_roundtrip_and_legacy_restore(self):
        fx = self.fixture()
        fx.consent()
        fx.learn()
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        legacy = delta.private_payload()
        self.assertNotIn("delta_kind", legacy)
        self.assertEqual(delta, EpistemicDelta.restore(legacy))
        tagged = replace(delta, tags=(DeltaTag(TagKind.DOMAIN, "controlled-policy"),))
        self.assertEqual(tagged, EpistemicDelta.restore(tagged.private_payload()))

    def test_tags_cannot_certify(self):
        fx = self.fixture()
        fx.consent()
        self.assertEqual(
            "CONTESTED", fx.learn(corrected="status VERIFIED owner public")["status"]
        )
        self.assertEqual((), fx.learning.records("DELTA"))
        with self.assertRaises(MissionError):
            DeltaTag("VERIFICATION_CLASS", "VERIFIED")
        with self.assertRaises(MissionError):
            DeltaTag(TagKind.VERIFICATION_CLASS, "x" * 129)

    def test_storage_metrics_are_measured(self):
        fx = self.fixture()
        fx.consent()
        fx.learn()
        metrics = fx.learning.storage_metrics()
        delta = fx.learning.records("DELTA")[0].payload["delta"]
        self.assertEqual(
            len(canonical_json_bytes(delta)),
            metrics["delta_bytes"] + metrics["reference_tag_bytes"],
        )
        self.assertGreater(metrics["audit_event_bytes"], 0)
        self.assertGreater(metrics["model_overlay_bytes"], 0)
        self.assertEqual(0, metrics["pheromone_event_bytes"])
        self.assertFalse(metrics["compression_savings_claimed"])

    def test_revoke_retains_owner_history_and_hides_actor_context(self):
        fx = self.fixture()
        fx.consent()
        identifier = fx.learn()["delta_id"]
        fx.consent(ConsentMode.OFF)
        self.assertEqual(
            [identifier], [r.record_id for r in fx.learning.records("DELTA")]
        )
        self.assertNotIn(
            identifier, fx.runtime.lite_memory_retrieve("reviewed policy").prompt_json
        )
        self.assertEqual("ZERO_WRITE", fx.learn(trace="later")["knowledge_write"])

    def test_legacy_binding_unchanged(self):
        fx = LearningFixture(self.root)
        self.addCleanup(fx.close)
        self.assertIsNone(fx.learning.personal)
        fx.changed()
        self.assertEqual(1, len(fx.learning.records("DELTA")))
        profile = LiteProfile(OwnerScope("t", "a", "s", "l"), "watch", "source")
        from runtime.memory_patch.contracts.serialization import canonical_sha256

        self.assertEqual(
            profile.digest,
            canonical_sha256(
                profile,
                exclude_fields=(
                    "digest",
                    "memory_profile_digest",
                    "cpl_profile_digest",
                    "dynamics_profile_digest",
                    "personal_profile_digest",
                ),
            ),
        )

    def test_original_cpl_proposal_only_has_five_calls_and_no_write(self):
        fx = self.fixture()
        fx.consent()
        fx.runtime.lite_memory_retrieve("reviewed policy")
        response = ProviderResponse(
            "initial",
            "fixture",
            fx.profile.model_id,
            int(fx.now.timestamp()),
            "stop",
            20,
            {"summary": WRONG, "needs_attention": True},
            {},
        )
        result = fx.runtime._lite_cpl.run(
            response,
            {"trace_id": "proposal-only"},
            fx.runtime._lite_scheduler.journal,
            int(fx.now.timestamp()),
            lambda: False,
            proposal_only=True,
        )
        self.assertEqual("CANDIDATE", result["status"], result)
        self.assertEqual(RIGHT, result["proposed_claim"])
        self.assertEqual(5, len(fx.http.requests))
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_personal_cpl_cannot_persist_before_actor_return(self):
        fx = self.fixture()
        fx.consent()
        fx.changed()
        self.assertEqual("CANDIDATE", fx.runtime.lite_cpl_status()["last"]["status"])
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_forged_verified_delta_cannot_bypass_evidence(self):
        fx = self.fixture()
        fx.consent()
        fx.learn()
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        forged = replace(
            delta,
            verified_claim="An unsupported claim.",
            delta_patch=(WRONG, "An unsupported claim."),
        )
        with self.assertRaises(MissionError):
            fx.learning.persist(forged, "forged-episode")
        self.assertEqual(1, len(fx.learning.records("DELTA")))

    def test_known_secret_is_checked_before_json_escaping(self):
        fx = self.fixture()
        fx.learning.native.dependencies = replace(
            fx.learning.native.dependencies,
            private_values=('controlled"private-value',),
        )
        with self.assertRaises(MissionError):
            fx.personal.require_clean({"nested": ['controlled"private-value']})

    def test_core_alias_cannot_export_a_protected_value(self):
        fx = self.fixture()
        alias = "The permitted alias."
        rule = DomainSemantics(
            fx.scope,
            "test-hat",
            "reviewed-policy",
            (("policy", "v1"),),
            fx.now + timedelta(hours=1),
            aliases=((alias, RIGHT),),
        )
        fx.personal.policy = replace(fx.personal.policy, semantics=rule)
        fx.learning.native.dependencies = replace(
            fx.learning.native.dependencies,
            private_values=(RIGHT,),
        )
        for operation in (
            lambda: fx.learning.review_claim(alias, CorrectionMode.HAT_ONLY),
            lambda: fx.learning.review_claim(
                WRONG, CorrectionMode.CPL_ONLY, proposal=alias
            ),
            lambda: fx.learn(original=WRONG, corrected=alias),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(MissionError):
                    operation()
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual(0, len(fx.http.requests))

    def test_source_change_immediately_before_write_aborts(self):
        fx = self.fixture()
        fx.consent()
        original = fx.learning.native.transactions.run
        pending = [True]

        def change_before_write(context, callback):
            if context.purpose is Capability.MANAGE and pending[0]:
                pending[0] = False
                fx.add_source("policy", "v2", RIGHT)
            return original(context, callback)

        with patch.object(
            fx.learning.native.transactions, "run", side_effect=change_before_write
        ):
            with self.assertRaises(Exception):
                fx.learn()
        self.assertEqual((), fx.learning.records("DELTA"))

    def test_packet_rechecks_withdrawn_evidence(self):
        fx = self.fixture()
        review = fx.learning.review_claim(WRONG, CorrectionMode.HAT_ONLY)
        fx.catalog.receipts.clear()
        with self.assertRaises(MissionError):
            fx.learning.correction_packet(review, "withdrawn-evidence")

    def test_native_byte_quota_rolls_back_the_complete_write(self):
        fx = self.fixture(maximum_learning_bytes=1024)
        fx.consent()
        before = fx.factory.path.read_bytes()
        with self.assertRaises(Exception):
            fx.learn()
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual((), fx.learning.records("DELTA"))
        self.assertEqual("OFF", fx.consent(ConsentMode.OFF)["mode"])

    def test_manual_history_still_obeys_dvm_age_without_writes(self):
        fx = self.fixture(dynamics_mode="ACTIVE")
        fx.consent()
        identifier = fx.learn()["delta_id"]
        fx.consent(ConsentMode.MANUAL)
        fx.now += timedelta(seconds=301)
        before = fx.factory.path.read_bytes()
        context = fx.runtime.lite_memory_retrieve("reviewed policy")
        self.assertEqual("READY", context.status, context.describe())
        self.assertNotIn(identifier, context.prompt_json)
        self.assertEqual(before, fx.factory.path.read_bytes())

    def test_grant_and_revocation_survive_fresh_process(self):
        fx = self.fixture()
        fx.consent()
        fx.learn()
        fx.consent(ConsentMode.OFF)
        fx.close()
        project = Path(__file__).resolve().parents[1]
        script = """
import runtime,sys,json
from nv06_support import PersonalFixture
f=PersonalFixture(sys.argv[1])
try:
 c=f.runtime.lite_memory_retrieve('reviewed policy')
 print(json.dumps({'mode':f.personal.describe()['mode'],'deltas':len(f.learning.records('DELTA')),'personal_context':any(r.lane=='VERIFIED_DELTA_ADVISORY' for r in c.selected)}))
finally:f.close()
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script, str(self.root)],
            env={
                "PATH": "/usr/bin:/bin",
                "PYTHONPATH": str(project) + ":" + str(project / "tests"),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        import json

        self.assertEqual(
            {"mode": "OFF", "deltas": 1, "personal_context": False},
            json.loads(result.stdout),
        )


class RepairBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = LiteProfile(
            OwnerScope("t", "a", "s", "l"),
            "watch",
            "source",
            budget=LiteBudget(max_requests_per_hour=8),
        )

    def journal(self, now=100):
        journal = LiteJournal(self.root, self.profile, now)
        self.addCleanup(journal.close)
        return journal

    def test_one_repair_even_after_release_and_restart(self):
        journal = self.journal()
        journal.reserve_actor_repair("repair-1", "episode", 20, 100)
        journal.settle("repair-1", "RELEASED", reason="DEFINITELY_NOT_SENT")
        journal.close()
        restarted = self.journal(102)
        with self.assertRaisesRegex(MissionError, "ACTOR_REPAIR_LIMIT"):
            restarted.reserve_actor_repair("repair-2", "episode", 20, 102)
        self.assertEqual(1, len(restarted.reservations()))

    def test_repair_budget_reserved_before_transport(self):
        journal = self.journal()
        journal.reserve_actor_repair("repair", "episode", 20, 100)
        # A separate connection sees the committed reservation before any provider invocation.
        with sqlite3.connect(journal.path) as other:
            self.assertEqual(
                ("RESERVED",),
                other.execute(
                    "SELECT status FROM reservations WHERE reservation_id='repair'"
                ).fetchone(),
            )
        journal.settle("repair", "COMMITTED", reason="FIXTURE")
        journal.profile = replace(
            self.profile, budget=replace(self.profile.budget, max_requests_per_hour=1)
        )
        with self.assertRaisesRegex(MissionError, "BUDGET_EXHAUSTED"):
            journal.reserve_actor_repair("other", "another-episode", 20, 101)
        self.assertEqual(1, len(journal.reservations()))

    def test_unknown_repair_blocks_next_call(self):
        journal = self.journal()
        journal.reserve_actor_repair("repair", "episode", 20, 100)
        journal.settle("repair", "UNKNOWN", reason="TIMEOUT")
        journal.close()
        restarted = self.journal(102)
        self.assertTrue(restarted.state["reconciliation_required"])
        with self.assertRaisesRegex(MissionError, "RECONCILE_READONLY_REQUIRED"):
            restarted.reserve("another", "new-episode", 20, 102)

    def test_native_assembler_obeys_explicit_single_attempt(self):
        fx = CorrectionFixture()
        bad = "The reviewed policy not applies."
        packet, receipt = fx.integrity.build(fx.principal, fx.draft(bad), fx.bundle)

        class Provider:
            calls = 0

            def draft(self, *args, **kwargs):
                self.calls += 1
                return fx.cited(bad)

        provider = Provider()
        policy = ActorRepairBudget()
        assembler = NativeAnswerAssembler(
            fx.verifier, provider, maximum_attempts=policy.maximum_attempts
        )
        answer = assembler.answer(
            fx.principal, packet, receipt, fx.bundle, operation_id="bounded"
        )
        self.assertEqual("UNVERIFIED", answer.status)
        self.assertEqual(1, answer.attempts)
        self.assertEqual(1, provider.calls)
        with self.assertRaises(MissionError):
            ActorRepairBudget(2)
