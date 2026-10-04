"""Finite, pure PRE-04 abstraction; no real authorization or effect execution."""
from collections import deque
from dataclasses import asdict, dataclass, replace
import hashlib
import json

PHASES = (
    'PROPOSED', 'VERIFIED', 'APPROVAL_REQUIRED', 'WARRANT_READY',
    'INTENT_RECORDED', 'DISPATCHED', 'ACKED', 'UNKNOWN', 'RECONCILING',
    'EXECUTED', 'NOT_APPLIED', 'COMPLETED', 'BLOCKED',
)
OUTCOMES = ('NONE', 'APPLIED', 'NOT_APPLIED', 'UNKNOWN')
ACTIONS = (
    'verify', 'require_approval', 'grant_warrant', 'record_intent',
    'invalidate_warrant', 'invalidate_attenuation', 'invalidate_epoch',
    'block', 'dispatch', 'ack_applied', 'ack_not_applied', 'lose_ack',
    'commit_applied', 'commit_not_applied', 'begin_reconciliation',
    'record_evidence', 'resolve_applied', 'resolve_not_applied', 'complete',
)


@dataclass(frozen=True)
class State:
    phase: str = 'PROPOSED'
    warrant_present: bool = False
    warrant_consumed: bool = False
    warrant_current: bool = True
    authority_attenuation_valid: bool = True
    lease_epoch_current: bool = True
    outcome: str = 'NONE'
    open_liability_count: int = 0
    reconciliation_evidence: bool = False
    effect_count: int = 0
    completed: bool = False
    # History witnesses: current flags may become false after dispatch.
    authorized_consumption: bool = False
    dispatch_attenuation_valid: bool = False
    dispatch_epoch_current: bool = False
    commit_recorded: bool = False
    commit_epoch_current: bool = False
    unknown_seen: bool = False

    def serialize(self):
        return json.dumps(asdict(self), sort_keys=True, separators=(',', ':'))


def invariant_violations(s):
    """Return named P1..P6 failures, including on deliberately unsafe fixtures."""
    failures = []
    if s.effect_count > 0 and not (
        s.warrant_present and s.warrant_consumed and s.authorized_consumption
    ):
        failures.append('NoEffectWithoutWarrant')
    if s.effect_count > 1:
        failures.append('NoWarrantReuse')
    if s.effect_count > 0 and not s.dispatch_attenuation_valid:
        failures.append('NoAuthorityAmplification')
    if ((s.effect_count > 0 and not s.dispatch_epoch_current)
            or (s.commit_recorded and not s.commit_epoch_current)):
        failures.append('NoStaleEpochCommit')
    if s.unknown_seen and s.phase in ('EXECUTED', 'NOT_APPLIED', 'COMPLETED') and not (
        s.reconciliation_evidence and s.outcome in ('APPLIED', 'NOT_APPLIED')
    ):
        failures.append('NoUnknownToSuccessWithoutEvidence')
    if s.completed and (s.open_liability_count != 0 or s.outcome == 'UNKNOWN'):
        failures.append('NoCompletedTaskWithOpenLiability')
    return tuple(failures)


def _well_formed(s):
    if not isinstance(s, State) or s.phase not in PHASES or s.outcome not in OUTCOMES:
        return False
    for name, value in asdict(s).items():
        if name not in ('phase', 'outcome', 'effect_count', 'open_liability_count'):
            if type(value) is not bool:
                return False
    return (type(s.effect_count) is int and 0 <= s.effect_count <= 2
            and type(s.open_liability_count) is int and 0 <= s.open_liability_count <= 1
            and s.completed == (s.phase == 'COMPLETED'))


class TransitionRejected(ValueError):
    """An abstract action failed closed; the immutable input is unchanged."""


