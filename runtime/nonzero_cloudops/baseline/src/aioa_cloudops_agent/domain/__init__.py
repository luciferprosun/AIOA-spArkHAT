"""Typed Non-Zero domain contracts."""

from .approval import ApprovalRecord, ApprovalStatus, validate_pending_approval_mapping
from .aws_boundary import (
    AwsBoundaryViolationError,
    AwsOperation,
    AwsOperationAssessment,
    AwsOperationClass,
    HumanApprovalState,
    assess_aws_operation,
    classify_aws_operation,
)
from .enums import AuthorityGate, ExecutionState
from .errors import (
    ContractValidationError,
    DomainError,
    ErrorCode,
    IllegalStateTransitionError,
)
from .identifiers import generate_correlation_id, validate_correlation_id
from .models import ExecutionBudget, ExecutionContext
from .transitions import validate_state_transition

__all__ = [
    "ApprovalRecord",
    "ApprovalStatus",
    "AuthorityGate",
    "AwsBoundaryViolationError",
    "AwsOperation",
    "AwsOperationAssessment",
    "AwsOperationClass",
    "ContractValidationError",
    "DomainError",
    "ErrorCode",
    "ExecutionBudget",
    "ExecutionContext",
    "ExecutionState",
    "HumanApprovalState",
    "IllegalStateTransitionError",
    "assess_aws_operation",
    "classify_aws_operation",
    "generate_correlation_id",
    "validate_correlation_id",
    "validate_pending_approval_mapping",
    "validate_state_transition",
]
