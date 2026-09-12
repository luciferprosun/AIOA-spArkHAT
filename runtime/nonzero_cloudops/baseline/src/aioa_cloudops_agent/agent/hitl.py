"""Native Strands HITL protected by exact default-deny pre-dispatch policy."""

import hashlib
import json
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from strands.hooks.events import BeforeToolCallEvent
from strands.interventions import Confirm, Deny, InterventionAction
from strands.vended_interventions.hitl import HumanInTheLoop

from aioa_cloudops_agent.cloudops import InvestigationIdentity, SandboxTarget
from aioa_cloudops_agent.nz import (
    ActionProposal,
    ActionTarget,
    ApprovalDecision,
    AuditEvent,
    AuditEventType,
    AuthorityGate,
    Capability,
    ExpectedPrecondition,
    NonEmptyText,
    ProposalState,
    Sha256Digest,
    ShortIdentifier,
    Uuid7Identifier,
)
from aioa_cloudops_agent.nz.errors import FailureDetail, FailureKind
from aioa_cloudops_agent.persistence import DurableTruthRepository, compute_evidence_digest
from aioa_cloudops_agent.remediation import STOP_SANDBOX_INSTANCE_TOOL_NAME
from aioa_cloudops_agent.safety import (
    DefaultDenyToolPolicy,
    PolicyDecision,
    PolicyDisposition,
    SchemaCorrectionBudget,
)

STOP_IMPACT_SUMMARY: Literal[
    "Gracefully stopping the sandbox instance is reversible but changes AWS workload state."
] = "Gracefully stopping the sandbox instance is reversible but changes AWS workload state."


class ApprovalPayload(BaseModel):
    """Human-visible mutation facts copied from one immutable durable proposal."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    action: Capability
    target: ActionTarget
    expected_precondition: ExpectedPrecondition
    authority: Literal[AuthorityGate.PLAN_AND_CONFIRM] = AuthorityGate.PLAN_AND_CONFIRM
    evidence_hash: Sha256Digest
    impact_summary: Literal[
        "Gracefully stopping the sandbox instance is reversible but changes AWS workload state."
    ] = STOP_IMPACT_SUMMARY

    @model_validator(mode="after")
    def validate_stop_payload(self) -> Self:
        if self.action is not Capability.STOP_SANDBOX_INSTANCE:
            raise ValueError("approval payload must describe the canonical sandbox stop")
        if self.evidence_hash != self.expected_precondition.evidence_hash:
            raise ValueError("approval payload evidence binding is inconsistent")
        return self


class ApprovalInterrupt(BaseModel):
    """Serializable caller boundary returned when native Strands execution pauses."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interrupt_id: NonEmptyText
    payload: ApprovalPayload
    request_hash: Sha256Digest
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    reconciled: bool = False


