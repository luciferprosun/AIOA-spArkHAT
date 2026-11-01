"""OFFLINE Meta Model API provider-plan adapter (META-P2-01).

Stdlib-only, hermetic, no network. Reuses the existing OpenAI-compatible
provider interface shape WITHOUT calling its network ``generate()``; all
results are fixture/mock only. No token, no Authorization header, no
urllib/urlopen or other sockets anywhere in this module.

Binding (owner scope digest, source SHA, task digest) comes ONLY from the
trusted host call arguments, never from model output. Budget/timeout fields
are DESCRIPTIVE ONLY (preflight labels, not a hard billing cap); no API
spend is performed. ``dispatch_allowed`` is always False.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from runtime.providers.openai_compatible import OpenAICompatibleProvider

from .contracts import BrowserTaskV1, MetaContractError, _hash
from .muse_plan import MUSE_MODEL_ID, parse_muse_plan

OFFLINE_MODEL = "muse-spark-1.3"
OFFLINE_BASE_URL = "https://api.meta.ai/v1"
OFFLINE_ENVELOPE_SCHEMA = "aioa.meta.offline-provider.v1"

MAX_INPUT_CHARS = 2000
MAX_OUTPUT_TOKENS = 512
MAX_TIMEOUT_S = 15
MAX_FIXTURE_CHARS = 6144
# Informational offline-only budget label bound (USD). Descriptive only,
# not a hard API billing enforcement; no spend is ever performed.
MAX_BUDGET_USD = 1.0

_AUTHORITY_KEYS = frozenset({
    "approval", "approved", "approve", "authority",
    "authorized", "warrant", "grant", "allow_dispatch",
})


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise MetaContractError(code)


@dataclass(frozen=True, slots=True)
class OfflineMuseEnvelope:
    """Descriptive-only offline request envelope. Never dispatches."""

    schema: str
    model: str
    base_url: str
    owner_scope_digest: str
    source_sha: str
    task_digest: str
    instruction_chars: int
    max_output_tokens: int
    timeout_s: int
    budget_usd_limit: float

    @property
    def dispatch_allowed(self) -> bool:
        return False


def build_offline_envelope(
    task: BrowserTaskV1,
    instruction: str,
    *,
    max_output_tokens: int = 512,
    timeout_s: int = 15,
    budget_usd_limit: float = 0.0,
) -> OfflineMuseEnvelope:
    """Build a bounded descriptive envelope pinned to the offline contract."""
    _require(type(task) is BrowserTaskV1, "META_GATE_INPUT_DENIED")
    _require(
        type(instruction) is str and 1 <= len(instruction) <= MAX_INPUT_CHARS,
        "META_INPUT_DENIED",
    )
    _require(
        type(max_output_tokens) is int
        and 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS,
        "META_BUDGET_DENIED",
    )
    _require(
        type(timeout_s) is int and 1 <= timeout_s <= MAX_TIMEOUT_S,
        "META_BUDGET_DENIED",
    )
    _require(
        type(budget_usd_limit) in (int, float)
        and math.isfinite(budget_usd_limit)
        and 0 <= budget_usd_limit <= MAX_BUDGET_USD,
        "META_BUDGET_DENIED",
    )
    _hash(task.owner_scope_digest)
    _hash(task.source_sha, sha40=True)
    _hash(task.digest)
    _require(OFFLINE_MODEL == MUSE_MODEL_ID, "META_MODEL_DENIED")
    return OfflineMuseEnvelope(
        schema=OFFLINE_ENVELOPE_SCHEMA,
        model=OFFLINE_MODEL,
        base_url=OFFLINE_BASE_URL,
        owner_scope_digest=task.owner_scope_digest,
        source_sha=task.source_sha,
        task_digest=task.digest,
        instruction_chars=len(instruction),
        max_output_tokens=max_output_tokens,
        timeout_s=timeout_s,
        budget_usd_limit=float(budget_usd_limit),
    )


class OfflineMuseProvider(OpenAICompatibleProvider):
    """Fixture-only Muse provider. Network path is permanently closed."""

    def __init__(self) -> None:
        super().__init__(
            provider="meta-offline",
            api_key="",
            model=OFFLINE_MODEL,
            base_url=OFFLINE_BASE_URL,
        )

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        raise MetaContractError("META_OFFLINE_DENIED")

    def generate_exact(self, request, cancel, deadline, *, fixture=False):  # noqa: ARG002
        """Fail closed: never dispatch; parent LIVE HTTP path is not called."""
        raise MetaContractError("META_OFFLINE_DENIED")

    def plan_from_fixture(
        self,
        fixture: str,
        *,
        core_owner_scope_digest: str,
        core_source_sha: str,
        allowed_origins: tuple[str, ...] | list[str],
        stopped: bool,
        expected_task_digest: str,
        now: datetime | None = None,
    ) -> BrowserTaskV1:
        """Parse a fixture/mock planning reply into ``BrowserTaskV1``.

        ``fixture`` is a JSON string holding either the plan object itself
        or ``{"model": "muse-spark-1.3", "plan": {...}}``. Every binding
        check reuses :func:`parse_muse_plan`; model-claimed authority,
        owner, SHA, model id drift, and over-limit payloads are rejected
        with constant, redacted error codes.
        """
        _require(
            type(fixture) is str and 1 <= len(fixture) <= MAX_FIXTURE_CHARS,
            "META_JSON_DENIED",
        )
        _require(type(stopped) is bool, "META_GATE_INPUT_DENIED")
        _hash(core_owner_scope_digest)
        _hash(core_source_sha, sha40=True)
        _hash(expected_task_digest)
        try:
            value = json.loads(fixture)
        except (ValueError, TypeError):
            raise MetaContractError("META_JSON_DENIED") from None
        _require(type(value) is dict, "META_INPUT_DENIED")
        assert isinstance(value, dict)
        if "model" in value or "plan" in value:
            _require(
                frozenset(value) == frozenset({"model", "plan"}),
                "META_INPUT_DENIED",
            )
            _require(value["model"] == OFFLINE_MODEL, "META_MODEL_DENIED")
            value = value["plan"]
            _require(type(value) is dict, "META_INPUT_DENIED")
        elif "model" in value:
            raise MetaContractError("META_MODEL_DENIED")
        for key in value:
            _require(type(key) is str, "META_INPUT_DENIED")
            _require(key.lower() not in _AUTHORITY_KEYS, "META_AUTHORITY_DENIED")
        task = parse_muse_plan(
            value,
            core_owner_scope_digest=core_owner_scope_digest,
            core_source_sha=core_source_sha,
            allowed_origins=allowed_origins,
            stopped=stopped,
            now=now,
        )
        _require(task.digest == expected_task_digest, "META_TASK_MISMATCH")
        return task

    @property
    def dispatch_allowed(self) -> bool:
        return False
