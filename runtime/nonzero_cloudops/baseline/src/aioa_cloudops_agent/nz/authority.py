"""Closed capability-to-authority policy owned by the deterministic application."""

from typing import Final

from aioa_cloudops_agent.domain.enums import AuthorityGate

from .enums import Capability
from .errors import CapabilityDeniedError

_CAPABILITY_AUTHORITY: Final[dict[Capability, AuthorityGate]] = {
    Capability.INSPECT_INSTANCE: AuthorityGate.AUTO,
    Capability.READ_UTILIZATION_METRICS: AuthorityGate.AUTO,
    Capability.BUILD_REMEDIATION_EVIDENCE: AuthorityGate.AUTO,
    Capability.STOP_SANDBOX_INSTANCE: AuthorityGate.PLAN_AND_CONFIRM,
    Capability.VERIFY_INSTANCE_STATE: AuthorityGate.AUTO,
    Capability.QUERY_RESOURCE: AuthorityGate.AUTO,
    Capability.PLAN_REMEDIATION: AuthorityGate.PLAN_AND_CONFIRM,
    Capability.RELEASE_ELASTIC_IP: AuthorityGate.PLAN_AND_CONFIRM,
    Capability.REVOKE_PUBLIC_INGRESS: AuthorityGate.PLAN_AND_CONFIRM,
    Capability.TERMINATE_INSTANCES: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.START_INSTANCES: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.REBOOT_INSTANCES: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.MODIFY_INSTANCE_ATTRIBUTE: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.CREATE_TAGS: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.DELETE_TAGS: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.IAM_MUTATION: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.SSM_COMMAND_EXECUTION: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.FILESYSTEM_ACCESS: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.CREDENTIAL_ACCESS: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.UNSAFE_STOP_OPTIONS: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.STORAGE_DATABASE_DELETION: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.SECURITY_GROUP_NETWORK_OPENING: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.SHELL_EXECUTION: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.ARBITRARY_CODE_EXECUTION: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.ARBITRARY_URL_FETCH: AuthorityGate.NEVER_AUTONOMOUS,
    Capability.OUTSIDE_SANDBOX_SCOPE: AuthorityGate.NEVER_AUTONOMOUS,
}


def authority_for_capability(capability: Capability) -> AuthorityGate:
    """Return explicit authority or deny unknown/untyped capability values."""

    if not isinstance(capability, Capability):
        raise CapabilityDeniedError("unknown capability is denied")
    try:
        return _CAPABILITY_AUTHORITY[capability]
    except KeyError as error:
        raise CapabilityDeniedError("capability has no authority policy") from error


def require_capability_authority(
    capability: Capability,
    claimed_authority: AuthorityGate,
) -> AuthorityGate:
    """Reject a model or caller that claims authority outside the closed policy."""

    if not isinstance(claimed_authority, AuthorityGate):
        raise CapabilityDeniedError("authority claim is untyped and denied")
    required = authority_for_capability(capability)
    if claimed_authority is not required:
        raise CapabilityDeniedError(f"{capability.value} requires authority {required.value}")
    return required
