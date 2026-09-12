from aioa_cloudops_agent.domain import AuthorityGate, ExecutionState


def test_execution_state_values_are_canonical() -> None:
    assert [state.value for state in ExecutionState] == [
        "INIT",
        "RUNNING",
        "PENDING",
        "SUCCESS",
        "FAIL",
    ]


def test_authority_gate_values_are_canonical() -> None:
    assert [gate.value for gate in AuthorityGate] == [
        "AUTO",
        "PLAN_AND_CONFIRM",
        "NEVER_AUTONOMOUS",
    ]
