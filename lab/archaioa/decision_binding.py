"""Selected-evidence binding for a warrant candidate; no ServiceGuard effects."""
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar

from .authority import decode_enum
from .contracts import Contract, ContractValidationError, digest_id, identifier
from .decision_root import DecisionDependencyRoot
from .warrant import EffectWarrant


class DecisionState(Enum):
    CURRENT = 'CURRENT'
    STALE = 'STALE'


@dataclass(frozen=True)
class DecisionBinding(Contract):
    TYPE: ClassVar[str] = 'DecisionBinding'
    __hash__ = Contract.__hash__
    warrant_id: str
    operation_hash: str
    expected_root: DecisionDependencyRoot
    current_root: DecisionDependencyRoot
    state: DecisionState

    def __post_init__(self):
        identifier(self.warrant_id, 'warrant_id')
        digest_id(self.operation_hash, 'operation_hash')
        for field in ('expected_root', 'current_root'):
            if type(getattr(self, field)) is not DecisionDependencyRoot:
                raise ContractValidationError(field, 'dependency_root_required')
        if type(self.state) is not DecisionState:
            raise ContractValidationError('state', 'invalid_decision_state')
        expected_state = (DecisionState.CURRENT if self.current_root.root_digest == self.expected_root.root_digest
                          else DecisionState.STALE)
        if self.state is not expected_state:
            raise ContractValidationError('state', 'root_state_mismatch')

    def __bool__(self):
        raise TypeError('DecisionBinding requires explicit state inspection')

    @classmethod
    def _decode(cls, payload):
        for field in ('expected_root', 'current_root'):
            payload[field] = DecisionDependencyRoot.from_dict(payload[field])
        payload['state'] = decode_enum(DecisionState, payload['state'], 'state')
        return payload


def bind_decision(warrant: EffectWarrant, selected_evidence) -> DecisionBinding:
    """Recompute from caller-selected current evidence, never ambient task state.

    The caller must supply the entire current decision dependency set, including
    current additions/removals. Invalid/conflicting metadata raises a sanitized
    contract error; a well-formed changed set yields an explicit STALE result.
    CURRENT means root equality only, not production authorization or freshness
    against a clock. No evidence lookup, payload storage or effect occurs here.
    """
    if type(warrant) is not EffectWarrant:
        raise ContractValidationError('warrant', 'effect_warrant_required')
    current = DecisionDependencyRoot(selected_evidence)
    expected = warrant.decision_dependency_root
    state = DecisionState.CURRENT if current.root_digest == expected.root_digest else DecisionState.STALE
    return DecisionBinding(warrant.warrant_id, warrant.operation_hash, expected, current, state)



def validate_decision_binding(warrant: EffectWarrant, binding: DecisionBinding) -> None:
    """Reject stale or differently bound metadata; never consume the warrant."""
    if type(warrant) is not EffectWarrant:
        raise ContractValidationError('warrant', 'effect_warrant_required')
    if type(binding) is not DecisionBinding:
        raise ContractValidationError('binding', 'decision_binding_required')
    if (binding.warrant_id != warrant.warrant_id or
            binding.operation_hash != warrant.operation_hash or
            binding.expected_root != warrant.decision_dependency_root):
        raise ContractValidationError('binding', 'warrant_binding_mismatch')
    if binding.state is not DecisionState.CURRENT:
        raise ContractValidationError('decision_dependency_root', 'stale_decision')


def require_current_decision(warrant: EffectWarrant, selected_evidence) -> DecisionBinding:
    """Compute the current selection and fail closed on mismatch."""
    binding = bind_decision(warrant, selected_evidence)
    validate_decision_binding(warrant, binding)
    return binding
