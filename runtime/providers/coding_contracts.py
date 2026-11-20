"""Exact inert coding profile data; validation grants no execution authority."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime

from runtime.memory_patch.contracts.serialization import (
    canonical_json_bytes,
    canonical_sha256,
)

_SCHEMA = "aioa.selected-coding-profile.v2"
_PRICE_SCHEMA = "aioa.coding-pricing-evidence.v1"
# A bounded data envelope, separate from the profile's provider payload limits.
_MAX_PROFILE_BYTES = 16384
_FIELDS = frozenset((
    "schema", "selection_id", "selection_revision", "backend", "provider_id",
    "model_id", "endpoint", "adapter_contract_digest", "host_source", "limits",
    "pricing_evidence", "auth_ref", "protocol_options", "capability_digest",
))
_HOST_FIELDS = frozenset(("source_sha", "capsule_digest"))
_LIMITS = {
    "max_input_bytes": (1, 16384), "max_input_units": (1, 16896),
    "max_output_tokens": (1, 4096), "max_response_bytes": (1, 65536),
    "timeout_seconds": (1, 15), "max_events": (3, 64),
}
_PRICE_FIELDS = frozenset((
    "schema", "provider_id", "model_id", "endpoint_digest", "evidence_digest",
    "checked_at_utc", "valid_until_utc", "currency", "input_nano_usd_per_million",
    "output_nano_usd_per_million", "fixed_nano_usd", "reasoning_accounting",
))
_PAIRS = {
    "CODEX": ("codex_app_server", "owned-stdio://codex-app-server-0.167.0",
              "CODEX_OWNER_APPROVED_ISOLATED_AUTH_REF"),
    "META_MUSE": ("meta_model_api", "https://api.meta.ai/v1/chat/completions",
                  "MUSE_EXISTING_PRIVATE_KEY_REF"),
    "OPENROUTER": ("openrouter", "https://openrouter.ai/api/v1/chat/completions",
                   "OPENROUTER_SELECTED_ENV_REF"),
}
_OPTIONS = {
    "CODEX": frozenset(("model_provider", "effort", "binary_sha256",
                        "schema_manifest_sha256", "isolation_profile_digest")),
    "META_MUSE": frozenset(("api", "reasoning_effort", "output_token_parameter")),
    "OPENROUTER": frozenset(("api", "upstream_endpoint_slug", "allow_fallbacks",
                             "require_parameters", "output_token_parameter", "reasoning_effort")),
}
_EFFORTS = frozenset(("minimal", "low", "medium", "high", "xhigh", "max"))
_HEX32 = re.compile(r"[0-9a-f]{32}", re.ASCII)
_HEX40 = re.compile(r"[0-9a-f]{40}", re.ASCII)
_HEX64 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_LOGICAL_PROVIDER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}", re.ASCII)
_FULL_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)+", re.ASCII)
_UTC = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", re.ASCII)


class CodingContractError(ValueError):
    """Fixed nonsecret coding boundary error code."""

    def __init__(self, code: str = "CODING_PROFILE_DENIED") -> None:
        self.code = code
        super().__init__(code)


def _require(condition: bool) -> None:
    if not condition:
        raise CodingContractError("CODING_PROFILE_DENIED")


def _snapshot(value, depth=0):
    """Copy only the finite profile's plain JSON types before validation/hash."""
    _require(depth <= 3)
    if type(value) is dict:
        result = {}
        for key, item in value.items():
            _require(type(key) is str and len(key) <= 64)
            result[key] = _snapshot(item, depth + 1)
        return result
    if type(value) is str:
        _require(len(value.encode("utf-8")) <= 4096)
        return value
    _require(value is None or type(value) in (bool, int))
    return value


def _fields(value, fields) -> None:
    _require(type(value) is dict and value.keys() == fields)


def _match(value, pattern) -> None:
    _require(type(value) is str and pattern.fullmatch(value) is not None)


def _integer(value, low, high=None) -> None:
    _require(type(value) is int and value >= low and (high is None or value <= high))


def _utc(value):
    _match(value, _UTC)
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise CodingContractError("CODING_PROFILE_DENIED") from None


def _full_slug(value) -> None:
    _match(value, _FULL_SLUG)
    _require(len(value) <= 256 and not {part.lower() for part in value.split("/")} & {"auto", "router", "free"})


