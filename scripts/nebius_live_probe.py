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
import math
from decimal import Decimal, InvalidOperation
import os
import re
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
RUNTIME = REPO / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

from providers.exact import CancellationToken, ExactCallError, ExactRequest, sanitize_diagnostics  # noqa: E402
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
    exact_codes = {'INCOMPLETE_COMPLETION', 'MODEL_IDENTITY_MISMATCH', 'MISSING_REPORTED_MODEL',
                   'INVALID_PROVIDER_RESPONSE', 'TRANSPORT_TIMEOUT', 'TRANSPORT_ERROR', 'CANCELLED',
                   'DEADLINE_EXCEEDED', 'HTTP_BODY_LIMIT_EXCEEDED', 'INCOMPLETE_HTTP_BODY',
                   'OUTPUT_SIZE_EXCEEDED', 'USAGE_LIMIT_EXCEEDED', 'INVALID_REQUEST_LIMIT',
                   'INPUT_LIMIT_EXCEEDED', 'INVALID_MESSAGES', 'INVALID_TIMEOUT', 'EXACT_MODEL_REQUIRED',
                   'CONNECTION_BINDING_MISMATCH', 'UNSUPPORTED_STRICT_ENDPOINT', 'INVALID_ENDPOINT',
                   'INVALID_TRANSPORT_SCOPE', 'INVALID_RESPONSE_SCHEMA'}
    if (isinstance(error, ExactCallError) and type(error.code) is str
            and (error.code in exact_codes or re.fullmatch(r'PROVIDER_HTTP_[1-5][0-9]{2}', error.code))):
        return error.code
    message = str(error)
    if isinstance(error, RuntimeError) and message in {
            'nebius catalog unavailable', 'nebius catalog invalid', 'nebius catalog too large'}:
        return message.replace(" ", "_").upper()
    return 'TOKEN_FACTORY_ERROR'


def _safe_metadata(value) -> dict:
    """Return only bounded provider metadata; never copy arbitrary input data."""

    return sanitize_diagnostics(value)


PRICE_SOURCE = 'https://nebius.com/services/token-factory/models/nvidia-nemotron-models-inference'


def _cost_bound(quote, request):
    """Fresh explicit official quote plus conservative admission limits."""
    required = {'model_id', 'currency', 'input_usd_per_million', 'output_usd_per_million',
                'quoted_utc', 'source_url'}
    try:
        if (type(quote) is not dict or set(quote) != required
                or quote['model_id'] != request.requested_model or quote['currency'] != 'USD'
                or quote['source_url'] != PRICE_SOURCE):
            raise ValueError()
        created = dt.datetime.fromisoformat(quote['quoted_utc'].replace('Z', '+00:00'))
        age = (dt.datetime.now(dt.timezone.utc) - created).total_seconds()
        prices = [Decimal(quote[key]) for key in ('input_usd_per_million', 'output_usd_per_million')]
        if not 0 <= age <= 86400 or any(not p.is_finite() or not 0 <= p <= 100 for p in prices):
            raise ValueError()
        bound = (prices[0] * request.max_input_tokens + prices[1] * request.max_output_tokens) / 1_000_000
        if bound > Decimal('0.25'):
            raise ValueError()
        return {'usd_ceiling': '0.25', 'upper_bound_usd': str(bound),
                'input_usd_per_million': str(prices[0]), 'output_usd_per_million': str(prices[1]),
                'quoted_utc': created.isoformat(), 'source_url': PRICE_SOURCE,
                'input_bound_policy': 'utf8-bytes-plus-framing-v1'}
    except (KeyError, TypeError, ValueError, AttributeError, InvalidOperation, OverflowError):
        return None


