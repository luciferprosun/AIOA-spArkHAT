"""Read-only competition evidence projection for the local dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path

MAX_BYTES = 128 * 1024
EXPECTED_SCHEMA = "aioa.nvidia-competition-demo.v1"
ALLOWED_MODES = {"TEST_FIXTURE", "LIVE"}
ENV_PATH = "AIOA_COMPETITION_DEMO_EVIDENCE"


def _unavailable(status: str) -> dict:
    return {
        "schema": "aioa.competition-view.v1",
        "status": status,
        "provider_mode": "UNKNOWN",
        "evidence_available": False,
        "read_only": True,
    }


def load_competition_demo() -> dict:
    raw_path = os.environ.get(ENV_PATH, "").strip()
    if not raw_path:
        return _unavailable("NOT_CONFIGURED")
    try:
        candidate = Path(raw_path).expanduser()
        if candidate.is_symlink():
            return _unavailable("INVALID_EVIDENCE")
        path = candidate.resolve(strict=True)
        stat = path.stat()
        if not path.is_file() or stat.st_size > MAX_BYTES:
            return _unavailable("INVALID_EVIDENCE")
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _unavailable("INVALID_EVIDENCE")

    if (
        type(value) is not dict
        or value.get("schema") != EXPECTED_SCHEMA
        or value.get("execution_mode") not in ALLOWED_MODES
        or type(value.get("live_provider_claimed")) is not bool
        or type(value.get("events")) is not list
        or type(value.get("effect")) is not dict
        or type(value.get("safety")) is not dict
        or type(value.get("mission")) is not dict
        or (value.get("memory") is not None and type(value.get("memory")) is not dict)
    ):
        return _unavailable("INVALID_EVIDENCE")

    mode = value["execution_mode"]
    if mode == "TEST_FIXTURE" and value["live_provider_claimed"]:
        return _unavailable("INVALID_EVIDENCE")
    if mode == "LIVE" and not value["live_provider_claimed"]:
        return _unavailable("INVALID_EVIDENCE")

    events = []
    for row in value["events"]:
        if type(row) is not dict:
            return _unavailable("INVALID_EVIDENCE")
        stage, status, authority = row.get("stage"), row.get("status"), row.get("authority")
        if not all(type(item) is str and item for item in (stage, status, authority)):
            return _unavailable("INVALID_EVIDENCE")
        events.append({"stage": stage, "status": status, "authority": authority})

    effect = value["effect"]
    safety = value["safety"]
    mission = value["mission"]
    memory = value.get("memory") or {}
    backend_id = memory.get("backend_id", "UNKNOWN_LEGACY")
    backend_mode = memory.get("backend_mode", "UNKNOWN")
    schema_profile = memory.get("schema_profile", "UNKNOWN")
    dvm_pheromone_mode = memory.get("dvm_pheromone_mode")
    if dvm_pheromone_mode != "SHADOW":
        return _unavailable("INVALID_EVIDENCE")
    if backend_mode not in {"UNKNOWN", "TEST_FIXTURE", "LIVE_COCKROACH"}:
        return _unavailable("INVALID_EVIDENCE")
    if backend_mode == "TEST_FIXTURE" and backend_id != "repository-durable-test":
        return _unavailable("INVALID_EVIDENCE")
    if backend_mode == "LIVE_COCKROACH" and (
        backend_id != "cockroachdb-learning-v1" or schema_profile != "learning-v1"
    ):
        return _unavailable("INVALID_EVIDENCE")
    if not all(type(item) is str and item for item in (backend_id, backend_mode, schema_profile)):
        return _unavailable("INVALID_EVIDENCE")
    mission_fields = ("snapshot_state", "heartbeat_state", "last_stage", "restart_recovery", "runtime_factory")
    if not all(type(mission.get(key)) is str and mission.get(key) for key in mission_fields):
        return _unavailable("INVALID_EVIDENCE")
    bool_effect_fields = (
        "verified_effect", "dispatch_attempted", "replay_dispatch_attempted",
        "verified_record_persisted", "replay_verified_record_persisted",
    )
    if any(type(effect.get(key)) is not bool for key in bool_effect_fields):
        return _unavailable("INVALID_EVIDENCE")
    count_fields = (
        "receipt_effect_count", "independent_measurement_effect_count",
    )
    if any(type(effect.get(key)) is not int or effect.get(key) < 0 for key in count_fields):
        return _unavailable("INVALID_EVIDENCE")
    bool_safety_fields = (
        "provider_output_authority", "human_bound_effect_authority",
        "hidden_chain_of_thought_recorded",
    )
    if any(type(safety.get(key)) is not bool for key in bool_safety_fields):
        return _unavailable("INVALID_EVIDENCE")
    if type(safety.get("duplicate_effects")) is not int or safety.get("duplicate_effects") < 0:
        return _unavailable("INVALID_EVIDENCE")
    digest_fields = ("receipt_digest", "measurement_digest")
    if any(
        type(effect.get(key)) is not str
        or len(effect.get(key)) != 64
        or any(ch not in "0123456789abcdefABCDEF" for ch in effect.get(key))
        for key in digest_fields
    ):
        return _unavailable("INVALID_EVIDENCE")
    return {
        "schema": "aioa.competition-view.v1",
        "status": "READY",
        "provider_mode": mode,
        "provider_status": value.get("provider_status"),
        "evidence_available": True,
        "read_only": True,
        "task_success_rate": value.get("task_success_rate"),
        "scenario_count": value.get("scenario_count"),
        "events": events,
        "mission": {key: mission[key] for key in mission_fields},
        "memory": {
            "backend_id": backend_id,
            "backend_mode": backend_mode,
            "schema_profile": schema_profile,
            "first_write": memory.get("first_write"),
            "reuse_zero_write": memory.get("reuse_zero_write"),
            "stale_revalidation": memory.get("stale_revalidation"),
            "dvm_pheromone_mode": dvm_pheromone_mode,
        },
        "effect": {
            key: effect.get(key)
            for key in (
                "status", "verified_effect", "dispatch_attempted", "effect_count",
                "replay_status", "replay_dispatch_attempted", "effect_count_after_replay",
                "receipt_transport_result", "receipt_reconciliation_state", "receipt_effect_count",
                "receipt_digest", "independent_measurement_mode",
                "independent_measurement_effect_count", "measurement_digest",
                "verified_record_persisted", "replay_verified_record_persisted",
            )
        },
        "safety": {
            key: safety.get(key)
            for key in (
                "provider_output_authority", "duplicate_effects",
                "human_bound_effect_authority", "hidden_chain_of_thought_recorded",
            )
        },
    }
