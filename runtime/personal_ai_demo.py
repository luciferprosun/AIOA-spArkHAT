"""Restart-safe Personal AI scenario over existing memory and ServiceGuard ports.

The coordinator owns no model, memory, approval, or effect authority.  It
stores a small redacted projection so an operator can resume an uncertain
effect without persisting prompts, responses, private HAT text, or secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
from typing import Callable

from runtime.core_admission import Capability
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.lite import MemoryContext
from runtime.mission.contracts import logical_id
from runtime.nonzero_cloudops.state.files import (
    atomic_write_private_json,
    locked_private_file,
    open_local_payload,
    read_private_json,
    seal_local_payload,
    validate_local_path,
)
from runtime.service_guard.service import CoreServiceGuard


_PAYLOAD_TYPE = "AIOA_PERSONAL_AI_DEMO"
_STATES = frozenset(
    {
        "ADVISORY",
        "VERIFIED",
        "ZERO_WRITE",
        "APPROVAL_REQUIRED",
        "APPROVED",
        "EXECUTED",
        "RECONCILED",
        "REPLAY_BLOCKED",
    }
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_STATE_KEYS = frozenset(
    {
        "schema",
        "operation_id",
        "target_id",
        "proposal_id",
        "scope_digest",
        "provider_id",
        "model_id",
        "execution_mode",
        "model_authority",
        "memory",
        "cpl_status",
        "verification_status",
        "state",
        "timeline",
        "proposal_digest",
        "approval_digest",
        "receipt_id",
        "receipt_digest",
        "measurement_digest",
        "verified_effect",
        "reconciliation_pending",
        "replay_reason",
        "updated_at",
    }
)


class PersonalAIDemoError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, repr=False)
class PersonalAIDemoBindings:
    memory_retrieve: Callable[[str], MemoryContext] | None
    guard: CoreServiceGuard
    scheduler: object
    execution_mode: str

    def __post_init__(self) -> None:
        if (
            self.memory_retrieve is not None
            and not callable(self.memory_retrieve)
        ):
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_BINDINGS")
        if (
            type(self.guard) is not CoreServiceGuard
            or self.execution_mode not in {"LIVE", "FIXTURE"}
            or getattr(getattr(self.scheduler, "bindings", None), "service_guard", None)
            is None
            or self.scheduler.bindings.service_guard.guard is not self.guard
        ):
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_BINDINGS")


class PersonalAIDemoService:
    """Project one explicit operator scenario without creating new authority."""

    def __init__(self, state_root: str | Path, bindings: PersonalAIDemoBindings):
        if type(bindings) is not PersonalAIDemoBindings:
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_BINDINGS")
        root = Path(state_root).absolute()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = root.stat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise PersonalAIDemoError("UNSAFE_PERSONAL_AI_DIRECTORY")
        self.bindings = bindings
        self.path = root / "personal-ai-state.json"
        self.lock_path = root / "personal-ai-state.lock"
        validate_local_path(self.path)
        validate_local_path(self.lock_path)

    def _now(self) -> int:
        try:
            value = self.bindings.scheduler.bindings.clock()
        except Exception:
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_CLOCK") from None
        if type(value) not in (int, float) or not 0 <= value <= 2**53:
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_CLOCK")
        return int(value)

    @staticmethod
    def _timeline_valid(value: object) -> bool:
        return (
            type(value) is list
            and 1 <= len(value) <= 16
            and all(
                type(item) is dict
                and set(item) == {"state", "at"}
                and item.get("state") in _STATES
                and type(item.get("at")) is int
                and 0 <= item["at"] <= 2**53
                for item in value
            )
        )

    def _validate_state(self, value: object) -> dict:
        if (
            type(value) is not dict
            or set(value) != _STATE_KEYS
            or value.get("schema") != "aioa.personal-ai-demo.v1"
            or value.get("execution_mode") not in {"LIVE", "FIXTURE"}
            or value.get("model_authority") != "ADVISORY_ONLY"
            or value.get("state") not in _STATES
            or not self._timeline_valid(value.get("timeline"))
            or value["timeline"][-1]["state"] != value["state"]
            or any(
                type(value.get(name)) is not str or not value[name]
                for name in (
                    "operation_id",
                    "target_id",
                    "proposal_id",
                    "provider_id",
                    "model_id",
                    "cpl_status",
                    "verification_status",
                )
            )
            or any(
                type(value.get(name)) is not str or _HEX.fullmatch(value[name]) is None
                for name in ("proposal_id", "scope_digest", "proposal_digest")
            )
            or any(
                item is not None
                and (type(item) is not str or _HEX.fullmatch(item) is None)
                for item in (
                    value.get("approval_digest"),
                    value.get("receipt_digest"),
                    value.get("measurement_digest"),
                )
            )
            or type(value.get("verified_effect")) is not bool
            or type(value.get("reconciliation_pending")) is not bool
            or type(value.get("updated_at")) is not int
            or (
                value.get("receipt_id") is not None
                and (
                    type(value["receipt_id"]) is not str
                    or not value["receipt_id"].startswith("target-")
                    or len(value["receipt_id"]) != 71
                )
            )
            or value.get("replay_reason")
            not in {None, "DURABLE_VERIFIED_EFFECT"}
            or value.get("cpl_status") not in {"VERIFIED", "ZERO_WRITE"}
            or value.get("verification_status") != value.get("cpl_status")
        ):
            raise PersonalAIDemoError("PERSONAL_AI_STATE_INTEGRITY")
        memory = value.get("memory")
        if (
            type(memory) is not dict
            or set(memory)
            != {
                "status",
                "selected_count",
                "eligible_count",
                "context_digest",
                "context_byte_units",
                "truncated",
                "execution_authority",
            }
            or type(memory["status"]) is not str
            or any(
                type(memory[name]) is not int or not 0 <= memory[name] <= 1024
                for name in ("selected_count", "eligible_count", "context_byte_units")
            )
            or type(memory["truncated"]) is not bool
            or memory["execution_authority"] is not False
            or type(memory["context_digest"]) is not str
            or _HEX.fullmatch(memory["context_digest"]) is None
        ):
            raise PersonalAIDemoError("PERSONAL_AI_STATE_INTEGRITY")
        return dict(value)

    def _require_binding(self, state: dict) -> dict:
        profile = self.bindings.scheduler.profile
        if (
            state["scope_digest"]
            != canonical_sha256(list(self.bindings.guard.policy.scope.binding()))
            or state["target_id"] != self.bindings.guard.policy.target_id
            or state["operation_id"]
            != self.bindings.scheduler.bindings.service_guard.operation_id
            or state["provider_id"] != profile.provider_id
            or state["model_id"] != profile.model_id
            or state["execution_mode"] != self.bindings.execution_mode
        ):
            raise PersonalAIDemoError("PERSONAL_AI_BINDING_MISMATCH")
        return state

    def _load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            payload, _digest = open_local_payload(
                read_private_json(self.path), payload_type=_PAYLOAD_TYPE
            )
            return self._require_binding(self._validate_state(dict(payload)))
        except PersonalAIDemoError:
            raise
        except Exception:
            raise PersonalAIDemoError("PERSONAL_AI_STATE_INTEGRITY") from None

    def _write(self, state: dict) -> None:
        state = self._validate_state(state)
        atomic_write_private_json(
            self.path, seal_local_payload(state, payload_type=_PAYLOAD_TYPE)
        )

    def _append(self, state: dict, selected: str) -> None:
        if selected not in _STATES:
            raise PersonalAIDemoError("INVALID_PERSONAL_AI_STATE")
        if state["timeline"][-1]["state"] != selected:
            state["timeline"].append({"state": selected, "at": self._now()})
        state["state"] = selected
        state["updated_at"] = self._now()

    @staticmethod
    def _view(state: dict) -> dict:
        return {
            "schema": state["schema"],
            "operation_id": state["operation_id"],
            "target_id": state["target_id"],
            "proposal_id": state["proposal_id"],
            "provider_id": state["provider_id"],
            "model_id": state["model_id"],
            "execution_mode": state["execution_mode"],
            "model_authority": state["model_authority"],
            "memory": dict(state["memory"]),
            "cpl_status": state["cpl_status"],
            "verification_status": state["verification_status"],
            "state": state["state"],
            "timeline": [dict(item) for item in state["timeline"]],
            "approval": "APPROVED"
            if state["approval_digest"] is not None
            else "REQUIRED",
            "verified_effect": state["verified_effect"],
            "reconciliation_pending": state["reconciliation_pending"],
            "receipt_id": state["receipt_id"],
            "receipt_digest": state["receipt_digest"],
            "measurement_digest": state["measurement_digest"],
            "replay_reason": state["replay_reason"],
            "updated_at": state["updated_at"],
        }

    def prepare(self, request: dict) -> dict:
        if type(request) is not dict or set(request) != {
            "operation_id",
            "target_id",
            "memory_query",
        }:
            raise PersonalAIDemoError("INVALID_PREPARE_REQUEST")
        operation_id = request.get("operation_id")
        target_id = request.get("target_id")
        query = request.get("memory_query")
        try:
            logical_id(operation_id)
            logical_id(target_id)
        except (TypeError, ValueError):
            raise PersonalAIDemoError("INVALID_PREPARE_REQUEST") from None
        if (
            type(query) is not str
            or not query.strip()
            or len(query.encode("utf-8")) > 4096
            or target_id != self.bindings.guard.policy.target_id
            or operation_id
            != self.bindings.scheduler.bindings.service_guard.operation_id
            or self.bindings.memory_retrieve is None
        ):
            raise PersonalAIDemoError("INVALID_PREPARE_REQUEST")

        with locked_private_file(self.lock_path, exclusive=True):
            previous = self._load()
            if previous is not None:
                if (
                    previous["operation_id"] != operation_id
                    or previous["target_id"] != target_id
                ):
                    raise PersonalAIDemoError("PERSONAL_AI_OPERATION_CONFLICT")
                return self._view(previous)

            context = self.bindings.memory_retrieve(query)
            if type(context) is not MemoryContext or context.status != "READY":
                raise PersonalAIDemoError("PRIVATE_MEMORY_UNAVAILABLE")
            if any(reference.execution_authority for reference in context.selected):
                raise PersonalAIDemoError("MEMORY_AUTHORITY_DENIED")

            result = self.bindings.guard.cycle(
                self.bindings.scheduler, operation_id
            )
            if (
                result.get("status") != "BLOCKED"
                or result.get("reason") != "CONSENT_REQUIRED"
                or result.get("dispatch_attempted") is not False
            ):
                raise PersonalAIDemoError("PREPARE_DID_NOT_STOP_FOR_APPROVAL")
            records = self.bindings.guard.inspect(
                self.bindings.guard.core.local_operator(Capability.READ), operation_id
            )
            proposal = records.get("proposal")
            if type(proposal) is not dict or records.get("intent") is not None:
                raise PersonalAIDemoError("ADVISORY_PROPOSAL_UNAVAILABLE")

            profile = self.bindings.scheduler.profile
            now = self._now()
            verification = "VERIFIED" if context.selected else "ZERO_WRITE"
            proposal_digest = canonical_sha256(proposal)
            proposal_id = canonical_sha256(
                {
                    "operation_id": operation_id,
                    "target_id": target_id,
                    "scope": list(self.bindings.guard.policy.scope.binding()),
                    "proposal_digest": proposal_digest,
                }
            )
            state = {
                "schema": "aioa.personal-ai-demo.v1",
                "operation_id": operation_id,
                "target_id": target_id,
                "proposal_id": proposal_id,
                "scope_digest": canonical_sha256(
                    list(self.bindings.guard.policy.scope.binding())
                ),
                "provider_id": profile.provider_id,
                "model_id": profile.model_id,
                "execution_mode": self.bindings.execution_mode,
                "model_authority": "ADVISORY_ONLY",
                "memory": {
                    "status": "RETRIEVED" if context.selected else "EMPTY",
                    "selected_count": len(context.selected),
                    "eligible_count": len(context.eligible),
                    "context_digest": canonical_sha256(context.prompt_json),
                    "context_byte_units": context.context_byte_units,
                    "truncated": context.truncated,
                    "execution_authority": False,
                },
                "cpl_status": verification,
                "verification_status": verification,
                "state": "APPROVAL_REQUIRED",
                "timeline": [
                    {"state": "ADVISORY", "at": now},
                    {"state": verification, "at": now},
                    {"state": "APPROVAL_REQUIRED", "at": now},
                ],
                "proposal_digest": proposal_digest,
                "approval_digest": None,
                "receipt_id": None,
                "receipt_digest": None,
                "measurement_digest": None,
                "verified_effect": False,
                "reconciliation_pending": False,
                "replay_reason": None,
                "updated_at": now,
            }
            self._write(state)
            return self._view(state)

    def approve(self, proposal_id: str) -> dict:
        if type(proposal_id) is not str or _HEX.fullmatch(proposal_id) is None:
            raise PersonalAIDemoError("INVALID_PROPOSAL_ID")
        with locked_private_file(self.lock_path, exclusive=True):
            state = self._load()
            if state is None or state["proposal_id"] != proposal_id:
                raise PersonalAIDemoError("PROPOSAL_BINDING_MISMATCH")
            if state["state"] == "APPROVED":
                return self._view(state)
            if state["state"] != "APPROVAL_REQUIRED":
                raise PersonalAIDemoError("APPROVAL_STATE_DENIED")
            records = self.bindings.guard.inspect(
                self.bindings.guard.core.local_operator(Capability.READ),
                state["operation_id"],
            )
            approval = records.get("approval")
            if approval is None:
                approval = self.bindings.guard.approve(
                    self.bindings.guard.core.local_operator(
                        Capability.OWNER_APPROVAL
                    ),
                    state["operation_id"],
                )
            state["approval_digest"] = canonical_sha256(approval)
            self._append(state, "APPROVED")
            self._write(state)
            return self._view(state)

    def resume(self, operation_id: str) -> dict:
        try:
            logical_id(operation_id)
        except (TypeError, ValueError):
            raise PersonalAIDemoError("INVALID_OPERATION_ID") from None
        with locked_private_file(self.lock_path, exclusive=True):
            state = self._load()
            if state is None or state["operation_id"] != operation_id:
                raise PersonalAIDemoError("OPERATION_BINDING_MISMATCH")
            if state["state"] == "REPLAY_BLOCKED":
                return self._view(state)
            if state["state"] not in {"APPROVED", "EXECUTED", "RECONCILED"}:
                raise PersonalAIDemoError("RESUME_STATE_DENIED")

            result = self.bindings.guard.cycle(
                self.bindings.scheduler, operation_id
            )
            status = result.get("status")
            if status == "UNKNOWN":
                if state["state"] == "APPROVED":
                    self._append(state, "EXECUTED")
                state["reconciliation_pending"] = True
                self._write(state)
                return self._view(state)
            if status == "REPLAY":
                self._append(state, "REPLAY_BLOCKED")
                state["replay_reason"] = "DURABLE_VERIFIED_EFFECT"
                state["reconciliation_pending"] = False
                self._write(state)
                return self._view(state)
            if status != "VERIFIED" or result.get("verified_effect") is not True:
                raise PersonalAIDemoError("SERVICE_GUARD_DID_NOT_VERIFY")

            records = self.bindings.guard.inspect(
                self.bindings.guard.core.local_operator(Capability.READ), operation_id
            )
            receipt, verified = records.get("receipt"), records.get("verified")
            if (
                type(receipt) is not dict
                or type(verified) is not dict
                or verified.get("verified_effect") is not True
                or type(receipt.get("receipt_id")) is not str
                or type(verified.get("measurement_digest")) is not str
                or _HEX.fullmatch(verified["measurement_digest"]) is None
            ):
                raise PersonalAIDemoError("SERVICE_GUARD_EVIDENCE_MISSING")
            if state["state"] == "APPROVED":
                self._append(state, "EXECUTED")
            self._append(state, "RECONCILED")
            state["receipt_id"] = receipt["receipt_id"]
            state["receipt_digest"] = canonical_sha256(receipt)
            state["measurement_digest"] = verified["measurement_digest"]
            state["verified_effect"] = True
            state["reconciliation_pending"] = False
            self._write(state)
            return self._view(state)

    def status(self, operation_id: str) -> dict:
        try:
            logical_id(operation_id)
        except (TypeError, ValueError):
            raise PersonalAIDemoError("INVALID_OPERATION_ID") from None
        with locked_private_file(self.lock_path, exclusive=False):
            state = self._load()
            if state is None or state["operation_id"] != operation_id:
                raise PersonalAIDemoError("OPERATION_BINDING_MISMATCH")
            return self._view(state)
