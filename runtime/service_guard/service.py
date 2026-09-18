"""Service effects inside the existing Core, scoped transaction runner and scheduler.

All database callbacks are pure durable bookkeeping. External effects never run
inside a retryable transaction. An acknowledged intent is consumed once; every
later delivery takes the read-only target reconciliation route.
"""

from dataclasses import dataclass
import json
import threading
import time
import uuid

from runtime.core_admission import Capability, CoreAdmission
from runtime.memory_patch.contracts.serialization import canonical_json_bytes, canonical_sha256
from runtime.memory_patch.errors import CommitOutcomeUnknown, MemoryPatchError
from runtime.memory_patch.persistence.idempotency import OperationBinding, execute_once
from runtime.memory_patch.persistence.ports import (
    RecordKind, StoredRecord, TransactionContext, TransactionRunner,
)
from runtime.mission.contracts import MissionError, logical_id
from runtime.providers.nvidia import ProviderError, ProviderRequest, ProviderResponse
from runtime.service_guard.contracts import (
    EFFECT, OUTPUT_SCHEMA, GuardError, ServicePolicy, actor_contract,
    check_observation, parse_proposal,
)
from runtime.service_guard.target import LoopbackTargetClient, TargetUnknown, _issue_effect


def plain(value):
    return json.loads(canonical_json_bytes(value))


