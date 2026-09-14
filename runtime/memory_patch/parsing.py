"""Native deterministic parsing of explicitly admitted immutable snapshots. Retained pure normalization/chunk/hash algorithms never fetch, execute, or publish content."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Callable

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal
from runtime.evidence_admission import InputOrigin
from runtime.memory_patch.acquisition import AcquiredSnapshot
from runtime.memory_patch.contracts.enums import StableStringEnum
from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
    ensure_utc,
    freeze_json,
    require_sha256_hex,
    sha256_hex,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.source_lineage import SourceLicenseStatus


class ParsingError(RuntimeError):
    """Base parsing error whose public code is safe to persist."""

    def __init__(self, message: str, *, sanitized_code: str) -> None:
        super().__init__(message)
        self.sanitized_code = sanitized_code


class ParsingValidationError(ParsingError):
    """A typed contract, identity, or structural validation failure."""


class UnsupportedMediaTypeError(ParsingError):
    """No exact immutable parser profile exists for the media type."""


class ParsingResourceLimitError(ParsingError):
    """A versioned Step 11 resource limit was exceeded."""


class ParsingPersistenceConflictError(ParsingError):
    """A deterministic identity is already bound to different facts."""


class ParsingQuarantineError(ParsingError):
    """The parse result requires deterministic quarantine or review."""


PARSING_SCHEMA_VERSION = "1.0.0"
PARSER_CONTRACT_VERSION = "generic-parsing-pipeline-1a"
VALIDATOR_CONTRACT_VERSION = "generic-parse-artifact-validator-1a"
NORMALIZATION_PROFILE_NAME = "unicode-nfc-text-normalization"
NORMALIZATION_PROFILE_VERSION = "1.0.0"
CHUNKING_PROFILE_NAME = "model-neutral-character-chunking"
CHUNKING_PROFILE_VERSION = "1.0.0"
SECURITY_RULESET_NAME = "prompt-injection-static-rules"
SECURITY_RULESET_VERSION = "1.0.0"
OFFSET_BASIS = "NORMALIZED_UNICODE_CODE_POINTS_NFC"
_IDENTIFIER = re.compile("^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_VERSION = re.compile("^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_MEDIA_TYPE = re.compile(
    "^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$"
)
_CODE = re.compile("^[A-Z0-9][A-Z0-9_:-]{0,127}$")
_DOCUMENT_ID = re.compile("^parsedoc-[0-9a-f]{64}$")
_SECTION_ID = re.compile("^parsesection-[0-9a-f]{64}$")
_CHUNK_ID = re.compile("^parsechunk-[0-9a-f]{64}$")
_FINDING_ID = re.compile("^parsefinding-[0-9a-f]{64}$")
_LANGUAGE_TAG = re.compile(
    "^(?:[A-Za-z]{2,3}(?:-[A-Za-z]{3}){0,3}|[A-Za-z]{4}|[A-Za-z]{5,8})(?:-[A-Za-z]{4})?(?:-(?:[A-Za-z]{2}|[0-9]{3}))?(?:-(?:[A-Za-z0-9]{5,8}|[0-9][A-Za-z0-9]{3}))*(?:-[0-9A-WY-Za-wy-z](?:-[A-Za-z0-9]{2,8})+)*(?:-x(?:-[A-Za-z0-9]{1,8})+)?$"
)


def _text(value: object, field_name: str, maximum: int = 255) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or (len(value) > maximum)
        or any((ord(character) < 32 for character in value))
    ):
        raise ParsingValidationError(
            f"{field_name} must be a bounded canonical string",
            sanitized_code="INVALID_PARSING_VALUE",
        )
    return value


def _identifier(value: object, field_name: str) -> str:
    text = _text(value, field_name)
    if _IDENTIFIER.fullmatch(text) is None:
        raise ParsingValidationError(
            f"{field_name} is not a canonical identifier",
            sanitized_code="INVALID_PARSING_IDENTIFIER",
        )
    return text


def _optional_identifier(value: object | None, field_name: str) -> str | None:
    return None if value is None else _identifier(value, field_name)


def _digest(value: object, field_name: str) -> str:
    try:
        return require_sha256_hex(value, field_name)
    except Exception as exc:
        raise ParsingValidationError(
            f"{field_name} must be a lowercase SHA-256 digest",
            sanitized_code="INVALID_PARSING_DIGEST",
        ) from exc


def _timestamp(value: object, field_name: str) -> datetime:
    try:
        return ensure_utc(value, field_name)
    except Exception as exc:
        raise ParsingValidationError(
            f"{field_name} must be timezone-aware",
            sanitized_code="INVALID_PARSING_TIMESTAMP",
        ) from exc


def _version(value: object, field_name: str) -> str:
    result = _text(value, field_name, 64)
    if _VERSION.fullmatch(result) is None or result.casefold() == "latest":
        raise ParsingValidationError(
            f"{field_name} must be an immutable explicit version",
            sanitized_code="MUTABLE_PARSER_VERSION_ALIAS",
        )
    return result


def _metadata(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ParsingValidationError(
            f"{field_name} must be a mapping", sanitized_code="INVALID_PARSING_METADATA"
        )
    try:
        frozen = freeze_json(value)
        encoded = canonical_json_bytes(frozen)
    except Exception as exc:
        raise ParsingValidationError(
            f"{field_name} is not canonical JSON data",
            sanitized_code="INVALID_PARSING_METADATA",
        ) from exc
    if len(encoded) > 16 * 1024:
        raise ParsingValidationError(
            f"{field_name} exceeds the metadata bound",
            sanitized_code="RESOURCE_LIMIT_EXCEEDED",
        )
    assert isinstance(frozen, Mapping)
    return frozen


def _codes(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise ParsingValidationError(
            f"{field_name} must be an immutable tuple",
            sanitized_code="INVALID_PARSING_VALUE",
        )
    result = tuple(sorted({_text(value, field_name, 128) for value in values}))
    if result != values or any((_CODE.fullmatch(value) is None for value in result)):
        raise ParsingValidationError(
            f"{field_name} must contain sorted unique reason codes",
            sanitized_code="INVALID_PARSING_VALUE",
        )
    return result


class SectionKind(StableStringEnum):
    TEXT_BLOCK = "TEXT_BLOCK"
    JSON_VALUE = "JSON_VALUE"


class FindingSeverity(StableStringEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class FindingAction(StableStringEnum):
    RECORD_ONLY = "RECORD_ONLY"
    OPERATOR_REVIEW = "OPERATOR_REVIEW"
    QUARANTINE = "QUARANTINE"


class FindingCategory(StableStringEnum):
    ROLE_OR_SYSTEM_INSTRUCTION_MARKER = "ROLE_OR_SYSTEM_INSTRUCTION_MARKER"
    INSTRUCTION_OVERRIDE_PHRASE = "INSTRUCTION_OVERRIDE_PHRASE"
    TOOL_OR_COMMAND_EXECUTION_REQUEST = "TOOL_OR_COMMAND_EXECUTION_REQUEST"
    SECRET_OR_CREDENTIAL_EXFILTRATION_REQUEST = (
        "SECRET_OR_CREDENTIAL_EXFILTRATION_REQUEST"
    )
    REMOTE_OR_INDIRECT_INSTRUCTION = "REMOTE_OR_INDIRECT_INSTRUCTION"
    HIDDEN_MARKUP_OR_COMMENT_INSTRUCTION = "HIDDEN_MARKUP_OR_COMMENT_INSTRUCTION"
    ENCODED_OR_OBFUSCATED_INSTRUCTION_SIGNAL = (
        "ENCODED_OR_OBFUSCATED_INSTRUCTION_SIGNAL"
    )
    ZERO_WIDTH_OR_BIDI_CONTROL_SIGNAL = "ZERO_WIDTH_OR_BIDI_CONTROL_SIGNAL"
    RAG_POISONING_OR_RETRIEVAL_MANIPULATION_SIGNAL = (
        "RAG_POISONING_OR_RETRIEVAL_MANIPULATION_SIGNAL"
    )


class QuarantineReason(StableStringEnum):
    UNSUPPORTED_MEDIA_TYPE = "UNSUPPORTED_MEDIA_TYPE"
    INPUT_DIGEST_MISMATCH = "INPUT_DIGEST_MISMATCH"
    INPUT_LENGTH_MISMATCH = "INPUT_LENGTH_MISMATCH"
    INVALID_UTF8 = "INVALID_UTF8"
    PROHIBITED_CONTROL_CHARACTER = "PROHIBITED_CONTROL_CHARACTER"
    JSON_SYNTAX_INVALID = "JSON_SYNTAX_INVALID"
    JSON_DUPLICATE_MEMBER = "JSON_DUPLICATE_MEMBER"
    JSON_NONFINITE_NUMBER = "JSON_NONFINITE_NUMBER"
    JSON_DEPTH_LIMIT = "JSON_DEPTH_LIMIT"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    NORMALIZATION_FAILURE = "NORMALIZATION_FAILURE"
    NORMALIZATION_NON_IDEMPOTENT = "NORMALIZATION_NON_IDEMPOTENT"
    SECTION_RANGE_INVALID = "SECTION_RANGE_INVALID"
    SECTION_CONTENT_MISMATCH = "SECTION_CONTENT_MISMATCH"
    CHUNK_RANGE_INVALID = "CHUNK_RANGE_INVALID"
    CHUNK_CONTENT_MISMATCH = "CHUNK_CONTENT_MISMATCH"
    CHUNK_COVERAGE_INVALID = "CHUNK_COVERAGE_INVALID"
    SECURITY_FINDING_LIMIT_EXCEEDED = "SECURITY_FINDING_LIMIT_EXCEEDED"
    BLOCKING_PROMPT_INJECTION_SIGNAL = "BLOCKING_PROMPT_INJECTION_SIGNAL"
    PERSISTENCE_CONFLICT = "PERSISTENCE_CONFLICT"
    PARSE_RECEIPT_BINDING_MISMATCH = "PARSE_RECEIPT_BINDING_MISMATCH"
    VALIDATION_RECEIPT_BINDING_MISMATCH = "VALIDATION_RECEIPT_BINDING_MISMATCH"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Versioned, hardware-bounded limits with no silent truncation."""

    policy_name: str = "generic-parsing-resource-limits"
    policy_version: str = "1.0.0"
    maximum_input_bytes: int = 64 * 1024 * 1024
    maximum_decoded_characters: int = 8 * 1024 * 1024
    maximum_json_depth: int = 64
    maximum_json_members: int = 100000
    maximum_json_array_length: int = 100000
    maximum_string_length: int = 1 * 1024 * 1024
    maximum_sections: int = 100000
    maximum_section_length: int = 4 * 1024 * 1024
    maximum_chunks: int = 100000
    maximum_chunk_length: int = 1024
    maximum_security_findings: int = 1024
    maximum_metadata_bytes: int = 16 * 1024
    maximum_recursion_depth: int = 64

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "policy_name", _identifier(self.policy_name, "policy_name")
        )
        object.__setattr__(
            self, "policy_version", _version(self.policy_version, "policy_version")
        )
        for field_name in (
            "maximum_input_bytes",
            "maximum_decoded_characters",
            "maximum_json_depth",
            "maximum_json_members",
            "maximum_json_array_length",
            "maximum_string_length",
            "maximum_sections",
            "maximum_section_length",
            "maximum_chunks",
            "maximum_chunk_length",
            "maximum_security_findings",
            "maximum_metadata_bytes",
            "maximum_recursion_depth",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ParsingValidationError(
                    f"{field_name} must be a positive integer",
                    sanitized_code="INVALID_RESOURCE_POLICY",
                )
        if self.maximum_input_bytes > 64 * 1024 * 1024:
            raise ParsingValidationError(
                "Step 11 input cannot exceed the Step 10 storage bound",
                sanitized_code="INVALID_RESOURCE_POLICY",
            )

    @property
    def policy_digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class NormalizationProfile:
    name: str = NORMALIZATION_PROFILE_NAME
    version: str = NORMALIZATION_PROFILE_VERSION
    unicode_form: str = "NFC"
    encoding: str = "UTF-8-STRICT"
    bom_policy: str = "ALLOW_ONE_LEADING_UTF8_BOM"
    line_ending_policy: str = "CRLF_AND_CR_TO_LF"
    final_newline_policy: str = "PRESERVE_EXACTLY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "normalization_name"))
        object.__setattr__(
            self, "version", _version(self.version, "normalization_version")
        )
        if self.unicode_form != "NFC":
            raise ParsingValidationError(
                "Step 11 permits only canonical NFC normalization",
                sanitized_code="INVALID_NORMALIZATION_PROFILE",
            )
        for field_name in (
            "encoding",
            "bom_policy",
            "line_ending_policy",
            "final_newline_policy",
        ):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name, 128)
            )

    @property
    def profile_id(self) -> str:
        return f"{self.name}:{self.version}"

    @property
    def profile_digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class ParserProfile:
    name: str
    version: str
    contract_version: str
    media_type: str
    normalization: NormalizationProfile = field(default_factory=NormalizationProfile)

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "parser_name"))
        object.__setattr__(self, "version", _version(self.version, "parser_version"))
        object.__setattr__(
            self,
            "contract_version",
            _version(self.contract_version, "parser_contract_version"),
        )
        if (
            not isinstance(self.media_type, str)
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
        ):
            raise ParsingValidationError(
                "media_type must be an exact canonical type/subtype",
                sanitized_code="INVALID_PARSER_MEDIA_TYPE",
            )
        if not isinstance(self.normalization, NormalizationProfile):
            raise ParsingValidationError(
                "parser requires a typed normalization profile",
                sanitized_code="INVALID_NORMALIZATION_PROFILE",
            )

    @property
    def profile_digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class ChunkingProfile:
    name: str = CHUNKING_PROFILE_NAME
    version: str = CHUNKING_PROFILE_VERSION
    maximum_characters: int = 1024
    target_characters: int = 896
    minimum_characters: int = 1
    overlap_characters: int = 64
    boundary_search_window: int = 160
    boundary_priority: tuple[str, ...] = (
        "SECTION_END",
        "LINE_BREAK",
        "SENTENCE_WHITESPACE",
        "WHITESPACE",
        "SAFE_HARD_CUT",
    )
    cross_section_chunks: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "chunking_name"))
        object.__setattr__(self, "version", _version(self.version, "chunking_version"))
        for field_name in (
            "maximum_characters",
            "target_characters",
            "minimum_characters",
            "boundary_search_window",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ParsingValidationError(
                    f"{field_name} must be positive",
                    sanitized_code="INVALID_CHUNKING_PROFILE",
                )
        if (
            not isinstance(self.overlap_characters, int)
            or isinstance(self.overlap_characters, bool)
            or self.overlap_characters < 0
            or (self.minimum_characters > self.target_characters)
            or (self.target_characters > self.maximum_characters)
            or (self.overlap_characters >= self.maximum_characters)
        ):
            raise ParsingValidationError(
                "chunking size and overlap values are inconsistent",
                sanitized_code="INVALID_CHUNKING_PROFILE",
            )
        expected = (
            "SECTION_END",
            "LINE_BREAK",
            "SENTENCE_WHITESPACE",
            "WHITESPACE",
            "SAFE_HARD_CUT",
        )
        if self.boundary_priority != expected or self.cross_section_chunks is not False:
            raise ParsingValidationError(
                "Step 11 1A requires the fixed within-section boundary policy",
                sanitized_code="INVALID_CHUNKING_PROFILE",
            )

    @property
    def profile_digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True)
