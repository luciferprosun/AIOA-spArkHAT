"""Typed minimal deltas and Core-bound deterministic verification contracts.

DTO construction conveys no authority. Only NativeLearning may persist a delta
after checking current native evidence and the registered independent methods.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
    require_sha256_hex,
)
from runtime.mission.advisory import _claim
from runtime.mission.contracts import MissionError, bounded_int, id_tuple, logical_id


class DeltaStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SUPPORTED = "SUPPORTED"
    VERIFIED = "VERIFIED"
    CONTESTED = "CONTESTED"
    DEPRECATED = "DEPRECATED"
    SUPERSEDED = "SUPERSEDED"


class PrivacyScope(str, Enum):
    PRIVATE = "PRIVATE"
    TEAM = "TEAM"
    PUBLIC = "PUBLIC"


@dataclass(frozen=True, slots=True)
class ModelIdentity:
    provider: str
    model_id: str
    version: str
    family: str
    fingerprint: str = field(init=False)

    def __post_init__(self):
        for name in ("provider", "model_id", "version", "family"):
            value = getattr(self, name)
            if type(value) is not str or not value or len(value.encode()) > 256:
                raise MissionError("MODEL_IDENTITY_REQUIRED")
        object.__setattr__(
            self, "fingerprint", canonical_sha256(self, exclude_fields=("fingerprint",))
        )


@dataclass(frozen=True, slots=True)
class LearningPolicy:
    owner_scope: OwnerScope
    domain_hat: str
    task_signature: str
    task_instruction: str
    source_ids: tuple[str, ...]
    actor: ModelIdentity
    verifier_refs: tuple[str, ...]
    policy_version: str = "native-epistemic-delta-v1"
    privacy_scope: PrivacyScope = PrivacyScope.PRIVATE
    maximum_records: int = 128
    validity_seconds: int = 3600
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.owner_scope) is not OwnerScope
            or type(self.actor) is not ModelIdentity
        ):
            raise MissionError("INVALID_LEARNING_POLICY")
        if (
            self.privacy_scope is not PrivacyScope.PRIVATE
            or self.policy_version != "native-epistemic-delta-v1"
        ):
            raise MissionError("PRIVATE_ADVISORY_POLICY_REQUIRED")
        for value in (self.domain_hat, self.task_signature):
            logical_id(value)
        if len(_claim(self.task_instruction).encode()) > 2048:
            raise MissionError("TASK_TOO_LARGE")
        object.__setattr__(self, "source_ids", id_tuple(self.source_ids, maximum=8))
        object.__setattr__(
            self, "verifier_refs", id_tuple(self.verifier_refs, maximum=8)
        )
        if not self.source_ids or len(self.verifier_refs) < 2:
            raise MissionError("INDEPENDENT_VERIFIERS_REQUIRED")
        bounded_int(self.maximum_records, 8, 512)
        bounded_int(self.validity_seconds, 1, 86400)
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    @property
    def knowledge_digest(self):
        # Actor attribution belongs to the overlay, not canonical applicability.
        return canonical_sha256(self, exclude_fields=("actor", "digest"))


@dataclass(frozen=True, slots=True)
class VerificationInput:
    scope: OwnerScope
    domain_hat: str
    task_signature: str
    claim: str
    # Bytes and source/version identities already admitted by Core, not model citations.
    sources: tuple[tuple[str, str, str, str], ...]
    at: datetime
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.scope) is not OwnerScope
            or type(self.sources) is not tuple
            or not self.sources
        ):
            raise MissionError("EVIDENCE_REQUIRED")
        object.__setattr__(self, "claim", _claim(self.claim))
        object.__setattr__(self, "at", ensure_utc(self.at))
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )


@dataclass(frozen=True, slots=True)
class VerificationVerdict:
    input_digest: str
    supported: bool

    def __post_init__(self):
        require_sha256_hex(self.input_digest, "verification input")
        if type(self.supported) is not bool:
            raise MissionError("INVALID_VERIFIER_RESULT")


@dataclass(frozen=True, slots=True)
class CoreVerifierBinding:
    verifier_ref: str
    verifier_method: str
    source_family: str
    verifier: object

    def __post_init__(self):
        for value in (self.verifier_ref, self.verifier_method, self.source_family):
            logical_id(value)
        if not callable(getattr(self.verifier, "verify", None)):
            raise MissionError("VERIFIER_UNAVAILABLE")


@dataclass(frozen=True, slots=True)
class EvidenceLiteralVerifier:
    """A domain rule: the complete atomic claim must equal one admitted source.

    The host decides which source ids are authoritative for this task. This is
    not a general natural-language entailment or signature-means-truth claim.
    """

    def verify(self, request: VerificationInput):
        return VerificationVerdict(
            request.digest,
            any(_claim(row[3]) == request.claim for row in request.sources),
        )


@dataclass(frozen=True, slots=True)
class RegisteredRuleVerifier:
    """Separate Core-reviewed oracle, bound to exact task and source versions.

    No default oracle is supplied. Its registry is local trusted policy and
    cannot be populated from actor/critic text or retrieved instructions.
    """

    scope: OwnerScope
    task_signature: str
    expected_claim: str
    source_versions: tuple[tuple[str, str], ...]
    valid_until: datetime

    def verify(self, request: VerificationInput):
        valid = (
            request.scope == self.scope
            and request.task_signature == self.task_signature
            and request.claim == _claim(self.expected_claim)
            and tuple(sorted((row[0], row[1]) for row in request.sources))
            == tuple(sorted(self.source_versions))
            and request.at < ensure_utc(self.valid_until)
        )
        return VerificationVerdict(request.digest, valid)


@dataclass(frozen=True, slots=True)
class VerifierReceipt:
    verifier_ref: str
    verifier_method: str
    source_family: str
    input_digest: str
    supported: bool

    def __post_init__(self):
        for value in (self.verifier_ref, self.verifier_method, self.source_family):
            logical_id(value)
        require_sha256_hex(self.input_digest, "verification receipt")
        if type(self.supported) is not bool:
            raise MissionError("INVALID_VERIFIER_RESULT")


@dataclass(frozen=True, slots=True, repr=False)
class EpistemicDelta:
    delta_id: str
    scope: OwnerScope
    domain_hat: str
    model: ModelIdentity
    task_signature: str
    original_claim: str
    verified_claim: str
    delta_patch: tuple[str, str]
    error_type: str
    evidence_refs: tuple[str, ...]
    source_versions: tuple[tuple[str, str], ...]
    verifier_set: tuple[VerifierReceipt, ...]
    consensus_score: float
    status: DeltaStatus
    privacy_scope: PrivacyScope
    valid_from: datetime
    valid_until: datetime
    supersedes: tuple[str, ...]
    created_at: datetime
    last_seen_at: datetime
    last_used_at: datetime | None
    native_candidate_hash: str
    cpl_trace_ref: str
    policy_digest: str
    execution_authority: bool = field(default=False, init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope or type(self.model) is not ModelIdentity:
            raise MissionError("INVALID_DELTA")
        if (
            type(self.status) is not DeltaStatus
            or type(self.privacy_scope) is not PrivacyScope
        ):
            raise MissionError("INVALID_DELTA")
        for value in (self.delta_id, self.native_candidate_hash, self.policy_digest):
            require_sha256_hex(value, "delta identity")
        if (
            self.original_claim != _claim(self.original_claim)
            or self.verified_claim != _claim(self.verified_claim)
            or self.original_claim == self.verified_claim
            or self.delta_patch != (self.original_claim, self.verified_claim)
        ):
            raise MissionError("MINIMAL_DELTA_REQUIRED")
        if (
            not self.evidence_refs
            or not self.source_versions
            or len(self.verifier_set) > 8
        ):
            raise MissionError("DELTA_EVIDENCE_REQUIRED")
        if any(type(v) is not VerifierReceipt for v in self.verifier_set):
            raise MissionError("INVALID_VERIFIER_RESULT")
        if (
            type(self.consensus_score) not in (float, int)
            or not 0 <= self.consensus_score <= 1
        ):
            raise MissionError("INVALID_CONSENSUS")
        for name in (
            "valid_from",
            "valid_until",
            "created_at",
            "last_seen_at",
            "last_used_at",
        ):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, ensure_utc(getattr(self, name)))
        if self.valid_until <= self.valid_from or self.last_seen_at < self.created_at:
            raise MissionError("INVALID_DELTA_TIME")

    def private_payload(self):
        return json.loads(canonical_json_bytes(self))

    @classmethod
    def restore(cls, raw):
        value = json.loads(canonical_json_bytes(raw))
        if value.pop("execution_authority", None) is not False:
            raise MissionError("ADVISORY_ONLY")
        value["scope"] = OwnerScope(**value["scope"])
        model = value["model"]
        digest = model.pop("fingerprint")
        value["model"] = ModelIdentity(**model)
        if value["model"].fingerprint != digest:
            raise MissionError("MODEL_IDENTITY_REQUIRED")
        value["status"] = DeltaStatus(value["status"])
        value["privacy_scope"] = PrivacyScope(value["privacy_scope"])
        for name in ("delta_patch", "evidence_refs", "supersedes"):
            value[name] = tuple(value[name])
        value["source_versions"] = tuple(tuple(row) for row in value["source_versions"])
        value["verifier_set"] = tuple(
            VerifierReceipt(**row) for row in value["verifier_set"]
        )
        for name in (
            "valid_from",
            "valid_until",
            "created_at",
            "last_seen_at",
            "last_used_at",
        ):
            if value[name] is not None:
                value[name] = datetime.fromisoformat(value[name].replace("Z", "+00:00"))
        return cls(**value)
