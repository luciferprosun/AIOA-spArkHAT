"""Ownership-bound, plan-only rollback and cleanup contracts for Phase 3."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StringConstraints,
    ValidationError,
    model_validator,
)

from .deployment_contract import (
    AwsDeploymentContract,
    canonical_json,
    contract_sha256,
    pretty_json,
)
from .iac import (
    ExpectedResourceManifest,
    OwnershipProof,
    ResourceLifecycle,
)

Sha256Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
DeploymentId = Annotated[
    str,
    StringConstraints(pattern=r"^p3-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}$"),
]
LogicalId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9]{0,254}$")]


class CleanupError(RuntimeError):
    """Public-safe fixed-reason cleanup failure."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class StrictCleanupModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, validate_default=True)


class DeploymentPartialState(StrEnum):
    DEPLOYMENT_STARTED_THEN_FAILED = "DEPLOYMENT_STARTED_THEN_FAILED"
    RESOURCE_EXISTS_VERIFICATION_FAILED = "RESOURCE_EXISTS_VERIFICATION_FAILED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    RETRY = "RETRY"
    ROLLBACK_PARTIALLY_FAILED = "ROLLBACK_PARTIALLY_FAILED"
    DEPLOYMENT_VERIFIED = "DEPLOYMENT_VERIFIED"


class CleanupAttemptState(StrEnum):
    NEVER_ATTEMPTED = "NEVER_ATTEMPTED"
    PREVIOUSLY_FAILED = "PREVIOUSLY_FAILED"
    PREVIOUSLY_CONFIRMED_ABSENT = "PREVIOUSLY_CONFIRMED_ABSENT"


class CleanupPlanStatus(StrEnum):
    READY_FOR_OPERATOR_REVIEW = "READY_FOR_OPERATOR_REVIEW"
    BLOCKED_OWNERSHIP = "BLOCKED_OWNERSHIP"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"


class CleanupAction(StrEnum):
    DELETE_WITH_CLOUDFORMATION_STACK = "DELETE_WITH_CLOUDFORMATION_STACK"
    RETRY_CLOUDFORMATION_STACK_DELETE = "RETRY_CLOUDFORMATION_STACK_DELETE"
    RETAIN_PENDING_EXPLICIT_DISPOSITION = "RETAIN_PENDING_EXPLICIT_DISPOSITION"
    NO_OBSERVED_RESOURCE = "NO_OBSERVED_RESOURCE"
    ALREADY_CONFIRMED_ABSENT = "ALREADY_CONFIRMED_ABSENT"
    DO_NOT_DELETE_OWNERSHIP_UNPROVEN = "DO_NOT_DELETE_OWNERSHIP_UNPROVEN"


class CleanupRule(StrictCleanupModel):
    logical_id: LogicalId
    resource_type: str
    ownership_proof: OwnershipProof
    lifecycle: ResourceLifecycle
    rollback_action: CleanupAction
    partial_failure_action: CleanupAction
    cleanup_behavior: str

    @model_validator(mode="after")
    def validate_rule(self) -> Self:
        retained = self.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION
        expected = (
            CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
            if retained
            else CleanupAction.DELETE_WITH_CLOUDFORMATION_STACK
        )
        expected_partial = (
            CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
            if retained
            else CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE
        )
        if self.rollback_action is not expected or self.partial_failure_action is not expected_partial:
            raise ValueError("cleanup rule contradicts resource lifecycle")
        return self


