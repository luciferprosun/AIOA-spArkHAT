"""Pydantic contracts for one allow-listed sandbox EC2 investigation."""

import os
import re
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from aioa_cloudops_agent.config.settings import DEFAULT_AWS_REGION
from aioa_cloudops_agent.domain.aws_boundary import AwsOperationClass
from aioa_cloudops_agent.domain.enums import AuthorityGate
from aioa_cloudops_agent.domain.errors import ContractValidationError
from aioa_cloudops_agent.nz import ControlResult, Run
from aioa_cloudops_agent.nz.identifiers import Sha256Digest, Uuid7Identifier
from aioa_cloudops_agent.persistence.models import compute_evidence_digest

DEFAULT_SANDBOX_TAG_KEY: Final = "AIOACloudOpsSandbox"
DEFAULT_SANDBOX_TAG_VALUE: Final = "true"
_INSTANCE_ID_PATTERN: Final = re.compile(r"^i-[0-9a-f]{8}(?:[0-9a-f]{9})?$")
_INSTANCE_TYPE_PATTERN: Final = re.compile(r"^[a-z0-9][a-z0-9.-]{1,63}$")
_AVAILABILITY_ZONE_PATTERN: Final = re.compile(r"^eu-central-1[a-z]$")


def _valid_instance_id(value: object) -> str:
    if not isinstance(value, str) or _INSTANCE_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("instance_id must be a valid EC2 instance identifier")
    return value


def validate_instance_id(value: object) -> str:
    """Return one syntactically valid EC2 instance identifier."""

    try:
        return _valid_instance_id(value)
    except ValueError as error:
        raise ContractValidationError(str(error)) from error


