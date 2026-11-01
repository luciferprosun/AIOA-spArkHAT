"""Meta 2026 browser-admission *contracts*, not a browser executor.

All requests are untrusted until the existing AIOA Core admits them. This
package grants no owner warrant, filesystem, network, OAuth, or browser access.
"""

from .contracts import (
    ActionProposalV1,
    BrowserObservationV1,
    BrowserTaskV1,
    MetaContractError,
)
from .policy import GateEffect, GateResult, screen_action, screen_observation, screen_task

__all__ = [
    "ActionProposalV1",
    "BrowserObservationV1",
    "BrowserTaskV1",
    "GateEffect",
    "GateResult",
    "MetaContractError",
    "screen_action",
    "screen_observation",
    "screen_task",
]
