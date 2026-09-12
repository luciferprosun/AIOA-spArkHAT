import asyncio
from typing import Any

import pytest
from strands.models import Model
from strands.types.exceptions import ModelThrottledException

from aioa_cloudops_agent.safety import (
    CircuitBoundedModel,
    CircuitDependency,
    CircuitOpenError,
    CircuitState,
    DependencyCircuitBreaker,
)


class ScriptedModel(Model):
    def __init__(self, outcomes: list[str]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.config: dict[str, object] = {}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if outcome == "throttled":
            raise ModelThrottledException("provider detail must stay internal")
        yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        yield {"output": "ok"}


async def _consume_stream(model: Model) -> list[object]:
    return [event async for event in model.stream([])]


def test_model_circuit_suppresses_third_warm_call_without_hidden_retry() -> None:
    delegate = ScriptedModel(["throttled", "throttled", "success"])
    breaker = DependencyCircuitBreaker()
    model = CircuitBoundedModel(delegate, breaker)

    for _ in range(2):
        with pytest.raises(ModelThrottledException):
            asyncio.run(_consume_stream(model))

    assert delegate.calls == 2
    assert breaker.snapshot(CircuitDependency.BEDROCK_MODEL).state is CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        asyncio.run(_consume_stream(model))
    assert delegate.calls == 2


def test_model_circuit_delegates_configuration_and_records_success() -> None:
    delegate = ScriptedModel(["success"])
    breaker = DependencyCircuitBreaker()
    model = CircuitBoundedModel(delegate, breaker)
    model.update_config(max_tokens=1024)

    events = asyncio.run(_consume_stream(model))

    assert events == [{"messageStop": {"stopReason": "end_turn"}}]
    assert model.get_config() == {"max_tokens": 1024}
    assert breaker.snapshot(CircuitDependency.BEDROCK_MODEL).state is CircuitState.CLOSED
