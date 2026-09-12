"""Physically separate, fail-closed EC2 sandbox stop executor."""

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from aioa_cloudops_agent.config import SandboxRemediationSettings
from aioa_cloudops_agent.nz import (
    ExecutionAcknowledgement,
    ObservedInstanceState,
)
from aioa_cloudops_agent.persistence import compute_evidence_digest

from .emergency import EmergencyExecutionControl
from .errors import (
    RemediationAmbiguousError,
    RemediationDependencyError,
    RemediationDisabledError,
    RemediationExecutionError,
    RemediationScopeError,
)
from .models import StopExecutionCommand


class Ec2StopInstancesClient(Protocol):
    """Only AWS calls owned by the private executor process."""

    def describe_instances(self, *, InstanceIds: list[str]) -> dict[str, object]: ...

    def stop_instances(
        self,
        *,
        InstanceIds: list[str],
        DryRun: bool = False,
    ) -> dict[str, object]: ...


class PrivateRemediationExecutor(Protocol):
    """Orchestrator-facing private executor boundary."""

    def execute(self, command: StopExecutionCommand) -> ExecutionAcknowledgement: ...


def _aws_error_code(error: Exception) -> str | None:
    response = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return None
    details = response.get("Error")
    if not isinstance(details, Mapping):
        return None
    code = details.get("Code")
    return code if isinstance(code, str) else None


def _single_instance(response: object) -> Mapping[str, object]:
    if not isinstance(response, Mapping):
        raise RemediationDependencyError("DescribeInstances returned a malformed response")
    reservations = response.get("Reservations")
    if not isinstance(reservations, list):
        raise RemediationDependencyError("DescribeInstances omitted reservations")
    instances: list[Mapping[str, object]] = []
    for reservation in reservations:
        if not isinstance(reservation, Mapping):
            raise RemediationDependencyError("DescribeInstances returned a malformed reservation")
        reservation_instances = reservation.get("Instances")
        if not isinstance(reservation_instances, list):
            raise RemediationDependencyError("DescribeInstances omitted instance records")
        if not all(isinstance(instance, Mapping) for instance in reservation_instances):
            raise RemediationDependencyError("DescribeInstances returned malformed instance data")
        instances.extend(reservation_instances)
    if len(instances) != 1:
        raise RemediationScopeError("exactly one sandbox instance must be returned")
    return instances[0]