class LanguageTag:
    """Validated, descriptive BCP 47-style language metadata."""

    value: str

    def __post_init__(self) -> None:
        value = _text(self.value, "language_tag", 63)
        if _LANGUAGE_TAG.fullmatch(value) is None:
            raise ParsingValidationError(
                "language_tag is not a supported BCP 47-style tag",
                sanitized_code="INVALID_LANGUAGE_TAG",
            )
        object.__setattr__(self, "value", value)


@dataclass(frozen=True, slots=True)
class ParsedSection:
    document_id: str
    section_id: str
    section_ordinal: int
    parent_section_id: str | None
    section_kind: SectionKind
    structural_locator: str | None
    normalized_start_offset: int
    normalized_end_offset: int
    content: str = field(repr=False)
    content_sha256: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    parser_profile_digest: str = ""
    offset_basis: str = OFFSET_BASIS

    def __post_init__(self) -> None:
        if _DOCUMENT_ID.fullmatch(self.document_id) is None:
            raise ParsingValidationError(
                "section document_id is invalid", sanitized_code="SECTION_RANGE_INVALID"
            )
        if not isinstance(self.section_kind, SectionKind):
            raise ParsingValidationError(
                "section_kind has the wrong type",
                sanitized_code="SECTION_RANGE_INVALID",
            )
        if (
            not isinstance(self.section_ordinal, int)
            or isinstance(self.section_ordinal, bool)
            or self.section_ordinal < 0
            or (not isinstance(self.normalized_start_offset, int))
            or (not isinstance(self.normalized_end_offset, int))
            or (self.normalized_start_offset < 0)
            or (self.normalized_end_offset <= self.normalized_start_offset)
        ):
            raise ParsingValidationError(
                "section requires a valid half-open code-point range",
                sanitized_code="SECTION_RANGE_INVALID",
            )
        if not isinstance(self.content, str) or not self.content:
            raise ParsingValidationError(
                "section content must be non-empty text",
                sanitized_code="SECTION_CONTENT_MISMATCH",
            )
        digest = sha256_hex(self.content)
        if self.content_sha256:
            if _digest(self.content_sha256, "section_content_sha256") != digest:
                raise ParsingValidationError(
                    "section content digest mismatch",
                    sanitized_code="SECTION_CONTENT_MISMATCH",
                )
        else:
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "parser_profile_digest",
            _digest(self.parser_profile_digest, "parser_profile_digest"),
        )
        object.__setattr__(
            self, "metadata", _metadata(self.metadata, "section_metadata")
        )
        if self.offset_basis != OFFSET_BASIS:
            raise ParsingValidationError(
                "section offset basis is unsupported",
                sanitized_code="SECTION_RANGE_INVALID",
            )
        if (
            self.parent_section_id is not None
            and _SECTION_ID.fullmatch(self.parent_section_id) is None
        ):
            raise ParsingValidationError(
                "section parent identity is invalid",
                sanitized_code="SECTION_RANGE_INVALID",
            )
        if self.structural_locator is not None:
            object.__setattr__(
                self,
                "structural_locator",
                _text(self.structural_locator, "structural_locator", 2048),
            )
        identity = canonical_sha256(
            {
                "document_id": self.document_id,
                "section_ordinal": self.section_ordinal,
                "parent_section_id": self.parent_section_id,
                "section_kind": self.section_kind,
                "structural_locator": self.structural_locator,
                "normalized_start_offset": self.normalized_start_offset,
                "normalized_end_offset": self.normalized_end_offset,
                "content_sha256": self.content_sha256,
                "metadata": self.metadata,
                "parser_profile_digest": self.parser_profile_digest,
                "offset_basis": self.offset_basis,
            }
        )
        expected_id = f"parsesection-{identity}"
        if self.section_id:
            if self.section_id != expected_id:
                raise ParsingValidationError(
                    "section_id differs from immutable facts",
                    sanitized_code="SECTION_CONTENT_MISMATCH",
                )
        else:
            object.__setattr__(self, "section_id", expected_id)


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    tenant_id: str
    source_id: str
    hat_scope_id: str
    knowledge_version_id: str
    document_id: str
    section_id: str
    chunk_id: str
    chunk_ordinal: int
    section_chunk_ordinal: int
    normalized_start_offset: int
    normalized_end_offset: int
    content: str = field(repr=False)
    content_sha256: str = ""
    chunking_profile_digest: str = ""
    overlap_prefix_characters: int = 0
    language_tag: LanguageTag | None = None
    offset_basis: str = OFFSET_BASIS

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "source_id",
            "hat_scope_id",
            "knowledge_version_id",
        ):
            object.__setattr__(
                self, field_name, _identifier(getattr(self, field_name), field_name)
            )
        if (
            _DOCUMENT_ID.fullmatch(self.document_id) is None
            or _SECTION_ID.fullmatch(self.section_id) is None
        ):
            raise ParsingValidationError(
                "chunk document or section identity is invalid",
                sanitized_code="CHUNK_RANGE_INVALID",
            )
        for field_name in (
            "chunk_ordinal",
            "section_chunk_ordinal",
            "normalized_start_offset",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ParsingValidationError(
                    f"{field_name} is invalid", sanitized_code="CHUNK_RANGE_INVALID"
                )
        if (
            not isinstance(self.normalized_end_offset, int)
            or self.normalized_end_offset <= self.normalized_start_offset
            or (not isinstance(self.content, str))
            or (not self.content)
        ):
            raise ParsingValidationError(
                "chunk requires non-empty content and a valid range",
                sanitized_code="CHUNK_RANGE_INVALID",
            )
        if (
            not isinstance(self.overlap_prefix_characters, int)
            or isinstance(self.overlap_prefix_characters, bool)
            or self.overlap_prefix_characters < 0
            or (self.overlap_prefix_characters >= len(self.content))
        ):
            raise ParsingValidationError(
                "chunk overlap metadata is invalid",
                sanitized_code="CHUNK_RANGE_INVALID",
            )
        digest = sha256_hex(self.content)
        if self.content_sha256:
            if _digest(self.content_sha256, "chunk_content_sha256") != digest:
                raise ParsingValidationError(
                    "chunk content digest mismatch",
                    sanitized_code="CHUNK_CONTENT_MISMATCH",
                )
        else:
            object.__setattr__(self, "content_sha256", digest)
        object.__setattr__(
            self,
            "chunking_profile_digest",
            _digest(self.chunking_profile_digest, "chunking_profile_digest"),
        )
        if self.language_tag is not None and (
            not isinstance(self.language_tag, LanguageTag)
        ):
            raise ParsingValidationError(
                "chunk language_tag requires a typed tag",
                sanitized_code="INVALID_LANGUAGE_TAG",
            )
        if self.offset_basis != OFFSET_BASIS:
            raise ParsingValidationError(
                "chunk offset basis is unsupported",
                sanitized_code="CHUNK_RANGE_INVALID",
            )
        identity = canonical_sha256(
            {
                "tenant_id": self.tenant_id,
                "source_id": self.source_id,
                "hat_scope_id": self.hat_scope_id,
                "knowledge_version_id": self.knowledge_version_id,
                "document_id": self.document_id,
                "section_id": self.section_id,
                "chunk_ordinal": self.chunk_ordinal,
                "section_chunk_ordinal": self.section_chunk_ordinal,
                "normalized_start_offset": self.normalized_start_offset,
                "normalized_end_offset": self.normalized_end_offset,
                "content_sha256": self.content_sha256,
                "chunking_profile_digest": self.chunking_profile_digest,
                "overlap_prefix_characters": self.overlap_prefix_characters,
                "language_tag": None
                if self.language_tag is None
                else self.language_tag.value,
                "offset_basis": self.offset_basis,
            }
        )
        expected_id = f"parsechunk-{identity}"
        if self.chunk_id:
            if self.chunk_id != expected_id:
                raise ParsingValidationError(
                    "chunk_id differs from immutable facts",
                    sanitized_code="CHUNK_CONTENT_MISMATCH",
                )
        else:
            object.__setattr__(self, "chunk_id", expected_id)


@dataclass(frozen=True, slots=True)
class PromptInjectionFinding:
    document_id: str
    finding_id: str
    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    normalized_start_offset: int
    normalized_end_offset: int
    section_id: str | None
    evidence_excerpt_sha256: str
    action: FindingAction
    ruleset_name: str = SECURITY_RULESET_NAME
    ruleset_version: str = SECURITY_RULESET_VERSION
    finding_digest: str = ""

    def __post_init__(self) -> None:
        if _DOCUMENT_ID.fullmatch(self.document_id) is None:
            raise ParsingValidationError(
                "finding document identity is invalid",
                sanitized_code="INVALID_SECURITY_FINDING",
            )
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id", 128))
        if (
            not isinstance(self.category, FindingCategory)
            or not isinstance(self.severity, FindingSeverity)
            or (not isinstance(self.action, FindingAction))
        ):
            raise ParsingValidationError(
                "finding enum value is invalid",
                sanitized_code="INVALID_SECURITY_FINDING",
            )
        if (
            not isinstance(self.normalized_start_offset, int)
            or not isinstance(self.normalized_end_offset, int)
            or self.normalized_start_offset < 0
            or (self.normalized_end_offset <= self.normalized_start_offset)
        ):
            raise ParsingValidationError(
                "finding range is invalid", sanitized_code="INVALID_SECURITY_FINDING"
            )
        if (
            self.section_id is not None
            and _SECTION_ID.fullmatch(self.section_id) is None
        ):
            raise ParsingValidationError(
                "finding section identity is invalid",
                sanitized_code="INVALID_SECURITY_FINDING",
            )
        object.__setattr__(
            self,
            "evidence_excerpt_sha256",
            _digest(self.evidence_excerpt_sha256, "evidence_excerpt_sha256"),
        )
        object.__setattr__(
            self, "ruleset_name", _identifier(self.ruleset_name, "ruleset_name")
        )
        object.__setattr__(
            self, "ruleset_version", _version(self.ruleset_version, "ruleset_version")
        )
        digest = canonical_sha256(self, exclude_fields=("finding_id", "finding_digest"))
        if self.finding_digest:
            if _digest(self.finding_digest, "finding_digest") != digest:
                raise ParsingValidationError(
                    "finding digest mismatch", sanitized_code="INVALID_SECURITY_FINDING"
                )
        else:
            object.__setattr__(self, "finding_digest", digest)
        expected_id = f"parsefinding-{digest}"
        if self.finding_id:
            if self.finding_id != expected_id:
                raise ParsingValidationError(
                    "finding identity mismatch",
                    sanitized_code="INVALID_SECURITY_FINDING",
                )
        else:
            object.__setattr__(self, "finding_id", expected_id)


@dataclass(frozen=True, slots=True)
class QuarantineDecision:
    required: bool
    reason_codes: tuple[str, ...]
    decision_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.required, bool):
            raise ParsingValidationError(
                "quarantine marker must be boolean",
                sanitized_code="INVALID_QUARANTINE_DECISION",
            )
        object.__setattr__(
            self, "reason_codes", _codes(self.reason_codes, "quarantine_reason_codes")
        )
        if self.required != bool(self.reason_codes):
            raise ParsingValidationError(
                "quarantine marker and reasons must agree",
                sanitized_code="INVALID_QUARANTINE_DECISION",
            )
        digest = canonical_sha256(self, exclude_fields=("decision_digest",))
        if self.decision_digest:
            if _digest(self.decision_digest, "decision_digest") != digest:
                raise ParsingValidationError(
                    "quarantine decision digest mismatch",
                    sanitized_code="INVALID_QUARANTINE_DECISION",
                )
        else:
            object.__setattr__(self, "decision_digest", digest)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    tenant_id: str
    owner_user_id: str | None
    saga_id: str
    source_id: str
    snapshot_id: str
    knowledge_version_id: str
    knowledge_version_ordinal: int
    hat_scope_id: str
    s3_version_id: str
    locked_storage_evidence_digest: str
    input_sha256: str
    input_byte_length: int
    media_type: str
    parser_name: str
    parser_version: str
    parser_contract_version: str
    decoder_profile: str
    bom_policy: str
    bom_observed: bool
    normalization_profile: str
    normalization_version: str
    normalized_content_sha256: str
    normalized_character_length: int
    document_id: str
    section_count: int
    chunk_count: int
    security_finding_count: int
    section_manifest_digest: str
    chunk_manifest_digest: str
    finding_manifest_digest: str
    parse_artifact_digest: str
    completed_at: datetime
    language_tag: LanguageTag | None = None
    schema_version: str = PARSING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_id",
            "saga_id",
            "source_id",
            "snapshot_id",
            "knowledge_version_id",
            "hat_scope_id",
        ):
            object.__setattr__(
                self, field_name, _identifier(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self,
            "owner_user_id",
            _optional_identifier(self.owner_user_id, "owner_user_id"),
        )
        object.__setattr__(
            self, "s3_version_id", _text(self.s3_version_id, "s3_version_id", 1024)
        )
        for field_name in (
            "locked_storage_evidence_digest",
            "input_sha256",
            "normalized_content_sha256",
            "section_manifest_digest",
            "chunk_manifest_digest",
            "finding_manifest_digest",
            "parse_artifact_digest",
        ):
            object.__setattr__(
                self, field_name, _digest(getattr(self, field_name), field_name)
            )
        if (
            not isinstance(self.media_type, str)
            or _MEDIA_TYPE.fullmatch(self.media_type) is None
        ):
            raise ParsingValidationError(
                "document media_type is invalid",
                sanitized_code="INVALID_PARSER_MEDIA_TYPE",
            )
        for field_name in ("parser_name",):
            object.__setattr__(
                self, field_name, _identifier(getattr(self, field_name), field_name)
            )
        for field_name in (
            "parser_version",
            "parser_contract_version",
            "normalization_version",
        ):
            object.__setattr__(
                self, field_name, _version(getattr(self, field_name), field_name)
            )
        for field_name in ("decoder_profile", "bom_policy", "normalization_profile"):
            object.__setattr__(
                self, field_name, _text(getattr(self, field_name), field_name, 128)
            )
        if not isinstance(self.bom_observed, bool):
            raise ParsingValidationError(
                "BOM observation must be boolean",
                sanitized_code="INVALID_PARSING_VALUE",
            )
        for field_name in (
            "input_byte_length",
            "knowledge_version_ordinal",
            "normalized_character_length",
            "section_count",
            "chunk_count",
            "security_finding_count",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ParsingValidationError(
                    f"{field_name} must be non-negative",
                    sanitized_code="INVALID_PARSING_COUNT",
                )
        if self.knowledge_version_ordinal < 1:
            raise ParsingValidationError(
                "knowledge version ordinal must be positive",
                sanitized_code="INVALID_PARSING_COUNT",
            )
        if _DOCUMENT_ID.fullmatch(self.document_id) is None:
            raise ParsingValidationError(
                "document_id is invalid", sanitized_code="INVALID_PARSED_DOCUMENT"
            )
        if self.language_tag is not None and (
            not isinstance(self.language_tag, LanguageTag)
        ):
            raise ParsingValidationError(
                "document language_tag requires a typed tag",
                sanitized_code="INVALID_LANGUAGE_TAG",
            )
        object.__setattr__(
            self, "completed_at", _timestamp(self.completed_at, "completed_at")
        )
        if self.schema_version != PARSING_SCHEMA_VERSION:
            raise ParsingValidationError(
                "parsed document schema version is unsupported",
                sanitized_code="INVALID_PARSED_DOCUMENT",
            )


@dataclass(frozen=True, slots=True)
class ParseArtifact:
    document: ParsedDocument
    normalized_text: str = field(repr=False)
    sections: tuple[ParsedSection, ...]
    chunks: tuple[ParsedChunk, ...]
    findings: tuple[PromptInjectionFinding, ...]
    quarantine: QuarantineDecision

    def __post_init__(self) -> None:
        if not isinstance(self.document, ParsedDocument) or not isinstance(
            self.normalized_text, str
        ):
            raise ParsingValidationError(
                "parse artifact requires typed document and text",
                sanitized_code="INVALID_PARSE_ARTIFACT",
            )
        for value, expected, name in (
            (self.sections, ParsedSection, "sections"),
            (self.chunks, ParsedChunk, "chunks"),
            (self.findings, PromptInjectionFinding, "findings"),
        ):
            if not isinstance(value, tuple) or any(
                (not isinstance(item, expected) for item in value)
            ):
                raise ParsingValidationError(
                    f"{name} must be an immutable typed tuple",
                    sanitized_code="INVALID_PARSE_ARTIFACT",
                )
        if not isinstance(self.quarantine, QuarantineDecision):
            raise ParsingValidationError(
                "parse artifact requires typed quarantine evidence",
                sanitized_code="INVALID_PARSE_ARTIFACT",
            )
        if (
            len(self.normalized_text) != self.document.normalized_character_length
            or sha256_hex(self.normalized_text)
            != self.document.normalized_content_sha256
        ):
            raise ParsingValidationError(
                "normalized text differs from document identity",
                sanitized_code="NORMALIZATION_FAILURE",
            )
        if (len(self.sections), len(self.chunks), len(self.findings)) != (
            self.document.section_count,
            self.document.chunk_count,
            self.document.security_finding_count,
        ):
            raise ParsingValidationError(
                "artifact counts differ from the document",
                sanitized_code="INVALID_PARSE_ARTIFACT",
            )
        section_manifest = canonical_sha256(
            tuple((section.section_id for section in self.sections))
        )
        chunk_manifest = canonical_sha256(
            tuple((chunk.chunk_id for chunk in self.chunks))
        )
        finding_manifest = canonical_sha256(
            tuple((finding.finding_id for finding in self.findings))
        )
        if (section_manifest, chunk_manifest, finding_manifest) != (
            self.document.section_manifest_digest,
            self.document.chunk_manifest_digest,
            self.document.finding_manifest_digest,
        ):
            raise ParsingValidationError(
                "artifact manifests differ from document evidence",
                sanitized_code="INVALID_PARSE_ARTIFACT",
            )
        expected_artifact = canonical_sha256(
            {
                "document_id": self.document.document_id,
                "normalized_content_sha256": self.document.normalized_content_sha256,
                "section_manifest_digest": section_manifest,
                "chunk_manifest_digest": chunk_manifest,
                "finding_manifest_digest": finding_manifest,
                "quarantine_decision_digest": self.quarantine.decision_digest,
                "parser_profile": {
                    "name": self.document.parser_name,
                    "version": self.document.parser_version,
                    "contract": self.document.parser_contract_version,
                },
                "normalization_profile": {
                    "name": self.document.normalization_profile,
                    "version": self.document.normalization_version,
                },
            }
        )
        if expected_artifact != self.document.parse_artifact_digest:
            raise ParsingValidationError(
                "parse artifact digest differs from canonical facts",
                sanitized_code="INVALID_PARSE_ARTIFACT",
            )


@dataclass(frozen=True, slots=True)
class ParseValidationResult:
    accepted: bool
    reason_codes: tuple[str, ...]
    parse_artifact_digest: str
    validation_artifact_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise ParsingValidationError(
                "validation status must be boolean",
                sanitized_code="INVALID_PARSE_VALIDATION",
            )
        object.__setattr__(
            self, "reason_codes", _codes(self.reason_codes, "validation_reason_codes")
        )
        if self.accepted == bool(self.reason_codes):
            raise ParsingValidationError(
                "accepted status and blocking reasons are inconsistent",
                sanitized_code="INVALID_PARSE_VALIDATION",
            )
        object.__setattr__(
            self,
            "parse_artifact_digest",
            _digest(self.parse_artifact_digest, "parse_artifact_digest"),
        )
        digest = canonical_sha256(self, exclude_fields=("validation_artifact_digest",))
        if self.validation_artifact_digest:
            if (
                _digest(self.validation_artifact_digest, "validation_artifact_digest")
                != digest
            ):
                raise ParsingValidationError(
                    "validation artifact digest mismatch",
                    sanitized_code="INVALID_PARSE_VALIDATION",
                )
        else:
            object.__setattr__(self, "validation_artifact_digest", digest)


UTF8_BOM = b"\xef\xbb\xbf"


@dataclass(frozen=True, slots=True)
class NormalizedText:
    text: str
    bom_observed: bool
    input_sha256: str
    input_byte_length: int
    normalized_sha256: str


def _fail_limit(message: str) -> None:
    raise ParsingResourceLimitError(message, sanitized_code="RESOURCE_LIMIT_EXCEEDED")


def decode_and_normalize(
    payload: bytes,
    *,
    expected_sha256: str,
    expected_length: int,
    profile: NormalizationProfile,
    limits: ResourceLimits,
) -> NormalizedText:
    """Verify exact bytes, decode strictly, preserve semantics, and emit NFC."""
    if not isinstance(payload, bytes):
        raise ParsingValidationError(
            "parser input must be immutable bytes",
            sanitized_code="INVALID_PARSER_INPUT",
        )
    if len(payload) != expected_length:
        raise ParsingValidationError(
            "input byte length differs from the locked snapshot",
            sanitized_code="INPUT_LENGTH_MISMATCH",
        )
    if len(payload) > limits.maximum_input_bytes:
        _fail_limit("input exceeds the Step 11 byte limit")
    digest = sha256_hex(payload)
    if digest != expected_sha256:
        raise ParsingValidationError(
            "input digest differs from the locked snapshot",
            sanitized_code="INPUT_DIGEST_MISMATCH",
        )
    if not isinstance(profile, NormalizationProfile):
        raise ParsingValidationError(
            "normalization profile has the wrong type",
            sanitized_code="INVALID_NORMALIZATION_PROFILE",
        )
    bom_observed = payload.startswith(UTF8_BOM)
    encoded = payload[len(UTF8_BOM) :] if bom_observed else payload
    try:
        decoded = encoded.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ParsingValidationError(
            "input is not strict UTF-8", sanitized_code="INVALID_UTF8"
        ) from exc
    if len(decoded) > limits.maximum_decoded_characters:
        _fail_limit("decoded text exceeds the character limit")
    normalized_lines = decoded.replace("\r\n", "\n").replace("\r", "\n")
    for character in normalized_lines:
        codepoint = ord(character)
        if character == "\x00":
            raise ParsingValidationError(
                "NUL is prohibited in parsed content",
                sanitized_code="PROHIBITED_CONTROL_CHARACTER",
            )
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}:
            raise ParsingValidationError(
                f"prohibited control U+{codepoint:04X}",
                sanitized_code="PROHIBITED_CONTROL_CHARACTER",
            )
    try:
        normalized = unicodedata.normalize("NFC", normalized_lines)
    except Exception as exc:
        raise ParsingValidationError(
            "Unicode normalization failed", sanitized_code="NORMALIZATION_FAILURE"
        ) from exc
    if unicodedata.normalize("NFC", normalized) != normalized:
        raise ParsingValidationError(
            "Unicode normalization was not idempotent",
            sanitized_code="NORMALIZATION_NON_IDEMPOTENT",
        )
    if len(normalized) > limits.maximum_decoded_characters:
        _fail_limit("normalized text exceeds the character limit")
    return NormalizedText(
        text=normalized,
        bom_observed=bom_observed,
        input_sha256=digest,
        input_byte_length=len(payload),
        normalized_sha256=sha256_hex(normalized),
    )


PLAIN_TEXT_PROFILE = ParserProfile(
    name="generic-utf8-plain-text-parser",
    version="1.0.0",
    contract_version="1.0.0",
    media_type="text/plain",
)
JSON_PROFILE = ParserProfile(
    name="generic-canonical-json-document-parser",
    version="1.0.0",
    contract_version="1.0.0",
    media_type="application/json",
)


@dataclass(frozen=True, slots=True)
class SectionDraft:
    ordinal: int
    kind: SectionKind
    start: int
    end: int
    content: str
    structural_locator: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedContent:
    normalized: NormalizedText
    rendered_text: str
    sections: tuple[SectionDraft, ...]


def _limit(message: str, code: str = "RESOURCE_LIMIT_EXCEEDED") -> None:
    raise ParsingResourceLimitError(message, sanitized_code=code)


def _plain_sections(text: str, limits: ResourceLimits) -> tuple[SectionDraft, ...]:
    sections: list[SectionDraft] = []
    offset = 0
    block_start: int | None = None
    block_end = 0
    for line in text.splitlines(keepends=True):
        line_end = offset + len(line)
        content_end = line_end - 1 if line.endswith("\n") else line_end
        if line.rstrip("\n").strip(" \t"):
            if block_start is None:
                block_start = offset
            block_end = content_end
        elif block_start is not None:
            content = text[block_start:block_end]
            if len(content) > limits.maximum_section_length:
                _limit("plain-text section exceeds its character limit")
            sections.append(
                SectionDraft(
                    ordinal=len(sections),
                    kind=SectionKind.TEXT_BLOCK,
                    start=block_start,
                    end=block_end,
                    content=content,
                    structural_locator=None,
                    metadata={"projection": "BLANK_LINE_SEPARATED_BLOCK"},
                )
            )
            block_start = None
        offset = line_end
    if block_start is not None:
        content = text[block_start:block_end]
        if len(content) > limits.maximum_section_length:
            _limit("plain-text section exceeds its character limit")
        sections.append(
            SectionDraft(
                ordinal=len(sections),
                kind=SectionKind.TEXT_BLOCK,
                start=block_start,
                end=block_end,
                content=content,
                structural_locator=None,
                metadata={"projection": "BLANK_LINE_SEPARATED_BLOCK"},
            )
        )
    if len(sections) > limits.maximum_sections:
        _limit("plain-text document exceeds the section-count limit")
    return tuple(sections)


def parse_plain_text(
    payload: bytes,
    *,
    expected_sha256: str,
    expected_length: int,
    limits: ResourceLimits,
    profile: ParserProfile = PLAIN_TEXT_PROFILE,
) -> ParsedContent:
    normalized = decode_and_normalize(
        payload,
        expected_sha256=expected_sha256,
        expected_length=expected_length,
        profile=profile.normalization,
        limits=limits,
    )
    sections = _plain_sections(normalized.text, limits)
    if not sections:
        raise ParsingValidationError(
            "plain-text document contains no non-empty block",
            sanitized_code="EMPTY_DOCUMENT",
        )
    return ParsedContent(normalized, normalized.text, sections)


class _DuplicateMember(ValueError):
    pass


class _NonFiniteNumber(ValueError):
    pass


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateMember(key)
        result[key] = value
    return result


def _parse_constant(value: str) -> None:
    raise _NonFiniteNumber(value)


def _preflight_json_depth(text: str, maximum: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > maximum:
                _limit("JSON nesting exceeds the depth limit", "JSON_DEPTH_LIMIT")
        elif character in "]}":
            depth -= 1


def _normalize_json_string(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))


def _normalize_and_measure_json(
    value: Any,
    limits: ResourceLimits,
    depth: int = 0,
    counters: dict[str, int] | None = None,
) -> Any:
    if counters is None:
        counters = {"members": 0}
    if depth > limits.maximum_json_depth or depth > limits.maximum_recursion_depth:
        _limit("JSON nesting exceeds the depth limit", "JSON_DEPTH_LIMIT")
    if isinstance(value, str):
        normalized = _normalize_json_string(value)
        if len(normalized) > limits.maximum_string_length:
            _limit("JSON string exceeds its length limit")
        return normalized
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ParsingValidationError(
                "JSON number is not finite", sanitized_code="JSON_NONFINITE_NUMBER"
            )
        return value
    if isinstance(value, list):
        if len(value) > limits.maximum_json_array_length:
            _limit("JSON array exceeds its item limit")
        return [
            _normalize_and_measure_json(item, limits, depth + 1, counters)
            for item in value
        ]
    if isinstance(value, dict):
        counters["members"] += len(value)
        if counters["members"] > limits.maximum_json_members:
            _limit("JSON object members exceed the document limit")
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = _normalize_json_string(raw_key)
            if len(key) > limits.maximum_string_length:
                _limit("JSON object key exceeds its length limit")
            if key in normalized:
                raise ParsingValidationError(
                    "JSON keys collide after canonical normalization",
                    sanitized_code="JSON_DUPLICATE_MEMBER",
                )
            normalized[key] = _normalize_and_measure_json(
                item, limits, depth + 1, counters
            )
        return normalized
    raise ParsingValidationError(
        "JSON decoder returned an unsupported type",
        sanitized_code="JSON_SYNTAX_INVALID",
    )


def _pointer_component(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _render_json_with_sections(
    value: Any, limits: ResourceLimits
) -> tuple[str, tuple[SectionDraft, ...]]:
    output: list[str] = []
    sections: list[SectionDraft] = []
    length = 0

    def append(text: str) -> None:
        nonlocal length
        output.append(text)
        length += len(text)

    def render(node: Any, pointer: str, depth: int) -> None:
        if depth > limits.maximum_recursion_depth:
            _limit("JSON rendering exceeds its recursion limit", "JSON_DEPTH_LIMIT")
        if isinstance(node, dict) and node:
            append("{")
            for index, key in enumerate(sorted(node)):
                if index:
                    append(",")
                append(json.dumps(key, ensure_ascii=False, allow_nan=False))
                append(":")
                render(node[key], f"{pointer}/{_pointer_component(key)}", depth + 1)
            append("}")
            return
        if isinstance(node, list) and node:
            append("[")
            for index, item in enumerate(node):
                if index:
                    append(",")
                render(item, f"{pointer}/{index}", depth + 1)
            append("]")
            return
        start = length
        rendered = json.dumps(
            node,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        append(rendered)
        end = length
        if len(rendered) > limits.maximum_section_length:
            _limit("JSON value section exceeds its character limit")
        value_type = (
            "null"
            if node is None
            else "boolean"
            if isinstance(node, bool)
            else "number"
            if isinstance(node, (int, float))
            else "string"
            if isinstance(node, str)
            else "array"
            if isinstance(node, list)
            else "object"
        )
        sections.append(
            SectionDraft(
                ordinal=len(sections),
                kind=SectionKind.JSON_VALUE,
                start=start,
                end=end,
                content=rendered,
                structural_locator=pointer if pointer else "#",
                metadata={
                    "json_pointer": pointer,
                    "json_value_type": value_type,
                    "projection": "CANONICAL_LEAF_OR_EMPTY_CONTAINER",
                },
            )
        )

    render(value, "", 0)
    if len(sections) > limits.maximum_sections:
        _limit("JSON document exceeds the section-count limit")
    return ("".join(output), tuple(sections))


def parse_json_document(
    payload: bytes,
    *,
    expected_sha256: str,
    expected_length: int,
    limits: ResourceLimits,
    profile: ParserProfile = JSON_PROFILE,
) -> ParsedContent:
    normalized = decode_and_normalize(
        payload,
        expected_sha256=expected_sha256,
        expected_length=expected_length,
        profile=profile.normalization,
        limits=limits,
    )
    _preflight_json_depth(normalized.text, limits.maximum_json_depth)
    try:
        value = json.loads(
            normalized.text,
            object_pairs_hook=_object_pairs,
            parse_constant=_parse_constant,
        )
    except _DuplicateMember as exc:
        raise ParsingValidationError(
            "JSON contains a duplicate object member",
            sanitized_code="JSON_DUPLICATE_MEMBER",
        ) from exc
    except _NonFiniteNumber as exc:
        raise ParsingValidationError(
            "JSON contains a non-finite number", sanitized_code="JSON_NONFINITE_NUMBER"
        ) from exc
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ParsingValidationError(
            "JSON syntax is invalid", sanitized_code="JSON_SYNTAX_INVALID"
        ) from exc
    value = _normalize_and_measure_json(value, limits)
    rendered, sections = _render_json_with_sections(value, limits)
    if len(rendered) > limits.maximum_decoded_characters:
        _limit("canonical JSON output exceeds the character limit")
    canonical_normalized = NormalizedText(
        text=rendered,
        bom_observed=normalized.bom_observed,
        input_sha256=normalized.input_sha256,
        input_byte_length=normalized.input_byte_length,
        normalized_sha256=sha256_hex(rendered),
    )
    return ParsedContent(canonical_normalized, rendered, sections)


PARSER_FUNCTIONS = {
    "text/plain": parse_plain_text,
    "application/json": parse_json_document,
}
PARSER_PROFILES = {"text/plain": PLAIN_TEXT_PROFILE, "application/json": JSON_PROFILE}
_VARIATION_SELECTORS = tuple(range(65024, 65040)) + tuple(range(917760, 918000))


def _unsafe_split(text: str, position: int) -> bool:
    if position <= 0 or position >= len(text):
        return False
    next_code = ord(text[position])
    return (
        unicodedata.combining(text[position]) != 0
        or next_code in _VARIATION_SELECTORS
        or text[position] == "\u200d"
        or (text[position - 1] == "\u200d")
    )


def _safe_cut(text: str, proposed: int, maximum: int) -> int:
    cut = proposed
    while cut < maximum and _unsafe_split(text, cut):
        cut += 1
    if cut <= maximum and (not _unsafe_split(text, cut)):
        return cut
    cut = proposed
    while cut > 0 and _unsafe_split(text, cut):
        cut -= 1
    return cut


def _boundary(text: str, start: int, section_end: int, profile: ChunkingProfile) -> int:
    hard = min(start + profile.maximum_characters, section_end)
    if hard == section_end:
        return hard
    target = min(start + profile.target_characters, hard)
    low = max(
        start + profile.minimum_characters, target - profile.boundary_search_window
    )
    candidate_text = text[low:hard]
    priorities: tuple[tuple[str, ...], ...] = (
        ("\n",),
        (". ", "! ", "? ", ".\n", "!\n", "?\n"),
        (" ", "\t"),
    )
    for markers in priorities:
        best = -1
        marker_length = 0
        for marker in markers:
            found = candidate_text.rfind(marker)
            if found > best:
                best = found
                marker_length = len(marker)
        if best >= 0:
            cut = low + best + marker_length
            cut = _safe_cut(text, cut, hard)
            if cut > start:
                return cut
    cut = _safe_cut(text, hard, hard)
    if cut <= start:
        raise ParsingValidationError(
            "no safe bounded chunk boundary is available",
            sanitized_code="CHUNK_RANGE_INVALID",
        )
    return cut


def chunk_sections(
    *,
    tenant_id: str,
    source_id: str,
    hat_scope_id: str,
    knowledge_version_id: str,
    document_id: str,
    normalized_text: str,
    sections: tuple[ParsedSection, ...],
    profile: ChunkingProfile,
    limits: ResourceLimits,
    language_tag: LanguageTag | None,
) -> tuple[ParsedChunk, ...]:
    chunks: list[ParsedChunk] = []
    for section in sections:
        start = section.normalized_start_offset
        section_end = section.normalized_end_offset
        section_ordinal = 0
        previous_end: int | None = None
        while start < section_end:
            end = _boundary(normalized_text, start, section_end, profile)
            content = normalized_text[start:end]
            if (
                not content
                or len(content) > profile.maximum_characters
                or len(content) > limits.maximum_chunk_length
            ):
                raise ParsingValidationError(
                    "chunk length violates the versioned profile",
                    sanitized_code="CHUNK_RANGE_INVALID",
                )
            overlap = 0 if previous_end is None else previous_end - start
            chunks.append(
                ParsedChunk(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    hat_scope_id=hat_scope_id,
                    knowledge_version_id=knowledge_version_id,
                    document_id=document_id,
                    section_id=section.section_id,
                    chunk_id="",
                    chunk_ordinal=len(chunks),
                    section_chunk_ordinal=section_ordinal,
                    normalized_start_offset=start,
                    normalized_end_offset=end,
                    content=content,
                    chunking_profile_digest=profile.profile_digest,
                    overlap_prefix_characters=overlap,
                    language_tag=language_tag,
                )
            )
            if len(chunks) > limits.maximum_chunks:
                raise ParsingResourceLimitError(
                    "document exceeds the chunk-count limit",
                    sanitized_code="RESOURCE_LIMIT_EXCEEDED",
                )
            if end == section_end:
                break
            next_start = max(
                section.normalized_start_offset, end - profile.overlap_characters
            )
            while next_start < end and _unsafe_split(normalized_text, next_start):
                next_start += 1
            if next_start >= end:
                next_start = end
            previous_end = end
            start = next_start
            section_ordinal += 1
    return tuple(chunks)


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    category: FindingCategory
    pattern: re.Pattern[str]
    severity: FindingSeverity
    action: FindingAction


_RULES = (
    _Rule(
        "PI_ROLE_MARKER_001",
        FindingCategory.ROLE_OR_SYSTEM_INSTRUCTION_MARKER,
        re.compile("(?im)^\\s*(?:system|developer|assistant)\\s*:\\s*\\S+"),
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    ),
    _Rule(
        "PI_OVERRIDE_001",
        FindingCategory.INSTRUCTION_OVERRIDE_PHRASE,
        re.compile(
            "(?i)\\bignore\\s+(?:all\\s+|any\\s+|the\\s+)?previous\\s+instructions?\\b"
        ),
        FindingSeverity.BLOCKING,
        FindingAction.QUARANTINE,
    ),
    _Rule(
        "PI_TOOL_EXEC_001",
        FindingCategory.TOOL_OR_COMMAND_EXECUTION_REQUEST,
        re.compile(
            "(?i)\\b(?:run|execute|invoke|call)\\s+(?:this\\s+)?(?:shell|command|tool|terminal)\\b"
        ),
        FindingSeverity.BLOCKING,
        FindingAction.QUARANTINE,
    ),
    _Rule(
        "PI_SECRET_EXFIL_001",
        FindingCategory.SECRET_OR_CREDENTIAL_EXFILTRATION_REQUEST,
        re.compile(
            "(?i)\\b(?:reveal|send|print|exfiltrat\\w*)\\b.{0,48}\\b(?:password|secret|token|credential)s?\\b"
        ),
        FindingSeverity.BLOCKING,
        FindingAction.QUARANTINE,
    ),
    _Rule(
        "PI_REMOTE_001",
        FindingCategory.REMOTE_OR_INDIRECT_INSTRUCTION,
        re.compile(
            "(?i)\\b(?:follow|obey|execute)\\b.{0,40}\\binstructions?\\b.{0,40}\\b(?:remote|website|url|link)\\b"
        ),
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    ),
    _Rule(
        "PI_HIDDEN_MARKUP_001",
        FindingCategory.HIDDEN_MARKUP_OR_COMMENT_INSTRUCTION,
        re.compile("(?is)<!--.{0,256}(?:ignore|instruction|system|execute).{0,256}-->"),
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    ),
    _Rule(
        "PI_ENCODED_001",
        FindingCategory.ENCODED_OR_OBFUSCATED_INSTRUCTION_SIGNAL,
        re.compile(
            "(?<![A-Za-z0-9+/])(?:[A-Za-z0-9+/]{40,}={0,2}|[0-9A-Fa-f]{64,})(?![A-Za-z0-9+/])"
        ),
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    ),
    _Rule(
        "PI_RAG_POISON_001",
        FindingCategory.RAG_POISONING_OR_RETRIEVAL_MANIPULATION_SIGNAL,
        re.compile(
            "(?i)\\b(?:rank|retrieve|retrieval|search)\\b.{0,40}\\b(?:always|first|highest|prioriti[sz]e)\\b"
        ),
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    ),
)
_ZERO_WIDTH_OR_BIDI = re.compile(
    "[\u200b\u200c\u200d\u202a-\u202e\u2060\u2066-\u2069\ufeff]"
)
_QUOTED_CONTEXT = re.compile(
    "(?i)\\b(?:example|quoted|quotation|educational|training|detection|security\\s+text)\\b"
)


def _section_for_offset(
    sections: tuple[ParsedSection, ...], start: int, end: int
) -> str | None:
    matches = [
        section
        for section in sections
        if section.normalized_start_offset <= start
        and end <= section.normalized_end_offset
    ]
    if not matches:
        return None
    matches.sort(
        key=lambda section: (
            section.normalized_end_offset - section.normalized_start_offset
        )
    )
    return matches[0].section_id


def scan_security_findings(
    document_id: str,
    text: str,
    sections: tuple[ParsedSection, ...],
    limits: ResourceLimits,
) -> tuple[PromptInjectionFinding, ...]:
    findings: list[PromptInjectionFinding] = []

    def record(
        rule: _Rule,
        start: int,
        end: int,
        *,
        severity: FindingSeverity | None = None,
        action: FindingAction | None = None,
    ) -> None:
        bounded_start = max(0, start - 48)
        bounded_end = min(len(text), end + 48)
        findings.append(
            PromptInjectionFinding(
                document_id=document_id,
                finding_id="",
                rule_id=rule.rule_id,
                category=rule.category,
                severity=severity or rule.severity,
                normalized_start_offset=start,
                normalized_end_offset=end,
                section_id=_section_for_offset(sections, start, end),
                evidence_excerpt_sha256=sha256_hex(text[bounded_start:bounded_end]),
                action=action or rule.action,
            )
        )
        if len(findings) > limits.maximum_security_findings:
            raise ParsingResourceLimitError(
                "security finding count exceeds the policy limit",
                sanitized_code="SECURITY_FINDING_LIMIT_EXCEEDED",
            )

    for rule in _RULES:
        for match in rule.pattern.finditer(text):
            context = text[
                max(0, match.start() - 96) : min(len(text), match.end() + 96)
            ]
            if rule.severity is FindingSeverity.BLOCKING and (
                _QUOTED_CONTEXT.search(context)
                or (match.start() > 0 and text[match.start() - 1] in "'\"`")
            ):
                record(
                    rule,
                    match.start(),
                    match.end(),
                    severity=FindingSeverity.INFO,
                    action=FindingAction.RECORD_ONLY,
                )
            else:
                record(rule, match.start(), match.end())
    zero_rule = _Rule(
        "PI_INVISIBLE_001",
        FindingCategory.ZERO_WIDTH_OR_BIDI_CONTROL_SIGNAL,
        _ZERO_WIDTH_OR_BIDI,
        FindingSeverity.WARNING,
        FindingAction.OPERATOR_REVIEW,
    )
    for match in _ZERO_WIDTH_OR_BIDI.finditer(text):
        record(zero_rule, match.start(), match.end())
    findings.sort(
        key=lambda item: (item.normalized_start_offset, item.rule_id, item.finding_id)
    )
    return tuple(findings)


ParserFunction = Callable[..., ParsedContent]


class ParserRegistry:
    """Dispatch only exact declared media types; never guess from bytes."""

    def __init__(
        self,
        functions: Mapping[str, ParserFunction] | None = None,
        profiles: Mapping[str, ParserProfile] | None = None,
    ) -> None:
        selected_functions = dict(functions or PARSER_FUNCTIONS)
        selected_profiles = dict(profiles or PARSER_PROFILES)
        if set(selected_functions) != set(selected_profiles):
            raise ValueError("parser registry functions and profiles differ")
        if any(
            (
                media_type != profile.media_type
                or not callable(selected_functions[media_type])
                for media_type, profile in selected_profiles.items()
            )
        ):
            raise ValueError("parser registry contains an invalid profile binding")
        self._functions = MappingProxyType(selected_functions)
        self._profiles = MappingProxyType(selected_profiles)

    @property
    def supported_media_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._profiles))

    def profile_for(self, media_type: str) -> ParserProfile:
        profile = self._profiles.get(media_type)
        if profile is None:
            raise UnsupportedMediaTypeError(
                "no exact production parser profile exists for this media type",
                sanitized_code="UNSUPPORTED_MEDIA_TYPE",
            )
        return profile

    def parse(
        self,
        media_type: str,
        payload: bytes,
        *,
        expected_sha256: str,
        expected_length: int,
        limits: ResourceLimits,
    ) -> tuple[ParserProfile, ParsedContent]:
        profile = self.profile_for(media_type)
        result = self._functions[media_type](
            payload,
            expected_sha256=expected_sha256,
            expected_length=expected_length,
            limits=limits,
            profile=profile,
        )
        return (profile, result)


@dataclass(frozen=True, slots=True)
class ParsingRequest:
    tenant_id: str
    owner_user_id: str | None
    saga_id: str
    source_id: str
    snapshot_id: str
    knowledge_version_id: str
    knowledge_version_ordinal: int
    hat_scope_id: str
    s3_version_id: str
    locked_storage_evidence_digest: str
    input_sha256: str
    input_byte_length: int
    media_type: str
    completed_at: datetime
    language_tag: LanguageTag | None = None


class GenericParsingPipeline:
    """No-I/O deterministic pipeline over exact immutable snapshot bytes."""

    def __init__(
        self,
        *,
        registry: ParserRegistry | None = None,
        limits: ResourceLimits | None = None,
        chunking_profile: ChunkingProfile | None = None,
    ) -> None:
        self.registry = registry or ParserRegistry()
        self.limits = limits or ResourceLimits()
        self.chunking_profile = chunking_profile or ChunkingProfile()

    def parse(self, request: ParsingRequest, payload: bytes) -> ParseArtifact:
        profile, parsed = self.registry.parse(
            request.media_type,
            payload,
            expected_sha256=request.input_sha256,
            expected_length=request.input_byte_length,
            limits=self.limits,
        )
        document_identity = canonical_sha256(
            {
                "contract": "ParsedDocumentIdentity1A",
                "tenant_id": request.tenant_id,
                "owner_user_id": request.owner_user_id,
                "saga_id": request.saga_id,
                "source_id": request.source_id,
                "snapshot_id": request.snapshot_id,
                "knowledge_version_id": request.knowledge_version_id,
                "knowledge_version_ordinal": request.knowledge_version_ordinal,
                "hat_scope_id": request.hat_scope_id,
                "s3_version_id": request.s3_version_id,
                "locked_storage_evidence_digest": request.locked_storage_evidence_digest,
                "input_sha256": request.input_sha256,
                "input_byte_length": request.input_byte_length,
                "media_type": request.media_type,
                "parser_profile_digest": profile.profile_digest,
                "normalization_profile_digest": profile.normalization.profile_digest,
                "chunking_profile_digest": self.chunking_profile.profile_digest,
                "security_ruleset": {
                    "name": SECURITY_RULESET_NAME,
                    "version": SECURITY_RULESET_VERSION,
                },
                "resource_policy_digest": self.limits.policy_digest,
            }
        )
        document_id = f"parsedoc-{document_identity}"
        sections = tuple(
            (
                ParsedSection(
                    document_id=document_id,
                    section_id="",
                    section_ordinal=draft.ordinal,
                    parent_section_id=None,
                    section_kind=draft.kind,
                    structural_locator=draft.structural_locator,
                    normalized_start_offset=draft.start,
                    normalized_end_offset=draft.end,
                    content=draft.content,
                    metadata=draft.metadata,
                    parser_profile_digest=profile.profile_digest,
                )
                for draft in parsed.sections
            )
        )
        chunks = chunk_sections(
            tenant_id=request.tenant_id,
            source_id=request.source_id,
            hat_scope_id=request.hat_scope_id,
            knowledge_version_id=request.knowledge_version_id,
            document_id=document_id,
            normalized_text=parsed.rendered_text,
            sections=sections,
            profile=self.chunking_profile,
            limits=self.limits,
            language_tag=request.language_tag,
        )
        findings = scan_security_findings(
            document_id, parsed.rendered_text, sections, self.limits
        )
        blocking = tuple(
            sorted(
                {
                    "BLOCKING_PROMPT_INJECTION_SIGNAL"
                    for finding in findings
                    if finding.severity is FindingSeverity.BLOCKING
                }
            )
        )
        quarantine = QuarantineDecision(bool(blocking), blocking)
        section_manifest = canonical_sha256(
            tuple((section.section_id for section in sections))
        )
        chunk_manifest = canonical_sha256(tuple((chunk.chunk_id for chunk in chunks)))
        finding_manifest = canonical_sha256(
            tuple((finding.finding_id for finding in findings))
        )
        artifact_digest = canonical_sha256(
            {
                "document_id": document_id,
                "normalized_content_sha256": parsed.normalized.normalized_sha256,
                "section_manifest_digest": section_manifest,
                "chunk_manifest_digest": chunk_manifest,
                "finding_manifest_digest": finding_manifest,
                "quarantine_decision_digest": quarantine.decision_digest,
                "parser_profile": {
                    "name": profile.name,
                    "version": profile.version,
                    "contract": profile.contract_version,
                },
                "normalization_profile": {
                    "name": profile.normalization.name,
                    "version": profile.normalization.version,
                },
            }
        )
        document = ParsedDocument(
            tenant_id=request.tenant_id,
            owner_user_id=request.owner_user_id,
            saga_id=request.saga_id,
            source_id=request.source_id,
            snapshot_id=request.snapshot_id,
            knowledge_version_id=request.knowledge_version_id,
            knowledge_version_ordinal=request.knowledge_version_ordinal,
            hat_scope_id=request.hat_scope_id,
            s3_version_id=request.s3_version_id,
            locked_storage_evidence_digest=request.locked_storage_evidence_digest,
            input_sha256=request.input_sha256,
            input_byte_length=request.input_byte_length,
            media_type=request.media_type,
            parser_name=profile.name,
            parser_version=profile.version,
            parser_contract_version=profile.contract_version,
            decoder_profile=profile.normalization.encoding,
            bom_policy=profile.normalization.bom_policy,
            bom_observed=parsed.normalized.bom_observed,
            normalization_profile=profile.normalization.name,
            normalization_version=profile.normalization.version,
            normalized_content_sha256=parsed.normalized.normalized_sha256,
            normalized_character_length=len(parsed.rendered_text),
            document_id=document_id,
            section_count=len(sections),
            chunk_count=len(chunks),
            security_finding_count=len(findings),
            section_manifest_digest=section_manifest,
            chunk_manifest_digest=chunk_manifest,
            finding_manifest_digest=finding_manifest,
            parse_artifact_digest=artifact_digest,
            completed_at=request.completed_at,
            language_tag=request.language_tag,
        )
        return ParseArtifact(
            document=document,
            normalized_text=parsed.rendered_text,
            sections=sections,
            chunks=chunks,
            findings=findings,
            quarantine=quarantine,
        )


class ParseArtifactValidator:
    """Validate ranges, hashes, coverage, identities, and quarantine policy."""

    def __init__(self, limits: ResourceLimits | None = None) -> None:
        self.limits = limits or ResourceLimits()

    def validate(self, artifact: ParseArtifact) -> ParseValidationResult:
        reasons: set[str] = set()
        text = artifact.normalized_text
        previous_section_end = -1
        for expected_ordinal, section in enumerate(artifact.sections):
            if section.section_ordinal != expected_ordinal:
                reasons.add("SECTION_RANGE_INVALID")
            if (
                not 0
                <= section.normalized_start_offset
                < section.normalized_end_offset
                <= len(text)
            ):
                reasons.add("SECTION_RANGE_INVALID")
                continue
            if (
                text[section.normalized_start_offset : section.normalized_end_offset]
                != section.content
            ):
                reasons.add("SECTION_CONTENT_MISMATCH")
            if sha256_hex(section.content) != section.content_sha256:
                reasons.add("SECTION_CONTENT_MISMATCH")
            if (
                section.section_kind.value == "TEXT_BLOCK"
                and section.normalized_start_offset < previous_section_end
            ):
                reasons.add("SECTION_RANGE_INVALID")
            previous_section_end = max(
                previous_section_end, section.normalized_end_offset
            )
        sections_by_id = {section.section_id: section for section in artifact.sections}
        chunks_by_section: dict[str, list[object]] = {
            section.section_id: [] for section in artifact.sections
        }
        for expected_ordinal, chunk in enumerate(artifact.chunks):
            if (
                chunk.chunk_ordinal != expected_ordinal
                or chunk.section_id not in chunks_by_section
            ):
                reasons.add("CHUNK_RANGE_INVALID")
                continue
            chunks_by_section[chunk.section_id].append(chunk)
            section = sections_by_id[chunk.section_id]
            if (
                chunk.tenant_id != artifact.document.tenant_id
                or chunk.source_id != artifact.document.source_id
                or chunk.hat_scope_id != artifact.document.hat_scope_id
                or (
                    chunk.knowledge_version_id != artifact.document.knowledge_version_id
                )
                or (chunk.document_id != artifact.document.document_id)
                or (chunk.normalized_start_offset < section.normalized_start_offset)
                or (chunk.normalized_end_offset > section.normalized_end_offset)
            ):
                reasons.add("CHUNK_RANGE_INVALID")
            if (
                not 0
                <= chunk.normalized_start_offset
                < chunk.normalized_end_offset
                <= len(text)
            ):
                reasons.add("CHUNK_RANGE_INVALID")
                continue
            if (
                text[chunk.normalized_start_offset : chunk.normalized_end_offset]
                != chunk.content
            ):
                reasons.add("CHUNK_CONTENT_MISMATCH")
            if sha256_hex(chunk.content) != chunk.content_sha256:
                reasons.add("CHUNK_CONTENT_MISMATCH")
            if len(chunk.content) > self.limits.maximum_chunk_length:
                reasons.add("CHUNK_RANGE_INVALID")
        for section in artifact.sections:
            section_chunks = chunks_by_section[section.section_id]
            if not section_chunks:
                reasons.add("CHUNK_COVERAGE_INVALID")
                continue
            ordered = sorted(
                section_chunks, key=lambda chunk: chunk.section_chunk_ordinal
            )
            if [chunk.section_chunk_ordinal for chunk in ordered] != list(
                range(len(ordered))
            ):
                reasons.add("CHUNK_RANGE_INVALID")
            covered_to = section.normalized_start_offset
            for chunk in ordered:
                if chunk.normalized_start_offset > covered_to:
                    reasons.add("CHUNK_COVERAGE_INVALID")
                covered_to = max(covered_to, chunk.normalized_end_offset)
            if covered_to != section.normalized_end_offset:
                reasons.add("CHUNK_COVERAGE_INVALID")
        section_ids = {section.section_id for section in artifact.sections}
        for finding in artifact.findings:
            if (
                not 0
                <= finding.normalized_start_offset
                < finding.normalized_end_offset
                <= len(text)
            ):
                reasons.add("SECTION_RANGE_INVALID")
            if finding.section_id is not None and finding.section_id not in section_ids:
                reasons.add("SECTION_RANGE_INVALID")
        if any(
            (
                finding.severity is FindingSeverity.BLOCKING
                for finding in artifact.findings
            )
        ):
            reasons.add("BLOCKING_PROMPT_INJECTION_SIGNAL")
        if artifact.quarantine.required:
            reasons.update(artifact.quarantine.reason_codes)
        ordered_reasons = tuple(sorted(reasons))
        return ParseValidationResult(
            accepted=not ordered_reasons,
            reason_codes=ordered_reasons,
            parse_artifact_digest=artifact.document.parse_artifact_digest,
        )


class NativeParser:
    """Core authority and immutable snapshot binding around pure parsing."""

    def __init__(
        self,
        core: CoreAdmission,
        *,
        limits: ResourceLimits | None = None,
        chunking: ChunkingProfile | None = None,
    ):
        self._core = core
        self._pipeline = GenericParsingPipeline(
            limits=limits, chunking_profile=chunking
        )
        self._validator = ParseArtifactValidator(self._pipeline.limits)

    def parse(
        self,
        principal: CorePrincipal,
        acquired: AcquiredSnapshot,
        *,
        saga_id: str,
        at: datetime,
    ) -> ParseArtifact:
        if type(acquired) is not AcquiredSnapshot:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        snapshot = acquired.manifest.snapshot
        self._core.require(principal, Capability.EVIDENCE_CAPTURE, scope=snapshot.scope)
        if (
            snapshot.hat_id not in principal.hat_ids
            or snapshot.origin is not InputOrigin.SOURCE_BYTES
            or acquired.manifest.quarantined is not False
            or acquired.manifest.license_status
            in {SourceLicenseStatus.UNKNOWN, SourceLicenseStatus.PROHIBITED}
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        AcquiredSnapshot(acquired.manifest, acquired.payload)
        request = ParsingRequest(
            tenant_id=principal.scope.tenant_id,
            owner_user_id=principal.scope.owner_id,
            saga_id=saga_id,
            source_id=snapshot.source_id,
            snapshot_id=snapshot.snapshot_id,
            knowledge_version_id=snapshot.knowledge_version_id,
            knowledge_version_ordinal=snapshot.knowledge_version_ordinal,
            hat_scope_id=snapshot.hat_id,
            # Retained private canonical key denotes immutable object version.
            # The native storage contract has no AWS client or bucket resolver.
            s3_version_id=snapshot.storage.version,
            locked_storage_evidence_digest=snapshot.binding_digest,
            input_sha256=snapshot.content_sha256,
            input_byte_length=snapshot.byte_length,
            media_type=snapshot.media_type,
            completed_at=ensure_utc(at),
        )
        result = self._pipeline.parse(request, acquired.payload)
        verdict = self._validator.validate(result)
        if not verdict.accepted or result.quarantine.required:
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        return result
