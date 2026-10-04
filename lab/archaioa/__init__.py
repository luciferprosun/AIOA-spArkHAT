"""Portable PCAF contracts and pure semantics. CONTRACT / FIXTURE only."""
from .authority import AuthorityScope, Money, RiskLevel
from .canonical import canonical_digest, canonical_json
from .contracts import ContractValidationError
from .decision_root import DecisionDependencyRoot
from .evidence import EvidenceRef
from .liability import LiabilityRecord, LiabilityStatus
from .outcome import Applied, NotApplied, Outcome, Unknown
from .warrant import EffectWarrant, RevisionPolicy
from .faults import (
    FaultKind, FaultTrace, ambiguity_liability, classify_fault, is_blocking,
    open_liability, resolve_liability,
)
from .taint import DependencyGraph, DependencyNode, NodeKind, NodeTaint, TaintState, propagate_taint
from .task_semantics import CompletionDecision, CompletionState, check_completion

__all__ = (
    'Applied', 'AuthorityScope', 'ContractValidationError',
    'DecisionDependencyRoot', 'EffectWarrant', 'EvidenceRef', 'LiabilityRecord',
    'LiabilityStatus', 'Money', 'NotApplied', 'Outcome', 'RevisionPolicy',
    'RiskLevel', 'Unknown', 'canonical_digest', 'canonical_json',
    'CompletionDecision', 'CompletionState', 'DependencyGraph', 'DependencyNode',
    'FaultKind', 'FaultTrace', 'NodeKind', 'NodeTaint', 'TaintState',
    'ambiguity_liability', 'check_completion', 'classify_fault', 'is_blocking',
    'open_liability', 'propagate_taint', 'resolve_liability',
)

from .attenuation import (
    AuthorityBounds, attenuate_authority, attenuate_scope, scope_contains,
    validate_attenuation, validate_authority_attenuation,
)
from .decision_binding import (
    DecisionBinding, DecisionState, bind_decision, require_current_decision, validate_decision_binding,
)

__all__ += (
    'AuthorityBounds', 'attenuate_authority', 'attenuate_scope', 'scope_contains',
    'validate_attenuation', 'validate_authority_attenuation',
    'DecisionBinding', 'DecisionState', 'bind_decision', 'require_current_decision', 'validate_decision_binding',
)
