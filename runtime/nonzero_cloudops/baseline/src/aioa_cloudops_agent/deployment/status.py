"""Bounded multi-request status contract with no mutation replay capability."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from aioa_cloudops_agent.nz import TERMINAL_WORKFLOW_STATES, Run, WorkflowState
from aioa_cloudops_agent.nz.errors import StorageDependencyError


@dataclass(frozen=True, slots=True)
class StatusPollingPolicy:
    """A credible future EC2 transition window split across HTTP requests."""

    interval_seconds: int = 15
    max_observations: int = 20
    max_window_seconds: int = 300

    def __post_init__(self) -> None:
        if self.interval_seconds < 5 or self.interval_seconds > 30:
            raise ValueError("status interval must be between 5 and 30 seconds")
        if self.max_observations < 2 or self.max_observations > 40:
            raise ValueError("status observations must be between 2 and 40")
        if self.interval_seconds * self.max_observations > self.max_window_seconds:
            raise ValueError("status observation plan exceeds its finite window")


class _RunReader(Protocol):
    def get_run(self, run_id: UUID) -> Run | None: ...


class StatusObservationLimiter(Protocol):
    """Atomically cap useful public status observations for one durable run."""

    def reserve(self, run_id: UUID, *, max_observations: int) -> bool: ...


class _DynamoDbUpdateClient(Protocol):
    def update_item(self, **kwargs: object) -> dict[str, Any]: ...


def _is_conditional_failure(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, dict):
        return False
    details = response.get("Error")
    return isinstance(details, dict) and details.get("Code") == "ConditionalCheckFailedException"


class DynamoDbStatusObservationLimiter:
    """Use one conditional item update to enforce the per-run observation cap."""

    def __init__(self, client: _DynamoDbUpdateClient, table_name: str) -> None:
        if not table_name or table_name != table_name.strip():
            raise ValueError("table_name must be explicit")
        self._client = client
        self._table_name = table_name

    def reserve(self, run_id: UUID, *, max_observations: int) -> bool:
        if not isinstance(run_id, UUID) or max_observations < 1:
            raise ValueError("status observation reservation is invalid")
        try:
            self._client.update_item(
                TableName=self._table_name,
                Key={
                    "PK": {"S": f"JUDGE_STATUS#{run_id}"},
                    "SK": {"S": "PUBLIC_OBSERVATIONS"},
                },
                UpdateExpression=(
                    "SET #observations = if_not_exists(#observations, :zero) + :one, "
                    "#entity = if_not_exists(#entity, :entity)"
                ),
                ConditionExpression=(
                    "attribute_not_exists(#observations) OR #observations < :maximum"
                ),
                ExpressionAttributeNames={
                    "#observations": "observations",
                    "#entity": "entity_type",
                },
                ExpressionAttributeValues={
                    ":zero": {"N": "0"},
                    ":one": {"N": "1"},
                    ":maximum": {"N": str(max_observations)},
                    ":entity": {"S": "JUDGE_STATUS_OBSERVATIONS"},
                },
                ReturnValues="NONE",
            )
        except Exception as error:
            if _is_conditional_failure(error):
                return False
            raise StorageDependencyError("status observation cap is unavailable") from None
        return True


class InMemoryStatusObservationLimiter:
    """Concurrency-safe deterministic limiter for local tests only."""

    def __init__(self) -> None:
        self._counts: dict[UUID, int] = {}
        self._lock = Lock()

    def reserve(self, run_id: UUID, *, max_observations: int) -> bool:
        with self._lock:
            current = self._counts.get(run_id, 0)
            if current >= max_observations:
                return False
            self._counts[run_id] = current + 1
            return True


class PublicRunStatus(BaseModel):
    """Redacted status response: no target, provider detail, or exception text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    state: WorkflowState
    terminal: bool
    outcome_class: str
    next_poll_after_seconds: int | None


class ReadOnlyRunStatusService:
    """Read one durable run per request and never invoke the model or executor."""

    def __init__(
        self,
        repository: _RunReader,
        *,
        observation_limiter: StatusObservationLimiter,
        policy: StatusPollingPolicy | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._observation_limiter = observation_limiter
        self._policy = policy or StatusPollingPolicy()
        self._clock = clock or (lambda: datetime.now(UTC))

    def get(self, run_id: UUID) -> PublicRunStatus | None:
        try:
            run = self._repository.get_run(run_id)
        except StorageDependencyError:
            raise RuntimeError("durable status is unavailable") from None
        if run is None:
            return None
        terminal = run.state in TERMINAL_WORKFLOW_STATES
        next_poll_after_seconds: int | None = None
        if run.state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            outcome = "success_with_evidence"
        elif terminal:
            outcome = "closed_non_success"
        elif run.state in {
            WorkflowState.REMEDIATION_PROPOSED,
            WorkflowState.AWAITING_APPROVAL,
        }:
            terminal = True
            outcome = "proposal_ready_no_execution"
        else:
            now = self._clock()
            if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
                raise RuntimeError("durable status is unavailable")
            elapsed = now - run.created_at
            if elapsed < timedelta(0):
                raise RuntimeError("durable status is unavailable")
            finite_window = timedelta(
                seconds=min(
                    self._policy.max_window_seconds,
                    self._policy.interval_seconds * self._policy.max_observations,
                )
            )
            if elapsed >= finite_window:
                terminal = True
                outcome = "status_window_timeout_non_success"
            else:
                try:
                    observation_accepted = self._observation_limiter.reserve(
                        run.run_id,
                        max_observations=self._policy.max_observations,
                    )
                except StorageDependencyError:
                    raise RuntimeError("durable status is unavailable") from None
                if not observation_accepted:
                    terminal = True
                    outcome = "status_observation_cap_non_success"
                elif run.state in {
                    WorkflowState.EXECUTING,
                    WorkflowState.VERIFYING,
                    WorkflowState.RECOVERY_REQUIRED,
                }:
                    outcome = "read_only_reconciliation_pending"
                    next_poll_after_seconds = self._policy.interval_seconds
                else:
                    outcome = "in_progress"
                    next_poll_after_seconds = self._policy.interval_seconds
        return PublicRunStatus(
            run_id=run.run_id,
            state=run.state,
            terminal=terminal,
            outcome_class=outcome,
            next_poll_after_seconds=next_poll_after_seconds,
        )
