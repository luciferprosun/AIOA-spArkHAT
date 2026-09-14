"""Explicit Core source capture; domain memory and model text cannot self-promote."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Protocol

from runtime.core_admission import Capability, CoreAdmission, CorePrincipal, OwnerScope


class EvidenceAdmissionError(ValueError):
    def __init__(self) -> None:
        super().__init__("CORE_EVIDENCE_ADMISSION_DENIED")


class InputOrigin(str, Enum):
    SOURCE_BYTES = "source_bytes"
    OPERATIONAL_LOG = "operational_log"
    REASONING = "reasoning"
    MODEL_OUTPUT = "model_output"
    PERSONAL_MEMORY = "personal_memory"
    CRITIC = "critic"
    EXECUTION_RECEIPT = "execution_receipt"
    VAULT_PROJECTION = "vault_projection"


def _atom(value: str, limit: int = 256) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > limit
        or any(ord(c) < 32 for c in value)
    ):
        raise EvidenceAdmissionError()


def _digest(value: str) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise EvidenceAdmissionError()


def _canonical(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True, repr=False)
class SourceCaptureSpec:
    source_id: str
    source_version_id: str
    source_fingerprint: str
    artifact_fingerprint: str
    transform_fingerprints: tuple[str, ...]
    origin: InputOrigin
    license_id: str
    license_reviewed: bool
    quarantined: bool
    hat_id: str
    schema_version: str = "1.0.0"

    def __post_init__(self) -> None:
        for value in (
            self.source_id,
            self.source_version_id,
            self.license_id,
            self.hat_id,
        ):
            _atom(value)
        for value in (self.source_fingerprint, self.artifact_fingerprint):
            _digest(value)
        if (
            not isinstance(self.transform_fingerprints, tuple)
            or len(self.transform_fingerprints) > 32
        ):
            raise EvidenceAdmissionError()
        for value in self.transform_fingerprints:
            _digest(value)
        if type(self.origin) is not InputOrigin or self.schema_version != "1.0.0":
            raise EvidenceAdmissionError()
        if (
            type(self.license_reviewed) is not bool
            or type(self.quarantined) is not bool
        ):
            raise EvidenceAdmissionError()

    def binding(self) -> list:
        return [
            self.source_id,
            self.source_version_id,
            self.source_fingerprint,
            self.artifact_fingerprint,
            list(self.transform_fingerprints),
            self.origin.value,
            self.license_id,
            self.license_reviewed,
            self.quarantined,
            self.hat_id,
            self.schema_version,
        ]


@dataclass(frozen=True, slots=True, repr=False)
class CaptureIntent:
    intent_id: str
    scope: OwnerScope
    source: SourceCaptureSpec
    actor_session_id: str
    expires_at: datetime
    _seal: bytes = field(default=b"", repr=False)


@dataclass(frozen=True, slots=True, repr=False)
class CapturedEvidence:
    """Only a Core-owned evidence catalog can supply an admitted instance."""

    evidence_id: str
    scope: OwnerScope
    source: SourceCaptureSpec
    source_bytes: bytes
    artifact_bytes: bytes
    captured_at: datetime
    capture_intent_id: str
    record_digest: str
    withdrawn: bool = False

    def binding(self) -> list:
        return [
            self.evidence_id,
            list(self.scope.binding()),
            self.source.binding(),
            hashlib.sha256(self.source_bytes).hexdigest(),
            hashlib.sha256(self.artifact_bytes).hexdigest(),
            self.captured_at.isoformat(),
            self.capture_intent_id,
        ]


class CoreEvidenceCatalog(Protocol):
    """Core-owned L4 storage and provenance receipt verification, explicitly injected.

    admit is one logical capture by intent/digest; conflicting replay must deny.
    require_published verifies the existing Core provenance chain and publication
    receipt. Domain outbox insertion alone must never satisfy it.
    """

    def admit(self, record: CapturedEvidence) -> CapturedEvidence: ...
    def get(self, scope: OwnerScope, evidence_id: str) -> CapturedEvidence | None: ...
    def require_published(self, record: CapturedEvidence) -> None: ...


class CoreEvidenceAdmission:
    def __init__(
        self,
        admission: CoreAdmission,
        catalog: CoreEvidenceCatalog | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._admission = admission
        self._catalog = catalog
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._seal_key = secrets.token_bytes(32)
        self._consumed: set[str] = set()
        self._intent_lock = threading.Lock()

    def _signature(self, intent: CaptureIntent) -> bytes:
        binding = [
            intent.intent_id,
            list(intent.scope.binding()),
            intent.source.binding(),
            intent.actor_session_id,
            intent.expires_at.isoformat(),
        ]
        return hmac.digest(self._seal_key, _canonical(binding).encode(), "sha256")

    @staticmethod
    def _eligible(source: SourceCaptureSpec) -> None:
        if (
            type(source) is not SourceCaptureSpec
            or source.origin is not InputOrigin.SOURCE_BYTES
            or source.license_reviewed is not True
            or source.quarantined is not False
        ):
            raise EvidenceAdmissionError()

    def approve_capture(
        self, principal: CorePrincipal, source: SourceCaptureSpec
    ) -> CaptureIntent:
        scope = self._admission.require(principal, Capability.EVIDENCE_CAPTURE)
        self._eligible(source)
        if source.hat_id not in principal.hat_ids:
            raise EvidenceAdmissionError()
        intent = CaptureIntent(
            "capture_" + secrets.token_hex(16),
            scope,
            source,
            principal.actor_session_id,
            self._clock() + timedelta(minutes=5),
        )
        return replace(intent, _seal=self._signature(intent))

    def capture(
        self,
        principal: CorePrincipal,
        intent: CaptureIntent,
        *,
        source_bytes: bytes,
        artifact_bytes: bytes,
    ) -> CapturedEvidence:
        scope = self._admission.require(principal, Capability.EVIDENCE_CAPTURE)
        if self._catalog is None:
            raise EvidenceAdmissionError()
        if (
            type(intent) is not CaptureIntent
            or intent.scope != scope
            or intent.actor_session_id != principal.actor_session_id
            or intent.intent_id in self._consumed
            or self._clock() >= intent.expires_at
            or not hmac.compare_digest(intent._seal, self._signature(intent))
        ):
            raise EvidenceAdmissionError()
        self._eligible(intent.source)
        if any(
            type(data) is not bytes or not 0 < len(data) <= 4 * 1024 * 1024
            for data in (source_bytes, artifact_bytes)
        ):
            raise EvidenceAdmissionError()
        if (
            hashlib.sha256(source_bytes).hexdigest() != intent.source.source_fingerprint
            or hashlib.sha256(artifact_bytes).hexdigest()
            != intent.source.artifact_fingerprint
            or (
                source_bytes != artifact_bytes
                and not intent.source.transform_fingerprints
            )
        ):
            raise EvidenceAdmissionError()
        record = CapturedEvidence(
            "evidence_" + secrets.token_hex(16),
            scope,
            intent.source,
            source_bytes,
            artifact_bytes,
            self._clock(),
            intent.intent_id,
            "",
        )
        record = replace(record, record_digest=_canonical(record.binding()))
        # Consume before dispatch: an unknown catalog outcome needs explicit
        # receipt reconciliation, never a blind second capture.
        with self._intent_lock:
            if intent.intent_id in self._consumed:
                raise EvidenceAdmissionError()
            self._consumed.add(intent.intent_id)
        admitted = self._catalog.admit(record)
        if admitted != record:
            raise EvidenceAdmissionError()
        self._catalog.require_published(admitted)
        return admitted

    def require_evidence(
        self, principal: CorePrincipal, evidence_id: str
    ) -> CapturedEvidence:
        self._admission.require(principal, principal.capability)
        _atom(evidence_id)
        if self._catalog is None:
            raise EvidenceAdmissionError()
        record = self._catalog.get(principal.scope, evidence_id)
        if (
            type(record) is not CapturedEvidence
            or record.scope != principal.scope
            or record.evidence_id != evidence_id
            or record.withdrawn is not False
            or record.source.hat_id not in principal.hat_ids
        ):
            raise EvidenceAdmissionError()
        self._eligible(record.source)
        if (
            record.record_digest != _canonical(record.binding())
            or hashlib.sha256(record.source_bytes).hexdigest()
            != record.source.source_fingerprint
            or hashlib.sha256(record.artifact_bytes).hexdigest()
            != record.source.artifact_fingerprint
        ):
            raise EvidenceAdmissionError()
        self._catalog.require_published(record)
        return record
