"""Reviewed corpus identity and quarantine gates; no network retrieval engine."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal
from runtime.evidence_admission import InputOrigin
from runtime.memory_patch.contracts.serialization import (
    canonical_sha256,
    require_non_empty,
)
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.source_lineage import SourceLicenseStatus
from runtime.memory_patch.storage_ports import SnapshotBinding, SourceStoragePort


@dataclass(frozen=True, slots=True, repr=False)
class AcquisitionManifest:
    snapshot: SnapshotBinding
    license_status: SourceLicenseStatus
    license_id: str
    licensing_review_reference: str
    quarantined: bool = True

    def __post_init__(self) -> None:
        if (
            type(self.snapshot) is not SnapshotBinding
            or type(self.license_status) is not SourceLicenseStatus
            or type(self.quarantined) is not bool
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for value in (self.license_id, self.licensing_review_reference):
            require_non_empty(value, "licensing review identity")
            if len(value) > 256:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256(self)


@dataclass(frozen=True, slots=True, repr=False)
class AcquiredSnapshot:
    manifest: AcquisitionManifest
    payload: bytes

    def __post_init__(self) -> None:
        if (
            type(self.payload) is not bytes
            or len(self.payload) != self.manifest.snapshot.byte_length
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if (
            hashlib.sha256(self.payload).hexdigest()
            != self.manifest.snapshot.content_sha256
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)


def corpus_identity(manifests: tuple[AcquisitionManifest, ...]) -> str:
    if (
        type(manifests) is not tuple
        or not 1 <= len(manifests) <= 1024
        or any(type(item) is not AcquisitionManifest for item in manifests)
    ):
        raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
    identities = [
        (
            item.snapshot.scope.binding(),
            item.snapshot.source_id,
            item.snapshot.knowledge_version_id,
        )
        for item in manifests
    ]
    if len(identities) != len(set(identities)):
        raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
    return canonical_sha256(tuple(sorted(item.manifest_digest for item in manifests)))


class NativeAcquisition:
    def __init__(self, core: CoreAdmission, storage: SourceStoragePort | None = None):
        self._core = core
        self._storage = storage

    def acquire(
        self, principal: CorePrincipal, manifest: AcquisitionManifest
    ) -> AcquiredSnapshot:
        if type(manifest) is not AcquisitionManifest:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self._core.require(
            principal, Capability.EVIDENCE_CAPTURE, scope=manifest.snapshot.scope
        )
        if (
            manifest.snapshot.hat_id not in principal.hat_ids
            or manifest.snapshot.origin is not InputOrigin.SOURCE_BYTES
            or manifest.quarantined is not False
            or manifest.license_status
            in {SourceLicenseStatus.UNKNOWN, SourceLicenseStatus.PROHIBITED}
        ):
            raise MemoryPatchError(ErrorCode.EVIDENCE_DENIED)
        if self._storage is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        self._storage.require_locked(manifest.snapshot)
        return AcquiredSnapshot(
            manifest, self._storage.read_snapshot(manifest.snapshot)
        )
