"""Build privileged command data only from durable approved prerequisites."""

import hashlib
from datetime import datetime

from aioa_cloudops_agent.persistence import ApprovedActionPrerequisites

from .models import StopExecutionCommand


def build_stop_execution_command(
    prerequisites: ApprovedActionPrerequisites,
    *,
    issued_at: datetime,
) -> StopExecutionCommand:
    """Convert exact durable proof into one narrow private-executor command."""

    if not isinstance(prerequisites, ApprovedActionPrerequisites):
        raise TypeError("prerequisites must be ApprovedActionPrerequisites")
    if not isinstance(issued_at, datetime):
        raise TypeError("issued_at must be a datetime")
    run = prerequisites.run
    proposal = prerequisites.proposal
    approval = prerequisites.approval
    return StopExecutionCommand(
        proposal_id=proposal.proposal_id,
        run_id=run.run_id,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        action=proposal.action,
        target=proposal.target,
        expected_precondition=proposal.expected_precondition,
        evidence_hash=proposal.evidence_hash,
        approval_request_hash=approval.request_hash,
        approval_actor_session_id=approval.actor_session_id,
        approval_decision_nonce_hash=hashlib.sha256(
            approval.decision_nonce.encode("utf-8")
        ).hexdigest(),
        idempotency_key=prerequisites.idempotency.idempotency_key,
        issued_at=issued_at,
    )
