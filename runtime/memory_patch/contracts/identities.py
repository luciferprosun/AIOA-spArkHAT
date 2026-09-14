"Tenant ownership, kernel run, routing, and action-policy contracts."

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from runtime.memory_patch.contracts.enums import (
    ActionPolicy,
    AnswerStatus,
    EvidenceStatus,
    KnowledgeRoute,
)
from runtime.memory_patch.contracts.serialization import (
    ensure_utc,
    freeze_string_tuple,
    require_enum_member,
    require_non_empty,
)
from runtime.memory_patch.errors import ContractValidationError, OwnershipViolation


@dataclass(frozen=True, slots=True)
class MemoryOwnership:
    """Ownership coordinates for every private user-controlled object."""

    tenant_id: str
    user_id: str
    personal_memory_space_id: str

    def __post_init__(self) -> None:
        require_non_empty(self.tenant_id, "tenant_id")
        require_non_empty(self.user_id, "user_id")
        require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")


@dataclass(frozen=True, slots=True)
class KernelRunIdentity:
    """Identity and ownership context of one immutable Kernel run."""

    kernel_run_id: str
    tenant_id: str
    user_id: str
    personal_memory_space_id: str | None
    model_binding_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.kernel_run_id, "kernel_run_id")
        require_non_empty(self.tenant_id, "tenant_id")
        require_non_empty(self.user_id, "user_id")
        if self.personal_memory_space_id is not None:
            require_non_empty(self.personal_memory_space_id, "personal_memory_space_id")
        require_non_empty(self.model_binding_id, "model_binding_id")
        object.__setattr__(
            self, "created_at", ensure_utc(self.created_at, "created_at")
        )


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Historical Axis A decision; retrieval outcomes never rewrite it."""

    kernel_run_id: str
    knowledge_route: KnowledgeRoute
    selected_hat_id: str | None
    reason_codes: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.kernel_run_id, "kernel_run_id")
        require_enum_member(self.knowledge_route, KnowledgeRoute, "knowledge_route")
        object.__setattr__(
            self, "reason_codes", freeze_string_tuple(self.reason_codes, "reason_codes")
        )
        if self.knowledge_route in {
            KnowledgeRoute.HAT_ASSIST,
            KnowledgeRoute.HAT_ENFORCE,
        }:
            require_non_empty(self.selected_hat_id or "", "selected_hat_id")
        elif self.selected_hat_id is not None:
            raise ContractValidationError(
                "PASS_THROUGH and AMBIGUOUS routes cannot select a HAT"
            )
        if not self.reason_codes:
            raise ContractValidationError("routing decision requires a reason code")
        object.__setattr__(
            self, "decided_at", ensure_utc(self.decided_at, "decided_at")
        )


@dataclass(frozen=True, slots=True)
class ActionPolicyDecision:
    """Independent Axis B decision that memory and retrieval cannot modify."""

    kernel_run_id: str
    action_policy: ActionPolicy
    reason_codes: tuple[str, ...]
    decided_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.kernel_run_id, "kernel_run_id")
        require_enum_member(self.action_policy, ActionPolicy, "action_policy")
        object.__setattr__(
            self, "reason_codes", freeze_string_tuple(self.reason_codes, "reason_codes")
        )
        if not self.reason_codes:
            raise ContractValidationError(
                "action policy decision requires non-empty reason codes"
            )
        object.__setattr__(
            self, "decided_at", ensure_utc(self.decided_at, "decided_at")
        )


def require_tenant_context(tenant_id: str | None, user_id: str | None) -> None:
    """Fail closed when either part of a private ownership context is absent."""
    try:
        require_non_empty(tenant_id, "tenant context")
    except ContractValidationError as exc:
        raise OwnershipViolation("tenant context is required") from exc
    try:
        require_non_empty(user_id, "user context")
    except ContractValidationError as exc:
        raise OwnershipViolation("user context is required") from exc


def verify_ownership(
    ownership: MemoryOwnership,
    *,
    tenant_id: str | None,
    user_id: str | None,
    personal_memory_space_id: str | None = None,
) -> None:
    """Require an exact tenant, user, and personal-space ownership triple."""
    require_tenant_context(tenant_id, user_id)
    if ownership.tenant_id != tenant_id:
        raise OwnershipViolation("cross-tenant access is forbidden")
    if ownership.user_id != user_id:
        raise OwnershipViolation("cross-user access is forbidden")
    try:
        require_non_empty(personal_memory_space_id, "personal memory space context")
    except ContractValidationError as exc:
        raise OwnershipViolation("personal memory space context is required") from exc
    if ownership.personal_memory_space_id != personal_memory_space_id:
        raise OwnershipViolation("personal memory space ownership mismatch")


def verify_run_ownership(run: KernelRunIdentity, ownership: MemoryOwnership) -> None:
    """Prevent a run or Critic event from targeting another owner."""
    if run.tenant_id != ownership.tenant_id:
        raise OwnershipViolation("kernel run cannot cross tenants")
    if run.user_id != ownership.user_id:
        raise OwnershipViolation("kernel run cannot cross users")
    if run.personal_memory_space_id is None:
        raise OwnershipViolation("kernel run personal memory space context is required")
    if run.personal_memory_space_id != ownership.personal_memory_space_id:
        raise OwnershipViolation("kernel run cannot cross personal memory spaces")


def derive_answer_status(
    *,
    knowledge_route: KnowledgeRoute,
    action_policy: ActionPolicy,
    evidence_status: EvidenceStatus,
    verification_passed: bool | None = None,
    model_generation_failed: bool = False,
    storage_unavailable: bool = False,
    action_required: bool = False,
    action_confirmed: bool = False,
) -> AnswerStatus:
    """Derive the answer result while preserving independent route dimensions."""
    require_enum_member(knowledge_route, KnowledgeRoute, "knowledge_route")
    require_enum_member(action_policy, ActionPolicy, "action_policy")
    require_enum_member(evidence_status, EvidenceStatus, "evidence_status")
    if action_required and action_policy is ActionPolicy.DENY_ACTION:
        return AnswerStatus.BLOCKED_POLICY
    if (
        action_required
        and action_policy is ActionPolicy.REQUIRE_CONFIRMATION
        and (not action_confirmed)
    ):
        return AnswerStatus.BLOCKED_POLICY
    if knowledge_route is KnowledgeRoute.AMBIGUOUS:
        return AnswerStatus.BLOCKED_AMBIGUOUS_ROUTE
    if storage_unavailable:
        return AnswerStatus.BLOCKED_STORAGE_UNAVAILABLE
    if model_generation_failed:
        return AnswerStatus.MODEL_GENERATION_FAILED
    if knowledge_route is KnowledgeRoute.PASS_THROUGH:
        return AnswerStatus.PASS_THROUGH_RESULT
    if evidence_status in {
        EvidenceStatus.INSUFFICIENT,
        EvidenceStatus.UNAVAILABLE,
        EvidenceStatus.STALE,
        EvidenceStatus.INVALID,
    }:
        return AnswerStatus.BLOCKED_NO_VERIFIED_EVIDENCE
    if evidence_status is EvidenceStatus.CONFLICTING:
        if verification_passed:
            return AnswerStatus.VERIFIED_WITH_CONFLICTS
        return AnswerStatus.BLOCKED_CONFLICTING_EVIDENCE
    if evidence_status is EvidenceStatus.SUFFICIENT:
        if verification_passed is True:
            return AnswerStatus.VERIFIED
        if verification_passed is False:
            return AnswerStatus.BLOCKED_VERIFICATION_FAILED
    return AnswerStatus.DRAFT


def validate_result_invariants(
    routing: RoutingDecision,
    action: ActionPolicyDecision,
    evidence_status: EvidenceStatus,
    answer_status: AnswerStatus,
) -> None:
    """Validate cross-contract invariants without changing historical decisions."""
    require_enum_member(evidence_status, EvidenceStatus, "evidence_status")
    require_enum_member(answer_status, AnswerStatus, "answer_status")
    if routing.kernel_run_id != action.kernel_run_id:
        raise ContractValidationError("routing and action decisions use different runs")
    if (
        routing.knowledge_route is KnowledgeRoute.HAT_ENFORCE
        and evidence_status is EvidenceStatus.INSUFFICIENT
        and (answer_status is not AnswerStatus.BLOCKED_NO_VERIFIED_EVIDENCE)
    ):
        raise ContractValidationError(
            "HAT_ENFORCE with insufficient evidence must fail closed"
        )
    if answer_status is AnswerStatus.VERIFIED:
        expected = derive_answer_status(
            knowledge_route=routing.knowledge_route,
            action_policy=action.action_policy,
            evidence_status=evidence_status,
            verification_passed=True,
        )
        if expected is not AnswerStatus.VERIFIED:
            raise ContractValidationError(
                "VERIFIED answer violates route/evidence policy"
            )


def assert_action_policy_unchanged(
    original: ActionPolicyDecision, candidate: ActionPolicyDecision
) -> None:
    """Reject any attempt by personal memory to rewrite Axis B."""
    if original != candidate:
        raise ContractValidationError(
            "personal memory cannot alter an Action Policy decision"
        )
