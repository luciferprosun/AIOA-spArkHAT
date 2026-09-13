"""Reviewed pure domain semantics with native, inert dependencies."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from runtime.memory_patch.contracts.enums import (
    EvidenceStatus,
    MemoryTargetScope,
    StableStringEnum,
)
from runtime.memory_patch.contracts.records import (
    EvidenceBundleItem,
    verify_bundle_item_hash,
)
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    ensure_utc,
    freeze_json,
    require_sha256_hex,
)
from runtime.memory_patch.errors import (
    ContractValidationError,
    ErrorCode,
    IntegrityError,
    MemoryPatchError,
)
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle
from runtime.memory_patch.source_lineage import (
    SourceAccessClass,
    SourceAuthorityLevel,
    SourcePublicationState,
)

TEMPORAL_POLICY_ID = "temporal-resolution-policy-1a"
TEMPORAL_POLICY_VERSION = "1"
FRESHNESS_POLICY_SCHEMA_VERSION = "1.0.0"
TEMPORAL_FACTS_DIGEST_SCHEME = "step21-canonical-temporal-facts-1a"
MAX_TEMPORAL_CANDIDATES = 80
MAX_POLICY_SOURCE_KINDS = 64
MAX_FRESHNESS_SECONDS = 10 * 365 * 24 * 60 * 60


class TemporalQueryMode(StableStringEnum):
    CURRENT = "CURRENT"
    AS_OF = "AS_OF"
    FUTURE = "FUTURE"
    UNSPECIFIED = "UNSPECIFIED"


class TemporalApplicability(StableStringEnum):
    APPLICABLE = "APPLICABLE"
    NOT_YET_APPLICABLE = "NOT_YET_APPLICABLE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class FreshnessStatus(StableStringEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SupersessionStatus(StableStringEnum):
    NOT_SUPERSEDED = "NOT_SUPERSEDED"
    SUPERSEDED = "SUPERSEDED"
    AMBIGUOUS = "AMBIGUOUS"
    CYCLIC = "CYCLIC"
    UNKNOWN = "UNKNOWN"


class Step21ReasonCode(StableStringEnum):
    TEMPORAL_OK = "TEMPORAL_OK"
    NO_HAT_SELECTED = "NO_HAT_SELECTED"
    AMBIGUOUS_ROUTE = "AMBIGUOUS_ROUTE"
    STEP20_INPUT_HASH_INVALID = "STEP20_INPUT_HASH_INVALID"
    STEP20_INPUT_BINDING_MISMATCH = "STEP20_INPUT_BINDING_MISMATCH"
    TEMPORAL_SCOPE_MISMATCH = "TEMPORAL_SCOPE_MISMATCH"
    CURRENT_TIME_BOUND = "CURRENT_TIME_BOUND"
    EXPLICIT_AS_OF_BOUND = "EXPLICIT_AS_OF_BOUND"
    FUTURE_AS_OF_BOUND = "FUTURE_AS_OF_BOUND"
    AS_OF_UNSPECIFIED = "AS_OF_UNSPECIFIED"
    EFFECTIVE_AT_AS_OF = "EFFECTIVE_AT_AS_OF"
    NOT_YET_EFFECTIVE = "NOT_YET_EFFECTIVE"
    EFFECTIVE_PERIOD_EXPIRED = "EFFECTIVE_PERIOD_EXPIRED"
    SUPERSEDED_AT_AS_OF = "SUPERSEDED_AT_AS_OF"
    SUPERSESSION_AMBIGUOUS = "SUPERSESSION_AMBIGUOUS"
    SUPERSESSION_CYCLE = "SUPERSESSION_CYCLE"
    TEMPORAL_FACTS_MISSING = "TEMPORAL_FACTS_MISSING"
    TEMPORAL_FACTS_INVALID = "TEMPORAL_FACTS_INVALID"
    TEMPORAL_FACTS_DIGEST_INVALID = "TEMPORAL_FACTS_DIGEST_INVALID"
    TEMPORAL_FACTS_DIGEST_PRESERVED = "TEMPORAL_FACTS_DIGEST_PRESERVED"
    FRESHNESS_POLICY_MISSING = "FRESHNESS_POLICY_MISSING"
    FRESHNESS_FACT_MISSING = "FRESHNESS_FACT_MISSING"
    FRESHNESS_FACT_IN_FUTURE = "FRESHNESS_FACT_IN_FUTURE"
    EVIDENCE_FRESH = "EVIDENCE_FRESH"
    EVIDENCE_STALE = "EVIDENCE_STALE"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    INDEPENDENT_SUPPORT = "INDEPENDENT_SUPPORT"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    NO_APPLICABLE_EVIDENCE = "NO_APPLICABLE_EVIDENCE"
    COMPLETENESS_FALLBACK_ATTEMPTED = "COMPLETENESS_FALLBACK_ATTEMPTED"
    COMPLETENESS_FALLBACK_ADMITTED = "COMPLETENESS_FALLBACK_ADMITTED"
    COMPLETENESS_FALLBACK_EXHAUSTED = "COMPLETENESS_FALLBACK_EXHAUSTED"
    STEP20_COVERAGE_PARTIAL = "STEP20_COVERAGE_PARTIAL"
    EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    EVIDENCE_CONFLICTING = "EVIDENCE_CONFLICTING"
    EVIDENCE_INVALID = "EVIDENCE_INVALID"


class TemporalBoundaryError(RuntimeError):
    """Sanitized fail-closed error at the Step 21 boundary."""

    def __init__(self, reason_code: Step21ReasonCode) -> None:
        if not isinstance(reason_code, Step21ReasonCode):
            raise TypeError("reason_code must be a Step21ReasonCode")
        super().__init__(f"Step 21 temporal resolution denied: {reason_code.value}")
        self.reason_code = reason_code
        self.evidence_status = EvidenceStatus.INVALID


_CONTROL = re.compile("[\\x00-\\x1f\\x7f]")
_DOMAIN_ID = re.compile("^[a-z0-9][a-z0-9._-]{0,127}$")


def _text(value: object, field_name: str, maximum_bytes: int = 1024) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ContractValidationError(f"{field_name} must be canonical text")
    if unicodedata.normalize("NFC", value) != value or _CONTROL.search(value):
        raise ContractValidationError(f"{field_name} must be NFC without controls")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ContractValidationError(f"{field_name} exceeds its byte limit")
    return value


def _optional_text(
    value: object | None, field_name: str, maximum_bytes: int = 1024
) -> str | None:
    return None if value is None else _text(value, field_name, maximum_bytes)


def _domain_id(value: object, field_name: str) -> str:
    text = _text(value, field_name, 128)
    if _DOMAIN_ID.fullmatch(text) is None:
        raise ContractValidationError(f"{field_name} is not a logical identifier")
    return text


def _reason_tuple(value: object) -> tuple[Step21ReasonCode, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError("reason_codes must be ordered")
    if any((not isinstance(item, Step21ReasonCode) for item in value)):
        raise ContractValidationError("reason_codes must use Step21ReasonCode")
    return tuple(sorted(set(value), key=lambda item: item.value))


def _string_tuple(value: object, field_name: str, *, maximum: int) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise ContractValidationError(f"{field_name} must be ordered")
    result = tuple(sorted(set(value)))
    if len(result) > maximum or any((not isinstance(item, str) for item in result)):
        raise ContractValidationError(f"{field_name} is invalid")
    for item in result:
        _text(item, field_name, 512)
    return result


def _hash_tuple(value: object, field_name: str, maximum: int) -> tuple[str, ...]:
    result = _string_tuple(value, field_name, maximum=maximum)
    for digest in result:
        require_sha256_hex(digest, field_name)
    return result


@dataclass(frozen=True, slots=True)
class TemporalPolicy:
    policy_id: str = field(init=False, default=TEMPORAL_POLICY_ID)
    policy_version: str = field(init=False, default=TEMPORAL_POLICY_VERSION)
    interval_start_inclusive: bool = field(init=False, default=True)
    interval_end_exclusive: bool = field(init=False, default=True)
    source_operational_time_is_legal_time: bool = field(init=False, default=False)
    step20_rank_overrides_temporal_policy: bool = field(init=False, default=False)
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "policy_digest",
            canonical_sha256(self, exclude_fields=("policy_digest",)),
        )


@dataclass(frozen=True, slots=True)
class FreshnessPolicy:
    policy_id: str
    policy_version: str
    maximum_age_seconds_by_source_kind: Mapping[str, int]
    observation_precedence: tuple[str, ...] = (
        "verified_at",
        "retrieved_at",
        "source_observed_at",
        "snapshot_captured_at",
        "published_at",
    )
    schema_version: str = FRESHNESS_POLICY_SCHEMA_VERSION
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        _domain_id(self.policy_id, "freshness policy_id")
        _text(self.policy_version, "freshness policy_version", 64)
        if self.schema_version != FRESHNESS_POLICY_SCHEMA_VERSION:
            raise ContractValidationError("unsupported freshness policy schema")
        if not isinstance(self.maximum_age_seconds_by_source_kind, Mapping):
            raise ContractValidationError("freshness thresholds must be a mapping")
        if len(self.maximum_age_seconds_by_source_kind) > MAX_POLICY_SOURCE_KINDS:
            raise ContractValidationError("too many freshness source profiles")
        thresholds: dict[str, int] = {}
        for source_kind, seconds in self.maximum_age_seconds_by_source_kind.items():
            _text(source_kind, "freshness source_kind", 1024)
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int)
                or (not 1 <= seconds <= MAX_FRESHNESS_SECONDS)
            ):
                raise ContractValidationError("freshness threshold is outside policy")
            thresholds[source_kind] = seconds
        object.__setattr__(
            self,
            "maximum_age_seconds_by_source_kind",
            freeze_json(dict(sorted(thresholds.items()))),
        )
        if not isinstance(self.observation_precedence, (tuple, list)):
            raise ContractValidationError("observation_precedence must be ordered")
        precedence = tuple(self.observation_precedence)
        if len(precedence) > 8 or len(precedence) != len(set(precedence)):
            raise ContractValidationError("freshness observation precedence is invalid")
        for value in precedence:
            _text(value, "observation_precedence", 64)
        allowed = {
            "verified_at",
            "retrieved_at",
            "source_observed_at",
            "snapshot_captured_at",
            "published_at",
        }
        if not set(precedence) <= allowed:
            raise ContractValidationError("freshness observation precedence is invalid")
        object.__setattr__(self, "observation_precedence", precedence)
        object.__setattr__(
            self,
            "policy_digest",
            canonical_sha256(self, exclude_fields=("policy_digest",)),
        )


def load_temporal_policy() -> TemporalPolicy:
    return TemporalPolicy()


@dataclass(frozen=True, slots=True)
class TemporalFacts:
    published_at: datetime | None = None
    promulgated_at: datetime | None = None
    adopted_at: datetime | None = None
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    applicable_from: datetime | None = None
    applicable_to: datetime | None = None
    decision_date: datetime | None = None
    retrieved_at: datetime | None = None
    ingested_at: datetime | None = None
    verified_at: datetime | None = None
    source_observed_at: datetime | None = None
    snapshot_captured_at: datetime | None = None
    superseded_at: datetime | None = None
    version_status: str | None = None
    consolidation_status: str | None = None
    document_identity: str | None = None
    version_identity: str | None = None
    official_identifier: str | None = None
    provision_identifier: str | None = None
    supersedes: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()
    source_temporal_facts_digest: str | None = None
    source_digest_scheme: str | None = None
    applicability_facts_hash: str = field(init=False)
    facts_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "published_at",
            "promulgated_at",
            "adopted_at",
            "effective_from",
            "effective_to",
            "applicable_from",
            "applicable_to",
            "decision_date",
            "retrieved_at",
            "ingested_at",
            "verified_at",
            "source_observed_at",
            "snapshot_captured_at",
            "superseded_at",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))
        for name in (
            "version_status",
            "consolidation_status",
            "document_identity",
            "version_identity",
            "official_identifier",
            "provision_identifier",
            "source_digest_scheme",
        ):
            object.__setattr__(
                self, name, _optional_text(getattr(self, name), name, 512)
            )
        object.__setattr__(
            self, "supersedes", _string_tuple(self.supersedes, "supersedes", maximum=32)
        )
        object.__setattr__(
            self,
            "superseded_by",
            _string_tuple(self.superseded_by, "superseded_by", maximum=32),
        )
        if self.source_temporal_facts_digest is not None:
            require_sha256_hex(
                self.source_temporal_facts_digest, "source_temporal_facts_digest"
            )
        object.__setattr__(
            self,
            "applicability_facts_hash",
            canonical_sha256(
                {
                    "published_at": self.published_at,
                    "promulgated_at": self.promulgated_at,
                    "adopted_at": self.adopted_at,
                    "effective_from": self.effective_from,
                    "effective_to": self.effective_to,
                    "applicable_from": self.applicable_from,
                    "applicable_to": self.applicable_to,
                    "decision_date": self.decision_date,
                    "superseded_at": self.superseded_at,
                    "version_status": self.version_status,
                    "consolidation_status": self.consolidation_status,
                    "supersedes": self.supersedes,
                    "superseded_by": self.superseded_by,
                }
            ),
        )
        object.__setattr__(
            self,
            "facts_hash",
            canonical_sha256(
                self,
                exclude_fields=(
                    "facts_hash",
                    "applicability_facts_hash",
                    "source_temporal_facts_digest",
                    "source_digest_scheme",
                    "document_identity",
                    "version_identity",
                    "official_identifier",
                    "provision_identifier",
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class TemporalConflictGroup:
    logical_subject_identity: str
    candidate_item_hashes: tuple[str, ...]
    reason_codes: tuple[Step21ReasonCode, ...]
    conflict_group_id: str = field(init=False)
    conflict_group_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.logical_subject_identity, "logical_subject_identity", 512)
        hashes = _hash_tuple(
            self.candidate_item_hashes, "candidate_item_hashes", MAX_TEMPORAL_CANDIDATES
        )
        if len(hashes) < 2:
            raise ContractValidationError("a conflict group requires two candidates")
        object.__setattr__(self, "candidate_item_hashes", hashes)
        object.__setattr__(self, "reason_codes", _reason_tuple(self.reason_codes))
        digest = canonical_sha256(
            {
                "logical_subject_identity": self.logical_subject_identity,
                "candidate_item_hashes": hashes,
                "reason_codes": self.reason_codes,
            }
        )
        object.__setattr__(self, "conflict_group_hash", digest)
        object.__setattr__(self, "conflict_group_id", f"temporal-conflict:{digest}")


def verify_conflict_group_hash(value: TemporalConflictGroup) -> None:
    expected = canonical_sha256(
        {
            "logical_subject_identity": value.logical_subject_identity,
            "candidate_item_hashes": value.candidate_item_hashes,
            "reason_codes": value.reason_codes,
        }
    )
    if (
        value.conflict_group_hash != expected
        or value.conflict_group_id != f"temporal-conflict:{expected}"
    ):
        raise IntegrityError("temporal conflict group hash mismatch")


_DATE = re.compile("^\\d{4}-\\d{2}-\\d{2}$")
_TIME_FIELDS = (
    "published_at",
    "promulgated_at",
    "adopted_at",
    "effective_from",
    "effective_to",
    "applicable_from",
    "applicable_to",
    "decision_date",
    "retrieved_at",
    "ingested_at",
    "verified_at",
    "source_observed_at",
    "snapshot_captured_at",
    "superseded_at",
)


@dataclass(frozen=True, slots=True)
class CandidateTemporalState:
    bundle_hash: str
    item: EvidenceBundleItem
    facts: TemporalFacts
    logical_subject_identity: str
    applicability: TemporalApplicability
    supersession_status: SupersessionStatus
    freshness_status: FreshnessStatus
    conflict_group_id: str | None
    integrity_valid: bool
    reasons: tuple[Step21ReasonCode, ...]

    @property
    def version_identity(self) -> str:
        return self.facts.version_identity or self.item.identity.knowledge_version_id


def _instant(value: object, field_name: str) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return ensure_utc(value, field_name)
    if not isinstance(value, str) or value != value.strip():
        raise ValueError(f"{field_name} is not a canonical timestamp")
    if _DATE.fullmatch(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(candidate)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} lacks an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _relations(value: object) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (tuple, list)):
        values = tuple(value)
    else:
        raise ValueError("supersession relation must be text or an ordered list")
    if any((not isinstance(item, str) or not item.strip() for item in values)):
        raise ValueError("supersession relation contains an invalid identity")
    return tuple(sorted(set(values)))


def _metadata_mapping(item: EvidenceBundleItem) -> Mapping[str, object]:
    nested = item.structured_metadata.get("temporal_facts")
    if nested is None:
        return item.structured_metadata
    if not isinstance(nested, Mapping):
        raise ValueError("temporal_facts must be a mapping")
    return nested


def extract_temporal_facts(
    item: EvidenceBundleItem,
) -> tuple[TemporalFacts, tuple[Step21ReasonCode, ...], bool]:
    """Decode only explicit, bounded temporal metadata without inference."""
    metadata = item.structured_metadata
    try:
        temporal = _metadata_mapping(item)
        values = {name: _instant(temporal.get(name), name) for name in _TIME_FIELDS}
        source_digest = metadata.get(
            "temporal_facts_digest", temporal.get("temporal_facts_digest")
        )
        digest_scheme = metadata.get(
            "temporal_facts_digest_scheme", temporal.get("temporal_facts_digest_scheme")
        )
        facts = TemporalFacts(
            **values,
            version_status=str(temporal["version_status"])
            if temporal.get("version_status") not in (None, "")
            else str(metadata["version_status"])
            if metadata.get("version_status") not in (None, "")
            else None,
            consolidation_status=str(temporal["consolidation_status"])
            if temporal.get("consolidation_status") not in (None, "")
            else str(metadata["consolidation_status"])
            if metadata.get("consolidation_status") not in (None, "")
            else None,
            document_identity=str(metadata["document_identity"])
            if metadata.get("document_identity") not in (None, "")
            else None,
            version_identity=str(metadata["version_identity"])
            if metadata.get("version_identity") not in (None, "")
            else None,
            official_identifier=str(metadata["official_identifier"])
            if metadata.get("official_identifier") not in (None, "")
            else None,
            provision_identifier=str(metadata["provision_identifier"])
            if metadata.get("provision_identifier") not in (None, "")
            else None,
            supersedes=_relations(
                temporal.get("supersedes", metadata.get("supersedes"))
            ),
            superseded_by=_relations(
                temporal.get("superseded_by", metadata.get("superseded_by"))
            ),
            source_temporal_facts_digest=str(source_digest)
            if source_digest not in (None, "")
            else None,
            source_digest_scheme=str(digest_scheme)
            if digest_scheme not in (None, "")
            else None,
        )
    except (TypeError, ValueError) as exc:
        del exc
        fallback = TemporalFacts(
            document_identity=str(metadata["document_identity"])
            if isinstance(metadata.get("document_identity"), str)
            else None,
            version_identity=str(metadata["version_identity"])
            if isinstance(metadata.get("version_identity"), str)
            else None,
            official_identifier=str(metadata["official_identifier"])
            if isinstance(metadata.get("official_identifier"), str)
            else None,
            provision_identifier=str(metadata["provision_identifier"])
            if isinstance(metadata.get("provision_identifier"), str)
            else None,
        )
        return (fallback, (Step21ReasonCode.TEMPORAL_FACTS_INVALID,), False)
    if facts.source_digest_scheme == TEMPORAL_FACTS_DIGEST_SCHEME:
        if facts.source_temporal_facts_digest != facts.facts_hash:
            return (facts, (Step21ReasonCode.TEMPORAL_FACTS_DIGEST_INVALID,), False)
        digest_reasons: tuple[Step21ReasonCode, ...] = ()
    elif facts.source_temporal_facts_digest is not None:
        digest_reasons = (Step21ReasonCode.TEMPORAL_FACTS_DIGEST_PRESERVED,)
    else:
        digest_reasons = ()
    return (facts, digest_reasons, True)


def logical_subject_identity(item: EvidenceBundleItem, facts: TemporalFacts) -> str:
    document = (
        facts.document_identity or facts.official_identifier or item.identity.source_id
    )
    provision = facts.provision_identifier or item.identity.chunk_id
    digest = canonical_sha256(
        {
            "document_identity": document,
            "provision_identity": provision,
            "effective_scope": item.effective_scope,
        }
    )
    return f"temporal-subject:{digest}"


def _base_applicability(
    facts: TemporalFacts, as_of: datetime
) -> tuple[TemporalApplicability, SupersessionStatus, tuple[Step21ReasonCode, ...]]:
    intervals = (
        (facts.effective_from, facts.effective_to),
        (facts.applicable_from, facts.applicable_to),
    )
    if any(
        (
            start is not None and end is not None and (start > end)
            for start, end in intervals
        )
    ):
        return (
            TemporalApplicability.CONFLICTING,
            SupersessionStatus.AMBIGUOUS,
            (Step21ReasonCode.TEMPORAL_FACTS_INVALID,),
        )
    starts = tuple(
        (
            value
            for value in (facts.effective_from, facts.applicable_from)
            if value is not None
        )
    )
    ends = tuple(
        (
            value
            for value in (facts.effective_to, facts.applicable_to)
            if value is not None
        )
    )
    if starts and as_of < max(starts):
        return (
            TemporalApplicability.NOT_YET_APPLICABLE,
            SupersessionStatus.NOT_SUPERSEDED,
            (Step21ReasonCode.NOT_YET_EFFECTIVE,),
        )
    if ends and as_of >= min(ends):
        return (
            TemporalApplicability.EXPIRED,
            SupersessionStatus.NOT_SUPERSEDED,
            (Step21ReasonCode.EFFECTIVE_PERIOD_EXPIRED,),
        )
    if facts.superseded_at is not None and as_of >= facts.superseded_at:
        return (
            TemporalApplicability.SUPERSEDED,
            SupersessionStatus.SUPERSEDED,
            (Step21ReasonCode.SUPERSEDED_AT_AS_OF,),
        )
    status = (facts.version_status or "").upper()
    if status in {"REPEALED", "EXPIRED"}:
        if facts.superseded_at is None:
            return (
                TemporalApplicability.UNKNOWN,
                SupersessionStatus.UNKNOWN,
                (Step21ReasonCode.TEMPORAL_FACTS_MISSING,),
            )
    if (
        status == "SUPERSEDED"
        and facts.superseded_at is None
        and (not facts.superseded_by)
    ):
        return (
            TemporalApplicability.UNKNOWN,
            SupersessionStatus.UNKNOWN,
            (Step21ReasonCode.TEMPORAL_FACTS_MISSING,),
        )
    if not starts and (not ends) and (facts.decision_date is None):
        return (
            TemporalApplicability.UNKNOWN,
            SupersessionStatus.UNKNOWN,
            (Step21ReasonCode.TEMPORAL_FACTS_MISSING,),
        )
    if facts.decision_date is not None and as_of < facts.decision_date:
        return (
            TemporalApplicability.NOT_YET_APPLICABLE,
            SupersessionStatus.NOT_SUPERSEDED,
            (Step21ReasonCode.NOT_YET_EFFECTIVE,),
        )
    return (
        TemporalApplicability.APPLICABLE,
        SupersessionStatus.NOT_SUPERSEDED,
        (Step21ReasonCode.EFFECTIVE_AT_AS_OF,),
    )


def assess_bundle_item(
    bundle: FrozenEvidenceBundle, item: EvidenceBundleItem, *, as_of: datetime
) -> CandidateTemporalState:
    """Revalidate one Step 20 item and calculate base applicability."""
    verify_bundle_item_hash(item)
    if (
        item.identity.tenant_id != bundle.tenant_id
        or item.identity.hat_scope_id != bundle.hat_scope_id
        or item.effective_scope != bundle.effective_scope
        or (item.publication_state is not SourcePublicationState.PUBLISHED)
        or (
            item.authority_level
            not in {
                SourceAuthorityLevel.OFFICIAL_PRIMARY,
                SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
            }
        )
    ):
        raise TemporalBoundaryError(Step21ReasonCode.STEP20_INPUT_BINDING_MISMATCH)
    if item.access_class is SourceAccessClass.USER_PRIVATE:
        if (
            item.owner_user_id != bundle.user_id
            or item.target_scope is not MemoryTargetScope.USER_PERSONAL_HAT
            or item.personal_memory_space_id is None
        ):
            raise TemporalBoundaryError(Step21ReasonCode.STEP20_INPUT_BINDING_MISMATCH)
    elif (
        item.owner_user_id is not None
        or item.personal_memory_space_id is not None
        or item.target_scope is not MemoryTargetScope.SHARED_KNOWLEDGE_HAT
    ):
        raise TemporalBoundaryError(Step21ReasonCode.STEP20_INPUT_BINDING_MISMATCH)
    facts, digest_reasons, integrity_valid = extract_temporal_facts(item)
    subject = logical_subject_identity(item, facts)
    if not integrity_valid:
        applicability = TemporalApplicability.UNKNOWN
        supersession = SupersessionStatus.UNKNOWN
        base_reasons = digest_reasons
    else:
        applicability, supersession, base_reasons = _base_applicability(
            facts, ensure_utc(as_of, "as_of")
        )
    reasons = tuple(
        sorted(set((*digest_reasons, *base_reasons)), key=lambda value: value.value)
    )
    return CandidateTemporalState(
        bundle_hash=bundle.bundle_hash,
        item=item,
        facts=facts,
        logical_subject_identity=subject,
        applicability=applicability,
        supersession_status=supersession,
        freshness_status=FreshnessStatus.NOT_APPLICABLE,
        conflict_group_id=None,
        integrity_valid=integrity_valid,
        reasons=reasons,
    )


def update_state(
    state: CandidateTemporalState,
    *,
    applicability: TemporalApplicability | None = None,
    supersession_status: SupersessionStatus | None = None,
    freshness_status: FreshnessStatus | None = None,
    conflict_group_id: str | None | object = ...,
    reasons: tuple[Step21ReasonCode, ...] = (),
) -> CandidateTemporalState:
    values: dict[str, object] = {
        "applicability": applicability or state.applicability,
        "supersession_status": supersession_status or state.supersession_status,
        "freshness_status": freshness_status or state.freshness_status,
        "reasons": tuple(
            sorted(set((*state.reasons, *reasons)), key=lambda value: value.value)
        ),
    }
    if conflict_group_id is not ...:
        values["conflict_group_id"] = conflict_group_id
    return replace(state, **values)


def evaluate_freshness(
    state: CandidateTemporalState, policy: FreshnessPolicy, *, trusted_now: datetime
) -> CandidateTemporalState:
    """Evaluate operational freshness without changing applicability."""
    if state.applicability is not TemporalApplicability.APPLICABLE:
        return update_state(state, freshness_status=FreshnessStatus.NOT_APPLICABLE)
    threshold = policy.maximum_age_seconds_by_source_kind.get(state.item.source_kind)
    if threshold is None:
        return update_state(
            state,
            freshness_status=FreshnessStatus.UNKNOWN,
            reasons=(Step21ReasonCode.FRESHNESS_POLICY_MISSING,),
        )
    observation = None
    for field_name in policy.observation_precedence:
        value = getattr(state.facts, field_name)
        if value is not None:
            observation = value
            break
    if observation is None:
        return update_state(
            state,
            freshness_status=FreshnessStatus.UNKNOWN,
            reasons=(Step21ReasonCode.FRESHNESS_FACT_MISSING,),
        )
    now = ensure_utc(trusted_now, "trusted_now")
    if observation > now:
        return update_state(
            state,
            freshness_status=FreshnessStatus.UNKNOWN,
            reasons=(Step21ReasonCode.FRESHNESS_FACT_IN_FUTURE,),
        )
    if now - observation > timedelta(seconds=threshold):
        return update_state(
            state,
            freshness_status=FreshnessStatus.STALE,
            reasons=(Step21ReasonCode.EVIDENCE_STALE,),
        )
    return update_state(
        state,
        freshness_status=FreshnessStatus.FRESH,
        reasons=(Step21ReasonCode.EVIDENCE_FRESH,),
    )


def _cycle_nodes(edges: dict[str, set[str]]) -> set[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    cyclic: set[str] = set()

    def visit(node: str, path: tuple[str, ...]) -> None:
        if node in visiting:
            if node in path:
                cyclic.update(path[path.index(node) :])
            cyclic.add(node)
            return
        if node in visited:
            return
        visiting.add(node)
        for target in sorted(edges.get(node, ())):
            visit(target, (*path, node))
        visiting.remove(node)
        visited.add(node)

    for node in sorted(edges):
        visit(node, ())
    return cyclic


def _conflict_group(
    logical_subject_identity: str,
    item_hashes: tuple[str, ...],
    reason: Step21ReasonCode,
) -> TemporalConflictGroup | None:
    unique = tuple(sorted(set(item_hashes)))
    if len(unique) < 2:
        return None
    return TemporalConflictGroup(
        logical_subject_identity=logical_subject_identity,
        candidate_item_hashes=unique,
        reason_codes=(reason,),
    )


def apply_supersession_and_conflicts(
    values: tuple[CandidateTemporalState, ...],
) -> tuple[tuple[CandidateTemporalState, ...], tuple[TemporalConflictGroup, ...]]:
    """Apply only explicit graph facts, then preserve material conflicts."""
    states = {value.item.item_hash: value for value in values}
    by_version: dict[str, list[CandidateTemporalState]] = defaultdict(list)
    edges: dict[str, set[str]] = defaultdict(set)
    for value in values:
        by_version[value.version_identity].append(value)
        for successor in value.facts.superseded_by:
            edges[value.version_identity].add(successor)
        for predecessor in value.facts.supersedes:
            edges[predecessor].add(value.version_identity)
    groups: dict[str, TemporalConflictGroup] = {}

    def mark(
        affected: tuple[CandidateTemporalState, ...],
        *,
        reason: Step21ReasonCode,
        supersession: SupersessionStatus,
        logical_subject: str,
    ) -> None:
        group = _conflict_group(
            logical_subject, tuple((item.item.item_hash for item in affected)), reason
        )
        if group is not None:
            groups[group.conflict_group_hash] = group
        for item in affected:
            states[item.item.item_hash] = update_state(
                states[item.item.item_hash],
                applicability=TemporalApplicability.CONFLICTING,
                supersession_status=supersession,
                conflict_group_id=group.conflict_group_id if group else None,
                reasons=(reason, Step21ReasonCode.MATERIAL_CONFLICT),
            )

    cyclic_versions = _cycle_nodes(edges)
    if cyclic_versions:
        affected = tuple(
            (
                item
                for version in sorted(cyclic_versions)
                for item in by_version.get(version, ())
            )
        )
        if affected:
            mark(
                affected,
                reason=Step21ReasonCode.SUPERSESSION_CYCLE,
                supersession=SupersessionStatus.CYCLIC,
                logical_subject="supersession-cycle",
            )
    for predecessor, successors in sorted(edges.items()):
        predecessor_items = tuple(by_version.get(predecessor, ()))
        if not predecessor_items:
            continue
        if len(successors) > 1:
            affected = predecessor_items + tuple(
                (
                    item
                    for successor in sorted(successors)
                    for item in by_version.get(successor, ())
                )
            )
            mark(
                affected,
                reason=Step21ReasonCode.SUPERSESSION_AMBIGUOUS,
                supersession=SupersessionStatus.AMBIGUOUS,
                logical_subject=predecessor_items[0].logical_subject_identity,
            )
            continue
        successor = next(iter(successors))
        successor_items = tuple(by_version.get(successor, ()))
        if not successor_items:
            for item in predecessor_items:
                states[item.item.item_hash] = update_state(
                    states[item.item.item_hash],
                    applicability=TemporalApplicability.UNKNOWN,
                    supersession_status=SupersessionStatus.UNKNOWN,
                    reasons=(Step21ReasonCode.SUPERSESSION_AMBIGUOUS,),
                )
            continue
        successor_is_applicable = any(
            (
                states[item.item.item_hash].applicability
                is TemporalApplicability.APPLICABLE
                for item in successor_items
            )
        )
        if successor_is_applicable:
            for item in predecessor_items:
                current = states[item.item.item_hash]
                if current.applicability is TemporalApplicability.APPLICABLE:
                    states[item.item.item_hash] = update_state(
                        current,
                        applicability=TemporalApplicability.SUPERSEDED,
                        supersession_status=SupersessionStatus.SUPERSEDED,
                        reasons=(Step21ReasonCode.SUPERSEDED_AT_AS_OF,),
                    )
    for version, version_items in sorted(by_version.items()):
        current = tuple((states[item.item.item_hash] for item in version_items))
        if len({item.facts.applicability_facts_hash for item in current}) > 1:
            mark(
                current,
                reason=Step21ReasonCode.TEMPORAL_FACTS_DIGEST_INVALID,
                supersession=SupersessionStatus.AMBIGUOUS,
                logical_subject=current[0].logical_subject_identity,
            )
    by_subject: dict[str, list[CandidateTemporalState]] = defaultdict(list)
    for item_hash in tuple(states):
        state = states[item_hash]
        if state.applicability is TemporalApplicability.APPLICABLE:
            by_subject[state.logical_subject_identity].append(state)
    for subject, subject_items in sorted(by_subject.items()):
        if len(subject_items) < 2:
            continue
        if len({item.item.identity.content_sha256 for item in subject_items}) > 1:
            mark(
                tuple(subject_items),
                reason=Step21ReasonCode.MATERIAL_CONFLICT,
                supersession=SupersessionStatus.AMBIGUOUS,
                logical_subject=subject,
            )
        else:
            for item in subject_items:
                states[item.item.item_hash] = update_state(
                    states[item.item.item_hash],
                    reasons=(Step21ReasonCode.INDEPENDENT_SUPPORT,),
                )
    ordered = tuple((states[value.item.item_hash] for value in values))
    return (
        ordered,
        tuple(sorted(groups.values(), key=lambda item: item.conflict_group_id)),
    )


@dataclass(frozen=True, slots=True, repr=False)
class TemporalSelection:
    mode: TemporalQueryMode
    as_of: datetime
    states: tuple[CandidateTemporalState, ...]
    conflicts: tuple[TemporalConflictGroup, ...]

    @property
    def applicable_items(self):
        return tuple(
            s.item
            for s in self.states
            if s.integrity_valid
            and s.applicability is TemporalApplicability.APPLICABLE
            and s.freshness_status is FreshnessStatus.FRESH
            and s.conflict_group_id is None
        )

    @property
    def review_required(self):
        return (
            bool(self.conflicts)
            or len(self.applicable_items) != len(self.states)
            or not self.states
        )


def resolve_temporal(
    bundle: FrozenEvidenceBundle,
    *,
    mode: TemporalQueryMode,
    trusted_now: datetime,
    freshness: FreshnessPolicy,
    as_of: datetime | None = None,
) -> TemporalSelection:
    """Pure resolution after Core verifies the bundle. It confers no authority."""
    now = ensure_utc(trusted_now, "trusted_now")
    if type(mode) is not TemporalQueryMode or not isinstance(
        freshness, FreshnessPolicy
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    if mode in {TemporalQueryMode.CURRENT, TemporalQueryMode.UNSPECIFIED}:
        if as_of is not None:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        evaluation = now
    else:
        if as_of is None:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        evaluation = ensure_utc(as_of, "as_of")
        if (mode is TemporalQueryMode.FUTURE) != (evaluation > now):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    states = tuple(
        assess_bundle_item(bundle, item, as_of=evaluation) for item in bundle.items
    )
    states, conflicts = apply_supersession_and_conflicts(states)
    states = tuple(evaluate_freshness(s, freshness, trusted_now=now) for s in states)
    if mode is TemporalQueryMode.UNSPECIFIED:
        states = tuple(
            update_state(
                s,
                applicability=TemporalApplicability.UNKNOWN,
                freshness_status=FreshnessStatus.UNKNOWN,
                reasons=(Step21ReasonCode.AS_OF_UNSPECIFIED,),
            )
            for s in states
        )
    return TemporalSelection(mode, evaluation, states, conflicts)
