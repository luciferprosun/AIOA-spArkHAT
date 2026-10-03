"""Read-only competition evidence projection for the local dashboard."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

from runtime.providers.nebius_routing import (
    RoutingError,
    validate_competition_model,
)
from runtime.providers.nvidia import ProviderError

MAX_BYTES = 128 * 1024
EXPECTED_SCHEMA = "aioa.nvidia-competition-demo.v1"
ALLOWED_MODES = {"TEST_FIXTURE", "LIVE"}
ENV_PATH = "AIOA_COMPETITION_DEMO_EVIDENCE"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_PERSONAL_STATES = frozenset({
    "ADVISORY", "VERIFIED", "ZERO_WRITE", "APPROVAL_REQUIRED", "APPROVED",
    "EXECUTED", "RECONCILED", "REPLAY_BLOCKED",
})
_PERSONAL_STATUS_KEYS = frozenset({
    "schema", "operation_id", "target_id", "proposal_id", "provider_id",
    "model_id", "execution_mode", "model_authority", "memory", "cpl_status",
    "verification_status", "state", "timeline", "approval", "verified_effect",
    "reconciliation_pending", "receipt_id", "receipt_digest",
    "measurement_digest", "replay_reason", "updated_at",
})
_PERSONAL_EXTRA_KEYS = frozenset({"provider_mode", "target_mode", "verified_delta_status", "effect_apply_count", "duplicate_effect_count", "action"})
_RESERVATION_KEYS = frozenset({
    "reservation_id", "watch_id", "trace_id", "provider_id", "model_id",
    "created_at", "status", "estimated_units", "actual_units", "reason",
})


def _unavailable(status: str) -> dict:
    return {
        "schema": "aioa.competition-view.v1",
        "status": status,
        "provider_mode": "UNKNOWN",
        "evidence_available": False,
        "read_only": True,
    }


def _personal_unavailable() -> dict:
    return {
        "schema": "aioa.nebius-personal-ai-view.v1",
        "status": "INVALID_EVIDENCE",
        "evidence_available": False,
        "read_only": True,
    }


def project_nebius_personal_ai(status: dict, reservations: list[dict], *,
                               catalog: dict, cost_quote: dict,
                               expected_execution_mode: str) -> dict:
    """Strictly project redacted Personal AI state and its budget journal."""
    try:
        if (
            type(status) is not dict
            or set(status) not in (_PERSONAL_STATUS_KEYS, _PERSONAL_STATUS_KEYS | _PERSONAL_EXTRA_KEYS)
            or status.get("schema") not in {"aioa.personal-ai-demo.v1", "aioa.personal-ai-demo.v2"}
            or (status.get("schema") == "aioa.personal-ai-demo.v2" and not _PERSONAL_EXTRA_KEYS <= set(status))
            or status.get("provider_id") != "nebius"
            or status.get("execution_mode") not in {"LIVE", "FIXTURE"}
            or expected_execution_mode not in {"LIVE", "FIXTURE"}
            or status["execution_mode"] != expected_execution_mode
            or status.get("model_authority") != "ADVISORY_ONLY"
            or type(status.get("operation_id")) is not str
            or not status["operation_id"]
            or type(status.get("target_id")) is not str
            or not status["target_id"]
            or type(status.get("proposal_id")) is not str
            or _HEX.fullmatch(status["proposal_id"]) is None
        ):
            raise ValueError()
        if catalog.get("schema") == "aioa.nebius-fixture-catalog.v1":
            if (expected_execution_mode != "FIXTURE" or status.get("provider_mode", "FIXTURE") != "FIXTURE"
                    or catalog.get("status") != "FIXTURE" or catalog.get("transport_scope") != "TEST"
                    or catalog.get("live_catalog_validated") is not False or catalog.get("provider") != "nebius"
                    or catalog.get("authority") != "ADVISORY_ONLY" or catalog.get("fallback") is not False
                    or catalog.get("response_content_persisted") is not False
                    or type(catalog.get("catalog_nemotron_ids")) is not list
                    or status["model_id"] not in catalog["catalog_nemotron_ids"]):
                raise ValueError()
        else:
            validate_competition_model(status["model_id"], catalog, cost_quote)

        memory = status.get("memory")
        if (
            type(memory) is not dict
            or set(memory) != {
                "status", "selected_count", "eligible_count", "context_digest",
                "context_byte_units", "truncated", "execution_authority",
            }
            or memory.get("status") not in {"RETRIEVED", "EMPTY"}
            or any(
                type(memory.get(name)) is not int
                or not 0 <= memory[name] <= maximum
                for name, maximum in (
                    ("selected_count", 16),
                    ("eligible_count", 40),
                    ("context_byte_units", 8192),
                )
            )
            or memory["selected_count"] > memory["eligible_count"]
            or (memory["status"] == "RETRIEVED") != (memory["selected_count"] > 0)
            or type(memory.get("context_digest")) is not str
            or _HEX.fullmatch(memory["context_digest"]) is None
            or type(memory.get("truncated")) is not bool
            or memory.get("execution_authority") is not False
        ):
            raise ValueError()

        verification = status.get("verification_status")
        if (
            verification not in {"VERIFIED", "ZERO_WRITE"}
            or status.get("cpl_status") not in {"VERIFIED", "ZERO_WRITE", "NOT_RUN", "COMPLETED_ADVISORY"}
            or status.get("state") not in _PERSONAL_STATES
            or status.get("approval") not in {"REQUIRED", "APPROVED"}
            or type(status.get("verified_effect")) is not bool
            or type(status.get("reconciliation_pending")) is not bool
            or type(status.get("updated_at")) is not int
            or not 0 <= status["updated_at"] <= 2**53
        ):
            raise ValueError()
        if _PERSONAL_EXTRA_KEYS <= set(status):
            if (status["provider_mode"] not in {"LIVE", "FIXTURE"} or status["target_mode"] not in {"LIVE", "FIXTURE"}
                    or status["verified_delta_status"] != "ZERO_WRITE"
                    or (status["schema"] == "aioa.personal-ai-demo.v2" and status["cpl_status"] not in {"NOT_RUN", "COMPLETED_ADVISORY"})
                    or any(type(status[k]) is not int or not 0 <= status[k] <= 1 for k in ("effect_apply_count", "duplicate_effect_count"))):
                raise ValueError()
            action = status["action"]
            if (type(action) is not dict or set(action) != {"effect", "expected_target_revision"}
                    or action.get("effect") != "SET_MAINTENANCE"
                    or type(action.get("expected_target_revision")) is not int or not 1 <= action["expected_target_revision"] <= 2**53):
                raise ValueError()

        timeline = status.get("timeline")
        if (
            type(timeline) is not list
            or not 1 <= len(timeline) <= 16
            or any(
                type(row) is not dict
                or set(row) != {"state", "at"}
                or row.get("state") not in _PERSONAL_STATES
                or type(row.get("at")) is not int
                or not 0 <= row["at"] <= 2**53
                for row in timeline
            )
            or timeline[-1]["state"] != status["state"]
        ):
            raise ValueError()

        receipt_values = (
            status.get("receipt_digest"), status.get("measurement_digest")
        )
        if status["verified_effect"]:
            if (
                type(status.get("receipt_id")) is not str
                or not status["receipt_id"].startswith("target-")
                or len(status["receipt_id"]) != 71
                or any(type(item) is not str or _HEX.fullmatch(item) is None
                       for item in receipt_values)
            ):
                raise ValueError()
        elif status.get("receipt_id") is not None or any(
            item is not None for item in receipt_values
        ):
            raise ValueError()
        if (
            status.get("replay_reason") not in {None, "DURABLE_VERIFIED_EFFECT"}
            or (status["state"] == "REPLAY_BLOCKED")
            != (status.get("replay_reason") == "DURABLE_VERIFIED_EFFECT")
        ):
            raise ValueError()

        if type(reservations) is not list or not reservations:
            raise ValueError()
        estimated_units, actual_units, actual_present = 0, 0, False
        for row in reservations:
            if (
                type(row) is not dict
                or set(row) != _RESERVATION_KEYS
                or row.get("provider_id") != "nebius"
                or row.get("model_id") != status["model_id"]
                or row.get("status")
                not in {"RESERVED", "COMMITTED", "UNKNOWN", "RELEASED"}
                or type(row.get("estimated_units")) is not int
                or not 1 <= row["estimated_units"] <= 1_000_000
                or (
                    row.get("actual_units") is not None
                    and (
                        type(row["actual_units"]) is not int
                        or not 0 <= row["actual_units"] <= 1_000_000
                    )
                )
                or any(
                    type(row.get(name)) is not expected
                    for name, expected in (
                        ("reservation_id", str), ("watch_id", str),
                        ("trace_id", str), ("created_at", int), ("reason", str),
                    )
                )
            ):
                raise ValueError()
            estimated_units += row["estimated_units"]
            if row["actual_units"] is not None:
                actual_units += row["actual_units"]
                actual_present = True
        if estimated_units > 1_000_000 or actual_units > 1_000_000:
            raise ValueError()
    except (KeyError, TypeError, ValueError, RoutingError, ProviderError):
        return _personal_unavailable()

    return {
        "schema": "aioa.nebius-personal-ai-view.v1",
        "status": "READY",
        "evidence_available": True,
        "read_only": True,
        "operation_id": status["operation_id"],
        "target_id": status["target_id"],
        "proposal_id": status["proposal_id"],
        "provider": {
            "provider_id": "nebius",
            "model_id": status["model_id"],
            "execution_mode": status["execution_mode"],
            "mode": status.get("provider_mode", status["execution_mode"]),
            "authority": "ADVISORY_ONLY",
            "fallback": False,
            "estimated_units": estimated_units,
            "actual_units": actual_units if actual_present else None,
        },
        "memory": dict(memory),
        "cpl": {"status": status["cpl_status"] if status["schema"] == "aioa.personal-ai-demo.v2" else "NOT_RUN",
                "authority": "ADVISORY_ONLY",
                "scope": ("LEGACY_UNATTESTED" if status["schema"] == "aioa.personal-ai-demo.v1" else
                          "SEPARATE_SYNTHETIC_DEMONSTRATION" if status["cpl_status"] == "COMPLETED_ADVISORY" else "NOT_RUN")},
        "verification": {
            "status": verification,
            "delta": "ZERO_WRITE",
        },
        "approval": {"status": status["approval"]},
        "target": {"mode": status.get("target_mode", status["execution_mode"])},
        "action": dict(status["action"]) if "action" in status else None,
        "effects": {"apply_count": None if status["reconciliation_pending"] else status.get("effect_apply_count", 1 if status["verified_effect"] else 0),
                    "duplicate_count": None if status["reconciliation_pending"] else status.get("duplicate_effect_count", 0)},
        "service_guard": {
            "state": status["state"],
            "verified_effect": status["verified_effect"],
            "reconciliation_pending": status["reconciliation_pending"],
            "outcome": "UNKNOWN" if status["reconciliation_pending"] else ("VERIFIED" if status["verified_effect"] else "NOT_EXECUTED"),
        },
        "receipt": {
            "id": status["receipt_id"],
            "digest": status["receipt_digest"],
            "measurement_digest": status["measurement_digest"],
        },
        "replay": {"reason": status["replay_reason"]},
        "timeline": [dict(row) for row in timeline],
        "updated_at": status["updated_at"],
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