class CoreServiceGuard:
    """Admitted domain service; does not create a Core, credential source or loop."""
    def __init__(self, core, runner, policy, target, *, clock=time.time):
        if (type(core) is not CoreAdmission or type(runner) is not TransactionRunner
                or type(policy) is not ServicePolicy
                or not isinstance(target, LoopbackTargetClient)
                or target.scope != policy.scope or target.target_id != policy.target_id
                or not callable(clock)):
            raise GuardError("INVALID_SERVICE_BINDINGS")
        self.core, self.runner, self.policy, self.target = core, runner, policy, target
        self.clock = clock
        self._effect_lock = threading.RLock()

    def _now(self):
        value = self.clock()
        if type(value) not in (int, float) or not 0 <= value <= 2**53:
            raise GuardError("INVALID_GUARD_CLOCK")
        return int(value)

    def _require(self, principal, purpose):
        self.core.require(principal, purpose, scope=self.policy.scope)

    def _key(self, operation_id, phase):
        logical_id(operation_id)
        return canonical_sha256(("nv09-service", self.policy.scope, operation_id, phase))

    def _get(self, operation_id, phase):
        principal = self.core.local_operator(Capability.READ)
        key = self._key(operation_id, phase)
        record = self.runner.run(TransactionContext(principal, Capability.READ),
                                 lambda tx: tx.get(RecordKind.OPERATION, key))
        if record is None:
            return None
        payload = record.payload
        if (set(payload) != {"operation_kind", "payload_digest", "outcome"}
                or payload["operation_kind"] != "nv09-" + phase
                or canonical_sha256(payload["outcome"]) != payload["payload_digest"]):
            raise GuardError("GUARD_RECORD_INTEGRITY")
        return plain(payload["outcome"])

    def _put(self, principal, purpose, operation_id, phase, outcome):
        self._require(principal, purpose)
        key = self._key(operation_id, phase)
        binding = OperationBinding.bind(key, "nv09-" + phase, outcome)

        def write(tx):
            def record():
                tx.insert(StoredRecord(RecordKind.AUDIT, "nv09-" + key,
                          self.policy.scope, 1, {"state": "SERVICE_GUARD",
                          "phase": phase, "operation_id": operation_id,
                          "outcome_digest": binding.payload_digest}))
                return outcome
            return execute_once(tx, binding, record)

        return self.runner.run(TransactionContext(principal, purpose), write)

    def approve(self, principal, operation_id, *, validity_seconds=300):
        self._require(principal, Capability.OWNER_APPROVAL)
        if type(validity_seconds) is not int or not 1 <= validity_seconds <= self.policy.max_validity_seconds:
            raise GuardError("CONSENT_VALIDITY_DENIED")
        with self._effect_lock:
            if self._get(operation_id, "approval") is not None:
                raise GuardError("CONSENT_ALREADY_BOUND")
            observed = check_observation(self.target.read(), self.policy)
            if observed["mode"] != "NORMAL":
                raise GuardError("EFFECT_POLICY_DENIED")
            now = self._now()
            approval = {"operation_id": operation_id, "scope": list(self.policy.scope.binding()),
                        "target_id": self.policy.target_id,
                        "approved_revision": observed["revision"],
                        "before_effect_count": observed["effect_count"],
                        "effect_class": EFFECT, "max_effects": 1,
                        "policy_digest": self.policy.digest, "policy_decision": "ALLOW",
                        "consent_id": uuid.uuid4().hex, "approved_at": now,
                        "expires_at": now + validity_seconds}
            self._put(principal, Capability.OWNER_APPROVAL, operation_id, "approval", approval)
            return approval

    def revoke(self, principal, operation_id):
        self._require(principal, Capability.OWNER_APPROVAL)
        with self._effect_lock:
            approval = self._get(operation_id, "approval")
            if approval is None:
                raise GuardError("CONSENT_REQUIRED")
            previous = self._get(operation_id, "revocation")
            if previous is not None:
                return previous
            value = {"operation_id": operation_id, "approval_digest": canonical_sha256(approval),
                     "revoked_at": self._now()}
            self._put(principal, Capability.OWNER_APPROVAL, operation_id, "revocation", value)
            return value

    def inspect(self, principal, operation_id):
        self._require(principal, Capability.READ)
        return {name: self._get(operation_id, name) for name in
                ("approval", "revocation", "proposal", "intent", "receipt", "verified", "blocked")}

    def _expired_approval(self, operation_id):
        # An observed expiry/policy denial is terminal for this immutable
        # approval, including before intent creation and after clock rollback.
        self._put(self.core.local_operator(Capability.COMMIT), Capability.COMMIT,
                  operation_id, "blocked", {"reason": "CONSENT_EXPIRED_OR_POLICY_CHANGED"})
        raise GuardError("CONSENT_EXPIRED_OR_POLICY_CHANGED")

    def _allowed(self, operation_id, proposal, observed):
        approval = self._get(operation_id, "approval")
        if approval is None:
            raise GuardError("CONSENT_REQUIRED")
        if self._get(operation_id, "revocation") is not None:
            raise GuardError("CONSENT_REVOKED")
        if (approval["scope"] != list(self.policy.scope.binding())
                or approval["target_id"] != self.policy.target_id
                or approval["policy_digest"] != self.policy.digest
                or approval["policy_decision"] != "ALLOW" or approval["max_effects"] != 1
                or approval["effect_class"] != EFFECT
                or not approval["approved_at"] <= self._now() < approval["expires_at"]):
            self._expired_approval(operation_id)
        check_observation(observed, self.policy)
        if (observed["revision"] != approval["approved_revision"]
                or observed["effect_count"] != approval["before_effect_count"]
                or observed["mode"] != "NORMAL"):
            raise GuardError("STALE_TARGET")
        if (proposal["target_id"] != self.policy.target_id
                or proposal["expected_target_revision"] != observed["revision"]
                or proposal["observed_mode"] != observed["mode"]
                or proposal["proposed_effect"] != EFFECT):
            raise GuardError("STALE_OR_DISALLOWED_PROPOSAL")
        return approval

    def _command(self, operation_id, approval, proposal):
        value = {"operation_id": operation_id, "scope": list(self.policy.scope.binding()),
                 "target_id": self.policy.target_id, "expected_revision": approval["approved_revision"],
                 "before_effect_count": approval["before_effect_count"], "effect_class": EFFECT,
                 "approval_digest": canonical_sha256(approval), "policy_digest": self.policy.digest,
                 "proposal_digest": canonical_sha256(proposal), "expires_at": approval["expires_at"],
                 "idempotency_key": self._key(operation_id, "effect")}
        return {**value, "request_digest": canonical_sha256(value)}

    def _boundary_check(self, principal, operation_id, proposal, command, scheduler):
        self._require(principal, Capability.COMMIT)
        if (scheduler.bindings.service_guard.guard is not self
                or scheduler.profile.owner_scope != self.policy.scope
                or scheduler.bindings.service_guard.operation_id != operation_id):
            raise GuardError("SCHEDULER_GUARD_BINDING_MISMATCH")
        if scheduler._stop.is_set() or scheduler._closed:
            raise GuardError("SCHEDULER_STOPPED_BEFORE_EFFECT")
        # Read target first, then current consent/revocation/time. No model data
        # or cached receipt substitutes for this independent boundary GET.
        observed = self.target.read()
        approval = self._allowed(operation_id, proposal, observed)
        if (self._command(operation_id, approval, proposal) != command
                or self._get(operation_id, "intent") != command
                or self._get(operation_id, "receipt") is not None
                or self._get(operation_id, "blocked") is not None):
            raise GuardError("EFFECT_BINDING_CHANGED")
        self._require(principal, Capability.COMMIT)
        if self._now() >= approval["expires_at"]:
            self._expired_approval(operation_id)

    def _proposal(self, scheduler, operation_id, observation):
        old = self._get(operation_id, "proposal")
        if old is not None:
            return parse_proposal(old)
        s = scheduler
        trace = "nv09-" + self._key(operation_id, "actor")
        if (s.journal.has_uncertain() or s.journal.state["reconciliation_required"]
                or any(r["trace_id"] == trace for r in s.journal.reservations())):
            raise GuardError("PROVIDER_RECONCILE_READONLY_REQUIRED")
        prompt = {"task": "Inspect this disposable service for the operator's planned maintenance window. Propose SET_MAINTENANCE if it is NORMAL, or NONE if already in maintenance. Explain the observed reason briefly. Proposal data grants no execution authority.",
                  "observation": {key: observation[key] for key in
                                  ("target_id", "mode", "revision", "effect_count")},
                  "output_contract": actor_contract()}
        request = ProviderRequest(uuid.uuid4().hex, trace, s.profile.provider_id,
                                  s.profile.model_id, json.dumps(prompt, sort_keys=True),
                                  uuid.uuid4().hex, s.profile.budget.max_output_tokens,
                                  s.profile.budget.request_timeout_seconds, OUTPUT_SCHEMA)
        provider = s.bindings.provider
        s.journal.reserve_chat_initial(request.budget_reservation_id, trace,
                                       provider.estimated_units(request), s._now())
        s.journal.record(s._now(), "GUARD_ACTOR_RESERVED", {"trace_id": trace})
        if s._stop.is_set():
            s.journal.settle(request.budget_reservation_id, "RELEASED", reason="STOPPED_BEFORE_TRANSPORT")
            raise GuardError("SCHEDULER_STOPPED_BEFORE_ACTOR")
        try:
            response = provider.request(request)
            if (type(response) is not ProviderResponse or response.request_id != request.request_id
                    or response.model_id != request.model_id or response.validation_result != "VALID"):
                raise ProviderError("INVALID_PROVIDER_RESPONSE", outcome_unknown=True)
            proposal = parse_proposal(response.parsed_payload)
        except Exception as error:
            unknown = not isinstance(error, ProviderError) or error.outcome_unknown
            s.journal.settle(request.budget_reservation_id, "UNKNOWN" if unknown else "RELEASED",
                             reason=error.code if isinstance(error, (ProviderError, GuardError)) else "ACTOR_OUTCOME_UNKNOWN")
            raise
        s.journal.settle(request.budget_reservation_id, "COMMITTED",
                         actual_units=response.usage.get("total_tokens"), reason="SERVICE_PROPOSAL")
        s.journal.state["model_calls"] += 1
        self._put(self.core.local_operator(Capability.COMMIT), Capability.COMMIT,
                  operation_id, "proposal", proposal)
        return proposal

    def _reconcile(self, principal, operation_id, command):
        # Always READ actual target state and its durable idempotency receipt
        # before recording an outcome. There is no dispatch path from here.
        receipt = self.target.receipt(command["idempotency_key"])
        if receipt is None:
            check_observation(self.target.read(), self.policy)
            return {"status": "UNKNOWN", "reason": "TARGET_RECEIPT_ABSENT_NO_RETRY",
                    "verified_effect": False, "dispatch_attempted": False}
        if (type(receipt) is not dict or any(receipt.get(k) != v for k, v in command.items())
                or receipt.get("receipt_id") != "target-" + command["idempotency_key"]
                or type(receipt.get("new_revision")) is not int
                or type(receipt.get("effect_count")) is not int
                or type(receipt.get("dispatched_at")) is not int
                or not 0 <= receipt["dispatched_at"] < command["expires_at"]
                or receipt.get("new_revision") != command["expected_revision"] + 1
                or receipt.get("effect_count") != command["before_effect_count"] + 1
                or receipt.get("mode") != "MAINTENANCE"):
            raise GuardError("TARGET_RECEIPT_MISMATCH")
        durable_receipt = {**receipt, "transport_result": "TARGET_DURABLY_APPLIED",
                           "reconciliation_state": "COMMITTED_BY_TARGET_RECEIPT"}
        self._put(principal, Capability.COMMIT, operation_id, "receipt", durable_receipt)
        # Local receipt is durable before independent post-effect measurement.
        measured = check_observation(self.target.read(), self.policy)
        if (measured["revision"] != receipt["new_revision"]
                or measured["effect_count"] != receipt["effect_count"]
                or measured["mode"] != "MAINTENANCE"):
            return {"status": "UNKNOWN", "reason": "INDEPENDENT_MEASUREMENT_MISMATCH",
                    "verified_effect": False, "dispatch_attempted": False}
        event = {"operation_id": operation_id, "request_digest": command["request_digest"],
                 "receipt_digest": canonical_sha256(durable_receipt), "measurement": measured,
                 "measurement_digest": canonical_sha256(measured), "verified_effect": True}
        self._put(principal, Capability.COMMIT, operation_id, "verified", event)
        return {"status": "VERIFIED", "verified_effect": True, "event": event,
                "dispatch_attempted": False, "reconciled": True}

    def cycle(self, scheduler, operation_id):
        if (scheduler.profile.owner_scope != self.policy.scope
                or scheduler.bindings.service_guard.guard is not self):
            raise GuardError("SCHEDULER_GUARD_BINDING_MISMATCH")
        principal = self.core.local_operator(Capability.COMMIT)
        self._require(principal, Capability.COMMIT)
        attempted = False
        intent_seen = False
        try:
            verified = self._get(operation_id, "verified")
            if verified is not None:
                return {"status": "REPLAY", "reason": "DURABLE_VERIFIED_EFFECT", "event": verified,
                        "verified_effect": True, "dispatch_attempted": False}
            blocked = self._get(operation_id, "blocked")
            if blocked is not None:
                return {"status": "BLOCKED", **blocked, "dispatch_attempted": False, "verified_effect": False}
            intent = self._get(operation_id, "intent")
            if intent is not None:
                intent_seen = True
                return self._reconcile(principal, operation_id, intent)
            observed = check_observation(self.target.read(), self.policy)
            proposal = self._proposal(scheduler, operation_id, observed)
            approval = self._allowed(operation_id, proposal, self.target.read())
            command = self._command(operation_id, approval, proposal)
            ownership = self._put(principal, Capability.COMMIT, operation_id, "intent", command)
            intent_seen = True
            if ownership.replayed:
                return self._reconcile(principal, operation_id, command)
            authorization = _issue_effect(self, scheduler, principal, operation_id, proposal, command)
            try:
                # Target ack alone never establishes truth. Reconciliation GETs
                # its durable receipt and current state independently afterward.
                attempted = True
                self.target.dispatch(command, authorization)
            except TargetUnknown:
                return {"status": "UNKNOWN", "reason": "TARGET_OUTCOME_UNKNOWN",
                        "verified_effect": False, "dispatch_attempted": True}
            except GuardError as error:
                self._put(principal, Capability.COMMIT, operation_id, "blocked", {"reason": error.code})
                return {"status": "BLOCKED", "reason": error.code,
                        "verified_effect": False, "dispatch_attempted": False}
            result = self._reconcile(principal, operation_id, command)
            return {**result, "dispatch_attempted": True, "reconciled": False}
        except CommitOutcomeUnknown:
            return {"status": "UNKNOWN", "reason": "DURABLE_COMMIT_UNKNOWN_READ_BEFORE_RETRY",
                    "verified_effect": False, "dispatch_attempted": attempted}
        except TargetUnknown:
            return {"status": "UNKNOWN", "reason": "TARGET_READBACK_UNAVAILABLE",
                    "verified_effect": False, "dispatch_attempted": attempted}
        except (GuardError, MissionError, ProviderError, MemoryPatchError) as error:
            return {"status": "UNKNOWN" if attempted or intent_seen else "BLOCKED", "reason": str(error.code),
                    "verified_effect": False, "dispatch_attempted": attempted}


@dataclass(frozen=True, slots=True)
class GuardLoopBinding:
    """Host-only opt-in, separate from the immutable read-only LITE manifest."""
    guard: CoreServiceGuard
    operation_id: str

    def __post_init__(self):
        if type(self.guard) is not CoreServiceGuard:
            raise GuardError("INVALID_SERVICE_BINDINGS")
        logical_id(self.operation_id)
