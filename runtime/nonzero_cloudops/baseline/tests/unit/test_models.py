from uuid import UUID

import pytest

from aioa_cloudops_agent.domain import (
    AuthorityGate,
    ContractValidationError,
    ExecutionBudget,
    ExecutionContext,
    ExecutionState,
)

VALID_UUID7 = UUID("01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a")
VALID_BUDGET = ExecutionBudget(max_turns=10, max_tokens=4_096)


def test_valid_execution_context() -> None:
    context = ExecutionContext(
        correlation_id=VALID_UUID7,
        idempotency_key="incident-42:plan-1",
        state=ExecutionState.INIT,
        authority_gate=AuthorityGate.PLAN_AND_CONFIRM,
        budget=VALID_BUDGET,
    )

    assert context.correlation_id.version == 7
    assert context.state is ExecutionState.INIT
    assert context.authority_gate is AuthorityGate.PLAN_AND_CONFIRM
    assert context.budget == VALID_BUDGET


@pytest.mark.parametrize("state", [None, "INIT", 0])
def test_execution_context_rejects_missing_or_untyped_state(state: object) -> None:
    with pytest.raises(ContractValidationError, match="state must be an ExecutionState"):
        ExecutionContext(
            correlation_id=VALID_UUID7,
            idempotency_key="incident-42",
            state=state,
            authority_gate=AuthorityGate.AUTO,
            budget=VALID_BUDGET,
        )


def test_execution_context_rejects_uuid4_instead_of_faking_uuid7() -> None:
    uuid4_value = UUID("123e4567-e89b-42d3-a456-426614174abc")

    with pytest.raises(ContractValidationError, match="UUIDv7"):
        ExecutionContext(
            correlation_id=uuid4_value,
            idempotency_key="incident-42",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=VALID_BUDGET,
        )


@pytest.mark.parametrize("correlation_id", [None, "01890f6c-3311-7abc-8f4a-6e4f7f0b9b3a"])
def test_execution_context_requires_typed_correlation_id(correlation_id: object) -> None:
    with pytest.raises(ContractValidationError, match="must be a UUID"):
        ExecutionContext(
            correlation_id=correlation_id,
            idempotency_key="incident-42",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=VALID_BUDGET,
        )


@pytest.mark.parametrize("idempotency_key", [None, "", "   "])
def test_execution_context_rejects_missing_idempotency_key(idempotency_key: object) -> None:
    with pytest.raises(ContractValidationError, match="idempotency_key"):
        ExecutionContext(
            correlation_id=VALID_UUID7,
            idempotency_key=idempotency_key,
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=VALID_BUDGET,
        )


def test_execution_context_rejects_missing_budget() -> None:
    with pytest.raises(ContractValidationError, match="budget must be an ExecutionBudget"):
        ExecutionContext(
            correlation_id=VALID_UUID7,
            idempotency_key="incident-42",
            state=ExecutionState.INIT,
            authority_gate=AuthorityGate.AUTO,
            budget=None,
        )


@pytest.mark.parametrize(
    ("max_turns", "max_tokens"),
    [
        (0, 1),
        (-1, 1),
        (True, 1),
        (1, 0),
        (1, -1),
        (1, False),
        (ExecutionBudget.MAX_TURNS + 1, 1),
        (1, ExecutionBudget.MAX_TOKENS + 1),
    ],
)
def test_execution_budget_rejects_invalid_or_unbounded_values(
    max_turns: object,
    max_tokens: object,
) -> None:
    with pytest.raises(ContractValidationError):
        ExecutionBudget(max_turns=max_turns, max_tokens=max_tokens)


def test_execution_budget_requires_all_fields() -> None:
    with pytest.raises(TypeError):
        ExecutionBudget(max_turns=1)
