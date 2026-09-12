"""Small fail-closed correction budget for strict model-output schemas."""

from pydantic import BaseModel

from aioa_cloudops_agent.nz import ControlResult, FailureDetail, FailureKind


class SchemaCorrectionBudget:
    """Count rejected model payloads without ever relaxing their schema."""

    def __init__(self, *, max_attempts: int = 2) -> None:
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int):
            raise TypeError("max_attempts must be an integer")
        if not 1 <= max_attempts <= 3:
            raise ValueError("schema correction max_attempts must be between 1 and 3")
        self._max_attempts = max_attempts
        self._invalid_attempts = 0

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def invalid_attempts(self) -> int:
        return self._invalid_attempts

    @property
    def exhausted(self) -> bool:
        return self._invalid_attempts >= self._max_attempts

    def reject(self) -> FailureDetail:
        """Consume one correction attempt and return a typed validation failure."""

        if self._invalid_attempts < self._max_attempts:
            self._invalid_attempts += 1
        exhausted = self.exhausted
        return FailureDetail(
            kind=FailureKind.VALIDATION_FAILURE,
            code=("MODEL_OUTPUT_INVALID" if exhausted else "MODEL_OUTPUT_CORRECTION_REQUIRED"),
            message=(
                "Model output remained schema-invalid after the bounded correction budget"
                if exhausted
                else "Model output is schema-invalid and may be corrected within the fixed budget"
            ),
            retryable=not exhausted,
        )


class BoundedSchemaCorrection:
    """Strictly validate a fixed Pydantic model within a tiny correction budget."""

    def __init__(self, model_type: type[BaseModel], *, max_attempts: int = 2) -> None:
        if not isinstance(model_type, type) or not issubclass(model_type, BaseModel):
            raise TypeError("model_type must be a Pydantic model class")
        self._model_type = model_type
        self._budget = SchemaCorrectionBudget(max_attempts=max_attempts)

    @property
    def budget(self) -> SchemaCorrectionBudget:
        return self._budget

    def validate(self, payload: object) -> ControlResult[BaseModel]:
        """Validate strictly; an exhausted guard cannot be reopened by later prose."""

        if self._budget.exhausted:
            return ControlResult[BaseModel].failed(self._budget.reject())
        try:
            value = self._model_type.model_validate(payload, strict=True)
        except (TypeError, ValueError):
            return ControlResult[BaseModel].failed(self._budget.reject())
        return ControlResult[BaseModel].succeeded(value)
