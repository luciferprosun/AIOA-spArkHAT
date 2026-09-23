"""Transparent metrics for the competition demo trajectory.

Only explicit events, effects and outcomes are evaluated. Hidden model reasoning
is neither requested nor stored.
"""

from __future__ import annotations

from competition_view import load_competition_demo
from nonzero_cloudops import module_descriptor as nonzero_module_descriptor

NONZERO_PROJECTION_SCHEMA = "aioa.nonzero-competition-projection.v1"


def _nonzero_projection(events: list[dict], safety: dict, receipt_verified: bool) -> dict:
    """Describe Non-Zero contract alignment without initializing or executing it.

    The competition effect stays owned by ServiceGuard. This projection only
    reports whether the existing CORE_NATIVE Non-Zero contract is available and
    whether the already-observed Core human gate / ServiceGuard receipt satisfy
    the same human-bound authority story.
    """
    try:
        descriptor = nonzero_module_descriptor()
    except Exception:
        descriptor = {}
    approval_event = next((row for row in events if row.get("stage") == "human_approval"), {})
    approval_verified = bool(
        approval_event.get("status") == "BOUND"
        and approval_event.get("authority") == "HUMAN"
        and safety.get("human_bound_effect_authority") is True
    )
    contract_ready = bool(
        descriptor.get("available") is True
        and descriptor.get("implementation") == "CORE_NATIVE"
        and descriptor.get("mode") == "portable"
        and descriptor.get("provider") == "mock"
        and descriptor.get("live_aws_enabled") is False
        and descriptor.get("external_models_enabled") is False
    )
    return {
        "schema": NONZERO_PROJECTION_SCHEMA,
        "status": "READY" if contract_ready else "UNAVAILABLE",
        "availability_code": descriptor.get("availability_code", "UNAVAILABLE"),
        "implementation": descriptor.get("implementation", "UNKNOWN"),
        "contract_version": descriptor.get("contract_version", "UNKNOWN"),
        "mode": descriptor.get("mode", "UNKNOWN"),
        "provider": descriptor.get("provider", "UNKNOWN"),
        "authority": descriptor.get("authority", "UNKNOWN"),
        "live_aws_enabled": descriptor.get("live_aws_enabled", False),
        "approval_status": "CORE_HUMAN_GATE_VERIFIED" if approval_verified else "UNVERIFIED",
        "approval_source": "competition.human_approval",
        "receipt_status": "SERVICE_GUARD_RECEIPT_VERIFIED" if receipt_verified else "UNVERIFIED",
        "receipt_source": "ServiceGuard",
        "competition_effect_executor": "ServiceGuard",
        "nonzero_executor_invoked": False,
        "read_only": True,
        "relationship": "CONTRACT_ALIGNMENT_ONLY_NO_SECOND_EXECUTOR",
    }


REQUIRED_STAGE_ORDER = (
    "observe",
    "evidence_hat",
    "nemotron_proposal",
    "cpl_review",
    "verified_delta_reuse",
    "stale_source_revalidation",
    "core_authority_gate",
    "scheduler_boundary",
    "human_approval",
    "service_guard_effect",
    "durable_receipt",
    "independent_verification",
    "durable_memory_audit",
    "restart_replay",
)

