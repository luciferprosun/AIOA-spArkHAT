"""Trusted-principal and one-time freshness binding for non-public HITL resume proof."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, ConfigDict, SecretStr

from aioa_cloudops_agent.agent.approval_flow import ApprovalResumeResult
from aioa_cloudops_agent.agent.hitl import ApprovalInterrupt, ApprovalResumeRequest
from aioa_cloudops_agent.nz import ApprovalDecision, Checkpoint, WorkflowState
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError

from .auth import AuthenticatedJudgePrincipal

_CHALLENGE_DIGEST_KEY = "judge_freshness_digest"
_PRINCIPAL_DIGEST_KEY = "judge_principal_digest"
_EXPIRES_AT_KEY = "judge_freshness_expires_at"
_CONSUMED_KEY = "judge_freshness_consumed"


class _CheckpointRepository(Protocol):
    def get_checkpoint(self, run_id: object) -> Checkpoint | None: ...

    def save_checkpoint(
        self,
        checkpoint: Checkpoint,
        *,
        expected_version: int | None,
    ) -> Checkpoint: ...


class _ApprovalResumer(Protocol):
    def resume(self, response: ApprovalResumeRequest) -> ApprovalResumeResult: ...


class IssuedResumeChallenge(BaseModel):
    """One-time server-issued value; repr hides the usable credential."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: SecretStr
    expires_at: datetime


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthenticatedApprovalResumeService:
    """Consume durable freshness before handing a typed response to Strands."""

    def __init__(
        self,
        flow: _ApprovalResumer,
        repository: _CheckpointRepository,
        *,
        clock: Callable[[], datetime],
        challenge_factory: Callable[[], str],
        challenge_ttl_seconds: int = 300,
    ) -> None:
        if not all(callable(value) for value in (clock, challenge_factory)):
            raise TypeError("clock and challenge_factory must be callable")
        if not 30 <= challenge_ttl_seconds <= 600:
            raise ValueError("challenge_ttl_seconds must be between 30 and 600")
        self._flow = flow
        self._repository = repository
        self._clock = clock
        self._challenge_factory = challenge_factory
        self._challenge_ttl_seconds = challenge_ttl_seconds

    def issue(
        self,
        interrupt: ApprovalInterrupt,
        principal: AuthenticatedJudgePrincipal,
    ) -> IssuedResumeChallenge:
        """Persist only digests of a server-issued principal-bound challenge."""

        if not isinstance(interrupt, ApprovalInterrupt):
            raise TypeError("interrupt must be ApprovalInterrupt")
        if not isinstance(principal, AuthenticatedJudgePrincipal):
            raise TypeError("principal must be server-authenticated")
        checkpoint = self._repository.get_checkpoint(interrupt.payload.run_id)
        if (
            checkpoint is None
            or checkpoint.last_safe_state is not WorkflowState.AWAITING_APPROVAL
            or checkpoint.resume_metadata.get("approval_interrupt_id")
            != interrupt.interrupt_id
            or checkpoint.resume_metadata.get("approval_request_hash")
            != interrupt.request_hash
        ):
            raise StorageConflictError("durable approval interrupt is not challenge-ready")
        value = self._challenge_factory()
        if not isinstance(value, str) or len(value) < 32 or value != value.strip():
            raise ValueError("challenge_factory returned an invalid value")
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
            raise StorageDependencyError("resume authority clock is unavailable")
        expires_at = now + timedelta(seconds=self._challenge_ttl_seconds)
        updated = Checkpoint(
            run_id=checkpoint.run_id,
            last_safe_state=checkpoint.last_safe_state,
            resume_metadata={
                **checkpoint.resume_metadata,
                _CHALLENGE_DIGEST_KEY: _digest(value),
                _PRINCIPAL_DIGEST_KEY: _digest(principal.subject),
                _EXPIRES_AT_KEY: expires_at.isoformat(),
                _CONSUMED_KEY: False,
            },
            tool_result_hashes=checkpoint.tool_result_hashes,
            created_at=now,
            version=checkpoint.version + 1,
        )
        self._repository.save_checkpoint(updated, expected_version=checkpoint.version)
        return IssuedResumeChallenge(value=SecretStr(value), expires_at=expires_at)

    def resume(
        self,
        *,
        interrupt: ApprovalInterrupt,
        decision: ApprovalDecision,
        principal: AuthenticatedJudgePrincipal,
        challenge: str,
    ) -> ApprovalResumeResult:
        """Atomically consume freshness, then resume the exact durable interrupt."""

        if not isinstance(interrupt, ApprovalInterrupt):
            raise TypeError("interrupt must be ApprovalInterrupt")
        if not isinstance(decision, ApprovalDecision):
            raise TypeError("decision must be ApprovalDecision")
        if not isinstance(principal, AuthenticatedJudgePrincipal):
            raise TypeError("principal must be server-authenticated")
        if not isinstance(challenge, str):
            raise StorageConflictError("durable resume challenge was rejected")
        checkpoint = self._repository.get_checkpoint(interrupt.payload.run_id)
        if checkpoint is None:
            raise StorageConflictError("durable resume challenge is unavailable")
        metadata = checkpoint.resume_metadata
        expected_challenge = metadata.get(_CHALLENGE_DIGEST_KEY)
        expected_principal = metadata.get(_PRINCIPAL_DIGEST_KEY)
        expires_raw = metadata.get(_EXPIRES_AT_KEY)
        try:
            expires_at = datetime.fromisoformat(str(expires_raw))
        except (TypeError, ValueError):
            raise StorageConflictError("durable resume challenge is invalid") from None
        if (
            metadata.get(_CONSUMED_KEY) is not False
            or not isinstance(expected_challenge, str)
            or not isinstance(expected_principal, str)
            or not hmac.compare_digest(expected_challenge, _digest(challenge))
            or not hmac.compare_digest(expected_principal, _digest(principal.subject))
            or self._clock() >= expires_at
        ):
            raise StorageConflictError("durable resume challenge was rejected")
        consumed_at = self._clock()
        consumed = Checkpoint(
            run_id=checkpoint.run_id,
            last_safe_state=checkpoint.last_safe_state,
            resume_metadata={**metadata, _CONSUMED_KEY: True},
            tool_result_hashes=checkpoint.tool_result_hashes,
            created_at=consumed_at,
            version=checkpoint.version + 1,
        )
        self._repository.save_checkpoint(consumed, expected_version=checkpoint.version)
        payload = interrupt.payload
        challenge_digest = _digest(challenge)
        response = ApprovalResumeRequest(
            interrupt_id=interrupt.interrupt_id,
            proposal_id=payload.proposal_id,
            run_id=payload.run_id,
            action=payload.action,
            target=payload.target,
            evidence_hash=payload.evidence_hash,
            request_hash=interrupt.request_hash,
            decision=decision,
            actor_session_id=f"judge:{_digest(principal.subject)[:32]}",
            decision_nonce=f"freshness:{challenge_digest}",
        )
        return self._flow.resume(response)
