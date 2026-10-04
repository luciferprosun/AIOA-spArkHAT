"""Single-operation authorization schema; not production authority."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import ClassVar

from .authority import AuthorityScope, RiskLevel, decode_enum
from .contracts import Contract, ContractValidationError, digest_id, identifier, utc_time
from .decision_root import DecisionDependencyRoot


class RevisionPolicy(Enum):
    REQUIRE = 'REQUIRE'
    ALLOW_UNVERSIONED = 'ALLOW_UNVERSIONED'


@dataclass(frozen=True, kw_only=True)
class EffectWarrant(Contract):
    TYPE: ClassVar[str] = 'EffectWarrant'
    __hash__ = Contract.__hash__
    TIME_FIELDS: ClassVar[tuple[str, ...]] = ('issued_at', 'expires_at')
    warrant_id: str
    task_id: str
    owner_scope: str
    operation_class: str
    operation_hash: str
    target_fingerprint: str
    expected_target_revision: str | None
    revision_policy: RevisionPolicy
    decision_dependency_root: DecisionDependencyRoot
    lease_epoch: int
    authority_scope: AuthorityScope
    approval_digest: str
    money_reservation_id: str
    risk_reservation_id: str
    nonce: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self):
        for field in ('warrant_id', 'task_id', 'owner_scope', 'operation_class', 'money_reservation_id', 'risk_reservation_id', 'nonce'):
            identifier(getattr(self, field), field)
        for field in ('operation_hash', 'target_fingerprint', 'approval_digest'):
            digest_id(getattr(self, field), field)
        if type(self.lease_epoch) is not int or self.lease_epoch < 0:
            raise ContractValidationError('lease_epoch', 'nonnegative_integer_required')
        if type(self.decision_dependency_root) is not DecisionDependencyRoot:
            raise ContractValidationError('decision_dependency_root', 'dependency_root_required')
        if type(self.authority_scope) is not AuthorityScope:
            raise ContractValidationError('authority_scope', 'authority_scope_required')
        if type(self.revision_policy) is not RevisionPolicy:
            raise ContractValidationError('revision_policy', 'invalid_policy')
        if self.expected_target_revision is None:
            if self.revision_policy is not RevisionPolicy.ALLOW_UNVERSIONED:
                raise ContractValidationError('expected_target_revision', 'revision_required')
        else:
            identifier(self.expected_target_revision, 'expected_target_revision')
        object.__setattr__(self, 'issued_at', utc_time(self.issued_at, 'issued_at'))
        object.__setattr__(self, 'expires_at', utc_time(self.expires_at, 'expires_at'))
        if self.expires_at <= self.issued_at:
            raise ContractValidationError('expires_at', 'invalid_window')
        scope = self.authority_scope
        if self.owner_scope != scope.owner_scope or self.task_id != scope.task_scope:
            raise ContractValidationError('authority_scope', 'owner_task_mismatch')
        if self.operation_class not in scope.operation_classes or self.target_fingerprint != scope.target_scope:
            raise ContractValidationError('authority_scope', 'operation_target_mismatch')
        if self.issued_at < scope.not_before or self.expires_at > scope.expires_at:
            raise ContractValidationError('authority_scope', 'window_outside_scope')
        if (self.money_reservation_id == 'NONE') != (scope.monetary_ceiling.amount == 0):
            raise ContractValidationError('money_reservation_id', 'inconsistent_reservation')
        if (self.risk_reservation_id == 'NONE') != (scope.risk_ceiling is RiskLevel.LOW):
            raise ContractValidationError('risk_reservation_id', 'inconsistent_reservation')

    @classmethod
    def _decode(cls, payload):
        payload['revision_policy'] = decode_enum(RevisionPolicy, payload['revision_policy'], 'revision_policy')
        payload['decision_dependency_root'] = DecisionDependencyRoot.from_dict(payload['decision_dependency_root'])
        payload['authority_scope'] = AuthorityScope.from_dict(payload['authority_scope'])
        return payload
