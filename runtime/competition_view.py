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
        "provider_mode": "EXTERNAL_UNAVAILABLE",
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
        "effect": {
            key: effect.get(key)
            for key in (
                "status", "verified_effect", "dispatch_attempted", "effect_count",
                "replay_status", "replay_dispatch_attempted", "effect_count_after_replay",
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