def _validate(body) -> None:
    _fields(body, _FIELDS)
    _require(body["schema"] == _SCHEMA)
    _match(body["selection_id"], _HEX32)
    _integer(body["selection_revision"], 1)
    backend = body["backend"]
    _require(type(backend) is str and backend in _PAIRS)
    provider, endpoint, auth_ref = _PAIRS[backend]
    _require(body["provider_id"] == provider and body["endpoint"] == endpoint and body["auth_ref"] == auth_ref)
    _match(body["adapter_contract_digest"], _HEX64)
    _match(body["capability_digest"], _HEX64)
    host = body["host_source"]
    _fields(host, _HOST_FIELDS)
    _match(host["source_sha"], _HEX40)
    _match(host["capsule_digest"], _HEX64)
    limits = body["limits"]
    _fields(limits, _LIMITS.keys())
    for name, (low, high) in _LIMITS.items():
        _integer(limits[name], low, high)
    price = body["pricing_evidence"]
    _fields(price, _PRICE_FIELDS)
    _require(price["schema"] == _PRICE_SCHEMA and price["provider_id"] == provider
             and price["model_id"] == body["model_id"] and price["currency"] == "USD")
    _require(price["endpoint_digest"] == canonical_sha256(endpoint))
    _match(price["evidence_digest"], _HEX64)
    checked, until = _utc(price["checked_at_utc"]), _utc(price["valid_until_utc"])
    _require(checked < until)
    for name in ("input_nano_usd_per_million", "output_nano_usd_per_million", "fixed_nano_usd"):
        _integer(price[name], 0)
    _require(type(price["reasoning_accounting"]) is str
             and price["reasoning_accounting"] in ("BOUNDED_IN_OUTPUT", "UNSUPPORTED"))
    options = body["protocol_options"]
    _fields(options, _OPTIONS[backend])
    if backend == "CODEX":
        _require(body["model_id"] == "gpt-6.1-sol" and options["effort"] == "max")
        # This syntax is data only; a reviewed fixed literal/proof is still
        # required at a future shared gate before any broker/transport exists.
        _match(options["model_provider"], _LOGICAL_PROVIDER)
        for name in ("binary_sha256", "schema_manifest_sha256", "isolation_profile_digest"):
            _match(options[name], _HEX64)
    else:
        _require(options["api"] == "CHAT_COMPLETIONS_V1")
        effort = options["reasoning_effort"]
        _require((backend == "OPENROUTER" and effort is None)
                 or (type(effort) is str and effort in _EFFORTS))
        if backend == "META_MUSE":
            _require(body["model_id"] == "muse-spark-1.3"
                     and options["output_token_parameter"] == "max_completion_tokens")
        else:
            _full_slug(body["model_id"])
            _full_slug(options["upstream_endpoint_slug"])
            _require(options["allow_fallbacks"] is False and options["require_parameters"] is True)
            _require(type(options["output_token_parameter"]) is str
                     and options["output_token_parameter"] in ("max_tokens", "max_completion_tokens"))


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _number_denied(_value):
    raise CodingContractError("CODING_PROFILE_DENIED")


@dataclass(frozen=True, slots=True, init=False)
class SelectedCodingProfileV2:
    """Immutable canonical profile snapshot, with no live admission or I/O."""

    _wire: bytes = field(repr=False)
    _digest: str

    def __init__(self, value: dict) -> None:
        try:
            _require(type(value) is dict)
            body = _snapshot(value)
            _validate(body)
            wire = canonical_json_bytes(body)
            _require(1 <= len(wire) <= _MAX_PROFILE_BYTES)
            digest = canonical_sha256(body)
        except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError, RuntimeError):
            raise CodingContractError("CODING_PROFILE_DENIED") from None
        object.__setattr__(self, "_wire", wire)
        object.__setattr__(self, "_digest", digest)

    @classmethod
    def from_dict(cls, value: dict) -> SelectedCodingProfileV2:
        return cls(value)

    @classmethod
    def from_json(cls, raw: bytes) -> SelectedCodingProfileV2:
        _require(type(raw) is bytes and 1 <= len(raw) <= _MAX_PROFILE_BYTES)
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                              parse_float=_number_denied, parse_constant=_number_denied)
            return cls.from_dict(body)
        except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
            raise CodingContractError("CODING_PROFILE_DENIED") from None

    def to_dict(self) -> dict:
        """Return a detached exact wire body, including every null and option."""
        return json.loads(self._wire)

    @property
    def selection_digest(self) -> str:
        return self._digest


