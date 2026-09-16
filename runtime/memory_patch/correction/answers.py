"""Verified answer assembly: one bounded retry of the identical signed packet."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from runtime.core_admission import CorePrincipal
from runtime.memory_patch.correction.packets import (
    NativeCorrectionPacket,
    PacketIntegrityReceipt,
)
from runtime.memory_patch.correction.verification import CitedDraft, NativeVerifier
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.retrieval.contracts import FrozenEvidenceBundle


class CorrectedDraftPort(Protocol):
    """Implemented only by the adapter of Core's existing exact provider path."""

    def draft(
        self,
        principal: CorePrincipal,
        packet: NativeCorrectionPacket,
        bundle: FrozenEvidenceBundle,
        *,
        attempt: int,
    ) -> CitedDraft: ...


@dataclass(frozen=True, slots=True, repr=False)
class NativeVerifiedAnswer:
    answer: str
    status: str
    citations: tuple[str, ...]
    memory_context_used: bool
    review_required: bool
    verification: object | None
    attempts: int


UNKNOWN_ANSWER = "No verified answer is available. Human review is required."


class NativeAnswerAssembler:
    def __init__(
        self,
        verifier: NativeVerifier,
        provider: CorrectedDraftPort | None = None,
        *,
        maximum_attempts: int = 2,
    ):
        if type(maximum_attempts) is not int or maximum_attempts not in (1, 2):
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        self.verifier, self.provider = verifier, provider
        self.maximum_attempts = maximum_attempts
        self._completed = {}
        self._lock = threading.Lock()

    def answer(
        self,
        principal: CorePrincipal,
        packet: NativeCorrectionPacket,
        receipt: PacketIntegrityReceipt,
        bundle: FrozenEvidenceBundle,
        *,
        operation_id: str,
    ):
        self.verifier.integrity.verify(principal, packet, receipt)
        self.verifier.claims.retrieval.require_bundle(principal, bundle)
        if packet.bundle_hash != bundle.bundle_hash:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        key = (principal.scope.binding(), operation_id)
        with self._lock:
            prior = self._completed.get(key)
            if prior is not None:
                if prior[0] != packet.packet_hash:
                    raise MemoryPatchError(ErrorCode.IDEMPOTENCY_CONFLICT)
                # Re-evaluate source authority and time after a readback/restart.
                if prior[2] is not None:
                    checked = self.verifier.verify(
                        principal, prior[2], packet, receipt, bundle
                    )
                    if not checked.verified:
                        return NativeVerifiedAnswer(
                            UNKNOWN_ANSWER,
                            "UNVERIFIED",
                            (),
                            False,
                            True,
                            checked,
                            prior[1].attempts,
                        )
                return prior[1]
            if self.provider is None:
                return NativeVerifiedAnswer(
                    UNKNOWN_ANSWER, "UNVERIFIED", (), False, True, None, 0
                )
            if len(self._completed) >= 1024:
                raise MemoryPatchError(ErrorCode.QUOTA_EXCEEDED)
            last = None
            for attempt in range(1, self.maximum_attempts + 1):
                self.verifier.integrity.consume_attempt(
                    principal,
                    packet,
                    receipt,
                    operation_id=operation_id,
                    attempt=attempt,
                )
                try:
                    candidate = self.provider.draft(
                        principal, packet, bundle, attempt=attempt
                    )
                    if type(candidate) is not CitedDraft:
                        raise MemoryPatchError(ErrorCode.PROVIDER_DENIED)
                    last = self.verifier.verify(
                        principal, candidate, packet, receipt, bundle
                    )
                except Exception:
                    # An unknown provider outcome never becomes a fallback answer.
                    result = NativeVerifiedAnswer(
                        UNKNOWN_ANSWER, "UNVERIFIED", (), False, True, None, attempt
                    )
                    self._completed[key] = (packet.packet_hash, result, None)
                    return result
                if last.verified:
                    result = NativeVerifiedAnswer(
                        candidate.draft.text,
                        "VERIFIED",
                        last.citation_item_hashes,
                        False,
                        False,
                        last,
                        attempt,
                    )
                    self._completed[key] = (packet.packet_hash, result, candidate)
                    return result
            result = NativeVerifiedAnswer(
                UNKNOWN_ANSWER,
                "UNVERIFIED",
                (),
                False,
                True,
                last,
                self.maximum_attempts,
            )
            self._completed[key] = (packet.packet_hash, result, None)
            return result

    def close(self):
        with self._lock:
            self._completed.clear()
