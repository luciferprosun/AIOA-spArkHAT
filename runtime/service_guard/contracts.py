"""Bounded data contracts. Neither model proposals nor receipts grant authority."""

from collections.abc import Mapping
from dataclasses import dataclass

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import logical_id

OUTPUT_SCHEMA = "aioa-service-proposal-v1"
EFFECT = "SET_MAINTENANCE"


class GuardError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse_proposal(value):
    keys = {"target_id", "observed_mode", "expected_target_revision",
            "proposed_effect", "reason_summary", "needs_attention"}
    if (not isinstance(value, Mapping) or set(value) != keys
            or type(value["target_id"]) is not str
            or type(value["observed_mode"]) is not str
            or value["observed_mode"] not in {"NORMAL", "MAINTENANCE"}
            or type(value["expected_target_revision"]) is not int
            or not 1 <= value["expected_target_revision"] <= 2**53
            or type(value["proposed_effect"]) is not str
            or value["proposed_effect"] not in {EFFECT, "NONE"}
            or type(value["reason_summary"]) is not str
            or not 1 <= len(value["reason_summary"]) <= 400
            or type(value["needs_attention"]) is not bool):
        raise GuardError("INVALID_SERVICE_PROPOSAL")
    try:
        logical_id(value["target_id"])
    except ValueError:
        raise GuardError("INVALID_SERVICE_PROPOSAL") from None
    return dict(value)


def actor_contract():
    return {"type": "object", "additionalProperties": False,
            "required": ["target_id", "observed_mode", "expected_target_revision",
                         "proposed_effect", "reason_summary", "needs_attention"],
            "properties": {
                "target_id": {"type": "string"},
                "observed_mode": {"enum": ["NORMAL", "MAINTENANCE"]},
                "expected_target_revision": {"type": "integer", "minimum": 1},
                "proposed_effect": {"enum": [EFFECT, "NONE"]},
                "reason_summary": {"type": "string", "minLength": 1, "maxLength": 400},
                "needs_attention": {"type": "boolean"}}}


@dataclass(frozen=True, slots=True)
class ServicePolicy:
    scope: OwnerScope
    target_id: str
    revision: int = 1
    effect_class: str = EFFECT
    max_effects: int = 1
    max_validity_seconds: int = 600

    def __post_init__(self):
        if (type(self.scope) is not OwnerScope or type(self.revision) is not int
                or self.revision < 1 or self.effect_class != EFFECT
                or type(self.max_effects) is not int or self.max_effects != 1
                or type(self.max_validity_seconds) is not int
                or not 1 <= self.max_validity_seconds <= 600):
            raise GuardError("INVALID_SERVICE_POLICY")
        logical_id(self.target_id)

    @property
    def digest(self):
        return canonical_sha256(self)


def check_observation(value, policy):
    if (type(value) is not dict
            or set(value) != {"target_id", "scope", "mode", "revision", "effect_count"}
            or value["target_id"] != policy.target_id
            or value["scope"] != list(policy.scope.binding())
            or type(value["mode"]) is not str
            or value["mode"] not in {"NORMAL", "MAINTENANCE"}
            or type(value["revision"]) is not int or not 1 <= value["revision"] <= 2**53
            or type(value["effect_count"]) is not int
            or not 0 <= value["effect_count"] < value["revision"]):
        raise GuardError("TARGET_IDENTITY_OR_STATE_MISMATCH")
    return value