def _valid_bounded_text(name: str, value: object, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ValueError(f"{name} must not contain surrounding whitespace")
    if len(value) > maximum:
        raise ValueError(f"{name} must not exceed {maximum} characters")
    return value


def _valid_utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be a timezone-aware UTC datetime")
    return value


class CloudOpsContract(BaseModel):
    """Strict immutable public boundary for model/tool/control exchange."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Ec2InstanceState(StrEnum):
    """States returned by EC2 DescribeInstances."""

    PENDING = "pending"
    RUNNING = "running"
    SHUTTING_DOWN = "shutting-down"
    TERMINATED = "terminated"
    STOPPING = "stopping"
    STOPPED = "stopped"


class Ec2MonitoringState(StrEnum):
    """Normalized detailed-monitoring state."""

    DISABLED = "disabled"
    DISABLING = "disabling"
    ENABLED = "enabled"
    PENDING = "pending"


class InvestigationIdentity(CloudOpsContract):
    """UUIDv7 identities propagated across run, tools, evidence, and audit."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier

    @classmethod
    def from_run(cls, run: Run) -> "InvestigationIdentity":
        """Derive tool identity only from the typed authoritative run."""

        if not isinstance(run, Run):
            raise TypeError("run must be a Run")
        return cls(
            run_id=run.run_id,
            trace_id=run.trace_id,
            correlation_id=run.correlation_id,
        )


class SandboxTarget(CloudOpsContract):
    """Exact EC2 target and tag proof required before evidence is actionable."""

    instance_id: str
    region: Literal["eu-central-1"] = DEFAULT_AWS_REGION
    required_tag_key: str = DEFAULT_SANDBOX_TAG_KEY
    required_tag_value: str = DEFAULT_SANDBOX_TAG_VALUE

    @field_validator("instance_id", mode="before")
    @classmethod
    def validate_target_instance_id(cls, value: object) -> str:
        return _valid_instance_id(value)

    @field_validator("required_tag_key")
    @classmethod
    def validate_tag_key(cls, value: object) -> str:
        return _valid_bounded_text("required_tag_key", value, 128)

    @field_validator("required_tag_value")
    @classmethod
    def validate_tag_value(cls, value: object) -> str:
        return _valid_bounded_text("required_tag_value", value, 256)

    @classmethod
    def from_environment(cls) -> "SandboxTarget":
        """Load production scope without inventing a target or changing AWS tags."""

        instance_id = os.getenv("SANDBOX_INSTANCE_ID")
        if instance_id is None:
            raise ContractValidationError("SANDBOX_INSTANCE_ID is required")
        try:
            return cls(
                instance_id=instance_id,
                region=os.getenv("SANDBOX_REGION", DEFAULT_AWS_REGION),
                required_tag_key=os.getenv("SANDBOX_TAG_KEY", DEFAULT_SANDBOX_TAG_KEY),
                required_tag_value=os.getenv(
                    "SANDBOX_TAG_VALUE",
                    DEFAULT_SANDBOX_TAG_VALUE,
                ),
            )
        except ValueError as error:
            raise ContractValidationError("sandbox target configuration is invalid") from error


class InstanceInspection(CloudOpsContract):
    """Normalized non-secret evidence for one proven sandbox instance."""

    run_id: Uuid7Identifier
    trace_id: Uuid7Identifier
    correlation_id: Uuid7Identifier
    instance_id: str
    region: Literal["eu-central-1"]
    state: Ec2InstanceState
    instance_type: str
    launch_time: datetime
    monitoring_state: Ec2MonitoringState
    availability_zone: str
    sandbox_tag_key: str
    sandbox_tag_value: str
    evidence_digest: Sha256Digest
    authority_gate: AuthorityGate = AuthorityGate.AUTO
    operation_class: AwsOperationClass = AwsOperationClass.READ_ONLY

    @field_validator("instance_id", mode="before")
    @classmethod
    def validate_inspected_instance_id(cls, value: object) -> str:
        return _valid_instance_id(value)

    @field_validator("instance_type")
    @classmethod
    def validate_instance_type(cls, value: object) -> str:
        if not isinstance(value, str) or _INSTANCE_TYPE_PATTERN.fullmatch(value) is None:
            raise ValueError("instance_type is invalid")
        return value

    @field_validator("launch_time")
    @classmethod
    def validate_launch_time(cls, value: datetime) -> datetime:
        return _valid_utc("launch_time", value)

    @field_validator("availability_zone")
    @classmethod
    def validate_availability_zone(cls, value: object) -> str:
        if not isinstance(value, str) or _AVAILABILITY_ZONE_PATTERN.fullmatch(value) is None:
            raise ValueError("availability_zone must belong to eu-central-1")
        return value

    @field_validator("sandbox_tag_key")
    @classmethod
    def validate_sandbox_tag_key(cls, value: object) -> str:
        return _valid_bounded_text("sandbox_tag_key", value, 128)

    @field_validator("sandbox_tag_value")
    @classmethod
    def validate_sandbox_tag_value(cls, value: object) -> str:
        return _valid_bounded_text("sandbox_tag_value", value, 256)

    @model_validator(mode="after")
    def validate_boundary_and_digest(self) -> Self:
        if self.authority_gate is not AuthorityGate.AUTO:
            raise ValueError("inspect_instance authority gate must be AUTO")
        if self.operation_class is not AwsOperationClass.READ_ONLY:
            raise ValueError("inspect_instance operation must be READ_ONLY")
        if self.evidence_digest != compute_evidence_digest(self.evidence_payload()):
            raise ValueError("evidence_digest does not match inspection evidence")
        return self

    @classmethod
    def create(
        cls,
        *,
        identity: InvestigationIdentity,
        instance_id: str,
        region: str,
        state: Ec2InstanceState,
        instance_type: str,
        launch_time: datetime,
        monitoring_state: Ec2MonitoringState,
        availability_zone: str,
        sandbox_tag_key: str,
        sandbox_tag_value: str,
    ) -> "InstanceInspection":
        """Build evidence with a digest over canonical allow-listed fields."""

        if not isinstance(identity, InvestigationIdentity):
            raise TypeError("identity must be an InvestigationIdentity")
        payload = {
            "authority_gate": AuthorityGate.AUTO.value,
            "availability_zone": availability_zone,
            "correlation_id": str(identity.correlation_id),
            "instance_id": instance_id,
            "instance_type": instance_type,
            "launch_time": launch_time.isoformat(),
            "monitoring_state": monitoring_state.value,
            "operation_class": AwsOperationClass.READ_ONLY.value,
            "region": region,
            "run_id": str(identity.run_id),
            "sandbox_tag_key": sandbox_tag_key,
            "sandbox_tag_value": sandbox_tag_value,
            "state": state.value,
            "trace_id": str(identity.trace_id),
        }
        return cls(
            run_id=identity.run_id,
            trace_id=identity.trace_id,
            correlation_id=identity.correlation_id,
            instance_id=instance_id,
            region=region,
            state=state,
            instance_type=instance_type,
            launch_time=launch_time,
            monitoring_state=monitoring_state,
            availability_zone=availability_zone,
            sandbox_tag_key=sandbox_tag_key,
            sandbox_tag_value=sandbox_tag_value,
            evidence_digest=compute_evidence_digest(payload),
        )

    def evidence_payload(self) -> dict[str, str]:
        """Return canonical evidence without raw provider metadata."""

        return {
            "authority_gate": self.authority_gate.value,
            "availability_zone": self.availability_zone,
            "correlation_id": str(self.correlation_id),
            "instance_id": self.instance_id,
            "instance_type": self.instance_type,
            "launch_time": self.launch_time.isoformat(),
            "monitoring_state": self.monitoring_state.value,
            "operation_class": self.operation_class.value,
            "region": self.region,
            "run_id": str(self.run_id),
            "sandbox_tag_key": self.sandbox_tag_key,
            "sandbox_tag_value": self.sandbox_tag_value,
            "state": self.state.value,
            "trace_id": str(self.trace_id),
        }

    def as_dict(self) -> dict[str, str]:
        """Return the typed public evidence as JSON-safe values."""

        return {**self.evidence_payload(), "evidence_digest": self.evidence_digest}


InspectInstanceResult = ControlResult[InstanceInspection]