_CHOICE_FIELDS = frozenset((
    "schema", "selection_id", "selection_revision", "backend", "model_id",
    "selection_digest",
))
_POLICY_FIELDS = frozenset((
    "schema", "task_digest", "selection_digest", "max_model_calls", "max_repairs",
    "max_total_input_units", "max_total_output_tokens", "max_total_cost_nano_usd",
    "model_risk_units", "issued_at", "expires_at",
))
_BINDING_FIELDS = frozenset((
    "schema", "task_digest", "selection", "selection_digest", "run_policy",
    "run_policy_digest", "selected_by_session_digest", "selected_at",
))


def _choice_snapshot(value):
    body = _snapshot(value)
    _fields(body, _CHOICE_FIELDS)
    _require(body["schema"] == "aioa.coding-backend-choice.v1")
    _match(body["selection_id"], _HEX32)
    _integer(body["selection_revision"], 1)
    _require(type(body["backend"]) is str and body["backend"] in _PAIRS)
    if body["backend"] == "CODEX":
        _require(body["model_id"] == "gpt-6.1-sol")
    elif body["backend"] == "META_MUSE":
        _require(body["model_id"] == "muse-spark-1.3")
    else:
        _full_slug(body["model_id"])
    _match(body["selection_digest"], _HEX64)
    return body


def _policy_snapshot(value):
    body = _snapshot(value)
    _fields(body, _POLICY_FIELDS)
    _require(body["schema"] == "aioa.coding-run-policy.v1")
    _match(body["task_digest"], _HEX64)
    _match(body["selection_digest"], _HEX64)
    _integer(body["max_model_calls"], 1, 3)
    calls = body["max_model_calls"]
    _integer(body["max_repairs"], 0, min(2, calls - 1))
    _integer(body["max_total_input_units"], 1, calls * 16896)
    _integer(body["max_total_output_tokens"], 1, calls * 4096)
    for name in ("max_total_cost_nano_usd", "model_risk_units"):
        _integer(body[name], 1, 2**63 - 1)
    for name in ("issued_at", "expires_at"):
        _integer(body[name], 1, 2**53)
    _require(body["issued_at"] < body["expires_at"] <= body["issued_at"] + 300)
    return body


def _coding_snapshot(value, snapshot, maximum):
    """Capture one of the three closed inert DTOs; no authority or I/O."""
    try:
        _require(type(value) is dict)
        body = snapshot(value)
        wire = canonical_json_bytes(body)
        _require(1 <= len(wire) <= maximum)
        return wire, canonical_sha256(body)
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError, RuntimeError):
        raise CodingContractError("CODING_PROFILE_DENIED") from None


def _coding_json(raw, maximum):
    _require(type(raw) is bytes and 1 <= len(raw) <= maximum)
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_float=_number_denied, parse_constant=_number_denied)
    except (ValueError, TypeError, OverflowError, UnicodeError, RecursionError):
        raise CodingContractError("CODING_PROFILE_DENIED") from None


@dataclass(frozen=True, slots=True, init=False)
class CodingBackendChoiceV1:
    """An exact reference to finite host data, never a provider capability."""

    _wire: bytes = field(repr=False)
    _digest: str

    def __init__(self, value: dict) -> None:
        wire, digest = _coding_snapshot(value, _choice_snapshot, 4096)
        object.__setattr__(self, "_wire", wire)
        object.__setattr__(self, "_digest", digest)

    @classmethod
    def from_dict(cls, value: dict) -> CodingBackendChoiceV1:
        return cls(value)

    @classmethod
    def from_json(cls, raw: bytes) -> CodingBackendChoiceV1:
        return cls(_coding_json(raw, 4096))

    def to_dict(self) -> dict:
        return json.loads(self._wire)

    @property
    def digest(self) -> str:
        return self._digest