class Ec2SandboxStopExecutor:
    """Own the sole StopInstances capability behind all live safety gates."""

    def __init__(
        self,
        client: Ec2StopInstancesClient,
        settings: SandboxRemediationSettings,
        *,
        emergency_control: EmergencyExecutionControl,
        clock: Callable[[], datetime],
    ) -> None:
        if not isinstance(settings, SandboxRemediationSettings):
            raise TypeError("settings must be SandboxRemediationSettings")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if not isinstance(emergency_control, EmergencyExecutionControl):
            raise TypeError("emergency_control must implement EmergencyExecutionControl")
        self._client = client
        self._settings = settings
        self._emergency_control = emergency_control
        self._clock = clock

    def execute(self, command: StopExecutionCommand) -> ExecutionAcknowledgement:
        """Dry-run then gracefully stop exactly one preconfigured tagged target."""

        if not isinstance(command, StopExecutionCommand):
            raise TypeError("command must be StopExecutionCommand")
        if not self._settings.live_execution_enabled:
            raise RemediationDisabledError("live sandbox stop requires both explicit opt-ins")
        target = self._settings.target
        if (
            command.target.resource_id != target.instance_id
            or command.target.region != self._settings.region
            or command.target.required_tag_key != target.required_tag_key
            or command.target.required_tag_value != target.required_tag_value
        ):
            raise RemediationScopeError("execution command is outside configured sandbox scope")
        if command.expected_precondition.instance_state is not ObservedInstanceState.RUNNING:
            raise RemediationScopeError("sandbox stop requires a running precondition")
        try:
            instance = _single_instance(
                self._client.describe_instances(InstanceIds=[target.instance_id])
            )
        except (RemediationDependencyError, RemediationScopeError):
            raise
        except Exception as error:
            raise RemediationDependencyError("fresh sandbox scope check failed") from error
        if instance.get("InstanceId") != target.instance_id:
            raise RemediationScopeError("DescribeInstances returned a different target")
        state = instance.get("State")
        state_name = state.get("Name") if isinstance(state, Mapping) else None
        if state_name != ObservedInstanceState.RUNNING.value:
            raise RemediationScopeError("sandbox instance is not in the approved running state")
        if instance.get("RootDeviceType") != "ebs":
            raise RemediationScopeError("sandbox instance must be EBS-backed")
        tags = instance.get("Tags")
        if not isinstance(tags, list):
            raise RemediationScopeError("fresh sandbox tag proof is missing")
        tag_map = {
            tag.get("Key"): tag.get("Value")
            for tag in tags
            if isinstance(tag, Mapping)
        }
        if tag_map.get(target.required_tag_key) != target.required_tag_value:
            raise RemediationScopeError("fresh sandbox tag proof failed")

        self._emergency_control.assert_writes_enabled()
        try:
            self._client.stop_instances(InstanceIds=[target.instance_id], DryRun=True)
        except Exception as error:
            if _aws_error_code(error) != "DryRunOperation":
                raise RemediationDependencyError("StopInstances DryRun was not authorized") from error
        else:
            raise RemediationDependencyError("StopInstances DryRun returned unexpected success")

        self._emergency_control.assert_writes_enabled()
        try:
            response = self._client.stop_instances(InstanceIds=[target.instance_id])
        except Exception as error:
            code = _aws_error_code(error)
            if code is None:
                raise RemediationAmbiguousError(
                    "StopInstances acknowledgement is ambiguous and requires reconciliation"
                ) from error
            raise RemediationExecutionError(f"StopInstances failed with AWS code {code}") from error
        if not isinstance(response, Mapping):
            raise RemediationAmbiguousError("StopInstances returned a malformed acknowledgement")
        transitions = response.get("StoppingInstances")
        if not isinstance(transitions, list) or len(transitions) != 1:
            raise RemediationAmbiguousError("StopInstances did not acknowledge exactly one target")
        transition = transitions[0]
        if not isinstance(transition, Mapping) or transition.get("InstanceId") != target.instance_id:
            raise RemediationAmbiguousError("StopInstances acknowledgement target is ambiguous")
        previous = transition.get("PreviousState")
        current = transition.get("CurrentState")
        previous_name = previous.get("Name") if isinstance(previous, Mapping) else None
        current_name = current.get("Name") if isinstance(current, Mapping) else None
        if previous_name != ObservedInstanceState.RUNNING.value or current_name not in {
            ObservedInstanceState.STOPPING.value,
            ObservedInstanceState.STOPPED.value,
        }:
            raise RemediationAmbiguousError("StopInstances acknowledgement state is unexpected")
        response_metadata = response.get("ResponseMetadata")
        request_reference = (
            response_metadata.get("RequestId")
            if isinstance(response_metadata, Mapping)
            else None
        )
        if request_reference is not None and not isinstance(request_reference, str):
            request_reference = None
        acknowledged_at = self._clock()
        hash_payload = {
            "proposal_id": str(command.proposal_id),
            "run_id": str(command.run_id),
            "action": command.action.value,
            "target": command.target.model_dump(mode="json"),
            "previous_state": previous_name,
            "current_state": current_name,
            "request_reference": request_reference,
            "acknowledged_at": acknowledged_at.isoformat(),
        }
        return ExecutionAcknowledgement(
            proposal_id=command.proposal_id,
            run_id=command.run_id,
            action=command.action,
            target=command.target,
            previous_state=ObservedInstanceState(previous_name),
            current_state=ObservedInstanceState(current_name),
            request_reference=request_reference,
            acknowledged_at=acknowledged_at,
            acknowledgement_hash=compute_evidence_digest(hash_payload),
        )
