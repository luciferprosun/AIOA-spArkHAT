"""Low-level DynamoDB adapter with explicit conditional-write semantics."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from aioa_cloudops_agent.domain.approval import ApprovalRecord, ApprovalStatus
from aioa_cloudops_agent.domain.enums import AuthorityGate, ExecutionState
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.domain.transitions import validate_state_transition

from .errors import (
    IdempotencyConflictError,
    OptimisticConcurrencyError,
    PersistenceConflictError,
    PersistenceOperationError,
)
from .keys import approval_key, execution_key, idempotency_key, provenance_key
from .models import (
    ExecutionRecord,
    IdempotencyClaim,
    ProvenanceRecord,
    validate_utc_timestamp,
)

DynamoAttribute = dict[str, Any]
DynamoItem = dict[str, DynamoAttribute]


class DynamoDbClient(Protocol):
    """Small subset of the low-level DynamoDB client used by this adapter."""

    def put_item(self, **kwargs: Any) -> Mapping[str, Any]:
        """Create or conditionally replace one item."""

    def get_item(self, **kwargs: Any) -> Mapping[str, Any]:
        """Read one item by its composite key."""

    def update_item(self, **kwargs: Any) -> Mapping[str, Any]:
        """Conditionally update one versioned item."""


def _string(value: str) -> DynamoAttribute:
    return {"S": value}


def _number(value: int) -> DynamoAttribute:
    return {"N": str(value)}


def _timestamp(value: datetime) -> DynamoAttribute:
    return _string(value.isoformat())


def _conditional_check_failed(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    details = response.get("Error")
    return isinstance(details, Mapping) and details.get("Code") == "ConditionalCheckFailedException"


def _required_string(item: Mapping[str, DynamoAttribute], name: str) -> str:
    try:
        value = item[name]["S"]
    except (KeyError, TypeError) as error:
        raise PersistenceOperationError("Stored item does not satisfy the persistence contract") from error
    if not isinstance(value, str):
        raise PersistenceOperationError("Stored item does not satisfy the persistence contract")
    return value


def _required_integer(item: Mapping[str, DynamoAttribute], name: str) -> int:
    try:
        return int(item[name]["N"])
    except (KeyError, TypeError, ValueError) as error:
        raise PersistenceOperationError("Stored item does not satisfy the persistence contract") from error


def _optional_string(item: Mapping[str, DynamoAttribute], name: str) -> str | None:
    if name not in item:
        return None
    return _required_string(item, name)


class DynamoDbExecutionRepository:
    """Non-Zero state adapter that never scans, deletes, or silently overwrites."""

    def __init__(self, client: DynamoDbClient, table_name: str) -> None:
        if not isinstance(table_name, str) or not table_name.strip():
            raise ContractValidationError("table_name must be a non-empty string")
        if table_name != table_name.strip():
            raise ContractValidationError("table_name must not contain surrounding whitespace")
        self._client = client
        self._table_name = table_name

    def create_execution(self, record: ExecutionRecord) -> ExecutionRecord:
        if not isinstance(record, ExecutionRecord):
            raise ContractValidationError("record must be an ExecutionRecord")
        if record.version != 1:
            raise ContractValidationError("new execution version must be 1")
        key = execution_key(record.correlation_id)
        item: DynamoItem = {
            **key.as_item(),
            "entity_type": _string("EXECUTION"),
            "correlation_id": _string(str(record.correlation_id)),
            "idempotency_key": _string(record.idempotency_key),
            "execution_state": _string(record.execution_state.value),
            "authority_gate": _string(record.authority_gate.value),
            "created_at": _timestamp(record.created_at),
            "updated_at": _timestamp(record.updated_at),
            "version": _number(record.version),
        }
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise PersistenceConflictError("Execution metadata already exists") from error
            raise PersistenceOperationError("Unable to create execution metadata") from error
        return record

    def get_execution(self, correlation_id: UUID) -> ExecutionRecord | None:
        key = execution_key(validate_correlation_id(correlation_id))
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key=key.as_item(),
                ConsistentRead=True,
            )
        except Exception as error:
            raise PersistenceOperationError("Unable to read execution metadata") from error
        if not isinstance(response, Mapping):
            raise PersistenceOperationError("DynamoDB returned an invalid execution response")
        item = response.get("Item")
        if item is None:
            return None
        if not isinstance(item, Mapping):
            raise PersistenceOperationError("Stored execution metadata is invalid")
        return self._execution_from_item(item)

    def claim_idempotency(self, claim: IdempotencyClaim) -> IdempotencyClaim:
        if not isinstance(claim, IdempotencyClaim):
            raise ContractValidationError("claim must be an IdempotencyClaim")
        key = idempotency_key(claim.idempotency_key)
        item: DynamoItem = {
            **key.as_item(),
            "entity_type": _string("IDEMPOTENCY"),
            "correlation_id": _string(str(claim.correlation_id)),
            "idempotency_key": _string(claim.idempotency_key),
            "claimed_at": _timestamp(claim.claimed_at),
        }
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise IdempotencyConflictError(claim.idempotency_key) from error
            raise PersistenceOperationError("Unable to claim idempotency key") from error
        return claim

    def update_execution_state(
        self,
        correlation_id: UUID,
        next_state: ExecutionState,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> ExecutionRecord:
        valid_id = validate_correlation_id(correlation_id)
        if not isinstance(next_state, ExecutionState):
            raise ContractValidationError("next_state must be an ExecutionState")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version <= 0
        ):
            raise ContractValidationError("expected_version must be a positive integer")
        validate_utc_timestamp("updated_at", updated_at)

        current = self.get_execution(valid_id)
        if current is None:
            raise PersistenceOperationError("Execution metadata was not found")
        if current.version != expected_version:
            raise OptimisticConcurrencyError(expected_version)
        if updated_at < current.updated_at:
            raise ContractValidationError("updated_at must not precede the stored updated_at")
        validate_state_transition(current.execution_state, next_state)

        try:
            response = self._client.update_item(
                TableName=self._table_name,
                Key=execution_key(valid_id).as_item(),
                UpdateExpression=(
                    "SET #execution_state = :next_state, #updated_at = :updated_at, "
                    "#version = #version + :one"
                ),
                ConditionExpression=(
                    "#version = :expected_version AND #execution_state = :current_state"
                ),
                ExpressionAttributeNames={
                    "#execution_state": "execution_state",
                    "#updated_at": "updated_at",
                    "#version": "version",
                },
                ExpressionAttributeValues={
                    ":next_state": _string(next_state.value),
                    ":updated_at": _timestamp(updated_at),
                    ":one": _number(1),
                    ":expected_version": _number(expected_version),
                    ":current_state": _string(current.execution_state.value),
                },
                ReturnValues="ALL_NEW",
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise OptimisticConcurrencyError(expected_version) from error
            raise PersistenceOperationError("Unable to update execution metadata") from error

        if not isinstance(response, Mapping):
            raise PersistenceOperationError("DynamoDB returned an invalid update response")
        attributes = response.get("Attributes")
        if not isinstance(attributes, Mapping):
            raise PersistenceOperationError("DynamoDB did not return updated execution metadata")
        return self._execution_from_item(attributes)

    def append_provenance(self, record: ProvenanceRecord) -> ProvenanceRecord:
        if not isinstance(record, ProvenanceRecord):
            raise ContractValidationError("record must be a ProvenanceRecord")
        key = provenance_key(record.correlation_id, record.sequence, record.event_id)
        item: DynamoItem = {
            **key.as_item(),
            "entity_type": _string("PROVENANCE"),
            "correlation_id": _string(str(record.correlation_id)),
            "event_id": _string(record.event_id),
            "event_type": _string(record.event_type.value),
            "sequence": _number(record.sequence),
            "timestamp": _timestamp(record.timestamp),
            "actor": _string(record.actor),
            "summary": _string(record.summary),
            "attributes": {
                "M": {key: _string(value) for key, value in record.attributes.items()}
            },
        }
        if record.evidence_digest is not None:
            item["evidence_digest"] = _string(record.evidence_digest)
        try:
            self._client.put_item(
                TableName=self._table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise PersistenceConflictError("Provenance event already exists") from error
            raise PersistenceOperationError("Unable to append provenance event") from error
        return record

    def save_approval(
        self,
        record: ApprovalRecord,
        *,
        expected_status: ApprovalStatus | None = None,
    ) -> ApprovalRecord:
        if not isinstance(record, ApprovalRecord):
            raise ContractValidationError("record must be an ApprovalRecord")
        if expected_status is not None and not isinstance(expected_status, ApprovalStatus):
            raise ContractValidationError("expected_status must be an ApprovalStatus")
        key = approval_key(record.correlation_id, record.proposal_id)
        item: DynamoItem = {
            **key.as_item(),
            "entity_type": _string("APPROVAL"),
            "correlation_id": _string(str(record.correlation_id)),
            "proposal_id": _string(record.proposal_id),
            "status": _string(record.status.value),
            "requested_at": _timestamp(record.requested_at),
        }
        if record.resolved_at is not None:
            item["resolved_at"] = _timestamp(record.resolved_at)

        expression_values: dict[str, DynamoAttribute] | None = None
        if expected_status is None:
            condition = "attribute_not_exists(PK) AND attribute_not_exists(SK)"
        else:
            condition = "#status = :expected_status"
            expression_values = {":expected_status": _string(expected_status.value)}

        request: dict[str, Any] = {
            "TableName": self._table_name,
            "Item": item,
            "ConditionExpression": condition,
        }
        if expression_values is not None:
            request["ExpressionAttributeNames"] = {"#status": "status"}
            request["ExpressionAttributeValues"] = expression_values
        try:
            self._client.put_item(**request)
        except Exception as error:
            if _conditional_check_failed(error):
                raise PersistenceConflictError("Approval state no longer matches expectation") from error
            raise PersistenceOperationError("Unable to save approval state") from error
        return record

    def get_approval(self, correlation_id: UUID, proposal_id: str) -> ApprovalRecord | None:
        key = approval_key(correlation_id, proposal_id)
        try:
            response = self._client.get_item(
                TableName=self._table_name,
                Key=key.as_item(),
                ConsistentRead=True,
            )
        except Exception as error:
            raise PersistenceOperationError("Unable to read approval state") from error
        if not isinstance(response, Mapping):
            raise PersistenceOperationError("DynamoDB returned an invalid approval response")
        item = response.get("Item")
        if item is None:
            return None
        if not isinstance(item, Mapping):
            raise PersistenceOperationError("Stored approval state is invalid")
        try:
            resolved_at_value = _optional_string(item, "resolved_at")
            return ApprovalRecord(
                correlation_id=UUID(_required_string(item, "correlation_id")),
                proposal_id=_required_string(item, "proposal_id"),
                status=ApprovalStatus(_required_string(item, "status")),
                requested_at=datetime.fromisoformat(_required_string(item, "requested_at")),
                resolved_at=(
                    datetime.fromisoformat(resolved_at_value)
                    if resolved_at_value is not None
                    else None
                ),
            )
        except (ContractValidationError, ValueError) as error:
            raise PersistenceOperationError("Stored approval state is invalid") from error

    @staticmethod
    def _execution_from_item(item: Mapping[str, DynamoAttribute]) -> ExecutionRecord:
        try:
            return ExecutionRecord(
                correlation_id=UUID(_required_string(item, "correlation_id")),
                idempotency_key=_required_string(item, "idempotency_key"),
                execution_state=ExecutionState(_required_string(item, "execution_state")),
                authority_gate=AuthorityGate(_required_string(item, "authority_gate")),
                created_at=datetime.fromisoformat(_required_string(item, "created_at")),
                updated_at=datetime.fromisoformat(_required_string(item, "updated_at")),
                version=_required_integer(item, "version"),
            )
        except (ContractValidationError, ValueError) as error:
            raise PersistenceOperationError("Stored execution metadata is invalid") from error
