"""PLAN_AND_CONFIRM proposal builder with deterministic local authority policy."""

import json
from datetime import datetime, timedelta
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import (
    CloudFinding,
    CloudResourceType,
    ControlResult,
    Ec2Resource,
    FailureDetail,
    FailureKind,
    PlanDisposition,
    RemediationOperation,
    RemediationPlan,
    RemediationProposal,
    ResourceEvidence,
    SecurityGroupResource,
    ShortIdentifier,
)

from .query_resource import REQUIRED_EC2_TAGS


class ModelPlanCandidate(BaseModel):
    """Strict untrusted model output; local policy remains authoritative."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: PlanDisposition
    operation_type: RemediationOperation | None = None
    target_resource_type: CloudResourceType | None = None
    target_resource_id: ShortIdentifier | None = None
    normalized_parameters: dict[ShortIdentifier, JsonValue] | None = None
    claimed_authority: AuthorityGate | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        optional_values = (
            self.operation_type,
            self.target_resource_type,
            self.target_resource_id,
            self.normalized_parameters,
            self.claimed_authority,
        )
        if self.disposition is PlanDisposition.NO_ACTION:
            if any(value is not None for value in optional_values):
                raise ValueError("NO_ACTION model plan must not contain operation data")
        elif any(value is None for value in optional_values):
            raise ValueError("model proposal must contain all exact operation fields")
        return self


def canonical_model_candidate(evidence: ResourceEvidence) -> ModelPlanCandidate:
    """Derive the only candidate that local evidence and authority policy permit."""

    if evidence.findings == (CloudFinding.CLEAN,):
        return ModelPlanCandidate(disposition=PlanDisposition.NO_ACTION)
    if evidence.findings == (CloudFinding.UNATTACHED_ELASTIC_IP,):
        return ModelPlanCandidate(
            disposition=PlanDisposition.PROPOSAL,
            operation_type=RemediationOperation.RELEASE_ELASTIC_IP,
            target_resource_type=CloudResourceType.ELASTIC_IP,
            target_resource_id=evidence.resource.resource_id,
            normalized_parameters={"allocation_id": evidence.resource.resource_id},
            claimed_authority=AuthorityGate.PLAN_AND_CONFIRM,
        )
    if evidence.findings == (CloudFinding.OVERLY_PERMISSIVE_INGRESS,):
        if not isinstance(evidence.resource, SecurityGroupResource):
            raise ValueError("security-group finding requires security-group evidence")
        unsafe_rules = [
            rule.model_dump(mode="json")
            for rule in evidence.resource.inbound_rules
            if rule.cidr_ipv4 == "0.0.0.0/0"
        ]
        if not unsafe_rules:
            raise ValueError("security-group finding has no observed unsafe rule")
        return ModelPlanCandidate(
            disposition=PlanDisposition.PROPOSAL,
            operation_type=RemediationOperation.REVOKE_PUBLIC_INGRESS,
            target_resource_type=CloudResourceType.SECURITY_GROUP,
            target_resource_id=evidence.resource.resource_id,
            normalized_parameters={
                "ingress_rules": unsafe_rules,
                "security_group_id": evidence.resource.resource_id,
            },
            claimed_authority=AuthorityGate.PLAN_AND_CONFIRM,
        )
    if evidence.findings == (CloudFinding.REQUIRED_TAGS_MISSING,):
        if not isinstance(evidence.resource, Ec2Resource):
            raise ValueError("tag finding requires EC2 evidence")
        missing = sorted(REQUIRED_EC2_TAGS - evidence.resource.tags.keys())
        return ModelPlanCandidate(
            disposition=PlanDisposition.NON_EXECUTABLE_RECOMMENDATION,
            operation_type=RemediationOperation.APPLY_REQUIRED_TAGS,
            target_resource_type=CloudResourceType.EC2_INSTANCE,
            target_resource_id=evidence.resource.resource_id,
            normalized_parameters={
                "tags": {
                    key: "hackathon" if key == "Environment" else "platform"
                    for key in missing
                }
            },
            claimed_authority=AuthorityGate.NEVER_AUTONOMOUS,
        )
    raise ValueError("resource findings do not have a supported remediation policy")


class PlanRemediation:
    """Validate model data against evidence, then create inert proposal data only."""

    authority = AuthorityGate.PLAN_AND_CONFIRM

    def execute(
        self,
        evidence: ResourceEvidence | object,
        *,
        model_output: str,
        proposal_id: UUID,
        created_at: datetime,
    ) -> ControlResult[RemediationPlan]:
        try:
            validated_evidence = ResourceEvidence.model_validate(evidence)
        except ValidationError:
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "PLAN_EVIDENCE_INVALID",
                "PlanRemediation requires validated resource evidence",
            )
        if not isinstance(model_output, str) or not model_output.strip():
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "MODEL_PLAN_INVALID",
                "Model plan output must be non-empty JSON",
            )
        try:
            payload = json.loads(model_output)
            candidate = ModelPlanCandidate.model_validate(payload)
        except (json.JSONDecodeError, ValidationError, TypeError):
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "MODEL_PLAN_INVALID",
                "Model plan output failed strict validation",
            )
        try:
            expected = canonical_model_candidate(validated_evidence)
        except ValueError:
            return self._failed(
                FailureKind.POLICY_DENIAL,
                "REMEDIATION_POLICY_UNSUPPORTED",
                "Observed findings are outside the local remediation policy",
            )
        if candidate != expected:
            return self._failed(
                FailureKind.POLICY_DENIAL,
                "MODEL_PLAN_POLICY_MISMATCH",
                "Model plan does not match evidence-bound local policy",
            )
        if expected.disposition is PlanDisposition.NO_ACTION:
            return ControlResult[RemediationPlan].succeeded(
                RemediationPlan(
                    disposition=PlanDisposition.NO_ACTION,
                    evidence_hash=validated_evidence.evidence_hash,
                    reason="Resource is compliant; no remediation is warranted",
                )
            )
        operation = expected.operation_type
        parameters = expected.normalized_parameters
        authority = expected.claimed_authority
        if operation is None or parameters is None or authority is None:
            return self._failed(
                FailureKind.POLICY_DENIAL,
                "REMEDIATION_POLICY_INCOMPLETE",
                "Local remediation policy did not resolve exact action data",
            )
        risk = {
            RemediationOperation.RELEASE_ELASTIC_IP: (
                "Releasing an address is destructive and requires exact human approval"
            ),
            RemediationOperation.REVOKE_PUBLIC_INGRESS: (
                "Changing ingress can disrupt access and requires exact human approval"
            ),
            RemediationOperation.APPLY_REQUIRED_TAGS: (
                "Tag mutation is recommendation-only under the current hard policy"
            ),
        }[operation]
        try:
            proposal = RemediationProposal.create(
                proposal_id=proposal_id,
                evidence=validated_evidence,
                operation_type=operation,
                normalized_parameters=parameters,
                authority_class=authority,
                risk_summary=risk,
                created_at=created_at,
                expires_at=created_at + timedelta(hours=24),
            )
        except (TypeError, ValueError):
            return self._failed(
                FailureKind.VALIDATION_FAILURE,
                "PROPOSAL_CONTRACT_INVALID",
                "Evidence-bound proposal failed canonical validation",
            )
        return ControlResult[RemediationPlan].succeeded(
            RemediationPlan(
                disposition=expected.disposition,
                evidence_hash=validated_evidence.evidence_hash,
                proposal=proposal,
                reason=risk,
            )
        )

    @staticmethod
    def _failed(
        kind: FailureKind,
        code: str,
        message: str,
    ) -> ControlResult[RemediationPlan]:
        return ControlResult[RemediationPlan].failed(
            FailureDetail(kind=kind, code=code, message=message, retryable=False)
        )
