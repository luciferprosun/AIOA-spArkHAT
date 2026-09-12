import pytest

from aioa_cloudops_agent.nz import (
    AuthorityGate,
    Capability,
    CapabilityDeniedError,
    authority_for_capability,
    require_capability_authority,
)


@pytest.mark.parametrize(
    "capability",
    [
        Capability.INSPECT_INSTANCE,
        Capability.READ_UTILIZATION_METRICS,
        Capability.BUILD_REMEDIATION_EVIDENCE,
        Capability.VERIFY_INSTANCE_STATE,
    ],
)
def test_observation_and_evidence_capabilities_are_auto(capability: Capability) -> None:
    assert authority_for_capability(capability) is AuthorityGate.AUTO


def test_sandbox_stop_requires_plan_and_confirm() -> None:
    assert (
        authority_for_capability(Capability.STOP_SANDBOX_INSTANCE) is AuthorityGate.PLAN_AND_CONFIRM
    )


@pytest.mark.parametrize(
    "capability",
    [
        Capability.TERMINATE_INSTANCES,
        Capability.START_INSTANCES,
        Capability.REBOOT_INSTANCES,
        Capability.MODIFY_INSTANCE_ATTRIBUTE,
        Capability.CREATE_TAGS,
        Capability.DELETE_TAGS,
        Capability.IAM_MUTATION,
        Capability.SSM_COMMAND_EXECUTION,
        Capability.FILESYSTEM_ACCESS,
        Capability.CREDENTIAL_ACCESS,
        Capability.UNSAFE_STOP_OPTIONS,
        Capability.STORAGE_DATABASE_DELETION,
        Capability.SECURITY_GROUP_NETWORK_OPENING,
        Capability.SHELL_EXECUTION,
        Capability.ARBITRARY_CODE_EXECUTION,
        Capability.ARBITRARY_URL_FETCH,
        Capability.OUTSIDE_SANDBOX_SCOPE,
    ],
)
def test_dangerous_capabilities_are_never_autonomous(capability: Capability) -> None:
    assert authority_for_capability(capability) is AuthorityGate.NEVER_AUTONOMOUS


def test_unknown_capability_defaults_to_deny() -> None:
    with pytest.raises(CapabilityDeniedError, match="unknown capability"):
        authority_for_capability("delete_everything")


def test_model_cannot_claim_auto_for_mutation() -> None:
    with pytest.raises(CapabilityDeniedError, match="PLAN_AND_CONFIRM"):
        require_capability_authority(
            Capability.STOP_SANDBOX_INSTANCE,
            AuthorityGate.AUTO,
        )


def test_untyped_authority_claim_fails_closed() -> None:
    with pytest.raises(CapabilityDeniedError, match="untyped"):
        require_capability_authority(Capability.INSPECT_INSTANCE, "AUTO")
