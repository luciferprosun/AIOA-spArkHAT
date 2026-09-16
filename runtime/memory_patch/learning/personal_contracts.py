"""Owner-bound opt-in contracts; metadata and model text convey no authority."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256, ensure_utc
from runtime.mission.advisory import _claim
from runtime.mission.contracts import MissionError, bounded_int, id_tuple, logical_id


class ConsentMode(str, Enum):
    OFF = "OFF"
    MANUAL = "MANUAL"
    AUTO_VERIFIED_SCOPED = "AUTO_VERIFIED_SCOPED"


class CorrectionMode(str, Enum):
    CPL_ONLY = "CPL_ONLY"
    HAT_ONLY = "HAT_ONLY"
    HYBRID = "HYBRID"

    @property
    def requires_critics(self):
        return self is not CorrectionMode.HAT_ONLY


class SemanticDeltaKind(str, Enum):
    REPLACE = "REPLACE"
    ADD_MISSING_CONDITION = "ADD_MISSING_CONDITION"
    QUALIFY = "QUALIFY"
    RETRACT = "RETRACT"


class TagKind(str, Enum):
    DOMAIN = "DOMAIN"
    TASK_FAMILY = "TASK_FAMILY"
    ERROR_CLASS = "ERROR_CLASS"
    SOURCE_FAMILY = "SOURCE_FAMILY"
    TEMPORAL_SCOPE = "TEMPORAL_SCOPE"
    VERIFICATION_CLASS = "VERIFICATION_CLASS"
    RISK_CLASS = "RISK_CLASS"
    CORRECTION_TYPE = "CORRECTION_TYPE"


@dataclass(frozen=True, slots=True)
class DeltaTag:
    kind: TagKind
    value: str

    def __post_init__(self):
        if type(self.kind) is not TagKind:
            raise MissionError("INVALID_DELTA_TAG")
        logical_id(self.value)
        if len(self.value.encode()) > 128:
            raise MissionError("DELTA_TAG_BUDGET")


def validate_tags(tags):
    if (
        type(tags) is not tuple
        or len(tags) > 8
        or any(type(t) is not DeltaTag for t in tags)
        or len({t.kind for t in tags}) != len(tags)
    ):
        raise MissionError("INVALID_DELTA_TAGS")
    return tags


@dataclass(frozen=True, slots=True, repr=False)
class DomainSemantics:
    """Finite Core-reviewed aliases; no fuzzy matching or entailment oracle.

    Aliases interpret an input claim. The canonical claim must still pass all
    independent NativeLearning verifiers against current admitted evidence.
    Neither a tag nor an alias registration constitutes factual support.
    """

    scope: OwnerScope
    domain_hat: str
    task_signature: str
    source_versions: tuple[tuple[str, str], ...]
    valid_until: datetime
    aliases: tuple[tuple[str, str], ...] = ()
    delta_kind: SemanticDeltaKind = SemanticDeltaKind.REPLACE
    required_condition: str | None = None
    tags: tuple[DeltaTag, ...] = ()
    digest: str = field(init=False)

    def __post_init__(self):
        if (
            type(self.scope) is not OwnerScope
            or type(self.delta_kind) is not SemanticDeltaKind
        ):
            raise MissionError("INVALID_DOMAIN_SEMANTICS")
        for value in (self.domain_hat, self.task_signature):
            logical_id(value)
        if (
            type(self.source_versions) is not tuple
            or not 1 <= len(self.source_versions) <= 8
            or any(type(p) is not tuple or len(p) != 2 for p in self.source_versions)
            or len(set(self.source_versions)) != len(self.source_versions)
        ):
            raise MissionError("INVALID_DOMAIN_SEMANTICS")
        for pair in self.source_versions:
            for value in pair:
                logical_id(value)
        if type(self.aliases) is not tuple or len(self.aliases) > 16:
            raise MissionError("INVALID_DOMAIN_EQUIVALENCE")
        for pair in self.aliases:
            if (
                type(pair) is not tuple
                or len(pair) != 2
                or any(v != _claim(v) for v in pair)
            ):
                raise MissionError("INVALID_DOMAIN_EQUIVALENCE")
        keys = {p[0] for p in self.aliases}
        if len(keys) != len(self.aliases) or any(p[1] in keys for p in self.aliases):
            raise MissionError("DOMAIN_EQUIVALENCE_CHAIN_DENIED")
        if self.required_condition is not None:
            object.__setattr__(
                self, "required_condition", _claim(self.required_condition)
            )
        if (
            self.delta_kind
            in {SemanticDeltaKind.ADD_MISSING_CONDITION, SemanticDeltaKind.QUALIFY}
            and not self.required_condition
        ):
            raise MissionError("SEMANTIC_CONDITION_REQUIRED")
        validate_tags(self.tags)
        object.__setattr__(self, "valid_until", ensure_utc(self.valid_until))
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    def canonical_claim(self, claim, *, scope, hat, task, versions, at):
        value = _claim(claim)
        if (
            scope != self.scope
            or hat != self.domain_hat
            or task != self.task_signature
            or tuple(sorted(versions)) != tuple(sorted(self.source_versions))
            or ensure_utc(at) >= self.valid_until
        ):
            # A stale rule cannot interpret an alias, even if a model agrees.
            raise MissionError("DOMAIN_EQUIVALENCE_NOT_APPLICABLE")
        return dict(self.aliases).get(value, value)


@dataclass(frozen=True, slots=True, repr=False)
class PersonalDeltaPolicy:
    scope: OwnerScope
    allowed_domain_hats: tuple[str, ...]
    consent_anchor_hat: str
    semantics: DomainSemantics | None = None
    policy_version: str = "owner-personal-delta-v1"
    history_policy: str = "RETAIN_OWNER_AUDIT_HIDE_WHEN_OFF"
    maximum_learning_bytes: int = 262144
    digest: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope:
            raise MissionError("INVALID_PERSONAL_DELTA_POLICY")
        hats = id_tuple(self.allowed_domain_hats, maximum=8)
        if not hats or self.consent_anchor_hat not in hats:
            raise MissionError("CONSENT_HAT_BINDING_REQUIRED")
        if self.semantics is not None and (
            type(self.semantics) is not DomainSemantics
            or self.semantics.scope != self.scope
            or self.semantics.domain_hat not in hats
        ):
            raise MissionError("INVALID_DOMAIN_SEMANTICS")
        if (
            self.policy_version != "owner-personal-delta-v1"
            or self.history_policy != "RETAIN_OWNER_AUDIT_HIDE_WHEN_OFF"
        ):
            raise MissionError("UNSUPPORTED_PERSONAL_HISTORY_POLICY")
        object.__setattr__(self, "allowed_domain_hats", hats)
        bounded_int(self.maximum_learning_bytes, 1024, 4194304)
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    @property
    def personal_space_ref(self):
        # Core's existing default space/slot, not a second HAT or database.
        return "personal-delta-" + canonical_sha256(self.scope)

    @property
    def consent_ref(self):
        return "consent-" + canonical_sha256(self.scope)


@dataclass(frozen=True, slots=True)
class ActorRepairBudget:
    maximum_attempts: int = 1

    def __post_init__(self):
        if type(self.maximum_attempts) is not int or self.maximum_attempts != 1:
            raise MissionError("ACTOR_REPAIR_LIMIT_MUST_BE_ONE")
