"""Read existing Core Critic metadata and create DETECTED advisory candidates."""

from __future__ import annotations

from typing import Protocol

from runtime.core_admission import Capability, CoreActor, CoreAdmission
from runtime.memory_patch.contracts.enums import MemoryContentKind
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError
from runtime.memory_patch.personal.candidates import NativeCandidates
from runtime.memory_patch.personal.contracts import CandidateDraft
from runtime.memory_patch.retrieval.contracts import bounded_text


class CoreCriticReadPort(Protocol):
    def get(self, run_id: str) -> dict: ...
    def verify(self, run_id: str, reference_manifest=None) -> dict: ...


class NativeCriticAdapter:
    def __init__(
        self,
        core: CoreAdmission,
        candidates: NativeCandidates,
        existing_critic: CoreCriticReadPort | None = None,
    ):
        self.core, self.candidates, self.existing_critic = (
            core,
            candidates,
            existing_critic,
        )

    def candidate_from_run(
        self, principal, run_id: str, *, hat_id: str, operation_key: str
    ):
        self.core.require(principal, Capability.CANDIDATE)
        if principal.actor is not CoreActor.OWNER_HUMAN:
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        bounded_text(run_id, 128)
        if self.existing_critic is None:
            raise MemoryPatchError(ErrorCode.BACKEND_UNCONFIGURED)
        view = self.existing_critic.get(run_id)
        if (
            not isinstance(view, dict)
            or view.get("run_id") != run_id
            or view.get("execution_status") != "COMPLETED"
            or view.get("authority") != "ADVISORY_ONLY"
            or view.get("knowledge_promotion") != "DISABLED"
            or view.get("human_review_required") is not True
            or view.get("model_training") != "NONE"
        ):
            raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
        proof = self.existing_critic.verify(run_id, view.get("evidence_chain"))
        if (
            not isinstance(proof, dict)
            or proof.get("ok") is not True
            or proof.get("run_id") != run_id
            or proof.get("authority") != "INTEGRITY_ONLY_NOT_TRUTH"
            or proof.get("issues") != []
            or proof.get("terminal_hash")
            != view.get("evidence_chain", {}).get("terminal_hash")
        ):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        reviews = view.get("reviews")
        if not isinstance(reviews, list) or len(reviews) != 3:
            raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
        summaries = []
        slots = []
        for review in reviews:
            allowed = {
                "slot_id",
                "role",
                "provider_id",
                "model_id",
                "execution_status",
                "summary",
                "findings",
                "uncertainty",
                "evidence_conflicts",
                "snapshot_hash",
                "observer_configuration_hash",
                "error_category",
                "authority",
            }
            if (
                not isinstance(review, dict)
                or set(review) != allowed
                or review["authority"] != "METADATA_ONLY_NO_AUTHORITY"
                or review["execution_status"] != "COMPLETED"
            ):
                raise MemoryPatchError(ErrorCode.ADMISSION_DENIED)
            slots.append(review["slot_id"])
            summaries.append(bounded_text(review["summary"], 500))
            if not isinstance(review["findings"], list) or len(review["findings"]) > 4:
                raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
            for finding in review["findings"]:
                if not isinstance(finding, dict) or set(finding) != {
                    "category",
                    "severity",
                    "title",
                    "detail",
                }:
                    raise MemoryPatchError(ErrorCode.INVALID_REQUEST)
                bounded_text(finding["title"], 120)
                bounded_text(finding["detail"], 600)
        if slots != ["observer-1", "observer-2", "observer-3"]:
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        if canonical_sha256(view) != canonical_sha256(self.existing_critic.get(run_id)):
            raise MemoryPatchError(ErrorCode.INTEGRITY_FAILED)
        draft = CandidateDraft(
            "Critic observation",
            summaries[0],
            "\n".join(summaries),
            MemoryContentKind.MODEL_EXPERIENCE,
            hat_id,
            tuple(sorted(principal.model_binding_ids)),
        )
        # Core supplies this producer principal. The metadata contains no role,
        # evidence, approval, execution or tenant-normalization authority.
        producer = self.core.critic_candidate()
        return self.candidates.intake(
            producer,
            draft,
            operation_key=operation_key,
            producer_metadata_digest=canonical_sha256(
                {
                    "run_id": run_id,
                    "reviews": reviews,
                    "terminal_hash": proof["terminal_hash"],
                }
            ),
        )
