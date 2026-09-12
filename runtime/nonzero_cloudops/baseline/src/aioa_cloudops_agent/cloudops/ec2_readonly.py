"""Narrow provider protocol for one targeted EC2 inspection."""

from collections.abc import Mapping
from typing import Any, Protocol


class Ec2DescribeInstancesClient(Protocol):
    """Only the scoped DescribeInstances call required by inspect_instance."""

    def describe_instances(
        self,
        *,
        InstanceIds: list[str],
    ) -> Mapping[str, Any]:
        """Describe exactly the requested instance identifiers."""
