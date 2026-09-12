"""Provider-neutral cloud inventory boundary and deterministic local AWS fixtures."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Protocol

from aioa_cloudops_agent.nz import (
    CloudResource,
    CloudResourceType,
    Ec2Resource,
    ElasticIpResource,
    ResourceQuery,
    SecurityGroupResource,
    SecurityGroupRule,
)

MOCK_UNATTACHED_EIP_ID: Final = "eipalloc-0123456789abcdef0"
MOCK_UNSAFE_SECURITY_GROUP_ID: Final = "sg-0123456789abcdef0"
MOCK_UNTAGGED_INSTANCE_ID: Final = "i-0fedcba9876543210"
MOCK_CLEAN_INSTANCE_ID: Final = "i-0123456789abcdef0"
MOCK_REGION: Final = "eu-central-1"


class CloudProviderError(RuntimeError):
    """Base typed cloud adapter failure without raw provider response leakage."""


class CloudResourceNotFoundError(CloudProviderError):
    """The exact validated resource does not exist in the selected provider."""


class CloudAdapterUnavailableError(CloudProviderError):
    """The selected read adapter failed before normalized evidence was produced."""


class CloudProvider(Protocol):
    """Small read-only interface consumed by QueryResource."""

    @property
    def adapter_name(self) -> str:
        """Return a stable non-secret provenance name."""

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        """Return one normalized resource or a typed provider failure."""


def default_mock_resources() -> tuple[CloudResource, ...]:
    """Return deterministic scenarios A-D from the Local-First Phase 1 contract."""

    return (
        ElasticIpResource(
            resource_id=MOCK_UNATTACHED_EIP_ID,
            region=MOCK_REGION,
            public_ip="198.51.100.42",
            association_id=None,
            tags={"Environment": "hackathon", "Owner": "platform"},
        ),
        SecurityGroupResource(
            resource_id=MOCK_UNSAFE_SECURITY_GROUP_ID,
            region=MOCK_REGION,
            vpc_id="vpc-0123456789abcdef0",
            inbound_rules=(
                SecurityGroupRule(
                    ip_protocol="tcp",
                    from_port=22,
                    to_port=22,
                    cidr_ipv4="0.0.0.0/0",
                ),
            ),
            outbound_rules=(
                SecurityGroupRule(
                    ip_protocol="-1",
                    cidr_ipv4="0.0.0.0/0",
                ),
            ),
            tags={"Environment": "hackathon", "Owner": "platform"},
        ),
        Ec2Resource(
            resource_id=MOCK_UNTAGGED_INSTANCE_ID,
            region=MOCK_REGION,
            state="running",
            instance_type="t3.micro",
            tags={},
        ),
        Ec2Resource(
            resource_id=MOCK_CLEAN_INSTANCE_ID,
            region=MOCK_REGION,
            state="running",
            instance_type="t3.micro",
            tags={
                "AIOACloudOpsSandbox": "true",
                "Environment": "hackathon",
                "Owner": "platform",
            },
        ),
    )


class MockAwsAdapter:
    """Deterministic, credential-free adapter used by local tests and demos."""

    def __init__(
        self,
        resources: tuple[CloudResource, ...] | None = None,
        *,
        fail_operations: frozenset[str] = frozenset(),
        utilization_values: tuple[float, ...] = (0.2,) * 12,
    ) -> None:
        selected = resources if resources is not None else default_mock_resources()
        self._resources = {
            (item.resource_type, item.resource_id, item.region): item for item in selected
        }
        if len(self._resources) != len(selected):
            raise ValueError("mock fixture resource identities must be unique")
        allowed_failures = {"get_resource", "describe_instances", "get_metric_statistics"}
        if not fail_operations <= allowed_failures:
            raise ValueError("unknown mock failure injection operation")
        if not utilization_values:
            raise ValueError("utilization_values must not be empty")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in utilization_values):
            raise ValueError("utilization_values must be numeric")
        self._fail_operations = fail_operations
        self._utilization_values = tuple(float(value) for value in utilization_values)
        self.read_calls: list[ResourceQuery] = []
        self.sdk_compatible_calls: list[str] = []
        self.mutation_calls = 0
        self.network_calls = 0

    @property
    def adapter_name(self) -> str:
        return "mock-aws-adapter"

    def get_resource(self, query: ResourceQuery) -> CloudResource:
        if not isinstance(query, ResourceQuery):
            raise TypeError("query must be ResourceQuery")
        if "get_resource" in self._fail_operations:
            raise CloudAdapterUnavailableError("mock cloud adapter failure was injected")
        self.read_calls.append(query)
        resource = self._resources.get((query.resource_type, query.resource_id, query.region))
        if resource is None:
            raise CloudResourceNotFoundError("resource was not found in the selected inventory")
        return resource

    def describe_instances(self, *, InstanceIds: list[str]) -> Mapping[str, Any]:
        """Support the existing canonical Strands inspection path with the same fixture."""

        if "describe_instances" in self._fail_operations:
            raise CloudAdapterUnavailableError("mock DescribeInstances failure was injected")
        if len(InstanceIds) != 1:
            raise CloudAdapterUnavailableError("mock adapter accepts exactly one instance ID")
        self.sdk_compatible_calls.append("ec2:DescribeInstances")
        try:
            resource = self.get_resource(
                ResourceQuery(
                    resource_type=CloudResourceType.EC2_INSTANCE,
                    resource_id=InstanceIds[0],
                    region=MOCK_REGION,
                )
            )
        except CloudResourceNotFoundError:
            return {"Reservations": []}
        if not isinstance(resource, Ec2Resource):
            raise CloudAdapterUnavailableError("mock instance fixture normalized incorrectly")
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": resource.resource_id,
                            "State": {"Name": resource.state},
                            "InstanceType": resource.instance_type,
                            "LaunchTime": datetime(2026, 8, 26, 6, 0, tzinfo=UTC),
                            "Monitoring": {"State": "disabled"},
                            "Placement": {"AvailabilityZone": f"{resource.region}a"},
                            "Tags": [
                                {"Key": key, "Value": value}
                                for key, value in sorted(resource.tags.items())
                            ],
                        }
                    ]
                }
            ]
        }

    def get_metric_statistics(self, **kwargs: object) -> Mapping[str, Any]:
        """Support the existing canonical utilization reader without a network call."""

        if "get_metric_statistics" in self._fail_operations:
            raise CloudAdapterUnavailableError("mock CloudWatch failure was injected")
        self.sdk_compatible_calls.append("cloudwatch:GetMetricStatistics")
        end_time = kwargs.get("EndTime")
        if not isinstance(end_time, datetime):
            raise CloudAdapterUnavailableError("mock CloudWatch EndTime is invalid")
        return {
            "Datapoints": [
                {
                    "Timestamp": end_time - timedelta(minutes=5 * (index + 1)),
                    "Average": value,
                    "Unit": "Percent",
                }
                for index, value in enumerate(self._utilization_values)
            ]
        }