def transition(s, action):
    """One guarded action; invalid inputs/actions and unsafe results fail closed."""
    if not _well_formed(s) or invariant_violations(s) or action not in ACTIONS:
        raise TransitionRejected('invalid state or action')
    p = s.phase
    updates = None
    if action == 'verify' and p == 'PROPOSED':
        updates = dict(phase='VERIFIED')
    elif action == 'require_approval' and p == 'VERIFIED':
        updates = dict(phase='APPROVAL_REQUIRED')
    elif action == 'grant_warrant' and p == 'APPROVAL_REQUIRED' and not s.warrant_present:
        updates = dict(phase='WARRANT_READY', warrant_present=True)
    elif action == 'record_intent' and p == 'WARRANT_READY':
        updates = dict(phase='INTENT_RECORDED')
    elif action in ('invalidate_warrant', 'invalidate_attenuation', 'invalidate_epoch'):
        field = {'invalidate_warrant': 'warrant_current',
                 'invalidate_attenuation': 'authority_attenuation_valid',
                 'invalidate_epoch': 'lease_epoch_current'}[action]
        if p not in ('COMPLETED', 'BLOCKED') and getattr(s, field):
            updates = {field: False}
    elif action == 'block' and p in PHASES[:5] and not (
        s.warrant_current and s.authority_attenuation_valid and s.lease_epoch_current
    ):
        updates = dict(phase='BLOCKED')
    elif action == 'dispatch' and p == 'INTENT_RECORDED' and (
        s.warrant_present and not s.warrant_consumed and s.warrant_current
        and s.authority_attenuation_valid and s.lease_epoch_current
        and s.effect_count == 0 and s.outcome == 'NONE' and not s.unknown_seen
    ):
        updates = dict(phase='DISPATCHED', warrant_consumed=True, effect_count=1,
                       authorized_consumption=True, dispatch_attenuation_valid=True,
                       dispatch_epoch_current=True)
    elif action in ('ack_applied', 'ack_not_applied') and p == 'DISPATCHED':
        updates = dict(phase='ACKED', outcome=(
            'APPLIED' if action == 'ack_applied' else 'NOT_APPLIED'))
    elif action == 'lose_ack' and p == 'DISPATCHED':
        updates = dict(phase='UNKNOWN', outcome='UNKNOWN', open_liability_count=1,
                       unknown_seen=True)
    elif action in ('commit_applied', 'commit_not_applied') and p == 'ACKED' and s.lease_epoch_current:
        expected = 'APPLIED' if action == 'commit_applied' else 'NOT_APPLIED'
        if s.outcome == expected:
            updates = dict(phase='EXECUTED' if expected == 'APPLIED' else 'NOT_APPLIED',
                           commit_recorded=True, commit_epoch_current=True)
    elif action == 'begin_reconciliation' and p == 'UNKNOWN':
        updates = dict(phase='RECONCILING')
    elif action == 'record_evidence' and p == 'RECONCILING' and not s.reconciliation_evidence:
        updates = dict(reconciliation_evidence=True)
    elif action in ('resolve_applied', 'resolve_not_applied') and p == 'RECONCILING' and (
        s.reconciliation_evidence and s.outcome == 'UNKNOWN' and s.lease_epoch_current
    ):
        applied = action == 'resolve_applied'
        updates = dict(phase='EXECUTED' if applied else 'NOT_APPLIED',
                       outcome='APPLIED' if applied else 'NOT_APPLIED',
                       open_liability_count=0, commit_recorded=True, commit_epoch_current=True)
    elif action == 'complete' and p in ('EXECUTED', 'NOT_APPLIED') and (
        s.open_liability_count == 0 and s.outcome in ('APPLIED', 'NOT_APPLIED')
        and (not s.unknown_seen or s.reconciliation_evidence)
    ):
        updates = dict(phase='COMPLETED', completed=True)
    if updates is None:
        raise TransitionRejected('action precondition failed: ' + action)
    result = replace(s, **updates)
    if not _well_formed(result) or invariant_violations(result):
        raise TransitionRejected('action result failed safety check: ' + action)
    return result


def format_trace(trace, violations):
    """Deterministic shortest BFS counterexample, including the initial state."""
    lines = ['Invariant failure: ' + ', '.join(violations)]
    lines.extend(f'{i}: {action} {state.serialize()}' for i, (action, state) in enumerate(trace))
    return '\n'.join(lines)


class ModelViolation(AssertionError):
    pass


@dataclass(frozen=True)
class CheckResult:
    reachable_states: int
    transitions: int
    rejected_attempts: int
    max_depth: int
    digest: str
    violations: tuple = ()


def check_model(initial=State(), depth_bound=32):
    """Exhaust BFS to a fixed point, or fail if the explicit depth bound cuts it off.

    Every action is attempted at every state, including illegal replay/retry.
    The digest covers ordered states and labeled edges/rejections, not hash order.
    """
    queue = deque([(initial, 0)])
    parents = {initial: None}
    edges = rejected = max_depth = 0
    digest = hashlib.sha256()

    def trace(s):
        path = []
        while parents[s] is not None:
            previous, action = parents[s]
            path.append((action, s))
            s = previous
        return [('Init', s)] + list(reversed(path))

    while queue:
        s, depth = queue.popleft()
        failures = invariant_violations(s)
        if not _well_formed(s):
            failures += ('FiniteStateDomain',)
        if failures:
            raise ModelViolation(format_trace(trace(s), failures))
        max_depth = max(max_depth, depth)
        digest.update(('STATE ' + s.serialize() + '\n').encode())
        for action in ACTIONS:
            before = s.serialize()
            try:
                successor = transition(s, action)
            except TransitionRejected:
                assert before == s.serialize(), 'rejected action mutated input'
                rejected += 1
                digest.update(('REJECT ' + action + '\n').encode())
                continue
            edges += 1
            digest.update(('EDGE ' + action + ' ' + successor.serialize() + '\n').encode())
            if successor not in parents:
                parents[successor] = (s, action)
                if depth >= depth_bound:
                    raise ModelViolation(format_trace(trace(successor), ('DepthBoundNotExhaustive',)))
                queue.append((successor, depth + 1))
    return CheckResult(len(parents), edges, rejected, max_depth, digest.hexdigest())


if __name__ == '__main__':
    print(json.dumps(asdict(check_model()), sort_keys=True, separators=(',', ':')))
