"""Central exact-name, exact-schema, default-deny tool dispatch policy."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from aioa_cloudops_agent.cloudops.models import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.domain.identifiers import validate_correlation_id
from aioa_cloudops_agent.nz import (
    ActionProposal,
    Approval,
    ApprovalDecision,
    Capability,
    FailureDetail,
    FailureKind,
    ProposalState,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.persistence import DurableTruthRepository


class PolicyDisposition(StrEnum):
    """Whether a pre-dispatch request may proceed, interrupt, or must stop."""

    ALLOW = "ALLOW"
    REQUIRE_CONFIRMATION = "REQUIRE_CONFIRMATION"
    DENY = "DENY"


class PolicyDecision(BaseModel):
    """Typed pre-dispatch result independent of model prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: PolicyDisposition
    capability: Capability | None = None
    authority: AuthorityGate | None = None
    terminal_state: WorkflowState | None = None
    failure: FailureDetail | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.disposition is PolicyDisposition.DENY:
            if self.failure is None or self.terminal_state is None:
                raise ValueError("denied policy decision requires typed failure and state")
        elif self.failure is not None or self.terminal_state is not None:
            raise ValueError("allowed policy decision cannot contain a failure state")
        return self


_TOOL_CAPABILITY: dict[str, Capability] = {
    Capability.INSPECT_INSTANCE.value: Capability.INSPECT_INSTANCE,
    Capability.READ_UTILIZATION_METRICS.value: Capability.READ_UTILIZATION_METRICS,
    Capability.BUILD_REMEDIATION_EVIDENCE.value: Capability.BUILD_REMEDIATION_EVIDENCE,
    Capability.STOP_SANDBOX_INSTANCE.value: Capability.STOP_SANDBOX_INSTANCE,
    Capability.VERIFY_INSTANCE_STATE.value: Capability.VERIFY_INSTANCE_STATE,
}
_STRUCTURALLY_DENIED_TOOL: dict[str, Capability] = {
    "CreateTags": Capability.CREATE_TAGS,
    "DeleteTags": Capability.DELETE_TAGS,
    "ModifyInstanceAttribute": Capability.MODIFY_INSTANCE_ATTRIBUTE,
    "RebootInstances": Capability.REBOOT_INSTANCES,
    "SendCommand": Capability.SSM_COMMAND_EXECUTION,
    "StartInstances": Capability.START_INSTANCES,
    "TerminateInstances": Capability.TERMINATE_INSTANCES,
    "create_tags": Capability.CREATE_TAGS,
    "credentials": Capability.CREDENTIAL_ACCESS,
    "delete_tags": Capability.DELETE_TAGS,
    "fetch_url": Capability.ARBITRARY_URL_FETCH,
    "filesystem": Capability.FILESYSTEM_ACCESS,
    "iam_mutation": Capability.IAM_MUTATION,
    "modify_instance_attribute": Capability.MODIFY_INSTANCE_ATTRIBUTE,
    "python": Capability.ARBITRARY_CODE_EXECUTION,
    "reboot_instances": Capability.REBOOT_INSTANCES,
    "shell": Capability.SHELL_EXECUTION,
    "ssm_send_command": Capability.SSM_COMMAND_EXECUTION,
    "start_instances": Capability.START_INSTANCES,
    "terminate_instances": Capability.TERMINATE_INSTANCES,
}
_INSTANCE_TOOLS = frozenset(
    {
        Capability.INSPECT_INSTANCE,
        Capability.READ_UTILIZATION_METRICS,
        Capability.BUILD_REMEDIATION_EVIDENCE,
    }
)


@dataclass(frozen=True, slots=True)
class _DurableContext:
    proposal: ActionProposal
    run: Run
    approval: Approval | None


