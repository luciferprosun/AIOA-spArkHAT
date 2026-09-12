#!/usr/bin/env python3
"""Validate the explicit Day 15 region and bounded judge-token expiry locally."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.day15.validate_template import (  # noqa: E402
    DEFAULT_TEMPLATE,
    TemplateFailure,
    compare_lambda_configuration_sha256,
    load_template,
)

EXPECTED_REGION: Final = "eu-central-1"
JUDGE_TOKEN_MAX_LIFETIME_SECONDS: Final = 86_400
STATUS_PRIORITY: Final = {"PASS": 0, "PARTIAL": 1, "BLOCKED": 2, "FAIL": 3}
UTC_TIMESTAMP_PATTERN: Final = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"
)


@dataclass(frozen=True, slots=True)
class CheckResult:
    status: str
    reasons: tuple[str, ...] = ()


def canonical_json(value: object) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def combine_status(*statuses: str) -> str:
    """Return the most severe stable status."""

    return max(statuses, key=lambda item: STATUS_PRIORITY.get(item, STATUS_PRIORITY["FAIL"]))


def validate_region(region: str | None) -> CheckResult:
    """Never infer deployment region from the shell or AWS configuration."""

    if region is None or not region.strip():
        return CheckResult("BLOCKED", ("EXPLICIT_REGION_REQUIRED",))
    if region != region.strip() or region != EXPECTED_REGION:
        return CheckResult("FAIL", ("REGION_NOT_EU_CENTRAL_1",))
    return CheckResult("PASS")


def _utc_now(clock: Callable[[], datetime]) -> datetime | None:
    try:
        now = clock()
    except Exception:
        return None
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() != timedelta(0):
        return None
    return now


def validate_judge_token_not_after(
    value: str | None,
    *,
    clock: Callable[[], datetime],
) -> CheckResult:
    """Require a UTC expiry strictly in the future and no more than 24 hours away."""

    if value is None or not value:
        return CheckResult("BLOCKED", ("JUDGE_TOKEN_NOT_AFTER_REQUIRED",))
    if value != value.strip() or UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        return CheckResult("FAIL", ("JUDGE_TOKEN_NOT_AFTER_NOT_UTC",))
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return CheckResult("FAIL", ("JUDGE_TOKEN_NOT_AFTER_INVALID",))
    if expiry.tzinfo is None or expiry.utcoffset() != timedelta(0):
        return CheckResult("FAIL", ("JUDGE_TOKEN_NOT_AFTER_NOT_UTC",))
    now = _utc_now(clock)
    if now is None:
        return CheckResult("BLOCKED", ("UTC_CLOCK_UNAVAILABLE",))
    if expiry <= now:
        return CheckResult("FAIL", ("JUDGE_TOKEN_NOT_AFTER_NOT_FUTURE",))
    if expiry - now > timedelta(seconds=JUDGE_TOKEN_MAX_LIFETIME_SECONDS):
        return CheckResult("FAIL", ("JUDGE_TOKEN_NOT_AFTER_EXCEEDS_24H",))
    return CheckResult("PASS")


def run_preflight(
    *,
    region: str | None,
    judge_token_not_after: str | None,
    lambda_configuration_sha256: str | None = None,
    template_path: Path = DEFAULT_TEMPLATE,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, object]:
    region_result = validate_region(region)
    token_result = validate_judge_token_not_after(judge_token_not_after, clock=clock)
    try:
        template = load_template(template_path)
        config_status, config_reasons, computed_digest = compare_lambda_configuration_sha256(
            template,
            lambda_configuration_sha256,
        )
    except TemplateFailure:
        config_status = "FAIL"
        config_reasons = ("LAMBDA_CONFIGURATION_TEMPLATE_INVALID",)
        computed_digest = None
    status = combine_status(region_result.status, token_result.status, config_status)
    return {
        "checks": [
            {
                "check_id": "D15-PREFLIGHT-REGION",
                "reasons": list(region_result.reasons),
                "status": region_result.status,
            },
            {
                "check_id": "D15-PREFLIGHT-JUDGE-TOKEN-EXPIRY",
                "reasons": list(token_result.reasons),
                "status": token_result.status,
            },
            {
                "check_id": "D15-PREFLIGHT-LAMBDA-CONFIGURATION",
                "reasons": list(config_reasons),
                "status": config_status,
            },
        ],
        "computed_lambda_configuration_sha256": computed_digest,
        "schema_version": 1,
        "status": status,
    }


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region")
    parser.add_argument("--judge-token-not-after")
    parser.add_argument("--lambda-configuration-sha256")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    payload = run_preflight(
        region=args.region,
        judge_token_not_after=args.judge_token_not_after,
        lambda_configuration_sha256=args.lambda_configuration_sha256,
        template_path=args.template,
    )
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = sorted(reason for check in payload["checks"] for reason in check["reasons"])
        print(f"DAY15_PREFLIGHT {payload['status']} reasons={','.join(reasons) or '-'}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
