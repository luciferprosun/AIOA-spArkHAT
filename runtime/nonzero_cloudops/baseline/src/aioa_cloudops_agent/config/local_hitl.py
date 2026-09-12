"""Safe-by-default Local-2 state, inventory, and approval challenge settings."""

import os
from dataclasses import dataclass
from pathlib import Path

from aioa_cloudops_agent.domain.errors import ContractValidationError

from .local_first import LocalFirstMode


def _validate_local_json_path(name: str, value: object) -> Path:
    if not isinstance(value, Path) or not str(value).strip():
        raise ContractValidationError(f"Local-2 {name} must be a non-empty Path")
    if ".." in value.parts or len(os.fsencode(value)) > 4_096:
        raise ContractValidationError(f"Local-2 {name} contains unsafe traversal or length")
    if any(parent.is_symlink() for parent in value.parents if parent.exists()):
        raise ContractValidationError(f"Local-2 {name} must not traverse a symlink")
    if value.is_symlink():
        raise ContractValidationError(f"Local-2 {name} must not be a symlink")
    return value


@dataclass(frozen=True, slots=True)
class LocalHitlSettings:
    """Non-secret settings for the complete credential-free Local-2 runtime."""

    mode: LocalFirstMode = LocalFirstMode.MOCK
    state_path: Path = Path(".local/aioa-local-hitl-state.json")
    inventory_path: Path = Path(".local/aioa-local-mock-inventory.json")
    request_ttl_seconds: int = 600

    def __post_init__(self) -> None:
        if self.mode is not LocalFirstMode.MOCK:
            raise ContractValidationError(
                "Local-2 live mode is unavailable; explicit mock mode is required"
            )
        state_path = _validate_local_json_path("state_path", self.state_path)
        inventory_path = _validate_local_json_path(
            "inventory_path", self.inventory_path
        )
        same_existing_file = False
        if state_path.exists() and inventory_path.exists():
            try:
                same_existing_file = os.path.samefile(state_path, inventory_path)
            except OSError:
                same_existing_file = False
        if (
            state_path.resolve(strict=False) == inventory_path.resolve(strict=False)
            or same_existing_file
        ):
            raise ContractValidationError(
                "Local-2 durable truth and mock inventory paths must be separate"
            )
        if (
            isinstance(self.request_ttl_seconds, bool)
            or not isinstance(self.request_ttl_seconds, int)
            or not 60 <= self.request_ttl_seconds <= 3_600
        ):
            raise ContractValidationError(
                "Local-2 request TTL must be between 60 and 3600 seconds"
            )

    @classmethod
    def from_environment(cls) -> "LocalHitlSettings":
        """Load local-only paths and TTL without discovering cloud credentials."""

        raw_mode = os.getenv("AIOA_LOCAL_MODE", LocalFirstMode.MOCK.value)
        try:
            mode = LocalFirstMode(raw_mode)
        except ValueError as error:
            raise ContractValidationError("AIOA_LOCAL_MODE must be mock or live") from error
        raw_state = os.getenv(
            "AIOA_LOCAL_HITL_STATE_PATH",
            ".local/aioa-local-hitl-state.json",
        )
        raw_inventory = os.getenv(
            "AIOA_LOCAL_INVENTORY_PATH",
            ".local/aioa-local-mock-inventory.json",
        )
        raw_ttl = os.getenv("AIOA_LOCAL_APPROVAL_TTL_SECONDS", "600")
        try:
            ttl = int(raw_ttl)
        except ValueError as error:
            raise ContractValidationError(
                "AIOA_LOCAL_APPROVAL_TTL_SECONDS must be an integer"
            ) from error
        return cls(
            mode=mode,
            state_path=Path(raw_state),
            inventory_path=Path(raw_inventory),
            request_ttl_seconds=ttl,
        )
