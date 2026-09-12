import ast
from contextlib import AbstractContextManager
from pathlib import Path
from threading import Event, Thread
from uuid import UUID

import pytest
from botocore.exceptions import (
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from aioa_cloudops_agent.agent import (
    CURRENT_REGISTERED_TOOL_COUNT,
    CURRENT_TOOL_NAMES,
    FINAL_TOOL_CAP,
)
from aioa_cloudops_agent.cloudops import (
    InspectInstanceService,
    InvestigationIdentity,
    SandboxTarget,
    create_inspect_instance_tool,
)
from aioa_cloudops_agent.nz import FailureKind
from aioa_cloudops_agent.safety import (
    BoundedReadRetry,
    CircuitBreakerSettings,
    CircuitDependency,
    CircuitOpenError,
    CircuitState,
    CircuitStateUnavailableError,
    DependencyCircuitBreaker,
    ReadRetryStateUnavailableError,
    RetryOperationClass,
    is_known_transient_read_error,
)

ROOT = Path(__file__).resolve().parents[2]
INSTANCE_ID = "i-0123456789abcdef0"
RUN_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
TRACE_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3b")
CORRELATION_ID = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3c")


class ProviderError(RuntimeError):
    def __init__(self, code: str, status: int, detail: str = "provider failure") -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(detail)


class ManualClock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _breaker(
    clock: ManualClock,
    *,
    threshold: int = 2,
    cooldown: float = 10.0,
) -> DependencyCircuitBreaker:
    return DependencyCircuitBreaker(
        CircuitBreakerSettings(
            failure_threshold=threshold,
            cooldown_seconds=cooldown,
        ),
        clock=clock,
    )


def _retry(
    breaker: DependencyCircuitBreaker,
    dependency: CircuitDependency = CircuitDependency.EC2_READ,
    *,
    max_attempts: int = 1,
    sleeper: object | None = None,
) -> BoundedReadRetry:
    return BoundedReadRetry(
        max_attempts=max_attempts,
        sleeper=sleeper,  # type: ignore[arg-type]
        circuit_breaker=breaker,
        dependency=dependency,
    )


def _transient() -> None:
    raise ProviderError("ThrottlingException", 429)


def _open(
    retry: BoundedReadRetry,
    *,
    failures: int = 1,
) -> None:
    for _ in range(failures):
        with pytest.raises(ProviderError):
            retry.run(_transient)


def _identity() -> InvestigationIdentity:
    return InvestigationIdentity(
        run_id=RUN_ID,
        trace_id=TRACE_ID,
        correlation_id=CORRELATION_ID,
    )


def test_terminal_transient_read_below_threshold_stays_closed_after_existing_retry_cap() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=2)
    calls = 0
    sleeps: list[int] = []

    def transient() -> None:
        nonlocal calls
        calls += 1
        _transient()

    with pytest.raises(ProviderError):
        _retry(breaker, max_attempts=2, sleeper=sleeps.append).run(transient)

    snapshot = breaker.snapshot(CircuitDependency.EC2_READ)
    assert calls == 2
    assert sleeps == [1]
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_transient_failures == 1
    assert breaker.snapshot(CircuitDependency.CLOUDWATCH_READ).state is CircuitState.CLOSED


def test_threshold_transient_failure_opens_with_dependency_unavailable_result() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    calls = 0

    class FailingEc2Client:
        def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
            nonlocal calls
            assert InstanceIds == [INSTANCE_ID]
            calls += 1
            _transient()

    service = InspectInstanceService(
        FailingEc2Client(),
        SandboxTarget(instance_id=INSTANCE_ID),
        retry=_retry(breaker),
    )

    result = service.inspect_result(instance_id=INSTANCE_ID, identity=_identity())

    assert result.failure is not None
    assert result.failure.kind is FailureKind.DEPENDENCY_UNAVAILABLE
    assert result.failure.code == "EC2_DESCRIBE_UNAVAILABLE"
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.OPEN
    assert calls == 1


