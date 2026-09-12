"""Typed independent EC2 read-back observations and completion result."""

from datetime import datetime, timedelta
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aioa_cloudops_agent.cloudops import Ec2InstanceState
from aioa_cloudops_agent.domain import AuthorityGate, AwsOperationClass
from aioa_cloudops_agent.nz import (
    ActionTarget,
    Sha256Digest,
    Uuid7Identifier,
    VerificationDisposition,
    VerificationEvidence,
    WorkflowState,
)


class VerificationObservation(BaseModel):
    """One normalized provider read, never a mutation acknowledgement."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    target: ActionTarget
    disposition: VerificationDisposition
    observed_state: Ec2InstanceState
    observed_at: datetime
    attempt: int
    inspection_evidence_hash: Sha256Digest
    observation_hash: Sha256Digest
    authority_gate: Literal[AuthorityGate.AUTO] = AuthorityGate.AUTO
    operation_class: Literal[AwsOperationClass.READ_ONLY] = AwsOperationClass.READ_ONLY

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("observed_at must be a timezone-aware UTC datetime")
        return value

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        expected = (
            VerificationDisposition.VERIFIED
            if self.observed_state is Ec2InstanceState.STOPPED
            else VerificationDisposition.STILL_TRANSITIONING
            if self.observed_state is Ec2InstanceState.STOPPING
            else VerificationDisposition.MISMATCH
        )
        if self.disposition is not expected:
            raise ValueError("verification disposition does not match observed EC2 state")
        if self.attempt <= 0:
            raise ValueError("attempt must be positive")
        return self


class VerificationCompletion(BaseModel):
    """Durable final proof returned only after the success transition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: VerificationEvidence
    final_state: Literal[WorkflowState.SUCCESS_WITH_EVIDENCE] = (
        WorkflowState.SUCCESS_WITH_EVIDENCE
    )
    attempts: int = Field(ge=0)
    reconciled: bool = False