@dataclass(frozen=True, slots=True, init=False)
class CodingRunPolicyV1:
    """Bounded run data; monetary and risk limits grant no spending approval."""

    _wire: bytes = field(repr=False)
    _digest: str

    def __init__(self, value: dict) -> None:
        wire, digest = _coding_snapshot(value, _policy_snapshot, 4096)
        object.__setattr__(self, "_wire", wire)
        object.__setattr__(self, "_digest", digest)

    @classmethod
    def from_dict(cls, value: dict) -> CodingRunPolicyV1:
        return cls(value)

    @classmethod
    def from_json(cls, raw: bytes) -> CodingRunPolicyV1:
        return cls(_coding_json(raw, 4096))

    def to_dict(self) -> dict:
        return json.loads(self._wire)

    @property
    def digest(self) -> str:
        return self._digest


def _binding_snapshot(value):
    # Snapshot each finite nested field independently. The S1 profile's depth
    # and byte envelope stay unchanged when embedded in the larger witness.
    _fields(value, _BINDING_FIELDS)
    body = {name: _snapshot(value[name]) for name in _BINDING_FIELDS
            if name not in ("selection", "run_policy")}
    body["selection"] = SelectedCodingProfileV2.from_dict(value["selection"]).to_dict()
    body["run_policy"] = CodingRunPolicyV1.from_dict(value["run_policy"]).to_dict()
    _require(body["schema"] == "aioa.coding-backend-binding.v1")
    for name in ("task_digest", "selection_digest", "run_policy_digest", "selected_by_session_digest"):
        _match(body[name], _HEX64)
    _integer(body["selected_at"], 1, 2**53)
    policy = body["run_policy"]
    _require(body["selection_digest"] == canonical_sha256(body["selection"])
             and body["run_policy_digest"] == canonical_sha256(policy)
             and policy["task_digest"] == body["task_digest"]
             and policy["selection_digest"] == body["selection_digest"]
             and policy["issued_at"] <= body["selected_at"] < policy["expires_at"])
    return body


@dataclass(frozen=True, slots=True, init=False)
class CodingBackendBindingV1:
    """The full immutable historical choice; no approval or execution claim."""

    _wire: bytes = field(repr=False)
    _digest: str

    def __init__(self, value: dict) -> None:
        wire, digest = _coding_snapshot(value, _binding_snapshot, 24576)
        object.__setattr__(self, "_wire", wire)
        object.__setattr__(self, "_digest", digest)

    @classmethod
    def from_dict(cls, value: dict) -> CodingBackendBindingV1:
        return cls(value)

    @classmethod
    def from_json(cls, raw: bytes) -> CodingBackendBindingV1:
        return cls(_coding_json(raw, 24576))

    def to_dict(self) -> dict:
        return json.loads(self._wire)

    @property
    def digest(self) -> str:
        return self._digest


@dataclass(frozen=True, slots=True, init=False)
class CodingBackendRegistry:
    """Finite trusted DATA, captured as canonical bytes with no live authority."""

    _profiles: tuple[bytes, ...] = field(repr=False)

    def __init__(self, profiles: tuple[SelectedCodingProfileV2, ...]) -> None:
        _require(type(profiles) is tuple and 1 <= len(profiles) <= 16)
        entries, identities = [], set()
        for profile in profiles:
            _require(type(profile) is SelectedCodingProfileV2)
            captured = SelectedCodingProfileV2.from_dict(profile.to_dict())
            _require(captured.selection_digest == profile.selection_digest)
            body = captured.to_dict()
            key = (body["selection_id"], body["selection_revision"])
            _require(key not in identities)
            identities.add(key)
            entries.append(canonical_json_bytes(body))
        object.__setattr__(self, "_profiles", tuple(entries))

    def _host_sources(self):
        return tuple((body["host_source"]["source_sha"], body["host_source"]["capsule_digest"])
                     for body in (json.loads(wire) for wire in self._profiles))

    def resolve(self, choice: CodingBackendChoiceV1) -> SelectedCodingProfileV2:
        _require(type(choice) is CodingBackendChoiceV1)
        selected = CodingBackendChoiceV1.from_dict(choice.to_dict()).to_dict()
        for wire in self._profiles:
            profile = SelectedCodingProfileV2.from_json(wire)
            body = profile.to_dict()
            if (body["selection_id"], body["selection_revision"]) == (
                    selected["selection_id"], selected["selection_revision"]):
                _require(body["backend"] == selected["backend"]
                         and body["model_id"] == selected["model_id"]
                         and profile.selection_digest == selected["selection_digest"])
                return profile
        raise CodingContractError("CODING_PROFILE_DENIED")
