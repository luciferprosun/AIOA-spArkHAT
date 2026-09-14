"""Domain-neutral native policy bindings and reviewed deterministic German-law fixture metadata. These rules classify supplied source facts; no demo runner, source fetching, model answer or evidence publication is enabled."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from runtime.core_admission import CoreAdmission, CorePrincipal
from runtime.evidence_admission import CoreEvidenceAdmission
from runtime.memory_patch.contracts.serialization import canonical_sha256, ensure_utc
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.hats import ScopedHatBinding
from runtime.memory_patch.source_lineage import SourceAuthorityLevel


class GermanLawPolicyError(ValueError):
    """A deterministic, non-authoritative German-law policy rejection."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


GERMAN_LAW_POLICY_VERSION = "german-law-source-authority-1a"
GERMAN_LAW_TEMPORAL_POLICY_VERSION = "german-law-temporal-policy-1a"
GERMAN_LAW_ADAPTER_POLICY_VERSION = "german-law-metadata-adapters-1a"


class LegalJurisdiction(str, Enum):
    DE_FEDERAL = "DE_FEDERAL"
    DE_STATE = "DE_STATE"
    EU = "EU"


class GermanLegalSourceClass(str, Enum):
    DE_FEDERAL_AUTHENTIC_PROMULGATION = "DE_FEDERAL_AUTHENTIC_PROMULGATION"
    DE_FEDERAL_OFFICIAL_CONSOLIDATED_LAW = "DE_FEDERAL_OFFICIAL_CONSOLIDATED_LAW"
    DE_FEDERAL_OFFICIAL_COURT_DECISION = "DE_FEDERAL_OFFICIAL_COURT_DECISION"
    DE_STATE_AUTHENTIC_PROMULGATION = "DE_STATE_AUTHENTIC_PROMULGATION"
    DE_STATE_OFFICIAL_CONSOLIDATED_LAW = "DE_STATE_OFFICIAL_CONSOLIDATED_LAW"
    DE_STATE_OFFICIAL_COURT_DECISION = "DE_STATE_OFFICIAL_COURT_DECISION"
    EU_AUTHENTIC_OFFICIAL_JOURNAL = "EU_AUTHENTIC_OFFICIAL_JOURNAL"
    EU_OFFICIAL_CONSOLIDATED_ACT = "EU_OFFICIAL_CONSOLIDATED_ACT"
    OFFICIAL_LEGISLATIVE_MATERIAL = "OFFICIAL_LEGISLATIVE_MATERIAL"
    OFFICIAL_ADMINISTRATIVE_GUIDANCE = "OFFICIAL_ADMINISTRATIVE_GUIDANCE"
    OFFICIAL_RESEARCH_OR_EXPLANATORY_MATERIAL = (
        "OFFICIAL_RESEARCH_OR_EXPLANATORY_MATERIAL"
    )
    REPUTABLE_LEGAL_SECONDARY = "REPUTABLE_LEGAL_SECONDARY"
    PRIVATE_LEGAL_DATABASE = "PRIVATE_LEGAL_DATABASE"
    USER_SUPPLIED_LEGAL_DOCUMENT = "USER_SUPPLIED_LEGAL_DOCUMENT"
    DERIVED_SUMMARY = "DERIVED_SUMMARY"
    UNKNOWN_LEGAL_SOURCE = "UNKNOWN_LEGAL_SOURCE"


class AuthenticityStatus(str, Enum):
    AUTHENTIC = "AUTHENTIC"
    OFFICIAL_NON_AUTHENTIC = "OFFICIAL_NON_AUTHENTIC"
    NOT_AUTHENTIC = "NOT_AUTHENTIC"
    UNKNOWN = "UNKNOWN"


class ConsolidationStatus(str, Enum):
    NOT_CONSOLIDATED = "NOT_CONSOLIDATED"
    OFFICIAL_CONSOLIDATED = "OFFICIAL_CONSOLIDATED"
    PRIVATE_CONSOLIDATED = "PRIVATE_CONSOLIDATED"
    UNKNOWN = "UNKNOWN"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    OFFICIAL_REFERENCE_VERIFIED = "OFFICIAL_REFERENCE_VERIFIED"
    AUTHENTICITY_VERIFIED = "AUTHENTICITY_VERIFIED"
    CONFLICTING = "CONFLICTING"
    INSUFFICIENT = "INSUFFICIENT"


