"""Reviewed pure domain semantics with native, inert dependencies."""

from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.enums import StableStringEnum
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    require_sha256_hex,
)
from runtime.memory_patch.errors import (
    ContractValidationError,
    ErrorCode,
    MemoryPatchError,
)

STEP19_SCHEMA_VERSION = "1.0.0"
APPROVED_EMBEDDING_DIMENSION = 384
APPROVED_MAXIMUM_TOKENS = 512
APPROVED_WEIGHT_FILENAME = "model.safetensors"
EMBEDDING_BYTES_LENGTH = APPROVED_EMBEDDING_DIMENSION * 4
MAXIMUM_QUERY_UTF8_BYTES = 4096
MAXIMUM_CANDIDATE_CONTENT_BYTES = 64 * 1024


class Step19ReasonCode(StableStringEnum):
    EMBEDDING_GENERATION_OK = "EMBEDDING_GENERATION_OK"
    VECTOR_RETRIEVAL_OK = "VECTOR_RETRIEVAL_OK"
    VECTOR_MATCH = "VECTOR_MATCH"
    NO_MATCH = "NO_MATCH"
    NO_HAT_SELECTED = "NO_HAT_SELECTED"
    AMBIGUOUS_ROUTE = "AMBIGUOUS_ROUTE"
    ROUTE_HASH_INVALID = "ROUTE_HASH_INVALID"
    ROUTE_SCOPE_MISMATCH = "ROUTE_SCOPE_MISMATCH"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    USER_MISMATCH = "USER_MISMATCH"
    REQUEST_ID_MISMATCH = "REQUEST_ID_MISMATCH"
    HAT_IDENTITY_MISMATCH = "HAT_IDENTITY_MISMATCH"
    HAT_SCOPE_MISMATCH = "HAT_SCOPE_MISMATCH"
    MODEL_IDENTITY_INVALID = "MODEL_IDENTITY_INVALID"
    MODEL_RUNTIME_UNAVAILABLE = "MODEL_RUNTIME_UNAVAILABLE"
    MODEL_WEIGHT_MISMATCH = "MODEL_WEIGHT_MISMATCH"
    EMBEDDING_VECTOR_INVALID = "EMBEDDING_VECTOR_INVALID"
    CACHE_HIT = "CACHE_HIT"
    CACHE_MISS = "CACHE_MISS"
    CACHE_INTEGRITY_INVALID = "CACHE_INTEGRITY_INVALID"
    CACHE_CONFLICT = "CACHE_CONFLICT"
    BATCH_LIMIT_EXCEEDED = "BATCH_LIMIT_EXCEEDED"
    ITEM_LIMIT_EXCEEDED = "ITEM_LIMIT_EXCEEDED"
    QUERY_TOO_LARGE = "QUERY_TOO_LARGE"
    RESULT_LIMIT_EXCEEDED = "RESULT_LIMIT_EXCEEDED"
    SOURCE_NOT_ELIGIBLE = "SOURCE_NOT_ELIGIBLE"
    EMBEDDING_RECORD_CONFLICT = "EMBEDDING_RECORD_CONFLICT"
    DATABASE_ERROR = "DATABASE_ERROR"
    SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"


class EmbeddingBoundaryError(RuntimeError):
    """Sanitized fail-closed Step 19 error with a closed reason code."""

    def __init__(self, reason_code: Step19ReasonCode) -> None:
        if not isinstance(reason_code, Step19ReasonCode):
            raise TypeError("reason_code must be a Step19ReasonCode")
        super().__init__(
            f"Step 19 embedding/vector operation denied: {reason_code.value}"
        )
        self.reason_code = reason_code


