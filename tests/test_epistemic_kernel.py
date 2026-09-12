import unittest
from pathlib import Path

from adaptive_routing.epistemic_kernel import AOIAEpistemicKernel


# The kernel receives the runtime resource root, just as AgentRuntime does.
# The old repository-root argument only passed via an unintended global corpus
# fallback. Keep every assertion; provide the explicit intended fixture root.
PROJECT_DIR = Path(__file__).resolve().parents[1] / 'runtime'


class AOIAEpistemicKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.kernel = AOIAEpistemicKernel(PROJECT_DIR)

    def test_evaluate_is_deterministic_for_same_query(self) -> None:
        first = self.kernel.evaluate("systemctl status")
        second = self.kernel.evaluate("systemctl status")
        self.assertEqual(first.route, second.route)
        self.assertEqual(first.depth, second.depth)
        self.assertEqual(first.pressure, second.pressure)
        self.assertEqual(first.confidence, second.confidence)
        self.assertEqual(first.manual_review_reasons, second.manual_review_reasons)

    def test_provenance_is_attached_to_evidence(self) -> None:
        decision = self.kernel.evaluate("systemctl status")
        self.assertTrue(decision.evidence)
        provenance = decision.evidence[0].get("provenance", {})
        self.assertIn("metadata", provenance)
        self.assertIn("content_hash", provenance)

    def test_duplicate_command_triggers_manual_review(self) -> None:
        decision = self.kernel.evaluate("systemctl status")
        self.assertTrue(decision.should_respond_locally)
        self.assertTrue(decision.manual_review_required)
        self.assertIn("duplicate_or_conflicting_sources_detected", decision.manual_review_reasons)

    def test_non_linux_query_does_not_force_local_response(self) -> None:
        decision = self.kernel.evaluate("write a haiku about spring")
        self.assertFalse(decision.should_respond_locally)


if __name__ == "__main__":
    unittest.main()
