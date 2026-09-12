import os
from pathlib import Path

import pytest

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.config import (
    LocalHitlSettings,
    ModelProviderName,
    PortableServerSettings,
    RuntimeMode,
)
from aioa_cloudops_agent.domain import ContractValidationError
from aioa_cloudops_agent.local_api import (
    LOCAL_API_BODY_MAX_BYTES,
    LOCAL_API_SOCKET_TIMEOUT_SECONDS,
    LocalApiApplication,
    LocalApiTokenAuthorizer,
    create_local_http_server,
)

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "p" * 48


def _portable_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in tuple(os.environ):
        if name.startswith("AIOA_") or name in {"APPLICATION_VERSION", "SOURCE_COMMIT"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIOA_LOCAL_HITL_STATE_PATH", str(tmp_path / "truth.json"))
    monkeypatch.setenv("AIOA_LOCAL_INVENTORY_PATH", str(tmp_path / "inventory.json"))
    monkeypatch.setenv("AIOA_LOCAL_API_TOKEN_PATH", str(tmp_path / "operator.token"))


def test_portable_settings_ignore_ambient_aws_credentials(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _portable_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ambient-not-authority")
    monkeypatch.setenv("AWS_REGION", "us-east-1")

    settings = PortableServerSettings.from_environment()

    assert settings.runtime.mode is RuntimeMode.PORTABLE
    assert settings.runtime.model_provider is ModelProviderName.MOCK
    assert settings.runtime.aws_calls_allowed is False
    assert settings.allowed_egress == "none"
    assert settings.provider_timeout_seconds == settings.retry_budget == 0
    assert settings.request_timeout_seconds == LOCAL_API_SOCKET_TIMEOUT_SECONDS
    assert settings.request_size_limit_bytes == LOCAL_API_BODY_MAX_BYTES


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AIOA_RUNTIME_MODE", "aws"),
        ("AIOA_MODEL_PROVIDER", "bedrock"),
        ("AIOA_ALLOWED_ORIGINS", "*"),
        ("AIOA_ALLOWED_EGRESS", "internet"),
        ("AIOA_STORAGE_MODE", "cloud"),
        ("AIOA_PROVIDER_TIMEOUT_SECONDS", "1"),
        ("AIOA_RETRY_BUDGET", "1"),
        ("AIOA_AUTHORITY_MODE", "MODEL_AUTONOMOUS"),
    ],
)
def test_portable_settings_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    name: str,
    value: str,
) -> None:
    _portable_environment(monkeypatch, tmp_path)
    monkeypatch.setenv(name, value)

    with pytest.raises(ContractValidationError):
        PortableServerSettings.from_environment()


def test_container_binding_requires_explicit_intent(tmp_path: Path) -> None:
    runtime = create_local_hitl_runtime(
        LocalHitlSettings(
            state_path=tmp_path / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        )
    )
    application = LocalApiApplication(runtime, LocalApiTokenAuthorizer(TOKEN))
    with pytest.raises(ValueError, match=r"only to 127\.0\.0\.1"):
        create_local_http_server(application, host="0.0.0.0", port=0)

    server = create_local_http_server(
        application,
        host="0.0.0.0",
        port=0,
        allow_container_binding=True,
    )
    try:
        assert server.server_address[0] == "0.0.0.0"
    finally:
        server.server_close()


def test_docker_build_context_is_deny_by_default_and_runtime_is_non_root() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert dockerignore.splitlines()[1] == "**"
    assert "!src/**" in dockerignore
    assert "USER aioa" in dockerfile
    assert "chmod 2770 /var/lib/aioa" in dockerfile
    assert "ENTRYPOINT [\"python\", \"-m\", \"aioa_cloudops_agent.portable_server\"]" in dockerfile
    assert "AIOA_LOCAL_HITL_STATE_PATH=/var/lib/aioa/durable-truth.json" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "chmod 777" not in dockerfile
    assert "COPY ." not in dockerfile
