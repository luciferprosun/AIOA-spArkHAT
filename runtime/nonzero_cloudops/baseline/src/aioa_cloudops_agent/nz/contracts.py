"""Pydantic contracts at Non-Zero model, control, and durable boundaries."""

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from aioa_cloudops_agent.domain.enums import AuthorityGate

from .authority import require_capability_authority
from .enums import (
    ActionOutcome,
    ApprovalDecision,
    AuditEventType,
    Capability,
    CloudFinding,
    CloudResourceType,
    ExecutionAcknowledgementStatus,
    IdempotencyStatus,
    ObservedInstanceState,
    PlanDisposition,
    ProposalState,
    RemediationOperation,
    VerificationDisposition,
    VerificationProofOrigin,
    WorkflowState,
)
from .errors import FailureDetail
from .identifiers import (
    Ec2InstanceId,
    IdempotencyKey,
    NonEmptyText,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
)
from .redaction import contains_sensitive_material
from .transitions import validate_workflow_transition


def _require_utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value


def _canonical_digest(payload: object) -> str:
    """Hash strict canonical JSON used by local evidence and proposal bindings."""

    canonical = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class NonZeroContract(BaseModel):
    """Shared strict shape: immutable fields and no unknown model output."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class BudgetCounters(NonZeroContract):
    """Bounded consumption retained with a durable run."""

    max_turns: int = Field(gt=0, le=1_000)
    max_tokens: int = Field(gt=0, le=10_000_000)
    max_elapsed_seconds: int = Field(default=60, gt=0, le=3_600)
    turns_used: int = Field(default=0, ge=0)
    tokens_used: int = Field(default=0, ge=0)
    elapsed_milliseconds_used: int = Field(default=0, ge=0, le=3_600_000)

    @model_validator(mode="after")
    def validate_consumption(self) -> Self:
        if self.turns_used > self.max_turns:
            raise ValueError("turns_used must not exceed max_turns")
        if self.tokens_used > self.max_tokens:
            raise ValueError("tokens_used must not exceed max_tokens")
        if self.elapsed_milliseconds_used > self.max_elapsed_seconds * 1_000:
            raise ValueError("elapsed_milliseconds_used must not exceed the time budget")
        return self


class Run(NonZeroContract):
    """Versioned workflow truth with explicit identity, lifecycle, and budgets."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    idempotency_key: IdempotencyKey
    state: WorkflowState
    created_at: datetime
    updated_at: datetime
    budget: BudgetCounters
    version: int = Field(default=1, gt=0)

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(field_name, value)

    @model_validator(mode="after")
    def validate_time_order(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        return self

    @classmethod
    def new(
        cls,
        *,
        run_id: Uuid7Identifier,
        trace_id: Uuid7Identifier,
        correlation_id: Uuid7Identifier,
        idempotency_key: IdempotencyKey,
        created_at: datetime,
        budget: BudgetCounters,
    ) -> "Run":
        return cls(
            run_id=run_id,
            trace_id=trace_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            state=WorkflowState.RECEIVED,
            created_at=created_at,
            updated_at=created_at,
            budget=budget,
            version=1,
        )


def transition_run(run: Run, next_state: WorkflowState, *, updated_at: datetime) -> Run:
    """Create a validated next version without trusting unvalidated model updates."""

    if not isinstance(run, Run):
        raise TypeError("run must be a Run")
    valid_state = validate_workflow_transition(run.state, next_state)
    valid_time = _require_utc("updated_at", updated_at)
    if valid_time < run.updated_at:
        raise ValueError("updated_at must not precede the current run timestamp")
    values = run.model_dump()
    values.update(
        {
            "state": valid_state,
            "updated_at": valid_time,
            "version": run.version + 1,
        }
    )
    return Run.model_validate(values)


class ResourceQuery(NonZeroContract):
    """Validated provider-neutral identity for one exact resource read."""

    resource_type: CloudResourceType
    resource_id: ShortIdentifier
    region: ShortIdentifier = "eu-central-1"

    @model_validator(mode="after")
    def validate_identifier_shape(self) -> Self:
        patterns = {
            CloudResourceType.EC2_INSTANCE: r"^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$",
            CloudResourceType.ELASTIC_IP: r"^eipalloc-[0-9a-f]{8}(?:[0-9a-f]{9})?$",
            CloudResourceType.SECURITY_GROUP: r"^sg-[0-9a-f]{8}(?:[0-9a-f]{9})?$",
        }
        if re.fullmatch(patterns[self.resource_type], self.resource_id) is None:
            raise ValueError("resource_id does not match resource_type")
        return self


class SecurityGroupRule(NonZeroContract):
    """Normalized ingress/egress rule sufficient for deterministic risk checks."""

    ip_protocol: NonEmptyText
    cidr_ipv4: NonEmptyText
    from_port: int | None = Field(default=None, ge=0, le=65_535)
    to_port: int | None = Field(default=None, ge=0, le=65_535)

    @field_validator("cidr_ipv4")
    @classmethod
    def validate_cidr(cls, value: str) -> str:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError as error:
            raise ValueError("cidr_ipv4 must be a valid IPv4 network") from error
        if network.version != 4:
            raise ValueError("cidr_ipv4 must be an IPv4 network")
        return str(network)

    @model_validator(mode="after")
    def validate_ports(self) -> Self:
        if self.ip_protocol == "-1":
            if self.from_port is not None or self.to_port is not None:
                raise ValueError("all-protocol rules must omit ports")
        elif self.from_port is None or self.to_port is None:
            raise ValueError("scoped protocol rules require both ports")
        elif self.from_port > self.to_port:
            raise ValueError("from_port must not exceed to_port")
        return self


class Ec2Resource(NonZeroContract):
    """Compact normalized EC2-like inventory record."""

    resource_type: Literal[CloudResourceType.EC2_INSTANCE] = CloudResourceType.EC2_INSTANCE
    resource_id: str = Field(pattern=r"^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
    region: ShortIdentifier
    state: Literal["pending", "running", "stopping", "stopped", "terminated"]
    instance_type: ShortIdentifier
    tags: dict[ShortIdentifier, NonEmptyText]


class ElasticIpResource(NonZeroContract):
    """Compact normalized Elastic-IP-like inventory record."""

    resource_type: Literal[CloudResourceType.ELASTIC_IP] = CloudResourceType.ELASTIC_IP
    resource_id: str = Field(pattern=r"^eipalloc-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
    region: ShortIdentifier
    public_ip: NonEmptyText
    association_id: str | None = Field(
        default=None,
        pattern=r"^eipassoc-[0-9a-f]{8}(?:[0-9a-f]{9})?$",
    )
    tags: dict[ShortIdentifier, NonEmptyText]

    @field_validator("public_ip")
    @classmethod
    def validate_public_ip(cls, value: str) -> str:
        try:
            address = ipaddress.ip_address(value)
        except ValueError as error:
            raise ValueError("public_ip must be a valid IP address") from error
        if address.version != 4:
            raise ValueError("public_ip must be IPv4")
        return str(address)


class SecurityGroupResource(NonZeroContract):
    """Compact normalized Security-Group-like inventory record."""

    resource_type: Literal[CloudResourceType.SECURITY_GROUP] = CloudResourceType.SECURITY_GROUP
    resource_id: str = Field(pattern=r"^sg-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
    region: ShortIdentifier
    vpc_id: str = Field(pattern=r"^vpc-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
    inbound_rules: tuple[SecurityGroupRule, ...]
    outbound_rules: tuple[SecurityGroupRule, ...]
    tags: dict[ShortIdentifier, NonEmptyText]


CloudResource = Annotated[
    Ec2Resource | ElasticIpResource | SecurityGroupResource,
    Field(discriminator="resource_type"),
]


class ResourceProvenance(NonZeroContract):
    """Structured origin of normalized facts without raw provider internals."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    source: Literal["query_resource"] = "query_resource"
    adapter: ShortIdentifier
    resource_type: CloudResourceType
    resource_id: ShortIdentifier
    observed_fields: tuple[NonEmptyText, ...] = Field(min_length=1)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _require_utc("observed_at", value)

    @field_validator("observed_fields")
    @classmethod
    def validate_observed_fields(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if tuple(sorted(set(value))) != value:
            raise ValueError("observed_fields must be unique and canonically ordered")
        return value


class ResourceEvidence(NonZeroContract):
    """Trusted read-only evidence produced through the cloud adapter boundary."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    resource: CloudResource
    findings: tuple[CloudFinding, ...] = Field(min_length=1)
    provenance: ResourceProvenance
    observed_at: datetime
    authority: Literal[AuthorityGate.AUTO] = AuthorityGate.AUTO
    evidence_hash: Sha256Digest

    @field_validator("observed_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _require_utc("observed_at", value)

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if (
            self.run_id != self.provenance.run_id
            or self.trace_id != self.provenance.trace_id
            or self.correlation_id != self.provenance.correlation_id
            or self.resource.resource_type is not self.provenance.resource_type
            or self.resource.resource_id != self.provenance.resource_id
            or self.observed_at != self.provenance.observed_at
        ):
            raise ValueError("resource evidence and provenance identities must match")
        if CloudFinding.CLEAN in self.findings and self.findings != (CloudFinding.CLEAN,):
            raise ValueError("CLEAN cannot coexist with a remediation finding")
        if tuple(sorted(set(self.findings), key=lambda item: item.value)) != self.findings:
            raise ValueError("findings must be unique and canonically ordered")
        if self.evidence_hash != _canonical_digest(self.evidence_payload()):
            raise ValueError("evidence_hash does not match canonical resource evidence")
        return self

    def evidence_payload(self) -> dict[str, object]:
        return {
            "authority": self.authority.value,
            "correlation_id": str(self.correlation_id),
            "findings": [finding.value for finding in self.findings],
            "observed_at": self.observed_at.isoformat(),
            "provenance": self.provenance.model_dump(mode="json"),
            "resource": self.resource.model_dump(mode="json"),
            "run_id": str(self.run_id),
            "trace_id": str(self.trace_id),
        }

    def stable_fingerprint(self) -> Sha256Digest:
        """Bind the observed facts while excluding run identity and timestamps."""

        return _canonical_digest(
            {
                "findings": [finding.value for finding in self.findings],
                "resource": self.resource.model_dump(mode="json"),
            }
        )

    @classmethod
    def create(
        cls,
        *,
        run: Run,
        resource: CloudResource,
        findings: tuple[CloudFinding, ...],
        provenance: ResourceProvenance,
        observed_at: datetime,
    ) -> "ResourceEvidence":
        values: dict[str, object] = {
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "correlation_id": run.correlation_id,
            "resource": resource,
            "findings": findings,
            "provenance": provenance,
            "observed_at": observed_at,
        }
        provisional = cls.model_construct(
            **values,
            authority=AuthorityGate.AUTO,
            evidence_hash="0" * 64,
        )
        return cls(**values, evidence_hash=_canonical_digest(provisional.evidence_payload()))


class RemediationProposal(NonZeroContract):
    """Inert exact-action proposal whose stable hash can be bound to future approval."""

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    normalized_parameters: dict[ShortIdentifier, JsonValue] = Field(min_length=1)
    authority_class: AuthorityGate
    evidence_hash: Sha256Digest
    evidence_fingerprint: Sha256Digest
    risk_summary: NonEmptyText
    created_at: datetime
    expires_at: datetime
    proposal_hash: Sha256Digest
    status: ProposalState = ProposalState.PROPOSED
    version: int = Field(default=1, gt=0)
    authorizes_execution: Literal[False] = False

    @field_validator("created_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info: object) -> datetime:
        return _require_utc(getattr(info, "field_name", "timestamp"), value)

    @model_validator(mode="after")
    def validate_policy_and_hash(self) -> Self:
        policy = {
            RemediationOperation.RELEASE_ELASTIC_IP: (
                CloudResourceType.ELASTIC_IP,
                AuthorityGate.PLAN_AND_CONFIRM,
            ),
            RemediationOperation.REVOKE_PUBLIC_INGRESS: (
                CloudResourceType.SECURITY_GROUP,
                AuthorityGate.PLAN_AND_CONFIRM,
            ),
            RemediationOperation.APPLY_REQUIRED_TAGS: (
                CloudResourceType.EC2_INSTANCE,
                AuthorityGate.NEVER_AUTONOMOUS,
            ),
        }
        expected_type, expected_authority = policy[self.operation_type]
        if self.target_resource_type is not expected_type:
            raise ValueError("operation_type does not match target_resource_type")
        if self.authority_class is not expected_authority:
            raise ValueError("operation_type does not match local authority policy")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be later than created_at")
        if self.proposal_hash != _canonical_digest(self.action_payload()):
            raise ValueError("proposal_hash does not match canonical action content")
        return self

    def action_payload(self) -> dict[str, object]:
        """Return only stable action-defining fields; exclude IDs and timestamps."""

        return {
            "authority_class": self.authority_class.value,
            "evidence_fingerprint": self.evidence_fingerprint,
            "normalized_parameters": self.normalized_parameters,
            "operation_type": self.operation_type.value,
            "target_resource_id": self.target_resource_id,
            "target_resource_type": self.target_resource_type.value,
        }

    @classmethod
    def create(
        cls,
        *,
        proposal_id: Uuid7Identifier,
        evidence: ResourceEvidence,
        operation_type: RemediationOperation,
        normalized_parameters: dict[ShortIdentifier, JsonValue],
        authority_class: AuthorityGate,
        risk_summary: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> "RemediationProposal":
        values: dict[str, object] = {
            "proposal_id": proposal_id,
            "run_id": evidence.run_id,
            "correlation_id": evidence.correlation_id,
            "operation_type": operation_type,
            "target_resource_type": evidence.resource.resource_type,
            "target_resource_id": evidence.resource.resource_id,
            "normalized_parameters": normalized_parameters,
            "authority_class": authority_class,
            "evidence_hash": evidence.evidence_hash,
            "evidence_fingerprint": evidence.stable_fingerprint(),
            "risk_summary": risk_summary,
            "created_at": created_at,
            "expires_at": expires_at,
        }
        provisional = cls.model_construct(
            **values,
            proposal_hash="0" * 64,
            status=ProposalState.PROPOSED,
            version=1,
            authorizes_execution=False,
        )
        return cls(**values, proposal_hash=_canonical_digest(provisional.action_payload()))


class RemediationPlan(NonZeroContract):
    """Explicit proposal, clean result, or non-executable recommendation."""

    disposition: PlanDisposition
    evidence_hash: Sha256Digest
    proposal: RemediationProposal | None = None
    reason: NonEmptyText

    @model_validator(mode="after")
    def validate_disposition(self) -> Self:
        if self.disposition is PlanDisposition.NO_ACTION:
            if self.proposal is not None:
                raise ValueError("NO_ACTION cannot contain a proposal")
        elif self.proposal is None:
            raise ValueError("proposal dispositions require a typed proposal")
        elif self.proposal.evidence_hash != self.evidence_hash:
            raise ValueError("plan and proposal evidence hashes must match")
        elif (
            self.disposition is PlanDisposition.PROPOSAL
            and self.proposal.authority_class is not AuthorityGate.PLAN_AND_CONFIRM
        ):
            raise ValueError("executable proposal data requires PLAN_AND_CONFIRM")
        elif (
            self.disposition is PlanDisposition.NON_EXECUTABLE_RECOMMENDATION
            and self.proposal.authority_class is not AuthorityGate.NEVER_AUTONOMOUS
        ):
            raise ValueError("recommendation requires NEVER_AUTONOMOUS")
        return self


class ActionTarget(NonZeroContract):
    """One explicit sandbox EC2 target; no arbitrary resource argument map."""

    resource_type: Literal["AWS::EC2::Instance"] = "AWS::EC2::Instance"
    resource_id: Ec2InstanceId
    region: Literal["eu-central-1"] = "eu-central-1"
    sandbox_scope: ShortIdentifier
    required_tag_key: ShortIdentifier = "AIOACloudOpsSandbox"
    required_tag_value: ShortIdentifier = "true"


class ExpectedPrecondition(NonZeroContract):
    """Evidence-backed state expected immediately before future execution."""

    instance_state: ObservedInstanceState
    observed_at: datetime
    evidence_hash: Sha256Digest

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _require_utc("observed_at", value)


class ActionProposal(NonZeroContract):
    """Durable write-before-execute proposal that is never approval."""

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    action: Capability
    target: ActionTarget
    expected_precondition: ExpectedPrecondition
    authority: AuthorityGate
    state: ProposalState = ProposalState.PROPOSED
    evidence_hash: Sha256Digest
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc("created_at", value)

    @model_validator(mode="after")
    def validate_mutation_proposal(self) -> Self:
        if self.action is not Capability.STOP_SANDBOX_INSTANCE:
            raise ValueError("only the canonical sandbox stop may form a mutation proposal")
        require_capability_authority(self.action, self.authority)
        if self.expected_precondition.instance_state is not ObservedInstanceState.RUNNING:
            raise ValueError("stop proposal requires a running-instance precondition")
        if self.evidence_hash != self.expected_precondition.evidence_hash:
            raise ValueError("proposal evidence_hash must match precondition evidence")
        return self

    @property
    def authorizes_execution(self) -> Literal[False]:
        """Make the proposal/approval boundary unambiguous to callers."""

        return False


class Approval(NonZeroContract):
    """Explicit human approval or denial, separate from proposal state."""

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    action: Capability
    target: ActionTarget
    evidence_hash: Sha256Digest
    interrupt_id: NonEmptyText
    request_hash: Sha256Digest
    decision: ApprovalDecision
    decided_at: datetime
    actor_session_id: ShortIdentifier
    decision_nonce: NonEmptyText = Field(min_length=16, max_length=256)

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return _require_utc("decided_at", value)

    @model_validator(mode="after")
    def validate_action_binding(self) -> Self:
        if self.action is not Capability.STOP_SANDBOX_INSTANCE:
            raise ValueError("approval can bind only the canonical sandbox stop")
        return self


class ActionResult(NonZeroContract):
    """Explicit future action outcome; no generic success boolean."""

    outcome: ActionOutcome
    observed_state: ObservedInstanceState | None = None
    evidence_hash: Sha256Digest | None = None
    failure: FailureDetail | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        if self.outcome is ActionOutcome.SUCCEEDED:
            if (
                self.observed_state is None
                or self.evidence_hash is None
                or self.failure is not None
            ):
                raise ValueError("successful action result requires evidence and forbids failure")
        elif self.failure is None:
            raise ValueError("non-success action result requires explicit failure detail")
        return self


class ExecutionAcknowledgement(NonZeroContract):
    """Safe provider receipt that cannot represent post-action verification."""

    status: Literal[ExecutionAcknowledgementStatus.ACCEPTED] = (
        ExecutionAcknowledgementStatus.ACCEPTED
    )
    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    action: Literal[Capability.STOP_SANDBOX_INSTANCE] = Capability.STOP_SANDBOX_INSTANCE
    target: ActionTarget
    previous_state: Literal[ObservedInstanceState.RUNNING] = ObservedInstanceState.RUNNING
    current_state: Literal[ObservedInstanceState.STOPPING, ObservedInstanceState.STOPPED]
    request_reference: NonEmptyText | None = None
    acknowledged_at: datetime
    acknowledgement_hash: Sha256Digest

    @field_validator("acknowledged_at")
    @classmethod
    def validate_acknowledged_at(cls, value: datetime) -> datetime:
        return _require_utc("acknowledged_at", value)


class VerificationEvidence(NonZeroContract):
    """Immutable proof that independent EC2 read-back observed the stopped target."""

    evidence_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    disposition: Literal[VerificationDisposition.VERIFIED] = VerificationDisposition.VERIFIED
    action: Literal[Capability.STOP_SANDBOX_INSTANCE] = Capability.STOP_SANDBOX_INSTANCE
    target: ActionTarget
    observed_state: Literal[ObservedInstanceState.STOPPED] = ObservedInstanceState.STOPPED
    verified_at: datetime
    proof_origin: VerificationProofOrigin = VerificationProofOrigin.EXECUTION_ACKNOWLEDGEMENT
    execution_acknowledgement_hash: Sha256Digest | None = None
    recovery_observation_hash: Sha256Digest | None = None
    observation_hash: Sha256Digest
    request_reference: NonEmptyText | None = None
    evidence_hash: Sha256Digest

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: datetime) -> datetime:
        return _require_utc("verified_at", value)

    @model_validator(mode="after")
    def validate_evidence_hash(self) -> Self:
        if self.proof_origin is VerificationProofOrigin.EXECUTION_ACKNOWLEDGEMENT:
            if self.execution_acknowledgement_hash is None:
                raise ValueError("acknowledgement proof requires its durable hash")
            if self.recovery_observation_hash is not None:
                raise ValueError("acknowledgement proof cannot contain recovery proof")
        elif (
            self.recovery_observation_hash is None
            or self.execution_acknowledgement_hash is not None
        ):
            raise ValueError("recovery proof requires only its read-back hash")
        canonical = json.dumps(
            self.evidence_payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if self.evidence_hash != hashlib.sha256(canonical).hexdigest():
            raise ValueError("verification evidence_hash does not match canonical evidence")
        return self

    def evidence_payload(self) -> dict[str, object]:
        """Return canonical decision-relevant proof without provider response leakage."""

        payload: dict[str, object] = {
            "action": self.action.value,
            "correlation_id": str(self.correlation_id),
            "disposition": self.disposition.value,
            "observation_hash": self.observation_hash,
            "observed_state": self.observed_state.value,
            "proposal_id": str(self.proposal_id),
            "request_reference": self.request_reference,
            "run_id": str(self.run_id),
            "target": self.target.model_dump(mode="json"),
            "trace_id": str(self.trace_id),
            "verified_at": self.verified_at.isoformat(),
        }
        if self.proof_origin is VerificationProofOrigin.EXECUTION_ACKNOWLEDGEMENT:
            # Keep the pre-Day-11 canonical shape so already persisted hashes remain valid.
            payload["execution_acknowledgement_hash"] = self.execution_acknowledgement_hash
        else:
            payload["proof_origin"] = self.proof_origin.value
            payload["recovery_observation_hash"] = self.recovery_observation_hash
        return payload

    @classmethod
    def create(
        cls,
        *,
        evidence_id: Uuid7Identifier,
        proposal: ActionProposal,
        run: Run,
        verified_at: datetime,
        acknowledgement: ExecutionAcknowledgement,
        observation_hash: Sha256Digest,
    ) -> "VerificationEvidence":
        """Build linked final proof and its stable canonical SHA-256 digest."""

        if (
            proposal.run_id != run.run_id
            or acknowledgement.proposal_id != proposal.proposal_id
            or acknowledgement.run_id != run.run_id
            or acknowledgement.target != proposal.target
        ):
            raise ValueError("verification evidence prerequisites do not share one identity")
        values: dict[str, object] = {
            "evidence_id": evidence_id,
            "proposal_id": proposal.proposal_id,
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "correlation_id": run.correlation_id,
            "target": proposal.target,
            "verified_at": verified_at,
            "execution_acknowledgement_hash": acknowledgement.acknowledgement_hash,
            "observation_hash": observation_hash,
            "request_reference": acknowledgement.request_reference,
        }
        provisional = cls.model_construct(**values, evidence_hash="0" * 64)
        canonical = json.dumps(
            provisional.evidence_payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(**values, evidence_hash=hashlib.sha256(canonical).hexdigest())

    @classmethod
    def create_from_recovery(
        cls,
        *,
        evidence_id: Uuid7Identifier,
        proposal: ActionProposal,
        run: Run,
        verified_at: datetime,
        observation_hash: Sha256Digest,
    ) -> "VerificationEvidence":
        """Create proof from approved lost-ACK work plus independent stopped read-back."""

        if proposal.run_id != run.run_id:
            raise ValueError("recovery evidence prerequisites do not share one run")
        values: dict[str, object] = {
            "evidence_id": evidence_id,
            "proposal_id": proposal.proposal_id,
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "correlation_id": run.correlation_id,
            "target": proposal.target,
            "verified_at": verified_at,
            "proof_origin": VerificationProofOrigin.RECOVERY_READ_BACK,
            "recovery_observation_hash": observation_hash,
            "observation_hash": observation_hash,
        }
        provisional = cls.model_construct(**values, evidence_hash="0" * 64)
        canonical = json.dumps(
            provisional.evidence_payload(),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return cls(**values, evidence_hash=hashlib.sha256(canonical).hexdigest())


class IdempotencyRecord(NonZeroContract):
    """Semantic duplicate ownership and optional durable action outcome."""

    idempotency_key: IdempotencyKey
    proposal_id: Uuid7Identifier
    action_fingerprint: Sha256Digest
    status: IdempotencyStatus = IdempotencyStatus.REGISTERED
    execution_acknowledgement: ExecutionAcknowledgement | None = None
    action_result: ActionResult | None = None
    registered_at: datetime
    completed_at: datetime | None = None

    @field_validator("registered_at")
    @classmethod
    def validate_registered_at(cls, value: datetime) -> datetime:
        return _require_utc("registered_at", value)

    @field_validator("completed_at")
    @classmethod
    def validate_completed_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _require_utc("completed_at", value)

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status is IdempotencyStatus.REGISTERED:
            if self.action_result is not None or self.completed_at is not None:
                raise ValueError("registered idempotency record cannot contain a result")
        elif self.action_result is None or self.completed_at is None:
            raise ValueError("resolved idempotency record requires result and completed_at")
        elif self.completed_at < self.registered_at:
            raise ValueError("completed_at must not precede registered_at")
        return self


class LocalApprovalRequestRecord(NonZeroContract):
    """Durable, nonce-hash-bound request for one local human decision."""

    request_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    proposal_version: int = Field(gt=0)
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    actor_session_id: ShortIdentifier
    decision_nonce_hash: Sha256Digest
    requested_at: datetime
    expires_at: datetime
    request_hash: Sha256Digest

    @field_validator("requested_at", "expires_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info: object) -> datetime:
        return _require_utc(getattr(info, "field_name", "timestamp"), value)

    @model_validator(mode="after")
    def validate_request_binding(self) -> Self:
        if self.expires_at <= self.requested_at:
            raise ValueError("local approval request must expire after it is created")
        if self.request_hash != _canonical_digest(self.binding_payload()):
            raise ValueError("local approval request hash does not match its binding")
        return self

    def binding_payload(self) -> dict[str, object]:
        return {
            "actor_session_id": self.actor_session_id,
            "correlation_id": str(self.correlation_id),
            "decision_nonce_hash": self.decision_nonce_hash,
            "evidence_hash": self.evidence_hash,
            "expires_at": self.expires_at.isoformat(),
            "operation_type": self.operation_type.value,
            "proposal_hash": self.proposal_hash,
            "proposal_id": str(self.proposal_id),
            "proposal_version": self.proposal_version,
            "request_id": str(self.request_id),
            "run_id": str(self.run_id),
            "target_resource_id": self.target_resource_id,
            "target_resource_type": self.target_resource_type.value,
        }

    @classmethod
    def create(
        cls,
        *,
        request_id: Uuid7Identifier,
        proposal: RemediationProposal,
        actor_session_id: str,
        decision_nonce_hash: Sha256Digest,
        requested_at: datetime,
        expires_at: datetime,
    ) -> "LocalApprovalRequestRecord":
        if proposal.authority_class is not AuthorityGate.PLAN_AND_CONFIRM:
            raise ValueError("only PLAN_AND_CONFIRM proposals may request local approval")
        if proposal.status is not ProposalState.AWAITING_APPROVAL:
            raise ValueError("local approval requires an awaiting proposal")
        if expires_at > proposal.expires_at:
            raise ValueError("approval request cannot outlive its proposal")
        values: dict[str, object] = {
            "request_id": request_id,
            "proposal_id": proposal.proposal_id,
            "run_id": proposal.run_id,
            "correlation_id": proposal.correlation_id,
            "proposal_hash": proposal.proposal_hash,
            "evidence_hash": proposal.evidence_hash,
            "proposal_version": proposal.version,
            "operation_type": proposal.operation_type,
            "target_resource_type": proposal.target_resource_type,
            "target_resource_id": proposal.target_resource_id,
            "actor_session_id": actor_session_id,
            "decision_nonce_hash": decision_nonce_hash,
            "requested_at": requested_at,
            "expires_at": expires_at,
        }
        provisional = cls.model_construct(**values, request_hash="0" * 64)
        return cls(**values, request_hash=_canonical_digest(provisional.binding_payload()))


class LocalApprovalDecisionRecord(NonZeroContract):
    """One immutable human decision bound to the complete local request."""

    request_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    request_hash: Sha256Digest
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    proposal_version: int = Field(gt=0)
    decision: ApprovalDecision
    actor_session_id: ShortIdentifier
    decision_nonce_hash: Sha256Digest
    decided_at: datetime
    decision_hash: Sha256Digest

    @field_validator("decided_at")
    @classmethod
    def validate_decided_at(cls, value: datetime) -> datetime:
        return _require_utc("decided_at", value)

    @model_validator(mode="after")
    def validate_decision_binding(self) -> Self:
        if self.decision_hash != _canonical_digest(self.binding_payload()):
            raise ValueError("local approval decision hash does not match its binding")
        return self

    def binding_payload(self) -> dict[str, object]:
        return {
            "actor_session_id": self.actor_session_id,
            "decided_at": self.decided_at.isoformat(),
            "decision": self.decision.value,
            "decision_nonce_hash": self.decision_nonce_hash,
            "evidence_hash": self.evidence_hash,
            "proposal_hash": self.proposal_hash,
            "proposal_id": str(self.proposal_id),
            "proposal_version": self.proposal_version,
            "request_hash": self.request_hash,
            "request_id": str(self.request_id),
            "run_id": str(self.run_id),
        }

    @classmethod
    def create(
        cls,
        request: LocalApprovalRequestRecord,
        *,
        decision: ApprovalDecision,
        decided_at: datetime,
    ) -> "LocalApprovalDecisionRecord":
        values: dict[str, object] = {
            "request_id": request.request_id,
            "proposal_id": request.proposal_id,
            "run_id": request.run_id,
            "request_hash": request.request_hash,
            "proposal_hash": request.proposal_hash,
            "evidence_hash": request.evidence_hash,
            "proposal_version": request.proposal_version,
            "decision": decision,
            "actor_session_id": request.actor_session_id,
            "decision_nonce_hash": request.decision_nonce_hash,
            "decided_at": decided_at,
        }
        provisional = cls.model_construct(**values, decision_hash="0" * 64)
        return cls(**values, decision_hash=_canonical_digest(provisional.binding_payload()))


class LocalExecutionIntent(NonZeroContract):
    """Write-before-execute ownership for one approved local mock mutation."""

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    decision_hash: Sha256Digest
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    idempotency_key: IdempotencyKey
    registered_at: datetime
    intent_hash: Sha256Digest

    @field_validator("registered_at")
    @classmethod
    def validate_registered_at(cls, value: datetime) -> datetime:
        return _require_utc("registered_at", value)

    @model_validator(mode="after")
    def validate_intent_binding(self) -> Self:
        if self.operation_type is RemediationOperation.APPLY_REQUIRED_TAGS:
            raise ValueError("NEVER_AUTONOMOUS tag proposals cannot form execution intent")
        if self.intent_hash != _canonical_digest(self.binding_payload()):
            raise ValueError("local execution intent hash does not match its binding")
        return self

    def binding_payload(self) -> dict[str, object]:
        return {
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "idempotency_key": self.idempotency_key,
            "operation_type": self.operation_type.value,
            "proposal_hash": self.proposal_hash,
            "proposal_id": str(self.proposal_id),
            "registered_at": self.registered_at.isoformat(),
            "run_id": str(self.run_id),
            "target_resource_id": self.target_resource_id,
            "target_resource_type": self.target_resource_type.value,
        }

    @classmethod
    def create(
        cls,
        proposal: RemediationProposal,
        approval: LocalApprovalDecisionRecord,
        *,
        registered_at: datetime,
    ) -> "LocalExecutionIntent":
        if approval.decision is not ApprovalDecision.APPROVED:
            raise ValueError("local execution intent requires approval")
        if (
            approval.proposal_id != proposal.proposal_id
            or approval.run_id != proposal.run_id
            or approval.proposal_hash != proposal.proposal_hash
            or approval.evidence_hash != proposal.evidence_hash
            or approval.proposal_version != proposal.version
        ):
            raise ValueError("local execution intent prerequisites do not match")
        values: dict[str, object] = {
            "run_id": proposal.run_id,
            "proposal_id": proposal.proposal_id,
            "proposal_hash": proposal.proposal_hash,
            "evidence_hash": proposal.evidence_hash,
            "decision_hash": approval.decision_hash,
            "operation_type": proposal.operation_type,
            "target_resource_type": proposal.target_resource_type,
            "target_resource_id": proposal.target_resource_id,
            "idempotency_key": f"local-exec:{proposal.proposal_hash}",
            "registered_at": registered_at,
        }
        provisional = cls.model_construct(**values, intent_hash="0" * 64)
        return cls(**values, intent_hash=_canonical_digest(provisional.binding_payload()))


class LocalExecutionReceipt(NonZeroContract):
    """Atomic mock-provider mutation receipt; a receipt is not final verification."""

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    proposal_hash: Sha256Digest
    evidence_hash: Sha256Digest
    decision_hash: Sha256Digest
    intent_hash: Sha256Digest
    idempotency_key: IdempotencyKey
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    before_resource: CloudResource
    after_resource: CloudResource | None = None
    executed_at: datetime
    receipt_hash: Sha256Digest

    @field_validator("executed_at")
    @classmethod
    def validate_executed_at(cls, value: datetime) -> datetime:
        return _require_utc("executed_at", value)

    @model_validator(mode="after")
    def validate_receipt_binding(self) -> Self:
        if (
            self.before_resource.resource_type is not self.target_resource_type
            or self.before_resource.resource_id != self.target_resource_id
        ):
            raise ValueError("local receipt before-resource target does not match")
        if self.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
            if not isinstance(self.before_resource, ElasticIpResource):
                raise ValueError("release receipt requires Elastic IP state")
            if self.before_resource.association_id is not None or self.after_resource is not None:
                raise ValueError("release receipt must prove an unattached address became absent")
        elif self.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
            if not isinstance(self.before_resource, SecurityGroupResource) or not isinstance(
                self.after_resource, SecurityGroupResource
            ):
                raise ValueError("ingress receipt requires Security Group before/after state")
            if (
                self.after_resource.resource_id != self.before_resource.resource_id
                or self.after_resource.region != self.before_resource.region
                or self.after_resource.vpc_id != self.before_resource.vpc_id
                or self.after_resource.outbound_rules != self.before_resource.outbound_rules
                or self.after_resource.tags != self.before_resource.tags
                or len(self.after_resource.inbound_rules) >= len(self.before_resource.inbound_rules)
            ):
                raise ValueError("ingress receipt does not prove a bounded rule removal")
            remaining_before = iter(self.before_resource.inbound_rules)
            for expected_rule in self.after_resource.inbound_rules:
                if not any(rule == expected_rule for rule in remaining_before):
                    raise ValueError(
                        "ingress receipt after-state is not an ordered subset"
                    )
        else:
            raise ValueError("local receipt operation is non-executable")
        if self.receipt_hash != _canonical_digest(self.receipt_payload()):
            raise ValueError("local execution receipt hash does not match its payload")
        return self

    def receipt_payload(self) -> dict[str, object]:
        return {
            "after_resource": (
                None if self.after_resource is None else self.after_resource.model_dump(mode="json")
            ),
            "before_resource": self.before_resource.model_dump(mode="json"),
            "decision_hash": self.decision_hash,
            "evidence_hash": self.evidence_hash,
            "executed_at": self.executed_at.isoformat(),
            "idempotency_key": self.idempotency_key,
            "intent_hash": self.intent_hash,
            "operation_type": self.operation_type.value,
            "proposal_hash": self.proposal_hash,
            "proposal_id": str(self.proposal_id),
            "run_id": str(self.run_id),
            "target_resource_id": self.target_resource_id,
            "target_resource_type": self.target_resource_type.value,
        }


class LocalVerificationEvidence(NonZeroContract):
    """Independent read-back proof for a completed local mock mutation."""

    run_id: Uuid7Identifier
    proposal_id: Uuid7Identifier
    receipt_hash: Sha256Digest
    operation_type: RemediationOperation
    target_resource_type: CloudResourceType
    target_resource_id: ShortIdentifier
    observed_absent: bool
    observed_resource: CloudResource | None = None
    verified_at: datetime
    verification_hash: Sha256Digest

    @field_validator("verified_at")
    @classmethod
    def validate_verified_at(cls, value: datetime) -> datetime:
        return _require_utc("verified_at", value)

    @model_validator(mode="after")
    def validate_verification_binding(self) -> Self:
        if self.operation_type is RemediationOperation.RELEASE_ELASTIC_IP:
            if not self.observed_absent or self.observed_resource is not None:
                raise ValueError("release verification requires exact target absence")
        elif self.operation_type is RemediationOperation.REVOKE_PUBLIC_INGRESS:
            if self.observed_absent or not isinstance(
                self.observed_resource, SecurityGroupResource
            ):
                raise ValueError("ingress verification requires Security Group read-back")
            if (
                self.observed_resource.resource_id != self.target_resource_id
                or self.observed_resource.resource_type is not self.target_resource_type
            ):
                raise ValueError("local verification observed a different target")
        else:
            raise ValueError("local verification operation is non-executable")
        if self.verification_hash != _canonical_digest(self.verification_payload()):
            raise ValueError("local verification hash does not match its payload")
        return self

    def verification_payload(self) -> dict[str, object]:
        return {
            "observed_absent": self.observed_absent,
            "observed_resource": (
                None
                if self.observed_resource is None
                else self.observed_resource.model_dump(mode="json")
            ),
            "operation_type": self.operation_type.value,
            "proposal_id": str(self.proposal_id),
            "receipt_hash": self.receipt_hash,
            "run_id": str(self.run_id),
            "target_resource_id": self.target_resource_id,
            "target_resource_type": self.target_resource_type.value,
            "verified_at": self.verified_at.isoformat(),
        }


class Checkpoint(NonZeroContract):
    """Versioned last-safe-state foundation for later restart reconciliation."""

    run_id: Uuid7Identifier
    last_safe_state: WorkflowState
    resume_metadata: dict[str, JsonValue] = Field(default_factory=dict)
    tool_result_hashes: dict[ShortIdentifier, Sha256Digest] = Field(default_factory=dict)
    resource_evidence: ResourceEvidence | None = None
    remediation_proposal: RemediationProposal | None = None
    local_approval_request: LocalApprovalRequestRecord | None = None
    local_approval: LocalApprovalDecisionRecord | None = None
    local_execution_intent: LocalExecutionIntent | None = None
    local_execution_receipt: LocalExecutionReceipt | None = None
    local_verification: LocalVerificationEvidence | None = None
    created_at: datetime
    version: int = Field(default=1, gt=0)

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _require_utc("created_at", value)

    @model_validator(mode="after")
    def validate_last_safe_state(self) -> Self:
        if self.last_safe_state in {WorkflowState.EXECUTING, WorkflowState.VERIFYING}:
            raise ValueError("checkpoint cannot label an active side-effect state as safe")
        if self.remediation_proposal is not None and self.resource_evidence is None:
            raise ValueError("local proposal checkpoint requires resource evidence")
        if self.remediation_proposal is not None and (
            self.remediation_proposal.run_id != self.run_id
            or self.resource_evidence is None
            or self.resource_evidence.run_id != self.run_id
            or self.remediation_proposal.correlation_id
            != self.resource_evidence.correlation_id
            or self.remediation_proposal.evidence_hash != self.resource_evidence.evidence_hash
        ):
            raise ValueError("checkpoint evidence and proposal identities must match")
        proposal = self.remediation_proposal
        request = self.local_approval_request
        approval = self.local_approval
        intent = self.local_execution_intent
        receipt = self.local_execution_receipt
        verification = self.local_verification
        if request is not None and (
            proposal is None
            or request.run_id != self.run_id
            or request.correlation_id != proposal.correlation_id
            or request.proposal_id != proposal.proposal_id
            or request.proposal_hash != proposal.proposal_hash
            or request.evidence_hash != proposal.evidence_hash
            or request.proposal_version != proposal.version
            or request.operation_type is not proposal.operation_type
            or request.target_resource_type is not proposal.target_resource_type
            or request.target_resource_id != proposal.target_resource_id
        ):
            raise ValueError("checkpoint local approval request is not proposal-bound")
        if approval is not None and (
            request is None
            or approval.run_id != self.run_id
            or approval.request_id != request.request_id
            or approval.request_hash != request.request_hash
            or approval.proposal_id != request.proposal_id
            or approval.proposal_hash != request.proposal_hash
            or approval.evidence_hash != request.evidence_hash
            or approval.proposal_version != request.proposal_version
            or approval.actor_session_id != request.actor_session_id
            or approval.decision_nonce_hash != request.decision_nonce_hash
            or approval.decided_at < request.requested_at
            or approval.decided_at > request.expires_at
        ):
            raise ValueError("checkpoint local approval is not request-bound")
        if intent is not None and (
            proposal is None
            or approval is None
            or approval.decision is not ApprovalDecision.APPROVED
            or intent.run_id != self.run_id
            or intent.proposal_id != proposal.proposal_id
            or intent.proposal_hash != proposal.proposal_hash
            or intent.evidence_hash != proposal.evidence_hash
            or intent.decision_hash != approval.decision_hash
            or intent.operation_type is not proposal.operation_type
            or intent.target_resource_type is not proposal.target_resource_type
            or intent.target_resource_id != proposal.target_resource_id
            or intent.idempotency_key != f"local-exec:{proposal.proposal_hash}"
            or intent.registered_at < approval.decided_at
            or intent.registered_at > proposal.expires_at
        ):
            raise ValueError("checkpoint local execution intent is not approval-bound")
        if receipt is not None and (
            intent is None
            or receipt.run_id != self.run_id
            or receipt.proposal_id != intent.proposal_id
            or receipt.proposal_hash != intent.proposal_hash
            or receipt.evidence_hash != intent.evidence_hash
            or receipt.decision_hash != intent.decision_hash
            or receipt.intent_hash != intent.intent_hash
            or receipt.idempotency_key != intent.idempotency_key
            or receipt.operation_type is not intent.operation_type
            or receipt.target_resource_type is not intent.target_resource_type
            or receipt.target_resource_id != intent.target_resource_id
            or receipt.executed_at < intent.registered_at
        ):
            raise ValueError("checkpoint local receipt is not intent-bound")
        if verification is not None and (
            receipt is None
            or verification.run_id != self.run_id
            or verification.proposal_id != receipt.proposal_id
            or verification.receipt_hash != receipt.receipt_hash
            or verification.operation_type is not receipt.operation_type
            or verification.target_resource_type is not receipt.target_resource_type
            or verification.target_resource_id != receipt.target_resource_id
            or verification.observed_resource != receipt.after_resource
            or verification.verified_at < receipt.executed_at
        ):
            raise ValueError("checkpoint local verification is not receipt-bound")
        return self


class AuditEvent(NonZeroContract):
    """Append-oriented provenance event with redacted payload evidence."""

    event_id: Uuid7Identifier
    run_id: Uuid7Identifier
    type: AuditEventType
    timestamp: datetime
    source: ShortIdentifier
    tool_name: ShortIdentifier | None = None
    model_id: NonEmptyText | None = None
    redacted_payload_hash: Sha256Digest
    metadata: dict[ShortIdentifier, NonEmptyText] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _require_utc("timestamp", value)

    @model_validator(mode="after")
    def prohibit_sensitive_metadata(self) -> Self:
        sensitive_terms = ("credential", "password", "secret", "token")
        if any(any(term in key.casefold() for term in sensitive_terms) for key in self.metadata):
            raise ValueError("sensitive audit metadata keys are prohibited")
        if contains_sensitive_material(self.metadata):
            raise ValueError("sensitive audit metadata values are prohibited")
        return self
