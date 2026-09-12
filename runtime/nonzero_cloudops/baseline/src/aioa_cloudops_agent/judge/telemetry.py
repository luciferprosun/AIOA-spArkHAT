"""Process-lifetime sampled OTel export with a sanitized AWS X-Ray boundary."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Final, Protocol

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
from opentelemetry.trace import Tracer

from aioa_cloudops_agent.domain.identifiers import validate_correlation_id

_SERVICE_NAME: Final = "aioa-nonzero-orchestrator"
_SAMPLER_NAME: Final = "parentbased_traceidratio"
_SAMPLE_RATIO: Final = 0.05
_UNREDACTED_OPT_IN: Final = "gen_ai_unredacted_attributes="
_EXPORTED_SPAN_NAME: Final = "aioa.judge.operation"
_MAX_EXPORT_BATCH: Final = 10
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9_./:{}-]{1,128}$")
_ATTRIBUTE_NAMES: Final[dict[str, str]] = {
    "aioa.run_id": "run_id",
    "aioa.trace_id": "trace_id",
    "aioa.correlation_id": "correlation_id",
    "aioa.route": "route",
    "http.route": "route",
    "aioa.outcome": "outcome",
    "aioa.dependency": "dependency",
}
_ROUTES: Final = frozenset(
    {
        "health",
        "investigate",
        "ready",
        "root",
        "status",
        "/health",
        "/judge/investigate",
        "/judge/status/{run_id}",
        "/ready",
    }
)
_OUTCOMES: Final = frozenset(
    {
        "budget_exhausted",
        "closed_non_success",
        "dependency_unavailable",
        "evidence_ambiguous",
        "error",
        "not_ready",
        "quota_exhausted",
        "recovery_required",
        "remediation_proposed",
        "success",
    }
)
_DEPENDENCIES: Final = frozenset(
    {
        "BEDROCK_MODEL",
        "CLOUDWATCH_READ",
        "DYNAMODB_READ",
        "EC2_READ",
        "SECRETS_READ",
        "VERIFICATION_READ",
    }
)


class _XRayClient(Protocol):
    def put_trace_segments(self, **kwargs: object) -> Mapping[str, object]: ...


class XRayCompatibleIdGenerator(IdGenerator):
    """Generate OTel IDs whose trace prefix is a valid X-Ray epoch field."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        random_bits: Callable[[int], int] = secrets.randbits,
    ) -> None:
        if not callable(clock) or not callable(random_bits):
            raise TypeError("X-Ray ID generator dependencies must be callable")
        self._clock = clock
        self._random_bits = random_bits

    def generate_span_id(self) -> int:
        return self._random_identifier(64)

    def generate_trace_id(self) -> int:
        try:
            raw_now = self._clock()
        except Exception as error:
            raise RuntimeError("X-Ray trace clock is unavailable") from error
        if (
            isinstance(raw_now, bool)
            or not isinstance(raw_now, (int, float))
            or not isfinite(float(raw_now))
        ):
            raise RuntimeError("X-Ray trace clock is unavailable")
        epoch_seconds = int(raw_now)
        if not 0 <= epoch_seconds <= 0xFFFFFFFF:
            raise RuntimeError("X-Ray trace clock is unavailable")
        return (epoch_seconds << 96) | self._random_identifier(96)

    def _random_identifier(self, bits: int) -> int:
        try:
            value = self._random_bits(bits)
        except Exception as error:
            raise RuntimeError("X-Ray trace entropy is unavailable") from error
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value < (1 << bits)
        ):
            raise RuntimeError("X-Ray trace entropy is unavailable")
        return value or 1


def _xray_trace_id(trace_id: int) -> str:
    rendered = f"{trace_id:032x}"
    return f"1-{rendered[:8]}-{rendered[8:]}"


def _safe_attribute(source_name: str, value: object) -> tuple[str, str] | None:
    exported_name = _ATTRIBUTE_NAMES.get(source_name)
    if exported_name is None or not isinstance(value, str):
        return None
    if _SAFE_TEXT.fullmatch(value) is None:
        return None
    if exported_name in {"run_id", "trace_id", "correlation_id"}:
        try:
            validate_correlation_id(value)
        except Exception:
            return None
    else:
        allowed_values = {
            "dependency": _DEPENDENCIES,
            "outcome": _OUTCOMES,
            "route": _ROUTES,
        }.get(exported_name)
        if allowed_values is None or value not in allowed_values:
            return None
    return exported_name, value


