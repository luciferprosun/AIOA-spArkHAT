"""Descriptive text comparison must never imply semantic agreement or authority."""
import hashlib
import unittest

from critical_loop.comparison import MAX_COMPARISON_CHARS, compare_responses


class ResponseComparisonTests(unittest.TestCase):
    def test_exact_fingerprints_and_unicode_are_preserved(self):
        text = "Zażółć 🛰\nline"
        result = compare_responses(text, text)
        self.assertTrue(result['exact_equal'])
        self.assertTrue(result['layout_equal'])
        self.assertEqual(result['draft_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(result['final_sha256'], result['draft_sha256'])
        self.assertEqual(result['draft_characters'], len(text))
        self.assertEqual(result['authority'], 'ADVISORY_ONLY')
        self.assertEqual(result['semantic_equivalence'], 'NOT_EVALUATED')
        self.assertNotIn(text, str(result))

    def test_layout_equality_preserves_distinct_exact_fingerprints(self):
        result = compare_responses('\r\nA\t B  \r\nC\r\n', 'A B\nC')
        self.assertFalse(result['exact_equal'])
        self.assertTrue(result['layout_equal'])
        self.assertNotEqual(result['draft_sha256'], result['final_sha256'])
        self.assertEqual(result['shared_normalized_lines'], 2)

    def test_quoted_code_layout_match_is_explicitly_not_semantic_equivalence(self):
        result = compare_responses('print("a  b")', 'print("a b")')
        self.assertTrue(result['layout_equal'])
        self.assertFalse(result['exact_equal'])
        self.assertEqual(result['semantic_equivalence'], 'NOT_EVALUATED')

    def test_unique_line_counts_keep_orientation_without_returning_text(self):
        result = compare_responses('shared\ndraft\ndraft', 'shared\nfinal')
        self.assertEqual((result['shared_normalized_lines'], result['draft_only_normalized_lines'],
                          result['final_only_normalized_lines']), (1, 1, 1))
        self.assertFalse(result['layout_equal'])
        self.assertEqual(compare_responses('A', 'a')['shared_normalized_lines'], 0)

    def test_reordering_is_not_equality_even_with_identical_line_sets(self):
        result = compare_responses('first\nsecond', 'second\nfirst')
        self.assertFalse(result['exact_equal'])
        self.assertFalse(result['layout_equal'])
        self.assertEqual(result['shared_normalized_lines'], 2)

    def test_invalid_and_oversized_responses_are_withheld_without_truncation(self):
        for invalid in (None, False, 1, {}, [], b'text', '', '\t\r\n', 'x' * (MAX_COMPARISON_CHARS + 1)):
            with self.subTest(kind=type(invalid).__name__):
                self.assertIsNone(compare_responses(invalid, 'valid'))
                self.assertIsNone(compare_responses('valid', invalid))
        self.assertTrue(compare_responses('x' * MAX_COMPARISON_CHARS,
                                          'x' * MAX_COMPARISON_CHARS)['exact_equal'])


if __name__ == '__main__':
    unittest.main()
