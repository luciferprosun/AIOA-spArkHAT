"""Read-only projection of explicit NVIDIA hosted-provider availability evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

MAX_BYTES = 32 * 1024
ENV_PATH = "AIOA_NVIDIA_PROVIDER_EVIDENCE"
RECOVERY_SCHEMA = "aioa.nvidia-provider-recovery.v1"
AVAILABILITY_SCHEMA = "aioa.nvidia-provider-availability.v1"
EXPECTED_HOST = "integrate.api.nvidia.com"
EXPECTED_PATH = "/v1/chat/completions"
ALLOWED_EXTERNAL_REASONS = {"TIMEOUT", "RATE_LIMIT", "AUTH", "CONNECTIVITY", "OTHER"}


def _unavailable(status: str) -> dict:
    return {
        "schema": "aioa.provider-availability-view.v1",
        "status": status,
        "provider_mode": "UNKNOWN",
        "evidence_available": False,
        "read_only": True,
    }


def _load_value() -> dict | None:
    raw_path = os.environ.get(ENV_PATH, "").strip()
    if not raw_path:
        return None
    try:
        candidate = Path(raw_path).expanduser()
        if candidate.is_symlink():
            raise ValueError("symlink evidence")
        path = candidate.resolve(strict=True)
        stat = path.stat()
        if not path.is_file() or stat.st_size > MAX_BYTES:
            raise ValueError("invalid evidence file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return {}
    return value if type(value) is dict else {}


def _base(value: dict, provider_mode: str, status: str) -> dict:
    return {
        "schema": "aioa.provider-availability-view.v1",
        "status": status,
        "provider_mode": provider_mode,
        "evidence_available": True,
        "read_only": True,
        "checked_at_utc": value.get("checked_at_utc"),
        "model": value.get("model"),
        "endpoint_host": value.get("endpoint_host"),
    }


def provider_availability() -> dict:
    value = _load_value()
    if value is None:
        return _unavailable("NOT_CONFIGURED")
    if not value:
        return _unavailable("INVALID_EVIDENCE")
    schema = value.get("schema")
    if schema == RECOVERY_SCHEMA:
        smoke = value.get("smoke_result")
        digest = value.get("smoke_result_sha256")
        doctor = value.get("doctor")
        valid = (
            value.get("status") == "RECOVERED"
            and smoke == "NV_OK"
            and type(digest) is str
            and digest == hashlib.sha256(smoke.encode("utf-8")).hexdigest()
            and type(doctor) is dict
            and doctor.get("connectivity") == "PASS"
            and str(doctor.get("credential_readiness", "")).startswith("SET_")
            and value.get("endpoint_host") == EXPECTED_HOST
            and value.get("endpoint_path") == EXPECTED_PATH
            and value.get("historical_unknowns_modified") is False
            and value.get("new_24h_trial_started") is False
            and type(value.get("checked_at_utc")) is str
            and type(value.get("model")) is str
        )
        if not valid:
            return _unavailable("INVALID_EVIDENCE")
        return _base(value, "LIVE", "RECOVERED")

    if schema == AVAILABILITY_SCHEMA:
        reason = value.get("reason")
        valid = (
            value.get("status") == "EXTERNAL_UNAVAILABLE"
            and reason in ALLOWED_EXTERNAL_REASONS
            and value.get("endpoint_host") == EXPECTED_HOST
            and type(value.get("checked_at_utc")) is str
            and type(value.get("model")) is str
            and value.get("live_call_succeeded") is False
        )
        if not valid:
            return _unavailable("INVALID_EVIDENCE")
        result = _base(value, "EXTERNAL_UNAVAILABLE", "EXTERNAL_UNAVAILABLE")
        result["reason"] = reason
        return result
    return _unavailable("INVALID_EVIDENCE")
