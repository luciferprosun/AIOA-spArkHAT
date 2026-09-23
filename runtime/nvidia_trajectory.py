"""Read-only ATIF-v1.7 projection of deterministic NVIDIA competition evidence."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any


ATIF_VERSION = "ATIF-v1.7"
EXPECTED_DEMO_SCHEMA = "aioa.nvidia-competition-demo.v1"
EXPECTED_EVENT_COUNT = 14
PROJECTION_KIND = "DETERMINISTIC_EVIDENCE_PROJECTION"


class TrajectoryExportError(ValueError):
    """The source artifact cannot be projected without weakening evidence bounds."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrajectoryExportError(f"INVALID_FIELD:{field}")
    return value


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _validate_source(demo: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if demo.get("schema") != EXPECTED_DEMO_SCHEMA:
        raise TrajectoryExportError("UNSUPPORTED_DEMO_SCHEMA")
    if demo.get("execution_mode") != "TEST_FIXTURE":
        raise TrajectoryExportError("SOURCE_NOT_TEST_FIXTURE")
    if demo.get("live_provider_claimed") is not False:
        raise TrajectoryExportError("LIVE_PROVIDER_CLAIM_REJECTED")

    safety = _mapping(demo.get("safety"), "safety")
    if safety.get("provider_output_authority") is not False:
        raise TrajectoryExportError("PROVIDER_AUTHORITY_REJECTED")
    if safety.get("hidden_chain_of_thought_recorded") is not False:
        raise TrajectoryExportError("HIDDEN_REASONING_SOURCE_REJECTED")
    if safety.get("human_bound_effect_authority") is not True:
        raise TrajectoryExportError("HUMAN_AUTHORITY_NOT_BOUND")
    duplicate_effects = safety.get("duplicate_effects")
    if type(duplicate_effects) is not int or duplicate_effects != 0:
        raise TrajectoryExportError("DUPLICATE_EFFECT_EVIDENCE_INVALID")

    events = demo.get("events")
    if not isinstance(events, list) or len(events) != EXPECTED_EVENT_COUNT:
        raise TrajectoryExportError("EVENT_SET_INVALID")
    validated: list[Mapping[str, Any]] = []
    for index, raw_event in enumerate(events, start=1):
        event = _mapping(raw_event, f"events[{index}]")
        for key in ("stage", "status", "authority"):
            if not isinstance(event.get(key), str) or not event.get(key):
                raise TrajectoryExportError(f"EVENT_FIELD_INVALID:{index}:{key}")
        validated.append(event)
    return validated


def competition_demo_to_atif(demo: Mapping[str, Any]) -> dict[str, Any]:
    """Project bounded deterministic competition evidence into ATIF-v1.7 JSON."""
    if not isinstance(demo, Mapping):
        raise TrajectoryExportError("SOURCE_NOT_OBJECT")
    events = _validate_source(demo)
    source_digest = _canonical_sha256(demo)

    steps: list[dict[str, Any]] = [
        {
            "step_id": 1,
            "source": "system",
            "message": (
                "AIOA spArkHAT deterministic competition evidence projection; "
                "TEST_FIXTURE only."
            ),
            "extra": {
                "projection_kind": PROJECTION_KIND,
                "source_schema": EXPECTED_DEMO_SCHEMA,
            },
        }
    ]
    for step_id, event in enumerate(events, start=2):
        steps.append(
            {
                "step_id": step_id,
                "source": "system",
                "message": f"{event['stage']}: {event['status']}",
                "extra": {
                    "stage": event["stage"],
                    "status": event["status"],
                    "authority": event["authority"],
                    "projection_kind": "SYSTEM_EVIDENCE_EVENT",
                },
            }
        )

    return {
        "schema_version": ATIF_VERSION,
        "session_id": f"aioa-fixture-{source_digest[:16]}",
        "trajectory_id": f"competition-{source_digest[:16]}",
        "agent": {
            "name": str(demo.get("product_name") or "AIOA spArkHAT"),
            "version": EXPECTED_DEMO_SCHEMA,
            "extra": {
                "provider_mode": "TEST_FIXTURE",
                "projection_kind": PROJECTION_KIND,
            },
        },
        "steps": steps,
        "notes": (
            "Read-only ATIF projection of deterministic AIOA competition evidence. "
            "Not a live provider transcript; no hidden reasoning is exported."
        ),
        "extra": {
            "projection_kind": PROJECTION_KIND,
            "source_schema": EXPECTED_DEMO_SCHEMA,
            "source_canonical_json_sha256": source_digest,
            "execution_mode": "TEST_FIXTURE",
            "live_provider_claimed": False,
            "raw_provider_trace": False,
        },
    }
