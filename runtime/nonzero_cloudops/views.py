# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: local_api/contracts.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Strict local-only HTTP contracts for the Local-2 operator surface."""

from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import (
    ApprovalDecision,
    AuditEventType,
    CloudResourceType,
    FailureKind,
    LocalExecutionReceipt,
    LocalVerificationEvidence,
    NonEmptyText,
    RemediationOperation,
    RemediationProposal,
    ResourceEvidence,
    ResourceQuery,
    Run,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
    WorkflowState,
    contains_sensitive_material,
)


class LocalApiErrorCode(StrEnum):
    """Stable redacted HTTP errors; exception text never crosses the boundary."""

    BAD_REQUEST = "BAD_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    REQUEST_TIMEOUT = "REQUEST_TIMEOUT"
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    UNAUTHORIZED = "UNAUTHORIZED"
    POLICY_DENIED = "POLICY_DENIED"
    CONFLICT = "CONFLICT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class LocalEvidenceCategory(StrEnum):
    """Judge-facing provenance classes; model output remains visibly non-authoritative."""

    FACT = "FACT"
    AGENT_INFERENCE = "AGENT_INFERENCE"
    POLICY_DECISION = "POLICY_DECISION"
    HUMAN_DECISION = "HUMAN_DECISION"
    ACTION = "ACTION"
    VERIFICATION = "VERIFICATION"
    RECOVERY = "RECOVERY"


class LocalApiErrorResponse(BaseModel):
    """Public failure without provider payloads, secrets, or tracebacks."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: Literal[False] = False
    error: LocalApiErrorCode
    failure_kind: FailureKind | None = None
    failure_code: str | None = Field(default=None, min_length=1, max_length=128)
    retryable: bool = False


class StartRunRequest(BaseModel):
    """One exact inventory target; region and budgets remain server-owned."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: CloudResourceType
    resource_id: ShortIdentifier

    @model_validator(mode="after")
    def validate_resource_identity(self) -> Self:
        ResourceQuery(
            resource_type=self.resource_type,
            resource_id=self.resource_id,
        )
        return self

    def to_query(self) -> ResourceQuery:
        return ResourceQuery(
            resource_type=self.resource_type,
            resource_id=self.resource_id,
        )


class ResumeRequest(BaseModel):
    """Require an explicit final execution gesture at the HTTP boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirm_execution: Literal[True]

    @field_validator("confirm_execution", mode="before")
    @classmethod
    def require_boolean_gesture(cls, value):
        if value is not True:
            raise ValueError("explicit boolean execution confirmation required")
        return value


class LocalRuntimeView(BaseModel):
    """Truthful, public-safe runtime facts for labels and judge evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_mode: Literal["portable"] = "portable"
    experience_mode: Literal["PORTABLE_SANDBOX"] = "PORTABLE_SANDBOX"
    model_mode: Literal["DETERMINISTIC_MODEL"] = "DETERMINISTIC_MODEL"
    provider: Literal["mock"] = "mock"
    model_id: str = Field(min_length=1, max_length=256)
    agent_framework: Literal["AIOA spArkHAT"] = "AIOA spArkHAT"
    aws_calls_allowed: Literal[False] = False
    real_cloud_mutations_enabled: Literal[False] = False
    external_network_allowed: Literal[False] = False
    process_provider_calls: int = Field(ge=0)
    process_external_network_calls: int = Field(ge=0)
    process_sandbox_mutations: int = Field(ge=0)


class LocalReadyView(BaseModel):
    """Readiness distinct from process health and free of cloud prerequisites."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ready"] = "ready"
    process_status: Literal["READY"] = "READY"
    provider_status: Literal["READY"] = "READY"
    sandbox_status: Literal["READY"] = "READY"
    runtime: LocalRuntimeView


class LocalApprovalRequestView(BaseModel):
    """Human-visible binding with nonce/session material deliberately removed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    proposal_id: UUID
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    proposal_version: int = Field(gt=0)
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    requested_at: datetime
    expires_at: datetime
    request_hash: Sha256Digest


class LocalApprovalDecisionView(BaseModel):
    """Durable human authority proof without actor-session or nonce hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: UUID
    proposal_id: UUID
    request_hash: Sha256Digest
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    proposal_version: int = Field(gt=0)
    decision: ApprovalDecision
    decided_at: datetime
    decision_hash: Sha256Digest


class LocalApprovalChallengeRequestView(LocalApprovalRequestView):
    """Public request binding, including the run ID required by DecisionRequest."""

    run_id: Uuid7Identifier


class LocalApprovalChallengeView(BaseModel):
    """Protected challenge: the ephemeral nonce is exposed only at this step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: LocalApprovalChallengeRequestView
    proposal: RemediationProposal
    evidence: ResourceEvidence
    decision_nonce: NonEmptyText = Field(min_length=16, max_length=256)


class LocalExecutionCompletionView(BaseModel):
    """Public projection of an already validated internal terminal result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    decision: ApprovalDecision
    final_state: Literal[
        WorkflowState.DENIED_BY_HUMAN,
        WorkflowState.SUCCESS_WITH_EVIDENCE,
    ]
    approval: LocalApprovalDecisionView
    receipt: LocalExecutionReceipt | None = None
    verification: LocalVerificationEvidence | None = None
    reconciled: bool = False


class LocalExecutionIntentView(BaseModel):
    """Sanitized write-before-execute proof for one exact approved action."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: UUID
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    decision_hash: Sha256Digest
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    registered_at: datetime
    intent_hash: Sha256Digest


class LocalCheckpointView(BaseModel):
    """Judge-safe projection of the durable checkpoint and linked evidence chain."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    last_safe_state: WorkflowState
    version: int = Field(gt=0)
    resource_evidence: ResourceEvidence | None = None
    remediation_proposal: RemediationProposal | None = None
    approval_request: LocalApprovalRequestView | None = None
    approval: LocalApprovalDecisionView | None = None
    execution_intent: LocalExecutionIntentView | None = None
    execution_receipt: LocalExecutionReceipt | None = None
    verification: LocalVerificationEvidence | None = None


class LocalAuditEventView(BaseModel):
    """Redacted immutable event; only judge-relevant metadata is exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: UUID
    type: AuditEventType
    category: LocalEvidenceCategory
    summary: str = Field(min_length=1, max_length=160)
    timestamp: datetime
    source: ShortIdentifier
    redacted_payload_hash: Sha256Digest
    metadata: dict[ShortIdentifier, str] = Field(default_factory=dict)


class LocalRunView(BaseModel):
    """Authenticated judge projection; secret-adjacent durable fields stay private."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_schema_version: Literal[2] = 2
    evidence_integrity: Literal["VERIFIED"] = "VERIFIED"
    evidence_snapshot_sha256: Sha256Digest
    run: Run
    checkpoint: LocalCheckpointView | None = None
    audit_events: tuple[LocalAuditEventView, ...] = ()
    runtime: LocalRuntimeView
    run_sandbox_mutations: int = Field(ge=0, le=1)
    audit_event_count: int = Field(ge=0, le=1_024)
    audit_events_truncated: bool

    @model_validator(mode="after")
    def validate_timeline_bounds(self) -> Self:
        if self.audit_event_count < len(self.audit_events):
            raise ValueError("audit event count is smaller than the visible timeline")
        if self.audit_events_truncated != (
            self.audit_event_count > len(self.audit_events)
        ):
            raise ValueError("audit timeline truncation marker is inconsistent")
        if contains_sensitive_material(self.model_dump(mode="json")):
            raise ValueError("judge evidence contains sensitive material")
        return self
