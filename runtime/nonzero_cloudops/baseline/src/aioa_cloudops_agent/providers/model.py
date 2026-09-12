"""Small model-plan protocol and a deterministic Strands-compatible local provider."""

import json
from collections.abc import AsyncIterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from strands.models import Model

from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import PlanDisposition, ResourceEvidence


class ModelProviderError(RuntimeError):
    """Explicit provider failure safe to translate at the orchestration boundary."""


class ModelProviderTimeoutError(ModelProviderError):
    """Deterministic timeout used to verify bounded provider handling."""


class ModelProviderRetryableError(ModelProviderError):
    """Typed transient provider failure that may be retried by an owning boundary."""


class ModelProviderNonRetryableError(ModelProviderError):
    """Typed permanent provider failure which must not be retried silently."""


class ModelProviderUnavailableError(ModelProviderRetryableError):
    """Selected provider could not be loaded or initialized."""


class ModelProvider(Protocol):
    """Small provider-neutral interface required by local remediation planning."""

    def create_plan(self, evidence: ResourceEvidence) -> str:
        """Return untrusted JSON data; callers must validate it locally."""


class MockModelFailure(StrEnum):
    """Deterministic scripted outcomes required by the Local-First test matrix."""

    NONE = "NONE"
    MALFORMED = "MALFORMED"
    TRUNCATED = "TRUNCATED"
    INVALID_STRUCTURED = "INVALID_STRUCTURED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    TIMEOUT = "TIMEOUT"
    CONNECTION_FAILURE = "CONNECTION_FAILURE"
    RATE_LIMIT = "RATE_LIMIT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    POLICY_INVALID = "POLICY_INVALID"
    EMPTY = "EMPTY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENIED_ACTION = "DENIED_ACTION"
    RETRYABLE_ERROR = "RETRYABLE_ERROR"
    NON_RETRYABLE_ERROR = "NON_RETRYABLE_ERROR"


@dataclass(frozen=True, slots=True)
class MockToolCall:
    """One deterministic native Strands tool request."""

    name: str
    arguments: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("mock tool name must not be empty")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("mock tool arguments must be a mapping")


