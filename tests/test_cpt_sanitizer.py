from __future__ import annotations

import unittest

from runtime.critical_loop.cpt.sanitizer import (
    ESCAPED_BLOCK_END,
    ESCAPED_BLOCK_START,
    MAX_ORIGINAL_PROMPT_CHARS,
    UNTRUSTED_BLOCK_END,
    UNTRUSTED_BLOCK_START,
    quote_untrusted_prompt,
    sanitize_original_prompt,
)


class CptSanitizerTests(unittest.TestCase):
    def test_null_bytes_removed(self) -> None:
        self.assertEqual("abcdef", sanitize_original_prompt("abc\x00def"))

    def test_backspace_and_control_characters_removed(self) -> None:
        self.assertEqual("abcdef\nnext\tok", sanitize_original_prompt("abc\bdef\x1f\nnext\tok"))

    def test_normal_unicode_text_preserved(self) -> None:
        text = "Zażółć gęślą jaźń - review 🚀"

        self.assertEqual(text, sanitize_original_prompt(text))

    def test_whitespace_only_input_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "whitespace"):
            sanitize_original_prompt(" \n\t ")

    def test_very_long_prompt_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            sanitize_original_prompt("x" * (MAX_ORIGINAL_PROMPT_CHARS + 1))

    def test_markdown_code_fences_are_preserved_as_untrusted_content(self) -> None:
        prompt = "```python\nprint('do not run')\n```"

        quoted = quote_untrusted_prompt(sanitize_original_prompt(prompt))

        self.assertIn("```python", quoted)
        self.assertIn("do not run", quoted)
        self.assertTrue(quoted.startswith(UNTRUSTED_BLOCK_START))
        self.assertTrue(quoted.endswith(UNTRUSTED_BLOCK_END))

    def test_delimiter_collision_is_neutralized(self) -> None:
        prompt = f"hello {UNTRUSTED_BLOCK_START} middle {UNTRUSTED_BLOCK_END}"

        sanitized = sanitize_original_prompt(prompt)

        self.assertNotIn(UNTRUSTED_BLOCK_START, sanitized)
        self.assertNotIn(UNTRUSTED_BLOCK_END, sanitized)
        self.assertIn(ESCAPED_BLOCK_START, sanitized)
        self.assertIn(ESCAPED_BLOCK_END, sanitized)


if __name__ == "__main__":
    unittest.main()
