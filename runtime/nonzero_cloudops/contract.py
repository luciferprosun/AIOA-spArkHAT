"""Dependency-free discovery and configuration of the Core-owned capability."""

from __future__ import annotations

import importlib.metadata
import sys
from dataclasses import dataclass

MODULE_ID = "nonzero-cloudops"
CONTRACT_VERSION = "nonzero-native-v1"
JUDGE_SHA = "4fafed8b1a877e55d96ddd9baea0a737fbeeaa4a"
CORE_BASELINE_SHA = "5f30f092f7a20035ed1caf4a8e22397673f598df"
DEPENDENCIES = {"pydantic": "2.13.4", "uuid6": "2025.0.1"}
CAPABILITIES = (
    "investigate",
    "propose",
    "request-approval",
    "record-decision",
    "execute-approved-portable",
    "verify",
    "inspect-evidence",
)


class NonZeroError(RuntimeError):
    """Fixed public error code, never raw dependency exceptions or credentials."""

    def __init__(self, code: str, status: int = 503):
        super().__init__(code)
        self.code, self.status = code, status


@dataclass(frozen=True, slots=True)
class ModuleConfig:
    enabled: bool = True
    backend: str = "portable"
    aws_enabled: bool = False
    expected_source_sha: str = JUDGE_SHA
    request_ttl_seconds: int = 600
    max_runs: int = 64
    max_output_bytes: int = 524288
    max_trace_bytes: int = 32 * 1024 * 1024

    def __post_init__(self):
        if type(self.enabled) is not bool or type(self.aws_enabled) is not bool:
            raise NonZeroError("NONZERO_CONFIG_INVALID", 400)
        if self.backend not in ("portable", "aws") or type(self.backend) is not str:
            raise NonZeroError("NONZERO_CONFIG_INVALID", 400)
        if (
            type(self.expected_source_sha) is not str
            or self.expected_source_sha != JUDGE_SHA
        ):
            raise NonZeroError("NONZERO_SOURCE_IDENTITY_MISMATCH", 409)
        bounds = (
            (self.request_ttl_seconds, 60, 3600),
            (self.max_runs, 1, 128),
            (self.max_output_bytes, 16384, 1048576),
            (self.max_trace_bytes, 1048576, 64 * 1024 * 1024),
        )
        if any(
            type(value) is not int or not lower <= value <= upper
            for value, lower, upper in bounds
        ):
            raise NonZeroError("NONZERO_CONFIG_INVALID", 400)
        if self.backend == "portable" and self.aws_enabled:
            raise NonZeroError("NONZERO_CONFIG_INVALID", 400)


def parse_config(config=None) -> ModuleConfig:
    if config is None:
        return ModuleConfig()
    if isinstance(config, ModuleConfig):
        config.__post_init__()
        return config
    if type(config) is not dict:
        raise NonZeroError("NONZERO_CONFIG_INVALID", 400)
    try:
        return ModuleConfig(**config)
    except (TypeError, ValueError) as error:
        raise NonZeroError("NONZERO_CONFIG_INVALID", 400) from error


def module_descriptor(config=None) -> dict:
    code, missing, backend = "AVAILABLE", [], "portable"
    try:
        selected = parse_config(config)
        backend = selected.backend
        if not selected.enabled:
            code = "NONZERO_DISABLED"
        elif backend == "aws":
            code = (
                "NONZERO_AWS_BACKEND_NOT_CERTIFIED"
                if selected.aws_enabled
                else "NONZERO_AWS_EXPLICIT_ENABLEMENT_REQUIRED"
            )
    except NonZeroError as error:
        code = error.code
    if sys.version_info < (3, 11):  # noqa: UP036 - explicit fail-closed discovery contract
        missing.append("python>=3.11")
        if code == "AVAILABLE":
            code = "NONZERO_UNAVAILABLE_REQUIRES_PYTHON_3_11"
    for package, expected in DEPENDENCIES.items():
        try:
            if importlib.metadata.version(package) != expected:
                missing.append(package + "==" + expected)
        except importlib.metadata.PackageNotFoundError:
            missing.append(package + "==" + expected)
    if missing and code == "AVAILABLE":
        code = "NONZERO_OPTIONAL_DEPENDENCIES_UNAVAILABLE"
    return {
        "module": MODULE_ID,
        "product_name": "AIOA spArkHAT",
        "contract_version": CONTRACT_VERSION,
        "registered": True,
        "available": code == "AVAILABLE",
        "availability_code": code,
        "missing_requirements": missing,
        "capabilities": list(CAPABILITIES),
        "source_sha": JUDGE_SHA,
        "mode": backend,
        "default_mode": "portable",
        "provider": "mock",
        "implementation": "CORE_NATIVE",
        "authority": "EXPLICIT_HUMAN_APPROVAL_SYNTHETIC_ONLY",
        "live_aws_enabled": False,
        "external_models_enabled": False,
        "command": "/nonzero",
        "api_prefix": "/api/nonzero",
    }
