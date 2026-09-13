"""Core-supplied immutable source storage and derived-cache contracts only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from runtime.core_admission import OwnerScope
from runtime.evidence_admission import InputOrigin
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    ensure_utc,
    require_non_empty,
    require_sha256_hex,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError


class StoragePurpose(str, Enum):
    SOURCE_SNAPSHOT = "SOURCE_SNAPSHOT"
    DERIVED_CACHE = "DERIVED_CACHE"
    OWNER_EXPORT = "OWNER_EXPORT"


@dataclass(frozen=True, slots=True, repr=False)
class StorageHandle:
    """An opaque capability supplied by Core; no path/DSN or ambient resolver."""

    reference: str
    scope: OwnerScope
    purpose: StoragePurpose
    version: str

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not OwnerScope
            or type(self.purpose) is not StoragePurpose
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for value in (self.reference, self.version):
            require_non_empty(value, "storage identity")
            if (
                len(value) > 256
                or "://" in value
                or value.startswith(("/", "\\"))
                or value.lower() == "latest"
            ):
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)


@dataclass(frozen=True, slots=True, repr=False)
class SnapshotBinding:
    scope: OwnerScope
    source_id: str
    snapshot_id: str
    knowledge_version_id: str
    knowledge_version_ordinal: int
    hat_id: str
    storage: StorageHandle
    content_sha256: str
    byte_length: int
    media_type: str
    origin: InputOrigin
    captured_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not OwnerScope
            or type(self.storage) is not StorageHandle
            or self.storage.scope != self.scope
        ):
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        if (
            self.storage.purpose is not StoragePurpose.SOURCE_SNAPSHOT
            or type(self.origin) is not InputOrigin
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for value in (
            self.source_id,
            self.snapshot_id,
            self.knowledge_version_id,
            self.hat_id,
            self.media_type,
        ):
            require_non_empty(value, "snapshot identity")
            if len(value) > 256:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if (
            type(self.knowledge_version_ordinal) is not int
            or self.knowledge_version_ordinal < 1
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        if (
            type(self.byte_length) is not int
            or not 1 <= self.byte_length <= 64 * 1024 * 1024
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        require_sha256_hex(self.content_sha256, "snapshot fingerprint")
        object.__setattr__(self, "captured_at", ensure_utc(self.captured_at))

    @property
    def binding_digest(self) -> str:
        return canonical_sha256(self)


class SourceStoragePort(Protocol):
    """Must verify the exact Core handle/version before reading supplied bytes."""

    def read_snapshot(self, snapshot: SnapshotBinding) -> bytes: ...
    def require_locked(self, snapshot: SnapshotBinding) -> None: ...


class DerivedCachePort(Protocol):
    """A disposable cache cannot provide source or approval authority."""

    def get(self, handle: StorageHandle, content_digest: str) -> bytes | None: ...
    def put(
        self, handle: StorageHandle, content_digest: str, payload: bytes
    ) -> None: ...


class UnconfiguredStorage:
    def read_snapshot(self, snapshot: SnapshotBinding) -> bytes:
        raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)

    def require_locked(self, snapshot: SnapshotBinding) -> None:
        raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