class DefaultDenyToolPolicy:
    """Authorize only the frozen five-tool surface and its exact durable context."""

    def __init__(
        self,
        *,
        identity: InvestigationIdentity,
        target: SandboxTarget,
        repository: DurableTruthRepository | None,
    ) -> None:
        if not isinstance(identity, InvestigationIdentity):
            raise TypeError("identity must be InvestigationIdentity")
        if not isinstance(target, SandboxTarget):
            raise TypeError("target must be SandboxTarget")
        self._identity = identity
        self._target = target
        self._repository = repository

    @property
    def identity(self) -> InvestigationIdentity:
        return self._identity

    def evaluate(self, tool_name: object, tool_input: object) -> PolicyDecision:
        """Evaluate typed identifiers only; prompt text is never inspected as authority."""

        capability = _TOOL_CAPABILITY.get(tool_name) if isinstance(tool_name, str) else None
        if capability is None:
            denied_capability = (
                _STRUCTURALLY_DENIED_TOOL.get(tool_name)
                if isinstance(tool_name, str)
                else None
            )
            return self._deny(
                denied_capability,
                FailureKind.POLICY_DENIAL,
                (
                    "NEVER_AUTONOMOUS_DENIED"
                    if denied_capability is not None
                    else "UNKNOWN_TOOL_DENIED"
                ),
                (
                    "NEVER_AUTONOMOUS capability is structurally denied before dispatch"
                    if denied_capability is not None
                    else "Unknown tool or capability is denied before dispatch"
                ),
            )
        if not isinstance(tool_input, dict):
            return self._schema_denial(capability, "Tool input must be an exact object")
        expected_key = "instance_id" if capability in _INSTANCE_TOOLS else "proposal_id"
        if set(tool_input) != {expected_key}:
            if expected_key not in tool_input:
                return self._schema_denial(capability, "Required tool identifier is missing")
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "PRIVILEGED_FIELD_DENIED",
                "Extra or confused tool fields are denied before dispatch",
            )
        if capability in _INSTANCE_TOOLS:
            return self._evaluate_instance_read(capability, tool_input[expected_key])
        proposal_id = self._proposal_identifier(capability, tool_input[expected_key])
        if isinstance(proposal_id, PolicyDecision):
            return proposal_id
        if capability is Capability.STOP_SANDBOX_INSTANCE:
            return self._evaluate_stop(proposal_id)
        return self._evaluate_verification(proposal_id)

    def _evaluate_instance_read(
        self,
        capability: Capability,
        instance_id: object,
    ) -> PolicyDecision:
        if not isinstance(instance_id, str):
            return self._schema_denial(capability, "instance_id must be a string")
        if instance_id != self._target.instance_id:
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "SANDBOX_SCOPE_DENIED",
                "Read target is outside the configured sandbox scope",
            )
        return PolicyDecision(
            disposition=PolicyDisposition.ALLOW,
            capability=capability,
            authority=AuthorityGate.AUTO,
        )

    def _proposal_identifier(
        self,
        capability: Capability,
        value: object,
    ) -> UUID | PolicyDecision:
        try:
            return validate_correlation_id(value)
        except Exception:
            return self._schema_denial(capability, "proposal_id must be an RFC UUIDv7")

    def _durable_context(
        self,
        capability: Capability,
        proposal_id: UUID,
    ) -> _DurableContext | PolicyDecision:
        if self._repository is None:
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "DURABLE_AUTHORITY_ABSENT",
                "Durable proposal authority is unavailable",
            )
        try:
            proposal = self._repository.get_proposal(proposal_id)
            run = self._repository.get_run(self._identity.run_id)
            approval = self._repository.get_approval(proposal_id)
        except Exception:
            return self._deny(
                capability,
                FailureKind.DEPENDENCY_UNAVAILABLE,
                "DURABLE_POLICY_UNAVAILABLE",
                "Durable policy prerequisites are unavailable",
            )
        if proposal is None or run is None:
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "DURABLE_REFERENCE_DENIED",
                "Tool request lacks a matching durable run and proposal",
            )
        if (
            proposal.run_id != self._identity.run_id
            or run.run_id != self._identity.run_id
            or run.trace_id != self._identity.trace_id
            or run.correlation_id != self._identity.correlation_id
            or proposal.action is not Capability.STOP_SANDBOX_INSTANCE
            or proposal.target.resource_id != self._target.instance_id
            or proposal.target.region != self._target.region
            or proposal.target.required_tag_key != self._target.required_tag_key
            or proposal.target.required_tag_value != self._target.required_tag_value
            or proposal.authority is not AuthorityGate.PLAN_AND_CONFIRM
            or proposal.evidence_hash != proposal.expected_precondition.evidence_hash
        ):
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "CROSS_CONTEXT_DENIED",
                "Durable proposal does not match this run, action, evidence, or sandbox",
            )
        if approval is not None and (
            approval.proposal_id != proposal.proposal_id
            or approval.run_id != proposal.run_id
            or approval.action is not proposal.action
            or approval.target != proposal.target
            or approval.evidence_hash != proposal.evidence_hash
        ):
            return self._deny(
                capability,
                FailureKind.POLICY_DENIAL,
                "APPROVAL_BINDING_DENIED",
                "Durable approval binding is stale or belongs to another context",
            )
        return _DurableContext(proposal=proposal, run=run, approval=approval)

    def _evaluate_stop(self, proposal_id: UUID) -> PolicyDecision:
        context = self._durable_context(Capability.STOP_SANDBOX_INSTANCE, proposal_id)
        if isinstance(context, PolicyDecision):
            return context
        proposal = context.proposal
        run = context.run
        approval = context.approval
        if (
            proposal.state is ProposalState.AWAITING_APPROVAL
            and run.state is WorkflowState.AWAITING_APPROVAL
            and approval is None
        ):
            return PolicyDecision(
                disposition=PolicyDisposition.REQUIRE_CONFIRMATION,
                capability=Capability.STOP_SANDBOX_INSTANCE,
                authority=AuthorityGate.PLAN_AND_CONFIRM,
            )
        if (
            proposal.state is ProposalState.AWAITING_APPROVAL
            and run.state is WorkflowState.APPROVED
            and approval is not None
            and approval.decision is ApprovalDecision.APPROVED
        ):
            return PolicyDecision(
                disposition=PolicyDisposition.ALLOW,
                capability=Capability.STOP_SANDBOX_INSTANCE,
                authority=AuthorityGate.PLAN_AND_CONFIRM,
            )
        return self._deny(
            Capability.STOP_SANDBOX_INSTANCE,
            FailureKind.POLICY_DENIAL,
            "STOP_PREREQUISITES_DENIED",
            "Stop requires the exact awaiting confirmation or durable approved context",
        )

    def _evaluate_verification(self, proposal_id: UUID) -> PolicyDecision:
        context = self._durable_context(Capability.VERIFY_INSTANCE_STATE, proposal_id)
        if isinstance(context, PolicyDecision):
            return context
        run = context.run
        approval = context.approval
        if (
            run.state
            not in {
                WorkflowState.VERIFYING,
                WorkflowState.RECOVERY_REQUIRED,
                WorkflowState.SUCCESS_WITH_EVIDENCE,
            }
            or approval is None
            or approval.decision is not ApprovalDecision.APPROVED
        ):
            return self._deny(
                Capability.VERIFY_INSTANCE_STATE,
                FailureKind.POLICY_DENIAL,
                "VERIFICATION_CONTEXT_DENIED",
                "Verification requires the approved durable target in a verification state",
            )
        return PolicyDecision(
            disposition=PolicyDisposition.ALLOW,
            capability=Capability.VERIFY_INSTANCE_STATE,
            authority=AuthorityGate.AUTO,
        )

    @staticmethod
    def _schema_denial(capability: Capability, message: str) -> PolicyDecision:
        return DefaultDenyToolPolicy._deny(
            capability,
            FailureKind.VALIDATION_FAILURE,
            "TOOL_SCHEMA_INVALID",
            message,
        )

    @staticmethod
    def _deny(
        capability: Capability | None,
        kind: FailureKind,
        code: str,
        message: str,
    ) -> PolicyDecision:
        state = {
            FailureKind.POLICY_DENIAL: WorkflowState.DENIED_BY_POLICY,
            FailureKind.VALIDATION_FAILURE: WorkflowState.MODEL_OUTPUT_INVALID,
            FailureKind.DEPENDENCY_UNAVAILABLE: WorkflowState.DEPENDENCY_UNAVAILABLE,
        }[kind]
        return PolicyDecision(
            disposition=PolicyDisposition.DENY,
            capability=capability,
            authority=(
                AuthorityGate.AUTO
                if capability in {*_INSTANCE_TOOLS, Capability.VERIFY_INSTANCE_STATE}
                else AuthorityGate.PLAN_AND_CONFIRM
                if capability is Capability.STOP_SANDBOX_INSTANCE
                else AuthorityGate.NEVER_AUTONOMOUS
            ),
            terminal_state=state,
            failure=FailureDetail(
                kind=kind,
                code=code,
                message=message,
                retryable=kind is FailureKind.DEPENDENCY_UNAVAILABLE,
            ),
        )
