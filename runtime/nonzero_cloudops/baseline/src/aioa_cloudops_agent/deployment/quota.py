"""Atomic server-owned daily judge request, token, and cost reservations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from threading import Lock
from typing import Any, Protocol

from aioa_cloudops_agent.nz.errors import StorageDependencyError


@dataclass(frozen=True, slots=True)
class JudgeQuotaPolicy:
    """A conservative hard reservation cap applied before any Bedrock call."""

    max_requests_per_day: int = 20
    max_reserved_tokens_per_day: int = 163_840
    max_reserved_cost_microusd_per_day: int = 1_000_000
    tokens_per_request: int = 8_192
    cost_microusd_per_request: int = 50_000

    def __post_init__(self) -> None:
        values = (
            self.max_requests_per_day,
            self.max_reserved_tokens_per_day,
            self.max_reserved_cost_microusd_per_day,
            self.tokens_per_request,
            self.cost_microusd_per_request,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("judge quota values must be positive integers")
        if self.tokens_per_request > self.max_reserved_tokens_per_day:
            raise ValueError("one request cannot exceed the daily token cap")
        if self.cost_microusd_per_request > self.max_reserved_cost_microusd_per_day:
            raise ValueError("one request cannot exceed the daily cost cap")


@dataclass(frozen=True, slots=True)
class JudgeQuotaReservation:
    """Sanitized durable totals after one accepted reservation."""

    day: date
    requests: int
    reserved_tokens: int
    reserved_cost_microusd: int


class DynamoDbQuotaClient(Protocol):
    def update_item(self, **kwargs: object) -> Mapping[str, Any]: ...


def _conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    details = response.get("Error")
    return isinstance(details, Mapping) and details.get("Code") == "ConditionalCheckFailedException"


class DynamoDbJudgeQuotaRepository:
    """Reserve all three daily caps in one conditional DynamoDB update."""

    def __init__(
        self,
        client: DynamoDbQuotaClient,
        table_name: str,
        *,
        policy: JudgeQuotaPolicy | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        self._client = client
        self._table_name = table_name
        self._policy = policy or JudgeQuotaPolicy()
        self._clock = clock

    def reserve(self) -> JudgeQuotaReservation | None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise StorageDependencyError("judge quota clock is unavailable")
        day = now.date()
        policy = self._policy
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={"PK": {"S": f"JUDGE_QUOTA#{day.isoformat()}"}, "SK": {"S": "DAILY"}},
                UpdateExpression=(
                    "SET #requests = if_not_exists(#requests, :zero) + :one, "
                    "#tokens = if_not_exists(#tokens, :zero) + :tokens, "
                    "#cost = if_not_exists(#cost, :zero) + :cost, "
                    "#entity = if_not_exists(#entity, :entity)"
                ),
                ConditionExpression=(
                    "(attribute_not_exists(#requests) OR #requests < :max_requests) AND "
                    "(attribute_not_exists(#tokens) OR #tokens <= :token_ceiling) AND "
                    "(attribute_not_exists(#cost) OR #cost <= :cost_ceiling)"
                ),
                ExpressionAttributeNames={
                    "#requests": "requests",
                    "#tokens": "reserved_tokens",
                    "#cost": "reserved_cost_microusd",
                    "#entity": "entity_type",
                },
                ExpressionAttributeValues={
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":tokens": {"N": str(policy.tokens_per_request)},
                    ":cost": {"N": str(policy.cost_microusd_per_request)},
                    ":max_requests": {"N": str(policy.max_requests_per_day)},
                    ":token_ceiling": {
                        "N": str(policy.max_reserved_tokens_per_day - policy.tokens_per_request)
                    },
                    ":cost_ceiling": {
                        "N": str(
                            policy.max_reserved_cost_microusd_per_day
                            - policy.cost_microusd_per_request
                        )
                    },
                    ":entity": {"S": "JUDGE_DAILY_QUOTA"},
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            if _conditional_failure(error):
                return None
            raise StorageDependencyError("judge quota reservation is unavailable") from error
        attributes = response.get("Attributes") if isinstance(response, Mapping) else None
        try:
            assert isinstance(attributes, Mapping)
            return JudgeQuotaReservation(
                day=day,
                requests=int(attributes["requests"]["N"]),
                reserved_tokens=int(attributes["reserved_tokens"]["N"]),
                reserved_cost_microusd=int(attributes["reserved_cost_microusd"]["N"]),
            )
        except (AssertionError, KeyError, TypeError, ValueError) as error:
            raise StorageDependencyError("judge quota response is malformed") from error


class InMemoryJudgeQuotaRepository:
    """Deterministic concurrency-safe test implementation."""

    def __init__(
        self,
        *,
        policy: JudgeQuotaPolicy | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._policy = policy or JudgeQuotaPolicy()
        self._clock = clock
        self._totals: dict[date, JudgeQuotaReservation] = {}
        self._lock = Lock()

    def reserve(self) -> JudgeQuotaReservation | None:
        day = self._clock().date()
        policy = self._policy
        with self._lock:
            current = self._totals.get(day, JudgeQuotaReservation(day, 0, 0, 0))
            candidate = JudgeQuotaReservation(
                day=day,
                requests=current.requests + 1,
                reserved_tokens=current.reserved_tokens + policy.tokens_per_request,
                reserved_cost_microusd=(
                    current.reserved_cost_microusd + policy.cost_microusd_per_request
                ),
            )
            if (
                candidate.requests > policy.max_requests_per_day
                or candidate.reserved_tokens > policy.max_reserved_tokens_per_day
                or candidate.reserved_cost_microusd
                > policy.max_reserved_cost_microusd_per_day
            ):
                return None
            self._totals[day] = candidate
            return candidate
