import json
from uuid import UUID

import pytest
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanContext, TraceFlags, TraceState

from aioa_cloudops_agent.judge.telemetry import (
    SanitizedXRaySpanExporter,
    XRayCompatibleIdGenerator,
    initialize_judge_telemetry,
)

RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")
SECRET = "private-token-and-provider-body-must-never-export"
TELEMETRY_ENVIRONMENT = {
    "OTEL_SERVICE_NAME": "aioa-nonzero-orchestrator",
    "OTEL_TRACES_SAMPLER": "parentbased_traceidratio",
    "OTEL_TRACES_SAMPLER_ARG": "0.05",
    "OTEL_SEMCONV_STABILITY_OPT_IN": (
        "gen_ai_latest_experimental,gen_ai_unredacted_attributes="
    ),
}


class XRayClient:
    def __init__(self, response: object | None = None) -> None:
        self.response = {} if response is None else response
        self.calls: list[dict[str, object]] = []

    def put_trace_segments(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.response


class Span:
    def __init__(self) -> None:
        self.start_time = 1_000_000_000
        self.end_time = 2_000_000_000
        self.parent = None
        self.attributes = {
            "aioa.run_id": str(RUN_ID),
            "aioa.trace_id": str(TRACE_ID),
            "aioa.correlation_id": str(CORRELATION_ID),
            "http.route": "/judge/investigate",
            "aioa.outcome": "success",
            "aioa.dependency": "EC2_READ",
            "authorization": SECRET,
            "exception.message": SECRET,
            "gen_ai.prompt": SECRET,
            "gen_ai.provider.response": SECRET,
            "aioa.tool_arguments": SECRET,
        }
        self._context = SpanContext(
            trace_id=0x1234567890ABCDEF1234567890ABCDEF,
            span_id=0x1234567890ABCDEF,
            is_remote=False,
            trace_flags=TraceFlags.SAMPLED,
            trace_state=TraceState(),
        )

    def get_span_context(self) -> SpanContext:
        return self._context


def test_xray_exporter_emits_only_allowlisted_ids_route_outcome_and_dependency() -> None:
    client = XRayClient()
    exporter = SanitizedXRaySpanExporter(client)

    result = exporter.export([Span()])

    assert result is SpanExportResult.SUCCESS
    assert len(client.calls) == 1
    documents = client.calls[0]["TraceSegmentDocuments"]
    assert isinstance(documents, list) and len(documents) == 1
    document = json.loads(documents[0])
    assert document["name"] == "aioa.judge.operation"
    assert document["annotations"] == {
        "correlation_id": str(CORRELATION_ID),
        "dependency": "EC2_READ",
        "outcome": "success",
        "route": "/judge/investigate",
        "run_id": str(RUN_ID),
        "trace_id": str(TRACE_ID),
    }
    rendered = documents[0]
    assert SECRET not in rendered
    assert "prompt" not in rendered
    assert "tool" not in rendered
    assert "provider" not in rendered
    assert "exception" not in rendered


def test_xray_exporter_fails_closed_on_unprocessed_or_oversized_batch() -> None:
    exporter = SanitizedXRaySpanExporter(
        XRayClient({"UnprocessedTraceSegments": [{"ErrorCode": "Throttled"}]})
    )

    assert exporter.export([Span()]) is SpanExportResult.FAILURE
    assert exporter.export([Span()] * 11) is SpanExportResult.FAILURE


def test_xray_id_generator_uses_epoch_prefix_and_nonzero_bounded_entropy() -> None:
    generator = XRayCompatibleIdGenerator(
        clock=lambda: 1_724_512_800.75,
        random_bits=lambda _bits: 0,
    )

    trace_id = generator.generate_trace_id()

    assert trace_id >> 96 == 1_724_512_800
    assert trace_id & ((1 << 96) - 1) == 1
    assert generator.generate_span_id() == 1


def test_process_telemetry_uses_exact_sampled_provider_and_empty_unredacted_opt_in() -> None:
    telemetry = initialize_judge_telemetry(
        XRayClient(),
        environment=TELEMETRY_ENVIRONMENT,
        install_global=False,
    )

    try:
        sampler = telemetry.provider.sampler.get_description()
        assert "ParentBased" in sampler
        assert "0.05" in sampler
        assert telemetry.tracer is not None
    finally:
        telemetry.provider.shutdown()


def test_process_telemetry_rejects_nonempty_unredacted_genai_attributes() -> None:
    environment = {
        **TELEMETRY_ENVIRONMENT,
        "OTEL_SEMCONV_STABILITY_OPT_IN": (
            "gen_ai_latest_experimental,gen_ai_unredacted_attributes=true"
        ),
    }

    with pytest.raises(RuntimeError, match="telemetry configuration"):
        initialize_judge_telemetry(
            XRayClient(),
            environment=environment,
            install_global=False,
        )
