from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "changed_secret_scan", Path(__file__).resolve().parents[1] / "scripts/check_changed_secrets.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ChangedSecretScanTests(unittest.TestCase):
    def test_required_categories(self):
        examples = {
            "PRIVATE_KEY": "-----BEGIN " + "PRIVATE KEY-----",
            "BEARER_LITERAL": "Bearer " + "Z" * 24,
            "NEBIUS_KEY": "neb_" + "A" * 24,
            "OPENAI_KEY": "sk-" + "proj-" + "X" * 24,
            "AWS_ACCESS_KEY": "AKIA" + "A" * 16,
            "HIGH_ENTROPY_TOKEN_ASSIGNMENT": "api_key=" + repr("abcdefghijklmnopqrstuvwxyz0123456789"),
        }
        for category, example in examples.items():
            with self.subTest(category=category):
                self.assertIn(category, scanner.scan_text(example))

    def test_nebius_versioned_key(self):
        self.assertIn("NEBIUS_KEY", scanner.scan_text("v1." + "a" * 40 + "." + "b" * 30))

    def test_safe_dynamic_credentials(self):
        source = 'headers = {"Authorization": f"Bearer {api_key}"}\napi_key = os.environ.get("NEBIUS_API_KEY")'
        self.assertEqual((), scanner.scan_text(source))

    def test_python_expressions_are_not_literal_tokens(self):
        source = "self.csrf_token = secrets.token_urlsafe(32)\nmax_output_tokens = max_output_tokens\n"
        self.assertEqual((), scanner.scan_text(source))

    def test_token_limit_field_is_not_a_credential_assignment(self):
        self.assertEqual((), scanner.scan_text('token_limit_field = "reasoning_included_in_output_bound"'))

    def test_documentation_filenames_are_not_nebius_credentials(self):
        self.assertEqual((), scanner.scan_text("docs/nebius_personal_ai_demo_runbook.md"))

    def test_low_entropy_assignment_not_reported(self):
        self.assertEqual((), scanner.scan_text("api_key=" + repr("x" * 40)))

    def test_unquoted_shell_and_json_tokens(self):
        candidate = "abcdefghijklmnopqrstuvwxyz0123456789"
        for source in ("API_TOKEN=" + candidate, json.dumps({"token": candidate})):
            self.assertIn("HIGH_ENTROPY_TOKEN_ASSIGNMENT", scanner.scan_text(source))

    def test_report_never_contains_candidate(self):
        candidate = "sk-" + "Aq9Bv8Cw7Dx6Ey5Fz4Gu3Ht2Is1Jr0K" * 2
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "unsafe.txt").write_text(candidate)
            report = scanner.scan_files(root, ["unsafe.txt"])
            self.assertEqual("FAIL", report["status"])
            self.assertNotIn(candidate, json.dumps(report))
            self.assertEqual({"path", "category", "status"}, set(report["results"][0]))

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "link").symlink_to("/etc/passwd")
            report = scanner.scan_files(root, ["link"])
            self.assertEqual("UNSAFE_PATH", report["results"][0]["category"])
            self.assertEqual("FAIL", report["status"])

    def test_safe_file_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "safe.py").write_text("answer = 42")
            self.assertEqual("PASS", scanner.scan_files(root, ["safe.py"])["status"])


if __name__ == "__main__":
    unittest.main()
