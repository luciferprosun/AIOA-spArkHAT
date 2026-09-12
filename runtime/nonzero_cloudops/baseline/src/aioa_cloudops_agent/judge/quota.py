"""Independent durable quotas for status and public readiness reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from aioa_cloudops_agent.nz.errors import StorageDependencyError


@dataclass(frozen=True, slots=True)
class StatusRequestQuotaPolicy:
    """Finite request-only cap; it does not reserve model tokens or cost."""

    max_requests_per_day: int = 200

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_requests_per_day, bool)
            or not isinstance(self.max_requests_per_day, int)
            or not 1 <= self.max_requests_per_day <= 1_000
        ):
            raise ValueError("status request quota must be between 1 and 1000")


@dataclass(frozen=True, slots=True)
class StatusRequestQuotaReservation:
    day: date
    requests: int


class _DynamoDbUpdateClient(Protocol):
    def update_item(self, **kwargs: object) -> Mapping[str, Any]: ...


def _conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    details = response.get("Error")
    return isinstance(details, Mapping) and details.get("Code") == (
        "ConditionalCheckFailedException"
    )


class DynamoDbStatusRequestQuotaRepository:
    """Reserve one status request with a dedicated conditional DynamoDB item."""

    def __init__(
        self,
        client: _DynamoDbUpdateClient,
        table_name: str,
        *,
        clock: Callable[[], datetime],
        policy: StatusRequestQuotaPolicy | None = None,
    ) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._client = client
        self._table_name = table_name
        self._clock = clock
        self._policy = policy or StatusRequestQuotaPolicy()

    def reserve(self) -> StatusRequestQuotaReservation | None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise StorageDependencyError("status request quota clock is unavailable")
        day = now.date()
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={
                    "PK": {"S": f"JUDGE_STATUS_QUOTA#{day.isoformat()}"},
                    "SK": {"S": "DAILY_REQUESTS"},
                },
                UpdateExpression=(
                    "SET #requests = if_not_exists(#requests, :zero) + :one, "
                    "#entity = if_not_exists(#entity, :entity)"
                ),
                ConditionExpression=(
                    "attribute_not_exists(#requests) OR #requests < :maximum"
                ),
                ExpressionAttributeNames={
                    "#requests": "requests",
                    "#entity": "entity_type",
                },
                ExpressionAttributeValues={
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":maximum": {"N": str(self._policy.max_requests_per_day)},
                    ":entity": {"S": "JUDGE_STATUS_DAILY_QUOTA"},
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            if _conditional_failure(error):
                return None
            raise StorageDependencyError("status request quota is unavailable") from None
        attributes = response.get("Attributes") if isinstance(response, Mapping) else None
        try:
            assert isinstance(attributes, Mapping)
            requests = int(attributes["requests"]["N"])
        except (AssertionError, KeyError, TypeError, ValueError) as error:
            raise StorageDependencyError("status request quota response is malformed") from error
        return StatusRequestQuotaReservation(day=day, requests=requests)


@dataclass(frozen=True, slots=True)
class ReadinessProbeQuotaPolicy:
    """Hard daily cap on actual public dependency probes, excluding cache hits."""

    max_probes_per_day: int = 1_440

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_probes_per_day, bool)
            or not isinstance(self.max_probes_per_day, int)
            or not 1 <= self.max_probes_per_day <= 2_880
        ):
            raise ValueError("readiness probe quota must be between 1 and 2880")


@dataclass(frozen=True, slots=True)
class ReadinessProbeQuotaReservation:
    day: date
    probes: int


class DynamoDbReadinessProbeQuotaRepository:
    """Atomically cap actual readiness dependency probes without model budget."""

    def __init__(
        self,
        client: _DynamoDbUpdateClient,
        table_name: str,
        *,
        clock: Callable[[], datetime],
        policy: ReadinessProbeQuotaPolicy | None = None,
    ) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._client = client
        self._table_name = table_name
        self._clock = clock
        self._policy = policy or ReadinessProbeQuotaPolicy()

    def reserve(self) -> ReadinessProbeQuotaReservation | None:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise StorageDependencyError("readiness probe quota clock is unavailable")
        day = now.date()
        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key={
                    "PK": {"S": f"JUDGE_READINESS_QUOTA#{day.isoformat()}"},
                    "SK": {"S": "DAILY_PROBES"},
                },
                UpdateExpression=(
                    "SET #probes = if_not_exists(#probes, :zero) + :one, "
                    "#entity = if_not_exists(#entity, :entity)"
                ),
                ConditionExpression=(
                    "attribute_not_exists(#probes) OR #probes < :maximum"
                ),
                ExpressionAttributeNames={
                    "#probes": "probes",
                    "#entity": "entity_type",
                },
                ExpressionAttributeValues={
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":maximum": {"N": str(self._policy.max_probes_per_day)},
                    ":entity": {"S": "JUDGE_READINESS_DAILY_QUOTA"},
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            if _conditional_failure(error):
                return None
            raise StorageDependencyError("readiness probe quota is unavailable") from None
        attributes = response.get("Attributes") if isinstance(response, Mapping) else None
        try:
            assert isinstance(attributes, Mapping)
            probes = int(attributes["probes"]["N"])
        except (AssertionError, KeyError, TypeError, ValueError) as error:
            raise StorageDependencyError("readiness probe quota response is malformed") from error
        return ReadinessProbeQuotaReservation(day=day, probes=probes)
