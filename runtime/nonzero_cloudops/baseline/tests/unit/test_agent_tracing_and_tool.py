from contextlib import AbstractContextManager
from datetime import UTC, datetime

import pytest

from aioa_cloudops_agent.agent import build_agent_trace_attributes, build_inspection_request
from aioa_cloudops_agent.cloudops import (
    InspectInstanceService,
    InvestigationIdentity,
    SandboxTarget,
    create_inspect_instance_tool,
    inspection_to_provenance,
)
from aioa_cloudops_agent.domain import ContractValidationError, generate_correlation_id
from aioa_cloudops_agent.nz import FailureKind

INSTANCE_ID = "i-0123456789abcdef0"


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=generate_correlation_id(),
        trace_id=generate_correlation_id(),
        correlation_id=generate_correlation_id(),
    )


class FakeEc2Client:
    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
        assert InstanceIds == [INSTANCE_ID]
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": INSTANCE_ID,
                            "State": {"Name": "running"},
                            "InstanceType": "t3.micro",
                            "LaunchTime": datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
                            "Monitoring": {"State": "disabled"},
                            "Placement": {"AvailabilityZone": "eu-central-1a"},
                            "Tags": [
                                {"Key": "AIOACloudOpsSandbox", "Value": "true"}
                            ],
                        }
                    ]
                }
            ]
        }


class RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}

    def set_attribute(self, name: str, value: object) -> None:
        self.attributes[name] = value


class SpanContext(AbstractContextManager[RecordingSpan]):
    def __init__(self, span: RecordingSpan) -> None:
        self.span = span

    def __enter__(self) -> RecordingSpan:
        return self.span

    def __exit__(self, *args: object) -> None:
        return None


class RecordingTracer:
    def __init__(self) -> None:
        self.span_names: list[str] = []
        self.spans: list[RecordingSpan] = []

    def start_as_current_span(self, name: str) -> SpanContext:
        self.span_names.append(name)
        span = RecordingSpan()
        self.spans.append(span)
        return SpanContext(span)


def test_agent_trace_attributes_propagate_uuidv7_correlation() -> None:
    identity = _identity()

    attributes = build_agent_trace_attributes(identity)

    assert attributes["aioa.run_id"] == str(identity.run_id)
    assert attributes["aioa.trace_id"] == str(identity.trace_id)
    assert attributes["aioa.correlation_id"] == str(identity.correlation_id)
    assert attributes["aioa.agent_id"] == "aioa-nonzero-cloudops-primary"
    assert attributes["aioa.authority_gate"] == "AUTO"
    assert attributes["aioa.operation_class"] == "READ_ONLY"


def test_native_tool_emits_safe_trace_and_typed_result() -> None:
    identity = _identity()
    tracer = RecordingTracer()
    service = InspectInstanceService(FakeEc2Client(), SandboxTarget(instance_id=INSTANCE_ID))
    inspect_instance = create_inspect_instance_tool(service, identity, tracer=tracer)

    result = inspect_instance(instance_id=INSTANCE_ID)

    assert inspect_instance.tool_name == "inspect_instance"
    assert result["status"] == "SUCCESS"
    assert result["value"]["run_id"] == str(identity.run_id)
    assert result["value"]["trace_id"] == str(identity.trace_id)
    assert result["value"]["correlation_id"] == str(identity.correlation_id)
    assert result["value"]["instance_id"] == INSTANCE_ID
    assert result["value"]["authority_gate"] == "AUTO"
    assert result["value"]["operation_class"] == "READ_ONLY"
    assert tracer.span_names == ["cloudops.inspect_instance"]
    assert tracer.spans[0].attributes["aioa.run_id"] == str(identity.run_id)
    assert tracer.spans[0].attributes["aioa.trace_id"] == str(identity.trace_id)
    assert tracer.spans[0].attributes["aioa.correlation_id"] == str(
        identity.correlation_id
    )
    assert tracer.spans[0].attributes["aioa.tool_name"] == "inspect_instance"
    assert tracer.spans[0].attributes["aioa.evidence_digest"] == result["value"][
        "evidence_digest"
    ]


def test_tool_result_and_provenance_retain_same_correlation_and_digest() -> None:
    identity = _identity()
    service = InspectInstanceService(FakeEc2Client(), SandboxTarget(instance_id=INSTANCE_ID))
    inspection = service.inspect(instance_id=INSTANCE_ID, identity=identity)
    event = inspection_to_provenance(
        inspection,
        event_id="evt-tool-1",
        sequence=1,
        timestamp=datetime(2026, 8, 23, 9, 1, tzinfo=UTC),
    )

    assert event.correlation_id == identity.correlation_id
    assert event.evidence_digest == inspection.evidence_digest
    assert event.attributes["instance_id"] == INSTANCE_ID


def test_malformed_tool_input_fails_explicitly() -> None:
    service = InspectInstanceService(FakeEc2Client(), SandboxTarget(instance_id=INSTANCE_ID))
    inspect_instance = create_inspect_instance_tool(service, _identity())

    result = inspect_instance(instance_id="not-an-instance")

    assert result["status"] == "FAILURE"
    assert result["failure"]["kind"] == FailureKind.VALIDATION_FAILURE.value


def test_model_like_extra_scope_arguments_are_not_accepted() -> None:
    service = InspectInstanceService(FakeEc2Client(), SandboxTarget(instance_id=INSTANCE_ID))
    inspect_instance = create_inspect_instance_tool(service, _identity())

    with pytest.raises(TypeError):
        inspect_instance(
            instance_id=INSTANCE_ID,
            region="us-east-1",
            account_scope="model-expanded-scope",
        )


def test_inspection_request_forces_one_tool_and_no_mutation_claim() -> None:
    request = build_inspection_request(SandboxTarget(instance_id=INSTANCE_ID))

    assert "inspect_instance exactly once" in request
    assert INSTANCE_ID in request
    assert "only on the returned evidence" in request
    assert "Do not claim or propose any mutation" in request


def test_untyped_request_target_fails_explicitly() -> None:
    with pytest.raises(ContractValidationError, match="SandboxTarget"):
        build_inspection_request(INSTANCE_ID)
