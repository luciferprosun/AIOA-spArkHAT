# Native semantic port; MIT attribution: LICENSE-NONZERO.txt.
# Source: local_api/views.py at 4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a.
"""Sanitized read models for the portable judge experience."""

from .composition import NativeComponents
from .models import AuditEvent, AuditEventType, Checkpoint, Run
from .state.repository import RunSnapshot
from .views import (
    LocalApprovalDecisionView,
    LocalApprovalRequestView,
    LocalAuditEventView,
    LocalCheckpointView,
    LocalEvidenceCategory,
    LocalExecutionIntentView,
    LocalRuntimeView,
    LocalRunView,
)

_AGENT_INFERENCE_EVENTS = frozenset(
    {
        AuditEventType.MODEL_OBSERVED,
        AuditEventType.PROPOSAL_CREATED,
        AuditEventType.REMEDIATION_PLANNED,
        AuditEventType.NO_ACTION_RECORDED,
        AuditEventType.RECOMMENDATION_RECORDED,
    }
)
_POLICY_EVENTS = frozenset(
    {
        AuditEventType.POLICY_DENIED,
        AuditEventType.MODEL_OUTPUT_REJECTED,
        AuditEventType.BUDGET_EXHAUSTED,
        AuditEventType.BUDGET_UPDATED,
    }
)
_HUMAN_EVENTS = frozenset(
    {AuditEventType.APPROVAL_REQUESTED, AuditEventType.APPROVAL_RECORDED}
)
_ACTION_EVENTS = frozenset(
    {
        AuditEventType.IDEMPOTENCY_REGISTERED,
        AuditEventType.EXECUTION_REQUESTED,
        AuditEventType.EXECUTION_ACKNOWLEDGED,
    }
)
_VERIFICATION_EVENTS = frozenset(
    {
        AuditEventType.VERIFICATION_STARTED,
        AuditEventType.VERIFICATION_OBSERVED,
        AuditEventType.VERIFICATION_RECORDED,
    }
)
_RECOVERY_EVENTS = frozenset(
    {
        AuditEventType.RECOVERY_CLASSIFIED,
        AuditEventType.RECOVERY_OBSERVED,
        AuditEventType.RECOVERY_COMPLETED,
        AuditEventType.RECOVERY_DEFERRED,
    }
)

_PUBLIC_AUDIT_METADATA = frozenset(
    {
        "authority",
        "decision",
        "policy_code",
        "proposal_id",
        "request_id",
        "resource_id",
        "resource_type",
    }
)


def runtime_view(runtime: NativeComponents) -> LocalRuntimeView:
    """Truthful counters for the Core-owned native portable composition."""
    if not isinstance(runtime, NativeComponents):
        raise TypeError("runtime must be NativeComponents")
    _, mutations, _ = runtime.executor.counters()
    return LocalRuntimeView(
        model_id="core-native-deterministic-advisor-v1",
        process_provider_calls=runtime.advisor.plan_calls,
        process_external_network_calls=0,
        process_sandbox_mutations=mutations,
    )


def _checkpoint_view(checkpoint: Checkpoint | None) -> LocalCheckpointView | None:
    if checkpoint is None:
        return None
    request = checkpoint.local_approval_request
    approval = checkpoint.local_approval
    intent = checkpoint.local_execution_intent
    return LocalCheckpointView(
        last_safe_state=checkpoint.last_safe_state,
        version=checkpoint.version,
        resource_evidence=checkpoint.resource_evidence,
        remediation_proposal=checkpoint.remediation_proposal,
        approval_request=(
            None
            if request is None
            else LocalApprovalRequestView(
                request_id=request.request_id,
                proposal_id=request.proposal_id,
                proposal_hash=request.proposal_hash,
                evidence_hash=request.evidence_hash,
                proposal_version=request.proposal_version,
                operation_type=request.operation_type,
                target_resource_type=request.target_resource_type,
                target_resource_id=request.target_resource_id,
                requested_at=request.requested_at,
                expires_at=request.expires_at,
                request_hash=request.request_hash,
            )
        ),
        approval=(
            None
            if approval is None
            else LocalApprovalDecisionView(
                request_id=approval.request_id,
                proposal_id=approval.proposal_id,
                request_hash=approval.request_hash,
                proposal_hash=approval.proposal_hash,
                evidence_hash=approval.evidence_hash,
                proposal_version=approval.proposal_version,
                decision=approval.decision,
                decided_at=approval.decided_at,
                decision_hash=approval.decision_hash,
            )
        ),
        execution_intent=(
            None
            if intent is None
            else LocalExecutionIntentView(
                proposal_id=intent.proposal_id,
                proposal_hash=intent.proposal_hash,
                evidence_hash=intent.evidence_hash,
                decision_hash=intent.decision_hash,
                operation_type=intent.operation_type,
                target_resource_type=intent.target_resource_type,
                target_resource_id=intent.target_resource_id,
                registered_at=intent.registered_at,
                intent_hash=intent.intent_hash,
            )
        ),
        execution_receipt=checkpoint.local_execution_receipt,
        verification=checkpoint.local_verification,
    )


def _audit_event_view(event: AuditEvent) -> LocalAuditEventView:
    if event.type in _AGENT_INFERENCE_EVENTS:
        category = LocalEvidenceCategory.AGENT_INFERENCE
    elif event.type in _POLICY_EVENTS:
        category = LocalEvidenceCategory.POLICY_DECISION
    elif event.type in _HUMAN_EVENTS:
        category = LocalEvidenceCategory.HUMAN_DECISION
    elif event.type in _ACTION_EVENTS:
        category = LocalEvidenceCategory.ACTION
    elif event.type in _VERIFICATION_EVENTS:
        category = LocalEvidenceCategory.VERIFICATION
    elif event.type in _RECOVERY_EVENTS:
        category = LocalEvidenceCategory.RECOVERY
    else:
        category = LocalEvidenceCategory.FACT
    return LocalAuditEventView(
        event_id=event.event_id,
        type=event.type,
        category=category,
        summary=event.type.value.replace("_", " ").title(),
        timestamp=event.timestamp,
        source=event.source,
        redacted_payload_hash=event.redacted_payload_hash,
        metadata={
            key: value
            for key, value in event.metadata.items()
            if key in _PUBLIC_AUDIT_METADATA
        },
    )


def run_view(
    runtime: NativeComponents,
    snapshot: RunSnapshot,
) -> LocalRunView:
    """Project authoritative state into the sole judge-facing run representation."""

    if not isinstance(runtime, NativeComponents) or not isinstance(
        snapshot, RunSnapshot
    ):
        raise TypeError("runtime and snapshot must use canonical local contracts")
    run = snapshot.run
    checkpoint = snapshot.checkpoint
    audit_events = snapshot.audit_events
    if not isinstance(run, Run):
        raise TypeError("snapshot must contain a canonical run")
    if checkpoint is not None and checkpoint.run_id != run.run_id:
        raise ValueError("checkpoint does not belong to the requested run")
    if any(event.run_id != run.run_id for event in audit_events):
        raise ValueError("audit timeline contains another run")
    receipt = None if checkpoint is None else checkpoint.local_execution_receipt
    return LocalRunView(
        evidence_snapshot_sha256=snapshot.snapshot_sha256,
        run=run,
        checkpoint=_checkpoint_view(checkpoint),
        audit_events=tuple(_audit_event_view(event) for event in audit_events),
        runtime=runtime_view(runtime),
        run_sandbox_mutations=int(receipt is not None),
        audit_event_count=snapshot.audit_event_count,
        audit_events_truncated=snapshot.audit_event_count > len(audit_events),
    )
