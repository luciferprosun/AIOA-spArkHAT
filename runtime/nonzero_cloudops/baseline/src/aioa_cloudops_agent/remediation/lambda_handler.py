"""Private Lambda entry point using bounded EC2 client construction."""

from datetime import UTC, datetime
from typing import Any

from aioa_cloudops_agent.aws_clients import create_ec2_stop_client
from aioa_cloudops_agent.config import SandboxRemediationSettings

from .emergency import EnvironmentEmergencyExecutionControl, emergency_denial_payload
from .errors import RemediationEmergencyDisabledError
from .executor import Ec2SandboxStopExecutor
from .models import StopExecutionCommand


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    """Validate one command and execute the gated graceful stop with no retries."""

    del context
    settings = SandboxRemediationSettings.from_environment()
    command = StopExecutionCommand.model_validate(event)
    client = create_ec2_stop_client()
    try:
        acknowledgement = Ec2SandboxStopExecutor(
            client,
            settings,
            emergency_control=EnvironmentEmergencyExecutionControl(),
            clock=lambda: datetime.now(UTC),
        ).execute(command)
    except RemediationEmergencyDisabledError:
        return emergency_denial_payload()
    return acknowledgement.model_dump(mode="json")
