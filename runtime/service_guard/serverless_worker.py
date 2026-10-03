"""Narrow serverless target contract; the platform adapter supplies durable storage.

The worker has no provider, shell, local filesystem, scheduler, or approval
logic. Core ServiceGuard owns the authorization decision; a deployment store
must atomically fence target revision and persist each idempotency receipt.
"""

from __future__ import annotations

import re
from typing import Protocol

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.mission.contracts import logical_id
from runtime.service_guard.contracts import EFFECT, GuardError, ServicePolicy, check_observation


SCHEMA = "aioa.nebius-serverless-target.v1"
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_COMMAND_FIELDS = {
    "operation_id", "scope", "target_id", "expected_revision", "before_effect_count",
    "effect_class", "approval_digest", "policy_digest", "proposal_digest", "expires_at",
    "idempotency_key", "request_digest",
}


class DurableTargetStore(Protocol):
    """Deployment-owned transactional store; no local fallback is provided."""

    def read_state(self, target_id: str, scope: list[str]) -> dict: ...
    def read_receipt(self, target_id: str, scope: list[str], idempotency_key: str) -> dict | None: ...
    def apply_once(self, command: dict) -> dict: ...


def _validate_envelope(request: object, store: object) -> tuple[str, str, list[str]]:
    if (type(request) is not dict or request.get("schema") != SCHEMA
            or type(request.get("action")) is not str):
        raise GuardError("TARGET_OPERATION_DENIED")
    action, target_id, scope_values = request["action"], request.get("target_id"), request.get("scope")
    if type(target_id) is not str or type(scope_values) is not list or len(scope_values) != 4:
        raise GuardError("TARGET_IDENTITY_OR_STATE_MISMATCH")
    try:
        logical_id(target_id)
        scope = OwnerScope(*scope_values)
    except (TypeError, ValueError):
        raise GuardError("TARGET_IDENTITY_OR_STATE_MISMATCH") from None
    if not all(callable(getattr(store, name, None))
               for name in ("read_state", "read_receipt", "apply_once")):
        raise GuardError("TARGET_STORE_UNAVAILABLE")
    return action, target_id, list(scope.binding())


def _validate_command(command: object, target_id: str, scope: list[str]) -> dict:
    if type(command) is not dict or set(command) != _COMMAND_FIELDS:
        raise GuardError("TARGET_COMMAND_DENIED")
    if (command["target_id"] != target_id or command["scope"] != scope
            or command["effect_class"] != EFFECT
            or type(command["expected_revision"]) is not int
            or not 1 <= command["expected_revision"] <= 2**53
            or type(command["before_effect_count"]) is not int
            or not 0 <= command["before_effect_count"] < command["expected_revision"]
            or type(command["expires_at"]) is not int
            or not 0 <= command["expires_at"] <= 2**53
            or any(type(command[name]) is not str or _HEX.fullmatch(command[name]) is None
                   for name in ("approval_digest", "policy_digest", "proposal_digest",
                                "idempotency_key", "request_digest"))):
        raise GuardError("TARGET_COMMAND_DENIED")
    try:
        logical_id(command["operation_id"])
    except ValueError:
        raise GuardError("TARGET_COMMAND_DENIED") from None
    expected = canonical_sha256({name: value for name, value in command.items()
                                 if name != "request_digest"})
    if expected != command["request_digest"]:
        raise GuardError("TARGET_COMMAND_DENIED")
    return command


def handle_target_request(request: dict, store: DurableTargetStore) -> dict | None:
    """Handle exactly one typed request using a deployment-provided atomic store."""
    try:
        raw = canonical_json_bytes(request)
    except Exception:
        raise GuardError("TARGET_REQUEST_INVALID") from None
    if len(raw) > 16384:
        raise GuardError("TARGET_REQUEST_LIMIT")
    action, target_id, scope = _validate_envelope(request, store)
    if action == "READ_STATE" and set(request) == {"schema", "action", "target_id", "scope"}:
        state = store.read_state(target_id, scope)
        try:
            check_observation(state, ServicePolicy(OwnerScope(*scope), target_id))
        except GuardError:
            raise GuardError("TARGET_IDENTITY_OR_STATE_MISMATCH") from None
        return state
    if action == "READ_RECEIPT" and set(request) == {
            "schema", "action", "target_id", "scope", "idempotency_key"}:
        key = request["idempotency_key"]
        if type(key) is not str or _HEX.fullmatch(key) is None:
            raise GuardError("INVALID_EFFECT_KEY")
        receipt = store.read_receipt(target_id, scope, key)
        if receipt is not None and type(receipt) is not dict:
            raise GuardError("TARGET_RECEIPT_INVALID")
        return receipt
    if action == "APPLY_SET_MAINTENANCE" and set(request) == {
            "schema", "action", "target_id", "scope", "command"}:
        command = _validate_command(request["command"], target_id, scope)
        receipt = store.apply_once(command)
        if (type(receipt) is not dict
                or any(receipt.get(name) != value for name, value in command.items())
                or receipt.get("receipt_id") != "target-" + command["idempotency_key"]
                or type(receipt.get("new_revision")) is not int
                or receipt["new_revision"] != command["expected_revision"] + 1
                or type(receipt.get("effect_count")) is not int
                or receipt["effect_count"] != command["before_effect_count"] + 1
                or receipt.get("mode") != "MAINTENANCE"
                or type(receipt.get("dispatched_at")) is not int
                or not 0 <= receipt["dispatched_at"] < command["expires_at"]):
            raise GuardError("TARGET_RECEIPT_INVALID")
        return receipt
    raise GuardError("TARGET_OPERATION_DENIED")
