#!/usr/bin/env python3
"""Plan or explicitly execute a two-alias Day 15 rollback without rebuilding code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Final

EXPECTED_REGION: Final = "eu-central-1"
NAME_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,127}$")
PROFILE_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}$")
VERSION_PATTERN: Final = re.compile(r"^[1-9][0-9]*$")


class RollbackFailure(RuntimeError):
    def __init__(self, reason: str, *, status: str = "FAIL") -> None:
        self.reason = reason
        self.status = status
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class RollbackRequest:
    stack_name: str
    orchestrator_function_name: str
    executor_function_name: str
    orchestrator_previous_version: str
    executor_previous_version: str
    profile: str
    region: str


def canonical_json(value: object) -> str:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )


def _validate_request(request: RollbackRequest) -> None:
    if NAME_PATTERN.fullmatch(request.stack_name) is None:
        raise RollbackFailure("STACK_NAME_INVALID")
    if any(
        NAME_PATTERN.fullmatch(name) is None
        for name in (request.orchestrator_function_name, request.executor_function_name)
    ):
        raise RollbackFailure("FUNCTION_NAME_INVALID")
    if request.orchestrator_function_name == request.executor_function_name:
        raise RollbackFailure("FUNCTION_NAMES_MUST_DIFFER")
    if any(
        VERSION_PATTERN.fullmatch(version) is None
        for version in (request.orchestrator_previous_version, request.executor_previous_version)
    ):
        raise RollbackFailure("PREVIOUS_VERSION_INVALID")
    if PROFILE_PATTERN.fullmatch(request.profile) is None:
        raise RollbackFailure("PROFILE_NAME_INVALID")
    if request.region != EXPECTED_REGION:
        raise RollbackFailure("REGION_NOT_EU_CENTRAL_1")


def _aws_environment() -> dict[str, str]:
    blocked = {
        "AWS_ACCESS_KEY_ID",
        "AWS_DEFAULT_PROFILE",
        "AWS_DEFAULT_REGION",
        "AWS_PROFILE",
        "AWS_REGION",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in blocked and not name.startswith("AWS_ENDPOINT_URL_")
    }
    environment.pop("AWS_ENDPOINT_URL", None)
    environment.update(
        {
            "AWS_CLI_AUTO_PROMPT": "off",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "true",
            "AWS_PAGER": "",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
    )
    return environment


def _aws_json(arguments: tuple[str, ...], *, profile: str, region: str) -> dict[str, object]:
    executable = shutil.which("aws")
    if executable is None:
        raise RollbackFailure("AWS_CLI_UNAVAILABLE", status="BLOCKED")
    command = (
        executable,
        *arguments,
        "--profile",
        profile,
        "--region",
        region,
        "--no-cli-pager",
        "--output",
        "json",
    )
    try:
        result = subprocess.run(
            command,
            env=_aws_environment(),
            check=False,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RollbackFailure("AWS_READ_PREFLIGHT_UNAVAILABLE", status="BLOCKED") from error
    if result.returncode != 0:
        raise RollbackFailure("AWS_READ_PREFLIGHT_FAILED", status="BLOCKED")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RollbackFailure("AWS_READ_PREFLIGHT_INVALID", status="BLOCKED") from error
    if not isinstance(value, dict):
        raise RollbackFailure("AWS_READ_PREFLIGHT_INVALID", status="BLOCKED")
    return value


def _stack_functions(request: RollbackRequest) -> set[str]:
    response = _aws_json(
        ("cloudformation", "describe-stack-resources", "--stack-name", request.stack_name),
        profile=request.profile,
        region=request.region,
    )
    resources = response.get("StackResources")
    if not isinstance(resources, list):
        raise RollbackFailure("STACK_RESOURCE_PREFLIGHT_INVALID", status="BLOCKED")
    return {
        str(item["PhysicalResourceId"])
        for item in resources
        if isinstance(item, dict)
        and item.get("ResourceType") == "AWS::Lambda::Function"
        and isinstance(item.get("PhysicalResourceId"), str)
    }


def _alias_version(function_name: str, request: RollbackRequest) -> str:
    response = _aws_json(
        ("lambda", "get-alias", "--function-name", function_name, "--name", "live"),
        profile=request.profile,
        region=request.region,
    )
    version = response.get("FunctionVersion")
    if not isinstance(version, str) or VERSION_PATTERN.fullmatch(version) is None:
        raise RollbackFailure("LIVE_ALIAS_VERSION_INVALID", status="BLOCKED")
    return version


def _validate_version_exists(function_name: str, version: str, request: RollbackRequest) -> None:
    response = _aws_json(
        (
            "lambda",
            "get-function",
            "--function-name",
            function_name,
            "--qualifier",
            version,
        ),
        profile=request.profile,
        region=request.region,
    )
    configuration = response.get("Configuration")
    if not isinstance(configuration, dict) or configuration.get("Version") != version:
        raise RollbackFailure("PREVIOUS_VERSION_NOT_RETAINED", status="BLOCKED")


def build_plan(request: RollbackRequest) -> dict[str, object]:
    """Read current aliases and retained versions, then return one reviewable plan."""

    _validate_request(request)
    stack_functions = _stack_functions(request)
    expected_functions = {
        request.orchestrator_function_name,
        request.executor_function_name,
    }
    if not expected_functions.issubset(stack_functions):
        raise RollbackFailure("FUNCTION_NOT_OWNED_BY_STACK")
    targets = (
        (
            "executor",
            request.executor_function_name,
            request.executor_previous_version,
        ),
        (
            "orchestrator",
            request.orchestrator_function_name,
            request.orchestrator_previous_version,
        ),
    )
    aliases: list[dict[str, object]] = []
    for role, function_name, previous_version in targets:
        current_version = _alias_version(function_name, request)
        _validate_version_exists(function_name, previous_version, request)
        aliases.append(
            {
                "alias": "live",
                "current_version": current_version,
                "function_name": function_name,
                "pending": current_version != previous_version,
                "role": role,
                "target_version": previous_version,
            }
        )
    plan: dict[str, object] = {
        "aliases": aliases,
        "operation": "alias-only-rollback-no-rebuild",
        "region": request.region,
        "schema_version": 1,
        "stack_name": request.stack_name,
    }
    plan["plan_sha256"] = hashlib.sha256(canonical_json(plan).encode("utf-8")).hexdigest()
    return plan


def _update_alias(function_name: str, version: str, request: RollbackRequest) -> None:
    _aws_json(
        (
            "lambda",
            "update-alias",
            "--function-name",
            function_name,
            "--name",
            "live",
            "--function-version",
            version,
        ),
        profile=request.profile,
        region=request.region,
    )


def execute_plan(
    request: RollbackRequest,
    plan: dict[str, object],
    *,
    confirmed_sha256: str | None,
) -> dict[str, object]:
    if confirmed_sha256 != plan.get("plan_sha256"):
        raise RollbackFailure("PLAN_CONFIRMATION_REQUIRED", status="BLOCKED")
    aliases = plan.get("aliases")
    if not isinstance(aliases, list):
        raise RollbackFailure("ROLLBACK_PLAN_INVALID")
    for alias in aliases:
        if not isinstance(alias, dict) or not alias.get("pending"):
            continue
        function_name = alias.get("function_name")
        version = alias.get("target_version")
        if not isinstance(function_name, str) or not isinstance(version, str):
            raise RollbackFailure("ROLLBACK_PLAN_INVALID")
        try:
            _update_alias(function_name, version, request)
        except RollbackFailure as error:
            raise RollbackFailure("ALIAS_RECONCILIATION_REQUIRED", status="PARTIAL") from error
    verified = build_plan(request)
    verified_aliases = verified.get("aliases", [])
    if not isinstance(verified_aliases, list) or any(
        isinstance(alias, dict) and alias.get("pending") for alias in verified_aliases
    ):
        raise RollbackFailure("ALIAS_RECONCILIATION_REQUIRED", status="PARTIAL")
    return {
        "plan_sha256": plan["plan_sha256"],
        "schema_version": 1,
        "status": "PASS",
        "verification": "ALIASES_MATCH_CAPTURED_VERSIONS",
    }


def _exit_code(status: str) -> int:
    return {"PASS": 0, "FAIL": 1, "PARTIAL": 2, "BLOCKED": 3}.get(status, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stack-name", required=True)
    parser.add_argument("--orchestrator-function-name", required=True)
    parser.add_argument("--executor-function-name", required=True)
    parser.add_argument("--orchestrator-previous-version", required=True)
    parser.add_argument("--executor-previous-version", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-plan-sha256")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    request = RollbackRequest(
        stack_name=args.stack_name,
        orchestrator_function_name=args.orchestrator_function_name,
        executor_function_name=args.executor_function_name,
        orchestrator_previous_version=args.orchestrator_previous_version,
        executor_previous_version=args.executor_previous_version,
        profile=args.profile,
        region=args.region,
    )
    try:
        plan = build_plan(request)
        if args.execute:
            payload = execute_plan(
                request,
                plan,
                confirmed_sha256=args.confirm_plan_sha256,
            )
        else:
            payload = {"plan": plan, "schema_version": 1, "status": "PASS"}
    except RollbackFailure as error:
        payload = {"reasons": [error.reason], "schema_version": 1, "status": error.status}
    if args.json:
        print(canonical_json(payload))
    else:
        reasons = ",".join(payload.get("reasons", [])) or "-"
        print(f"DAY15_ALIAS_ROLLBACK {payload['status']} reasons={reasons}")
    return _exit_code(str(payload["status"]))


if __name__ == "__main__":
    raise SystemExit(main())
