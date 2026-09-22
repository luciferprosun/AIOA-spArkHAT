"""Versioned mission data, bound to existing Core ownership, never authority.

JSON uses the existing MemoryPatch strict parser and canonical serialization.
Registries and owner scope are injected by Core, never resolved from a manifest.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contract import parse_request
from runtime.memory_patch.contracts.serialization import canonical_sha256, freeze_json

SCHEMA_VERSION = "aioa-mission-v1"
PROFILE = "nvidia-lite"
SCHEDULER_OWNER = "AgentRuntime"
MAX_MANIFEST_BYTES = 24000
ADAPTER_REFS = MappingProxyType(
    {
        "memory": "memory-patch-native-v1",
        "critic": "cpl-1plus3plus1-v1",
        "authority": "nonzero-native-v1",
        "model": "nvidia-build-unbound-v1",
        "scheduler": "lite-scheduler-contract-v1",
    }
)
POLICY_VERSIONS = MappingProxyType(
    {
        "mission": "nv01-controlled-v1",
        "authority": "nonzero-native-v1",
        "temporal": "temporal-resolution-policy-1a",
        "pheromone": "advisory-trail-v1",
    }
)
MODEL_PROFILE_REF = "nvidia-nemotron-unbound-v1"
SECRET_REFS = frozenset({"nvidia-build-key"})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)


class MissionError(ValueError):
    """Stable public codes, no raw caller data or dependency error text."""

    def __init__(self, code="INVALID_MANIFEST", *, status="INVALID", exit_code=2):
        super().__init__(code)
        self.code, self.status, self.exit_code = code, status, exit_code


def logical_id(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise MissionError()
    return value


def bounded_int(value, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise MissionError()
    return value


def id_tuple(values, *, maximum=32):
    if type(values) not in (list, tuple) or len(values) > maximum:
        raise MissionError()
    result = tuple(logical_id(v) for v in values)
    if len(result) != len(set(result)):
        raise MissionError("DUPLICATE_REFERENCE")
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class MissionBudget:
    max_model_calls: int = 0
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    max_cost_microusd: int = 0
    max_wall_seconds: int = 180
    max_episodes: int = 1

    def __post_init__(self):
        for name, lower, upper in (
            ("max_model_calls", 0, 5),
            ("max_input_tokens", 0, 32768),
            ("max_output_tokens", 0, 8192),
            ("max_cost_microusd", 0, 10000000),
            ("max_wall_seconds", 1, 3600),
            ("max_episodes", 1, 8),
        ):
            bounded_int(getattr(self, name), lower, upper)


@dataclass(frozen=True, slots=True, repr=False)
class MissionContext:
    """Trusted Core-supplied metadata, not a principal or approval mechanism."""

    owner_scope: OwnerScope | None = None
    registered_source_ids: frozenset[str] = frozenset()
    classification: str = "STATIC_CONFIG"

    def __post_init__(self):
        if self.owner_scope is not None and type(self.owner_scope) is not OwnerScope:
            raise MissionError("OWNER_CONTEXT_INVALID")
        if (
            type(self.registered_source_ids) is not frozenset
            or len(self.registered_source_ids) > 128
        ):
            raise MissionError("REGISTRY_INVALID")
        for value in self.registered_source_ids:
            logical_id(value)
        if self.classification not in {"STATIC_CONFIG", "CONTRACT_TEST"}:
            raise MissionError("CONTEXT_INVALID")


@dataclass(frozen=True, slots=True, repr=False)
class MissionManifest:
    mission_id: str
    owner_scope: OwnerScope
    manifest_revision: int
    source_ids: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION
    profile: str = PROFILE
    enabled: bool = False
    mode: str = "CONTROLLED"
    effects_enabled: bool = False
    model_profile_ref: str = MODEL_PROFILE_REF
    scheduler_owner: str = SCHEDULER_OWNER
    budget: MissionBudget = field(default_factory=MissionBudget)
    adapter_refs: object = field(default_factory=lambda: ADAPTER_REFS)
    policy_versions: object = field(default_factory=lambda: POLICY_VERSIONS)
    secret_refs: tuple[str, ...] = ()
    digest: str = field(init=False)

    def __post_init__(self):
        logical_id(self.mission_id)
        if type(self.owner_scope) is not OwnerScope:
            raise MissionError("OWNER_CONTEXT_INVALID")
        # Existing scope IDs retain their meaning; this JSON surface is narrower.
        for value in self.owner_scope.binding():
            logical_id(value)
        bounded_int(self.manifest_revision, 1, 2147483647)
        if self.schema_version != SCHEMA_VERSION or self.profile != PROFILE:
            raise MissionError("UNSUPPORTED_VERSION_OR_PROFILE")
        if type(self.enabled) is not bool or type(self.effects_enabled) is not bool:
            raise MissionError()
        if self.mode not in {"CONTROLLED", "AUTO_SCOPED"} or type(self.mode) is not str:
            raise MissionError()
        if self.effects_enabled:
            raise MissionError(
                "EFFECTS_NOT_IMPLEMENTED", status="POLICY_BLOCKED", exit_code=4
            )
        if self.scheduler_owner != SCHEDULER_OWNER:
            raise MissionError("SCHEDULER_OWNER_MISMATCH")
        if self.model_profile_ref != MODEL_PROFILE_REF:
            raise MissionError("UNREGISTERED_MODEL_PROFILE")
        if type(self.budget) is not MissionBudget:
            raise MissionError()
        for name, expected in (
            ("adapter_refs", ADAPTER_REFS),
            ("policy_versions", POLICY_VERSIONS),
        ):
            value = getattr(self, name)
            if not isinstance(value, (dict, MappingProxyType)) or dict(value) != dict(
                expected
            ):
                raise MissionError("UNREGISTERED_ADAPTER_OR_POLICY")
            object.__setattr__(self, name, freeze_json(dict(value)))
        object.__setattr__(self, "source_ids", id_tuple(self.source_ids))
        secret_refs = id_tuple(self.secret_refs, maximum=1)
        if set(secret_refs) - SECRET_REFS:
            raise MissionError("UNREGISTERED_SECRET_REFERENCE")
        object.__setattr__(self, "secret_refs", secret_refs)
        object.__setattr__(
            self, "digest", canonical_sha256(self, exclude_fields=("digest",))
        )

    def require_context(self, context):
        if type(context) is not MissionContext or context.owner_scope is None:
            raise MissionError(
                "OWNER_CONTEXT_UNAVAILABLE", status="UNAVAILABLE", exit_code=3
            )
        if self.owner_scope != context.owner_scope:
            raise MissionError(
                "OWNER_SCOPE_MISMATCH", status="POLICY_BLOCKED", exit_code=4
            )
        if set(self.source_ids) - context.registered_source_ids:
            raise MissionError("UNREGISTERED_SOURCE")

    def require_controlled(self):
        if self.mode == "AUTO_SCOPED":
            raise MissionError(
                "AUTO_SCOPED_NOT_IMPLEMENTED", status="POLICY_BLOCKED", exit_code=4
            )


def parse_manifest(text, context):
    """Strict v1 schema + Core binding; this does not admit a mission to run."""
    try:
        value = parse_request(text)
        required = {
            "schema_version",
            "mission_id",
            "owner_scope",
            "manifest_revision",
            "source_ids",
        }
        allowed = set(MissionManifest.__dataclass_fields__) - {"digest"}
        if required - value.keys() or value.keys() - allowed:
            raise MissionError()
        owner = value.pop("owner_scope")
        if type(owner) is not dict or set(owner) != {
            "tenant_id",
            "owner_id",
            "space_id",
            "slot_id",
        }:
            raise MissionError()
        for identity in owner.values():
            logical_id(identity)
        budget = value.pop("budget", {})
        if (
            type(budget) is not dict
            or budget.keys() - MissionBudget.__dataclass_fields__.keys()
        ):
            raise MissionError()
        manifest = MissionManifest(
            owner_scope=OwnerScope(**owner), budget=MissionBudget(**budget), **value
        )
        manifest.require_context(context)
        manifest.require_controlled()
        return manifest
    except MissionError:
        raise
    except (TypeError, ValueError, RecursionError, OverflowError, UnicodeError):
        raise MissionError() from None


def compare_manifest_revision(previous, current):
    """Pure idempotency check; no new store and no implicit revision upgrade."""
    if type(previous) is not MissionManifest or type(current) is not MissionManifest:
        raise MissionError()
    first = (previous.owner_scope, previous.mission_id, previous.manifest_revision)
    second = (current.owner_scope, current.mission_id, current.manifest_revision)
    if first != second:
        raise MissionError("IDENTITY_MISMATCH")
    if previous.digest != current.digest:
        raise MissionError("CONFLICT", status="CONFLICT", exit_code=4)
    return "DUPLICATE"


@dataclass(frozen=True, slots=True)
class MissionTrace:
    """Links existing trace/run IDs; never generates or replaces a legacy ID."""

    trace_id: str
    mission_id: str
    episode_id: str
    event_id: str
    model_profile_ref: str
    manifest_revision: int
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self):
        for name in (
            "trace_id",
            "mission_id",
            "episode_id",
            "event_id",
            "model_profile_ref",
        ):
            logical_id(getattr(self, name))
        bounded_int(self.manifest_revision, 1, 2147483647)
        object.__setattr__(self, "evidence_refs", id_tuple(self.evidence_refs))

    def require_manifest(self, manifest):
        if (self.mission_id, self.manifest_revision, self.model_profile_ref) != (
            manifest.mission_id,
            manifest.manifest_revision,
            manifest.model_profile_ref,
        ):
            raise MissionError("TRACE_BINDING_MISMATCH")


def contract_fixture_context():
    """Synthetic ownership metadata only; no principal, approval, database or key."""
    return MissionContext(
        OwnerScope(
            "synthetic-tenant", "synthetic-owner", "synthetic-space", "synthetic-slot"
        ),
        frozenset({"nv01.synthetic.source"}),
        "CONTRACT_TEST",
    )


def contract_fixture_manifest(*, enabled=False):
    return MissionManifest(
        "nv01-synthetic-mission",
        contract_fixture_context().owner_scope,
        1,
        ("nv01.synthetic.source",),
        enabled=enabled,
    )
