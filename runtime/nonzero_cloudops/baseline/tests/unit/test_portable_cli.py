from __future__ import annotations

import json
from pathlib import Path

from aioa_cloudops_agent.portable import PortableDemoReceipt
from aioa_cloudops_agent.portable.cli import main

ROOT = Path(__file__).resolve().parents[2]
RESOURCE_ROOT = ROOT / "src" / "aioa_cloudops_agent" / "portable" / "resources"


def _portable_environment(monkeypatch: object) -> None:
    monkeypatch.setenv("AIOA_RUNTIME_MODE", "portable")
    monkeypatch.setenv("AIOA_MODEL_PROVIDER", "mock")
    monkeypatch.setenv("AIOA_AWS_INTEGRATION_ENABLED", "false")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def test_packaged_resources_match_the_reviewed_offline_inputs() -> None:
    assert (RESOURCE_ROOT / "phase3-deployment-contract.json").read_bytes() == (
        ROOT / "requirements" / "phase3-deployment-contract.json"
    ).read_bytes()
    assert (RESOURCE_ROOT / "post-deploy-verifier-pass.json").read_bytes() == (
        ROOT / "tests" / "fixtures" / "phase3" / "post-deploy-verifier-pass.json"
    ).read_bytes()


def test_packaged_cli_runs_with_explicit_paths(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    _portable_environment(monkeypatch)
    output = tmp_path / "receipt.json"

    code = main(
        [
            "--workspace",
            str(tmp_path / "workspace"),
            "--output",
            str(output),
        ]
    )

    assert code == 0
    receipt = PortableDemoReceipt.model_validate_json(output.read_text(encoding="utf-8"))
    assert PortableDemoReceipt.model_validate_json(capsys.readouterr().out) == receipt


def test_packaged_cli_reports_fixed_failure_without_state(
    tmp_path: Path,
    monkeypatch: object,
    capsys: object,
) -> None:
    monkeypatch.setenv("AIOA_RUNTIME_MODE", "aws")
    monkeypatch.setenv("AIOA_MODEL_PROVIDER", "bedrock")
    monkeypatch.setenv("AIOA_AWS_INTEGRATION_ENABLED", "true")
    output = tmp_path / "receipt.json"

    code = main(["--workspace", str(tmp_path / "workspace"), "--output", str(output)])

    assert code == 1
    assert json.loads(capsys.readouterr().out) == {
        "aws_mutations": 0,
        "external_network_connections": 0,
        "reason": "PORTABLE_RUNTIME_CONFIGURATION_INVALID",
        "status": "FAIL",
    }
    assert not output.exists()
