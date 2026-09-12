import copy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from aioa_cloudops_agent.domain import (
    ApprovalRecord,
    ApprovalStatus,
    AuthorityGate,
    ContractValidationError,
    ExecutionState,
)
from aioa_cloudops_agent.persistence import (
    DynamoDbExecutionRepository,
    ExecutionRecord,
    IdempotencyClaim,
    IdempotencyConflictError,
    OptimisticConcurrencyError,
    PersistenceConflictError,
    ProvenanceEventType,
    ProvenanceRecord,
    compute_evidence_digest,
)

UUID7_A = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
UUID7_B = UUID("01890f6c-3312-7abc-8f4a-6e4f7f0b9b3b")
NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)


class ConditionalCheckFailed(Exception):
    def __init__(self) -> None:
        self.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
        super().__init__("conditional write rejected")


class FakeDynamoDbClient:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.operations: list[str] = []
        self.requests: list[dict[str, Any]] = []

    @staticmethod
    def _key(value: dict[str, Any]) -> tuple[str, str]:
        return value["PK"]["S"], value["SK"]["S"]

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.operations.append("PutItem")
        self.requests.append(copy.deepcopy(kwargs))
        item = kwargs["Item"]
        key = self._key(item)
        condition = kwargs["ConditionExpression"]
        if condition.startswith("attribute_not_exists") and key in self.items:
            raise ConditionalCheckFailed
        if condition == "#status = :expected_status":
            existing = self.items.get(key)
            expected = kwargs["ExpressionAttributeValues"][":expected_status"]
            if existing is None or existing.get("status") != expected:
                raise ConditionalCheckFailed
        self.items[key] = copy.deepcopy(item)
        return {}

    def get_item(self, **kwargs: Any) -> dict[str, Any]:
        self.operations.append("GetItem")
        self.requests.append(copy.deepcopy(kwargs))
        item = self.items.get(self._key(kwargs["Key"]))
        return {} if item is None else {"Item": copy.deepcopy(item)}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.operations.append("UpdateItem")
        self.requests.append(copy.deepcopy(kwargs))
        key = self._key(kwargs["Key"])
        item = self.items[key]
        values = kwargs["ExpressionAttributeValues"]
        if (
            item["version"] != values[":expected_version"]
            or item["execution_state"] != values[":current_state"]
        ):
            raise ConditionalCheckFailed
        item["execution_state"] = copy.deepcopy(values[":next_state"])
        item["updated_at"] = copy.deepcopy(values[":updated_at"])
        item["version"] = {"N": str(int(item["version"]["N"]) + 1)}
        return {"Attributes": copy.deepcopy(item)}


def _record(
    correlation_id: UUID = UUID7_A,
    *,
    idempotency_key: str = "request-001",
) -> ExecutionRecord:
    return ExecutionRecord(
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        execution_state=ExecutionState.INIT,
        authority_gate=AuthorityGate.AUTO,
        created_at=NOW,
        updated_at=NOW,
        version=1,
    )


def test_execution_create_and_consistent_read_round_trip() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    record = _record()

    assert repository.create_execution(record) == record
    assert repository.get_execution(UUID7_A) == record
    assert client.operations == ["PutItem", "GetItem"]
    assert client.requests[0]["ConditionExpression"] == (
        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
    )
    assert client.requests[1]["ConsistentRead"] is True


def test_idempotency_claim_is_atomic_and_duplicate_cannot_create_second_execution() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    first_claim = IdempotencyClaim(UUID7_A, "request-001", NOW)
    duplicate_claim = IdempotencyClaim(UUID7_B, "request-001", NOW)

    repository.claim_idempotency(first_claim)
    repository.create_execution(_record())
    with pytest.raises(IdempotencyConflictError):
        repository.claim_idempotency(duplicate_claim)

    execution_items = [
        item for item in client.items.values() if item["entity_type"]["S"] == "EXECUTION"
    ]
    assert len(execution_items) == 1
    claim_requests = [
        request
        for request in client.requests
        if request.get("Item", {}).get("entity_type") == {"S": "IDEMPOTENCY"}
    ]
    assert all(
        request["ConditionExpression"] == "attribute_not_exists(PK)"
        for request in claim_requests
    )


def test_execution_create_does_not_overwrite_existing_record() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    repository.create_execution(_record())

    with pytest.raises(PersistenceConflictError):
        repository.create_execution(_record())


def test_new_execution_must_start_at_version_one() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    invalid = ExecutionRecord(
        correlation_id=UUID7_A,
        idempotency_key="request-001",
        execution_state=ExecutionState.INIT,
        authority_gate=AuthorityGate.AUTO,
        created_at=NOW,
        updated_at=NOW,
        version=2,
    )

    with pytest.raises(ContractValidationError, match="version must be 1"):
        repository.create_execution(invalid)
    assert client.operations == []


def test_execution_update_uses_optimistic_version_and_rejects_stale_writer() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    repository.create_execution(_record())

    updated = repository.update_execution_state(
        UUID7_A,
        ExecutionState.RUNNING,
        expected_version=1,
        updated_at=NOW + timedelta(seconds=1),
    )

    assert updated.execution_state is ExecutionState.RUNNING
    assert updated.version == 2
    with pytest.raises(OptimisticConcurrencyError) as captured:
        repository.update_execution_state(
            UUID7_A,
            ExecutionState.FAIL,
            expected_version=1,
            updated_at=NOW + timedelta(seconds=2),
        )
    assert captured.value.retryable is True


def test_provenance_is_append_only_and_duplicate_event_is_rejected() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    event = ProvenanceRecord(
        correlation_id=UUID7_A,
        event_id="event-001",
        event_type=ProvenanceEventType.EXECUTION_CREATED,
        sequence=1,
        timestamp=NOW,
        actor="execution-service",
        summary="Execution created",
        evidence_digest=compute_evidence_digest({"state": "INIT"}),
    )

    assert repository.append_provenance(event) == event
    with pytest.raises(PersistenceConflictError):
        repository.append_provenance(event)
    assert not hasattr(repository, "overwrite_provenance")
    assert not hasattr(repository, "delete_provenance")


def test_approval_state_can_be_created_conditionally_resolved_and_read() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")
    pending = ApprovalRecord(
        correlation_id=UUID7_A,
        proposal_id="proposal-001",
        status=ApprovalStatus.PENDING_APPROVAL,
        requested_at=NOW,
    )
    approved = ApprovalRecord(
        correlation_id=UUID7_A,
        proposal_id="proposal-001",
        status=ApprovalStatus.APPROVED,
        requested_at=NOW,
        resolved_at=NOW + timedelta(minutes=1),
    )

    repository.save_approval(pending)
    assert repository.get_approval(UUID7_A, "proposal-001") == pending
    repository.save_approval(approved, expected_status=ApprovalStatus.PENDING_APPROVAL)

    assert repository.get_approval(UUID7_A, "proposal-001") == approved


def test_adapter_exposes_no_scan_or_destructive_table_operation() -> None:
    client = FakeDynamoDbClient()
    repository = DynamoDbExecutionRepository(client, "state-table")

    assert not hasattr(repository, "scan")
    assert not hasattr(repository, "delete_table")
    assert not hasattr(repository, "batch_write_item")
