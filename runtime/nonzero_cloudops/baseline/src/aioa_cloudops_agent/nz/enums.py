"""Closed Non-Zero workflow, policy, and result vocabularies."""

from enum import StrEnum
from typing import Final


class WorkflowState(StrEnum):
    """Canonical lifecycle for the bounded idle-EC2 remediation workflow."""

    RECEIVED = "RECEIVED"
    INVESTIGATING = "INVESTIGATING"
    EVIDENCE_READY = "EVIDENCE_READY"
    REMEDIATION_PROPOSED = "REMEDIATION_PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    NO_ACTION_REQUIRED = "NO_ACTION_REQUIRED"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    SUCCESS_WITH_EVIDENCE = "SUCCESS_WITH_EVIDENCE"
    DENIED_BY_HUMAN = "DENIED_BY_HUMAN"
    DENIED_BY_POLICY = "DENIED_BY_POLICY"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    AMBIGUOUS_RESULT = "AMBIGUOUS_RESULT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


TERMINAL_WORKFLOW_STATES: Final[frozenset[WorkflowState]] = frozenset(
    {
        WorkflowState.SUCCESS_WITH_EVIDENCE,
        WorkflowState.NO_ACTION_REQUIRED,
        WorkflowState.RECOMMENDATION_ONLY,
        WorkflowState.DENIED_BY_HUMAN,
        WorkflowState.DENIED_BY_POLICY,
        WorkflowState.MODEL_OUTPUT_INVALID,
        WorkflowState.AMBIGUOUS_RESULT,
        WorkflowState.DEPENDENCY_UNAVAILABLE,
        WorkflowState.BUDGET_EXHAUSTED,
        WorkflowState.EXECUTION_FAILED,
        WorkflowState.VERIFICATION_FAILED,
    }
)


class Capability(StrEnum):
    """Closed policy catalog; entries do not create executable tools."""

    INSPECT_INSTANCE = "inspect_instance"
    READ_UTILIZATION_METRICS = "read_utilization_metrics"
    BUILD_REMEDIATION_EVIDENCE = "build_remediation_evidence"
    STOP_SANDBOX_INSTANCE = "stop_sandbox_instance"
    VERIFY_INSTANCE_STATE = "verify_instance_state"
    QUERY_RESOURCE = "query_resource"
    PLAN_REMEDIATION = "plan_remediation"
    RELEASE_ELASTIC_IP = "ReleaseAddress"
    REVOKE_PUBLIC_INGRESS = "RevokeSecurityGroupIngress"
    TERMINATE_INSTANCES = "TerminateInstances"
    START_INSTANCES = "StartInstances"
    REBOOT_INSTANCES = "RebootInstances"
    MODIFY_INSTANCE_ATTRIBUTE = "ModifyInstanceAttribute"
    CREATE_TAGS = "CreateTags"
    DELETE_TAGS = "DeleteTags"
    IAM_MUTATION = "IAM_MUTATION"
    SSM_COMMAND_EXECUTION = "SSM_COMMAND_EXECUTION"
    FILESYSTEM_ACCESS = "FILESYSTEM_ACCESS"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"
    UNSAFE_STOP_OPTIONS = "UNSAFE_STOP_OPTIONS"
    STORAGE_DATABASE_DELETION = "STORAGE_DATABASE_DELETION"
    SECURITY_GROUP_NETWORK_OPENING = "SECURITY_GROUP_NETWORK_OPENING"
    SHELL_EXECUTION = "SHELL_EXECUTION"
    ARBITRARY_CODE_EXECUTION = "ARBITRARY_CODE_EXECUTION"
    ARBITRARY_URL_FETCH = "ARBITRARY_URL_FETCH"
    OUTSIDE_SANDBOX_SCOPE = "OUTSIDE_SANDBOX_SCOPE"


class ProposalState(StrEnum):
    """Persistence state of a proposal, kept separate from approval."""

    PROPOSED = "PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    SUPERSEDED = "SUPERSEDED"


class ApprovalDecision(StrEnum):
    """Explicit human decision; absence is represented by no approval record."""

    APPROVED = "APPROVED"
    DENIED = "DENIED"


class FailureKind(StrEnum):
    """Failure categories that must survive control and storage boundaries."""

    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    POLICY_DENIAL = "POLICY_DENIAL"
    AMBIGUOUS_RESULT = "AMBIGUOUS_RESULT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    BUDGET_EXHAUSTION = "BUDGET_EXHAUSTION"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    RECOVERY_REQUIREMENT = "RECOVERY_REQUIREMENT"
    ILLEGAL_STATE_TRANSITION = "ILLEGAL_STATE_TRANSITION"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    TOOL_ADAPTER_FAILURE = "TOOL_ADAPTER_FAILURE"
    STORAGE_FAILURE = "STORAGE_FAILURE"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"


