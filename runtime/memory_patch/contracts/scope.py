"Generic scope dimensions carried without domain-specific interpretation."

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from runtime.memory_patch.contracts.enums import (
    MissingDimensionBehavior,
    ScopeComparisonMode,
    ScopeValueType,
)
from runtime.memory_patch.contracts.serialization import (
    ensure_utc,
    freeze_json,
    require_enum_member,
    require_non_empty,
)
from runtime.memory_patch.errors import ContractValidationError


@dataclass(frozen=True, slots=True)
class ScopeDimension:
    """A typed request or evidence scope value interpreted by a HAT."""

    name: str
    value: Any
    value_type: ScopeValueType
    comparison_mode: ScopeComparisonMode
    source: str
    required: bool

    def __post_init__(self) -> None:
        require_non_empty(self.name, "scope dimension name")
        require_non_empty(self.source, "scope dimension source")
        require_enum_member(self.value_type, ScopeValueType, "value_type")
        require_enum_member(
            self.comparison_mode, ScopeComparisonMode, "comparison_mode"
        )
        if self.required is not True and self.required is not False:
            raise ContractValidationError("scope required must be a boolean")
        object.__setattr__(self, "value", freeze_json(self.value))
        validate_scope_value(self.value, self.value_type, self.name)


@dataclass(frozen=True, slots=True)
class HatScopeDimensionDefinition:
    """A HAT declaration of a supported dimension and missing-value policy."""

    name: str
    value_type: ScopeValueType
    comparison_mode: ScopeComparisonMode
    required: bool
    default_behavior: MissingDimensionBehavior
    missing_creates_ambiguous: bool
    default_value: Any | None = None
    description: str = ""

    def __post_init__(self) -> None:
        require_non_empty(self.name, "scope definition name")
        require_enum_member(self.value_type, ScopeValueType, "value_type")
        require_enum_member(
            self.comparison_mode, ScopeComparisonMode, "comparison_mode"
        )
        require_enum_member(
            self.default_behavior, MissingDimensionBehavior, "default_behavior"
        )
        if self.required is not True and self.required is not False:
            raise ContractValidationError("scope required must be a boolean")
        if (
            self.missing_creates_ambiguous is not True
            and self.missing_creates_ambiguous is not False
        ):
            raise ContractValidationError("missing_creates_ambiguous must be a boolean")
        frozen_default = freeze_json(self.default_value)
        object.__setattr__(self, "default_value", frozen_default)
        if self.default_behavior is MissingDimensionBehavior.USE_DEFAULT:
            if self.default_value is None:
                raise ContractValidationError(
                    f"scope definition {self.name!r} requires a default value"
                )
            validate_scope_value(self.default_value, self.value_type, self.name)
        elif self.default_value is not None:
            raise ContractValidationError(
                f"scope definition {self.name!r} has an unused default value"
            )
        if self.required and self.default_behavior is MissingDimensionBehavior.OPTIONAL:
            raise ContractValidationError(
                f"required scope definition {self.name!r} cannot be OPTIONAL"
            )
        if self.default_behavior is MissingDimensionBehavior.AMBIGUOUS and (
            not self.missing_creates_ambiguous
        ):
            raise ContractValidationError(
                f"scope definition {self.name!r} must mark missing as ambiguous"
            )


def validate_scope_value(
    value: Any, value_type: ScopeValueType, field_name: str
) -> None:
    """Validate representation only; Kernel Core never interprets its meaning."""
    if value_type is ScopeValueType.STRING and (not isinstance(value, str)):
        raise ContractValidationError(f"{field_name} must be a string")
    if value_type is ScopeValueType.INTEGER and (
        not isinstance(value, int) or isinstance(value, bool)
    ):
        raise ContractValidationError(f"{field_name} must be an integer")
    if value_type is ScopeValueType.NUMBER and (
        not isinstance(value, (int, float)) or isinstance(value, bool)
    ):
        raise ContractValidationError(f"{field_name} must be numeric")
    if value_type is ScopeValueType.BOOLEAN and (not isinstance(value, bool)):
        raise ContractValidationError(f"{field_name} must be a boolean")
    if value_type is ScopeValueType.STRING_SET:
        if not isinstance(value, (tuple, frozenset)) or not all(
            (isinstance(item, str) for item in value)
        ):
            raise ContractValidationError(f"{field_name} must be a string collection")
    if value_type is ScopeValueType.TIMESTAMP:
        ensure_utc(value, field_name)
    if value_type is ScopeValueType.SEMVER:
        if not isinstance(value, str) or not value.strip():
            raise ContractValidationError(f"{field_name} must be a version string")


def validate_scope_dimensions(
    definitions: tuple[HatScopeDimensionDefinition, ...],
    values: tuple[ScopeDimension, ...],
) -> tuple[str, ...]:
    """Return missing dimensions that the manifest says make routing ambiguous."""
    definitions_by_name = {definition.name: definition for definition in definitions}
    if len(definitions_by_name) != len(definitions):
        raise ContractValidationError("scope definition names must be unique")
    values_by_name = {dimension.name: dimension for dimension in values}
    if len(values_by_name) != len(values):
        raise ContractValidationError("scope dimension names must be unique")
    unsupported = set(values_by_name) - set(definitions_by_name)
    if unsupported:
        raise ContractValidationError(
            f"unsupported scope dimensions: {', '.join(sorted(unsupported))}"
        )
    for name, dimension in values_by_name.items():
        definition = definitions_by_name[name]
        if dimension.value_type is not definition.value_type:
            raise ContractValidationError(f"scope dimension {name!r} has wrong type")
        if dimension.comparison_mode is not definition.comparison_mode:
            raise ContractValidationError(
                f"scope dimension {name!r} has wrong comparison mode"
            )
    ambiguous = [
        definition.name
        for definition in definitions
        if definition.name not in values_by_name
        and definition.missing_creates_ambiguous
    ]
    return tuple(sorted(ambiguous))


def scope_interval_is_valid(
    valid_from: datetime | None, valid_until: datetime | None
) -> bool:
    """Return whether an optional validity interval is well formed."""
    if valid_from is not None:
        valid_from = ensure_utc(valid_from, "valid_from")
    if valid_until is not None:
        valid_until = ensure_utc(valid_until, "valid_until")
    return valid_from is None or valid_until is None or valid_from <= valid_until
