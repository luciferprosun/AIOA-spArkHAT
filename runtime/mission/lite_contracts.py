"""NV-02 immutable read-only profile; Core retains ownership and configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contract import parse_request
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.mission.contracts import MissionContext, MissionError, bounded_int, logical_id

MODEL = "nvidia/nemotron-3.5-lightning-30b-a3b"
PROFILE = "aioa-lite-agent-v1"


@dataclass(frozen=True, slots=True)
class LiteBudget:
    max_requests_per_hour: int = 4
    max_hourly_units: int = 32768
    max_retry: int = 1
    max_output_tokens: int = 256
    max_input_bytes: int = 4096
    max_response_bytes: int = 16384
    request_timeout_seconds: int = 30
    retry_delay_seconds: int = 2
    max_reservations: int = 1024

    def __post_init__(self):
        bounds = {
            "max_requests_per_hour": (1, 60), "max_hourly_units": (1, 1000000),
            "max_retry": (0, 2), "max_output_tokens": (1, 2048),
            "max_input_bytes": (256, 16384), "max_response_bytes": (512, 24000),
            "request_timeout_seconds": (1, 120), "retry_delay_seconds": (1, 60),
            "max_reservations": (1, 10000),
        }
        for name, limits in bounds.items():
            bounded_int(getattr(self, name), *limits)


@dataclass(frozen=True, slots=True)
class LiteCadence:
    interval_seconds: int = 60
    freshness_seconds: int = 120
    interpretation_interval_seconds: int = 0
    max_evidence_events: int = 256

    def __post_init__(self):
        for name, limits in {
            "interval_seconds": (1, 3600), "freshness_seconds": (1, 86400),
            "interpretation_interval_seconds": (0, 86400),
            "max_evidence_events": (16, 10000),
        }.items():
            bounded_int(getattr(self, name), *limits)


@dataclass(frozen=True, slots=True, repr=False)
class LiteProfile:
    owner_scope: OwnerScope
    watch_id: str
    observation_source_ref: str
    enabled: bool = False
    profile_id: str = PROFILE
    manifest_version: int = 1
    manifest_revision: int = 1
    runtime_mode: str = "LITE"
    provider_id: str = "nvidia"
    model_id: str = MODEL
    scheduler_policy_ref: str = "lite-fixed-cadence-v1"
    budget_policy_ref: str = "lite-durable-units-v1"
    freshness_policy_ref: str = "lite-change-gate-v1"
    max_queue_depth: int = 2
    max_concurrent_inference: int = 1
    live_mutations: bool = False
    memory_mode: str = "OFF"
    memory_profile_digest: str | None = None
    cpl_profile_digest: str | None = None
    dynamics_profile_digest: str | None = None
    cpl_mode: str = "OFF"
    auto_mode: str = "DISABLED"
    dvm_mode: str = "OFF"
    pheromone_mode: str = "OFF"
    budget: LiteBudget = field(default_factory=LiteBudget)
    cadence: LiteCadence = field(default_factory=LiteCadence)
    digest: str = field(init=False)

    def __post_init__(self):
        if type(self.owner_scope) is not OwnerScope:
            raise MissionError("OWNER_CONTEXT_INVALID")
        for value in (*self.owner_scope.binding(), self.watch_id, self.observation_source_ref):
            logical_id(value)
        bounded_int(self.manifest_revision, 1, 2147483647)
        bounded_int(self.max_queue_depth, 1, 8)
        if type(self.enabled) is not bool or self.live_mutations is not False:
            raise MissionError("LITE_READONLY_REQUIRED")
        fixed = {
            "profile_id": PROFILE, "manifest_version": 1, "runtime_mode": "LITE",
            "provider_id": "nvidia", "max_concurrent_inference": 1,
            "auto_mode": "DISABLED", "scheduler_policy_ref": "lite-fixed-cadence-v1",
            "budget_policy_ref": "lite-durable-units-v1",
            "freshness_policy_ref": "lite-change-gate-v1",
        }
        for name, expected in fixed.items():
            value = getattr(self, name)
            if type(value) is not type(expected) or value != expected:
                raise MissionError("UNSUPPORTED_LITE_CONFIGURATION")
        if self.model_id != MODEL or type(self.model_id) is not str:
            raise MissionError("MODEL_NOT_FOUND")
        for name in ("memory_mode", "cpl_mode", "dvm_mode", "pheromone_mode"):
            value = getattr(self, name)
            allowed = {"OFF", "SHADOW", "ACTIVE"}
            if type(value) is not str or value not in allowed:
                raise MissionError("LITE_READONLY_REQUIRED")
        if self.memory_profile_digest is not None:
            from runtime.memory_patch.contracts.serialization import require_sha256_hex
            require_sha256_hex(self.memory_profile_digest, "memory profile")
            if self.memory_mode == "OFF":
                raise MissionError("MEMORY_MODE_MISMATCH")
        if self.memory_mode == "ACTIVE" and self.memory_profile_digest is None:
            raise MissionError("MEMORY_PROFILE_REQUIRED")
        if self.cpl_profile_digest is not None:
            from runtime.memory_patch.contracts.serialization import require_sha256_hex
            require_sha256_hex(self.cpl_profile_digest, "CPL profile")
            if self.cpl_mode == "OFF":
                raise MissionError("CPL_MODE_MISMATCH")
        if self.cpl_mode == "ACTIVE" and self.cpl_profile_digest is None:
            raise MissionError("CPL_PROFILE_REQUIRED")
        if self.dynamics_profile_digest is not None:
            from runtime.memory_patch.contracts.serialization import require_sha256_hex
            require_sha256_hex(self.dynamics_profile_digest, "dynamics profile")
            if self.dvm_mode == "OFF" or self.dvm_mode != self.pheromone_mode:
                raise MissionError("DYNAMICS_MODE_MISMATCH")
        if "ACTIVE" in {self.dvm_mode, self.pheromone_mode} and self.dynamics_profile_digest is None:
            raise MissionError("DYNAMICS_PROFILE_REQUIRED")
        if type(self.budget) is not LiteBudget or type(self.cadence) is not LiteCadence:
            raise MissionError("INVALID_LITE_POLICY")
        # Preserve NV02 manifest identity when the optional integration is absent.
        excluded = ("digest",) + tuple(name for name in ("memory_profile_digest", "cpl_profile_digest", "dynamics_profile_digest") if getattr(self, name) is None)
        object.__setattr__(self, "digest", canonical_sha256(self, exclude_fields=excluded))

    def require_context(self, context):
        if type(context) is not MissionContext or context.owner_scope is None:
            raise MissionError("OWNER_CONTEXT_UNAVAILABLE")
        if self.owner_scope != context.owner_scope:
            raise MissionError("OWNER_SCOPE_MISMATCH")
        if self.observation_source_ref not in context.registered_source_ids:
            raise MissionError("UNREGISTERED_SOURCE")


def parse_lite_profile(text, context):
    try:
        value = parse_request(text)
        required = {"owner_scope", "watch_id", "observation_source_ref", "manifest_version", "profile_id"}
        allowed = LiteProfile.__dataclass_fields__.keys() - {"digest"}
        if required - value.keys() or value.keys() - allowed:
            raise MissionError("INVALID_LITE_MANIFEST")
        owner = value.pop("owner_scope")
        if type(owner) is not dict or set(owner) != {"tenant_id", "owner_id", "space_id", "slot_id"}:
            raise MissionError("OWNER_CONTEXT_INVALID")
        budget, cadence = value.pop("budget", {}), value.pop("cadence", {})
        if type(budget) is not dict or type(cadence) is not dict:
            raise MissionError("INVALID_LITE_POLICY")
        profile = LiteProfile(owner_scope=OwnerScope(**owner), budget=LiteBudget(**budget),
                              cadence=LiteCadence(**cadence), **value)
        profile.require_context(context)
        return profile
    except MissionError:
        raise
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError):
        raise MissionError("INVALID_LITE_MANIFEST") from None


@dataclass(frozen=True, slots=True)
class ObservationSnapshot:
    source_id: str
    source_revision: str
    observed_at: int
    fresh_until: int
    health: str
    value: str
    material_change: bool
    change_reason: str
    content_digest: str = field(init=False)

    def __post_init__(self):
        logical_id(self.source_id)
        logical_id(self.source_revision)
        bounded_int(self.observed_at, 0, 2**53)
        bounded_int(self.fresh_until, self.observed_at, 2**53)
        if (self.health not in {"OK", "UNCERTAIN", "DOWN"}
                or type(self.value) is not str or len(self.value.encode("utf-8")) > 512
                or type(self.material_change) is not bool
                or self.change_reason not in {"BASELINE", "STABLE", "MATERIAL_CHANGE"}):
            raise MissionError("INVALID_OBSERVATION")
        object.__setattr__(self, "content_digest", canonical_sha256({"health": self.health, "value": self.value}))


class ObservationPort(Protocol):
    def observe(self, now: int, previous_digest: str | None, freshness_seconds: int) -> ObservationSnapshot: ...


class CadencePolicyPort(Protocol):
    """Future advisory port; NV-02 never uses its output to control time."""
    def shadow(self, signal: str) -> None: ...


class SalienceHintPort(Protocol):
    """Future advisory port; no production deposits or authority changes."""
    def shadow(self, signal: str) -> None: ...
