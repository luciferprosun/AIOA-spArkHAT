import os
from pathlib import Path

import pytest

from aioa_cloudops_agent.agent import create_local_hitl_runtime
from aioa_cloudops_agent.config import LocalFirstMode, LocalHitlSettings
from aioa_cloudops_agent.domain import ContractValidationError


def test_local_hitl_settings_require_explicit_mock_and_separate_files(
    tmp_path: Path,
) -> None:
    shared = tmp_path / "shared.json"

    with pytest.raises(ContractValidationError, match="explicit mock mode"):
        LocalHitlSettings(mode=LocalFirstMode.LIVE)
    with pytest.raises(ContractValidationError, match="must be separate"):
        LocalHitlSettings(state_path=shared, inventory_path=shared)
    with pytest.raises(ContractValidationError, match="between 60 and 3600"):
        LocalHitlSettings(request_ttl_seconds=59)


def test_local_hitl_settings_load_only_local_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    truth = tmp_path / "truth.json"
    inventory = tmp_path / "inventory.json"
    monkeypatch.setenv("AIOA_LOCAL_MODE", "mock")
    monkeypatch.setenv("AIOA_LOCAL_HITL_STATE_PATH", str(truth))
    monkeypatch.setenv("AIOA_LOCAL_INVENTORY_PATH", str(inventory))
    monkeypatch.setenv("AIOA_LOCAL_APPROVAL_TTL_SECONDS", "900")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "must-not-be-read")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-be-read")

    settings = LocalHitlSettings.from_environment()
    runtime = create_local_hitl_runtime(settings)

    assert settings.state_path == truth
    assert settings.inventory_path == inventory
    assert settings.request_ttl_seconds == 900
    assert runtime.repository.path == truth
    assert runtime.cloud_state.path == inventory
    assert runtime.cloud_provider.network_calls == 0
    assert not truth.exists()
    assert not inventory.exists()


@pytest.mark.parametrize("raw_ttl", ["not-an-integer", "0", "3601"])
def test_local_hitl_environment_rejects_invalid_ttl(
    monkeypatch: pytest.MonkeyPatch,
    raw_ttl: str,
) -> None:
    monkeypatch.setenv("AIOA_LOCAL_APPROVAL_TTL_SECONDS", raw_ttl)

    with pytest.raises(ContractValidationError):
        LocalHitlSettings.from_environment()


def test_local_hitl_paths_reject_traversal_symlinks_and_hardlink_aliases(
    tmp_path: Path,
) -> None:
    with pytest.raises(ContractValidationError, match="unsafe traversal"):
        LocalHitlSettings(
            state_path=tmp_path / "nested" / ".." / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        )

    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ContractValidationError, match="must not be a symlink"):
        LocalHitlSettings(state_path=link, inventory_path=tmp_path / "inventory.json")

    directory = tmp_path / "state-directory"
    directory.mkdir()
    directory_link = tmp_path / "linked-directory"
    directory_link.symlink_to(directory, target_is_directory=True)
    with pytest.raises(ContractValidationError, match="must not traverse a symlink"):
        LocalHitlSettings(
            state_path=directory_link / "truth.json",
            inventory_path=tmp_path / "inventory.json",
        )

    alias = tmp_path / "alias.json"
    os.link(target, alias)
    with pytest.raises(ContractValidationError, match="must be separate"):
        LocalHitlSettings(state_path=target, inventory_path=alias)
