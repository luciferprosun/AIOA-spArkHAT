"""Offline Muse planner contract (G3 preparation).

Stdlib-only, no network, no browser, no effects. Builds a bounded,
provider-agnostic request payload for model id ``muse-spark-1.3`` with NO
embedded credential, and parses an UNTRUSTED model-originated plan into the
existing :class:`BrowserTaskV1` READ contract only.

Model output is *data*. It cannot grant WRITE/EXEC, change allowed origins,
owner binding, source SHA, STOP state, or task lease. A Core-owned runtime
must still admit dispatch via ``screen_task`` independently.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .contracts import BrowserTaskV1, MetaContractError, _hash, utc_timestamp
from .policy import GateEffect, screen_task

MUSE_MODEL_ID = "muse-spark-1.3"
MUSE_REQUEST_SCHEMA = "aioa.meta.muse-request.v1"

# The only tool a Muse plan may name. Anything else is WRITE/EXEC or unknown.
ALLOWED_MUSE_TOOLS = frozenset({"browser.navigate_read"})

# Exact model-originated fields. Unknown model-originated fields are rejected.
# Binding fields (owner digest, source SHA, allowed origins) are NEVER taken
# from model output; the trusted host supplies them separately.
_MUSE_PLAN_FIELDS = frozenset({
    "tool",
    "task_id",
    "target_url",
    "deadline_utc",
    "max_pages",
    "timeout_ms",
    "max_chars",
})

_REQUEST_FIELDS = frozenset({
    "schema", "model", "instruction", "task", "tools", "max_tokens",
    "temperature",
})

_MAX_INSTRUCTION_CHARS = 2000
_MAX_TOKENS_MIN = 1
_MAX_TOKENS_MAX = 1200

_CREDENTIAL_SUBSTRINGS = (
    "api_key", "apikey", "authorization", "bearer",
    "cookie", "secret", "password", "meta_api_key",
)


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise MetaContractError(code)


def _no_credentials(obj: Any) -> None:
    """Fail closed if any key/value even smells like a credential."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            _require(
                type(key) is str
                and not any(s in key.lower() for s in _CREDENTIAL_SUBSTRINGS),
                "META_CREDENTIAL_DENIED",
            )
            _no_credentials(value)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _no_credentials(item)


@dataclass(frozen=True, slots=True)
class MuseRequestV1:
    """Bounded provider-agnostic request preview. Never dispatches."""

    model: str
    instruction: str
    task_digest: str
    max_tokens: int = 800
    temperature: int = 0
    schema: str = MUSE_REQUEST_SCHEMA

    @property
    def dispatch_allowed(self) -> bool:
        return False


def build_muse_request(
    task: BrowserTaskV1,
    instruction: str,
    *,
    max_tokens: int = 800,
) -> dict:
    """Build a bounded offline request payload for ``muse-spark-1.3``.

    The instruction string is embedded as opaque DATA, never interpreted.
    No credential is read, embedded, or returned.
    """
    _require(type(task) is BrowserTaskV1, "META_GATE_INPUT_DENIED")
    _require(
        type(instruction) is str and 1 <= len(instruction) <= _MAX_INSTRUCTION_CHARS,
        "META_INPUT_DENIED",
    )
    _require(
        type(max_tokens) is int and _MAX_TOKENS_MIN <= max_tokens <= _MAX_TOKENS_MAX,
        "META_BUDGET_DENIED",
    )
    payload = {
        "schema": MUSE_REQUEST_SCHEMA,
        "model": MUSE_MODEL_ID,
        "instruction": instruction,
        "task": task.to_dict(),
        "tools": sorted(ALLOWED_MUSE_TOOLS),
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    _require(frozenset(payload) == _REQUEST_FIELDS, "META_INPUT_DENIED")
    _require(payload["model"] == MUSE_MODEL_ID, "META_MODEL_DENIED")
    _no_credentials(payload)
    return payload


def parse_muse_plan(
    value: object,
    *,
    core_owner_scope_digest: str,
    core_source_sha: str,
    allowed_origins: tuple[str, ...] | list[str],
    stopped: bool,
    now: datetime | None = None,
) -> BrowserTaskV1:
    """Parse untrusted Muse output into :class:`BrowserTaskV1` (READ-only).

    Binding comes ONLY from trusted host arguments. Any model-supplied
    owner digest, SHA, origins, approval, WRITE/EXEC tool, unknown field,
    STOP/expiry drift, or malformed value raises ``MetaContractError``.
    """
    _require(type(value) is dict, "META_INPUT_DENIED")
    assert isinstance(value, dict)
    _require(frozenset(value) == _MUSE_PLAN_FIELDS, "META_INPUT_DENIED")
    _require(type(stopped) is bool, "META_GATE_INPUT_DENIED")
    _hash(core_owner_scope_digest)
    _hash(core_source_sha, sha40=True)
    _require(
        type(allowed_origins) in (list, tuple) and len(allowed_origins) >= 1,
        "META_ORIGINS_DENIED",
    )
    origins = tuple(allowed_origins)
    _require(all(type(o) is str for o in origins), "META_ORIGINS_DENIED")

    tool = value["tool"]
    _require(type(tool) is str and tool in ALLOWED_MUSE_TOOLS, "META_TOOL_DENIED")

    task_id = value["task_id"]
    target_url = value["target_url"]
    deadline_utc = value["deadline_utc"]
    max_pages = value["max_pages"]
    timeout_ms = value["timeout_ms"]
    max_chars = value["max_chars"]
    _require(type(task_id) is str, "META_ID_DENIED")
    _require(type(target_url) is str, "META_URL_DENIED")
    _require(type(deadline_utc) is str, "META_TIME_DENIED")
    _require(
        type(max_pages) is int and type(timeout_ms) is int and type(max_chars) is int,
        "META_BUDGET_DENIED",
    )
    utc_timestamp(deadline_utc)  # malformed timestamps fail here, no echo.
    _no_credentials(value)

    task = BrowserTaskV1(
        task_id=task_id,
        owner_scope_digest=core_owner_scope_digest,
        source_sha=core_source_sha,
        allowed_origins=origins,
        target_url=target_url,
        deadline_utc=deadline_utc,
        operation="navigate_read",
        max_pages=max_pages,
        timeout_ms=timeout_ms,
        max_chars=max_chars,
    )
    result = screen_task(
        task,
        core_owner_scope_digest=core_owner_scope_digest,
        core_source_sha=core_source_sha,
        stopped=stopped,
        now=now,
    )
    if result.effect is not GateEffect.CORE_ADMISSION_REQUIRED:
        raise MetaContractError(result.reason)
    if result.effect is GateEffect.DENY:  # defensive; reason already raised above.
        raise MetaContractError("META_DENIED")
    return task