class RollbackCleanupContract(StrictCleanupModel):
    schema_version: Literal[1]
    contract_id: Literal["AIOA_PHASE3_ROLLBACK_CLEANUP_CONTRACT"]
    policy: Literal["OWNERSHIP_BOUND_EXPLICIT_APPROVAL_ONLY"]
    deployment_contract_sha256: Sha256Digest
    expected_resource_manifest_sha256: Sha256Digest
    partial_states: tuple[DeploymentPartialState, ...]
    ownership_requirements: tuple[
        Literal[
            "DEPLOYMENT_ID_MATCH",
            "STACK_ID_HASH_MATCH",
            "STACK_MEMBERSHIP_CONFIRMED",
            "CONTRACT_HASH_MATCH",
            "LOGICAL_ID_AND_TYPE_MATCH",
            "EXACT_TAGS_WHEN_SUPPORTED",
        ],
        ...,
    ]
    approval_requirements: tuple[
        Literal[
            "EXPLICIT_APPROVED_DECISION",
            "PLAN_HASH_MATCH",
            "DEPLOYMENT_ID_MATCH",
            "FIFTEEN_MINUTE_MAX_LIFETIME",
            "ONE_TIME_NONCE",
            "EXACT_ACTION_SET",
        ],
        ...,
    ]
    ownership_tags: dict[str, str]
    rules: tuple[CleanupRule, ...]
    retained_resources_require_separate_disposition: Literal[True]
    execution_default_enabled: Literal[False]
    cli_emits_cloud_commands: Literal[False]
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]

    @model_validator(mode="after")
    def validate_contract(self) -> Self:
        if tuple(self.partial_states) != tuple(DeploymentPartialState):
            raise ValueError("all deployment partial states must be explicit and ordered")
        if tuple(sorted(rule.logical_id for rule in self.rules)) != tuple(
            rule.logical_id for rule in self.rules
        ):
            raise ValueError("cleanup rules must be ordered by logical ID")
        if len({rule.logical_id for rule in self.rules}) != len(self.rules):
            raise ValueError("cleanup rule logical IDs must be unique")
        if self.ownership_tags != {
            "AIOAProject": "NonZeroCloudOps",
            "AIOAStage": "hackathon",
            "ManagedBy": "CloudFormation",
        }:
            raise ValueError("cleanup ownership tags must be exact")
        return self


class DeploymentCleanupBinding(StrictCleanupModel):
    deployment_id: DeploymentId
    repo_sha: GitSha
    deployment_contract_sha256: Sha256Digest
    expected_resource_manifest_sha256: Sha256Digest
    stack_id_sha256: Sha256Digest


class ObservedCleanupResource(StrictCleanupModel):
    logical_id: LogicalId
    resource_type: str
    deployment_id: DeploymentId
    deployment_contract_sha256: Sha256Digest
    stack_id_sha256: Sha256Digest
    stack_membership_confirmed: bool
    ownership_tags: dict[str, str] | None
    cleanup_attempt_state: CleanupAttemptState


class CleanupObservationFixture(StrictCleanupModel):
    schema_version: Literal[1]
    fixture_id: Literal["PHASE3_SYNTHETIC_CLEANUP_OBSERVATIONS"]
    synthetic: Literal[True]
    binding: DeploymentCleanupBinding
    resources: tuple[ObservedCleanupResource, ...]
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]

    @model_validator(mode="after")
    def validate_resources(self) -> Self:
        if tuple(sorted(item.logical_id for item in self.resources)) != tuple(
            item.logical_id for item in self.resources
        ):
            raise ValueError("observations must be ordered by logical ID")
        if len({item.logical_id for item in self.resources}) != len(self.resources):
            raise ValueError("observed logical IDs must be unique")
        return self


class CleanupPlanItem(StrictCleanupModel):
    logical_id: LogicalId
    resource_type: str
    action: CleanupAction
    ownership_proven: bool
    reason: str
    destructive: bool

    @model_validator(mode="after")
    def validate_action(self) -> Self:
        destructive_actions = {
            CleanupAction.DELETE_WITH_CLOUDFORMATION_STACK,
            CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE,
        }
        if self.destructive != (self.action in destructive_actions):
            raise ValueError("cleanup action destructive flag is inconsistent")
        if self.destructive and not self.ownership_proven:
            raise ValueError("destructive cleanup requires proven ownership")
        return self


