"""Explicit, bounded AWS SDK client construction for the Day 15 runtime."""

from typing import Any, Final, Protocol

from botocore.config import Config

from aioa_cloudops_agent.config.settings import DEFAULT_AWS_REGION

AWS_CONNECT_TIMEOUT_SECONDS: Final = 3
AWS_READ_TIMEOUT_SECONDS: Final = 10
BEDROCK_READ_TIMEOUT_SECONDS: Final = 45
AWS_TOTAL_MAX_ATTEMPTS: Final = 1


class AwsClientCreator(Protocol):
    """Narrow injectable boundary matching ``boto3.client`` construction."""

    def __call__(
        self,
        service_name: str,
        *,
        region_name: str,
        config: Config,
    ) -> Any: ...


def _default_client_creator(
    service_name: str,
    *,
    region_name: str,
    config: Config,
) -> Any:
    """Import boto3 lazily so importing this module never creates an AWS client."""

    import boto3

    return boto3.client(service_name, region_name=region_name, config=config)


def _bounded_config(*, read_timeout_seconds: int) -> Config:
    """Return a fresh config that owns region, timeout, and retry behavior."""

    return Config(
        region_name=DEFAULT_AWS_REGION,
        connect_timeout=AWS_CONNECT_TIMEOUT_SECONDS,
        ignore_configured_endpoint_urls=True,
        read_timeout=read_timeout_seconds,
        retries={
            "mode": "standard",
            "total_max_attempts": AWS_TOTAL_MAX_ATTEMPTS,
        },
    )


def create_bedrock_runtime_config() -> Config:
    """Return the exact config Strands must pass to its Bedrock client."""

    return _bounded_config(read_timeout_seconds=BEDROCK_READ_TIMEOUT_SECONDS)


def _create_client(
    service_name: str,
    *,
    read_timeout_seconds: int,
    client_creator: AwsClientCreator | None,
) -> Any:
    creator = client_creator if client_creator is not None else _default_client_creator
    return creator(
        service_name,
        region_name=DEFAULT_AWS_REGION,
        config=_bounded_config(read_timeout_seconds=read_timeout_seconds),
    )


def create_ec2_read_client(*, client_creator: AwsClientCreator | None = None) -> Any:
    """Create the EC2 read client without SDK-owned retries."""

    return _create_client(
        "ec2",
        read_timeout_seconds=AWS_READ_TIMEOUT_SECONDS,
        client_creator=client_creator,
    )


def create_ec2_stop_client(*, client_creator: AwsClientCreator | None = None) -> Any:
    """Create the private EC2 stop/DryRun client without SDK-owned retries."""

    return _create_client(
        "ec2",
        read_timeout_seconds=AWS_READ_TIMEOUT_SECONDS,
        client_creator=client_creator,
    )


def create_cloudwatch_read_client(*, client_creator: AwsClientCreator | None = None) -> Any:
    """Create the CloudWatch read client without SDK-owned retries."""

    return _create_client(
        "cloudwatch",
        read_timeout_seconds=AWS_READ_TIMEOUT_SECONDS,
        client_creator=client_creator,
    )


def create_lambda_invoke_client(*, client_creator: AwsClientCreator | None = None) -> Any:
    """Create the private Lambda invoke client without SDK-owned retries."""

    return _create_client(
        "lambda",
        read_timeout_seconds=AWS_READ_TIMEOUT_SECONDS,
        client_creator=client_creator,
    )


def create_bedrock_runtime_client(*, client_creator: AwsClientCreator | None = None) -> Any:
    """Create the bounded Bedrock runtime client with one total SDK attempt."""

    creator = client_creator if client_creator is not None else _default_client_creator
    return creator(
        "bedrock-runtime",
        region_name=DEFAULT_AWS_REGION,
        config=create_bedrock_runtime_config(),
    )
