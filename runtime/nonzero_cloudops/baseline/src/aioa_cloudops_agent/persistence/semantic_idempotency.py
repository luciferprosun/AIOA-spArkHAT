"""Stable semantic idempotency for the future approved EC2 stop action."""

import hashlib
import json
from datetime import datetime

from aioa_cloudops_agent.nz import ActionProposal, IdempotencyRecord, ProposalState
from aioa_cloudops_agent.nz.errors import DurablePrerequisiteError


def derive_action_fingerprint(proposal: ActionProposal) -> str:
    """Hash the logical action without relying on a random identifier alone."""

    if not isinstance(proposal, ActionProposal):
        raise TypeError("proposal must be an ActionProposal")
    payload = {
        "run_id": str(proposal.run_id),
        "action": proposal.action.value,
        "target": proposal.target.model_dump(mode="json"),
        "expected_precondition": proposal.expected_precondition.model_dump(mode="json"),
        "authority": proposal.authority.value,
        "evidence_hash": proposal.evidence_hash,
    }
    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def derive_idempotency_key(proposal: ActionProposal) -> str:
    """Return a stable key for the same logical run/action/precondition."""

    return f"action/{derive_action_fingerprint(proposal)}"


def build_idempotency_record(
    proposal: ActionProposal,
    *,
    registered_at: datetime,
) -> IdempotencyRecord:
    """Build registration only after the proposal is durably awaiting approval."""

    if proposal.state is not ProposalState.AWAITING_APPROVAL:
        raise DurablePrerequisiteError("proposal must be durably awaiting approval")
    fingerprint = derive_action_fingerprint(proposal)
    return IdempotencyRecord(
        idempotency_key=f"action/{fingerprint}",
        proposal_id=proposal.proposal_id,
        action_fingerprint=fingerprint,
        registered_at=registered_at,
    )