class ResultStatus(StrEnum):
    """Discriminator for explicit success and failure results."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ActionOutcome(StrEnum):
    """Durable outcome of a future consequential action."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class IdempotencyStatus(StrEnum):
    """Lifecycle of a semantic idempotency ownership record."""

    REGISTERED = "REGISTERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"


class ExecutionAcknowledgementStatus(StrEnum):
    """Provider acknowledgement is explicitly not verified completion."""

    ACCEPTED = "ACCEPTED"


class VerificationDisposition(StrEnum):
    """Explicit result of independent post-action EC2 read-back."""

    VERIFIED = "VERIFIED"
    STILL_TRANSITIONING = "STILL_TRANSITIONING"
    MISMATCH = "MISMATCH"


class VerificationProofOrigin(StrEnum):
    """How independent stopped-state proof is bound to durable execution truth."""

    EXECUTION_ACKNOWLEDGEMENT = "EXECUTION_ACKNOWLEDGEMENT"
    RECOVERY_READ_BACK = "RECOVERY_READ_BACK"


class ObservedInstanceState(StrEnum):
    """Normalized EC2 states relevant to the bounded workflow."""

    PENDING = "pending"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


class AuditEventType(StrEnum):
    """Append-oriented audit events for workflow and tool evidence."""

    RUN_CREATED = "RUN_CREATED"
    STATE_TRANSITIONED = "STATE_TRANSITIONED"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_RECORDED = "APPROVAL_RECORDED"
    IDEMPOTENCY_REGISTERED = "IDEMPOTENCY_REGISTERED"
    EXECUTION_REQUESTED = "EXECUTION_REQUESTED"
    EXECUTION_ACKNOWLEDGED = "EXECUTION_ACKNOWLEDGED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_OBSERVED = "VERIFICATION_OBSERVED"
    CHECKPOINT_SAVED = "CHECKPOINT_SAVED"
    TOOL_OBSERVED = "TOOL_OBSERVED"
    MODEL_OBSERVED = "MODEL_OBSERVED"
    VERIFICATION_RECORDED = "VERIFICATION_RECORDED"
    RECOVERY_CLASSIFIED = "RECOVERY_CLASSIFIED"
    RECOVERY_OBSERVED = "RECOVERY_OBSERVED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    RECOVERY_DEFERRED = "RECOVERY_DEFERRED"
    POLICY_DENIED = "POLICY_DENIED"
    MODEL_OUTPUT_REJECTED = "MODEL_OUTPUT_REJECTED"
    BUDGET_UPDATED = "BUDGET_UPDATED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RESOURCE_QUERIED = "RESOURCE_QUERIED"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    NO_ACTION_RECORDED = "NO_ACTION_RECORDED"
    RECOMMENDATION_RECORDED = "RECOMMENDATION_RECORDED"


class CloudResourceType(StrEnum):
    """Provider-neutral resource kinds supported by the local CloudSecOps read model."""

    EC2_INSTANCE = "AWS::EC2::Instance"
    ELASTIC_IP = "AWS::EC2::EIP"
    SECURITY_GROUP = "AWS::EC2::SecurityGroup"


class CloudFinding(StrEnum):
    """Closed deterministic findings derived from normalized resource evidence."""

    UNATTACHED_ELASTIC_IP = "UNATTACHED_ELASTIC_IP"
    OVERLY_PERMISSIVE_INGRESS = "OVERLY_PERMISSIVE_INGRESS"
    REQUIRED_TAGS_MISSING = "REQUIRED_TAGS_MISSING"
    CLEAN = "CLEAN"


class RemediationOperation(StrEnum):
    """Closed proposal operations; entries are data and do not expose execution."""

    RELEASE_ELASTIC_IP = "RELEASE_ELASTIC_IP"
    REVOKE_PUBLIC_INGRESS = "REVOKE_PUBLIC_INGRESS"
    APPLY_REQUIRED_TAGS = "APPLY_REQUIRED_TAGS"


class PlanDisposition(StrEnum):
    """Explicit result of deterministic remediation planning."""

    PROPOSAL = "PROPOSAL"
    NO_ACTION = "NO_ACTION"
    NON_EXECUTABLE_RECOMMENDATION = "NON_EXECUTABLE_RECOMMENDATION"


class RecoveryDisposition(StrEnum):
    """What a later recovery controller can infer from durable state."""

    NEW_RUN = "NEW_RUN"
    SAFE_RESUMABLE = "SAFE_RESUMABLE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    TERMINAL_RUN = "TERMINAL_RUN"
