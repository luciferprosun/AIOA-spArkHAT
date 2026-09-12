"""Bounded Strands investigation ending at a durable non-authorizing proposal."""

from collections.abc import Callable
from datetime import datetime
from math import ceil, isfinite
from time import monotonic as monotonic_clock
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from strands.types.agent import Limits

from aioa_cloudops_agent.cloudops import (
    EvidenceBuildOutcome,
    EvidenceDecision,
    RemediationEvidenceBundle,
)
from aioa_cloudops_agent.domain import AuthorityGate
from aioa_cloudops_agent.nz import (
    ActionProposal,
    AuditEvent,
    AuditEventType,
    BudgetCounters,
    Capability,
    Checkpoint,
    ControlResult,
    FailureDetail,
    FailureKind,
    ProposalState,
    Run,
    WorkflowState,
)
from aioa_cloudops_agent.nz.errors import StorageConflictError, StorageDependencyError
from aioa_cloudops_agent.nz.identifiers import Uuid7Identifier
from aioa_cloudops_agent.persistence import DurableTruthRepository, compute_evidence_digest
from aioa_cloudops_agent.safety import workflow_state_for_failure

from .factory import INVESTIGATION_TOOL_NAMES, PrimaryAgentRuntime
from .runtime import build_investigation_request


class InvestigationCompletion(BaseModel):
    """Evidence-backed package result that explicitly carries no execution authority."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    proposal: ActionProposal
    evidence: RemediationEvidenceBundle | None
    final_state: Literal[WorkflowState.REMEDIATION_PROPOSED]
    agent_summary: str = Field(min_length=1, max_length=1_024)
    reconciled: bool = False

    @model_validator(mode="after")
    def validate_completion(self) -> Self:
        if self.proposal.run_id != self.run_id:
            raise ValueError("completion proposal belongs to another run")
        if self.proposal.authorizes_execution:
            raise ValueError("investigation completion cannot authorize execution")
        if not self.reconciled and self.evidence is None:
            raise ValueError("new completion requires its typed evidence bundle")
        if self.evidence is not None and (
            self.evidence.run_id != self.run_id
            or self.evidence.trace_id != self.trace_id
            or self.evidence.correlation_id != self.correlation_id
            or self.evidence.evidence_hash != self.proposal.evidence_hash
        ):
            raise ValueError("completion identities or evidence hash do not match")
        return self


InvestigationFlowResult = ControlResult[InvestigationCompletion]


class BoundedInvestigationFlow:
    """Let Strands orchestrate reads while NZ owns durable state and proposal validity."""

    def __init__(
        self,
        runtime: PrimaryAgentRuntime,
        repository: DurableTruthRepository,
        *,
        clock: Callable[[], datetime],
        event_id_factory: Callable[[], UUID],
        monotonic: Callable[[], float] = monotonic_clock,
    ) -> None:
        if not isinstance(runtime, PrimaryAgentRuntime):
            raise TypeError("runtime must be PrimaryAgentRuntime")
        if not callable(clock) or not callable(event_id_factory) or not callable(monotonic):
            raise TypeError("clock, event_id_factory and monotonic must be callable")
        self._runtime = runtime
        self._repository = repository
        self._clock = clock
        self._event_id_factory = event_id_factory
        self._monotonic = monotonic

    def execute(self, run: Run) -> InvestigationFlowResult:
        """Run one bounded investigation or reconcile its exact durable completion."""

        identity = self._runtime.identity
        if not isinstance(run, Run):
            raise TypeError("run must be a Run")
        if (
            run.run_id != identity.run_id
            or run.trace_id != identity.trace_id
            or run.correlation_id != identity.correlation_id
        ):
            return self._failure(
                FailureKind.VALIDATION_FAILURE,
                "RUN_IDENTITY_INVALID",
                "Run identity does not match the Strands tool context",
            )

        try:
            current = self._repository.get_run(run.run_id)
        except StorageDependencyError:
            return self._storage_failure("Durable run lookup is unavailable")
        if current is not None:
            if current != run:
                if current.state is WorkflowState.REMEDIATION_PROPOSED:
                    return self._reconcile_completion(current)
                return self._failure(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "RUN_ALREADY_ACTIVE",
                    "Existing durable run requires explicit recovery",
                )
        else:
            try:
                current = self._repository.create_run(run)
                self._append_audit(
                    run,
                    event_type=AuditEventType.RUN_CREATED,
                    payload_hash=compute_evidence_digest(run.model_dump(mode="json")),
                    source="nz-control-plane",
                )
            except StorageConflictError:
                try:
                    raced = self._repository.get_run(run.run_id)
                except StorageDependencyError:
                    return self._storage_failure("Durable run reconciliation is unavailable")
                if raced is not None and raced.state is WorkflowState.REMEDIATION_PROPOSED:
                    return self._reconcile_completion(raced)
                return self._failure(
                    FailureKind.RECOVERY_REQUIREMENT,
                    "RUN_CREATE_CONFLICT",
                    "Durable run ownership could not be reconciled",
                )
            except StorageDependencyError:
                return self._storage_failure("Durable run creation is unavailable")

        if current.state is not WorkflowState.RECEIVED:
            return self._failure(
                FailureKind.RECOVERY_REQUIREMENT,
                "RUN_STATE_UNSAFE",
                "Investigation can start only from durable RECEIVED state",
            )
        try:
            current = self._transition(current, WorkflowState.INVESTIGATING)
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failure("Durable INVESTIGATING transition failed")

        remaining_turns = current.budget.max_turns - current.budget.turns_used
        remaining_tokens = current.budget.max_tokens - current.budget.tokens_used
        remaining_milliseconds = (
            current.budget.max_elapsed_seconds * 1_000 - current.budget.elapsed_milliseconds_used
        )
        if min(remaining_turns, remaining_tokens, remaining_milliseconds) <= 0:
            return self._budget_exhausted(current, "Run budget was exhausted before invocation")
        limits: Limits = {
            "turns": remaining_turns,
            "output_tokens": min(
                remaining_tokens,
                self._runtime.model_settings.max_output_tokens,
            ),
            "total_tokens": remaining_tokens,
        }
        try:
            started_at = self._monotonic()
        except Exception:
            return self._budget_exhausted(current, "Elapsed-time budget guard is unavailable")
        try:
            agent_result = self._runtime.agent(
                build_investigation_request(self._runtime.target),
                limits=limits,
            )
        except Exception:
            try:
                elapsed = self._elapsed_since(started_at)
            except Exception:
                return self._budget_exhausted(
                    current,
                    "Elapsed-time budget guard returned an invalid interval",
                )
            try:
                current, _ = self._record_budget(current, None, elapsed)
            except ValueError:
                return self._budget_exhausted(
                    current,
                    "Agent usage accounting returned invalid data",
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failure("Durable budget accounting failed")
            return self._fail_durable_run(
                current,
                FailureDetail(
                    kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                    code="STRANDS_DEPENDENCY_UNAVAILABLE",
                    message="Strands or model dependency is unavailable",
                    retryable=True,
                ),
            )

        try:
            elapsed = self._elapsed_since(started_at)
        except Exception:
            return self._budget_exhausted(
                current,
                "Elapsed-time budget guard returned an invalid interval",
            )
        try:
            current, time_exhausted = self._record_budget(current, agent_result, elapsed)
        except ValueError:
            return self._budget_exhausted(
                current,
                "Agent usage accounting returned invalid data",
            )
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failure("Durable budget accounting failed")

        intervention_failure = getattr(
            self._runtime.human_in_the_loop,
            "last_failure",
            None,
        )
        if isinstance(intervention_failure, FailureDetail):
            return self._fail_durable_run(current, intervention_failure)

        if str(agent_result.stop_reason).startswith("limit_") or time_exhausted:
            return self._budget_exhausted(
                current,
                "Bounded Strands investigation exhausted its turn, token, or time budget",
            )

        context = self._runtime.tool_context
        failure = context.first_failure()
        if failure is not None:
            return self._fail_durable_run_with_audit(current, failure)
        if tuple(context.tool_calls) != INVESTIGATION_TOOL_NAMES:
            return self._fail_durable_run_with_audit(
                current,
                FailureDetail(
                    kind=FailureKind.VALIDATION_FAILURE,
                    code="TOOL_SEQUENCE_INVALID",
                    message="Strands did not complete the canonical bounded tool sequence",
                    retryable=False,
                ),
            )
        outcome = context.evidence()
        inspection = context.inspection()
        utilization = context.utilization()
        if outcome is None or inspection is None or utilization is None:
            return self._fail_durable_run_with_audit(
                current,
                FailureDetail(
                    kind=FailureKind.VALIDATION_FAILURE,
                    code="TOOL_EVIDENCE_MISSING",
                    message="Typed tool evidence is incomplete",
                    retryable=False,
                ),
            )

        try:
            self._append_tool_audits(run, outcome)
            current = self._transition(current, WorkflowState.EVIDENCE_READY)
            first_checkpoint = Checkpoint(
                run_id=run.run_id,
                last_safe_state=WorkflowState.EVIDENCE_READY,
                resume_metadata={
                    "classification": outcome.evidence.utilization_classification.value,
                    "proposal_id": str(self._runtime.proposal_id),
                },
                tool_result_hashes={
                    "inspect_instance": inspection.evidence_digest,
                    "read_utilization_metrics": utilization.evidence_digest,
                    "build_remediation_evidence": outcome.evidence.evidence_hash,
                },
                created_at=self._clock(),
                version=1,
            )
            self._repository.save_checkpoint(first_checkpoint, expected_version=None)
        except (StorageConflictError, StorageDependencyError):
            return self._fail_durable_run(
                current,
                FailureDetail(
                    kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                    code="EVIDENCE_DURABILITY_FAILED",
                    message="Evidence checkpoint or audit durability failed",
                    retryable=True,
                ),
            )

        if outcome.decision is EvidenceDecision.NOT_ELIGIBLE:
            return self._fail_durable_run_with_audit(
                current,
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="INSTANCE_NOT_IDLE",
                    message="Deterministic evidence does not support an idle-instance proposal",
                    retryable=False,
                ),
            )
        proposal = outcome.proposal
        if proposal is None:
            return self._fail_durable_run(
                current,
                FailureDetail(
                    kind=FailureKind.RECOVERY_REQUIREMENT,
                    code="PROPOSAL_MISSING",
                    message="Eligible evidence did not produce a typed proposal",
                    retryable=False,
                ),
            )

        try:
            durable_proposal = self._create_or_reconcile_proposal(proposal)
            self._append_audit(
                run,
                event_type=AuditEventType.PROPOSAL_CREATED,
                payload_hash=proposal.evidence_hash,
                source="nz-control-plane",
                metadata={"proposal_id": str(proposal.proposal_id)},
            )
            current = self._transition(current, WorkflowState.REMEDIATION_PROPOSED)
            self._repository.save_checkpoint(
                Checkpoint(
                    run_id=run.run_id,
                    last_safe_state=WorkflowState.REMEDIATION_PROPOSED,
                    resume_metadata={
                        "classification": outcome.evidence.utilization_classification.value,
                        "proposal_id": str(proposal.proposal_id),
                    },
                    tool_result_hashes={
                        "inspect_instance": inspection.evidence_digest,
                        "read_utilization_metrics": utilization.evidence_digest,
                        "build_remediation_evidence": outcome.evidence.evidence_hash,
                    },
                    created_at=self._clock(),
                    version=2,
                ),
                expected_version=1,
            )
            if self._repository.get_approval(proposal.proposal_id) is not None:
                raise StorageConflictError("unexpected approval exists before HITL")
        except StorageDependencyError:
            return self._fail_durable_run(
                current,
                FailureDetail(
                    kind=FailureKind.DEPENDENCY_UNAVAILABLE,
                    code="PROPOSAL_DURABILITY_FAILED",
                    message="Durable proposal persistence is unavailable",
                    retryable=True,
                ),
            )
        except StorageConflictError:
            return self._fail_durable_run(
                current,
                FailureDetail(
                    kind=FailureKind.RECOVERY_REQUIREMENT,
                    code="PROPOSAL_CONFLICT",
                    message="Durable proposal state could not be reconciled",
                    retryable=False,
                ),
            )

        return ControlResult[InvestigationCompletion].succeeded(
            self._completion(
                run=current,
                proposal=durable_proposal,
                evidence=outcome.evidence,
                reconciled=False,
            )
        )

    def _transition(self, run: Run, next_state: WorkflowState) -> Run:
        return self._repository.transition_run(
            run.run_id,
            next_state,
            expected_state=run.state,
            expected_version=run.version,
            updated_at=self._clock(),
        )

    def _append_tool_audits(self, run: Run, outcome: EvidenceBuildOutcome) -> None:
        context = self._runtime.tool_context
        inspection = context.inspection()
        utilization = context.utilization()
        if inspection is None or utilization is None:
            raise StorageConflictError("tool audit requires complete evidence")
        for tool_name, digest, metadata in (
            (
                "inspect_instance",
                inspection.evidence_digest,
                {"instance_id": inspection.instance_id},
            ),
            (
                "read_utilization_metrics",
                utilization.evidence_digest,
                {"classification": utilization.classification.value},
            ),
            (
                "build_remediation_evidence",
                outcome.evidence.evidence_hash,
                {"decision": outcome.decision.value},
            ),
        ):
            self._append_audit(
                run,
                event_type=AuditEventType.TOOL_OBSERVED,
                payload_hash=digest,
                source="strands-agent",
                tool_name=tool_name,
                metadata=metadata,
            )

    def _append_audit(
        self,
        run: Run,
        *,
        event_type: AuditEventType,
        payload_hash: str,
        source: str,
        tool_name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._repository.append_audit_event(
            AuditEvent(
                event_id=self._event_id_factory(),
                run_id=run.run_id,
                type=event_type,
                timestamp=self._clock(),
                source=source,
                tool_name=tool_name,
                model_id=self._runtime.model_settings.model_id,
                redacted_payload_hash=payload_hash,
                metadata={
                    "trace_id": str(run.trace_id),
                    "correlation_id": str(run.correlation_id),
                    **(metadata or {}),
                },
            )
        )

    def _create_or_reconcile_proposal(self, proposal: ActionProposal) -> ActionProposal:
        try:
            return self._repository.create_proposal(proposal)
        except StorageConflictError as conflict:
            existing = self._repository.get_proposal(proposal.proposal_id)
            if existing != proposal:
                raise StorageConflictError("proposal ownership is incompatible") from conflict
            return existing

    def _reconcile_completion(self, run: Run) -> InvestigationFlowResult:
        try:
            proposal = self._repository.get_proposal(self._runtime.proposal_id)
            approval = self._repository.get_approval(self._runtime.proposal_id)
        except StorageDependencyError:
            return self._storage_failure("Durable proposal reconciliation is unavailable")
        if (
            proposal is None
            or proposal.run_id != run.run_id
            or proposal.action is not Capability.STOP_SANDBOX_INSTANCE
            or proposal.authority is not AuthorityGate.PLAN_AND_CONFIRM
            or proposal.state is not ProposalState.PROPOSED
            or proposal.target.resource_id != self._runtime.target.instance_id
            or proposal.target.region != self._runtime.target.region
            or proposal.target.required_tag_key != self._runtime.target.required_tag_key
            or proposal.target.required_tag_value != self._runtime.target.required_tag_value
            or proposal.authorizes_execution
            or approval is not None
        ):
            return self._failure(
                FailureKind.RECOVERY_REQUIREMENT,
                "PROPOSAL_RECONCILIATION_FAILED",
                "Existing durable proposal is missing or incompatible",
            )
        evidence_outcome = self._runtime.tool_context.evidence()
        return ControlResult[InvestigationCompletion].succeeded(
            self._completion(
                run=run,
                proposal=proposal,
                evidence=None if evidence_outcome is None else evidence_outcome.evidence,
                reconciled=True,
            )
        )

    def _completion(
        self,
        *,
        run: Run,
        proposal: ActionProposal,
        evidence: RemediationEvidenceBundle | None,
        reconciled: bool,
    ) -> InvestigationCompletion:
        summary = (
            f"run_id={run.run_id} trace_id={run.trace_id} "
            f"correlation_id={run.correlation_id} proposal_id={proposal.proposal_id}; "
            "durable remediation proposal created; human approval is still absent."
        )
        return InvestigationCompletion(
            run_id=run.run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
            proposal=proposal,
            evidence=evidence,
            final_state=WorkflowState.REMEDIATION_PROPOSED,
            agent_summary=summary,
            reconciled=reconciled,
        )

    def _fail_durable_run(
        self,
        run: Run,
        failure: FailureDetail,
    ) -> InvestigationFlowResult:
        target_state = workflow_state_for_failure(failure)
        try:
            self._transition(run, target_state)
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failure("Failed to persist the terminal investigation state")
        return ControlResult[InvestigationCompletion].failed(failure)

    def _fail_durable_run_with_audit(
        self,
        run: Run,
        failure: FailureDetail,
    ) -> InvestigationFlowResult:
        event_type = (
            AuditEventType.POLICY_DENIED
            if failure.kind is FailureKind.POLICY_DENIAL
            else AuditEventType.MODEL_OUTPUT_REJECTED
            if failure.kind is FailureKind.VALIDATION_FAILURE
            else None
        )
        if event_type is not None:
            try:
                self._append_audit(
                    run,
                    event_type=event_type,
                    payload_hash=compute_evidence_digest(
                        {"code": failure.code, "kind": failure.kind.value}
                    ),
                    source="nz-control-policy",
                    metadata={"failure_code": failure.code},
                )
            except (StorageConflictError, StorageDependencyError):
                return self._storage_failure("Failure audit could not be persisted")
        return self._fail_durable_run(run, failure)

    def _elapsed_since(self, started_at: float) -> float:
        finished_at = self._monotonic()
        if (
            isinstance(started_at, bool)
            or isinstance(finished_at, bool)
            or not isinstance(started_at, (int, float))
            or not isinstance(finished_at, (int, float))
            or not isfinite(float(started_at))
            or not isfinite(float(finished_at))
            or finished_at < started_at
        ):
            raise ValueError("monotonic clock returned an invalid interval")
        return float(finished_at - started_at)

    @staticmethod
    def _agent_consumption(agent_result: object | None) -> tuple[int, int]:
        if agent_result is None:
            return 0, 0
        metrics = getattr(agent_result, "metrics", None)
        invocation = getattr(metrics, "latest_agent_invocation", None)
        cycles = getattr(invocation, "cycles", None)
        usage = getattr(invocation, "usage", None)
        if not isinstance(cycles, (list, tuple)) or not isinstance(usage, dict):
            raise ValueError("Strands usage telemetry is missing")
        tokens = usage.get("totalTokens")
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens < 0:
            raise ValueError("Strands token telemetry is invalid")
        return len(cycles), tokens

    def _record_budget(
        self,
        run: Run,
        agent_result: object | None,
        elapsed_seconds: float,
    ) -> tuple[Run, bool]:
        turns, tokens = self._agent_consumption(agent_result)
        elapsed_milliseconds = max(0, ceil(elapsed_seconds * 1_000))
        remaining_milliseconds = (
            run.budget.max_elapsed_seconds * 1_000 - run.budget.elapsed_milliseconds_used
        )
        budget_exhausted = (
            elapsed_milliseconds >= remaining_milliseconds
            or turns > run.budget.max_turns - run.budget.turns_used
            or tokens > run.budget.max_tokens - run.budget.tokens_used
        )
        budget = BudgetCounters(
            max_turns=run.budget.max_turns,
            max_tokens=run.budget.max_tokens,
            max_elapsed_seconds=run.budget.max_elapsed_seconds,
            turns_used=min(run.budget.max_turns, run.budget.turns_used + turns),
            tokens_used=min(run.budget.max_tokens, run.budget.tokens_used + tokens),
            elapsed_milliseconds_used=min(
                run.budget.max_elapsed_seconds * 1_000,
                run.budget.elapsed_milliseconds_used + elapsed_milliseconds,
            ),
        )
        updated = self._repository.update_run_budget(
            run.run_id,
            budget,
            expected_version=run.version,
            updated_at=self._clock(),
        )
        self._append_audit(
            updated,
            event_type=AuditEventType.BUDGET_UPDATED,
            payload_hash=compute_evidence_digest(budget.model_dump(mode="json")),
            source="nz-budget-guard",
            metadata={
                "elapsed_milliseconds_used": str(budget.elapsed_milliseconds_used),
                "model_units_used": str(budget.tokens_used),
                "turns_used": str(budget.turns_used),
            },
        )
        return updated, budget_exhausted

    def _budget_exhausted(self, run: Run, message: str) -> InvestigationFlowResult:
        failure = FailureDetail(
            kind=FailureKind.BUDGET_EXHAUSTION,
            code="AGENT_BUDGET_EXHAUSTED",
            message=message,
            retryable=False,
        )
        try:
            self._append_audit(
                run,
                event_type=AuditEventType.BUDGET_EXHAUSTED,
                payload_hash=compute_evidence_digest(run.budget.model_dump(mode="json")),
                source="nz-budget-guard",
                metadata={"failure_code": failure.code},
            )
        except (StorageConflictError, StorageDependencyError):
            return self._storage_failure("Budget exhaustion audit could not be persisted")
        return self._fail_durable_run(run, failure)

    @staticmethod
    def _failure(
        kind: FailureKind,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> InvestigationFlowResult:
        return ControlResult[InvestigationCompletion].failed(
            FailureDetail(
                kind=kind,
                code=code,
                message=message,
                retryable=retryable,
            )
        )

    @classmethod
    def _storage_failure(cls, message: str) -> InvestigationFlowResult:
        return cls._failure(
            FailureKind.DEPENDENCY_UNAVAILABLE,
            "DURABLE_TRUTH_UNAVAILABLE",
            message,
            retryable=True,
        )