class CleanupPlan(StrictCleanupModel):
    schema_version: Literal[1]
    plan_type: Literal["PHASE3_CLEANUP_PLAN_ONLY"]
    status: CleanupPlanStatus
    deployment_state: DeploymentPartialState
    binding: DeploymentCleanupBinding
    cleanup_contract_sha256: Sha256Digest
    items: tuple[CleanupPlanItem, ...]
    destructive_action_ids: tuple[Literal["CLEANUP_STACK_DELETE"], ...]
    requires_explicit_operator_approval: Literal[True]
    execution_default_enabled: Literal[False]
    cloud_commands_emitted: Literal[0]
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]
    plan_sha256: Sha256Digest

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if tuple(sorted(item.logical_id for item in self.items)) != tuple(
            item.logical_id for item in self.items
        ):
            raise ValueError("cleanup plan items must be ordered by logical ID")
        blocked = any(
            item.action is CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN
            for item in self.items
        )
        destructive = any(item.destructive for item in self.items)
        expected_status = (
            CleanupPlanStatus.BLOCKED_OWNERSHIP
            if blocked
            else CleanupPlanStatus.READY_FOR_OPERATOR_REVIEW
            if destructive
            else CleanupPlanStatus.NO_ACTION_REQUIRED
        )
        if self.status is not expected_status:
            raise ValueError("cleanup plan status is inconsistent")
        expected_actions = ("CLEANUP_STACK_DELETE",) if destructive and not blocked else ()
        if self.destructive_action_ids != expected_actions:
            raise ValueError("cleanup destructive action set is inconsistent")
        material = self.model_dump(mode="json", exclude={"plan_sha256"})
        if self.plan_sha256 != hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest():
            raise ValueError("cleanup plan hash is invalid")
        return self


class CleanupApproval(StrictCleanupModel):
    schema_version: Literal[1]
    decision: Literal["APPROVED"]
    deployment_id: DeploymentId
    plan_sha256: Sha256Digest
    destructive_action_ids: tuple[Literal["CLEANUP_STACK_DELETE"], ...]
    operator_subject_sha256: Sha256Digest
    approval_nonce_sha256: Sha256Digest
    issued_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_lifetime(self) -> Self:
        for value in (self.issued_at, self.expires_at):
            if value.tzinfo is None or value.utcoffset() != timedelta(0):
                raise ValueError("cleanup approval timestamps must be UTC")
        if self.expires_at <= self.issued_at:
            raise ValueError("cleanup approval expiry must be after issue")
        if self.expires_at - self.issued_at > timedelta(minutes=15):
            raise ValueError("cleanup approval lifetime exceeds fifteen minutes")
        if self.destructive_action_ids != ("CLEANUP_STACK_DELETE",):
            raise ValueError("cleanup approval action set must be exact")
        return self


class CleanupAuthorizationEnvelope(StrictCleanupModel):
    schema_version: Literal[1]
    status: Literal["AUTHORIZED_BUT_NOT_EXECUTED"]
    deployment_id: DeploymentId
    plan_sha256: Sha256Digest
    approval_nonce_sha256: Sha256Digest
    destructive_action_ids: tuple[Literal["CLEANUP_STACK_DELETE"], ...]
    authorization_sha256: Sha256Digest
    execution_default_enabled: Literal[False]
    cloud_commands_emitted: Literal[0]
    network_connections: Literal[0]
    aws_mutations: Literal[0]
    live_receipts: Literal[0]

    @model_validator(mode="after")
    def validate_authorization(self) -> Self:
        material = self.model_dump(mode="json", exclude={"authorization_sha256"})
        if self.authorization_sha256 != hashlib.sha256(
            canonical_json(material).encode("utf-8")
        ).hexdigest():
            raise ValueError("cleanup authorization hash is invalid")
        return self


