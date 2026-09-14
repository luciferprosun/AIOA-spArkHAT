"""Reviewed pure domain semantics with native, inert dependencies."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.enums import StableStringEnum
from runtime.memory_patch.contracts.records import (
    ClaimCandidate as KernelClaimCandidate,
)
from runtime.memory_patch.contracts.scope import ScopeDimension
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    require_enum_member,
    require_sha256_hex,
    verify_canonical_hash,
)
from runtime.memory_patch.errors import (
    ContractValidationError,
    ErrorCode,
    IntegrityError,
    MemoryPatchError,
)
from runtime.memory_patch.retrieval.contracts import (
    FrozenEvidenceBundle,
    bounded_text,
    trusted_dimensions,
)
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.memory_patch.retrieval.temporal import TemporalQueryMode, resolve_temporal

CLAIM_PROCESSING_POLICY_ID = "claim-extraction-evidence-binding-1a"
CLAIM_PROCESSING_POLICY_VERSION = "1"
CLAIM_SPAN_CONVENTION = "draft-v1-unicode-codepoints-start-inclusive-end-exclusive-v1"
MAX_CLAIMS = 256
MAX_CLAIM_UTF8_BYTES = 16 * 1024
MAX_EVIDENCE_LINKS = 4096


class ClaimType(StableStringEnum):
    FACTUAL = "FACTUAL"
    TEMPORAL = "TEMPORAL"
    LEGAL_NORM = "LEGAL_NORM"
    SOURCE_ASSERTION = "SOURCE_ASSERTION"
    QUANTITATIVE = "QUANTITATIVE"
    RELATIONAL = "RELATIONAL"
    NON_FACTUAL = "NON_FACTUAL"


class ClaimAtomicity(StableStringEnum):
    ATOMIC = "ATOMIC"
    COMPOUND = "COMPOUND"
    NON_FACTUAL = "NON_FACTUAL"


class ClaimEvidenceRelation(StableStringEnum):
    SUPPORTS = "SUPPORTS"
    REFUTES = "REFUTES"
    RELATED_ONLY = "RELATED_ONLY"
    INSUFFICIENT = "INSUFFICIENT"


class ClaimEvidenceCandidateStatus(StableStringEnum):
    SUPPORTED = "SUPPORTED"
    REFUTED = "REFUTED"
    UNVERIFIED = "UNVERIFIED"


class ClaimReasonCode(StableStringEnum):
    CLAIM_EXTRACTED = "CLAIM_EXTRACTED"
    CLAIM_NON_FACTUAL = "CLAIM_NON_FACTUAL"
    CLAIM_COMPOUND = "CLAIM_COMPOUND"
    CLAIM_SPAN_INVALID = "CLAIM_SPAN_INVALID"
    CLAIM_TEXT_MISMATCH = "CLAIM_TEXT_MISMATCH"
    INPUT_HASH_INVALID = "INPUT_HASH_INVALID"
    INPUT_BINDING_MISMATCH = "INPUT_BINDING_MISMATCH"
    EVIDENCE_SUPPORTS = "EVIDENCE_SUPPORTS"
    EVIDENCE_REFUTES = "EVIDENCE_REFUTES"
    EVIDENCE_RELATED_ONLY = "EVIDENCE_RELATED_ONLY"
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    TEMPORAL_MISMATCH = "TEMPORAL_MISMATCH"
    TEMPORAL_CONFLICT = "TEMPORAL_CONFLICT"
    FRESHNESS_STALE = "FRESHNESS_STALE"
    SOURCE_AUTHORITY_INSUFFICIENT = "SOURCE_AUTHORITY_INSUFFICIENT"
    EVIDENCE_UNAVAILABLE = "EVIDENCE_UNAVAILABLE"
    CLAIM_SUPPORTED = "CLAIM_SUPPORTED"
    CLAIM_REFUTED = "CLAIM_REFUTED"
    CLAIM_UNVERIFIED = "CLAIM_UNVERIFIED"
    MATERIAL_CONFLICT = "MATERIAL_CONFLICT"
    PACKET_INPUT_FROZEN = "PACKET_INPUT_FROZEN"


class ClaimBoundaryError(RuntimeError):
    """Sanitized fail-closed error at the Step 23 boundary."""

    def __init__(self, reason_code: ClaimReasonCode) -> None:
        if not isinstance(reason_code, ClaimReasonCode):
            raise TypeError("reason_code must be ClaimReasonCode")
        super().__init__(f"Step 23 claim binding denied: {reason_code.value}")
        self.reason_code = reason_code


_CONTROL = re.compile("[\\x00-\\x08\\x0b\\x0c\\x0e-\\x1f\\x7f]")
_REASON_ORDER = {value: index for index, value in enumerate(ClaimReasonCode)}


def _text(value: object, field_name: str, maximum_bytes: int = 1024) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or (unicodedata.normalize("NFC", value) != value)
        or _CONTROL.search(value)
        or (len(value.encode("utf-8")) > maximum_bytes)
    ):
        raise ContractValidationError(
            f"{field_name} must be bounded canonical NFC text"
        )
    return value


def _scope_tuple(value: object, field_name: str) -> tuple[ScopeDimension, ...]:
    if not isinstance(value, (tuple, list)) or any(
        (not isinstance(item, ScopeDimension) for item in value)
    ):
        raise ContractValidationError(
            f"{field_name} must contain ScopeDimension values"
        )
    result = tuple(value)
    if len({item.name for item in result}) != len(result):
        raise ContractValidationError(f"{field_name} names must be unique")
    return result


def _reason_tuple(value: object) -> tuple[ClaimReasonCode, ...]:
    if not isinstance(value, (tuple, list)) or any(
        (not isinstance(item, ClaimReasonCode) for item in value)
    ):
        raise ContractValidationError(
            "reason_codes must contain ClaimReasonCode values"
        )
    result = tuple(sorted(set(value), key=_REASON_ORDER.__getitem__))
    if tuple(value) != result:
        raise ContractValidationError("reason_codes must be unique and canonical")
    return result


def reason_codes(*values: ClaimReasonCode) -> tuple[ClaimReasonCode, ...]:
    """Return a unique, stable Step 23 reason tuple."""
    return tuple(sorted(set(values), key=_REASON_ORDER.__getitem__))


def normalize_claim_for_match(value: str) -> str:
    """Create a separate, non-authoritative form used only for exact rules."""
    text = _text(value, "claim text", MAX_CLAIM_UTF8_BYTES)
    folded = " ".join(text.casefold().split())
    return folded.strip(" .!?;:…")


def derive_claim_id(
    draft_v1_hash: str, start_offset: int, end_offset: int, exact_claim_text: str
) -> str:
    require_sha256_hex(draft_v1_hash, "draft_v1_hash")
    digest = canonical_sha256(
        {
            "draft_v1_hash": draft_v1_hash,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "exact_claim_text": exact_claim_text,
        }
    )
    return f"claim-{digest}"


@dataclass(frozen=True, slots=True)
class ClaimProcessingPolicy:
    policy_id: str = CLAIM_PROCESSING_POLICY_ID
    policy_version: str = CLAIM_PROCESSING_POLICY_VERSION
    span_convention: str = CLAIM_SPAN_CONVENTION
    support_rule: str = "normalized-whole-assertion-equality-v1"
    refutation_rule: str = "single-explicit-negation-counterpart-v1"
    related_rule: str = "bounded-significant-token-overlap-diagnostic-only-v1"
    maximum_claims: int = MAX_CLAIMS
    maximum_evidence_links: int = MAX_EVIDENCE_LINKS
    model_assisted_extraction: bool = False
    policy_digest: str = field(init=False)

    def __post_init__(self) -> None:
        for value, name in (
            (self.policy_id, "policy_id"),
            (self.policy_version, "policy_version"),
            (self.span_convention, "span_convention"),
            (self.support_rule, "support_rule"),
            (self.refutation_rule, "refutation_rule"),
            (self.related_rule, "related_rule"),
        ):
            _text(value, name, 256)
        if (
            self.maximum_claims != MAX_CLAIMS
            or self.maximum_evidence_links != MAX_EVIDENCE_LINKS
        ):
            raise ContractValidationError("Step 23 resource bounds are fixed")
        if self.model_assisted_extraction is not False:
            raise ContractValidationError("Step 23 V1 extraction is deterministic only")
        object.__setattr__(
            self,
            "policy_digest",
            canonical_sha256(self, exclude_fields=("policy_digest",)),
        )


def load_claim_processing_policy() -> ClaimProcessingPolicy:
    return ClaimProcessingPolicy()


@dataclass(frozen=True, slots=True)
class ClaimRecord:
    draft_id: str
    draft_v1_hash: str
    start_offset: int
    end_offset: int
    exact_claim_text: str
    normalized_match_text: str
    claim_type: ClaimType
    atomicity: ClaimAtomicity
    scope_dimensions: tuple[ScopeDimension, ...]
    reason_codes: tuple[ClaimReasonCode, ...]
    exact_claim_text_sha256: str = field(init=False)
    claim_id: str = field(init=False)
    claim_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _text(self.draft_id, "draft_id", 255)
        require_sha256_hex(self.draft_v1_hash, "draft_v1_hash")
        for value, name in (
            (self.start_offset, "start_offset"),
            (self.end_offset, "end_offset"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContractValidationError(f"{name} must be a non-negative integer")
        if self.start_offset >= self.end_offset:
            raise ClaimBoundaryError(ClaimReasonCode.CLAIM_SPAN_INVALID)
        text = _text(self.exact_claim_text, "exact_claim_text", MAX_CLAIM_UTF8_BYTES)
        normalized = normalize_claim_for_match(text)
        if not normalized or self.normalized_match_text != normalized:
            raise ContractValidationError("normalized claim text differs from policy")
        require_enum_member(self.claim_type, ClaimType, "claim_type")
        require_enum_member(self.atomicity, ClaimAtomicity, "atomicity")
        if (self.claim_type is ClaimType.NON_FACTUAL) != (
            self.atomicity is ClaimAtomicity.NON_FACTUAL
        ):
            raise ContractValidationError("non-factual type and atomicity must agree")
        object.__setattr__(
            self,
            "scope_dimensions",
            _scope_tuple(self.scope_dimensions, "scope_dimensions"),
        )
        object.__setattr__(self, "reason_codes", _reason_tuple(self.reason_codes))
        if ClaimReasonCode.CLAIM_EXTRACTED not in self.reason_codes:
            raise ContractValidationError("claim must record deterministic extraction")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        object.__setattr__(self, "exact_claim_text_sha256", digest)
        claim_id = derive_claim_id(
            self.draft_v1_hash, self.start_offset, self.end_offset, text
        )
        object.__setattr__(self, "claim_id", claim_id)
        KernelClaimCandidate(
            claim_id=claim_id,
            draft_id=self.draft_id,
            statement=text,
            claim_category=self.claim_type.value,
            scope_dimensions=self.scope_dimensions,
        )
        object.__setattr__(
            self, "claim_hash", canonical_sha256(self, exclude_fields=("claim_hash",))
        )


def verify_claim_record_hash(value: ClaimRecord) -> None:
    verify_canonical_hash(value, value.claim_hash, exclude_fields=("claim_hash",))
    expected_id = derive_claim_id(
        value.draft_v1_hash,
        value.start_offset,
        value.end_offset,
        value.exact_claim_text,
    )
    if value.claim_id != expected_id:
        raise IntegrityError("claim ID differs from exact Draft V1 span")
    if (
        value.exact_claim_text_sha256
        != hashlib.sha256(value.exact_claim_text.encode("utf-8")).hexdigest()
    ):
        raise IntegrityError("claim text digest mismatch")


_BULLET_PREFIX = re.compile("(?:[-*•]\\s+|\\(?\\d{1,3}[.)]\\s+)")
_COMPOUND = re.compile(
    "\\b(?:und|oder|aber|sowie|während|hingegen|and|or|but|whereas)\\b", re.IGNORECASE
)
_NOMINAL_COORDINATION = re.compile(
    "\\b(?P<left>[A-ZÄÖÜ][^\\W_]*)\\s+(?:und|oder|sowie|and|or)\\s+(?P<right>[A-ZÄÖÜ][^\\W_]*)\\b"
)
_LEGAL_ROMAN_REFERENCES = frozenset({"I", "II", "III"})
_DATE_OR_NUMBER = re.compile("(?:\\b\\d{1,4}(?:[./-]\\d{1,2}){0,2}\\b|%)")
_NON_FACTUAL_PREFIXES = (
    "hallo",
    "guten tag",
    "danke",
    "vielen dank",
    "bitte beachten",
    "meiner meinung nach",
    "ich denke",
    "ich hoffe",
    "dies ist nur ein entwurf",
    "ich bin ein sprachmodell",
)
_SOURCE_MARKERS = (
    "laut ",
    "quelle",
    "amtlich",
    "offiziell",
    "official source",
    "source says",
)
_TEMPORAL_MARKERS = (
    "aktuell",
    "derzeit",
    "gegenwärtig",
    "seit ",
    " bis ",
    "wirksam",
    "in kraft",
    "aufgehoben",
    "außer kraft",
    "superseded",
    "repealed",
    "effective",
    "as of",
)
_LEGAL_MARKERS = (
    "§",
    "gesetz",
    "verordnung",
    "vorschrift",
    "anspruch",
    "artikel ",
    "art. ",
    "recht",
    "pflicht",
    "darf ",
    "muss ",
)
_RELATIONAL_MARKERS = (
    "bezieht sich",
    "gehört zu",
    "entspricht",
    "ist gleich",
    "is related to",
    "equals",
)
_ABBREVIATIONS = frozenset(
    {
        "abs.",
        "art.",
        "bzw.",
        "ca.",
        "dr.",
        "ggf.",
        "nr.",
        "prof.",
        "sog.",
        "u.a.",
        "z.b.",
    }
)
_GERMAN_MONTH_NAMES = frozenset(
    {
        "januar",
        "februar",
        "märz",
        "april",
        "mai",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "dezember",
    }
)


@dataclass(frozen=True, slots=True)
class TextSpan:
    start_offset: int
    end_offset: int
    text: str


def _trim_span(text: str, start: int, end: int) -> TextSpan | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    prefix = _BULLET_PREFIX.match(text, start, end)
    if prefix is not None:
        start = prefix.end()
        while start < end and text[start].isspace():
            start += 1
    if start >= end:
        return None
    return TextSpan(start, end, text[start:end])


def _period_is_boundary(text: str, index: int) -> bool:
    if index > 0 and index + 1 < len(text):
        if text[index - 1].isdigit() and text[index + 1].isdigit():
            return False
    token_start = index
    while token_start > 0 and (not text[token_start - 1].isspace()):
        token_start -= 1
    ordinal = text[token_start:index]
    if ordinal.isdigit():
        next_start = index + 1
        while next_start < len(text) and text[next_start].isspace():
            next_start += 1
        next_end = next_start
        while next_end < len(text) and text[next_end].isalpha():
            next_end += 1
        if text[next_start:next_end].casefold() in _GERMAN_MONTH_NAMES:
            return False
    if (
        ordinal in _LEGAL_ROMAN_REFERENCES
        and index + 1 < len(text)
        and (text[index + 1] in " \t")
    ):
        next_start = index + 1
        while next_start < len(text) and text[next_start] in " \t":
            next_start += 1
        if next_start < len(text) and text[next_start].islower():
            return False
    if text[token_start : index + 1].casefold() in _ABBREVIATIONS:
        return False
    return index + 1 == len(text) or text[index + 1].isspace()


def _without_nominal_coordination(text: str) -> str:
    """Remove only connectors joining adjacent capitalized nominal tokens."""
    value = text
    while True:
        value, replacements = _NOMINAL_COORDINATION.subn("\\g<left> \\g<right>", value)
        if replacements == 0:
            return value


def exact_text_spans(text: str) -> tuple[TextSpan, ...]:
    """Split text without rewriting it; offsets are Unicode code points."""
    if not isinstance(text, str) or unicodedata.normalize("NFC", text) != text:
        raise ClaimBoundaryError(ClaimReasonCode.CLAIM_TEXT_MISMATCH)
    spans: list[TextSpan] = []
    start = 0
    for index, character in enumerate(text):
        boundary = character in "\n\r;?!"
        if character == ".":
            boundary = _period_is_boundary(text, index)
        if not boundary:
            continue
        end = index if character in "\n\r" else index + 1
        span = _trim_span(text, start, end)
        if span is not None:
            spans.append(span)
        start = index + 1
    span = _trim_span(text, start, len(text))
    if span is not None:
        spans.append(span)
    return tuple(spans)


def classify_claim(text: str) -> tuple[ClaimType, ClaimAtomicity]:
    normalized = normalize_claim_for_match(text)
    if text.rstrip().endswith("?") or normalized.startswith(_NON_FACTUAL_PREFIXES):
        return (ClaimType.NON_FACTUAL, ClaimAtomicity.NON_FACTUAL)
    if any((marker in normalized for marker in _SOURCE_MARKERS)):
        claim_type = ClaimType.SOURCE_ASSERTION
    elif any((marker in normalized for marker in _TEMPORAL_MARKERS)):
        claim_type = ClaimType.TEMPORAL
    elif any((marker in normalized for marker in _LEGAL_MARKERS)):
        claim_type = ClaimType.LEGAL_NORM
    elif _DATE_OR_NUMBER.search(normalized):
        claim_type = ClaimType.QUANTITATIVE
    elif any((marker in normalized for marker in _RELATIONAL_MARKERS)):
        claim_type = ClaimType.RELATIONAL
    else:
        claim_type = ClaimType.FACTUAL
    atomicity = (
        ClaimAtomicity.COMPOUND
        if _COMPOUND.search(_without_nominal_coordination(text))
        else ClaimAtomicity.ATOMIC
    )
    return (claim_type, atomicity)


_TOKEN = re.compile("[^\\W_]+", re.UNICODE)
_GERMAN_MONTH_NAMES = frozenset(
    {
        "januar",
        "februar",
        "märz",
        "april",
        "mai",
        "juni",
        "juli",
        "august",
        "september",
        "oktober",
        "november",
        "dezember",
    }
)
_NEGATIONS = frozenset(
    {
        "kein",
        "keine",
        "keinen",
        "keiner",
        "keines",
        "keinem",
        "nicht",
        "nie",
        "niemals",
        "no",
        "not",
        "never",
    }
)
_STOPWORDS = frozenset(
    {
        "aber",
        "als",
        "and",
        "auch",
        "das",
        "dem",
        "den",
        "der",
        "des",
        "die",
        "ein",
        "eine",
        "einer",
        "eines",
        "für",
        "in",
        "ist",
        "mit",
        "oder",
        "the",
        "und",
        "von",
        "zu",
    }
)


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(normalize_claim_for_match(value)))


def _negation_counterparts(left: str, right: str) -> bool:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    left_negations = tuple((token for token in left_tokens if token in _NEGATIONS))
    right_negations = tuple((token for token in right_tokens if token in _NEGATIONS))
    if (len(left_negations), len(right_negations)) not in {(1, 0), (0, 1)}:
        return False
    left_base = tuple((token for token in left_tokens if token not in _NEGATIONS))
    right_base = tuple((token for token in right_tokens if token not in _NEGATIONS))
    return bool(left_base) and left_base == right_base


def _quantitative_counterparts(left: str, right: str) -> bool:
    """Detect a changed date/number in otherwise closely aligned claims."""
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)

    def facts(tokens: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            (
                token
                for token in tokens
                if token.isdigit() or token in _GERMAN_MONTH_NAMES
            )
        )

    left_facts = facts(left_tokens)
    right_facts = facts(right_tokens)
    if not left_facts or not right_facts or left_facts == right_facts:
        return False
    excluded = _STOPWORDS | _GERMAN_MONTH_NAMES
    left_base = {
        token for token in left_tokens if not token.isdigit() and token not in excluded
    }
    right_base = {
        token for token in right_tokens if not token.isdigit() and token not in excluded
    }
    shared = left_base & right_base
    smaller = min(len(left_base), len(right_base))
    return smaller >= 3 and len(shared) * 4 >= smaller * 3


def _related(left: str, right: str) -> bool:
    left_tokens = {token for token in _tokens(left) if token not in _STOPWORDS}
    right_tokens = {token for token in _tokens(right) if token not in _STOPWORDS}
    shared = left_tokens & right_tokens
    return (
        bool(left_tokens)
        and bool(right_tokens)
        and (len(shared) >= 2)
        and (len(shared) * 2 >= min(len(left_tokens), len(right_tokens)))
    )


def _text_relation(
    claim: ClaimRecord, evidence: TextSpan
) -> ClaimEvidenceRelation | None:
    if claim.normalized_match_text == normalize_claim_for_match(evidence.text):
        return ClaimEvidenceRelation.SUPPORTS
    if _negation_counterparts(claim.exact_claim_text, evidence.text):
        return ClaimEvidenceRelation.REFUTES
    if _quantitative_counterparts(claim.exact_claim_text, evidence.text):
        return ClaimEvidenceRelation.REFUTES
    if _related(claim.exact_claim_text, evidence.text):
        return ClaimEvidenceRelation.RELATED_ONLY
    return None


@dataclass(frozen=True, slots=True, repr=False)
class NativeDraft:
    scope: OwnerScope
    hat_id: str
    draft_id: str
    text: str
    draft_hash: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        bounded_text(self.hat_id)
        bounded_text(self.draft_id)
        bounded_text(self.text, 65536)
        if unicodedata.normalize("NFC", self.text) != self.text:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        object.__setattr__(
            self, "draft_hash", canonical_sha256(self, exclude_fields=("draft_hash",))
        )


@dataclass(frozen=True, slots=True, repr=False)
class NativeClaimLink:
    item_hash: str
    evidence_id: str
    relation: ClaimEvidenceRelation
    start_offset: int
    end_offset: int
    exact_source_text: str


@dataclass(frozen=True, slots=True, repr=False)
class NativeClaimAssessment:
    claim: ClaimRecord
    status: ClaimEvidenceCandidateStatus
    links: tuple[NativeClaimLink, ...]


@dataclass(frozen=True, slots=True, repr=False)
class NativeClaimAnalysis:
    draft: NativeDraft
    bundle_hash: str
    assessments: tuple[NativeClaimAssessment, ...]
    review_required: bool
    analysis_hash: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(
            self,
            "analysis_hash",
            canonical_sha256(self, exclude_fields=("analysis_hash",)),
        )


def extract_native_claims(draft: NativeDraft) -> tuple[ClaimRecord, ...]:
    if draft.draft_hash != canonical_sha256(draft, exclude_fields=("draft_hash",)):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    spans = exact_text_spans(draft.text)
    if len(spans) > load_claim_processing_policy().maximum_claims:
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    claims = []
    for span in spans:
        claim_type, atomicity = classify_claim(span.text)
        reasons = [ClaimReasonCode.CLAIM_EXTRACTED]
        if atomicity is ClaimAtomicity.COMPOUND:
            reasons.append(ClaimReasonCode.CLAIM_COMPOUND)
        if atomicity is ClaimAtomicity.NON_FACTUAL:
            reasons.append(ClaimReasonCode.CLAIM_NON_FACTUAL)
        claim = ClaimRecord(
            draft.draft_id,
            draft.draft_hash,
            span.start_offset,
            span.end_offset,
            span.text,
            normalize_claim_for_match(span.text),
            claim_type,
            atomicity,
            trusted_dimensions(draft.scope, draft.hat_id),
            reason_codes(*reasons),
        )
        verify_claim_record_hash(claim)
        if draft.text[claim.start_offset : claim.end_offset] != claim.exact_claim_text:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        claims.append(claim)
    return tuple(claims)


class NativeClaims:
    def __init__(self, core: CoreAdmission, retrieval: NativeRetrieval):
        self.core, self.retrieval = core, retrieval

    def assess(
        self,
        principal: CorePrincipal,
        draft: NativeDraft,
        bundle: FrozenEvidenceBundle,
        *,
        mode=TemporalQueryMode.CURRENT,
        as_of=None,
    ) -> NativeClaimAnalysis:
        if principal.capability not in {
            Capability.READ,
            Capability.VALIDATE,
            Capability.PROPOSE,
        }:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        return self.assess_bound(principal, draft, bundle, mode=mode, as_of=as_of)

    def assess_bound(
        self, principal, draft, bundle, *, mode=TemporalQueryMode.CURRENT, as_of=None
    ):
        """Revalidation under an existing Core operation; no capability minting."""
        if principal.capability not in {
            Capability.READ,
            Capability.PROPOSE,
            Capability.VALIDATE,
            Capability.OWNER_APPROVAL,
            Capability.COMMIT,
            Capability.ACTIVATE,
            Capability.MANAGE,
        }:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        self.core.require(principal, principal.capability, scope=draft.scope)
        self.retrieval.require_bundle(principal, bundle)
        if draft.scope != bundle.scope or draft.hat_id != bundle.hat_scope_id:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        temporal = resolve_temporal(
            bundle,
            mode=mode,
            trusted_now=self.retrieval.clock(),
            as_of=as_of,
            freshness=self.retrieval.freshness,
        )
        eligible = {i.item_hash for i in temporal.applicable_items}
        assessments = []
        for claim in extract_native_claims(draft):
            links = []
            for item in bundle.items:
                for span in exact_text_spans(item.excerpt.text):
                    relation = _text_relation(claim, span)
                    if relation is None:
                        continue
                    if item.item_hash not in eligible or (
                        claim.claim_type is ClaimType.SOURCE_ASSERTION
                        and item.authority_level.value != "OFFICIAL_PRIMARY"
                    ):
                        relation = ClaimEvidenceRelation.INSUFFICIENT
                    links.append(
                        NativeClaimLink(
                            item.item_hash,
                            item.evidence_id,
                            relation,
                            span.start_offset,
                            span.end_offset,
                            span.text,
                        )
                    )
            if len(links) > load_claim_processing_policy().maximum_evidence_links:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            relations = {link.relation for link in links}
            status = ClaimEvidenceCandidateStatus.UNVERIFIED
            if claim.atomicity is ClaimAtomicity.ATOMIC:
                if (
                    ClaimEvidenceRelation.SUPPORTS in relations
                    and ClaimEvidenceRelation.REFUTES not in relations
                ):
                    status = ClaimEvidenceCandidateStatus.SUPPORTED
                elif (
                    ClaimEvidenceRelation.REFUTES in relations
                    and ClaimEvidenceRelation.SUPPORTS not in relations
                ):
                    status = ClaimEvidenceCandidateStatus.REFUTED
            assessments.append(NativeClaimAssessment(claim, status, tuple(links)))
        review = (
            temporal.review_required
            or not assessments
            or any(
                a.status is not ClaimEvidenceCandidateStatus.SUPPORTED
                for a in assessments
            )
        )
        return NativeClaimAnalysis(
            draft, bundle.bundle_hash, tuple(assessments), review
        )