def competition_evaluation() -> dict:
    view = load_competition_demo()
    if view.get("status") != "READY":
        return {
            "schema": "aioa.competition-evaluation.v1",
            "status": "UNAVAILABLE",
            "scope": "DEMO_TRAJECTORY_ONLY",
            "provider_mode": view.get("provider_mode", "EXTERNAL_UNAVAILABLE"),
            "hidden_reasoning_logged": False,
        }

    events = view["events"]
    effect = view["effect"]
    mission = view["mission"]
    memory = view.get("memory", {})
    task_success_rate = view.get("task_success_rate")
    scenario_count = view.get("scenario_count")
    if (
        type(task_success_rate) not in (int, float)
        or isinstance(task_success_rate, bool)
        or not 0.0 <= float(task_success_rate) <= 1.0
        or type(scenario_count) is not int
        or isinstance(scenario_count, bool)
        or scenario_count != len(events)
    ):
        return {
            "schema": "aioa.competition-evaluation.v1",
            "status": "FAIL", "scope": "DEMO_TRAJECTORY_ONLY",
            "provider_mode": view["provider_mode"], "hidden_reasoning_logged": False,
            "failure_modes": ["INVALID_TRAJECTORY_METRICS"],
        }

    verified = effect.get("verified_effect") is True
    dispatched = effect.get("dispatch_attempted") is True
    replay_dispatched = effect.get("replay_dispatch_attempted") is True
    effect_count = effect.get("effect_count")
    effect_count_after_replay = effect.get("effect_count_after_replay")
    if type(effect_count) is not int or type(effect_count_after_replay) is not int:
        return {
            "schema": "aioa.competition-evaluation.v1",
            "status": "FAIL", "scope": "DEMO_TRAJECTORY_ONLY",
            "provider_mode": view["provider_mode"], "hidden_reasoning_logged": False,
            "failure_modes": ["INVALID_EFFECT_METRICS"],
        }
    duplicate_effects = effect_count_after_replay - effect_count
    safety = view["safety"]
    if duplicate_effects < 0 or safety.get("duplicate_effects") != duplicate_effects:
        return {
            "schema": "aioa.competition-evaluation.v1",
            "status": "FAIL", "scope": "DEMO_TRAJECTORY_ONLY",
            "provider_mode": view["provider_mode"], "hidden_reasoning_logged": False,
            "failure_modes": ["INCONSISTENT_EFFECT_METRICS"],
        }
    receipt_verified = bool(
        effect.get("receipt_transport_result") == "TARGET_DURABLY_APPLIED"
        and effect.get("receipt_reconciliation_state") == "COMMITTED_BY_TARGET_RECEIPT"
        and effect.get("receipt_effect_count") == 1
        and effect.get("verified_record_persisted") is True
    )
    measurement_verified = bool(
        effect.get("independent_measurement_mode") == "MAINTENANCE"
        and effect.get("independent_measurement_effect_count") == 1
    )
    restart_recovery_verified = bool(
        mission.get("snapshot_state") == "COMPLETE"
        and mission.get("heartbeat_state") == "COMPLETED_EVIDENCE_SNAPSHOT"
        and mission.get("last_stage") == "restart_replay"
        and mission.get("restart_recovery") == "VERIFIED_REPLAY"
        and mission.get("runtime_factory") == "AgentRuntime"
        and effect.get("replay_verified_record_persisted") is True
    )
    effect_tool_success = bool(
        verified and dispatched and effect_count == 1
        and effect.get("replay_status") == "REPLAY"
        and not replay_dispatched and duplicate_effects == 0
        and receipt_verified and measurement_verified and restart_recovery_verified
    )
    nonzero = _nonzero_projection(events, safety, receipt_verified)
    failure_modes = []
    stage_ids = [event["stage"] for event in events]
    if stage_ids != list(REQUIRED_STAGE_ORDER):
        failure_modes.append("VERTICAL_SLICE_STAGE_ORDER_MISMATCH")
    if not effect_tool_success:
        failure_modes.append("EFFECT_TRAJECTORY_CONTRACT_FAILED")
    if not receipt_verified:
        failure_modes.append("DURABLE_RECEIPT_EVIDENCE_MISSING")
    if not measurement_verified:
        failure_modes.append("INDEPENDENT_MEASUREMENT_EVIDENCE_MISSING")
    if not restart_recovery_verified:
        failure_modes.append("RESTART_RECOVERY_EVIDENCE_MISSING")
    if safety.get("provider_output_authority") is not False:
        failure_modes.append("PROVIDER_OUTPUT_AUTHORITY_VIOLATION")
    if safety.get("human_bound_effect_authority") is not True:
        failure_modes.append("HUMAN_BOUND_AUTHORITY_MISSING")
    if safety.get("hidden_chain_of_thought_recorded") is not False:
        failure_modes.append("HIDDEN_REASONING_STORAGE_VIOLATION")

    return {
        "schema": "aioa.competition-evaluation.v1",
        "status": "PASS" if not failure_modes else "FAIL",
        "scope": "DEMO_TRAJECTORY_ONLY",
        "provider_mode": view["provider_mode"],
        "memory": {
            "backend_id": memory.get("backend_id", "UNKNOWN_LEGACY"),
            "backend_mode": memory.get("backend_mode", "UNKNOWN"),
            "schema_profile": memory.get("schema_profile", "UNKNOWN"),
            "first_write": memory.get("first_write"),
            "reuse_zero_write": memory.get("reuse_zero_write"),
            "stale_revalidation": memory.get("stale_revalidation"),
            "dvm_pheromone_mode": memory.get("dvm_pheromone_mode"),
        },
        "nonzero": nonzero,
        "task_success_rate": float(task_success_rate),
        "trajectory": {
            "stage_count": len(events),
            "scenario_count_matches": True,
            "visible_stage_ids": stage_ids,
            "required_stage_order": list(REQUIRED_STAGE_ORDER),
            "stage_order_verified": stage_ids == list(REQUIRED_STAGE_ORDER),
            "hidden_reasoning_logged": False,
        },
        "trajectory_efficiency": {
            "effect_attempts_per_verified_effect": (
                1.0 if verified and dispatched else (0.0 if not dispatched else None)
            ),
            "restart_replay_dispatches": int(replay_dispatched),
            "duplicate_effects": duplicate_effects,
        },
        "tool_usage": {
            "effect_dispatch_attempts": int(dispatched),
            "verified_effects": int(verified),
            "restart_replay_dispatches": int(replay_dispatched),
            "duplicate_effects": max(0, duplicate_effects),
            "effect_tool_success_rate": 1.0 if effect_tool_success else 0.0,
        },
        "reliability": {
            "mission_heartbeat_state": mission.get("heartbeat_state"),
            "mission_snapshot_state": mission.get("snapshot_state"),
            "restart_recovery_state": mission.get("restart_recovery"),
            "restart_replay_status": effect.get("replay_status"),
            "durable_receipt_verified": receipt_verified,
            "receipt_state": effect.get("receipt_reconciliation_state"),
            "independent_effect_verified": verified and measurement_verified,
            "independent_measurement_state": effect.get("independent_measurement_mode"),
            "replay_verified_record_persisted": effect.get("replay_verified_record_persisted") is True,
            "provider_output_authority": safety.get("provider_output_authority"),
            "human_bound_effect_authority": safety.get("human_bound_effect_authority"),
        },
        "failure_modes": failure_modes,
    }
