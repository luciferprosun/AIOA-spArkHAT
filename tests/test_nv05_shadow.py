"""G05 prerequisite: SHADOW equations/audit/baseline tests before ACTIVE demo."""

from __future__ import annotations

import math
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from nv05_support import DynamicsFixture

from runtime.memory_patch.learning.dynamics import (
    MemoryDynamics,
    action_desirability,
    decay,
    recall_salience,
)
from runtime.memory_patch.learning.service import NativeLearning
from runtime.mission.contracts import MissionError


class NV05ShadowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self, **kwargs):
        fixture = DynamicsFixture(self.root, **kwargs)
        self.addCleanup(fixture.close)
        return fixture

    def test_closed_finite_caps_and_exact_decay_equation(self):
        fx = self.fixture()
        self.assertAlmostEqual(
            0.8 * math.exp(-0.0001 * 7200), decay(0.8, 7200, 0.0001), places=12
        )
        for value in (float("nan"), float("inf"), -0.1, 1.1, True):
            with self.subTest(value=value), self.assertRaises(MissionError):
                recall_salience(0.8, value, 0.1)
        with self.assertRaises(MissionError):
            decay(0.5, -1, 0.01)
        with self.assertRaises(MissionError):
            replace(fx.dynamics.policy, success_deposit=0.5)

    def test_negative_increases_recall_and_decreases_bad_path_desirability(self):
        self.assertGreater(
            recall_salience(0.8, 0.2, 0.9), recall_salience(0.8, 0.2, 0.1)
        )
        self.assertLess(
            action_desirability(0.2, 0.9, allowed=True),
            action_desirability(0.2, 0.1, allowed=True),
        )
        self.assertEqual(0.0, action_desirability(1.0, 0.0))

    def test_real_correction_creates_deep_trail_and_audited_both_channels(self):
        fx = self.fixture()
        fx.changed()
        self.assertEqual(
            "VERIFIED",
            fx.runtime.lite_cpl_status()["last"]["status"],
            fx.runtime.lite_cpl_status(),
        )
        trail = fx.learning.records("TRAIL")[0]
        self.assertEqual("DEEP", trail.payload["tier"])
        self.assertEqual(
            (0.2, 0.15), (trail.payload["tau_positive"], trail.payload["tau_negative"])
        )
        event = fx.learning.records("PHEROMONE_EVENT")[0].payload
        self.assertEqual((0.0, 0.0), event["old_tau"])
        self.assertEqual((0.2, 0.15), event["new_tau"])
        self.assertEqual("VERIFIED_CORRECTION", event["reason"])
        self.assertEqual(1.0, event["independence_factor"])
        self.assertTrue(event["evidence_refs"])
        self.assertEqual(1, len(fx.learning.records("DEPENDENCY")))

    def test_same_episode_provenance_is_idempotent_and_correlated_family_discounted(
        self,
    ):
        fx = self.fixture()
        fx.changed()
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        event = fx.learning.records("PHEROMONE_EVENT")[0].payload
        before = fx.factory.path.read_bytes()
        result = fx.dynamics.correction(delta, event["episode_ref"])
        self.assertEqual("DUPLICATE_NO_DEPOSIT", result["status"])
        self.assertEqual(before, fx.factory.path.read_bytes())
        result = fx.dynamics.correction(delta, "independent-new-episode")
        self.assertAlmostEqual(0.25, result["new_tau"][0])
        self.assertAlmostEqual(0.30, result["new_tau"][1])

    def test_independent_actor_family_has_full_factor_and_global_caps_hold(self):
        fx = self.fixture()
        fx.changed()
        delta = fx.learning.delta(fx.learning.records("DELTA")[0])
        policy = replace(
            fx.learning_policy,
            actor=replace(fx.learning_policy.actor, family="other-independent-family"),
        )
        other = NativeLearning(
            fx.runtime._lite_memory, policy, fx.verifiers, active=True
        )
        dynamics = MemoryDynamics(other, fx.dynamics.policy, fx.context, fx.profile)
        result = dynamics.correction(delta, "independent-family-episode")
        self.assertAlmostEqual(0.4, result["new_tau"][0])
        for n in range(20):
            result = fx.dynamics.correction(delta, "bounded-repeat-" + str(n))
        self.assertEqual((1.0, 1.0), result["new_tau"])

    def test_shadow_keeps_baseline_context_and_deep_storage(self):
        fx = self.fixture()
        fx.changed()
        fx.runtime.lite_memory_retrieve("reviewed policy")
        view = fx.runtime.lite_dynamics_status()["last"]
        self.assertEqual(view["baseline_selected"], view["selected"])
        self.assertEqual("SHADOW_BASELINE_UNCHANGED", view["migration_reason"])
        self.assertTrue(view["scores"])
        self.assertEqual([], view["hot_refs"])
        self.assertEqual("DEEP", fx.learning.records("TRAIL")[0].payload["tier"])

    def test_decay_is_a_separate_durable_event_without_positive_reward(self):
        fx = self.fixture()
        fx.changed()
        fx.now += timedelta(seconds=20)
        fx.runtime.lite_memory_retrieve("reviewed policy")
        events = [
            r.payload
            for r in fx.learning.records("PHEROMONE_EVENT")
            if r.payload["reason"] == "DECAY"
        ]
        self.assertEqual(1, len(events))
        self.assertAlmostEqual(0.2 * math.exp(-0.0001 * 20), events[0]["new_tau"][0])
        self.assertEqual(0.0, events[0]["evidence_quality"])

    def test_heartbeat_never_reads_scores_or_calls_cpl(self):
        fx = self.fixture()
        fx.changed()
        before = fx.factory.path.read_bytes()
        calls = len(fx.transport.calls) + len(fx.http.requests)
        for _ in range(10):
            fx.now += timedelta(seconds=1)
            fx.runtime.lite_tick()
        self.assertEqual(before, fx.factory.path.read_bytes())
        self.assertEqual(calls, len(fx.transport.calls) + len(fx.http.requests))

    def test_critical_recheck_age_cannot_be_starved_by_tau(self):
        fx = self.fixture(policy_changes={"recheck_deadline_seconds": 5})
        fx.changed()
        delta_id = fx.learning.records("DELTA")[0].record_id
        fx.now += timedelta(seconds=6)
        context = fx.runtime.lite_memory_retrieve("reviewed policy")
        self.assertNotIn(delta_id, [r.reference_id for r in context.eligible])
        obligation = fx.learning.records("OBLIGATION")[0].payload
        self.assertEqual("CRITICAL_RECHECK_DUE", obligation["reason"])
        self.assertEqual("REVALIDATION_REQUIRED", obligation["subject_status"])
        self.assertEqual("WORKING", fx.learning.records("TRAIL")[0].payload["tier"])