class TemporalDecision(str, Enum):
    APPLICABLE = "APPLICABLE"
    NOT_YET_APPLICABLE = "NOT_YET_APPLICABLE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


def _text(value: object, field_name: str, maximum: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or (len(value) > maximum)
    ):
        raise GermanLawPolicyError(
            "INVALID_VALUE", f"{field_name} must be bounded canonical text"
        )
    lowered = value.casefold()
    if any(
        (
            token in lowered
            for token in ("password=", "aws_secret", "authorization: bearer")
        )
    ):
        raise GermanLawPolicyError(
            "HIDDEN_AUTHORITY_OR_SECRET", f"{field_name} contains forbidden material"
        )
    return value


def _optional_text(
    value: object | None, field_name: str, maximum: int = 512
) -> str | None:
    return None if value is None else _text(value, field_name, maximum)


@dataclass(frozen=True, slots=True)
class GermanLawRequest:
    request_id: str
    query_text: str
    request_language: str
    legal_jurisdiction: LegalJurisdiction
    knowledge_as_of: datetime | None
    federal_state: str | None = None
    legal_domain: str | None = None
    official_identifier_hint: str | None = None
    court_or_proceeding_hint: str | None = None
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("request_id", "query_text"):
            object.__setattr__(self, name, _text(getattr(self, name), name, 4096))
        if self.request_language != "de":
            raise GermanLawPolicyError(
                "UNSUPPORTED_LANGUAGE", "Step 13 supports German requests only"
            )
        if not isinstance(self.legal_jurisdiction, LegalJurisdiction):
            raise GermanLawPolicyError(
                "UNSUPPORTED_JURISDICTION", "legal jurisdiction must be explicit"
            )
        if self.knowledge_as_of is not None:
            object.__setattr__(
                self,
                "knowledge_as_of",
                ensure_utc(self.knowledge_as_of, "knowledge_as_of"),
            )
        if (
            self.legal_jurisdiction is LegalJurisdiction.DE_STATE
            and self.federal_state is None
        ):
            raise GermanLawPolicyError(
                "MISSING_FEDERAL_STATE", "state-law requests require an explicit state"
            )
        if (
            self.legal_jurisdiction is not LegalJurisdiction.DE_STATE
            and self.federal_state is not None
        ):
            raise GermanLawPolicyError(
                "JURISDICTION_SCOPE_MISMATCH",
                "federal_state is valid only for DE_STATE",
            )
        for name in (
            "federal_state",
            "legal_domain",
            "official_identifier_hint",
            "court_or_proceeding_hint",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        object.__setattr__(
            self,
            "request_digest",
            canonical_sha256(self, exclude_fields=("request_digest",)),
        )


@dataclass(frozen=True, slots=True)
class GermanLawTemporalFacts:
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
    superseded_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, ensure_utc(value, name))


@dataclass(frozen=True, slots=True)
class GermanLawSourceMetadata:
    source_id: str
    source_registry_reference: str
    source_class: GermanLegalSourceClass
    official_publisher: str | None
    canonical_official_identifier: str | None
    jurisdiction: LegalJurisdiction
    language: str
    authenticity_status: AuthenticityStatus
    consolidation_status: ConsolidationStatus
    verification_status: VerificationStatus
    retrieval_reference: str
    temporal: GermanLawTemporalFacts = field(default_factory=GermanLawTemporalFacts)
    court_identity: str | None = None
    court_level: str | None = None
    metadata_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("source_id", "source_registry_reference", "retrieval_reference"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.source_class, GermanLegalSourceClass) or not isinstance(
            self.jurisdiction, LegalJurisdiction
        ):
            raise GermanLawPolicyError(
                "INVALID_SOURCE_CLASS",
                "typed source class and jurisdiction are required",
            )
        if self.language != "de" and self.language != "en":
            raise GermanLawPolicyError(
                "UNSUPPORTED_LANGUAGE", "unsupported source language"
            )
        for name in (
            "official_publisher",
            "canonical_official_identifier",
            "court_identity",
            "court_level",
        ):
            object.__setattr__(self, name, _optional_text(getattr(self, name), name))
        if not isinstance(self.temporal, GermanLawTemporalFacts):
            raise GermanLawPolicyError(
                "INVALID_TEMPORAL_METADATA", "temporal facts must be typed"
            )
        object.__setattr__(
            self,
            "metadata_digest",
            canonical_sha256(self, exclude_fields=("metadata_digest",)),
        )


