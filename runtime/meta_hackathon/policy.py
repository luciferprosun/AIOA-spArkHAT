"""Fail-closed *screening* for Muse/Chromium plans.

This module never returns ALLOW or a warrant. A Core-owned runtime must still
admit the owner, source version, task lease, kill switch and exact operations.
No browser implementation is attached here; no network or effects are emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from .contracts import (
    ActionProposalV1, BrowserObservationV1, BrowserTaskV1,
    MetaContractError, _hash, utc_timestamp, valid_page_url,
)


class GateEffect(str, Enum):
    DENY = "DENY"
    CORE_ADMISSION_REQUIRED = "CORE_ADMISSION_REQUIRED"
    OWNER_REVIEW_REQUIRED = "OWNER_REVIEW_REQUIRED"
    UNVERIFIED_EVIDENCE = "UNVERIFIED_EVIDENCE"


@dataclass(frozen=True, slots=True)
class GateResult:
    effect: GateEffect
    reason: str
    task_digest: str

    @property
    def dispatch_allowed(self) -> bool:
        """Always False at this *screening* boundary."""
        return False


def _now(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MetaContractError("META_CLOCK_DENIED")
    return value.astimezone(timezone.utc)


def screen_task(
    task: BrowserTaskV1,
    *,
    core_owner_scope_digest: str,
    core_source_sha: str,
    stopped: bool,
    now: datetime | None = None,
) -> GateResult:
    if type(task) is not BrowserTaskV1 or type(stopped) is not bool:
        raise MetaContractError("META_GATE_INPUT_DENIED")
    _hash(core_owner_scope_digest)
    _hash(core_source_sha, sha40=True)
    if stopped:
        return GateResult(GateEffect.DENY, "STOP", task.digest)
    if task.owner_scope_digest != core_owner_scope_digest:
        return GateResult(GateEffect.DENY, "OWNER_SCOPE_MISMATCH", task.digest)
    if task.source_sha != core_source_sha:
        return GateResult(GateEffect.DENY, "SOURCE_SHA_MISMATCH", task.digest)
    if _now(now) >= utc_timestamp(task.deadline_utc):
        return GateResult(GateEffect.DENY, "TASK_EXPIRED", task.digest)
    return GateResult(GateEffect.CORE_ADMISSION_REQUIRED,
                      "CORE_SESSION_AND_BROWSER_WORKER_NOT_ADMITTED", task.digest)


def screen_action(
    action: ActionProposalV1,
    task: BrowserTaskV1,
    *,
    stopped: bool,
    now: datetime | None = None,
) -> GateResult:
    if (type(action) is not ActionProposalV1 or type(task) is not BrowserTaskV1
            or type(stopped) is not bool):
        raise MetaContractError("META_GATE_INPUT_DENIED")
    if stopped or _now(now) >= utc_timestamp(task.deadline_utc):
        return GateResult(GateEffect.DENY, "STOP_OR_EXPIRED", task.digest)
    if action.task_digest != task.digest or _now(now) >= utc_timestamp(action.expires_at_utc):
        return GateResult(GateEffect.DENY, "STALE_ACTION", task.digest)
    try:
        valid_page_url(action.target_url, task.allowed_origins)
    except MetaContractError:
        return GateResult(GateEffect.DENY, "TARGET_OUTSIDE_SCOPE", task.digest)
    if action.action in ("shell.exec", "git.push", "gmail.send", "account.change"):
        return GateResult(GateEffect.DENY, "ACTION_NOT_IN_BROWSER_MVP", task.digest)
    return GateResult(GateEffect.OWNER_REVIEW_REQUIRED,
                      "EXACT_OWNER_WARRANT_REQUIRED_NO_DISPATCH", task.digest)


def screen_observation(
    observation: BrowserObservationV1,
    task: BrowserTaskV1,
) -> GateResult:
    if type(observation) is not BrowserObservationV1 or type(task) is not BrowserTaskV1:
        raise MetaContractError("META_GATE_INPUT_DENIED")
    if observation.task_digest != task.digest:
        return GateResult(GateEffect.DENY, "OBSERVATION_TASK_MISMATCH", task.digest)
    try:
        valid_page_url(observation.observed_url, task.allowed_origins)
    except MetaContractError:
        return GateResult(GateEffect.DENY, "OBSERVATION_REDIRECT_OUT_OF_SCOPE", task.digest)
    if utc_timestamp(observation.captured_at_utc) > utc_timestamp(task.deadline_utc):
        return GateResult(GateEffect.DENY, "OBSERVATION_AFTER_DEADLINE", task.digest)
    return GateResult(GateEffect.UNVERIFIED_EVIDENCE,
                      "INDEPENDENT_BROWSER_READBACK_REQUIRED", task.digest)
