#!/usr/bin/env python3
"""Bounded LIVE readiness probe for Nebius Token Factory.

The probe never falls back to another provider and never writes prompt/response
content or credentials into its receipt. Network and paid inference require
separate explicit operator flags.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from providers.exact import CancellationToken, ExactCallError, ExactRequest  # noqa: E402
from providers.config import load_api_environment  # noqa: E402
from providers.messages import ChatMessage  # noqa: E402
from providers.nebius import (  # noqa: E402
    DEFAULT_NEBIUS_BASE_URL,
    DEFAULT_NEBIUS_MODEL,
    NebiusProvider,
    normalize_nebius_base_url,
)


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _repository_state() -> dict:
    def git(*args: str) -> str:
        completed = subprocess.run(
            ("git", "-C", str(REPO), *args),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=5,
        )
        return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"

    status = git("status", "--porcelain")
    return {
        "git_sha": git("rev-parse", "HEAD"),
        "git_branch": git("branch", "--show-current"),
        "worktree_clean": status == "",
    }


def _write_receipt(path: Path, payload: dict) -> None:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _safe_error(error: Exception) -> str:
    if isinstance(error, ExactCallError):
        return error.code
    message = str(error)
    if isinstance(error, RuntimeError) and message.startswith("nebius "):
        return message.replace(" ", "_").upper()
    return type(error).__name__.upper()


def _base_receipt(model: str, base_url: str) -> dict:
    return {
        "schema": "aioa.nebius-live-probe.v1",
        "created_utc": _utc_now(),
        "provider": "nebius",
        "requested_model": model,
        "base_url": normalize_nebius_base_url(base_url),
        "authority": "ADVISORY_ONLY",
        "fallback": False,
        "response_content_persisted": False,
        **_repository_state(),
    }


def run_probe(
    *,
    api_key: str,
    model: str,
    base_url: str,
    allow_network: bool,
    allow_cost: bool,
    catalog_only: bool,
    timeout_seconds: float = 20.0,
    provider_factory=NebiusProvider,
) -> dict:
    receipt = _base_receipt(model, base_url)

    if not api_key.strip():
        return {**receipt, "status": "BLOCKED", "reason": "NEBIUS_API_KEY_MISSING"}
    if not model.lower().startswith("nvidia/nemotron"):
        return {**receipt, "status": "BLOCKED", "reason": "NON_NVIDIA_NEMOTRON_MODEL_REJECTED"}
    if not allow_network:
        return {**receipt, "status": "BLOCKED", "reason": "LIVE_NETWORK_AUTHORIZATION_REQUIRED"}

    try:
        provider = provider_factory(api_key=api_key, model=model, base_url=base_url)
        catalog = provider.discover_models(timeout_seconds=timeout_seconds)
    except Exception as error:
        return {**receipt, "status": "FAIL", "reason": _safe_error(error)}

    nemotron_models = tuple(
        value for value in catalog if value.lower().startswith("nvidia/nemotron")
    )
    if catalog_only:
        # Select from the live catalog, preferring Lightning while keeping the
        # configured exact Nemotron ID as the only fallback candidate.
        preferred_model = "nvidia/Nemotron-3_5-Lightning"
        selected = (
            preferred_model
            if preferred_model in catalog
            else model if model in nemotron_models else ""
        )
        if selected:
            model = selected
            receipt["requested_model"] = selected
    receipt.update(
        catalog_model_count=len(catalog),
        catalog_nemotron_ids=list(nemotron_models),
        selected_model_in_catalog=model in catalog,
        live_catalog_validated=True,
    )
    if model not in catalog:
        return {**receipt, "status": "FAIL", "reason": "MODEL_NOT_IN_TOKEN_FACTORY_CATALOG"}
    if catalog_only:
        return {
            **receipt,
            "status": "PASS",
            "scope": "LIVE_TOKEN_FACTORY_CATALOG_ONLY",
            "live_inference_validated": False,
        }

    if not allow_cost:
        return {
            **receipt,
            "status": "BLOCKED",
            "reason": "LIVE_PROVIDER_COST_AUTHORIZATION_REQUIRED",
            "live_inference_validated": False,
        }

    request = ExactRequest(
        "nebius",
        model,
        (
            ChatMessage(
                "system",
                "Return one brief acknowledgement. This is a bounded transport smoke test.",
            ),
            ChatMessage("user", "Acknowledge the Nebius Token Factory smoke test."),
        ),
        32,
        max_input_tokens=2048,
        max_response_bytes=16384,
        timeout_seconds=timeout_seconds,
        transport_scope="LIVE",
    )
    try:
        result = provider.generate_exact(
            request,
            CancellationToken(),
            time.monotonic() + timeout_seconds + 2.0,
        )
    except Exception as error:
        return {**receipt, "status": "FAIL", "reason": _safe_error(error)}

    content_bytes = result.content.encode("utf-8")

    return {
        **receipt,
        "status": "PASS",
        "scope": "LIVE_TOKEN_FACTORY_SMOKE",
        "live_inference_validated": True,
        "reported_model": result.reported_model,
        "identity_status": result.identity_status,
        "request_id": result.request_id,
        "usage": result.usage,
        "finish_reason": result.finish_reason,
        "latency_ms": result.latency_ms,
        "response_bytes": len(content_bytes),
        "response_sha256": hashlib.sha256(content_bytes).hexdigest(),
    }


def main() -> int:
    # Match ProviderManager's established local secret-file loading. Values
    # remain only in the process environment and are never logged or receipted.
    load_api_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-only", action="store_true")
    parser.add_argument("--allow-live-network", action="store_true")
    parser.add_argument("--allow-live-provider-cost", action="store_true")
    parser.add_argument("--model", default=os.getenv("NEBIUS_MODEL", DEFAULT_NEBIUS_MODEL))
    parser.add_argument("--base-url", default=os.getenv("NEBIUS_BASE_URL", DEFAULT_NEBIUS_BASE_URL))
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()

    result = run_probe(
        api_key=os.getenv("NEBIUS_API_KEY", ""),
        model=args.model,
        base_url=args.base_url,
        allow_network=args.allow_live_network,
        allow_cost=args.allow_live_provider_cost,
        catalog_only=args.catalog_only,
        timeout_seconds=args.timeout_seconds,
    )

    if args.receipt is not None:
        _write_receipt(args.receipt, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if result["status"] == "PASS":
        return 0
    return 2 if result["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
