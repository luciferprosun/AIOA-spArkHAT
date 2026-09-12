"""Deterministic authority boundary for future AWS operations."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .enums import AuthorityGate
from .errors import ContractValidationError, DomainError, ErrorCode


class AwsOperationClass(StrEnum):
    """Security classification for an AWS operation."""

    READ_ONLY = "READ_ONLY"
    MUTATION = "MUTATION"


class AwsOperation(StrEnum):
    """Closed set needed by the canonical EC2 workflow boundary."""

    INSPECT_INSTANCE = "INSPECT_INSTANCE"
    STOP_SANDBOX_INSTANCE = "STOP_SANDBOX_INSTANCE"


class HumanApprovalState(StrEnum):
    """Approval evidence supplied independently from configuration."""

    NOT_GRANTED = "NOT_GRANTED"
    GRANTED = "GRANTED"


_OPERATION_CLASSES: Final[dict[AwsOperation, AwsOperationClass]] = {
    AwsOperation.INSPECT_INSTANCE: AwsOperationClass.READ_ONLY,
    AwsOperation.STOP_SANDBOX_INSTANCE: AwsOperationClass.MUTATION,
}

_REQUIRED_MUTATION_GATES: Final[dict[AwsOperation, AuthorityGate]] = {
    AwsOperation.STOP_SANDBOX_INSTANCE: AuthorityGate.PLAN_AND_CONFIRM,
}


class AwsBoundaryViolationError(DomainError):
    """Raised when an AWS operation violates its authority boundary."""

    def __init__(self, message: str) -> None:
        super().__init__(
            code=ErrorCode.AWS_BOUNDARY_VIOLATION,
            message=message,
            retryable=False,
        )


@dataclass(frozen=True, slots=True)
class AwsOperationAssessment:
    """Explicit proposal and execution outcome for one classified operation."""

    operation: AwsOperation
    operation_class: AwsOperationClass
    may_propose: bool
    may_execute: bool
    human_approval_required: bool
    human_approval_granted: bool


def classify_aws_operation(operation: AwsOperation) -> AwsOperationClass:
    """Return a closed-set operation class without a permissive fallback."""

    if not isinstance(operation, AwsOperation):
        raise ContractValidationError("operation must be an AwsOperation")
    return _OPERATION_CLASSES[operation]


def assess_aws_operation(
    operation: AwsOperation,
    authority_gate: AuthorityGate,
    *,
    aws_mutations_enabled: bool = False,
    human_approval: HumanApprovalState = HumanApprovalState.NOT_GRANTED,
) -> AwsOperationAssessment:
    """Evaluate an operation without invoking AWS or treating configuration as approval."""

    operation_class = classify_aws_operation(operation)
    if not isinstance(authority_gate, AuthorityGate):
        raise ContractValidationError("authority_gate must be an AuthorityGate")
    if not isinstance(aws_mutations_enabled, bool):
        raise ContractValidationError("aws_mutations_enabled must be a boolean")
    if not isinstance(human_approval, HumanApprovalState):
        raise ContractValidationError("human_approval must be a HumanApprovalState")

    approval_granted = human_approval is HumanApprovalState.GRANTED

    if operation_class is AwsOperationClass.READ_ONLY:
        if authority_gate is AuthorityGate.AUTO:
            may_execute = True
            approval_required = False
        elif authority_gate is AuthorityGate.PLAN_AND_CONFIRM:
            may_execute = approval_granted
            approval_required = True
        else:
            may_execute = False
            approval_required = True
        return AwsOperationAssessment(
            operation=operation,
            operation_class=operation_class,
            may_propose=True,
            may_execute=may_execute,
            human_approval_required=approval_required,
            human_approval_granted=approval_granted,
        )

    if authority_gate is AuthorityGate.AUTO:
        raise AwsBoundaryViolationError("AWS mutations must never use the AUTO authority gate")

    required_gate = _REQUIRED_MUTATION_GATES[operation]
    if authority_gate is not required_gate:
        raise AwsBoundaryViolationError(
            f"{operation.value} requires the {required_gate.value} authority gate"
        )

    may_execute = aws_mutations_enabled and approval_granted

    return AwsOperationAssessment(
        operation=operation,
        operation_class=operation_class,
        may_propose=True,
        may_execute=may_execute,
        human_approval_required=True,
        human_approval_granted=approval_granted,
    )
