"""DynamoDB adapter for the canonical write-before-execute NZ records."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from aioa_cloudops_agent.config import DynamoDbSettings
from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionResult,
    Approval,
    ApprovalDecision,
    AuditEvent,
    BudgetCounters,
    Checkpoint,
    ExecutionAcknowledgement,
    IdempotencyRecord,
    IdempotencyStatus,
    ObservedInstanceState,
    ProposalState,
    Run,
    VerificationEvidence,
    VerificationProofOrigin,
    WorkflowState,
    transition_run,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError

from .durable_keys import (
    approval_decision_key,
    audit_event_key,
    checkpoint_key,
    proposal_key,
    run_key,
    semantic_idempotency_key,
    verification_evidence_key,
)
from .durable_logic import (
    completed_idempotency_status,
    transitioned_proposal,
    validate_approval_binding,
)
from .dynamodb import DynamoDbClient
from .keys import DynamoKey
from .semantic_idempotency import derive_action_fingerprint, derive_idempotency_key
from .serialization import DynamoAttribute, deserialize_record, serialize_record

DynamoItem = dict[str, DynamoAttribute]


def _string(value: str) -> DynamoAttribute:
    return {"S": value}


def _number(value: int) -> DynamoAttribute:
    return {"N": str(value)}


def _conditional_check_failed(error: Exception) -> bool:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    details = response.get("Error")
    return isinstance(details, Mapping) and details.get("Code") == (
        "ConditionalCheckFailedException"
    )


class DynamoDbDurableTruthRepository:
    """Fail-closed item repository with no scan, delete, or AWS action API."""

    def __init__(self, client: DynamoDbClient, settings: DynamoDbSettings) -> None:
        if not isinstance(settings, DynamoDbSettings):
            raise TypeError("settings must be DynamoDbSettings")
        self._client = client
        self._settings = settings

    @property
    def table_name(self) -> str:
        return self._settings.table_name

    @staticmethod
    def _item(
        key: DynamoKey,
        entity_type: str,
        record: BaseModel,
        **indexed: DynamoAttribute,
    ) -> DynamoItem:
        return {
            **key.as_item(),
            "entity_type": _string(entity_type),
            "record": serialize_record(record),
            **indexed,
        }

    def _put_create(
        self,
        key: DynamoKey,
        entity_type: str,
        record: BaseModel,
        **indexed: DynamoAttribute,
    ) -> None:
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item=self._item(key, entity_type, record, **indexed),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise StorageConflictError(f"{entity_type} record already exists") from error
            raise StorageDependencyError(f"unable to create {entity_type} record") from error

    def _read[RecordType: BaseModel](
        self,
        key: DynamoKey,
        entity_type: str,
        model_type: type[RecordType],
    ) -> RecordType | None:
        try:
            response = self._client.get_item(
                TableName=self.table_name,
                Key=key.as_item(),
                ConsistentRead=self._settings.consistent_reads,
            )
        except Exception as error:
            raise StorageDependencyError(f"unable to read {entity_type} record") from error
        if not isinstance(response, Mapping):
            raise StorageDependencyError("DynamoDB returned a malformed response")
        item = response.get("Item")
        if item is None:
            return None
        if not isinstance(item, Mapping):
            raise StorageDependencyError("DynamoDB returned a malformed item")
        stored_type = item.get("entity_type")
        if stored_type != _string(entity_type) or "record" not in item:
            raise StorageDependencyError("stored item has an unexpected entity contract")
        return deserialize_record(item["record"], model_type)

    def _update(
        self,
        key: DynamoKey,
        entity_type: str,
        record: BaseModel,
        *,
        condition: str,
        names: dict[str, str],
        values: dict[str, DynamoAttribute],
        indexed_updates: dict[str, DynamoAttribute],
    ) -> None:
        update_parts = ["#record = :record"]
        update_names = {"#record": "record", **names}
        update_values = {":record": serialize_record(record), **values}
        for index, (attribute_name, attribute_value) in enumerate(indexed_updates.items()):
            name_token = f"#update_{index}"
            value_token = f":update_{index}"
            update_parts.append(f"{name_token} = {value_token}")
            update_names[name_token] = attribute_name
            update_values[value_token] = attribute_value
        try:
            self._client.update_item(
                TableName=self.table_name,
                Key=key.as_item(),
                UpdateExpression=f"SET {', '.join(update_parts)}",
                ConditionExpression=condition,
                ExpressionAttributeNames=update_names,
                ExpressionAttributeValues=update_values,
            )
        except Exception as error:
            if _conditional_check_failed(error):
                raise StorageConflictError(f"{entity_type} conditional write failed") from error
            raise StorageDependencyError(f"unable to update {entity_type} record") from error

    def create_run(self, run: Run) -> Run:
        if run.version != 1 or run.state is not WorkflowState.RECEIVED:
            raise StorageConflictError("new durable run must start at RECEIVED version 1")
        self._put_create(
            run_key(run.run_id),
            "RUN",
            run,
            state=_string(run.state.value),
            version=_number(run.version),
        )
        return run

    def get_run(self, run_id: UUID) -> Run | None:
        return self._read(run_key(run_id), "RUN", Run)

    def transition_run(
        self,
        run_id: UUID,
        next_state: WorkflowState,
        *,
        expected_state: WorkflowState,
        expected_version: int,
        updated_at: datetime,
        approval_proposal_id: UUID | None = None,
        verification_proposal_id: UUID | None = None,
    ) -> Run:
        current = self.get_run(run_id)
        if current is None:
            raise StorageConflictError("durable run does not exist")
        if current.state is not expected_state or current.version != expected_version:
            raise StorageConflictError("durable run state or version no longer matches")
        if next_state in {WorkflowState.APPROVED, WorkflowState.DENIED_BY_HUMAN}:
            if approval_proposal_id is None:
                raise StorageConflictError(
                    "decision transition requires a durable proposal decision"
                )
            proposal = self.get_proposal(approval_proposal_id)
            approval = self.get_approval(approval_proposal_id)
            expected_decision = (
                ApprovalDecision.APPROVED
                if next_state is WorkflowState.APPROVED
                else ApprovalDecision.DENIED
            )
            if (
                proposal is None
                or proposal.run_id != run_id
                or proposal.state is not ProposalState.AWAITING_APPROVAL
                or approval is None
                or approval.decision is not expected_decision
            ):
                raise StorageConflictError(
                    "decision transition requires matching durable human decision"
                )
        if next_state is WorkflowState.SUCCESS_WITH_EVIDENCE:
            if verification_proposal_id is None:
                raise StorageConflictError("SUCCESS_WITH_EVIDENCE requires durable verification")
            proposal = self.get_proposal(verification_proposal_id)
            evidence = self.get_verification_evidence(run_id, verification_proposal_id)
            idempotency = (
                self.get_idempotency(derive_idempotency_key(proposal))
                if proposal is not None
                else None
            )
            if (
                proposal is None
                or evidence is None
                or evidence.run_id != run_id
                or evidence.observed_state is not ObservedInstanceState.STOPPED
                or idempotency is None
                or idempotency.status is not IdempotencyStatus.COMPLETED
                or idempotency.action_result is None
                or idempotency.action_result.evidence_hash != evidence.evidence_hash
            ):
                raise StorageConflictError("SUCCESS_WITH_EVIDENCE proof is incomplete")
        updated = transition_run(current, next_state, updated_at=updated_at)
        self._update(
            run_key(run_id),
            "RUN",
            updated,
            condition="#state = :expected_state AND #version = :expected_version",
            names={"#state": "state", "#version": "version"},
            values={
                ":expected_state": _string(expected_state.value),
                ":expected_version": _number(expected_version),
            },
            indexed_updates={
                "state": _string(updated.state.value),
                "version": _number(updated.version),
            },
        )
        return updated

    def create_proposal(self, proposal: ActionProposal) -> ActionProposal:
        if proposal.state is not ProposalState.PROPOSED:
            raise StorageConflictError("new durable proposal must start at PROPOSED")
        self._put_create(
            proposal_key(proposal.proposal_id),
            "ACTION_PROPOSAL",
            proposal,
            state=_string(proposal.state.value),
        )
        return proposal

    def update_run_budget(
        self,
        run_id: UUID,
        budget: BudgetCounters,
        *,
        expected_version: int,
        updated_at: datetime,
    ) -> Run:
        if not isinstance(budget, BudgetCounters):
            raise TypeError("budget must be BudgetCounters")
        if (
            isinstance(expected_version, bool)
            or not isinstance(expected_version, int)
            or expected_version <= 0
        ):
            raise TypeError("expected_version must be a positive integer")
        if not isinstance(updated_at, datetime):
            raise TypeError("updated_at must be datetime")
        current = self.get_run(run_id)
        if current is None or current.version != expected_version:
            raise StorageConflictError("durable run budget version no longer matches")
        if (
            budget.max_turns != current.budget.max_turns
            or budget.max_tokens != current.budget.max_tokens
            or budget.max_elapsed_seconds != current.budget.max_elapsed_seconds
            or budget.turns_used < current.budget.turns_used
            or budget.tokens_used < current.budget.tokens_used
            or budget.elapsed_milliseconds_used < current.budget.elapsed_milliseconds_used
            or updated_at < current.updated_at
        ):
            raise StorageConflictError("durable run budget update is not monotonic")
        values = current.model_dump()
        values.update(
            {
                "budget": budget,
                "updated_at": updated_at,
                "version": current.version + 1,
            }
        )
        updated = Run.model_validate(values)
        self._update(
            run_key(run_id),
            "RUN",
            updated,
            condition="#state = :expected_state AND #version = :expected_version",
            names={"#state": "state", "#version": "version"},
            values={
                ":expected_state": _string(current.state.value),
                ":expected_version": _number(expected_version),
            },
            indexed_updates={"version": _number(updated.version)},
        )
        return updated

    def get_proposal(self, proposal_id: UUID) -> ActionProposal | None:
        return self._read(proposal_key(proposal_id), "ACTION_PROPOSAL", ActionProposal)

    def transition_proposal(
        self,
        proposal_id: UUID,
        next_state: ProposalState,
        *,
        expected_state: ProposalState,
    ) -> ActionProposal:
        current = self.get_proposal(proposal_id)
        if current is None or current.state is not expected_state:
            raise StorageConflictError("durable proposal state no longer matches")
        updated = transitioned_proposal(current, next_state)
        self._update(
            proposal_key(proposal_id),
            "ACTION_PROPOSAL",
            updated,
            condition="#state = :expected_state",
            names={"#state": "state"},
            values={":expected_state": _string(expected_state.value)},
            indexed_updates={"state": _string(updated.state.value)},
        )
        return updated

    def create_approval(self, approval: Approval) -> Approval:
        proposal = self.get_proposal(approval.proposal_id)
        if proposal is None or proposal.state is not ProposalState.AWAITING_APPROVAL:
            raise StorageConflictError("human decision requires an awaiting durable proposal")
        validate_approval_binding(proposal, approval)
        try:
            self._put_create(
                approval_decision_key(approval.proposal_id),
                "APPROVAL",
                approval,
                decision=_string(approval.decision.value),
            )
        except StorageConflictError as conflict:
            existing = self.get_approval(approval.proposal_id)
            if existing == approval:
                return existing
            raise StorageConflictError("conflicting human decision already exists") from conflict
        return approval

    def get_approval(self, proposal_id: UUID) -> Approval | None:
        return self._read(approval_decision_key(proposal_id), "APPROVAL", Approval)

    def register_idempotency(self, record: IdempotencyRecord) -> IdempotencyRecord:
        key = semantic_idempotency_key(record.idempotency_key)
        existing = self.get_idempotency(record.idempotency_key)
        if existing is not None:
            if (
                existing.proposal_id != record.proposal_id
                or existing.action_fingerprint != record.action_fingerprint
            ):
                raise StorageConflictError("idempotency key has incompatible ownership")
            return existing
        proposal = self.get_proposal(record.proposal_id)
        if (
            proposal is None
            or proposal.state is not ProposalState.AWAITING_APPROVAL
            or record.action_fingerprint != derive_action_fingerprint(proposal)
            or record.idempotency_key != derive_idempotency_key(proposal)
        ):
            raise StorageConflictError("idempotency registration lacks a matching proposal")
        approval = self.get_approval(record.proposal_id)
        run = self.get_run(proposal.run_id)
        if approval is None or approval.decision is not ApprovalDecision.APPROVED:
            raise StorageConflictError("idempotency registration requires human approval")
        if run is None or run.state is not WorkflowState.APPROVED:
            raise StorageConflictError("idempotency registration requires an approved run")
        try:
            self._put_create(
                key,
                "IDEMPOTENCY",
                record,
                status=_string(record.status.value),
                action_fingerprint=_string(record.action_fingerprint),
            )
        except StorageConflictError as conflict:
            existing = self.get_idempotency(record.idempotency_key)
            if existing is None:
                raise StorageConflictError(
                    "idempotency ownership could not be reconciled"
                ) from conflict
            if (
                existing.proposal_id != record.proposal_id
                or existing.action_fingerprint != record.action_fingerprint
            ):
                raise StorageConflictError(
                    "idempotency key has incompatible ownership"
                ) from conflict
            return existing
        return record

    def get_idempotency(self, idempotency_key: str) -> IdempotencyRecord | None:
        return self._read(
            semantic_idempotency_key(idempotency_key),
            "IDEMPOTENCY",
            IdempotencyRecord,
        )

    def complete_idempotency(
        self,
        idempotency_key: str,
        result: ActionResult,
        *,
        completed_at: datetime,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        current = self.get_idempotency(idempotency_key)
        if current is None or current.status is not expected_status:
            raise StorageConflictError("idempotency status no longer matches")
        values = current.model_dump()
        values.update(
            {
                "status": completed_idempotency_status(result),
                "action_result": result,
                "completed_at": completed_at,
            }
        )
        updated = IdempotencyRecord.model_validate(values)
        self._update(
            semantic_idempotency_key(idempotency_key),
            "IDEMPOTENCY",
            updated,
            condition="#status = :expected_status AND #fingerprint = :fingerprint",
            names={"#status": "status", "#fingerprint": "action_fingerprint"},
            values={
                ":expected_status": _string(expected_status.value),
                ":fingerprint": _string(current.action_fingerprint),
            },
            indexed_updates={"status": _string(updated.status.value)},
        )
        return updated

    def record_execution_acknowledgement(
        self,
        idempotency_key: str,
        acknowledgement: ExecutionAcknowledgement,
        *,
        expected_status: IdempotencyStatus = IdempotencyStatus.REGISTERED,
    ) -> IdempotencyRecord:
        current = self.get_idempotency(idempotency_key)
        if current is None or current.status is not expected_status:
            raise StorageConflictError("idempotency status no longer matches")
        if current.execution_acknowledgement is not None:
            if current.execution_acknowledgement == acknowledgement:
                return current
            raise StorageConflictError("conflicting execution acknowledgement exists")
        if acknowledgement.proposal_id != current.proposal_id:
            raise StorageConflictError("execution acknowledgement ownership is invalid")
        updated = current.model_copy(update={"execution_acknowledgement": acknowledgement})
        try:
            self._update(
                semantic_idempotency_key(idempotency_key),
                "IDEMPOTENCY",
                updated,
                condition=(
                    "#status = :expected_status AND #fingerprint = :fingerprint "
                    "AND attribute_not_exists(#acknowledgement_hash)"
                ),
                names={
                    "#status": "status",
                    "#fingerprint": "action_fingerprint",
                    "#acknowledgement_hash": "acknowledgement_hash",
                },
                values={
                    ":expected_status": _string(expected_status.value),
                    ":fingerprint": _string(current.action_fingerprint),
                },
                indexed_updates={
                    "acknowledgement_hash": _string(acknowledgement.acknowledgement_hash)
                },
            )
        except StorageConflictError as conflict:
            raced = self.get_idempotency(idempotency_key)
            if raced is not None and raced.execution_acknowledgement == acknowledgement:
                return raced
            raise StorageConflictError("conflicting execution acknowledgement exists") from conflict
        return updated

    def save_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        expected_version: int | None,
    ) -> Checkpoint:
        key = checkpoint_key(checkpoint.run_id)
        if expected_version is None:
            if checkpoint.version != 1:
                raise StorageConflictError("new checkpoint must start at version 1")
            self._put_create(
                key,
                "CHECKPOINT",
                checkpoint,
                version=_number(checkpoint.version),
            )
            return checkpoint
        current = self.get_checkpoint(checkpoint.run_id)
        if (
            current is None
            or current.version != expected_version
            or checkpoint.version != expected_version + 1
        ):
            raise StorageConflictError("checkpoint version no longer matches")
        self._update(
            key,
            "CHECKPOINT",
            checkpoint,
            condition="#version = :expected_version",
            names={"#version": "version"},
            values={":expected_version": _number(expected_version)},
            indexed_updates={"version": _number(checkpoint.version)},
        )
        return checkpoint

    def get_checkpoint(self, run_id: UUID) -> Checkpoint | None:
        return self._read(checkpoint_key(run_id), "CHECKPOINT", Checkpoint)

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        self._put_create(
            audit_event_key(event.run_id, event.event_id),
            "AUDIT_EVENT",
            event,
        )
        return event

    def get_audit_event(self, run_id: UUID, event_id: UUID) -> AuditEvent | None:
        return self._read(audit_event_key(run_id, event_id), "AUDIT_EVENT", AuditEvent)

    def create_verification_evidence(
        self,
        evidence: VerificationEvidence,
    ) -> VerificationEvidence:
        proposal = self.get_proposal(evidence.proposal_id)
        run = self.get_run(evidence.run_id)
        idempotency = (
            self.get_idempotency(derive_idempotency_key(proposal)) if proposal is not None else None
        )
        approval = self.get_approval(evidence.proposal_id)
        acknowledgement_matches = (
            evidence.proof_origin is VerificationProofOrigin.EXECUTION_ACKNOWLEDGEMENT
            and idempotency is not None
            and idempotency.execution_acknowledgement is not None
            and idempotency.execution_acknowledgement.acknowledgement_hash
            == evidence.execution_acknowledgement_hash
        )
        recovery_matches = (
            evidence.proof_origin is VerificationProofOrigin.RECOVERY_READ_BACK
            and idempotency is not None
            and idempotency.status is IdempotencyStatus.REGISTERED
            and idempotency.execution_acknowledgement is None
            and approval is not None
            and approval.decision is ApprovalDecision.APPROVED
            and approval.run_id == evidence.run_id
            and approval.target == evidence.target
        )
        if (
            proposal is None
            or run is None
            or run.state is not WorkflowState.VERIFYING
            or proposal.run_id != evidence.run_id
            or proposal.target != evidence.target
            or run.trace_id != evidence.trace_id
            or run.correlation_id != evidence.correlation_id
            or idempotency is None
            or not (acknowledgement_matches or recovery_matches)
        ):
            raise StorageConflictError("verification evidence does not match the proposal")
        try:
            self._put_create(
                verification_evidence_key(evidence.run_id, evidence.proposal_id),
                "VERIFICATION_EVIDENCE",
                evidence,
                evidence_hash=_string(evidence.evidence_hash),
            )
        except StorageConflictError as conflict:
            existing = self.get_verification_evidence(
                evidence.run_id,
                evidence.proposal_id,
            )
            if existing == evidence:
                return existing
            raise StorageConflictError(
                "conflicting verification evidence already exists"
            ) from conflict
        return evidence

    def get_verification_evidence(
        self,
        run_id: UUID,
        proposal_id: UUID,
    ) -> VerificationEvidence | None:
        return self._read(
            verification_evidence_key(run_id, proposal_id),
            "VERIFICATION_EVIDENCE",
            VerificationEvidence,
        )
