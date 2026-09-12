from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    Ec2MonitoringState,
    InspectInstanceService,
    InstanceInspection,
    InstanceInspectionDependencyError,
    InstanceInspectionError,
    InvestigationIdentity,
    SandboxTarget,
    SandboxTargetMismatchError,
    inspection_to_provenance,
)
from aioa_cloudops_agent.domain import (
    AuthorityGate,
    AwsOperationClass,
    ContractValidationError,
)
from aioa_cloudops_agent.nz import FailureKind, ResultStatus
from aioa_cloudops_agent.persistence import ProvenanceEventType

INSTANCE_ID = "i-0123456789abcdef0"
OTHER_INSTANCE_ID = "i-0fedcba9876543210"
LAUNCH_TIME = datetime(2026, 8, 23, 9, 0, tzinfo=UTC)
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )


def _instance(*, instance_id: str = INSTANCE_ID, tags: object = None) -> dict[str, Any]:
    return {
        "InstanceId": instance_id,
        "State": {"Name": "running"},
        "InstanceType": "t3.micro",
        "LaunchTime": LAUNCH_TIME,
        "Monitoring": {"State": "disabled"},
        "Placement": {"AvailabilityZone": "eu-central-1a"},
        "Tags": ([{"Key": "AIOACloudOpsSandbox", "Value": "true"}] if tags is None else tags),
        "OwnerId": "owner-marker",
        "CredentialMaterial": "must-not-leak",
    }


def _response(*instances: object) -> dict[str, object]:
    return {"Reservations": [{"Instances": list(instances)}]}


class RecordingEc2Client:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[list[str]] = []

    def describe_instances(self, *, InstanceIds: list[str]) -> object:
        self.calls.append(InstanceIds)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class ProviderReadError(RuntimeError):
    def __init__(self, code: str, status: int) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__("provider-secret-detail")


class SequencedEc2Client:
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = iter(outcomes)
        self.calls = 0

    def describe_instances(self, *, InstanceIds: list[str]) -> object:
        assert InstanceIds == [INSTANCE_ID]
        self.calls += 1
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _service(response: object) -> tuple[InspectInstanceService, RecordingEc2Client]:
    client = RecordingEc2Client(response)
    return InspectInstanceService(client, SandboxTarget(instance_id=INSTANCE_ID)), client


def test_inspection_requests_exact_target_and_returns_typed_safe_result() -> None:
    service, client = _service(_response(_instance()))
    identity = _identity()

    result = service.inspect(instance_id=INSTANCE_ID, identity=identity)

    assert client.calls == [[INSTANCE_ID]]
    assert isinstance(result, InstanceInspection)
    assert result.run_id == identity.run_id
    assert result.trace_id == identity.trace_id
    assert result.correlation_id == identity.correlation_id
    assert result.instance_id == INSTANCE_ID
    assert result.state is Ec2InstanceState.RUNNING
    assert result.instance_type == "t3.micro"
    assert result.monitoring_state is Ec2MonitoringState.DISABLED
    assert result.authority_gate is AuthorityGate.AUTO
    assert result.operation_class is AwsOperationClass.READ_ONLY
    assert "Reservations" not in result.as_dict()
    assert "OwnerId" not in result.as_dict()
    assert "CredentialMaterial" not in result.as_dict()
    assert "must-not-leak" not in repr(result.as_dict())
    assert "owner-marker" not in repr(result.as_dict())


def test_inspection_evidence_digest_is_deterministic() -> None:
    service, _ = _service(_response(_instance()))
    identity = _identity()

    first = service.inspect(instance_id=INSTANCE_ID, identity=identity)
    second = service.inspect(instance_id=INSTANCE_ID, identity=identity)

    assert first.evidence_digest == second.evidence_digest
    assert len(first.evidence_digest) == 64


def test_request_for_nonconfigured_instance_fails_before_provider_call() -> None:
    service, client = _service(_response(_instance()))

    with pytest.raises(SandboxTargetMismatchError, match="not the configured sandbox"):
        service.inspect(instance_id=OTHER_INSTANCE_ID, identity=_identity())

    assert client.calls == []


def test_returned_instance_must_match_exact_requested_target() -> None:
    service, client = _service(_response(_instance(instance_id=OTHER_INSTANCE_ID)))

    with pytest.raises(SandboxTargetMismatchError, match="does not match"):
        service.inspect(instance_id=INSTANCE_ID, identity=_identity())

    assert client.calls == [[INSTANCE_ID]]


@pytest.mark.parametrize(
    "tags",
    [
        [],
        [{"Key": "AIOACloudOpsSandbox", "Value": "false"}],
        [
            {"Key": "AIOACloudOpsSandbox", "Value": "true"},
            {"Key": "AIOACloudOpsSandbox", "Value": "true"},
        ],
        [{"Key": "Name", "Value": "sandbox"}],
    ],
)
def test_missing_ambiguous_or_wrong_sandbox_tag_fails_closed(tags: object) -> None:
    service, _ = _service(_response(_instance(tags=tags)))

    with pytest.raises(SandboxTargetMismatchError):
        service.inspect(instance_id=INSTANCE_ID, identity=_identity())


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"Reservations": None},
        _response(),
        _response(_instance(), _instance()),
        {"Reservations": [{"Instances": None}]},
        _response({**_instance(), "State": {"Name": "unknown"}}),
        _response({**_instance(), "LaunchTime": "not-a-datetime"}),
    ],
)
def test_ambiguous_or_malformed_provider_evidence_fails_explicitly(response: object) -> None:
    service, _ = _service(response)

    with pytest.raises(InstanceInspectionError):
        service.inspect(instance_id=INSTANCE_ID, identity=_identity())