_CONTROL = re.compile("[\\x00-\\x1f\\x7f]")
_DOMAIN_ID = re.compile("^[a-z0-9][a-z0-9._-]{0,127}$")
_MODEL_ID = re.compile(
    "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
_REVISION = re.compile("^[0-9a-f]{40}$")


def _text(value: object, field_name: str, maximum_bytes: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or _CONTROL.search(value)
        or (unicodedata.normalize("NFC", value) != value)
        or (len(value.encode("utf-8")) > maximum_bytes)
    ):
        raise ContractValidationError(
            f"{field_name} must be bounded canonical NFC text"
        )
    return value


def _domain_id(value: object, field_name: str) -> str:
    text = _text(value, field_name, 128)
    if _DOMAIN_ID.fullmatch(text) is None:
        raise ContractValidationError(f"{field_name} must be a logical identifier")
    return text


def _content(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ContractValidationError("content must be non-empty text")
    if unicodedata.normalize("NFC", value) != value:
        raise ContractValidationError("content must use Unicode NFC")
    for character in value:
        if unicodedata.category(character) == "Cc" and character not in {"\t", "\n"}:
            raise ContractValidationError("content contains a prohibited control")
    if len(value.encode("utf-8")) > MAXIMUM_CANDIDATE_CONTENT_BYTES:
        raise ContractValidationError("content exceeds its byte limit")
    return value


@dataclass(frozen=True, slots=True)
class EmbeddingModelSpec:
    schema_version: str
    model_id: str
    model_revision: str
    model_family: str
    embedding_dimension: int
    maximum_tokens: int
    query_prefix: str
    passage_prefix: str
    normalization: str
    weight_filename: str
    weight_sha256: str
    license: str
    inference_backend: str
    input_policy_version: str
    backend_contract_version: str
    model_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if self.schema_version != STEP19_SCHEMA_VERSION:
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        if (
            not isinstance(self.model_id, str)
            or _MODEL_ID.fullmatch(self.model_id) is None
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        if (
            not isinstance(self.model_revision, str)
            or _REVISION.fullmatch(self.model_revision) is None
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        for value, name in (
            (self.model_family, "model_family"),
            (self.inference_backend, "inference_backend"),
            (self.input_policy_version, "input_policy_version"),
            (self.backend_contract_version, "backend_contract_version"),
        ):
            _domain_id(value, name)
        if (
            isinstance(self.embedding_dimension, bool)
            or not isinstance(self.embedding_dimension, int)
            or self.embedding_dimension != APPROVED_EMBEDDING_DIMENSION
            or isinstance(self.maximum_tokens, bool)
            or (not isinstance(self.maximum_tokens, int))
            or (self.maximum_tokens != APPROVED_MAXIMUM_TOKENS)
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        if not isinstance(self.query_prefix, str) or not self.query_prefix.endswith(
            " "
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        if not isinstance(self.passage_prefix, str) or not self.passage_prefix.endswith(
            " "
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        _text(self.query_prefix[:-1], "query_prefix", 64)
        _text(self.passage_prefix[:-1], "passage_prefix", 64)
        _domain_id(self.normalization.casefold().replace("_", "-"), "normalization")
        if self.weight_filename != APPROVED_WEIGHT_FILENAME:
            raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
        require_sha256_hex(self.weight_sha256, "weight_sha256")
        _text(self.license, "license", 64)
        object.__setattr__(
            self,
            "model_digest",
            canonical_sha256(self, exclude_fields=("model_digest",)),
        )


@dataclass(frozen=True, slots=True)
class EmbeddingVector:
    """Exact normalized float32 vector; never embedded in canonical JSON."""

    values: tuple[float, ...]
    float32_bytes: bytes = field(init=False, repr=False)
    bytes_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.values, (tuple, list))
            or len(self.values) != APPROVED_EMBEDDING_DIMENSION
        ):
            raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
        values: list[float] = []
        for item in self.values:
            if isinstance(item, bool) or not isinstance(item, (int, float)):
                raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
            value = float(item)
            if not math.isfinite(value):
                raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
            values.append(struct.unpack("<f", struct.pack("<f", value))[0])
        norm = math.sqrt(math.fsum((item * item for item in values)))
        if not math.isfinite(norm) or abs(norm - 1.0) > 1e-05:
            raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
        payload = struct.pack(f"<{APPROVED_EMBEDDING_DIMENSION}f", *values)
        if len(payload) != EMBEDDING_BYTES_LENGTH:
            raise AssertionError("float32 embedding byte length differs")
        object.__setattr__(self, "values", tuple(values))
        object.__setattr__(self, "float32_bytes", payload)
        object.__setattr__(self, "bytes_sha256", hashlib.sha256(payload).hexdigest())


def normalize_embedding_vector(values: Sequence[float]) -> EmbeddingVector:
    if len(values) != APPROVED_EMBEDDING_DIMENSION:
        raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
    converted: list[float] = []
    for item in values:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
        value = float(item)
        if not math.isfinite(value):
            raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
        converted.append(value)
    norm = math.sqrt(math.fsum((item * item for item in converted)))
    if not math.isfinite(norm) or norm <= 0:
        raise EmbeddingBoundaryError(Step19ReasonCode.EMBEDDING_VECTOR_INVALID)
    return EmbeddingVector(tuple((value / norm for value in converted)))


def vector_from_float32_bytes(payload: bytes) -> EmbeddingVector:
    if not isinstance(payload, bytes) or len(payload) != EMBEDDING_BYTES_LENGTH:
        raise EmbeddingBoundaryError(Step19ReasonCode.CACHE_INTEGRITY_INVALID)
    values = struct.unpack(f"<{APPROVED_EMBEDDING_DIMENSION}f", payload)
    return EmbeddingVector(values)


def prepare_passage(content: str, spec: EmbeddingModelSpec) -> str:
    return spec.passage_prefix + _content(content)


def prepare_query(query_text: str, spec: EmbeddingModelSpec) -> str:
    text = _text(query_text, "query_text", MAXIMUM_QUERY_UTF8_BYTES)
    return spec.query_prefix + text


def load_approved_model_spec() -> EmbeddingModelSpec:
    """Pinned metadata only. No model, file, environment or credential access."""
    spec = EmbeddingModelSpec(
        schema_version="1.0.0",
        model_id="intfloat/multilingual-e5-small",
        model_revision="fd1525a9fd15316a2d503bf26ab031a61d056e98",
        model_family="multilingual-e5",
        embedding_dimension=384,
        maximum_tokens=512,
        query_prefix="query: ",
        passage_prefix="passage: ",
        normalization="L2_UNIT",
        weight_filename="model.safetensors",
        weight_sha256="1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477",
        license="MIT",
        inference_backend="transformers",
        input_policy_version="e5-query-passage-prefix-v1",
        backend_contract_version="transformers-mean-pooling-v1",
    )
    if (
        spec.model_digest
        != "aa68fc625f243f0e9c5f97aa9a7d3b7963c7dfdd10ca645d0782f3d8e8c77070"
    ):
        raise EmbeddingBoundaryError(Step19ReasonCode.MODEL_IDENTITY_INVALID)
    return spec


@dataclass(frozen=True, slots=True, repr=False)
class VectorCacheIdentity:
    scope: OwnerScope
    hat_id: str
    model_digest: str
    content_sha256: str
    input_kind: str
    identity_digest: str = field(init=False)

    def __post_init__(self):
        if type(self.scope) is not OwnerScope or self.input_kind not in {
            "QUERY",
            "PASSAGE",
        }:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        _text(self.hat_id, "hat_id", 256)
        require_sha256_hex(self.content_sha256, "content_sha256")
        if self.model_digest != load_approved_model_spec().model_digest:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        object.__setattr__(
            self,
            "identity_digest",
            canonical_sha256(self, exclude_fields=("identity_digest",)),
        )


class EmbeddingCachePort(Protocol):
    def get(self, identity: VectorCacheIdentity) -> bytes | None: ...
    def put(self, identity: VectorCacheIdentity, vector_bytes: bytes) -> None: ...


class NativeEmbeddingCache:
    """An explicitly injected derived cache; generation stays with Core."""

    def __init__(self, core: CoreAdmission, port: EmbeddingCachePort | None = None):
        self.core, self.port = core, port

    def _require(self, principal, identity):
        self.core.require(principal, principal.capability, scope=identity.scope)
        if identity.hat_id not in principal.hat_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if self.port is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)

    def read(
        self, principal: CorePrincipal, identity: VectorCacheIdentity
    ) -> EmbeddingVector | None:
        self.core.require(principal, Capability.READ)
        self._require(principal, identity)
        payload = self.port.get(identity)
        return None if payload is None else vector_from_float32_bytes(payload)

    def write(
        self,
        principal: CorePrincipal,
        identity: VectorCacheIdentity,
        vector: EmbeddingVector,
    ):
        self.core.require(principal, Capability.EVIDENCE_CAPTURE)
        self._require(principal, identity)
        # Revalidate an untrusted adapter's object and exact float32 byte identity.
        checked = vector_from_float32_bytes(vector.float32_bytes)
        if (
            checked.bytes_sha256 != vector.bytes_sha256
            or checked.values != vector.values
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        self.port.put(identity, checked.float32_bytes)


@dataclass(frozen=True, slots=True, repr=False)
class ScopedVector:
    record_id: str
    scope: OwnerScope
    hat_id: str
    model_digest: str
    vector: EmbeddingVector


def exact_l2(left: EmbeddingVector, right: EmbeddingVector) -> float:
    left = vector_from_float32_bytes(left.float32_bytes)
    right = vector_from_float32_bytes(right.float32_bytes)
    return math.sqrt(
        math.fsum((a - b) ** 2 for a, b in zip(left.values, right.values, strict=True))
    )


def exact_top_k(
    core: CoreAdmission,
    principal: CorePrincipal,
    query: EmbeddingVector,
    candidates: tuple[ScopedVector, ...],
    *,
    hat_id: str,
    limit: int = 20,
):
    core.require(principal, Capability.READ)
    if (
        hat_id not in principal.hat_ids
        or type(limit) is not int
        or not 1 <= limit <= 100
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    if type(candidates) is not tuple or len(candidates) > 1024:
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    model = load_approved_model_spec().model_digest
    authorized = [
        c for c in candidates if c.scope == principal.scope and c.hat_id == hat_id
    ]
    if len({c.record_id for c in authorized}) != len(authorized):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    if any(c.model_digest != model for c in authorized):
        raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
    values = ((c.record_id, exact_l2(query, c.vector)) for c in authorized)
    return tuple(sorted(values, key=lambda item: (item[1], item[0]))[:limit])
