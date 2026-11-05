from __future__ import annotations

import unittest

from runtime.critical_loop.cpt.sanitizer import UNTRUSTED_BLOCK_END, UNTRUSTED_BLOCK_START
from runtime.critical_loop.cpt.templates import DISCLAIMER, REQUIRED_SECTIONS
from runtime.critical_loop.cpt.transformer import transform_prompt


class CptTransformerTests(unittest.TestCase):
    def test_deterministic_output_for_identical_input(self) -> None:
        first = transform_prompt("Review my app and tell me if it is good.")
        second = transform_prompt("Review my app and tell me if it is good.")

        self.assertEqual(first, second)

    def test_original_prompt_preserved_in_quoted_untrusted_section(self) -> None:
        prompt = "Review my database migration."

        record = transform_prompt(prompt)

        self.assertIn(UNTRUSTED_BLOCK_START, record.transformed_prompt)
        self.assertIn(prompt, record.transformed_prompt)
        self.assertIn(UNTRUSTED_BLOCK_END, record.transformed_prompt)

    def test_transformed_prompt_contains_disclaimer(self) -> None:
        record = transform_prompt("Review this design.")

        self.assertIn(DISCLAIMER, record.transformed_prompt)

    def test_transformed_prompt_contains_required_sections(self) -> None:
        record = transform_prompt("Review this incident report.")

        for section in REQUIRED_SECTIONS:
            with self.subTest(section=section):
                self.assertIn(section, record.transformed_prompt)

    def test_transformed_prompt_does_not_claim_critique_is_truth(self) -> None:
        record = transform_prompt("Review this app.")

        self.assertIn("not canonical truth", record.transformed_prompt)
        self.assertIn("hypotheses requiring human verification", record.transformed_prompt)

    def test_transformed_prompt_does_not_include_abusive_language(self) -> None:
        record = transform_prompt("Review this app.")
        abusive_terms = ("brutal", "destroy", "crush", "eviscerate", "humiliating", "you are wrong")

        offenders = [term for term in abusive_terms if term in record.transformed_prompt.lower()]

        self.assertEqual([], offenders)

    def test_transformation_id_and_hashes_stable_for_same_input(self) -> None:
        first = transform_prompt("Review this release.")
        second = transform_prompt("Review this release.")

        self.assertEqual(first.transformation_id, second.transformation_id)
        self.assertEqual(first.original_prompt_hash, second.original_prompt_hash)
        self.assertEqual(first.transformed_prompt_hash, second.transformed_prompt_hash)


if __name__ == "__main__":
    unittest.main()
