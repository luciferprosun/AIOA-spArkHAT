"""Explicit safe-by-default configuration for Local-First Phase 1."""

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from aioa_cloudops_agent.domain.errors import ContractValidationError


class LocalFirstMode(StrEnum):
    """Closed runtime selection with no implicit live-to-mock fallback."""

    MOCK = "mock"
    LIVE = "live"


@dataclass(frozen=True, slots=True)
class LocalFirstSettings:
    """Non-secret local composition settings."""

    mode: LocalFirstMode = LocalFirstMode.MOCK
    state_path: Path = Path(".local/aioa-local-phase1-state.json")

    def __post_init__(self) -> None:
        if not isinstance(self.mode, LocalFirstMode):
            raise ContractValidationError("local mode must be mock or live")
        if not isinstance(self.state_path, Path):
            raise ContractValidationError("local state_path must be a Path")
        if not str(self.state_path).strip():
            raise ContractValidationError("local state_path must not be empty")
        if ".." in self.state_path.parts or len(os.fsencode(self.state_path)) > 4_096:
            raise ContractValidationError(
                "local state_path contains unsafe traversal or length"
            )
        if any(
            parent.is_symlink()
            for parent in self.state_path.parents
            if parent.exists()
        ):
            raise ContractValidationError("local state_path must not traverse a symlink")
        if self.state_path.is_symlink():
            raise ContractValidationError("local state_path must not be a symlink")

    @classmethod
    def from_environment(cls) -> "LocalFirstSettings":
        """Load explicit mode and state path without discovering AWS credentials."""

        raw_mode = os.getenv("AIOA_LOCAL_MODE", LocalFirstMode.MOCK.value)
        raw_path = os.getenv("AIOA_LOCAL_STATE_PATH", ".local/aioa-local-phase1-state.json")
        try:
            mode = LocalFirstMode(raw_mode)
        except ValueError as error:
            raise ContractValidationError("AIOA_LOCAL_MODE must be mock or live") from error
        if not raw_path.strip():
            raise ContractValidationError("AIOA_LOCAL_STATE_PATH must not be empty")
        return cls(mode=mode, state_path=Path(raw_path))
