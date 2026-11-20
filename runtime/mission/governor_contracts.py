"""Value types and validation shared by the governor and its job records."""

import json
import re
from dataclasses import dataclass
from enum import Enum

from runtime.memory_patch.contracts.serialization import canonical_json_bytes
from runtime.memory_patch.errors import ErrorCode, MemoryPatchError

MAX_AMOUNT = 2**63 - 1


class GovernorReason(str, Enum):
    INVALID_AMOUNT = "INVALID_GOVERNOR_AMOUNT"
    INVALID_IDENTITY = "INVALID_GOVERNOR_IDENTITY"
    INVALID_DIGEST = "INVALID_EVIDENCE_DIGEST"
    INVALID_POLICY = "INVALID_GOVERNOR_POLICY"
    INVALID_BINDINGS = "INVALID_GOVERNOR_BINDINGS"
    CLOCK_UNSAFE = "CLOCK_UNSAFE"
    HISTORY_QUOTA = "HISTORY_QUOTA"
    INTEGRITY = "GOVERNOR_INTEGRITY"
    POLICY_BINDING = "POLICY_BINDING"
    BUDGET = "BUDGET_EXCEEDED"
    STALE_EPOCH = "STALE_EPOCH"
    INVALID_KILL = "INVALID_KILL_STATE"
    INVALID_REQUEST = "INVALID_RESERVATION_REQUEST"
    MODEL_BINDING = "MODEL_BINDING_DENIED"
    IDEMPOTENCY = "IDEMPOTENCY_CONFLICT"
    KILL = "KILL_SWITCH"
    OPEN = "CIRCUIT_OPEN"
    HALF_OPEN = "HALF_OPEN_BUSY"
    REQUIRED = "RESERVATION_REQUIRED"
    STALE_RESERVATION = "STALE_RESERVATION_EPOCH"
    NO_DISPATCH_PROOF = "NO_DISPATCH_PROOF_REQUIRED"
    DISPATCH_MARKER = "DISPATCH_MARKER_REQUIRED"


class GovernorError(MemoryPatchError, ValueError):
    """Native transaction-compatible exception with a closed, public reason."""

    def __init__(self, reason):
        self.reason = GovernorReason(reason)
        super().__init__(ErrorCode.INVALID_REQUEST)
        self.args = (self.reason.value,)


def _deny(condition, code):
    if not condition:
        raise GovernorError(code)


def _amount(value):
    _deny(type(value) is int and 0 <= value <= MAX_AMOUNT, "INVALID_GOVERNOR_AMOUNT")
    return value


def _identity(value):
    _deny(
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,179}", value) is not None,
        "INVALID_GOVERNOR_IDENTITY",
    )


def _digest(value):
    _deny(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "INVALID_EVIDENCE_DIGEST",
    )


@dataclass(frozen=True, slots=True, repr=False)
class ReservationRequest:
    request_id: str
    task_id: str
    provider_id: str
    model_id: str
    request_digest: str
    money_nano: int
    risk_units: int

    def __post_init__(self):
        for value in (self.request_id, self.task_id, self.provider_id, self.model_id):
            _identity(value)
        _digest(self.request_digest)
        _amount(self.money_nano)
        _amount(self.risk_units)


def _plain(value):
    return json.loads(canonical_json_bytes(value))