def test_open_circuit_suppresses_provider_calls_during_cooldown() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker)
    calls = 0

    def provider() -> None:
        nonlocal calls
        calls += 1
        _transient()

    with pytest.raises(ProviderError):
        retry.run(provider)
    with pytest.raises(CircuitOpenError) as suppressed:
        retry.run(provider)

    assert calls == 1
    assert suppressed.value.reason_code == "DEPENDENCY_CIRCUIT_OPEN"
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.OPEN


def test_cooldown_allows_exactly_one_single_call_half_open_probe() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    sleeps: list[int] = []
    retry = _retry(breaker, max_attempts=3, sleeper=sleeps.append)
    calls = 0

    def provider() -> str:
        nonlocal calls
        calls += 1
        if calls <= 3:
            _transient()
        return "recovered"

    with pytest.raises(ProviderError):
        retry.run(provider)
    assert calls == 3 and sleeps == [1, 2]
    clock.value = 10.0

    assert retry.run(provider) == "recovered"
    assert calls == 4
    assert sleeps == [1, 2]


def test_successful_half_open_probe_closes_and_resets_counter() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker)
    _open(retry)
    clock.value = 10.0

    assert retry.run(lambda: "healthy") == "healthy"

    snapshot = breaker.snapshot(CircuitDependency.EC2_READ)
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_transient_failures == 0
    assert snapshot.half_open_probe_active is False


def test_failed_half_open_probe_reopens_with_fresh_bounded_cooldown() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker)
    _open(retry)
    clock.value = 10.0

    with pytest.raises(ProviderError):
        retry.run(_transient)
    clock.value = 19.999
    with pytest.raises(CircuitOpenError):
        retry.run(lambda: "too early")
    clock.value = 20.0

    assert retry.run(lambda: "recovered") == "recovered"
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.CLOSED


def test_retry_sleeper_failure_is_redacted_and_opens_without_repeat_call() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    calls = 0

    def provider() -> None:
        nonlocal calls
        calls += 1
        _transient()

    def broken_sleeper(_: int) -> None:
        raise RuntimeError("private-sleeper-detail")

    retry = _retry(breaker, max_attempts=2, sleeper=broken_sleeper)
    with pytest.raises(ReadRetryStateUnavailableError) as unavailable:
        retry.run(provider)

    assert calls == 1
    assert unavailable.value.reason_code == "READ_RETRY_STATE_UNAVAILABLE"
    assert "private-sleeper-detail" not in str(unavailable.value)
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.OPEN


def test_access_denied_validation_and_policy_outcomes_do_not_increment_transient_counter() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=2)
    retry = _retry(breaker, max_attempts=3)
    calls = 0

    def denied() -> None:
        nonlocal calls
        calls += 1
        raise ProviderError("AccessDenied", 403)

    with pytest.raises(ProviderError):
        retry.run(denied)
    snapshot = breaker.snapshot(CircuitDependency.EC2_READ)
    assert calls == 1
    assert snapshot.state is CircuitState.CLOSED
    assert snapshot.consecutive_transient_failures == 0

    service = InspectInstanceService(
        object(),  # type: ignore[arg-type]
        SandboxTarget(instance_id=INSTANCE_ID),
        retry=retry,
    )
    result = service.inspect_result(
        instance_id="i-0fedcba9876543210",
        identity=_identity(),
    )
    assert result.failure is not None and result.failure.kind is FailureKind.POLICY_DENIAL
    assert breaker.snapshot(CircuitDependency.EC2_READ) == snapshot


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException", "ValidationException"])
def test_permanent_provider_code_wins_over_transient_http_status(code: str) -> None:
    error = ProviderError(code, 500)
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker, max_attempts=3)
    calls = 0

    def permanent() -> None:
        nonlocal calls
        calls += 1
        raise error

    assert is_known_transient_read_error(error) is False
    with pytest.raises(ProviderError):
        retry.run(permanent)
    assert calls == 1
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.CLOSED


