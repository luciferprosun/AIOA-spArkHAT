from collections.abc import Callable
from typing import Any

import pytest
from botocore.config import Config

from aioa_cloudops_agent.aws_clients import (
    AWS_CONNECT_TIMEOUT_SECONDS,
    AWS_READ_TIMEOUT_SECONDS,
    AWS_TOTAL_MAX_ATTEMPTS,
    BEDROCK_READ_TIMEOUT_SECONDS,
    create_bedrock_runtime_client,
    create_cloudwatch_read_client,
    create_ec2_read_client,
    create_ec2_stop_client,
    create_lambda_invoke_client,
)
from aioa_cloudops_agent.config.settings import DEFAULT_AWS_REGION


class RecordingClientCreator:
    def __init__(self) -> None:
        self.client = object()
        self.calls: list[tuple[str, str, Config]] = []

    def __call__(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> object:
        self.calls.append((service_name, region_name, config))
        return self.client


@pytest.mark.parametrize(
    ("factory", "service_name", "read_timeout"),
    (
        (create_ec2_read_client, "ec2", AWS_READ_TIMEOUT_SECONDS),
        (create_ec2_stop_client, "ec2", AWS_READ_TIMEOUT_SECONDS),
        (create_cloudwatch_read_client, "cloudwatch", AWS_READ_TIMEOUT_SECONDS),
        (create_lambda_invoke_client, "lambda", AWS_READ_TIMEOUT_SECONDS),
        (
            create_bedrock_runtime_client,
            "bedrock-runtime",
            BEDROCK_READ_TIMEOUT_SECONDS,
        ),
    ),
)
def test_critical_client_factories_own_region_timeouts_and_retry_count(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[..., Any],
    service_name: str,
    read_timeout: int,
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_MAX_ATTEMPTS", "99")
    monkeypatch.setenv("AWS_RETRY_MODE", "adaptive")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/untrusted/shared-config")
    creator = RecordingClientCreator()

    client = factory(client_creator=creator)

    assert client is creator.client
    assert len(creator.calls) == 1
    actual_service, region_name, config = creator.calls[0]
    assert actual_service == service_name
    assert region_name == DEFAULT_AWS_REGION == "eu-central-1"
    assert config.region_name == DEFAULT_AWS_REGION
    assert config.connect_timeout == AWS_CONNECT_TIMEOUT_SECONDS
    assert config.read_timeout == read_timeout
    assert config.ignore_configured_endpoint_urls is True
    assert 0 < config.connect_timeout < 60
    assert 0 < config.read_timeout < 60
    assert config.retries == {
        "mode": "standard",
        "total_max_attempts": AWS_TOTAL_MAX_ATTEMPTS,
    }
    assert config.retries["total_max_attempts"] == 1


def test_each_client_receives_a_fresh_transport_config() -> None:
    creator = RecordingClientCreator()

    create_ec2_read_client(client_creator=creator)
    create_ec2_read_client(client_creator=creator)

    assert len(creator.calls) == 2
    assert creator.calls[0][2] is not creator.calls[1][2]


def test_configured_endpoint_environment_cannot_redirect_real_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "unit-test-placeholder")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "unit-test-placeholder")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://untrusted.invalid")
    monkeypatch.setenv("AWS_ENDPOINT_URL_EC2", "https://untrusted-ec2.invalid")

    client = create_ec2_read_client()

    assert client.meta.endpoint_url == "https://ec2.eu-central-1.amazonaws.com"
