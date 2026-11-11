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
