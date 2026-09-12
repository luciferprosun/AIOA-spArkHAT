"""Typed command boundary for the private sandbox remediation executor."""

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from aioa_cloudops_agent.nz import (
    ActionTarget,
    Capability,
    ExpectedPrecondition,
    IdempotencyKey,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
)


class StopExecutionCommand(BaseModel):
    """Application-generated command; conversational input cannot construct it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    action: Literal[Capability.STOP_SANDBOX_INSTANCE] = Capability.STOP_SANDBOX_INSTANCE
    target: ActionTarget
    expected_precondition: ExpectedPrecondition
    evidence_hash: Sha256Digest
    approval_request_hash: Sha256Digest
    approval_actor_session_id: ShortIdentifier
    approval_decision_nonce_hash: Sha256Digest
    idempotency_key: IdempotencyKey
    issued_at: datetime

    @field_validator("issued_at")
    @classmethod
    def validate_issued_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("issued_at must be a timezone-aware UTC datetime")
        return value

    @model_validator(mode="after")
    def validate_evidence_binding(self) -> Self:
        if self.evidence_hash != self.expected_precondition.evidence_hash:
            raise ValueError("command evidence must match its expected precondition")
        return self