@dataclass(frozen=True, slots=True)
class GermanLawTemporalAssessment:
    decision: TemporalDecision
    policy_version: str
    reason_codes: tuple[str, ...]
    assessment_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        object.__setattr__(
            self,
            "assessment_digest",
            canonical_sha256(self, exclude_fields=("assessment_digest",)),
        )


@dataclass(frozen=True, slots=True)
class GermanLawSourceAuthorityAssessment:
    source_id: str
    authority_level: SourceAuthorityLevel
    source_class: GermanLegalSourceClass
    authenticity_status: AuthenticityStatus
    verification_status: VerificationStatus
    policy_version: str
    reason_codes: tuple[str, ...]
    unresolved_limitations: tuple[str, ...]
    temporal_assessment_digest: str
    assessment_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reason_codes", tuple(sorted(set(self.reason_codes))))
        object.__setattr__(
            self,
            "unresolved_limitations",
            tuple(sorted(set(self.unresolved_limitations))),
        )
        object.__setattr__(
            self,
            "assessment_digest",
            canonical_sha256(self, exclude_fields=("assessment_digest",)),
        )


_AUTHORITY = {
    GermanLegalSourceClass.DE_FEDERAL_AUTHENTIC_PROMULGATION: SourceAuthorityLevel.OFFICIAL_PRIMARY,
    GermanLegalSourceClass.DE_STATE_AUTHENTIC_PROMULGATION: SourceAuthorityLevel.OFFICIAL_PRIMARY,
    GermanLegalSourceClass.EU_AUTHENTIC_OFFICIAL_JOURNAL: SourceAuthorityLevel.OFFICIAL_PRIMARY,
    GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_COURT_DECISION: SourceAuthorityLevel.OFFICIAL_PRIMARY,
    GermanLegalSourceClass.DE_STATE_OFFICIAL_COURT_DECISION: SourceAuthorityLevel.OFFICIAL_PRIMARY,
    GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_CONSOLIDATED_LAW: SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    GermanLegalSourceClass.DE_STATE_OFFICIAL_CONSOLIDATED_LAW: SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    GermanLegalSourceClass.EU_OFFICIAL_CONSOLIDATED_ACT: SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    GermanLegalSourceClass.OFFICIAL_LEGISLATIVE_MATERIAL: SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    GermanLegalSourceClass.OFFICIAL_ADMINISTRATIVE_GUIDANCE: SourceAuthorityLevel.AUTHORITATIVE_SECONDARY,
    GermanLegalSourceClass.OFFICIAL_RESEARCH_OR_EXPLANATORY_MATERIAL: SourceAuthorityLevel.INFORMATIONAL_SECONDARY,
    GermanLegalSourceClass.REPUTABLE_LEGAL_SECONDARY: SourceAuthorityLevel.INFORMATIONAL_SECONDARY,
    GermanLegalSourceClass.PRIVATE_LEGAL_DATABASE: SourceAuthorityLevel.INFORMATIONAL_SECONDARY,
    GermanLegalSourceClass.USER_SUPPLIED_LEGAL_DOCUMENT: SourceAuthorityLevel.USER_SUPPLIED,
    GermanLegalSourceClass.DERIVED_SUMMARY: SourceAuthorityLevel.DERIVED,
    GermanLegalSourceClass.UNKNOWN_LEGAL_SOURCE: SourceAuthorityLevel.UNKNOWN,
}
_EXPECTED_PUBLISHERS = {
    GermanLegalSourceClass.DE_FEDERAL_AUTHENTIC_PROMULGATION: {
        "Bundesministerium der Justiz",
        "Bundesamt für Justiz",
    },
    GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_CONSOLIDATED_LAW: {
        "Bundesministerium der Justiz",
        "Bundesamt für Justiz",
    },
    GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_COURT_DECISION: {
        "Bundesverfassungsgericht",
        "Bundesgerichtshof",
        "Bundesarbeitsgericht",
        "Bundesverwaltungsgericht",
        "Bundesfinanzhof",
        "Bundessozialgericht",
    },
    GermanLegalSourceClass.OFFICIAL_LEGISLATIVE_MATERIAL: {
        "Deutscher Bundestag",
        "Bundesrat",
    },
    GermanLegalSourceClass.EU_AUTHENTIC_OFFICIAL_JOURNAL: {
        "Publications Office of the European Union"
    },
    GermanLegalSourceClass.EU_OFFICIAL_CONSOLIDATED_ACT: {
        "Publications Office of the European Union"
    },
}


