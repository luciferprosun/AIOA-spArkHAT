"""Orchestrator adapter for invoking only the private remediation function."""

import json
from collections.abc import Mapping
from typing import Protocol

from aioa_cloudops_agent.nz import ExecutionAcknowledgement

from .emergency import is_emergency_denial_payload
from .errors import (
    RemediationAmbiguousError,
    RemediationDependencyError,
    RemediationEmergencyDisabledError,
)
from .models import StopExecutionCommand


class LambdaInvokeClient(Protocol):
    """Narrow Lambda invocation API; no EC2 authority is exposed here."""

    def invoke(self, **kwargs: object) -> dict[str, object]: ...


class LambdaPrivateRemediationExecutor:
    """Send one typed command to one explicitly configured private function."""

    def __init__(self, client: LambdaInvokeClient, function_name: str) -> None:
        if not isinstance(function_name, str) or not function_name.strip():
            raise ValueError("function_name must be a non-empty explicit identifier")
        if function_name != function_name.strip():
            raise ValueError("function_name must not contain surrounding whitespace")
        self._client = client
        self._function_name = function_name

    def execute(self, command: StopExecutionCommand) -> ExecutionAcknowledgement:
        """Invoke synchronously once and reject malformed or ambiguous responses."""

        if not isinstance(command, StopExecutionCommand):
            raise TypeError("command must be StopExecutionCommand")
        try:
            response = self._client.invoke(
                FunctionName=self._function_name,
                InvocationType="RequestResponse",
                Payload=json.dumps(
                    command.model_dump(mode="json"),
                    allow_nan=False,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8"),
            )
        except Exception as error:
            raise RemediationAmbiguousError(
                "Private executor acknowledgement is ambiguous"
            ) from error
        if not isinstance(response, Mapping):
            raise RemediationAmbiguousError("Private executor returned a malformed response")
        if response.get("FunctionError") is not None:
            raise RemediationDependencyError("Private executor reported a typed function error")
        payload = response.get("Payload")
        try:
            raw = payload.read() if hasattr(payload, "read") else payload
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            decoded = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as error:
            raise RemediationAmbiguousError(
                "Private executor acknowledgement could not be validated"
            ) from error
        if is_emergency_denial_payload(decoded):
            raise RemediationEmergencyDisabledError(
                "emergency executor disable is active or unavailable"
            )
        try:
            return ExecutionAcknowledgement.model_validate(decoded)
        except Exception as error:
            raise RemediationAmbiguousError(
                "Private executor acknowledgement could not be validated"
            ) from error
