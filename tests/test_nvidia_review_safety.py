"""NVIDIA reviewer portability and evidence-output regression tests."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.nvidia_reviewer_preflight import _write_artifact, run_preflight

REPO = Path(__file__).resolve().parents[1]


class NvidiaReviewSafetyTests(unittest.TestCase):
    def test_cli_works_from_foreign_cwd_without_pythonpath_or_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "home").mkdir()
            env = {"PATH": os.defpath, "HOME": str(root / "home"),
                   "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                   "AOIA_HOME": str(root / "state"),
                   "AWS_EC2_METADATA_DISABLED": "true"}
            result = subprocess.run(
                [sys.executable, "-I", "-B", str(REPO / "scripts/nvidia_reviewer_preflight.py"),
                 "--root", str(root / "review")],
                cwd=root, env=env, capture_output=True, text=True, timeout=90)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual("PASS", summary["status"])
            self.assertEqual(14, summary["evaluation"]["stage_count"])
            self.assertEqual(0, summary["evaluation"]["duplicate_effects"])
            self.assertFalse(any(summary["claims"].values()))

    def test_artifact_existing_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "artifact.json"
            output.write_bytes(b"prior evidence")
            with self.assertRaises(FileExistsError):
                _write_artifact(output, {"new": "evidence"})
            self.assertEqual(b"prior evidence", output.read_bytes())

    def test_artifact_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "preserved.json"
            target.write_bytes(b"preserved evidence")
            output = Path(temp) / "artifact.json"
            output.symlink_to(target)
            with self.assertRaises(FileExistsError):
                _write_artifact(output, {"new": "evidence"})
            self.assertEqual(b"preserved evidence", target.read_bytes())


    def test_symlink_root_is_rejected_before_demo_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "target"
            target.mkdir()
            alias = Path(temp) / "alias"
            alias.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "PREFLIGHT_ROOT_SYMLINK_REJECTED"):
                run_preflight(alias)
            self.assertEqual([], list(target.iterdir()))

    def test_successful_artifact_has_private_mode_and_matching_digest(self):
        import hashlib
        import stat
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "artifact.json"
            digest = _write_artifact(output, {"label": "TEST_FIXTURE"})
            self.assertEqual(digest, hashlib.sha256(output.read_bytes()).hexdigest())
            self.assertEqual(0o600, stat.S_IMODE(output.stat().st_mode))


    def test_preflight_never_constructs_legacy_or_nonzero_executor_path(self):
        from unittest.mock import patch
        from tools.executor import ExecutionEngine
        from runtime.nonzero_cloudops.service import NonZeroCloudOpsService
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(ExecutionEngine, "__init__", side_effect=AssertionError("legacy path")) as legacy:
                with patch.object(NonZeroCloudOpsService, "__init__", side_effect=AssertionError("second executor")) as native:
                    result = run_preflight(Path(temp) / "review")
            legacy.assert_not_called()
            native.assert_not_called()
        self.assertEqual("PASS", result["status"])
        self.assertEqual("ServiceGuard", result["evaluation"]["effect_executor"])
        self.assertEqual(0, result["evaluation"]["duplicate_effects"])

    def test_preflight_parent_network_is_loopback_only(self):
        import ipaddress
        import socket
        from unittest.mock import patch
        connect = socket.socket.connect
        observed = []
        def checked(sock, address):
            if sock.family in (socket.AF_INET, socket.AF_INET6):
                self.assertTrue(ipaddress.ip_address(address[0]).is_loopback, address)
                observed.append(address[0])
            return connect(sock, address)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(socket.socket, "connect", checked):
                result = run_preflight(Path(temp) / "review")
        self.assertTrue(observed)
        self.assertEqual("PASS", result["status"])

    def test_ci_exercises_isolated_reviewer_and_published_main(self):
        workflow = (REPO / ".github/workflows/nonzero-pr.yml").read_text()
        self.assertIn("  push:\n    branches: [main]", workflow)
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertIn("NVIDIA isolated reviewer preflight", workflow)
        self.assertIn("working-directory: ${{ runner.temp }}", workflow)
        self.assertIn('python -I -B "$GITHUB_WORKSPACE/scripts/nvidia_reviewer_preflight.py"', workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("pull_request_target:", workflow)


if __name__ == "__main__":
    unittest.main()