def _safe_failure_diagnostics(error: Exception) -> dict:
    clean = _safe_metadata(getattr(error, "safe_metadata", None))
    clean.pop('provider', None)
    clean.pop('requested_model', None)
    return clean


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
    max_output_tokens: int = 256,
    provider_factory=NebiusProvider,
    cost_quote=None,
) -> dict:
    receipt = _base_receipt(model, base_url)
    receipt.update(inference_attempted=False, max_output_tokens=max_output_tokens,
                   timeout_seconds=timeout_seconds)

    if type(max_output_tokens) is not int or not 32 <= max_output_tokens <= 512:
        return {**receipt, "status": "BLOCKED", "reason": "INVALID_OUTPUT_TOKEN_LIMIT"}
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30):
        return {**receipt, 'status': 'BLOCKED', 'reason': 'INVALID_TIMEOUT'}

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
                "Return exactly: OK",
            ),
            ChatMessage("user", "Reply exactly with OK."),
        ),
        max_output_tokens,
        max_input_tokens=2048,
        max_response_bytes=16384,
        timeout_seconds=timeout_seconds,
        transport_scope="LIVE",
        bound_reasoning_tokens=True,
    )
    bound = _cost_bound(cost_quote, request)
    if bound is None:
        return {**receipt, 'status': 'BLOCKED', 'reason': 'UNVERIFIED_COST_BOUND',
                'live_inference_validated': False}
    receipt.update(cost_bound=bound, inference_attempted=True, token_limit_field='max_completion_tokens',
                   reasoning_included_in_output_bound=True)
    try:
        result = provider.generate_exact(
            request,
            CancellationToken(),
            time.monotonic() + timeout_seconds,
        )
    except Exception as error:
        return {
            **receipt,
            "status": "FAIL",
            "reason": _safe_error(error),
            "live_inference_validated": False,
            **_safe_failure_diagnostics(error),
        }

    if (
        result.provider_connection_id != "nebius"
        or result.requested_model != model
        or result.reported_model != model
        or result.identity_status != "EXACT_MATCH"
        or result.finish_reason != "stop"
        or result.transport_scope != "LIVE"
    ):
        reason = (
            "INCOMPLETE_COMPLETION"
            if result.finish_reason != "stop"
            else "MODEL_IDENTITY_MISMATCH"
        )
        return {
            **receipt,
            "status": "FAIL",
            "reason": reason,
            "live_inference_validated": False,
            **_safe_metadata({
                "finish_reason": result.finish_reason,
                "request_id": result.request_id,
                "usage": result.usage,
                "latency_ms": result.latency_ms,
            }),
        }

    content_bytes = result.content.encode("utf-8")

    return {
        **receipt,
        "status": "PASS",
        "scope": "LIVE_TOKEN_FACTORY_SMOKE",
        "live_inference_validated": True,
        "reported_model": result.reported_model,
        "identity_status": result.identity_status,
        **_safe_metadata(result.metadata()),
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
    parser.add_argument("--max-output-tokens", type=int, default=256)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument('--cost-quote', type=Path)
    args = parser.parse_args()

    paid = args.allow_live_provider_cost and not args.catalog_only
    state = _repository_state()
    frozen_main = 'd26266e54ee940d7ada30aa02783dc697618a72c'
    if paid:
        refs = [subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', ref], text=True).strip()
                for ref in ('main', 'origin/main')]
        if state['git_branch'] != 'nebius-personal-ai' or refs != [frozen_main, frozen_main]:
            print('BLOCKED: REPOSITORY_INTEGRITY_GATE')
            return 2
        if args.receipt is None:
            print('BLOCKED: NEW_RECEIPT_REQUIRED')
            return 2
    try:
        quote = json.loads(args.cost_quote.read_text()) if args.cost_quote else None
    except (OSError, ValueError):
        print('BLOCKED: INVALID_COST_QUOTE')
        return 2
    # Reserve before any network or inference; an existing receipt cannot cause
    # another paid call. A crash leaves evidence of the reserved attempt.
    descriptor = None
    if args.receipt is not None:
        try:
            descriptor = os.open(args.receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.write(descriptor, b'{"status":"UNKNOWN","reason":"PROBE_RESERVED_RECONCILE_BEFORE_RETRY"}\n')
            os.fsync(descriptor)
        except OSError:
            print('BLOCKED: RECEIPT_RESERVATION_FAILED')
            return 2
    result = run_probe(
        api_key=os.getenv("NEBIUS_API_KEY", ""),
        model=args.model,
        base_url=args.base_url,
        allow_network=args.allow_live_network,
        allow_cost=args.allow_live_provider_cost,
        catalog_only=args.catalog_only,
        timeout_seconds=args.timeout_seconds,
        max_output_tokens=args.max_output_tokens,
        cost_quote=quote,
    )

    if descriptor is not None:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.seek(0)
            stream.truncate()
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    if result["status"] == "PASS":
        return 0
    return 2 if result["status"] == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
