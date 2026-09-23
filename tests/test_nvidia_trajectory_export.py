from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "runtime" / "nvidia_trajectory.py"
SCRIPT = REPO / "scripts" / "nvidia_trajectory_export.py"
NVIDIA_ATIF_SITE = os.environ.get("NVIDIA_NAT_ATIF_SITE")


def _load_module():
    spec = importlib.util.spec_from_file_location("nvidia_trajectory", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("trajectory module import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _demo() -> dict:
    return {
        "schema": "aioa.nvidia-competition-demo.v1",
        "product_name": "AIOA spArkHAT",
        "execution_mode": "TEST_FIXTURE",
        "live_provider_claimed": False,
        "events": [
            {
                "stage": f"stage_{index:02d}",
                "status": "PASS",
                "authority": "EVIDENCE_ONLY",
            }
            for index in range(1, 15)
        ],
        "safety": {
            "provider_output_authority": False,
            "duplicate_effects": 0,
            "hidden_chain_of_thought_recorded": False,
            "human_bound_effect_authority": True,
        },
    }


class NvidiaTrajectoryExportTest(unittest.TestCase):
    def test_projection_is_bounded_and_deterministic(self) -> None:
        module = _load_module()
        first = module.competition_demo_to_atif(_demo())
        second = module.competition_demo_to_atif(_demo())
        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], "ATIF-v1.7")
        self.assertEqual(len(first["steps"]), 15)
        self.assertEqual(
            [step["step_id"] for step in first["steps"]], list(range(1, 16))
        )
        self.assertTrue(all(step["source"] == "system" for step in first["steps"]))
        self.assertFalse(
            any("reasoning_content" in step for step in first["steps"])
        )
        self.assertEqual(first["agent"]["name"], "AIOA spArkHAT")
        self.assertEqual(
            first["extra"]["projection_kind"], "DETERMINISTIC_EVIDENCE_PROJECTION"
        )
        self.assertFalse(first["extra"]["live_provider_claimed"])
        self.assertEqual(len(first["extra"]["source_canonical_json_sha256"]), 64)

    def test_context_continuation_keeps_one_logical_session(self) -> None:
        module = _load_module()
        value = module.competition_demo_to_atif(
            _demo(),
            session_id="gold24-session-001",
            continued_trajectory_ref="trajectory-segment-002.json",
        )
        self.assertEqual(value["session_id"], "gold24-session-001")
        self.assertEqual(
            value["continued_trajectory_ref"], "trajectory-segment-002.json"
        )
        with self.assertRaises(module.TrajectoryExportError):
            module.competition_demo_to_atif(_demo(), session_id="")
        with self.assertRaises(module.TrajectoryExportError):
            module.competition_demo_to_atif(
                _demo(), continued_trajectory_ref=""
            )

    def test_live_or_hidden_reasoning_inputs_fail_closed(self) -> None:
        module = _load_module()
        value = _demo()
        value["live_provider_claimed"] = True
        with self.assertRaises(module.TrajectoryExportError):
            module.competition_demo_to_atif(value)
        value = _demo()
        value["safety"]["hidden_chain_of_thought_recorded"] = True
        with self.assertRaises(module.TrajectoryExportError):
            module.competition_demo_to_atif(value)
        value = _demo()
        value["safety"]["provider_output_authority"] = True
        with self.assertRaises(module.TrajectoryExportError):
            module.competition_demo_to_atif(value)

    def test_malformed_events_fail_closed(self) -> None:
        module = _load_module()
        cases = (
            None,
            [],
            [{"stage": "only-stage"}],
            [{"stage": 1, "status": "PASS", "authority": "EVIDENCE_ONLY"}],
        )
        for events in cases:
            with self.subTest(events=events):
                value = _demo()
                value["events"] = events
                with self.assertRaises(module.TrajectoryExportError):
                    module.competition_demo_to_atif(value)

    def test_cli_does_not_modify_repository(self) -> None:
        before = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "demo.json"
            output = root / "trajectory.json"
            source.write_text(json.dumps(_demo()), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "--input", str(source), "--output", str(output)],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "ATIF-v1.7")
        after = subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        self.assertEqual(after, before)

    @unittest.skipUnless(
        NVIDIA_ATIF_SITE,
        "set NVIDIA_NAT_ATIF_SITE to pinned NVIDIA NeMo Agent Toolkit site",
    )
    def test_projection_validates_with_pinned_nvidia_atif_model(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = NVIDIA_ATIF_SITE
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "trajectory.json"
            module = _load_module()
            artifact.write_text(
                json.dumps(
                    module.competition_demo_to_atif(
                        _demo(),
                        session_id="gold24-session-001",
                        continued_trajectory_ref="trajectory-segment-002.json",
                    )
                ),
                encoding="utf-8",
            )
            validator = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import json,sys; "
                        "from nat.atif.trajectory import ATIF_VERSION,Trajectory; "
                        "p=json.load(open(sys.argv[1])); "
                        "o=Trajectory.model_validate(p); "
                        "assert o.schema_version==ATIF_VERSION; "
                        "assert o.session_id=='gold24-session-001'; "
                        "assert o.continued_trajectory_ref=='trajectory-segment-002.json'; "
                        "assert all(s.reasoning_content is None for s in o.steps); "
                        "print(ATIF_VERSION)"
                    ),
                    str(artifact),
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(validator.returncode, 0, validator.stderr)
        self.assertEqual(validator.stdout.strip(), "ATIF-v1.7")


if __name__ == "__main__":
    unittest.main()
