"""One-attempt model proxy bound to the process-local dependency circuit."""

from __future__ import annotations

from typing import Any

from strands.models import Model
from strands.types.exceptions import ModelThrottledException

from .circuit import CircuitDependency, CircuitPermit, DependencyCircuitBreaker
from .retry import is_known_transient_read_error


class CircuitBoundedModel(Model):
    """Suppress repeated warm-process model failures without replaying one invocation."""

    def __init__(self, delegate: Model, circuit_breaker: DependencyCircuitBreaker) -> None:
        if not isinstance(delegate, Model):
            raise TypeError("delegate must be a Strands Model")
        if not isinstance(circuit_breaker, DependencyCircuitBreaker):
            raise TypeError("circuit_breaker must be DependencyCircuitBreaker")
        self._delegate = delegate
        self._circuit_breaker = circuit_breaker

    @property
    def stateful(self) -> bool:
        return self._delegate.stateful

    def update_config(self, **model_config: Any) -> None:
        self._delegate.update_config(**model_config)

    def get_config(self) -> Any:
        return self._delegate.get_config()

    async def count_tokens(self, *args: Any, **kwargs: Any) -> int:
        return await self._delegate.count_tokens(*args, **kwargs)

    def _record_failure(self, permit: CircuitPermit, error: Exception) -> None:
        if isinstance(error, ModelThrottledException) or is_known_transient_read_error(error):
            self._circuit_breaker.record_transient_failure(permit)
        else:
            self._circuit_breaker.record_permanent_outcome(permit)

    async def stream(self, *args: Any, **kwargs: Any) -> Any:
        permit = self._circuit_breaker.acquire(CircuitDependency.BEDROCK_MODEL)
        recorded = False
        try:
            async for event in self._delegate.stream(*args, **kwargs):
                yield event
        except Exception as error:
            self._record_failure(permit, error)
            recorded = True
            raise
        finally:
            if not recorded:
                self._circuit_breaker.record_success(permit)

    async def structured_output(self, *args: Any, **kwargs: Any) -> Any:
        permit = self._circuit_breaker.acquire(CircuitDependency.BEDROCK_MODEL)
        recorded = False
        try:
            async for event in self._delegate.structured_output(*args, **kwargs):
                yield event
        except Exception as error:
            self._record_failure(permit, error)
            recorded = True
            raise
        finally:
            if not recorded:
                self._circuit_breaker.record_success(permit)