@pytest.mark.parametrize(
    "error",
    [
        ConnectTimeoutError(endpoint_url="https://ec2.eu-central-1.amazonaws.com"),
        ConnectionClosedError(endpoint_url="https://ec2.eu-central-1.amazonaws.com"),
        EndpointConnectionError(endpoint_url="https://ec2.eu-central-1.amazonaws.com"),
        ReadTimeoutError(endpoint_url="https://ec2.eu-central-1.amazonaws.com"),
    ],
    ids=("connect-timeout", "connection-closed", "endpoint", "read-timeout"),
)
def test_allowlisted_botocore_transport_errors_count_as_transient(
    error: Exception,
) -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker, max_attempts=1)

    def unavailable() -> None:
        raise error

    assert is_known_transient_read_error(error) is True
    with pytest.raises(type(error)):
        retry.run(unavailable)
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.OPEN


@pytest.mark.parametrize(
    "operation_class",
    [
        RetryOperationClass.MUTATION_BEFORE_SEND,
        RetryOperationClass.MUTATION_ACK_AMBIGUOUS,
    ],
)
def test_mutation_and_ambiguous_ack_classes_cannot_enter_retry_or_circuit(
    operation_class: RetryOperationClass,
) -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker)
    calls = 0

    def mutation() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(ValueError, match="read-only"):
        retry.run(mutation, operation_class=operation_class)

    assert calls == 0
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.CLOSED


def test_unavailable_clock_or_breaker_state_fails_closed_before_dependency_call() -> None:
    def broken_clock() -> float:
        raise RuntimeError("sensitive clock internals")

    breaker = DependencyCircuitBreaker(clock=broken_clock)
    retry = _retry(breaker)
    calls = 0

    def provider() -> None:
        nonlocal calls
        calls += 1

    with pytest.raises(CircuitStateUnavailableError) as unavailable:
        retry.run(provider)

    assert calls == 0
    assert unavailable.value.reason_code == "DEPENDENCY_CIRCUIT_UNAVAILABLE"
    assert "sensitive clock internals" not in str(unavailable.value)

    invalid_state_breaker = _breaker(ManualClock())
    invalid_state_breaker._states[CircuitDependency.EC2_READ] = object()  # type: ignore[assignment]
    with pytest.raises(CircuitStateUnavailableError):
        _retry(invalid_state_breaker).run(provider)
    assert calls == 0


def test_two_concurrent_half_open_attempts_allow_only_one_probe() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)
    retry = _retry(breaker)
    _open(retry)
    clock.value = 10.0
    entered = Event()
    release = Event()
    outcomes: list[str] = []

    def blocking_probe() -> str:
        entered.set()
        assert release.wait(timeout=2)
        return "healthy"

    def first_attempt() -> None:
        outcomes.append(retry.run(blocking_probe))

    thread = Thread(target=first_attempt)
    thread.start()
    assert entered.wait(timeout=2)
    with pytest.raises(CircuitOpenError):
        retry.run(lambda: "second probe")
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert outcomes == ["healthy"]
    assert breaker.snapshot(CircuitDependency.EC2_READ).state is CircuitState.CLOSED


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
        self.spans: list[RecordingSpan] = []

    def start_as_current_span(self, name: str) -> SpanContext:
        assert name == "cloudops.inspect_instance"
        span = RecordingSpan()
        self.spans.append(span)
        return SpanContext(span)