class ApprovalResumeRequest(BaseModel):
    """Typed external response that must echo the exact durable approval binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interrupt_id: NonEmptyText
    proposal_id: Uuid7Identifier
    run_id: Uuid7Identifier
    action: Capability
    target: ActionTarget
    evidence_hash: Sha256Digest
    request_hash: Sha256Digest
    decision: ApprovalDecision
    actor_session_id: ShortIdentifier
    decision_nonce: NonEmptyText = Field(min_length=16, max_length=256)


def build_approval_payload(proposal: ActionProposal) -> ApprovalPayload:
    """Build the human payload from the durable proposal, never model prose."""

    if not isinstance(proposal, ActionProposal):
        raise TypeError("proposal must be an ActionProposal")
    return ApprovalPayload(
        proposal_id=proposal.proposal_id,
        run_id=proposal.run_id,
        action=proposal.action,
        target=proposal.target,
        expected_precondition=proposal.expected_precondition,
        authority=proposal.authority,
        evidence_hash=proposal.evidence_hash,
    )


def approval_request_hash(payload: ApprovalPayload) -> str:
    """Hash the exact human-visible facts for tamper and replay detection."""

    if not isinstance(payload, ApprovalPayload):
        raise TypeError("payload must be an ApprovalPayload")
    return compute_evidence_digest(payload.model_dump(mode="json"))


class DurableProposalHumanInTheLoop(HumanInTheLoop):
    """Deny unsafe dispatch and derive native confirmation only from durable truth."""

    def __init__(
        self,
        repository: DurableTruthRepository | None,
        *,
        allowed_tools: list[str],
        identity: InvestigationIdentity,
        target: SandboxTarget,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID],
        model_id: str,
        schema_correction_attempts: int = 2,
    ) -> None:
        self._repository = repository
        self._policy = DefaultDenyToolPolicy(
            identity=identity,
            target=target,
            repository=repository,
        )
        self._clock = clock
        self._event_id_factory = event_id_factory
        self._model_id = model_id
        self._schema_budget = SchemaCorrectionBudget(max_attempts=schema_correction_attempts)
        self._last_failure: FailureDetail | None = None
        self._denial_count = 0
        super().__init__(
            allowed_tools=allowed_tools,
            classifier=None,
            enable_trust=False,
            ask=None,
        )

    @property
    def policy(self) -> DefaultDenyToolPolicy:
        """Expose the deterministic evaluator for tests and control-plane inspection."""

        return self._policy

    @property
    def last_failure(self) -> FailureDetail | None:
        """Return the latest uncorrected pre-dispatch failure for durable flow closure."""

        return self._last_failure

    @property
    def denial_count(self) -> int:
        return self._denial_count

    async def before_tool_call(
        self,
        event: BeforeToolCallEvent,
        **kwargs: object,
    ) -> InterventionAction:
        tool_input = event.tool_use.get("input")
        decision = self._policy.evaluate(event.tool_use.get("name"), tool_input)
        if decision.disposition is PolicyDisposition.DENY:
            assert decision.failure is not None
            failure = decision.failure
            if failure.kind is FailureKind.VALIDATION_FAILURE:
                failure = self._schema_budget.reject()
            self._last_failure = failure
            self._denial_count += 1
            self._append_denial_audit(event, decision, failure)
            return Deny(reason=self._safe_denial_reason(failure))
        if (
            self._last_failure is not None
            and self._last_failure.kind is not FailureKind.VALIDATION_FAILURE
        ):
            self._denial_count += 1
            self._append_denial_audit(event, decision, self._last_failure)
            return Deny(reason=self._safe_denial_reason(self._last_failure))
        if self._schema_budget.exhausted:
            failure = self._last_failure or self._schema_budget.reject()
            self._last_failure = failure
            self._denial_count += 1
            self._append_denial_audit(event, decision, failure)
            return Deny(reason=self._safe_denial_reason(failure))
        if (
            self._last_failure is not None
            and self._last_failure.kind is FailureKind.VALIDATION_FAILURE
        ):
            self._last_failure = None

        action = await super().before_tool_call(event, **kwargs)
        if event.tool_use["name"] != STOP_SANDBOX_INSTANCE_TOOL_NAME:
            return action
        if not isinstance(action, Confirm):
            return action
        if not isinstance(tool_input, dict) or set(tool_input) != {"proposal_id"}:
            return Deny(reason="Mutation request must contain only one durable proposal reference.")
        try:
            if self._repository is None:
                raise ValueError("durable truth is unavailable")
            proposal_id = UUID(str(tool_input["proposal_id"]))
            proposal = self._repository.get_proposal(proposal_id)
            if proposal is None or proposal.state is not ProposalState.AWAITING_APPROVAL:
                raise ValueError("proposal is not durably awaiting approval")
            payload = build_approval_payload(proposal)
            payload_json = json.dumps(
                payload.model_dump(mode="json"),
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except Exception:
            return Deny(reason="Durable approval payload could not be proven.")
        return Confirm(
            prompt=f"Approve proposal-bound sandbox STOP?\n  Payload: {payload_json}",
            reason=action.reason,
            response=action.response,
            evaluate=action.evaluate,
        )

    @staticmethod
    def _safe_denial_reason(failure: FailureDetail) -> str:
        if failure.kind is FailureKind.VALIDATION_FAILURE and failure.retryable:
            return "Tool schema rejected; one bounded exact-schema correction may be attempted."
        if failure.kind is FailureKind.VALIDATION_FAILURE:
            return "Tool schema rejected; the bounded correction budget is exhausted."
        return "Deterministic Non-Zero policy denied this tool request before dispatch."

    @staticmethod
    def _redacted_request_hash(event: BeforeToolCallEvent) -> str:
        try:
            canonical = json.dumps(
                {
                    "input": event.tool_use.get("input"),
                    "name": event.tool_use.get("name"),
                },
                allow_nan=False,
                default=lambda _: "<unsupported>",
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        except (TypeError, ValueError):
            canonical = b'{"request":"unserializable"}'
        return hashlib.sha256(canonical).hexdigest()

    def _append_denial_audit(
        self,
        event: BeforeToolCallEvent,
        decision: PolicyDecision,
        failure: FailureDetail,
    ) -> None:
        if self._repository is None:
            return
        try:
            run = self._repository.get_run(self._policy.identity.run_id)
            if run is None:
                return
            safe_tool_name = (
                decision.capability.value if decision.capability is not None else "policy-denied"
            )
            metadata = {
                "correlation_id": str(run.correlation_id),
                "failure_kind": failure.kind.value,
                "policy_code": failure.code,
                "trace_id": str(run.trace_id),
            }
            tool_input = event.tool_use.get("input")
            if isinstance(tool_input, dict) and set(tool_input) == {"proposal_id"}:
                with suppress(TypeError, ValueError, AttributeError):
                    metadata["proposal_id"] = str(UUID(str(tool_input["proposal_id"])))
            self._repository.append_audit_event(
                AuditEvent(
                    event_id=self._event_id_factory(),
                    run_id=run.run_id,
                    type=(
                        AuditEventType.MODEL_OUTPUT_REJECTED
                        if failure.kind is FailureKind.VALIDATION_FAILURE
                        else AuditEventType.POLICY_DENIED
                    ),
                    timestamp=self._clock(),
                    source="nz-safety-policy",
                    tool_name=safe_tool_name,
                    model_id=self._model_id,
                    redacted_payload_hash=self._redacted_request_hash(event),
                    metadata=metadata,
                )
            )
        except Exception:
            # Denial remains fail-closed even if its append-only proof is unavailable.
            return
