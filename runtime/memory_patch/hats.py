"""Scoped declarative HAT contracts attached to the existing Core selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from runtime.core_admission import CoreAdmission, CorePrincipal, OwnerScope
from runtime.memory_patch.contracts.records import (
    HatManifest,
    PersonalHatQuotaPolicy,
    validate_hat_manifest,
)
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError


class CoreHatSelection(Protocol):
    """The existing MemoryHatStore supplies this; native code never creates one."""

    def active_hat(self) -> object | None: ...


@dataclass(frozen=True, slots=True, repr=False)
class ScopedHatBinding:
    scope: OwnerScope
    hat_id: str
    hat_version: str
    manifest_digest: str
    model_binding_ids: frozenset[str]
    quota: PersonalHatQuotaPolicy


class NativeHatAdmission:
    def __init__(
        self,
        core: CoreAdmission,
        selection: CoreHatSelection,
        manifests: tuple[HatManifest, ...],
        *,
        quota: PersonalHatQuotaPolicy,
    ) -> None:
        if (
            type(manifests) is not tuple
            or not 1 <= len(manifests) <= 128
            or type(quota) is not PersonalHatQuotaPolicy
        ):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        for manifest in manifests:
            validate_hat_manifest(manifest)
        if len({manifest.hat_id for manifest in manifests}) != len(manifests):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self._core = core
        self._selection = selection
        self._manifests = manifests
        self._quota = quota

    def selected(self, principal: CorePrincipal, hat_id: str) -> ScopedHatBinding:
        self._core.require(principal, principal.capability)
        if hat_id not in principal.hat_ids:
            raise MemoryPatchError(ErrorCode.OWNER_DENIED)
        # Lookup uses the existing Core selection. Registry presence and overlay
        # instructions do not grant private reads, approval, or execution.
        active = self._selection.active_hat()
        if active is None or getattr(active, "name", None) != hat_id:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        manifest = next(
            (value for value in self._manifests if value.hat_id == hat_id), None
        )
        if manifest is None:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        validate_hat_manifest(manifest)
        return ScopedHatBinding(
            principal.scope,
            manifest.hat_id,
            manifest.hat_version,
            canonical_sha256(manifest),
            principal.model_binding_ids,
            self._quota,
        )
