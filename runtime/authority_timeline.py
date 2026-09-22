"""Read-only projection of existing AIOA authority boundaries for demos/audit."""

from __future__ import annotations

from collections.abc import Mapping


def _safe(call):
    try:
        value = call()
    except Exception:
        return {"status": "UNAVAILABLE"}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        return {"status": "AVAILABLE", "value": value}
    return {"status": "UNAVAILABLE"}


def _state(value: Mapping) -> str:
    for key in ("execution_status", "status", "state", "readiness", "mode"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return "AVAILABLE"


def build_authority_timeline(runtime) -> dict:
    """Project subsystem state without creating any new authority or mutation path."""
    provider = _safe(runtime.provider_manager.describe)
    critical = _safe(lambda: runtime.critical_loop.status())
    lite = _safe(runtime.lite_status)
    memory = _safe(runtime.lite_memory_status)
    lite_cpl = _safe(runtime.lite_cpl_status)
    dynamics = _safe(runtime.lite_dynamics_status)
    nonzero = _safe(runtime.nonzero_status)

    service_guard = lite.get("service_guard")
    if not isinstance(service_guard, Mapping):
        service_guard = {"status": "UNBOUND" if not lite.get("guarded_effect_domain") else "AVAILABLE"}

    events = [
        {"stage": "provider_proposal", "status": _state(provider),
         "authority": "ADVISORY_ONLY", "source": "ProviderManager"},
        {"stage": "critical_prompt_loop", "status": _state(critical),
         "authority": "ADVISORY_ONLY", "source": "CriticalPromptLoop"},
        {"stage": "verified_memory", "status": _state(memory),
         "authority": "ADVISORY_ONLY", "source": "MemoryPatch"},
        {"stage": "lite_cpl", "status": _state(lite_cpl),
         "authority": "ADVISORY_ONLY", "source": "LiteCPL"},
        {"stage": "memory_dynamics", "status": _state(dynamics),
         "authority": "SHADOW_OR_ADVISORY", "source": "MemoryDynamics"},
        {"stage": "scheduler", "status": _state(lite),
         "authority": "COORDINATION_ONLY", "source": "AgentRuntime"},
        {"stage": "service_guard", "status": _state(service_guard),
         "authority": "CORE_GATE", "source": "ServiceGuard"},
        {"stage": "nonzero_effect", "status": _state(nonzero),
         "authority": "HUMAN_BOUND_CORE", "source": "NonZero"},
        {"stage": "evidence_review", "status": "ENABLED",
         "authority": "METADATA_ONLY_NO_AUTHORITY", "source": "EvidenceReview"},
    ]
    return {
        "schema": "aioa.authority-timeline.v1",
        "product_name": "AIOA spArkHAT",
        "effect_authority": "CORE_HUMAN_GATED_ONLY",
        "provider_output_authority": False,
        "timeline_is_read_only_projection": True,
        "events": events,
    }
