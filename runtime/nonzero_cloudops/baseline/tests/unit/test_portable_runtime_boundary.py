import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from aioa_cloudops_agent.agent import create_local_first_runtime, create_local_hitl_runtime
from aioa_cloudops_agent.config import (
    BedrockSettings,
    LocalFirstSettings,
    LocalHitlSettings,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)
from aioa_cloudops_agent.domain import ContractValidationError

ROOT = Path(__file__).parents[2]
AWS_ENVIRONMENT_NAMES = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
)


def _clear_aws_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in AWS_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_portable_settings_are_the_credential_free_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_aws_environment(monkeypatch)
    for name in (
        "AIOA_RUNTIME_MODE",
        "AIOA_MODEL_PROVIDER",
        "AIOA_AWS_INTEGRATION_ENABLED",
        "BEDROCK_MODEL_ID",
        "BEDROCK_REGION",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = RuntimeSettings.from_environment()

    assert settings == RuntimeSettings()
    assert settings.mode is RuntimeMode.PORTABLE
    assert settings.model_provider is ModelProviderName.MOCK
    assert settings.aws_calls_allowed is False
    assert settings.bedrock is None


def test_portable_composition_starts_without_aws_or_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_aws_environment(monkeypatch)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("portable startup attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    phase_one = create_local_first_runtime(
        LocalFirstSettings(state_path=tmp_path / "phase-one.json")
    )
    hitl = create_local_hitl_runtime(
        LocalHitlSettings(
            state_path=tmp_path / "durable.json",
            inventory_path=tmp_path / "inventory.json",
        )
    )

    assert phase_one.runtime_settings == hitl.runtime_settings == RuntimeSettings()
    assert phase_one.cloud_provider.network_calls == 0
    assert hitl.cloud_provider.network_calls == 0
    assert phase_one.model_provider.network_calls == 0
    assert hitl.model_provider.network_calls == 0


def test_portable_import_and_startup_succeed_in_aws_free_subprocess(tmp_path: Path) -> None:
    environment = dict(os.environ)
    for name in AWS_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    environment.update(
        {
            "AIOA_AWS_INTEGRATION_ENABLED": "false",
            "AIOA_MODEL_PROVIDER": "mock",
            "AIOA_RUNTIME_MODE": "portable",
            "AWS_EC2_METADATA_DISABLED": "true",
            "PYTHONPATH": str(ROOT / "src"),
        }
    )
    code = f"""
from pathlib import Path
from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.config import LocalHitlSettings, RuntimeSettings
settings = RuntimeSettings.from_environment()
runtime = create_local_hitl_runtime(
    LocalHitlSettings(
        state_path=Path({str(tmp_path / 'subprocess-durable.json')!r}),
        inventory_path=Path({str(tmp_path / 'subprocess-inventory.json')!r}),
    ),
    runtime_settings=settings,
)
assert runtime.runtime_settings.mode.value == "portable"
assert runtime.runtime_settings.model_provider.value == "mock"
assert runtime.cloud_provider.network_calls == 0
print("PORTABLE_STARTUP_PASS")
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PORTABLE_STARTUP_PASS"


def test_aws_selection_without_explicit_opt_in_or_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIOA_RUNTIME_MODE", "aws")
    monkeypatch.setenv("AIOA_MODEL_PROVIDER", "bedrock")
    monkeypatch.setenv("AIOA_AWS_INTEGRATION_ENABLED", "false")
    with pytest.raises(ContractValidationError, match="requires AIOA_AWS"):
        RuntimeSettings.from_environment()

    monkeypatch.setenv("AIOA_AWS_INTEGRATION_ENABLED", "true")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    monkeypatch.delenv("BEDROCK_REGION", raising=False)
    with pytest.raises(ContractValidationError, match="explicit Bedrock"):
        RuntimeSettings.from_environment()


def test_provider_selection_never_silently_substitutes_mock_for_aws(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError, match="supports only"):
        RuntimeSettings(
            mode=RuntimeMode.PORTABLE,
            model_provider=ModelProviderName.BEDROCK,
        )
    with pytest.raises(ContractValidationError, match="requires the explicit bedrock"):
        RuntimeSettings(
            mode=RuntimeMode.AWS,
            model_provider=ModelProviderName.MOCK,
            aws_integration_enabled=True,
        )
    aws_settings = RuntimeSettings(
        mode=RuntimeMode.AWS,
        model_provider=ModelProviderName.BEDROCK,
        aws_integration_enabled=True,
        bedrock=BedrockSettings(),
    )
    with pytest.raises(ContractValidationError, match="requires portable runtime"):
        create_local_first_runtime(
            LocalFirstSettings(state_path=tmp_path / "state.json"),
            runtime_settings=aws_settings,
        )
