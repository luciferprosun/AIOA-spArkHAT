"""AUTO/read-only QueryResource service through the normalized CloudProvider."""

from datetime import datetime

from pydantic import ValidationError

from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import (
    CloudFinding,
    ControlResult,
    Ec2Resource,
    ElasticIpResource,
    FailureDetail,
    FailureKind,
    ResourceEvidence,
    ResourceProvenance,
    ResourceQuery,
    Run,
    SecurityGroupResource,
)

from .provider import (
    CloudAdapterUnavailableError,
    CloudProvider,
    CloudResourceNotFoundError,
)

REQUIRED_EC2_TAGS = frozenset({"Environment", "Owner"})


class QueryResource:
    """Validate, read, normalize, and provenance-stamp one exact resource."""

    authority = AuthorityGate.AUTO

    def __init__(self, provider: CloudProvider) -> None:
        if not isinstance(getattr(provider, "adapter_name", None), str):
            raise TypeError("provider must expose a stable adapter_name")
        if not callable(getattr(provider, "get_resource", None)):
            raise TypeError("provider must implement get_resource")
        self._provider = provider

    def execute(
        self,
        query: ResourceQuery | object,
        *,
        run: Run,
        observed_at: datetime,
    ) -> ControlResult[ResourceEvidence]:
        if not isinstance(run, Run):
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "QUERY_RUN_INVALID",
                "QueryResource requires a typed run",
            )
        try:
            validated_query = ResourceQuery.model_validate(query)
        except ValidationError:
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "RESOURCE_QUERY_INVALID",
                "Resource query is missing or malformed",
            )
        try:
            resource = self._provider.get_resource(validated_query)
        except CloudResourceNotFoundError:
            return self._failed(
                FailureKind.NOT_FOUND,
                "RESOURCE_NOT_FOUND",
                "Requested resource was not found",
            )
        except CloudAdapterUnavailableError:
            return self._failed(
                FailureKind.TOOL_ADAPTER_FAILURE,
                "CLOUD_ADAPTER_UNAVAILABLE",
                "Cloud inventory adapter is unavailable",
                retryable=True,
            )
        except Exception:
            return self._failed(
                FailureKind.TOOL_ADAPTER_FAILURE,
                "CLOUD_ADAPTER_INVALID_RESPONSE",
                "Cloud inventory adapter returned an invalid result",
            )
        findings = self._findings(resource)
        provenance = ResourceProvenance(
            run_id=run.run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            adapter=self._provider.adapter_name,
            resource_type=resource.resource_type,
            resource_id=resource.resource_id,
            observed_fields=tuple(sorted(resource.model_dump(mode="json"))),
            observed_at=observed_at,
        )
        try:
            evidence = ResourceEvidence.create(
                run=run,
                resource=resource,
                findings=findings,
                provenance=provenance,
                observed_at=observed_at,
            )
        except (TypeError, ValueError):
            return self._failed(
                FailureKind.TOOL_ADAPTER_FAILURE,
                "RESOURCE_EVIDENCE_INVALID",
                "Normalized resource evidence failed validation",
            )
        return ControlResult[ResourceEvidence].succeeded(evidence)

    @staticmethod
    def _findings(resource: object) -> tuple[CloudFinding, ...]:
        if isinstance(resource, ElasticIpResource):
            if resource.association_id is None:
                return (CloudFinding.UNATTACHED_ELASTIC_IP,)
            return (CloudFinding.CLEAN,)
        if isinstance(resource, SecurityGroupResource):
            public_ingress = any(
                rule.cidr_ipv4 == "0.0.0.0/0" for rule in resource.inbound_rules
            )
            if public_ingress:
                return (CloudFinding.OVERLY_PERMISSIVE_INGRESS,)
            return (CloudFinding.CLEAN,)
        if isinstance(resource, Ec2Resource):
            if not resource.tags.keys() >= REQUIRED_EC2_TAGS:
                return (CloudFinding.REQUIRED_TAGS_MISSING,)
            return (CloudFinding.CLEAN,)
        raise TypeError("unsupported normalized cloud resource")

    @staticmethod
    def _failed(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> ControlResult[ResourceEvidence]:
        return ControlResult[ResourceEvidence].failed(
            FailureDetail(kind=kind, code=code, message=message, retryable=retryable)
        )
