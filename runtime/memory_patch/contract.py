"""Dependency-free discovery and immutable, explicitly supplied Core settings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType

from runtime.core_admission import AdmissionError, Capability, LocalOwnerAssignment

MODULE_ID = "memory-patch"
CONTRACT_VERSION = "memory-patch-native-v1"
OPERATOR_INTENT = "memory-patch-operator-v1"


@dataclass(frozen=True, slots=True, repr=False)
class MemoryPatchConfig:
    enabled: bool = False
    assignment: LocalOwnerAssignment | None = None

    def __post_init__(self):
        if type(self.enabled) is not bool or (
            self.assignment is not None
            and type(self.assignment) is not LocalOwnerAssignment
        ):
            raise AdmissionError()


def snapshot_config(value=None):
    if value is None:
        return MemoryPatchConfig()
    if type(value) is not MemoryPatchConfig:
        raise AdmissionError()
    return MemoryPatchConfig(value.enabled, value.assignment)


def module_descriptor(config=None, *, configured=False, closed=False):
    config = snapshot_config(config)
    return {
        "module_id": MODULE_ID,
        "contract_version": CONTRACT_VERSION,
        "available": not closed,
        "enabled": config.enabled and not closed,
        "backend_status": "CLOSED"
        if closed
        else "CONFIGURED"
        if configured
        else "UNCONFIGURED",
        "reason_code": "MODULE_CLOSED"
        if closed
        else "MODULE_DISABLED"
        if not config.enabled
        else "OWNER_DENIED"
        if config.assignment is None
        else "READY"
        if configured
        else "BACKEND_UNCONFIGURED",
    }


# The existing trusted Core command/HTTP admission selects exactly one capability.
# These names are never interpreted as authority in a model response or body flag.
OPERATION_CAPABILITIES = MappingProxyType(
    {
        "read": Capability.READ,
        "list": Capability.READ,
        "trace": Capability.READ,
        "recover": Capability.READ,
        "retrieve": Capability.READ,
        "answer": Capability.READ,
        "candidate": Capability.CANDIDATE,
        "critic-candidate": Capability.CANDIDATE,
        "propose": Capability.PROPOSE,
        "bind-evidence": Capability.PROPOSE,
        "validate": Capability.VALIDATE,
        "await-approval": Capability.VALIDATE,
        "challenge": Capability.OWNER_APPROVAL,
        "decision": Capability.OWNER_APPROVAL,
        "commit": Capability.COMMIT,
        "activate": Capability.ACTIVATE,
        "slot-create": Capability.MANAGE,
        "slot-configure": Capability.MANAGE,
        "slot-state": Capability.MANAGE,
        "revoke": Capability.MANAGE,
        "supersede": Capability.MANAGE,
        "export": Capability.MANAGE,
        "sharing": Capability.MANAGE,
        "review-open": Capability.MANAGE,
        "review-queue": Capability.REVIEW,
        "review-claim": Capability.REVIEW,
        "review-decision": Capability.REVIEW,
        "publish": Capability.MANAGE,
        "initialize-publication": Capability.MANAGE,
        "migration-plan": Capability.MIGRATE,
        "migrate": Capability.MIGRATE,
    }
)


def operation_capability(operation):
    if type(operation) is not str or operation not in OPERATION_CAPABILITIES:
        raise AdmissionError()
    return OPERATION_CAPABILITIES[operation]


def parse_request(text):
    """One strict CLI JSON object; HTTP has the same framing in the Core handler."""
    if not isinstance(text, str) or len(text.encode("utf-8")) > 24000:
        raise ValueError("INVALID_REQUEST")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("INVALID_REQUEST")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("INVALID_REQUEST")

    value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    if type(value) is not dict:
        raise ValueError("INVALID_REQUEST")
    return value
