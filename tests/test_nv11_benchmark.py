"""NV11 measurement validity and actual native service integration, offline."""

from pathlib import Path
import json
import tempfile
import unittest

from nv11_benchmark import (
    CONFIG, VARIANTS, actor, benchmark, comparison, distribution, extreme_controls,
    fixture, run_trial, summarize, write_new,
)
from nv07_support import QUESTION, RIGHT, WRONG
from runtime.memory_patch.lite import lexical_relevance


class NV11BenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_four_variants_are_composed_with_real_disabled_boundaries(self):
        for variant in VARIANTS:
            with self.subTest(variant=variant), fixture(self.root / variant, variant) as fx:
                self.assertEqual(CONFIG[variant]["memory"], fx.profile.memory_mode)
                self.assertEqual(variant == "B0", fx.runtime._lite_memory is None)
                self.assertEqual(variant in {"B0", "B1"}, fx.runtime._lite_cpl is None)
                if variant in {"B0", "B1"}:
                    self.assertIsNone(fx.learning)
                else:
                    self.assertFalse(fx.personal.allowed())
                    self.assertEqual(variant == "B3", fx.learning.dynamics is not None)
                self.assertEqual([], fx.transport.calls)

    def test_actual_four_variant_trials_preserve_controls_and_raw_denominators(self):
        trials = [run_trial(self.root / variant, variant, warm=4) for variant in VARIANTS]
        summary = summarize(trials)
        self.assertEqual("PASS", summary["status"])
        self.assertEqual("SHADOW", summary["B3_STATUS"])
        self.assertFalse(any(summary["safety"].values()))
        self.assertEqual(set(VARIANTS), set(summary["variants"]))
        self.assertEqual({"B1/B0", "B2/B1", "B2/B0", "B3/B2", "B3/B0"}, set(summary["comparisons"]))
        self.assertTrue(all(r["classification"] == "INCONCLUSIVE" for r in summary["comparisons"].values()))
        for trial in trials:
            with self.subTest(variant=trial["variant"]):
                self.assertEqual("PASS", trial["status"])
                self.assertTrue(trial["controls"]["restart"]["equivalent_eligible"])
                self.assertEqual(0, trial["model_calls"])
                self.assertEqual(0, trial["effect_dispatches"])
                metrics = summary["variants"][trial["variant"]]
                self.assertEqual(5, metrics["evaluated_tasks"])
                self.assertEqual(5, metrics["correct"] + metrics["incorrect"])
                raw_tasks = [r for r in trial["records"] if r["stage"] in {"cold", "warm"}]
                self.assertEqual(sum(r["answer"] == r["expected"] for r in raw_tasks), metrics["correct"])
                self.assertEqual(sum(r["context_bytes"] for r in trial["records"]), metrics["context_bytes"])
                self.assertIsNone(metrics["warm_lookup_ms"]["p95_nearest_rank"])
                self.assertEqual([], trial["controls"]["revoke"]["fresh_forbidden_hits"])
                self.assertEqual([], trial["controls"]["expiry"]["fresh_forbidden_hits"])
                self.assertEqual("COST_NOT_AUTHORITATIVELY_AVAILABLE", metrics["authoritative_provider_cost"])
        self.assertTrue(trials[3]["controls"]["decay_revalidation"]["revalidations"])
        self.assertGreater(trials[3]["controls"]["decay_revalidation"]["trail_before"][0]["tau_positive"],
                           trials[3]["controls"]["decay_revalidation"]["trail_after_decay"][0]["tau_positive"])

    def test_same_actor_receives_real_context_but_can_ignore_it(self):
        self.assertEqual((WRONG, None), actor(QUESTION, ()))
        self.assertEqual(("42", None), actor("Return input", (), "42"))
        with fixture(self.root / "hat", "B1") as fx:
            context = fx.runtime.lite_memory_retrieve(QUESTION)
            self.assertIn(RIGHT, [r.text for r in context.selected])
            # A real recall can be useless to this selector. Do not change the
            # frozen workload/threshold merely to force a positive result.
            self.assertAlmostEqual(1 / 6, lexical_relevance(QUESTION, RIGHT))
            self.assertEqual((WRONG, None), actor(QUESTION, context.selected))

    def test_b3_result_json_roundtrip_preserves_trail_and_revalidation(self):
        trial = run_trial(self.root / "B3-serialization", "B3", warm=4)
        output = self.root / "B3-result.json"
        write_new(output, trial)
        observed = json.loads(output.read_text())
        self.assertEqual("PASS", observed["status"])
        self.assertEqual(trial["safety"], observed["safety"])
        controls = observed["controls"]["decay_revalidation"]
        self.assertTrue(controls["trail_before"])
        self.assertTrue(controls["revalidations"])
        self.assertEqual(trial["controls"]["decay_revalidation"]["trail_before"][0]["family_deposits"],
                         controls["trail_before"][0]["family_deposits"])
        self.assertEqual("RESOLVED", controls["revalidations"][0]["result"]["status"])
        self.assertEqual(trial["records"][0]["answer"], observed["records"][0]["answer"])

    def test_nearest_rank_p95_and_small_sample_suppression(self):
        self.assertEqual(95, distribution(range(1, 101))["p95_nearest_rank"])
        self.assertEqual(38, distribution(range(1, 41))["p95_nearest_rank"])
        self.assertIsNone(distribution(range(39))["p95_nearest_rank"])
        self.assertEqual(0, distribution([])["n"])

    def test_comparison_can_report_worse_same_and_insufficient_evidence(self):
        def metrics(quality, latency, trials=8):
            return {"task_success_rate": quality, "trials": trials,
                    "warm_lookup_ms": {"median": latency},
                    "trial_warm_medians_ms": [latency] * trials,
                    "warm_file_bytes": {"median": 10}}
        baseline = metrics(.75, 2)
        self.assertEqual("WORSE", comparison(metrics(.5, 1), baseline)["classification"])
        self.assertEqual("WORSE", comparison(metrics(.75, 6), baseline)["classification"])
        self.assertEqual("SAME", comparison(metrics(.75, 2.1), baseline)["classification"])
        self.assertEqual("BETTER", comparison(metrics(1, 6), baseline)["classification"])
        self.assertEqual("INCONCLUSIVE", comparison(metrics(1, 6, 1), baseline)["classification"])

    def test_extreme_inputs_and_numeric_salience_create_no_authority(self):
        controls = extreme_controls()
        self.assertEqual(5, len(controls["rejected"]))
        self.assertEqual(0, controls["unapproved_action_desirability"])
        self.assertLess(controls["decay_after_20s"], .2)

    def test_existing_evidence_and_state_cannot_be_overwritten(self):
        path = self.root / "existing.json"
        write_new(path, {"original": True})
        before = path.read_bytes()
        with self.assertRaises(FileExistsError):
            write_new(path, {"replacement": True})
        self.assertEqual(before, path.read_bytes())
        with self.assertRaises(FileExistsError):
            benchmark(self.root, trials=1, warm=4)

    def test_budgets_and_unknown_variant_rejected_before_measurement(self):
        with self.assertRaises(ValueError):
            benchmark(self.root / "bad", trials=17)
        self.assertFalse((self.root / "bad").exists())
        with self.assertRaises(ValueError), fixture(self.root / "unknown", "B4"):
            self.fail("unknown variant admitted")


if __name__ == "__main__":
    unittest.main()
