"""Maximum permission schema; pure comparisons do not mint authority."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import ClassVar

from .contracts import Contract, ContractValidationError, identifier, utc_time


class RiskLevel(Enum):
    LOW = 'LOW'
    MODERATE = 'MODERATE'
    HIGH = 'HIGH'
    CRITICAL = 'CRITICAL'

    @property
    def rank(self):
        return tuple(type(self)).index(self)


def decode_enum(enum_type, value, field):
    if type(value) is not str:
        raise ContractValidationError(field, 'invalid_enum')
    try:
        return enum_type(value)
    except ValueError:
        raise ContractValidationError(field, 'invalid_enum') from None


@dataclass(frozen=True)
class Money(Contract):
    TYPE: ClassVar[str] = 'Money'
    __hash__ = Contract.__hash__
    amount: Decimal
    currency: str

    def __post_init__(self):
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite() or self.amount < 0:
            raise ContractValidationError('amount', 'nonnegative_decimal_required')
        if not isinstance(self.currency, str) or re.fullmatch(r'[A-Z]{3}', self.currency) is None:
            raise ContractValidationError('currency', 'invalid_currency')

    @classmethod
    def _decode(cls, payload):
        if type(payload['amount']) is not str or re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?', payload['amount']) is None:
            raise ContractValidationError('amount', 'canonical_decimal_required')
        try:
            payload['amount'] = Decimal(payload['amount'])
        except InvalidOperation:
            raise ContractValidationError('amount', 'invalid_decimal') from None
        return payload


@dataclass(frozen=True)
class AuthorityScope(Contract):
    TYPE: ClassVar[str] = 'AuthorityScope'
    __hash__ = Contract.__hash__
    TIME_FIELDS: ClassVar[tuple[str, ...]] = ('not_before', 'expires_at')
    operation_classes: tuple[str, ...]
    target_scope: str
    risk_ceiling: RiskLevel
    monetary_ceiling: Money
    not_before: datetime
    expires_at: datetime
    owner_scope: str
    task_scope: str

    def __post_init__(self):
        if not isinstance(self.operation_classes, (list, tuple)) or not self.operation_classes:
            raise ContractValidationError('operation_classes', 'nonempty_operations_required')
        for operation in self.operation_classes:
            identifier(operation, 'operation_classes')
        object.__setattr__(self, 'operation_classes', tuple(sorted(set(self.operation_classes))))
        for field in ('target_scope', 'owner_scope', 'task_scope'):
            identifier(getattr(self, field), field)
        if type(self.risk_ceiling) is not RiskLevel:
            raise ContractValidationError('risk_ceiling', 'invalid_risk')
        if type(self.monetary_ceiling) is not Money:
            raise ContractValidationError('monetary_ceiling', 'money_required')
        object.__setattr__(self, 'not_before', utc_time(self.not_before, 'not_before'))
        object.__setattr__(self, 'expires_at', utc_time(self.expires_at, 'expires_at'))
        if self.expires_at <= self.not_before:
            raise ContractValidationError('expires_at', 'invalid_window')

    def contains(self, other: 'AuthorityScope') -> bool:
        if type(other) is not AuthorityScope:
            raise ContractValidationError('scope', 'authority_scope_required')
        return (
            self.target_scope == other.target_scope
            and self.owner_scope == other.owner_scope
            and self.task_scope == other.task_scope
            and set(other.operation_classes) <= set(self.operation_classes)
            and other.risk_ceiling.rank <= self.risk_ceiling.rank
            and self.monetary_ceiling.currency == other.monetary_ceiling.currency
            and other.monetary_ceiling.amount <= self.monetary_ceiling.amount
            and self.not_before <= other.not_before
            and other.expires_at <= self.expires_at
        )

    @classmethod
    def _decode(cls, payload):
        if not isinstance(payload['operation_classes'], list):
            raise ContractValidationError('operation_classes', 'array_required')
        payload['risk_ceiling'] = decode_enum(RiskLevel, payload['risk_ceiling'], 'risk_ceiling')
        payload['monetary_ceiling'] = Money.from_dict(payload['monetary_ceiling'])
        return payload
