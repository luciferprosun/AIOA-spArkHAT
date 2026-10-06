"""Strict parser for MCP Commander GitHub claim comments.

A claim proves that a worker observed and leased a transport task. It does
not grant execution authority and can never substitute for human approval.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import uuid

from .contracts import ContractError

CLAIM_PREFIX = "MCP-COMMANDER-CLAIM/v1\n"
_HASH_RE = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class TransportClaim:
    envelope_task_id: str
    local_job_id: str
    issue_number: int
    worker_id: str
    nonce: str
    payload_hash: str
    lease_expires_at: int
    authority: str = "TRANSPORT_EVIDENCE_ONLY"
    can_authorize_effects: bool = False


def _uuid_text(name: str, value: object) -> str:
    if type(value) is not str:
        raise ContractError(f"{name} must be a UUID string")
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ContractError(f"{name} must be a UUID string") from exc
    return value


def parse_claim_comment(text: str) -> TransportClaim:
    if type(text) is not str or not text.startswith(CLAIM_PREFIX):
        raise ContractError("claim comment prefix is invalid")
    raw = text[len(CLAIM_PREFIX):]
    if len(raw.encode("utf-8")) > 4096:
        raise ContractError("claim comment exceeds limit")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError("claim JSON is invalid") from exc
    if type(value) is not dict:
        raise ContractError("claim payload must be an object")
    expected = {
        "envelope_task_id", "local_job_id", "issue_number", "worker_id",
        "nonce", "payload_hash", "lease_expires_at",
    }
    if set(value) != expected:
        raise ContractError("claim fields do not match v1 contract")
    envelope_task_id = value["envelope_task_id"]
    if type(envelope_task_id) is not str or not envelope_task_id or len(envelope_task_id) > 128:
        raise ContractError("envelope_task_id is invalid")
    issue_number = value["issue_number"]
    if type(issue_number) is not int or issue_number <= 0:
        raise ContractError("issue_number is invalid")
    payload_hash = value["payload_hash"]
    if type(payload_hash) is not str or _HASH_RE.fullmatch(payload_hash) is None:
        raise ContractError("payload_hash is invalid")
    lease_expires_at = value["lease_expires_at"]
    if type(lease_expires_at) is not int or lease_expires_at <= 0:
        raise ContractError("lease_expires_at is invalid")
    return TransportClaim(
        envelope_task_id=envelope_task_id,
        local_job_id=_uuid_text("local_job_id", value["local_job_id"]),
        issue_number=issue_number,
        worker_id=_uuid_text("worker_id", value["worker_id"]),
        nonce=_uuid_text("nonce", value["nonce"]),
        payload_hash=payload_hash,
        lease_expires_at=lease_expires_at,
    )
