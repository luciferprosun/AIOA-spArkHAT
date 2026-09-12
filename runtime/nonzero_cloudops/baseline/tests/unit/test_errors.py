import pytest

from aioa_cloudops_agent.domain import ContractValidationError, DomainError, ErrorCode


def test_domain_error_exposes_typed_contract() -> None:
    error = DomainError(
        code=ErrorCode.INVALID_CONTRACT,
        message="Explicit validation failure",
        retryable=True,
    )

    assert error.code is ErrorCode.INVALID_CONTRACT
    assert error.message == "Explicit validation failure"
    assert error.retryable is True
    assert str(error) == error.message


def test_contract_validation_error_is_explicit_and_not_retryable() -> None:
    error = ContractValidationError("state is required")

    assert error.code is ErrorCode.INVALID_CONTRACT
    assert error.message == "state is required"
    assert error.retryable is False


@pytest.mark.parametrize(
    ("field", "value", "exception_type"),
    [
        ("code", "INVALID_CONTRACT", TypeError),
        ("message", None, TypeError),
        ("message", " ", ValueError),
        ("retryable", None, TypeError),
    ],
)
def test_domain_error_rejects_invalid_contract_fields(
    field: str,
    value: object,
    exception_type: type[Exception],
) -> None:
    arguments: dict[str, object] = {
        "code": ErrorCode.INVALID_CONTRACT,
        "message": "failure",
        "retryable": False,
    }
    arguments[field] = value

    with pytest.raises(exception_type):
        DomainError(**arguments)
