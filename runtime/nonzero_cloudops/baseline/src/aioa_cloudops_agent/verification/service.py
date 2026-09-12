"""Read-only verification using the existing exact-target EC2 inspection boundary."""

from datetime import datetime

from aioa_cloudops_agent.cloudops import (
    Ec2InstanceState,
    InspectInstanceService,
    InvestigationIdentity,
    SandboxTarget,
)
from aioa_cloudops_agent.nz import (
    ActionProposal,
    ControlResult,
    ResultStatus,
    VerificationDisposition,
)
from aioa_cloudops_agent.persistence import compute_evidence_digest

from .models import VerificationObservation


class VerifyInstanceStateService:
    """Independently re-read only the durable proposal's configured sandbox target."""

    def __init__(
        self,
        inspection_service: InspectInstanceService,
        target: SandboxTarget,
    ) -> None:
        if not isinstance(inspection_service, InspectInstanceService):
            raise TypeError("inspection_service must be InspectInstanceService")
        if not isinstance(target, SandboxTarget):
            raise TypeError("target must be SandboxTarget")
        self._inspection_service = inspection_service
        self._target = target

    def observe(
        self,
        proposal: ActionProposal,
        identity: InvestigationIdentity,
        *,
        observed_at: datetime,
        attempt: int,
    ) -> ControlResult[VerificationObservation]:
        """Return explicit stopped, transitional, mismatch, or provider failure evidence."""

        if not isinstance(proposal, ActionProposal):
            raise TypeError("proposal must be ActionProposal")
        if (
            proposal.target.resource_id != self._target.instance_id
            or proposal.target.region != self._target.region
            or proposal.target.required_tag_key != self._target.required_tag_key
            or proposal.target.required_tag_value != self._target.required_tag_value
        ):
            from aioa_cloudops_agent.nz import FailureDetail, FailureKind

            return ControlResult[VerificationObservation].failed(
                FailureDetail(
                    kind=FailureKind.POLICY_DENIAL,
                    code="VERIFICATION_SCOPE_DENIED",
                    message="Durable proposal is outside configured sandbox scope",
                    retryable=False,
                )
            )
        inspection = self._inspection_service.inspect_result(
            instance_id=proposal.target.resource_id,
            identity=identity,
        )
        if inspection.status is ResultStatus.FAILURE:
            assert inspection.failure is not None
            return ControlResult[VerificationObservation].failed(inspection.failure)
        assert inspection.value is not None
        state = inspection.value.state
        disposition = (
            VerificationDisposition.VERIFIED
            if state is Ec2InstanceState.STOPPED
            else VerificationDisposition.STILL_TRANSITIONING
            if state is Ec2InstanceState.STOPPING
            else VerificationDisposition.MISMATCH
        )
        payload = {
            "proposal_id": str(proposal.proposal_id),
            "run_id": str(identity.run_id),
            "trace_id": str(identity.trace_id),
            "correlation_id": str(identity.correlation_id),
            "target": proposal.target.model_dump(mode="json"),
            "disposition": disposition.value,
            "observed_state": state.value,
            "observed_at": observed_at.isoformat(),
            "attempt": attempt,
            "inspection_evidence_hash": inspection.value.evidence_digest,
        }
        return ControlResult[VerificationObservation].succeeded(
            VerificationObservation(
                proposal_id=proposal.proposal_id,
                run_id=identity.run_id,
                trace_id=identity.trace_id,
                correlation_id=identity.correlation_id,
                target=proposal.target,
                disposition=disposition,
                observed_state=state,
                observed_at=observed_at,
                attempt=attempt,
                inspection_evidence_hash=inspection.value.evidence_digest,
                observation_hash=compute_evidence_digest(payload),
            )
        )
