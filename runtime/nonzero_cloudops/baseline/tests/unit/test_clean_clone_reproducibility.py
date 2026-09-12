import json
from dataclasses import asdict
from pathlib import Path

import pytest
from scripts.prove_clean_clone import (
    DEV_INSTALL_TIMEOUT_SECONDS,
    PUBLIC_REPOSITORY_URL,
    SAFE_SMOKE_CHECKS,
    _run,
    clone_command,
    install_command,
    sanitized_environment,
    smoke_commands,
    validate_readme_contract,
    validation_payload,
)

ROOT = Path(__file__).resolve().parents[2]


def test_readme_contains_exact_public_install_and_verification_contract() -> None:
    assert validate_readme_contract(ROOT) == ()


def test_readme_contract_fails_when_a_harness_setup_step_is_missing(
    tmp_path: Path,
) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    (tmp_path / "README.md").write_text(
        readme.replace("python3.12 -m venv .venv", "removed setup step", 1),
        encoding="utf-8",
    )

    assert "README_STEP_MISSING:3" in validate_readme_contract(tmp_path)


@pytest.mark.parametrize(
    ("command", "step"),
    (
        (".venv/bin/python scripts/build_reviewer_evidence_manifest.py --check", 8),
        (".venv/bin/python scripts/validate_reviewer_evidence_manifest.py", 9),
    ),
)
def test_readme_contract_requires_every_manifest_smoke_step(
    tmp_path: Path,
    command: str,
    step: int,
) -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    (tmp_path / "README.md").write_text(
        readme.replace(command, "removed manifest step", 1),
        encoding="utf-8",
    )

    assert f"README_STEP_MISSING:{step}" in validate_readme_contract(tmp_path)


def test_harness_plan_uses_full_no_local_clone_and_fresh_noneditable_install() -> None:
    clone = clone_command("local-no-local", Path("fresh-repo"), ROOT)
    remote = clone_command("remote-public", Path("fresh-repo"), ROOT)
    install = install_command(Path("fresh-venv/bin/python"))

    assert "--no-local" in clone
    assert "--depth" not in clone
    assert "--branch" not in clone
    assert "--single-branch" not in clone
    assert "--depth" not in remote
    assert remote[remote.index("--branch") + 1] == "main"
    assert "--single-branch" in remote
    assert PUBLIC_REPOSITORY_URL in remote
    assert install[-1] == ".[dev]"
    assert "-e" not in install and "--editable" not in install
    assert DEV_INSTALL_TIMEOUT_SECONDS == 900


def test_missing_bootstrap_executable_is_a_fixed_failure_without_traceback(
    tmp_path: Path,
) -> None:
    result = _run(
        ("aioa-command-that-does-not-exist",),
        cwd=tmp_path,
        env={"PATH": ""},
    )

    assert result.returncode == 126
    assert result.stdout == result.stderr == ""


def test_harness_scrubs_aws_credentials_and_runs_only_public_safe_smoke() -> None:
    environment = sanitized_environment(
        {
            "PATH": "/safe/bin",
            "AWS_ACCESS_KEY_ID": "test-value",
            "AWS_SECRET_ACCESS_KEY": "test-value",
            "AWS_SESSION_TOKEN": "test-value",
            "AWS_PROFILE": "test-profile",
            "BEDROCK_MODEL_ID": "model-input",
            "SANDBOX_INSTANCE_ID": "model-target",
            "AIOA_ALLOW_LIVE_SANDBOX_STOP": "true",
            "STATE_TABLE_NAME": "private-table",
            "PYTHONPATH": "/private/source",
            "PYTHONHOME": "/private/python",
            "VIRTUAL_ENV": "/private/venv",
            "BOTO_CONFIG": "/private/boto-config",
            "APP_STAGE": "private-stage",
            "MODEL_MAX_OUTPUT_TOKENS": "1",
            "IDLE_CPU_THRESHOLD_PERCENT": "99",
            "HOME": "/private/home",
            "XDG_CONFIG_HOME": "/private/xdg",
            "PIP_INDEX_URL": "https://private-index.invalid/simple",
            "PIP_EXTRA_INDEX_URL": "https://private-extra.invalid/simple",
            "PIP_FIND_LINKS": "/private/wheels",
            "PIP_NO_INDEX": "1",
            "GIT_CONFIG_GLOBAL": "/private/gitconfig",
            "GIT_ASKPASS": "/private/askpass",
            "SSH_AUTH_SOCK": "/private/ssh-agent",
        }
    )
    commands = smoke_commands(Path("fresh-venv/bin/python"))

    assert environment["PATH"] == "/safe/bin"
    assert environment["AWS_EC2_METADATA_DISABLED"] == "true"
    assert environment["AWS_CONFIG_FILE"] == "/dev/null"
    assert environment["AWS_SHARED_CREDENTIALS_FILE"] == "/dev/null"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert environment["GIT_CONFIG_SYSTEM"] == "/dev/null"
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["PIP_CONFIG_FILE"] == "/dev/null"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert not any(
        key in environment
        for key in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SESSION_TOKEN",
            "BEDROCK_MODEL_ID",
            "SANDBOX_INSTANCE_ID",
            "AIOA_ALLOW_LIVE_SANDBOX_STOP",
            "STATE_TABLE_NAME",
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "BOTO_CONFIG",
            "APP_STAGE",
            "MODEL_MAX_OUTPUT_TOKENS",
            "IDLE_CPU_THRESHOLD_PERCENT",
            "HOME",
            "XDG_CONFIG_HOME",
            "PIP_INDEX_URL",
            "PIP_EXTRA_INDEX_URL",
            "PIP_FIND_LINKS",
            "PIP_NO_INDEX",
            "GIT_ASKPASS",
            "SSH_AUTH_SOCK",
        )
    )
    assert "AWS_PROFILE" not in environment
    assert len(commands) == len(SAFE_SMOKE_CHECKS) == 6
    joined = " ".join(part for command in commands for part in command)
    assert "run_p0_gate.py --validate-only --json" in joined
    assert "run_p1_gate.py --validate-only --json" in joined
    assert commands[3][-2:] == (
        "scripts/build_reviewer_evidence_manifest.py",
        "--check",
    )
    assert commands[4][-1] == "scripts/validate_reviewer_evidence_manifest.py"
    assert commands[3].index("--check") > 0
    assert "test_full_mocked_approved_e2e" in joined
    assert commands.index(commands[4]) < commands.index(commands[5])
    assert "StopInstances" not in joined


def test_validate_only_is_deterministic_and_exposes_no_local_paths() -> None:
    first = validation_payload(ROOT, requested_mode="local-no-local")
    second = validation_payload(ROOT, requested_mode="local-no-local")
    encoded = json.dumps(asdict(first), sort_keys=True)

    assert first == second
    assert first.status == "PASS"
    assert "/home/" not in encoded
    assert "/media/" not in encoded