class MockModelProvider(Model):
    """One local implementation behind both plan and canonical Strands interfaces."""

    def __init__(
        self,
        *,
        failure: MockModelFailure = MockModelFailure.NONE,
        tool_plan: tuple[MockToolCall, ...] = (),
        final_text: str = "Local model plan completed without execution authority.",
    ) -> None:
        if not isinstance(failure, MockModelFailure):
            raise TypeError("failure must be MockModelFailure")
        if not isinstance(final_text, str) or not final_text.strip():
            raise ValueError("final_text must not be empty")
        self.failure = failure
        self.tool_plan = tool_plan
        self.final_text = final_text
        self.calls = 0
        self.plan_calls = 0
        self.network_calls = 0
        self.config: dict[str, object] = {"context_window_limit": 32_000}

    def update_config(self, **model_config: Any) -> None:
        self.config.update(model_config)

    def get_config(self) -> dict[str, object]:
        return dict(self.config)

    def create_plan(self, evidence: ResourceEvidence) -> str:
        if not isinstance(evidence, ResourceEvidence):
            raise TypeError("evidence must be ResourceEvidence")
        self.plan_calls += 1
        self._raise_scripted_failure()
        if self.failure is MockModelFailure.MALFORMED:
            return "{not-json"
        if self.failure is MockModelFailure.TRUNCATED:
            return '{"disposition":"PROPOSAL"'
        if self.failure is MockModelFailure.INVALID_STRUCTURED:
            return json.dumps({"unexpected": "provider-shape"})
        if self.failure is MockModelFailure.EMPTY:
            return ""
        if self.failure is MockModelFailure.POLICY_INVALID:
            return json.dumps(
                {
                    "disposition": PlanDisposition.PROPOSAL.value,
                    "operation_type": "RELEASE_ELASTIC_IP",
                    "target_resource_type": evidence.resource.resource_type.value,
                    "target_resource_id": evidence.resource.resource_id,
                    "normalized_parameters": {"target": evidence.resource.resource_id},
                    "claimed_authority": AuthorityGate.AUTO.value,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        if self.failure is MockModelFailure.DENIED_ACTION:
            return json.dumps(
                {
                    "disposition": PlanDisposition.PROPOSAL.value,
                    "operation_type": "TERMINATE_INSTANCE",
                    "target_resource_type": evidence.resource.resource_type.value,
                    "target_resource_id": evidence.resource.resource_id,
                    "normalized_parameters": {"target": evidence.resource.resource_id},
                    "claimed_authority": AuthorityGate.NEVER_AUTONOMOUS.value,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        from aioa_cloudops_agent.cloudops.plan_remediation import canonical_model_candidate

        candidate = canonical_model_candidate(evidence)
        return json.dumps(
            candidate.model_dump(mode="json", exclude_none=True),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    async def structured_output(self, *args: Any, **kwargs: Any) -> AsyncIterable[dict[str, Any]]:
        if False:
            yield {}

    async def stream(
        self,
        messages: object,
        tool_specs: list[dict[str, object]] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, object]]:
        del messages, tool_specs, system_prompt, kwargs
        self.calls += 1
        self._raise_scripted_failure()
        yield {"messageStart": {"role": "assistant"}}
        if self.failure is MockModelFailure.MALFORMED:
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {"toolUse": {"toolUseId": "malformed-1", "name": "invalid"}},
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": "{not-json"}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        elif self.failure in {
            MockModelFailure.POLICY_INVALID,
            MockModelFailure.DENIED_ACTION,
        }:
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": "policy-invalid-1",
                            "name": "terminate_instances",
                        }
                    },
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"toolUse": {"input": "{}"}},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        elif self.failure is MockModelFailure.EMPTY:
            yield {"messageStop": {"stopReason": "end_turn"}}
        elif self.calls <= len(self.tool_plan):
            tool_call = self.tool_plan[self.calls - 1]
            yield {
                "contentBlockStart": {
                    "contentBlockIndex": 0,
                    "start": {
                        "toolUse": {
                            "toolUseId": f"mock-tool-{self.calls}",
                            "name": tool_call.name,
                        }
                    },
                }
            }
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {
                        "toolUse": {
                            "input": json.dumps(
                                dict(tool_call.arguments),
                                separators=(",", ":"),
                                sort_keys=True,
                            )
                        }
                    },
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {}}}
            yield {
                "contentBlockDelta": {
                    "contentBlockIndex": 0,
                    "delta": {"text": self.final_text},
                }
            }
            yield {"contentBlockStop": {"contentBlockIndex": 0}}
            yield {"messageStop": {"stopReason": "end_turn"}}
        yield {
            "metadata": {
                "usage": {"inputTokens": 5, "outputTokens": 5, "totalTokens": 10},
                "metrics": {"latencyMs": 1},
            }
        }

    def _raise_scripted_failure(self) -> None:
        if self.failure is MockModelFailure.PROVIDER_ERROR:
            raise ModelProviderError("mock model provider failure was injected")
        if self.failure is MockModelFailure.TIMEOUT:
            raise ModelProviderTimeoutError("mock model timeout was injected")
        if self.failure is MockModelFailure.RETRYABLE_ERROR:
            raise ModelProviderRetryableError("mock retryable model failure was injected")
        if self.failure is MockModelFailure.CONNECTION_FAILURE:
            raise ModelProviderRetryableError("mock model connection failure was injected")
        if self.failure is MockModelFailure.RATE_LIMIT:
            raise ModelProviderRetryableError("mock model rate limit was injected")
        if self.failure is MockModelFailure.NON_RETRYABLE_ERROR:
            raise ModelProviderNonRetryableError(
                "mock non-retryable model failure was injected"
            )
        if self.failure is MockModelFailure.MODEL_UNAVAILABLE:
            raise ModelProviderNonRetryableError("mock selected model is unavailable")
        if self.failure is MockModelFailure.CONFIGURATION_ERROR:
            raise ModelProviderNonRetryableError("mock model configuration is invalid")