def _segment_document(span: ReadableSpan) -> str | None:
    context = span.get_span_context()
    start_time = span.start_time
    end_time = span.end_time
    if (
        not context.is_valid
        or not isinstance(start_time, int)
        or not isinstance(end_time, int)
        or start_time < 0
        or end_time < start_time
    ):
        return None
    annotations: dict[str, str] = {}
    for source_name, value in (span.attributes or {}).items():
        safe = _safe_attribute(source_name, value)
        if safe is not None:
            annotations[safe[0]] = safe[1]
    document: dict[str, object] = {
        "annotations": annotations,
        "end_time": end_time / 1_000_000_000,
        "id": f"{context.span_id:016x}",
        "name": _EXPORTED_SPAN_NAME,
        "start_time": start_time / 1_000_000_000,
        "trace_id": _xray_trace_id(context.trace_id),
    }
    parent = span.parent
    if parent is not None and parent.is_valid:
        document["parent_id"] = f"{parent.span_id:016x}"
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


class SanitizedXRaySpanExporter(SpanExporter):
    """Export only bounded segment envelopes; never events, bodies, or exceptions."""

    def __init__(self, client: _XRayClient) -> None:
        if not callable(getattr(client, "put_trace_segments", None)):
            raise TypeError("X-Ray client must expose put_trace_segments")
        self._client = client

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if len(spans) > _MAX_EXPORT_BATCH:
            return SpanExportResult.FAILURE
        documents: list[str] = []
        try:
            for span in spans:
                document = _segment_document(span)
                if document is None or len(document.encode("utf-8")) > 64_000:
                    return SpanExportResult.FAILURE
                documents.append(document)
            if not documents:
                return SpanExportResult.SUCCESS
            response = self._client.put_trace_segments(
                TraceSegmentDocuments=documents,
            )
            if not isinstance(response, Mapping):
                return SpanExportResult.FAILURE
            unprocessed = response.get("UnprocessedTraceSegments", [])
            if not isinstance(unprocessed, list) or unprocessed:
                return SpanExportResult.FAILURE
        except Exception:
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS


@dataclass(frozen=True, slots=True)
class JudgeTelemetry:
    """Owned provider/exporter references retained for one warm process."""

    provider: TracerProvider
    exporter: SanitizedXRaySpanExporter
    tracer: Tracer

    def force_flush(self, timeout_millis: int = 2_000) -> bool:
        if (
            isinstance(timeout_millis, bool)
            or not isinstance(timeout_millis, int)
            or not 1 <= timeout_millis <= 5_000
        ):
            return False
        try:
            return bool(self.provider.force_flush(timeout_millis=timeout_millis))
        except Exception:
            return False


def _telemetry_environment(environment: Mapping[str, str]) -> str:
    service_name = environment.get("OTEL_SERVICE_NAME")
    sampler_name = environment.get("OTEL_TRACES_SAMPLER")
    sample_ratio = environment.get("OTEL_TRACES_SAMPLER_ARG")
    semantic_options = environment.get("OTEL_SEMCONV_STABILITY_OPT_IN")
    try:
        ratio = float(sample_ratio) if sample_ratio is not None else float("nan")
    except ValueError:
        ratio = float("nan")
    options = semantic_options.split(",") if semantic_options is not None else []
    if (
        service_name != _SERVICE_NAME
        or sampler_name != _SAMPLER_NAME
        or not isfinite(ratio)
        or ratio != _SAMPLE_RATIO
        or options.count(_UNREDACTED_OPT_IN) != 1
        or any(
            option.startswith("gen_ai_unredacted_attributes=")
            and option != _UNREDACTED_OPT_IN
            for option in options
        )
    ):
        raise RuntimeError("judge telemetry configuration is unavailable")
    return service_name


def initialize_judge_telemetry(
    xray_client: _XRayClient,
    *,
    environment: Mapping[str, str] = os.environ,
    install_global: bool = True,
) -> JudgeTelemetry:
    """Build one 5% parent-based provider and one direct bounded X-Ray exporter."""

    service_name = _telemetry_environment(environment)
    exporter = SanitizedXRaySpanExporter(xray_client)
    provider = TracerProvider(
        id_generator=XRayCompatibleIdGenerator(),
        resource=Resource({"service.name": service_name}),
        sampler=ParentBased(TraceIdRatioBased(_SAMPLE_RATIO)),
        shutdown_on_exit=False,
        span_limits=SpanLimits(
            max_attributes=16,
            max_events=0,
            max_links=0,
            max_span_attribute_length=128,
        ),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            exporter,
            max_queue_size=64,
            schedule_delay_millis=500,
            max_export_batch_size=_MAX_EXPORT_BATCH,
            export_timeout_millis=2_000,
        )
    )
    if install_global:
        trace.set_tracer_provider(provider)
        if trace.get_tracer_provider() is not provider:
            provider.shutdown()
            raise RuntimeError("judge telemetry provider is unavailable")
    return JudgeTelemetry(
        provider=provider,
        exporter=exporter,
        tracer=provider.get_tracer("aioa_cloudops_agent.judge"),
    )
