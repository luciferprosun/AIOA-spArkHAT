import pytest

from aioa_cloudops_agent.config import DynamoDbSettings
from aioa_cloudops_agent.domain import ContractValidationError


def test_dynamodb_settings_are_explicit_and_non_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STATE_TABLE_NAME", "aioa-hackathon-state")

    settings = DynamoDbSettings.from_environment()

    assert settings.table_name == "aioa-hackathon-state"
    assert settings.consistent_reads is True
    assert not hasattr(settings, "access_key")
    assert not hasattr(settings, "secret_key")
    assert not hasattr(settings, "endpoint_url")


def test_missing_table_configuration_fails_without_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("STATE_TABLE_NAME", raising=False)

    with pytest.raises(ContractValidationError, match="STATE_TABLE_NAME is required"):
        DynamoDbSettings.from_environment()


@pytest.mark.parametrize(
    "table_name",
    ["", "ab", "name with spaces", "a" * 256, "table/name"],
)
def test_invalid_table_names_fail_explicitly(table_name: str) -> None:
    with pytest.raises(ContractValidationError, match="table_name"):
        DynamoDbSettings(table_name=table_name)


def test_consistent_read_flag_must_be_typed() -> None:
    with pytest.raises(ContractValidationError, match="consistent_reads"):
        DynamoDbSettings(table_name="state-table", consistent_reads="yes")