def test_circuit_reason_is_redacted_and_trace_linked() -> None:
    clock = ManualClock()
    breaker = _breaker(clock, threshold=1)

    class SecretFailingEc2Client:
        def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]:
            assert InstanceIds == [INSTANCE_ID]
            raise ProviderError(
                "ThrottlingException",
                429,
                "provider-secret-marker",
            )

    service = InspectInstanceService(
        SecretFailingEc2Client(),
        SandboxTarget(instance_id=INSTANCE_ID),
        retry=_retry(breaker),
    )
    tracer = RecordingTracer()
    tool = create_inspect_instance_tool(service, _identity(), tracer=tracer)
    first = tool(instance_id=INSTANCE_ID)
    suppressed = tool(instance_id=INSTANCE_ID)

    assert first["failure"]["kind"] == FailureKind.DEPENDENCY_UNAVAILABLE.value
    assert suppressed["failure"]["code"] == "EC2_READ_CIRCUIT_OPEN"
    assert "provider-secret-marker" not in str((first, suppressed, tracer.spans))
    assert tracer.spans[-1].attributes == {
        "aioa.run_id": str(RUN_ID),
        "aioa.trace_id": str(TRACE_ID),
        "aioa.correlation_id": str(CORRELATION_ID),
        "aioa.tool_name": "inspect_instance",
        "aioa.authority_gate": "AUTO",
        "aioa.operation_class": "READ_ONLY",
        "aioa.result_status": "FAILURE",
        "aioa.failure_kind": "DEPENDENCY_UNAVAILABLE",
        "aioa.failure_code": "EC2_READ_CIRCUIT_OPEN",
    }


def test_circuit_adds_no_tool_iam_network_or_mutation_surface() -> None:
    assert CURRENT_REGISTERED_TOOL_COUNT == FINAL_TOOL_CAP == 5
    assert CURRENT_TOOL_NAMES == (
        "inspect_instance",
        "read_utilization_metrics",
        "build_remediation_evidence",
        "stop_sandbox_instance",
        "verify_instance_state",
    )
    for relative in (
        "src/aioa_cloudops_agent/remediation",
        "src/aioa_cloudops_agent/recovery",
    ):
        for path in (ROOT / relative).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    assert not module.endswith((".safety.retry", ".safety.circuit"))
                    if module.endswith(".safety"):
                        assert all(
                            alias.name
                            not in {
                                "BoundedReadRetry",
                                "DependencyCircuitBreaker",
                                "ReadRetryStateUnavailableError",
                                "RetryOperationClass",
                            }
                            and not alias.name.startswith("Circuit")
                            for alias in node.names
                        )
                elif isinstance(node, ast.Import):
                    assert all(
                        not alias.name.endswith((".safety.retry", ".safety.circuit"))
                        for alias in node.names
                    )
                elif isinstance(node, ast.Name):
                    assert node.id not in {
                        "BoundedReadRetry",
                        "DependencyCircuitBreaker",
                        "ReadRetryStateUnavailableError",
                        "RetryOperationClass",
                    }
                    assert not node.id.startswith("Circuit")
                elif isinstance(node, ast.Attribute):
                    assert node.attr not in {
                        "BoundedReadRetry",
                        "DependencyCircuitBreaker",
                        "ReadRetryStateUnavailableError",
                        "RetryOperationClass",
                    }
                    assert not node.attr.startswith("Circuit")
    circuit_tree = ast.parse(
        (ROOT / "src/aioa_cloudops_agent/safety/circuit.py").read_text(encoding="utf-8")
    )
    names = {
        node.func.attr
        for node in ast.walk(circuit_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert names.isdisjoint(
        {"stop_instances", "start_instances", "terminate_instances", "request", "urlopen"}
    )


@pytest.mark.parametrize(
    "settings",
    [
        {"failure_threshold": 0},
        {"failure_threshold": True},
        {"cooldown_seconds": 0},
        {"cooldown_seconds": float("inf")},
        {"max_half_open_probes": 2},
        {"max_half_open_probes": 1.0},
    ],
)
def test_circuit_limits_are_finite_validated_and_dependency_specific(
    settings: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CircuitBreakerSettings(**settings)  # type: ignore[arg-type]

    assert tuple(CircuitDependency) == (
        CircuitDependency.BEDROCK_MODEL,
        CircuitDependency.EC2_READ,
        CircuitDependency.CLOUDWATCH_READ,
        CircuitDependency.VERIFICATION_READ,
    )
