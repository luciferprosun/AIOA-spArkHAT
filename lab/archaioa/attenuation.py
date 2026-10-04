"""Meet-only delegation schema semantics; no authority minting or execution."""
from dataclasses import dataclass, replace
from typing import ClassVar

from .authority import AuthorityScope, decode_enum
from .contracts import Contract, ContractValidationError, identifier
from .warrant import RevisionPolicy


def _scope(value) -> AuthorityScope:
    """Accept canonical typed scopes or complete strict wire scopes.

    PRE-01 typed scopes already normalize operation sets. Raw attenuation wire
    input rejects duplicates before that normalization; no omitted defaults.
    """
    if type(value) is AuthorityScope:
        return value
    if type(value) is not dict:
        raise ContractValidationError('scope', 'authority_scope_required')
    operations = value.get('operation_classes')
    if type(operations) is not list:
        raise ContractValidationError('operation_classes', 'array_required')
    for operation in operations:
        identifier(operation, 'operation_classes')
    if len(set(operations)) != len(operations):
        raise ContractValidationError('operation_classes', 'duplicate_operation')
    return AuthorityScope.from_dict(value)


@dataclass(frozen=True)
class AuthorityBounds(Contract):
    """Complete scope plus explicit revision policy; no permissive defaults."""
    TYPE: ClassVar[str] = 'AuthorityBounds'
    __hash__ = Contract.__hash__
    authority_scope: AuthorityScope
    revision_policy: RevisionPolicy

    def __post_init__(self):
        if type(self.authority_scope) is not AuthorityScope:
            raise ContractValidationError('authority_scope', 'authority_scope_required')
        if type(self.revision_policy) is not RevisionPolicy:
            raise ContractValidationError('revision_policy', 'invalid_policy')

    @classmethod
    def _decode(cls, payload):
        payload['authority_scope'] = _scope(payload['authority_scope'])
        payload['revision_policy'] = decode_enum(RevisionPolicy, payload['revision_policy'], 'revision_policy')
        return payload


def scope_contains(parent: AuthorityScope, child: AuthorityScope) -> bool:
    """Exact child <= parent relation, using PRE-01 singleton scope semantics."""
    return _scope(parent).contains(_scope(child))


def validate_attenuation(parent: AuthorityScope, child: AuthorityScope) -> None:
    """Reject any scope amplification with sanitized typed metadata."""
    if not scope_contains(parent, child):
        raise ContractValidationError('scope', 'authority_amplification')


def attenuate_scope(parent: AuthorityScope, restriction: AuthorityScope) -> AuthorityScope:
    """Compute the meet or fail closed if no representable nonempty meet exists.

    Identifiers are opaque exact singletons, never path-prefix hierarchies.
    Currency conversion, empty executable scopes, and sibling unions are absent.
    """
    a, b = _scope(parent), _scope(restriction)
    if (a.owner_scope, a.task_scope, a.target_scope, a.monetary_ceiling.currency) != (
            b.owner_scope, b.task_scope, b.target_scope, b.monetary_ceiling.currency):
        raise ContractValidationError('scope', 'incomparable_scope')
    operations = tuple(sorted(set(a.operation_classes) & set(b.operation_classes)))
    start, end = max(a.not_before, b.not_before), min(a.expires_at, b.expires_at)
    if not operations or start >= end:
        raise ContractValidationError('scope', 'empty_meet')
    child = replace(a, operation_classes=operations,
                    risk_ceiling=min((a.risk_ceiling, b.risk_ceiling), key=lambda risk: risk.rank),
                    monetary_ceiling=min((a.monetary_ceiling, b.monetary_ceiling), key=lambda money: money.amount),
                    not_before=start, expires_at=end)
    validate_attenuation(a, child)
    validate_attenuation(b, child)
    return child


def _bounds(value):
    if type(value) is not AuthorityBounds:
        raise ContractValidationError('bounds', 'authority_bounds_required')
    return value


def validate_authority_attenuation(parent: AuthorityBounds, child: AuthorityBounds) -> None:
    """Scope and revision policy must both attenuate."""
    a, b = _bounds(parent), _bounds(child)
    validate_attenuation(a.authority_scope, b.authority_scope)
    if a.revision_policy is RevisionPolicy.REQUIRE and b.revision_policy is not RevisionPolicy.REQUIRE:
        raise ContractValidationError('revision_policy', 'policy_amplification')


def validate_authority_chain(human_root: AuthorityBounds, parent: AuthorityBounds,
                             child: AuthorityBounds) -> None:
    """Check child <= parent <= caller-supplied root; no human authentication."""
    validate_authority_attenuation(human_root, parent)
    validate_authority_attenuation(parent, child)


def attenuate_authority(parent: AuthorityBounds, restriction: AuthorityBounds) -> AuthorityBounds:
    """Meet scope and explicit unversioned policy without minting authority."""
    a, b = _bounds(parent), _bounds(restriction)
    policy = (RevisionPolicy.REQUIRE if RevisionPolicy.REQUIRE in
              (a.revision_policy, b.revision_policy) else RevisionPolicy.ALLOW_UNVERSIONED)
    child = AuthorityBounds(attenuate_scope(a.authority_scope, b.authority_scope), policy)
    validate_authority_attenuation(a, child)
    validate_authority_attenuation(b, child)
    return child
