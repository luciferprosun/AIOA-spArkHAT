from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "evidence-audit"
SCRIPT = SKILL / "scripts" / "audit_aioa.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("evidence_audit_skill", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("skill script import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvidenceAuditSkillTest(unittest.TestCase):
    def test_canonical_metadata_is_neutral_and_truthful(self) -> None:
        text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("name: evidence-audit", text)
        self.assertIn("author: LuciferSOL <42999854+luciferprosun@users.noreply.github.com>", text)
        self.assertNotIn("example.com", text)
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('int("14")', source)
        self.assertNotIn('int("300")', source)
        self.assertNotIn('int("9")', source)

    def test_sanitized_environment_uses_isolated_home(self) -> None:
        module = _load_script_module()
        values = {
            "HOME": "/tmp/source-home",
            "OPENROUTER_API_KEY": "placeholder-openrouter-secret",
            "NVIDIA_API_KEY": "placeholder-nvidia-secret",
            "AWS_SECRET_ACCESS_KEY": "placeholder-aws-secret",
            "GH_TOKEN": "placeholder-gh-secret",
            "SSH_AUTH_SOCK": "/run/user/1000/keyring/ssh",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch.dict(os.environ, values, clear=False):
                env = module._sanitized_env(root / "home", root / "tmp")
            self.assertEqual(Path(env["HOME"]), root / "home")
            self.assertEqual(Path(env["TMPDIR"]), root / "tmp")
            self.assertTrue(Path(env["XDG_CONFIG_HOME"]).is_relative_to(root))
            self.assertTrue(Path(env["XDG_CACHE_HOME"]).is_relative_to(root))
            self.assertTrue(Path(env["XDG_DATA_HOME"]).is_relative_to(root))
        for name in (
            "OPENROUTER_API_KEY",
            "NVIDIA_API_KEY",
            "AWS_SECRET_ACCESS_KEY",
            "GH_TOKEN",
            "SSH_AUTH_SOCK",
        ):
            self.assertNotIn(name, env)
        self.assertNotEqual(env["HOME"], values["HOME"])
        self.assertEqual(env["HTTP_PROXY"], module.FAIL_CLOSED_PROXY)
        self.assertEqual(env["NO_PROXY"], "127.0.0.1,localhost")

    def _valid_payload(self, module) -> dict:
        return {
            "status": "PASS",
            "scope": module.EXPECTED_SCOPE,
            "checks": {name: True for name in module.REQUIRED_PREFLIGHT_CHECKS},
            "projection": {
                "provider_mode": "TEST_FIXTURE",
                "memory_mode": "TEST_FIXTURE",
                "dvm_pheromone_mode": "SHADOW",
            },
            "evaluation": {
                "status": "PASS",
                "stage_count": 14,
                "duplicate_effects": 0,
                "restart_replay_dispatches": 0,
                "effect_executor": "ServiceGuard",
            },
            "claims": {
                "live_provider_validated_by_this_run": False,
                "live_cockroach_validated_by_this_run": False,
                "live_openrouter_validated_by_this_run": False,
                "live_aws_validated_by_this_run": False,
            },
        }

    def test_malformed_nested_types_fail_closed(self) -> None:
        module = _load_script_module()
        cases = (
            ("projection", []),
            ("evaluation", "PASS"),
            ("checks", []),
            ("claims", []),
        )
        for field, malformed in cases:
            with self.subTest(field=field):
                payload = self._valid_payload(module)
                payload[field] = malformed
                with self.assertRaises(module.ReviewerError):
                    module._summarize(payload)

    def test_numeric_fields_require_exact_ints_not_bool_or_float(self) -> None:
        module = _load_script_module()
        payload = self._valid_payload(module)
        payload["evaluation"]["duplicate_effects"] = False
        self.assertEqual(module._summarize(payload)["status"], "FAIL")
        payload = self._valid_payload(module)
        payload["evaluation"]["restart_replay_dispatches"] = False
        self.assertEqual(module._summarize(payload)["status"], "FAIL")
        payload = self._valid_payload(module)
        payload["evaluation"]["stage_count"] = 14.0
        self.assertEqual(module._summarize(payload)["status"], "FAIL")

    def test_missing_required_evidence_fails_closed(self) -> None:
        module = _load_script_module()
        payload = self._valid_payload(module)
        del payload["checks"]["provider_has_no_authority"]
        self.assertEqual(module._summarize(payload)["status"], "FAIL")
        payload = self._valid_payload(module)
        del payload["claims"]["live_provider_validated_by_this_run"]
        self.assertEqual(module._summarize(payload)["status"], "FAIL")

    def test_wrapper_is_read_only_for_repository_status(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(REPO)],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        after = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(after, before)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "PASS")

    def test_eval_dataset_routes_to_one_canonical_skill(self) -> None:
        payload = json.loads(
            (SKILL / "evals" / "evals.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["skill_name"], "evidence-audit")
        evals = payload["evals"]
        self.assertGreaterEqual(len(evals), 6)
        selected = {item.get("expected_skill") for item in evals}
        self.assertTrue(selected.issubset({"evidence-audit", None}))
        self.assertTrue(
            any(item.get("expected_script") == "scripts/audit_aioa.py" for item in evals)
        )


if __name__ == "__main__":
    unittest.main()
