"""Fail-closed configuration for the portable container entrypoint."""

import os
import re
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from aioa_cloudops_agent.domain.errors import ContractValidationError

from .local_hitl import LocalHitlSettings
from .runtime import (
    PORTABLE_MODEL_ID,
    ModelProviderName,
    RuntimeMode,
    RuntimeSettings,
)

_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")
_SOURCE_COMMIT = re.compile(r"(?:unknown|[0-9a-f]{7,64})")
_LOG_LEVELS = frozenset({"INFO", "WARNING", "ERROR"})
_REQUEST_SIZE_LIMIT_BYTES = 16_384
_REQUEST_TIMEOUT_SECONDS = 10


def _installed_version() -> str:
    try:
        return metadata.version("aioa-nonzero-cloudops-agent")
    except metadata.PackageNotFoundError:
        return "0.2.0rc1"


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ContractValidationError(f"{name} must be an integer") from error
    if not minimum <= value <= maximum:
        raise ContractValidationError(
            f"{name} must be between {minimum} and {maximum}"
        )
    return value


def _exact(name: str, default: str, expected: str) -> str:
    value = os.getenv(name, default)
    if value != expected:
        raise ContractValidationError(f"{name} must be exactly {expected}")
    return value


@dataclass(frozen=True, slots=True)
class PortableServerSettings:
    """Application-owned deployment values for the credential-free runtime."""

    runtime: RuntimeSettings
    local: LocalHitlSettings
    application_version: str
    source_commit: str
    host: str
    port: int
    allowed_origins: str
    allowed_egress: str
    storage_mode: str
    token_path: Path
    request_timeout_seconds: int
    provider_timeout_seconds: int
    retry_budget: int
    request_size_limit_bytes: int
    log_level: str
    public_mode_label: str
    sandbox_mode: str
    authority_mode: str

    def __post_init__(self) -> None:
        if (
            self.runtime.mode is not RuntimeMode.PORTABLE
            or self.runtime.model_provider is not ModelProviderName.MOCK
            or self.runtime.aws_calls_allowed
        ):
            raise ContractValidationError(
                "portable server requires portable mode and the mock provider"
            )
        if _VERSION.fullmatch(self.application_version) is None:
            raise ContractValidationError("APPLICATION_VERSION is invalid")
        if _SOURCE_COMMIT.fullmatch(self.source_commit) is None:
            raise ContractValidationError("SOURCE_COMMIT is invalid")
        if self.host not in {"127.0.0.1", "0.0.0.0"}:
            raise ContractValidationError("AIOA_HOST must be 127.0.0.1 or 0.0.0.0")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65_535:
            raise ContractValidationError("AIOA_PORT must be between 1 and 65535")
        for name, value, expected in (
            ("AIOA_ALLOWED_ORIGINS", self.allowed_origins, "same-origin"),
            ("AIOA_ALLOWED_EGRESS", self.allowed_egress, "none"),
            ("AIOA_STORAGE_MODE", self.storage_mode, "file"),
            ("AIOA_PUBLIC_MODE_LABEL", self.public_mode_label, "DEMO_SANDBOX"),
            ("AIOA_SANDBOX_MODE", self.sandbox_mode, "MOCK_OFFLINE"),
            (
                "AIOA_AUTHORITY_MODE",
                self.authority_mode,
                "HUMAN_APPROVAL_REQUIRED",
            ),
        ):
            if value != expected:
                raise ContractValidationError(f"{name} must be exactly {expected}")
        for name, value, expected in (
            ("AIOA_REQUEST_TIMEOUT_SECONDS", self.request_timeout_seconds, 10),
            ("AIOA_PROVIDER_TIMEOUT_SECONDS", self.provider_timeout_seconds, 0),
            ("AIOA_RETRY_BUDGET", self.retry_budget, 0),
            ("AIOA_REQUEST_SIZE_LIMIT_BYTES", self.request_size_limit_bytes, 16_384),
        ):
            if isinstance(value, bool) or value != expected:
                raise ContractValidationError(f"{name} must be exactly {expected}")
        if self.log_level not in _LOG_LEVELS:
            raise ContractValidationError("AIOA_LOG_LEVEL must be INFO, WARNING, or ERROR")
        if (
            not isinstance(self.token_path, Path)
            or ".." in self.token_path.parts
            or not str(self.token_path).strip()
            or len(os.fsencode(self.token_path)) > 4_096
        ):
            raise ContractValidationError("AIOA_LOCAL_API_TOKEN_PATH is invalid")

    @classmethod
    def from_environment(cls) -> "PortableServerSettings":
        """Load the closed portable contract without inspecting ambient credentials."""

        runtime = RuntimeSettings.from_environment()
        local = LocalHitlSettings.from_environment()
        session_ttl = _integer(
            "AIOA_SESSION_TTL_SECONDS",
            local.request_ttl_seconds,
            minimum=60,
            maximum=3_600,
        )
        if (
            "AIOA_SESSION_TTL_SECONDS" in os.environ
            and "AIOA_LOCAL_APPROVAL_TTL_SECONDS" in os.environ
            and session_ttl != local.request_ttl_seconds
        ):
            raise ContractValidationError("portable session TTL settings conflict")
        local = LocalHitlSettings(
            mode=local.mode,
            state_path=local.state_path,
            inventory_path=local.inventory_path,
            request_ttl_seconds=session_ttl,
        )
        model_id = os.getenv("AIOA_MODEL_ID", PORTABLE_MODEL_ID)
        if model_id != PORTABLE_MODEL_ID:
            raise ContractValidationError(
                f"AIOA_MODEL_ID must be exactly {PORTABLE_MODEL_ID} in portable mode"
            )
        return cls(
            runtime=runtime,
            local=local,
            application_version=os.getenv("APPLICATION_VERSION", _installed_version()),
            source_commit=os.getenv("SOURCE_COMMIT", "unknown"),
            host=os.getenv("AIOA_HOST", "127.0.0.1"),
            port=_integer("AIOA_PORT", 8_765, minimum=1, maximum=65_535),
            allowed_origins=_exact("AIOA_ALLOWED_ORIGINS", "same-origin", "same-origin"),
            allowed_egress=_exact("AIOA_ALLOWED_EGRESS", "none", "none"),
            storage_mode=_exact("AIOA_STORAGE_MODE", "file", "file"),
            token_path=Path(
                os.getenv("AIOA_LOCAL_API_TOKEN_PATH", ".local/aioa-local-api.token")
            ),
            request_timeout_seconds=_integer(
                "AIOA_REQUEST_TIMEOUT_SECONDS",
                _REQUEST_TIMEOUT_SECONDS,
                minimum=_REQUEST_TIMEOUT_SECONDS,
                maximum=_REQUEST_TIMEOUT_SECONDS,
            ),
            provider_timeout_seconds=_integer(
                "AIOA_PROVIDER_TIMEOUT_SECONDS", 0, minimum=0, maximum=0
            ),
            retry_budget=_integer("AIOA_RETRY_BUDGET", 0, minimum=0, maximum=0),
            request_size_limit_bytes=_integer(
                "AIOA_REQUEST_SIZE_LIMIT_BYTES",
                _REQUEST_SIZE_LIMIT_BYTES,
                minimum=_REQUEST_SIZE_LIMIT_BYTES,
                maximum=_REQUEST_SIZE_LIMIT_BYTES,
            ),
            log_level=os.getenv("AIOA_LOG_LEVEL", "INFO"),
            public_mode_label=_exact(
                "AIOA_PUBLIC_MODE_LABEL", "DEMO_SANDBOX", "DEMO_SANDBOX"
            ),
            sandbox_mode=_exact(
                "AIOA_SANDBOX_MODE", "MOCK_OFFLINE", "MOCK_OFFLINE"
            ),
            authority_mode=_exact(
                "AIOA_AUTHORITY_MODE",
                "HUMAN_APPROVAL_REQUIRED",
                "HUMAN_APPROVAL_REQUIRED",
            ),
        )
