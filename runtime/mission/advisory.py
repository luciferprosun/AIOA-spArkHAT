"""Thin links to native correction/experience records; no learning engine.

These contracts do not store events, assign scores, schedule work or grant any
capability. A future durable adapter must perform replay checks transactionally.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.evidence_admission import CoreEvidenceAdmission
from runtime.memory_patch.contracts.records import (
    CorrectionCandidate,
    ModelExperienceEvent,
    assert_model_experience_is_advisory,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256, ensure_utc
from runtime.mission.contracts import MissionError, MissionTrace, id_tuple, logical_id


def _same_owner(record, scope):
    if type(scope) is not OwnerScope or (
        record.tenant_id,
        record.user_id,
        record.personal_memory_space_id,
    ) != (scope.tenant_id, scope.owner_id, scope.space_id):
        raise MissionError("OWNER_SCOPE_MISMATCH", status="POLICY_BLOCKED", exit_code=4)


def _claim(value):
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 4096:
        raise MissionError("INVALID_MINIMAL_CLAIM")
    # Only Unicode NFC and outer whitespace: preserve case, units, dates and
    # internal whitespace (including literals/code). No fuzzy equivalence claim.
    return unicodedata.normalize("NFC", value).strip()


@dataclass(frozen=True, slots=True, repr=False)
class CorrectionDeltaLink:
    """References the existing CorrectionCandidate, not a competing Delta DTO."""

    candidate: CorrectionCandidate
    scope: OwnerScope
    trace: MissionTrace
    source_revision: str
    verification_method: str = "UNVERIFIED"

    def __post_init__(self):
        if (
            type(self.candidate) is not CorrectionCandidate
            or type(self.trace) is not MissionTrace
        ):
            raise MissionError("INVALID_CORRECTION_LINK")
        _same_owner(self.candidate, self.scope)
        logical_id(self.source_revision)
        if self.verification_method != "UNVERIFIED":
            raise MissionError("CORRECTION_CANDIDATE_IS_NOT_VERIFIED")
        if len(self.candidate.detected_claims) != 1:
            raise MissionError("MINIMAL_SINGLE_CLAIM_REQUIRED")
        if (
            self.candidate.event_id,
            self.candidate.run_id,
            self.candidate.model_binding_id,
        ) != (self.trace.event_id, self.trace.trace_id, self.trace.model_profile_ref):
            raise MissionError("TRACE_BINDING_MISMATCH")
        if set(self.trace.evidence_refs) != set(
            self.candidate.available_evidence_references
        ):
            raise MissionError("EVIDENCE_BINDING_MISMATCH")
        _claim(self.candidate.detected_claims[0].statement)
        _claim(self.candidate.proposed_correction)

    @property
    def applicability(self):
        return self.candidate.detected_claims[0].scope_dimensions

    def audit_decision(self):
        original = _claim(self.candidate.detected_claims[0].statement)
        corrected = _claim(self.candidate.proposed_correction)
        changed = original != corrected
        return {
            "event_id": self.candidate.event_id,
            "trace_id": self.trace.trace_id,
            "candidate_hash": self.candidate.content_hash,
            "delta_id": canonical_sha256(self) if changed else None,
            "status": "CANDIDATE_ONLY" if changed else "NO_CHANGE",
            "equivalence_method": "NFC_AND_OUTER_WHITESPACE_ONLY",
            "verification": "UNVERIFIED",
            "authority": "NONE",
        }


class PheromoneKind(str, Enum):
    VERIFIED_REUSE = "VERIFIED_REUSE"
    USEFUL_PROBE = "USEFUL_PROBE"
    ERROR_RECURRED = "ERROR_RECURRED"
    FAILED_REUSE = "FAILED_REUSE"
    CONFLICT = "CONFLICT"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True, repr=False)
class PheromoneEvent:
    """Scoped advisory trail metadata around an existing ModelExperienceEvent."""

    experience: ModelExperienceEvent
    trail_id: str
    scope: OwnerScope
    trace: MissionTrace
    kind: PheromoneKind
    verifier_ref: str
    source_revision: str
    policy_version: str = "advisory-trail-v1"

    def __post_init__(self):
        if (
            type(self.experience) is not ModelExperienceEvent
            or type(self.kind) is not PheromoneKind
            or type(self.trace) is not MissionTrace
        ):
            raise MissionError("INVALID_PHEROMONE_EVENT")
        _same_owner(self.experience, self.scope)
        for value in (self.trail_id, self.verifier_ref, self.source_revision):
            logical_id(value)
        if self.policy_version != "advisory-trail-v1":
            raise MissionError("UNSUPPORTED_POLICY_VERSION")
        if (
            self.experience.model_experience_event_id,
            self.experience.kernel_run_id,
        ) != (self.trace.event_id, self.trace.trace_id):
            raise MissionError("TRACE_BINDING_MISMATCH")
        assert_model_experience_is_advisory(self.experience)

    @property
    def event_id(self):
        return self.experience.model_experience_event_id

    @property
    def digest(self):
        return canonical_sha256(self)

    @property
    def signal_channel(self):
        # Channels remain distinct; this is categorization, not scoring.
        if self.kind in {PheromoneKind.VERIFIED_REUSE, PheromoneKind.USEFUL_PROBE}:
            return "UTILITY_POSITIVE_CANDIDATE"
        if self.kind is PheromoneKind.ERROR_RECURRED:
            return "RECHECK_SALIENCE_ONLY"
        if self.kind is PheromoneKind.FAILED_REUSE:
            return "UTILITY_NEGATIVE_CANDIDATE"
        return "REUSE_BLOCKED"


@dataclass(frozen=True, slots=True, repr=False)
class PheromoneSnapshotRef:
    snapshot_id: str
    trail_id: str
    scope: OwnerScope
    event_log_watermark: str
    created_at: datetime
    scoring_version: str
    tau_positive_ref: str
    tau_negative_ref: str
    policy_version: str = "advisory-trail-v1"

    def __post_init__(self):
        if (
            type(self.scope) is not OwnerScope
            or self.policy_version != "advisory-trail-v1"
        ):
            raise MissionError("INVALID_SNAPSHOT_REFERENCE")
        for name in (
            "snapshot_id",
            "trail_id",
            "event_log_watermark",
            "scoring_version",
            "tau_positive_ref",
            "tau_negative_ref",
        ):
            logical_id(getattr(self, name))
        if self.tau_positive_ref == self.tau_negative_ref:
            raise MissionError("POSITIVE_NEGATIVE_CHANNELS_MUST_DIFFER")
        object.__setattr__(self, "created_at", ensure_utc(self.created_at))


class VerifiedReusePort(Protocol):
    """Trusted Core-injected verifier seam, not a bool/score from model JSON.

    The future adapter must verify the corrected claim, scope/applicability,
    model-profile binding, freshness/current revocations and referenced receipts.
    No default implementation is supplied in G1. Returning normally attests only
    that advisory reuse checks passed; it never grants action or memory approval.
    """

    def require_verified_reuse(
        self, principal: CorePrincipal, event: PheromoneEvent
    ) -> None: ...


def require_verified_reuse(event, *, core, principal, evidence, verifier):
    if (
        type(event) is not PheromoneEvent
        or type(core) is not CoreAdmission
        or type(evidence) is not CoreEvidenceAdmission
    ):
        raise MissionError("VERIFICATION_UNAVAILABLE")
    core.require(principal, Capability.READ, scope=event.scope)
    if event.kind is not PheromoneKind.VERIFIED_REUSE:
        raise MissionError("REUSE_NOT_VERIFIED")
    refs = id_tuple(event.trace.evidence_refs)
    if not refs or verifier is None:
        raise MissionError("VERIFICATION_UNAVAILABLE")
    for ref in refs:
        record = evidence.require_evidence(principal, ref)
        if record.source.source_version_id != event.source_revision:
            raise MissionError("SOURCE_REVISION_MISMATCH")
    if verifier.require_verified_reuse(principal, event) is not None:
        raise MissionError("INVALID_VERIFIER_RECEIPT")
    # Advisory only. No principal is minted, no store/score/approval is touched.
    return "ADVISORY_REUSE_VERIFIED"


def compare_event_replay(previous, current):
    """Pure replay decision; a future durable store must enforce it atomically."""
    if type(previous) is not PheromoneEvent or type(current) is not PheromoneEvent:
        raise MissionError("INVALID_PHEROMONE_EVENT")
    if (previous.scope, previous.event_id) != (current.scope, current.event_id):
        raise MissionError("IDENTITY_MISMATCH")
    if previous.digest != current.digest:
        raise MissionError("CONFLICT", status="CONFLICT", exit_code=4)
    return "DUPLICATE_NO_DEPOSIT"


def compare_episode_reuse(previous, current):
    """One positive reinforcement per scoped trail/episode, even with new IDs.

    The future ledger must still record every distinct audit/revocation event.
    This decision suppresses a repeated positive deposit, not negative evidence.
    """
    if type(previous) is not PheromoneEvent or type(current) is not PheromoneEvent:
        raise MissionError("INVALID_PHEROMONE_EVENT")
    if (previous.scope, previous.trail_id, previous.trace.episode_id) != (
        current.scope,
        current.trail_id,
        current.trace.episode_id,
    ):
        raise MissionError("IDENTITY_MISMATCH")
    if previous.event_id == current.event_id:
        return compare_event_replay(previous, current)
    return "EPISODE_ALREADY_ACCOUNTED_NO_POSITIVE_DEPOSIT"
