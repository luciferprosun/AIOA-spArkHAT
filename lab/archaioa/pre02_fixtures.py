"""Synthetic lost-receipt stories, with no clock reads or external effects."""
from datetime import datetime, timezone

from .evidence import EvidenceRef
from .faults import FaultKind, FaultTrace, open_liability
from .taint import DependencyGraph, DependencyNode, NodeKind

START = datetime(2026, 10, 4, tzinfo=timezone.utc)


def resolution_evidence() -> EvidenceRef:
    return EvidenceRef('resolution-1', 'fixture', 'sha256:' + 'c' * 64, 'r1')


def fault_story(kind: FaultKind):
    """Ambiguous operation -> claim -> proposal -> completion candidate.

    LOST_ACK: effect may have happened, acknowledgment lost.
    PROVIDER_TIMEOUT_AFTER_POSSIBLE_ACCEPT: charge/acceptance may have happened.
    MISSING_RECEIPT_AFTER_EFFECT: effect evidence missing.
    INCONCLUSIVE_READBACK: observation proves neither outcome.
    None of these stories creates retries or classifies success/failure.
    """
    trace = FaultTrace(kind, 'task-1', 'request-1', 'sha256:' + 'a' * 64)
    liability = open_liability(trace, START)
    graph = DependencyGraph('task-1', (
        DependencyNode('operation', NodeKind.OPERATION, liability_ids=(liability.liability_id,)),
        DependencyNode('claim', NodeKind.CLAIM, ('operation',)),
        DependencyNode('proposal', NodeKind.PROPOSAL, ('claim',)),
        DependencyNode('candidate', NodeKind.COMPLETION_CANDIDATE, ('proposal',)),
    ))
    return trace, liability, graph