def manifest_sha256(manifest: ExpectedResourceManifest) -> str:
    return hashlib.sha256(
        canonical_json(manifest.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


def cleanup_contract_sha256(contract: RollbackCleanupContract) -> str:
    return hashlib.sha256(
        canonical_json(contract.model_dump(mode="json")).encode("utf-8")
    ).hexdigest()


def build_cleanup_contract(
    deployment_contract: AwsDeploymentContract,
    manifest: ExpectedResourceManifest,
) -> RollbackCleanupContract:
    if manifest.deployment_contract_sha256 != contract_sha256(deployment_contract):
        raise CleanupError("CLEANUP_CONTRACT_DEPLOYMENT_BINDING_MISMATCH")
    rules = tuple(
        CleanupRule(
            logical_id=item.logical_id,
            resource_type=item.resource_type,
            ownership_proof=item.ownership_proof,
            lifecycle=item.lifecycle,
            rollback_action=(
                CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
                if item.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION
                else CleanupAction.DELETE_WITH_CLOUDFORMATION_STACK
            ),
            partial_failure_action=(
                CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
                if item.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION
                else CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE
            ),
            cleanup_behavior=item.cleanup_behavior,
        )
        for item in manifest.resources
    )
    return RollbackCleanupContract(
        schema_version=1,
        contract_id="AIOA_PHASE3_ROLLBACK_CLEANUP_CONTRACT",
        policy="OWNERSHIP_BOUND_EXPLICIT_APPROVAL_ONLY",
        deployment_contract_sha256=contract_sha256(deployment_contract),
        expected_resource_manifest_sha256=manifest_sha256(manifest),
        partial_states=tuple(DeploymentPartialState),
        ownership_requirements=(
            "DEPLOYMENT_ID_MATCH",
            "STACK_ID_HASH_MATCH",
            "STACK_MEMBERSHIP_CONFIRMED",
            "CONTRACT_HASH_MATCH",
            "LOGICAL_ID_AND_TYPE_MATCH",
            "EXACT_TAGS_WHEN_SUPPORTED",
        ),
        approval_requirements=(
            "EXPLICIT_APPROVED_DECISION",
            "PLAN_HASH_MATCH",
            "DEPLOYMENT_ID_MATCH",
            "FIFTEEN_MINUTE_MAX_LIFETIME",
            "ONE_TIME_NONCE",
            "EXACT_ACTION_SET",
        ),
        ownership_tags=deployment_contract.application.ownership_tags.value,
        rules=rules,
        retained_resources_require_separate_disposition=True,
        execution_default_enabled=False,
        cli_emits_cloud_commands=False,
        network_connections=0,
        aws_mutations=0,
        live_receipts=0,
    )


def _strict_json(raw: str, *, invalid_reason: str) -> object:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in values:
            if name in result:
                raise ValueError("duplicate key")
            result[name] = value
        return result

    try:
        return json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CleanupError(invalid_reason) from error


def load_expected_resource_manifest(path: Path) -> ExpectedResourceManifest:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CleanupError("EXPECTED_RESOURCE_MANIFEST_UNAVAILABLE") from error
    _strict_json(raw, invalid_reason="EXPECTED_RESOURCE_MANIFEST_INVALID")
    try:
        return ExpectedResourceManifest.model_validate_json(raw)
    except ValidationError as error:
        raise CleanupError("EXPECTED_RESOURCE_MANIFEST_INVALID") from error


def load_cleanup_contract(path: Path) -> RollbackCleanupContract:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CleanupError("CLEANUP_CONTRACT_UNAVAILABLE") from error
    _strict_json(raw, invalid_reason="CLEANUP_CONTRACT_INVALID")
    try:
        return RollbackCleanupContract.model_validate_json(raw)
    except ValidationError as error:
        raise CleanupError("CLEANUP_CONTRACT_INVALID") from error


def load_cleanup_observations(path: Path) -> CleanupObservationFixture:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CleanupError("CLEANUP_OBSERVATIONS_UNAVAILABLE") from error
    _strict_json(raw, invalid_reason="CLEANUP_OBSERVATIONS_INVALID")
    try:
        return CleanupObservationFixture.model_validate_json(raw)
    except ValidationError as error:
        raise CleanupError("CLEANUP_OBSERVATIONS_INVALID") from error


def _ownership_proven(
    observation: ObservedCleanupResource,
    rule: CleanupRule,
    binding: DeploymentCleanupBinding,
    tags: dict[str, str],
) -> bool:
    if (
        observation.logical_id != rule.logical_id
        or observation.resource_type != rule.resource_type
        or observation.deployment_id != binding.deployment_id
        or observation.deployment_contract_sha256 != binding.deployment_contract_sha256
        or observation.stack_id_sha256 != binding.stack_id_sha256
        or not observation.stack_membership_confirmed
    ):
        return False
    if rule.ownership_proof is OwnershipProof.STACK_AND_EXACT_TAGS:
        return observation.ownership_tags == tags
    return observation.ownership_tags is None


def _plan_material(
    *,
    status: CleanupPlanStatus,
    deployment_state: DeploymentPartialState,
    binding: DeploymentCleanupBinding,
    contract_hash: str,
    items: tuple[CleanupPlanItem, ...],
    destructive_action_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "aws_mutations": 0,
        "binding": binding.model_dump(mode="json"),
        "cleanup_contract_sha256": contract_hash,
        "cloud_commands_emitted": 0,
        "deployment_state": deployment_state.value,
        "destructive_action_ids": list(destructive_action_ids),
        "execution_default_enabled": False,
        "items": [item.model_dump(mode="json") for item in items],
        "live_receipts": 0,
        "network_connections": 0,
        "plan_type": "PHASE3_CLEANUP_PLAN_ONLY",
        "requires_explicit_operator_approval": True,
        "schema_version": 1,
        "status": status.value,
    }


def plan_cleanup(
    contract: RollbackCleanupContract,
    observations: CleanupObservationFixture,
    *,
    deployment_state: DeploymentPartialState,
) -> CleanupPlan:
    """Create an idempotent plan. This function cannot execute or emit a cloud command."""

    binding = observations.binding
    if binding.deployment_contract_sha256 != contract.deployment_contract_sha256:
        raise CleanupError("CLEANUP_DEPLOYMENT_CONTRACT_MISMATCH")
    if binding.expected_resource_manifest_sha256 != contract.expected_resource_manifest_sha256:
        raise CleanupError("CLEANUP_RESOURCE_MANIFEST_MISMATCH")
    rules = {item.logical_id: item for item in contract.rules}
    observed = {item.logical_id: item for item in observations.resources}
    items: list[CleanupPlanItem] = []
    for logical_id in sorted(set(rules) | set(observed)):
        rule = rules.get(logical_id)
        observation = observed.get(logical_id)
        if rule is None and observation is not None:
            items.append(
                CleanupPlanItem(
                    logical_id=logical_id,
                    resource_type=observation.resource_type,
                    action=CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN,
                    ownership_proven=False,
                    reason="RESOURCE_NOT_IN_EXPECTED_MANIFEST",
                    destructive=False,
                )
            )
            continue
        if rule is None:
            raise CleanupError("CLEANUP_RULE_INTERNAL_ERROR")
        if observation is None:
            items.append(
                CleanupPlanItem(
                    logical_id=logical_id,
                    resource_type=rule.resource_type,
                    action=CleanupAction.NO_OBSERVED_RESOURCE,
                    ownership_proven=False,
                    reason="RESOURCE_NOT_OBSERVED_IN_PARTIAL_STATE",
                    destructive=False,
                )
            )
            continue
        owned = _ownership_proven(observation, rule, binding, contract.ownership_tags)
        if not owned:
            items.append(
                CleanupPlanItem(
                    logical_id=logical_id,
                    resource_type=observation.resource_type,
                    action=CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN,
                    ownership_proven=False,
                    reason="OWNERSHIP_BINDING_NOT_PROVEN",
                    destructive=False,
                )
            )
            continue
        if observation.cleanup_attempt_state is CleanupAttemptState.PREVIOUSLY_CONFIRMED_ABSENT:
            action = CleanupAction.ALREADY_CONFIRMED_ABSENT
            reason = "INDEPENDENT_ABSENCE_ALREADY_RECORDED"
        elif rule.lifecycle is ResourceLifecycle.RETAIN_EXPLICIT_DISPOSITION:
            action = CleanupAction.RETAIN_PENDING_EXPLICIT_DISPOSITION
            reason = "RETAIN_POLICY_REQUIRES_SEPARATE_DATA_OR_VERSION_DISPOSITION"
        elif (
            deployment_state is DeploymentPartialState.ROLLBACK_PARTIALLY_FAILED
            or observation.cleanup_attempt_state is CleanupAttemptState.PREVIOUSLY_FAILED
        ):
            action = CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE
            reason = "OWNED_STACK_RESOURCE_REMAINS_AFTER_FAILED_CLEANUP"
        else:
            action = CleanupAction.DELETE_WITH_CLOUDFORMATION_STACK
            reason = "OWNED_STACK_RESOURCE_ELIGIBLE_AFTER_EXPLICIT_APPROVAL"
        items.append(
            CleanupPlanItem(
                logical_id=logical_id,
                resource_type=rule.resource_type,
                action=action,
                ownership_proven=True,
                reason=reason,
                destructive=action
                in {
                    CleanupAction.DELETE_WITH_CLOUDFORMATION_STACK,
                    CleanupAction.RETRY_CLOUDFORMATION_STACK_DELETE,
                },
            )
        )
    frozen_items = tuple(items)
    blocked = any(
        item.action is CleanupAction.DO_NOT_DELETE_OWNERSHIP_UNPROVEN
        for item in frozen_items
    )
    destructive = any(item.destructive for item in frozen_items)
    status = (
        CleanupPlanStatus.BLOCKED_OWNERSHIP
        if blocked
        else CleanupPlanStatus.READY_FOR_OPERATOR_REVIEW
        if destructive
        else CleanupPlanStatus.NO_ACTION_REQUIRED
    )
    destructive_actions: tuple[str, ...] = (
        ("CLEANUP_STACK_DELETE",) if destructive and not blocked else ()
    )
    contract_hash = cleanup_contract_sha256(contract)
    material = _plan_material(
        status=status,
        deployment_state=deployment_state,
        binding=binding,
        contract_hash=contract_hash,
        items=frozen_items,
        destructive_action_ids=destructive_actions,
    )
    plan_hash = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return CleanupPlan.model_validate_json(
        canonical_json({**material, "plan_sha256": plan_hash})
    )


def authorize_cleanup_plan(
    plan: CleanupPlan,
    approval: CleanupApproval,
    *,
    now: datetime,
    consumed_nonce_hashes: frozenset[str],
) -> CleanupAuthorizationEnvelope:
    """Validate one approval and return a non-executing future authorization envelope."""

    if now.tzinfo is None or now.utcoffset() != timedelta(0):
        raise CleanupError("CLEANUP_AUTHORIZATION_CLOCK_INVALID")
    if plan.status is not CleanupPlanStatus.READY_FOR_OPERATOR_REVIEW:
        raise CleanupError("CLEANUP_PLAN_NOT_AUTHORIZABLE")
    if approval.deployment_id != plan.binding.deployment_id:
        raise CleanupError("CLEANUP_APPROVAL_DEPLOYMENT_MISMATCH")
    if approval.plan_sha256 != plan.plan_sha256:
        raise CleanupError("CLEANUP_APPROVAL_PLAN_MISMATCH")
    if approval.destructive_action_ids != plan.destructive_action_ids:
        raise CleanupError("CLEANUP_APPROVAL_ACTION_SET_MISMATCH")
    if now < approval.issued_at or now >= approval.expires_at:
        raise CleanupError("CLEANUP_APPROVAL_STALE")
    if approval.approval_nonce_sha256 in consumed_nonce_hashes:
        raise CleanupError("CLEANUP_APPROVAL_REPLAYED")
    material: dict[str, object] = {
        "approval_nonce_sha256": approval.approval_nonce_sha256,
        "aws_mutations": 0,
        "cloud_commands_emitted": 0,
        "deployment_id": plan.binding.deployment_id,
        "destructive_action_ids": list(plan.destructive_action_ids),
        "execution_default_enabled": False,
        "live_receipts": 0,
        "network_connections": 0,
        "plan_sha256": plan.plan_sha256,
        "schema_version": 1,
        "status": "AUTHORIZED_BUT_NOT_EXECUTED",
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return CleanupAuthorizationEnvelope.model_validate_json(
        canonical_json({**material, "authorization_sha256": digest})
    )


def render_cleanup_contract_schema() -> str:
    return pretty_json(RollbackCleanupContract.model_json_schema(mode="validation"))


def render_cleanup_plan_schema() -> str:
    return pretty_json(CleanupPlan.model_json_schema(mode="validation"))


def render_cleanup_contract_markdown(contract: RollbackCleanupContract) -> str:
    rows = [
        f"| `{rule.logical_id}` | `{rule.resource_type}` | `{rule.ownership_proof.value}` | "
        f"`{rule.lifecycle.value}` | `{rule.rollback_action.value}` | "
        f"`{rule.partial_failure_action.value}` |"
        for rule in contract.rules
    ]
    states = [f"- `{state.value}`" for state in contract.partial_states]
    return "\n".join(
        [
            "# Phase 3 Rollback and Cleanup Contract",
            "",
            "Status: local plan-only contract. It performs no AWS read or write and emits no cloud "
            "command.",
            "",
            f"- Deployment contract SHA-256: `{contract.deployment_contract_sha256}`",
            f"- Expected-resource manifest SHA-256: "
            f"`{contract.expected_resource_manifest_sha256}`",
            f"- Cleanup contract SHA-256: `{cleanup_contract_sha256(contract)}`",
            "- Execution enabled by default: `false`",
            "- Network connections / AWS mutations / live receipts: `0 / 0 / 0`",
            "",
            "## Partial states",
            "",
            *states,
            "",
            "Every retry rebuilds the same plan from durable bindings. Expired approval requires a "
            "fresh decision. A failed rollback plans only still-observed, proven-owned resources.",
            "",
            "## Resource rules",
            "",
            "| Logical ID | Type | Ownership proof | Lifecycle | Normal rollback | Partial failure |",
            "|---|---|---|---|---|---|",
            *rows,
            "",
            "A name is never ownership proof. Deletion eligibility requires the deployment ID, "
            "contract hash, stack ID hash, CloudFormation membership, logical ID/type, and exact "
            "ownership tags when the resource supports tags. Foreign or ambiguous resources are "
            "always `DO_NOT_DELETE_OWNERSHIP_UNPROVEN`.",
            "",
            "## Approval and execution boundary",
            "",
            "The local CLI can only produce a plan. A future executor must separately validate a "
            "fifteen-minute maximum approval bound to the exact deployment, plan hash, one-time nonce, "
            "operator subject hash, and exact action set. Even the authorization envelope remains "
            "`AUTHORIZED_BUT_NOT_EXECUTED`; it emits no AWS command.",
            "",
            "## Cost containment and residual verification",
            "",
            "Logs have three-day retention, DynamoDB uses on-demand capacity, Lambda reserved "
            "concurrency is one, model output is bounded, and no CloudFront or provisioned capacity is "
            "planned. Stack deletion handles ordinary resources. The DynamoDB table and two immutable "
            "Lambda versions are intentionally retained and require separate, ownership-bound data or "
            "rollback disposition; they are never silently deleted. After any future rollback, the "
            "operator must perform a read-only stack/resource inventory, reconcile it against the "
            "expected manifest, and record either zero unexpected residuals or a typed residual list.",
            "",
        ]
    )