def test_provider_failure_is_translated_without_leaking_details() -> None:
    service, _ = _service(RuntimeError("provider-secret-detail"))

    with pytest.raises(
        InstanceInspectionDependencyError, match="dependency is unavailable"
    ) as captured:
        service.inspect(instance_id=INSTANCE_ID, identity=_identity())

    assert "provider-secret-detail" not in str(captured.value)


def test_known_transient_inspection_failure_retries_within_fixed_cap() -> None:
    client = SequencedEc2Client(
        ProviderReadError("ThrottlingException", 429),
        _response(_instance()),
    )
    service = InspectInstanceService(client, SandboxTarget(instance_id=INSTANCE_ID))

    result = service.inspect(instance_id=INSTANCE_ID, identity=_identity())

    assert result.instance_id == INSTANCE_ID
    assert client.calls == 2


def test_access_denied_inspection_is_not_retried() -> None:
    client = SequencedEc2Client(
        ProviderReadError("AccessDenied", 403),
        _response(_instance()),
    )
    service = InspectInstanceService(client, SandboxTarget(instance_id=INSTANCE_ID))

    with pytest.raises(InstanceInspectionDependencyError):
        service.inspect(instance_id=INSTANCE_ID, identity=_identity())

    assert client.calls == 1


@pytest.mark.parametrize("instance_id", [None, "", "i-anything", "I-0123456789abcdef0"])
def test_malformed_instance_identifier_fails_explicitly(instance_id: object) -> None:
    with pytest.raises(ValidationError, match="valid EC2 instance"):
        SandboxTarget(instance_id=instance_id)


def test_missing_production_sandbox_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SANDBOX_INSTANCE_ID", raising=False)

    with pytest.raises(ContractValidationError, match="SANDBOX_INSTANCE_ID is required"):
        SandboxTarget.from_environment()


def test_production_scope_configuration_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_INSTANCE_ID", INSTANCE_ID)
    monkeypatch.setenv("SANDBOX_REGION", "eu-central-1")
    monkeypatch.setenv("SANDBOX_TAG_KEY", "AIOACloudOpsSandbox")
    monkeypatch.setenv("SANDBOX_TAG_VALUE", "true")

    target = SandboxTarget.from_environment()

    assert target.instance_id == INSTANCE_ID
    assert target.region == "eu-central-1"
    assert target.required_tag_key == "AIOACloudOpsSandbox"
    assert target.required_tag_value == "true"


def test_wrong_production_scope_region_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_INSTANCE_ID", INSTANCE_ID)
    monkeypatch.setenv("SANDBOX_REGION", "us-east-1")

    with pytest.raises(ContractValidationError, match="configuration is invalid"):
        SandboxTarget.from_environment()


def test_inspection_materializes_append_oriented_provenance() -> None:
    service, _ = _service(_response(_instance()))
    inspection = service.inspect(
        instance_id=INSTANCE_ID,
        identity=_identity(),
    )

    event = inspection_to_provenance(
        inspection,
        event_id="evt-inspection-1",
        sequence=1,
        timestamp=datetime(2026, 8, 23, 9, 1, tzinfo=UTC),
    )

    assert event.correlation_id == inspection.correlation_id
    assert event.event_type is ProvenanceEventType.CLOUDOPS_INSTANCE_INSPECTED
    assert event.evidence_digest == inspection.evidence_digest
    assert event.attributes["aws_api"] == "ec2:DescribeInstances"
    assert event.attributes["operation_class"] == "READ_ONLY"


def test_inspection_result_is_explicit_typed_success_union() -> None:
    service, _ = _service(_response(_instance()))

    result = service.inspect_result(instance_id=INSTANCE_ID, identity=_identity())
    restored = type(result).model_validate_json(result.model_dump_json())

    assert result.status is ResultStatus.SUCCESS
    assert result.value is not None
    assert result.failure is None
    assert restored == result
    assert restored.value is not None
    assert restored.value.run_id == RUN_ID
    assert restored.value.trace_id == TRACE_ID
    assert restored.value.correlation_id == CORRELATION_ID


def test_scope_denial_and_dependency_failure_are_distinguishable() -> None:
    scoped_service, scoped_client = _service(_response(_instance()))
    denied = scoped_service.inspect_result(
        instance_id=OTHER_INSTANCE_ID,
        identity=_identity(),
    )
    dependency_service, _ = _service(RuntimeError("provider-secret-detail"))
    unavailable = dependency_service.inspect_result(
        instance_id=INSTANCE_ID,
        identity=_identity(),
    )

    assert denied.status is ResultStatus.FAILURE
    assert denied.failure is not None
    assert denied.failure.kind is FailureKind.POLICY_DENIAL
    assert scoped_client.calls == []
    assert unavailable.status is ResultStatus.FAILURE
    assert unavailable.failure is not None
    assert unavailable.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert unavailable.failure.retryable is False
    assert "provider-secret-detail" not in unavailable.model_dump_json()


def test_wrong_region_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="eu-central-1"):
        SandboxTarget(instance_id=INSTANCE_ID, region="us-east-1")
