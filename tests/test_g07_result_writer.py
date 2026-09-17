"""Focused contracts for the G07-B.2 machine-result writer."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.record_suite import (
    ResultWriterError,
    atomic_write_json,
    prepare_result_output,
    run_suite,
)


class ResultWriterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_normal_file_output_is_parseable_and_preserves_counts(self):
        output = self.root / "result.json"
        report = {
            "STATUS": "PASS",
            "tests_run": 181,
            "passed": 181,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
        atomic_write_json(output, report)
        self.assertTrue(output.is_file())
        self.assertFalse(output.is_symlink())
        self.assertEqual(report, json.loads(output.read_text()))

    def test_nested_parent_is_created_without_creating_filename_directory(self):
        output = self.root / "nested" / "deeper" / "result.json"
        prepared = prepare_result_output(output)
        self.assertEqual(output, prepared)
        self.assertTrue(output.parent.is_dir())
        self.assertFalse(output.exists())
        atomic_write_json(output, {"STATUS": "PASS"})
        self.assertTrue(output.is_file())

    def test_existing_directory_is_a_deterministic_explicit_error(self):
        output = self.root / "result.json"
        output.mkdir()
        with patch(
            "scripts.record_suite.unittest.defaultTestLoader.discover"
        ) as discover, self.assertRaisesRegex(
            ResultWriterError, "RESULT_OUTPUT_IS_DIRECTORY"
        ):
            run_suite(self.root, output)
        discover.assert_not_called()
        self.assertTrue(output.is_dir())

    def test_existing_regular_file_is_safely_replaced(self):
        output = self.root / "result.json"
        output.write_text('{"STATUS":"OLD"}\n')
        atomic_write_json(output, {"STATUS": "PASS", "tests_run": 1})
        self.assertEqual(
            {"STATUS": "PASS", "tests_run": 1}, json.loads(output.read_text())
        )
        self.assertEqual([], list(output.parent.glob(f".{output.name}.*.tmp")))

    def test_invalid_json_value_does_not_replace_existing_result(self):
        output = self.root / "result.json"
        output.write_text('{"STATUS":"PRESERVED"}\n')
        with self.assertRaisesRegex(ResultWriterError, "RESULT_JSON_INVALID"):
            atomic_write_json(output, {"not_finite": float("nan")})
        self.assertEqual({"STATUS": "PRESERVED"}, json.loads(output.read_text()))


if __name__ == "__main__":
    unittest.main()