def assess_temporal(
    metadata: GermanLawSourceMetadata, request: GermanLawRequest
) -> GermanLawTemporalAssessment:
    facts = metadata.temporal
    reasons: list[str] = []
    if request.knowledge_as_of is None:
        return GermanLawTemporalAssessment(
            TemporalDecision.UNKNOWN,
            GERMAN_LAW_TEMPORAL_POLICY_VERSION,
            ("KNOWLEDGE_AS_OF_MISSING",),
        )
    for start, end, label in (
        (facts.effective_from, facts.effective_to, "EFFECTIVE"),
        (facts.applicable_from, facts.applicable_to, "APPLICABLE"),
    ):
        if start is not None and end is not None and (start > end):
            return GermanLawTemporalAssessment(
                TemporalDecision.CONFLICTING,
                GERMAN_LAW_TEMPORAL_POLICY_VERSION,
                (f"{label}_INTERVAL_INVALID",),
            )
    start = facts.applicable_from or facts.effective_from
    end = facts.applicable_to or facts.effective_to
    if start is not None and request.knowledge_as_of < start:
        return GermanLawTemporalAssessment(
            TemporalDecision.NOT_YET_APPLICABLE,
            GERMAN_LAW_TEMPORAL_POLICY_VERSION,
            ("FUTURE_AT_KNOWLEDGE_AS_OF",),
        )
    if end is not None and request.knowledge_as_of >= end:
        return GermanLawTemporalAssessment(
            TemporalDecision.EXPIRED,
            GERMAN_LAW_TEMPORAL_POLICY_VERSION,
            ("EXPIRED_AT_KNOWLEDGE_AS_OF",),
        )
    if start is None and end is None and (facts.decision_date is None):
        reasons.append("LEGAL_VALIDITY_INTERVAL_UNKNOWN")
        decision = TemporalDecision.UNKNOWN
    else:
        reasons.append("WITHIN_DECLARED_INTERVAL")
        decision = TemporalDecision.APPLICABLE
    return GermanLawTemporalAssessment(
        decision, GERMAN_LAW_TEMPORAL_POLICY_VERSION, tuple(reasons)
    )


def assess_source(
    metadata: GermanLawSourceMetadata, request: GermanLawRequest
) -> GermanLawSourceAuthorityAssessment:
    temporal = assess_temporal(metadata, request)
    reasons: list[str] = ["SOURCE_CLASS_MAPPED"]
    limitations: list[str] = []
    authority = _AUTHORITY[metadata.source_class]
    if metadata.jurisdiction is not request.legal_jurisdiction:
        limitations.append("JURISDICTION_MISMATCH")
    if (
        metadata.official_publisher is None
        or metadata.canonical_official_identifier is None
    ):
        limitations.append("OFFICIAL_IDENTITY_INCOMPLETE")
    expected_publishers = _EXPECTED_PUBLISHERS.get(metadata.source_class)
    if (
        expected_publishers is not None
        and metadata.official_publisher not in expected_publishers
    ):
        limitations.append("OFFICIAL_PUBLISHER_MISMATCH")
    if metadata.verification_status in {
        VerificationStatus.CONFLICTING,
        VerificationStatus.INSUFFICIENT,
        VerificationStatus.UNVERIFIED,
    }:
        limitations.append("SOURCE_VERIFICATION_INCOMPLETE")
    authentic_classes = {
        GermanLegalSourceClass.DE_FEDERAL_AUTHENTIC_PROMULGATION,
        GermanLegalSourceClass.DE_STATE_AUTHENTIC_PROMULGATION,
        GermanLegalSourceClass.EU_AUTHENTIC_OFFICIAL_JOURNAL,
    }
    if (
        metadata.source_class in authentic_classes
        and metadata.authenticity_status is not AuthenticityStatus.AUTHENTIC
    ):
        limitations.append("AUTHENTICITY_NOT_PROVEN")
    if metadata.source_class in {
        GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_CONSOLIDATED_LAW,
        GermanLegalSourceClass.DE_STATE_OFFICIAL_CONSOLIDATED_LAW,
        GermanLegalSourceClass.EU_OFFICIAL_CONSOLIDATED_ACT,
    }:
        reasons.append("CONSOLIDATED_TEXT_NOT_AUTHENTIC_PROMULGATION")
        if (
            metadata.consolidation_status
            is not ConsolidationStatus.OFFICIAL_CONSOLIDATED
        ):
            limitations.append("CONSOLIDATION_STATUS_MISMATCH")
    if metadata.source_class is GermanLegalSourceClass.OFFICIAL_LEGISLATIVE_MATERIAL:
        reasons.append("LEGISLATIVE_HISTORY_NOT_ENACTED_LAW")
    if metadata.source_class is GermanLegalSourceClass.OFFICIAL_ADMINISTRATIVE_GUIDANCE:
        reasons.append("AGENCY_INTERPRETATION_NOT_ENACTED_LAW")
    if metadata.source_class in {
        GermanLegalSourceClass.DE_FEDERAL_OFFICIAL_COURT_DECISION,
        GermanLegalSourceClass.DE_STATE_OFFICIAL_COURT_DECISION,
    }:
        reasons.append("DECISION_PRIMARY_ONLY_FOR_IDENTIFIED_CASE")
        if metadata.court_identity is None:
            limitations.append("COURT_IDENTITY_MISSING")
        court_scope_hints = tuple(
            (
                hint
                for hint in (
                    request.court_or_proceeding_hint,
                    request.official_identifier_hint,
                )
                if hint is not None
            )
        )
        if not court_scope_hints:
            limitations.append("COURT_OR_PROCEEDING_SCOPE_UNBOUND")
        else:
            exact_scope_identities = {
                identity
                for identity in (
                    metadata.court_identity,
                    metadata.canonical_official_identifier,
                )
                if identity is not None
            }
            if not any((hint in exact_scope_identities for hint in court_scope_hints)):
                limitations.append("COURT_OR_PROCEEDING_SCOPE_MISMATCH")
            else:
                reasons.append("COURT_OR_PROCEEDING_SCOPE_BOUND")
    if temporal.decision is not TemporalDecision.APPLICABLE:
        limitations.append("TEMPORAL_APPLICABILITY_UNRESOLVED")
    return GermanLawSourceAuthorityAssessment(
        metadata.source_id,
        authority,
        metadata.source_class,
        metadata.authenticity_status,
        metadata.verification_status,
        GERMAN_LAW_POLICY_VERSION,
        tuple(reasons),
        tuple(limitations),
        temporal.assessment_digest,
    )


