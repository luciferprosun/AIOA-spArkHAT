"""No-I/O composition inspection. READY is never inferred from port presence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from runtime.memory_patch.service import CoreMemoryPatchDependencies
from runtime.mission.contracts import (
    MODEL_PROFILE_REF,
    PROFILE,
    MissionContext,
    MissionError,
    MissionManifest,
    MissionTrace,
)


class SchedulerPort(Protocol):
    """Future single Core-owned LITE port. NV-01 never invokes it."""

    def describe(self, trace: MissionTrace) -> dict: ...


@dataclass(frozen=True, slots=True, repr=False)
class MissionBindings:
    """Only trusted Core can supply these; not deserialized from mission JSON."""

    scheduler: SchedulerPort | None = None
    scheduler_owner: str = "AgentRuntime"
    nvidia_key_available: bool | None = None

    def __post_init__(self):
        if self.scheduler_owner != "AgentRuntime" or (
            self.nvidia_key_available is not None
            and type(self.nvidia_key_available) is not bool
        ):
            raise MissionError("INVALID_CORE_BINDINGS")


def result_envelope(
    status,
    reason,
    *,
    trace=None,
    revision=None,
    components=None,
    next_action="NONE",
    retry_class="NONE",
    classification="STATIC_CONFIG",
):
    result = {
        "schema_version": "aioa-mission-diagnostic-v1",
        "status": status,
        "reason_code": reason,
        "trace_id": trace.trace_id if trace else "diagnostic-nvidia-lite",
        "profile": PROFILE,
        "manifest_revision": revision,
        "components": components or [],
        "next_action": next_action,
        "retry_class": retry_class,
        "classification": classification,
        "AIOA_LIVE_PROVIDER_CALLS": 0,
        "AIOA_EFFECTS_EXECUTED": 0,
    }
    if trace is not None:
        result["mission_context"] = {
            "mission_id": trace.mission_id,
            "episode_id": trace.episode_id,
            "event_id": trace.event_id,
            "model_profile_ref": trace.model_profile_ref,
            "evidence_refs": list(trace.evidence_refs),
            "manifest_revision": trace.manifest_revision,
        }
    return result


def inspect_runtime(runtime, *, manifest=None, trace=None):
    if runtime._inspection_only is not True:
        raise MissionError(
            "INSPECTION_RUNTIME_REQUIRED", status="POLICY_BLOCKED", exit_code=4
        )
    if runtime._memory_patch_closed or runtime._nonzero_closed:
        raise MissionError("RUNTIME_CLOSED", status="UNAVAILABLE", exit_code=3)
    context = runtime._mission_context or MissionContext()
    bindings = runtime._mission_bindings or MissionBindings()
    if type(context) is not MissionContext or type(bindings) is not MissionBindings:
        raise MissionError("INVALID_CORE_BINDINGS")
    deps = runtime._memory_patch_dependencies
    if deps is not None and type(deps) is not CoreMemoryPatchDependencies:
        raise MissionError("INVALID_CORE_BINDINGS")
    assignment = runtime.memory_patch_config.assignment
    if assignment is not None and context.owner_scope != assignment.scope:
        raise MissionError("OWNER_SCOPE_MISMATCH", status="POLICY_BLOCKED", exit_code=4)
    if manifest is not None:
        if type(manifest) is not MissionManifest:
            raise MissionError()
        manifest.require_context(context)
        manifest.require_controlled()
    if trace is not None:
        if type(trace) is not MissionTrace:
            raise MissionError("TRACE_BINDING_MISMATCH")
        if manifest is None:
            raise MissionError("TRACE_REQUIRES_MANIFEST")
        trace.require_manifest(manifest)
    trace_id = trace.trace_id if trace else "diagnostic-nvidia-lite"
    enabled = manifest is not None and manifest.enabled
    rows = []

    def component(name, status, reason, *, checked="static_config", **detail):
        rows.append(
            {
                "component_id": name,
                "status": status,
                "reason_code": reason,
                "checked_level": checked,
                "trace_id": trace_id,
                **detail,
            }
        )

    component(
        "mission_profile",
        "ENABLED" if enabled else "DISABLED",
        "CONTROLLED_CONTRACT_ONLY" if enabled else "PROFILE_DISABLED",
        mode="CONTROLLED",
        effects_enabled=False,
    )
    memory = runtime.memory_patch_status()  # existing Core-owned discovery seam
    if not memory["enabled"]:
        component(
            "memory_patch",
            "DISABLED",
            memory["reason_code"],
            contract_version=memory["contract_version"],
        )
    elif assignment is None:
        component("memory_patch", "UNAVAILABLE", "OWNER_DENIED")
    elif deps is None or deps.transaction_factory is None:
        component("memory_patch", "UNAVAILABLE", "BACKEND_UNCONFIGURED")
    else:
        component("memory_patch", "ENABLED", "BACKEND_BOUND_NOT_PROBED")
    for name, attribute in (
        ("evidence", "evidence_catalog"),
        ("source_registry", "sources"),
        ("provenance", "provenance_store"),
    ):
        bound = deps is not None and getattr(deps, attribute) is not None
        component(
            name,
            "ENABLED" if bound else "UNAVAILABLE",
            "PORT_BOUND_NOT_PROBED" if bound else "CORE_PORT_UNBOUND",
        )
    component(
        "cpl",
        "ENABLED" if enabled else "DISABLED",
        "EXACT_OPENROUTER_CONTRACT_ONLY",
        contract_version="cpl-1plus3plus1-v1",
        provider_connection_id="openrouter",
        live_enabled=False,
        initialized=runtime._cpl_service is not None,
        restart_policy="INTERRUPTED_NO_REPLAY",
    )
    nonzero = (
        runtime.nonzero_status()
    )  # metadata probe only; never property initialization
    component(
        "nonzero",
        "ENABLED" if nonzero["available"] else "UNAVAILABLE",
        "PORTABLE_CONTRACT_NOT_LIVE_APPROVAL"
        if nonzero["available"]
        else nonzero["availability_code"],
        checked="local_probe",
        authority="EXPLICIT_HUMAN_APPROVAL_SYNTHETIC_ONLY",
    )
    component(
        "hats",
        "UNAVAILABLE",
        "HAT_SELECTION_UNBOUND_IN_INSPECTION",
        temporal_modes=["CURRENT", "AS_OF"],
        german_law="FIXTURE_POLICY_ONLY",
    )
    component(
        "nvidia_adapter",
        "UNAVAILABLE",
        "PRODUCT_ADAPTER_NOT_IMPLEMENTED",
        nv00_tooling_is_product_adapter=False,
        model_profile_ref=MODEL_PROFILE_REF,
    )
    key_reason = (
        "CREDENTIAL_PRESENCE_NOT_CHECKED"
        if bindings.nvidia_key_available is None
        else "CREDENTIAL_MISSING"
        if not bindings.nvidia_key_available
        else "CREDENTIAL_PRESENT_NOT_VALIDATED"
    )
    component(
        "nvidia_credentials",
        "ENABLED" if bindings.nvidia_key_available else "UNAVAILABLE",
        key_reason,
    )
    component(
        "scheduler",
        "ENABLED" if bindings.scheduler is not None else "UNAVAILABLE",
        "PORT_BOUND_NOT_STARTED"
        if bindings.scheduler is not None
        else "SCHEDULER_NOT_IMPLEMENTED",
        scheduler_owner=bindings.scheduler_owner,
        started=False,
    )
    component("effects", "DISABLED", "EFFECTS_NOT_IMPLEMENTED")
    component("delta_pheromone", "DISABLED", "CONTRACTS_ONLY_NO_STORE_OR_SCORING")
    status = "UNAVAILABLE" if enabled else "DISABLED"
    return result_envelope(
        status,
        "REQUIRED_PORTS_NOT_READY" if enabled else "PROFILE_DISABLED",
        trace=trace,
        revision=manifest.manifest_revision if manifest else None,
        components=rows,
        next_action="REVIEW_G2_G3_PORT_BINDINGS"
        if enabled
        else "OPERATOR_REVIEW_REQUIRED",
        retry_class="MANUAL_CONFIGURATION" if enabled else "NONE",
        classification=context.classification,
    )
