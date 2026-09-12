import pytest

from aioa_cloudops_agent.domain import (
    AuthorityGate,
    AwsBoundaryViolationError,
    AwsOperation,
    AwsOperationClass,
    ContractValidationError,
    HumanApprovalState,
    assess_aws_operation,
    classify_aws_operation,
)


def test_inspect_instance_is_read_only_and_auto_executable() -> None:
    assessment = assess_aws_operation(AwsOperation.INSPECT_INSTANCE, AuthorityGate.AUTO)

    assert classify_aws_operation(AwsOperation.INSPECT_INSTANCE) is AwsOperationClass.READ_ONLY
    assert assessment.may_propose is True
    assert assessment.may_execute is True
    assert assessment.human_approval_required is False


def test_mutation_can_never_use_auto() -> None:
    with pytest.raises(AwsBoundaryViolationError, match="must never use the AUTO"):
        assess_aws_operation(AwsOperation.STOP_SANDBOX_INSTANCE, AuthorityGate.AUTO)


def test_plan_and_confirm_allows_a_proposal_but_not_execution_by_default() -> None:
    assessment = assess_aws_operation(
        AwsOperation.STOP_SANDBOX_INSTANCE,
        AuthorityGate.PLAN_AND_CONFIRM,
    )

    assert assessment.operation_class is AwsOperationClass.MUTATION
    assert assessment.may_propose is True
    assert assessment.may_execute is False
    assert assessment.human_approval_required is True
    assert assessment.human_approval_granted is False


def test_configuration_cannot_substitute_for_human_approval() -> None:
    assessment = assess_aws_operation(
        AwsOperation.STOP_SANDBOX_INSTANCE,
        AuthorityGate.PLAN_AND_CONFIRM,
        aws_mutations_enabled=True,
        human_approval=HumanApprovalState.NOT_GRANTED,
    )

    assert assessment.may_execute is False


def test_human_approval_cannot_substitute_for_global_write_enablement() -> None:
    assessment = assess_aws_operation(
        AwsOperation.STOP_SANDBOX_INSTANCE,
        AuthorityGate.PLAN_AND_CONFIRM,
        aws_mutations_enabled=False,
        human_approval=HumanApprovalState.GRANTED,
    )

    assert assessment.may_execute is False


def test_mutation_boundary_requires_both_independent_controls() -> None:
    assessment = assess_aws_operation(
        AwsOperation.STOP_SANDBOX_INSTANCE,
        AuthorityGate.PLAN_AND_CONFIRM,
        aws_mutations_enabled=True,
        human_approval=HumanApprovalState.GRANTED,
    )

    assert assessment.may_execute is True


def test_never_autonomous_is_the_wrong_gate_for_planned_stop() -> None:
    with pytest.raises(AwsBoundaryViolationError, match="requires the PLAN_AND_CONFIRM"):
        assess_aws_operation(
            AwsOperation.STOP_SANDBOX_INSTANCE,
            AuthorityGate.NEVER_AUTONOMOUS,
        )


@pytest.mark.parametrize(
    ("operation", "gate", "mutations_enabled", "approval"),
    [
        ("INSPECT_INSTANCE", AuthorityGate.AUTO, False, HumanApprovalState.NOT_GRANTED),
        (AwsOperation.INSPECT_INSTANCE, "AUTO", False, HumanApprovalState.NOT_GRANTED),
        (AwsOperation.INSPECT_INSTANCE, AuthorityGate.AUTO, 1, HumanApprovalState.NOT_GRANTED),
        (AwsOperation.INSPECT_INSTANCE, AuthorityGate.AUTO, False, True),
    ],
)
def test_untyped_boundary_inputs_fail_explicitly(
    operation: object,
    gate: object,
    mutations_enabled: object,
    approval: object,
) -> None:
    with pytest.raises(ContractValidationError):
        assess_aws_operation(
            operation,
            gate,
            aws_mutations_enabled=mutations_enabled,
            human_approval=approval,
        )