def authority_sort_key(
    assessment: GermanLawSourceAuthorityAssessment,
) -> tuple[int, int, str]:
    levels = {
        SourceAuthorityLevel.OFFICIAL_PRIMARY: 0,
        SourceAuthorityLevel.AUTHORITATIVE_SECONDARY: 1,
        SourceAuthorityLevel.INFORMATIONAL_SECONDARY: 2,
        SourceAuthorityLevel.USER_SUPPLIED: 3,
        SourceAuthorityLevel.DERIVED: 4,
        SourceAuthorityLevel.UNKNOWN: 5,
    }
    return (
        levels[assessment.authority_level],
        len(assessment.unresolved_limitations),
        assessment.source_id,
    )


@dataclass(frozen=True, slots=True)
class DomainProfile:
    profile_id: str
    version: str
    hat_id: str
    source_policy_version: str
    temporal_policy_version: str

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            _text(value, name, 128)
            if value.casefold() == "latest":
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)


GERMAN_LAW_FIXTURE_PROFILE = DomainProfile(
    "german-law",
    "1.0.0",
    "german-law",
    GERMAN_LAW_POLICY_VERSION,
    GERMAN_LAW_TEMPORAL_POLICY_VERSION,
)


def require_domain_profile(
    core: CoreAdmission,
    principal: CorePrincipal,
    binding: ScopedHatBinding,
    profile: DomainProfile,
) -> None:
    core.require(principal, principal.capability, scope=binding.scope)
    if (
        type(profile) is not DomainProfile
        or binding.hat_id != profile.hat_id
        or profile.hat_id not in principal.hat_ids
    ):
        raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)


def assess_reviewed_german_source(
    core: CoreAdmission,
    evidence: CoreEvidenceAdmission,
    principal: CorePrincipal,
    binding: ScopedHatBinding,
    evidence_id: str,
    metadata: GermanLawSourceMetadata,
    request: GermanLawRequest,
) -> GermanLawSourceAuthorityAssessment:
    """Policy classification of an admitted source, never answer certification."""
    require_domain_profile(core, principal, binding, GERMAN_LAW_FIXTURE_PROFILE)
    captured = evidence.require_evidence(principal, evidence_id)
    if (
        captured.source.source_id != metadata.source_id
        or captured.source.hat_id != binding.hat_id
    ):
        raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
    return assess_source(metadata, request)
