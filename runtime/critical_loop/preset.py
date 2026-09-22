"""Read-only competition preset for the existing strict OpenRouter CPL path."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from .review import SUPPORTED_ROLES

PRESET_ID = "openrouter-3-free-observers-v1"
PRIMARY_MODEL = "minimax/minimax-m3:free"
OBSERVER_MODELS = (
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "qwen/qwen3.8-27b:free",
)
MODELS = (PRIMARY_MODEL, *OBSERVER_MODELS)


def _positive_money(value: object) -> bool:
    try:
        return Decimal(str(value)) > 0
    except (InvalidOperation, ValueError, TypeError):
        return False


def build_openrouter_cpl_preset(service) -> dict:
    """Project preset/readiness only; never plans, approves or calls a provider."""
    status = service.status()
    provider = service.manager.strict_status()
    scope = status.get("mode", "UNKNOWN")
    blockers: list[str] = []
    if scope != "LIVE":
        blockers.append("NOT_LIVE_RUNTIME")
    if not provider.get("enabled"):
        blockers.append("OPENROUTER_DISABLED")
    if not provider.get("configured"):
        blockers.append("OPENROUTER_KEY_MISSING")
    if not status.get("live_enabled"):
        blockers.append("LIVE_COST_POLICY_DISABLED")
    if not _positive_money(status.get("session_budget_usd", "0")):
        blockers.append("SESSION_BUDGET_NOT_POSITIVE")

    return {
        "schema": "aioa.cpl-preset.v1",
        "preset_id": PRESET_ID,
        "read_only": True,
        "authority": "ADVISORY_ONLY",
        "provider_connection_id": "openrouter",
        "models": list(MODELS),
        "primary_model": PRIMARY_MODEL,
        "observer_models": list(OBSERVER_MODELS),
        "roles": list(SUPPORTED_ROLES),
        "sequence": ["DRAFTING", "REVIEWING_1", "REVIEWING_2", "REVIEWING_3", "REVISING"],
        "expected_generation_requests": 5,
        "run_budget_usd_suggestion": "0.01",
        "scope": scope,
        "provider_configured": bool(provider.get("configured")),
        "cost_policy_enabled": bool(status.get("live_enabled")),
        "live_preconditions_ready": not blockers,
        "blocking_reasons": blockers,
    }
