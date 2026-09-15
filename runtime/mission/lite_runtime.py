"""One AgentRuntime-owned LITE scheduler, deterministic probes, advisory output."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import threading
import time
import uuid

from runtime.memory_patch.contract import parse_request
from runtime.mission.cli import read_manifest_file
from runtime.mission.contracts import MissionError
from runtime.mission.lite_contracts import LiteProfile, ObservationSnapshot
from runtime.mission.lite_journal import LiteJournal
from runtime.providers.nvidia import ProviderError, ProviderRequest, ProviderResponse


class FileObservationProbe:
    """Explicit Core-bound fixture path. Only health/value affect the change gate."""
    def __init__(self, source_id, path):
        self.source_id, self.path = source_id, Path(path)

    def observe(self, now, previous_digest, freshness_seconds):
        try:
            value = parse_request(read_manifest_file(self.path))
            if set(value) != {"source_revision", "health", "value"}:
                raise ValueError()
            snapshot = ObservationSnapshot(self.source_id, value["source_revision"], now,
                                           now + freshness_seconds, value["health"], value["value"],
                                           False, "BASELINE" if previous_digest is None else "STABLE")
            if previous_digest is not None and snapshot.content_digest != previous_digest:
                snapshot = replace(snapshot, material_change=True, change_reason="MATERIAL_CHANGE")
            return snapshot
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            raise MissionError("OBSERVATION_UNAVAILABLE") from None


@dataclass(frozen=True, slots=True, repr=False)
class LiteBindings:
    # Host/Core inputs, never deserialized from email, manifest or model output.
    state_root: Path
    observation: object
    provider: object
    clock: object = time.time
    cadence_shadow: object = None
    salience_shadow: object = None
    scheduler_owner: str = "AgentRuntime"
    memory: object = None
    cpl: object = None


class LiteScheduler:
    def __init__(self, profile, context, bindings, *, memory=None, cpl=None):
        if type(profile) is not LiteProfile or type(bindings) is not LiteBindings:
            raise MissionError("INVALID_LITE_BINDINGS")
        profile.require_context(context)
        if not profile.enabled or bindings.scheduler_owner != "AgentRuntime":
            raise MissionError("SCHEDULER_OWNER_MISMATCH")
        if (getattr(bindings.provider, "provider_id", None) != profile.provider_id
                or getattr(bindings.provider, "model_id", None) != profile.model_id
                or getattr(bindings.observation, "source_id", None) != profile.observation_source_ref
                or not callable(getattr(bindings.observation, "observe", None))
                or not callable(getattr(bindings.provider, "request", None))
                or not callable(getattr(bindings.provider, "estimated_units", None))):
            raise MissionError("LITE_PORT_BINDING_MISMATCH")
        if getattr(bindings.provider, "budget", None) != profile.budget:
            raise MissionError("LITE_POLICY_BINDING_MISMATCH")
        self.profile, self.bindings = profile, bindings
        self.memory = memory
        self.cpl = cpl
        self._mutex = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self.journal = LiteJournal(bindings.state_root, profile, self._now())

    def _now(self):
        now = self.bindings.clock()
        if type(now) not in (int, float) or not 0 <= now <= 2**53:
            raise MissionError("INVALID_CLOCK")
        return int(now)

    def _state(self, state, reason, now, data=None):
        self.journal.state.update(state=state, reason=reason)
        self.journal.record(now, reason, data)

    def _signal(self, reason):
        for mode, port in ((self.profile.dvm_mode, self.bindings.cadence_shadow),
                           (self.profile.pheromone_mode, self.bindings.salience_shadow)):
            if mode == "SHADOW" and port is not None:
                try:
                    port.shadow(reason)  # Return values never feed configuration/authority.
                except Exception:
                    pass  # Advisory failure cannot change the control path.

    def describe(self, trace=None):
        with self._mutex:
            return self._describe()

    def _describe(self):
        state = self.journal.state
        return {**{key: value for key, value in state.items() if key != "queue"},
                "queue_depth": len(state["queue"]), "scheduler_owner": "AgentRuntime",
                "profile_id": self.profile.profile_id, "runtime_mode": "LITE",
                "provider_id": self.profile.provider_id, "model_id": self.profile.model_id,
                "live_mutations": False, "auto_mode": "DISABLED",
                "memory_mode": self.profile.memory_mode, "cpl_mode": self.profile.cpl_mode,
                "dvm_mode": self.profile.dvm_mode, "pheromone_mode": self.profile.pheromone_mode,
                "budget_policy": asdict(self.profile.budget), "cadence_policy": asdict(self.profile.cadence),
                "max_queue_depth": self.profile.max_queue_depth, "max_concurrent_inference": 1,
                "reservation_counts": {name: sum(r["status"] == name for r in self.journal.reservations())
                                       for name in ("RESERVED", "COMMITTED", "UNKNOWN", "RELEASED")},
                "domain_mutations": 0}

    def _memory_input(self, item):
        if self.memory is None:
            return item["input_text"]
        context = self.memory.retrieve(item["input_text"])
        self.journal.record(self._now(), "MEMORY_" + self.profile.memory_mode, context.describe())
        if self.profile.memory_mode == "SHADOW":
            return item["input_text"]
        if context.status != "READY":
            raise MissionError("MEMORY_DEGRADED")
        return json.dumps({"observation": json.loads(item["input_text"]),
                           "quoted_advisory_context": json.loads(context.prompt_json)}, sort_keys=True)

    def tick(self, *, execute=True):
        if not self._mutex.acquire(blocking=False):
            raise MissionError("SCHEDULER_BUSY")
        try:
            if self._closed:
                raise MissionError("SCHEDULER_CLOSED")
            now, state = self._now(), self.journal.state
            if self._stop.is_set():
                self._shutdown(now)
                return self._describe()
            if state["reconciliation_required"] or self.journal.has_uncertain():
                state["reconciliation_required"] = True
                self._state("RECONCILE_READONLY_REQUIRED", "RECONCILE_READONLY_REQUIRED", now)
                return self._describe()
            if state["last_check_at"] is not None and now < state["last_check_at"]:
                self._state("WAIT", "CLOCK_REGRESSION", now)
                return self._describe()
            if now >= state["next_check_at"]:
                self._state("DUE", "CHECK_DUE", now)
                self._state("PROBING", "READONLY_PROBE", now)
                try:
                    snapshot = self.bindings.observation.observe(now, state["last_digest"], self.profile.cadence.freshness_seconds)
                    if (type(snapshot) is not ObservationSnapshot or snapshot.source_id != self.profile.observation_source_ref
                            or snapshot.observed_at != now or snapshot.fresh_until <= now
                            or snapshot.fresh_until > now + self.profile.cadence.freshness_seconds):
                        raise MissionError("INVALID_OR_STALE_OBSERVATION")
                except Exception:
                    state["next_check_at"] = now + self.profile.cadence.interval_seconds
                    self._state("DEGRADED", "OBSERVATION_UNAVAILABLE", now)
                    return self._describe()
                state.update(last_check_at=now, next_check_at=now + self.profile.cadence.interval_seconds,
                             freshness_deadline=snapshot.fresh_until, probes=state["probes"] + 1)
                # Compute change independently; the probe cannot authorize inference.
                changed = state["last_digest"] is not None and snapshot.content_digest != state["last_digest"]
                interval = self.profile.cadence.interpretation_interval_seconds
                due = bool(interval and now - state["last_inference_at"] >= interval)
                reason = "MATERIAL_CHANGE" if changed else "UNCERTAINTY" if snapshot.health == "UNCERTAIN" else "INTERPRETATION_DUE" if due else "STABLE_OBSERVATION"
                key = snapshot.content_digest + ":" + (str(now // interval) if due else "snapshot")
                admitted = True
                if reason != "STABLE_OBSERVATION" and key != state["last_admitted_key"]:
                    self._state("CHANGE_DETECTED", reason, now)
                    if len(state["queue"]) >= self.profile.max_queue_depth:
                        self._state("WAIT", "BACKPRESSURE", now)
                        admitted = False
                    else:
                        item = dict(request_id=uuid.uuid4().hex, trace_id=uuid.uuid4().hex,
                                    digest=snapshot.content_digest, queued_at=now, attempts=0, retry_at=now,
                                    fresh_until=snapshot.fresh_until,
                                    input_text=json.dumps({"source_id": snapshot.source_id, "source_revision": snapshot.source_revision,
                                                           "health": snapshot.health, "value": snapshot.value}, sort_keys=True))
                        state["queue"].append(item)
                        state.update(last_admitted_key=key, last_inference_at=now)
                        self._state("INFERENCE_QUEUED", reason, now, {"trace_id": item["trace_id"], "content_digest": snapshot.content_digest})
                else:
                    self._state("WAIT", "STABLE_OBSERVATION", now)
                if admitted:
                    state["last_digest"] = snapshot.content_digest
                self._signal(reason)
                self.journal.record(now, "PROBE_SETTLED", {"content_digest": snapshot.content_digest})
            if execute and state["queue"] and not self._stop.is_set():
                self._drain(now)
            if self._stop.is_set():
                self._shutdown(self._now())
            return self._describe()
        finally:
            self._mutex.release()

    def _drain(self, now):
        state = self.journal.state
        item = state["queue"][0]
        if now >= item["fresh_until"]:
            state["queue"].pop(0)
            self._state("WAIT", "STALE_QUEUE_ITEM", now)
            return
        if now < item["retry_at"]:
            return
        try:
            input_text = self._memory_input(item)
        except MissionError as error:
            state["queue"].pop(0)
            self._state("DEGRADED", error.code, now)
            return
        reservation_id = uuid.uuid4().hex
        request = ProviderRequest(item["request_id"], item["trace_id"], self.profile.provider_id,
                                  self.profile.model_id, input_text, reservation_id,
                                  self.profile.budget.max_output_tokens, self.profile.budget.request_timeout_seconds)
        try:
            estimate = self.bindings.provider.estimated_units(request)
            self.journal.reserve(reservation_id, item["trace_id"], estimate, now)
        except (MissionError, ProviderError) as error:
            self._state("DEGRADED", error.code, now)
            return
        item["attempts"] += 1
        self._state("INFERENCE_RUNNING", "BUDGET_RESERVED", now,
                    {"reservation_id": reservation_id, "trace_id": item["trace_id"], "estimated_units": estimate})
        if self._stop.is_set():
            self.journal.settle(reservation_id, "RELEASED", reason="STOPPED_BEFORE_TRANSPORT")
            return
        try:
            # Exactly one synchronous transport at a time, under the scheduler mutex.
            response = self.bindings.provider.request(request)
            if (type(response) is not ProviderResponse or response.request_id != request.request_id
                    or response.model_id != request.model_id or response.validation_result != "VALID"):
                raise ProviderError("INVALID_PROVIDER_RESPONSE", outcome_unknown=True)
        except ProviderError as error:
            status = "UNKNOWN" if error.outcome_unknown else "RELEASED"
            self.journal.settle(reservation_id, status, reason=error.code)
            if error.code not in {"MISSING_API_KEY", "INVALID_API_KEY_CONFIGURATION", "MODEL_NOT_FOUND", "INVALID_PROVIDER_REQUEST", "INPUT_TOO_LARGE"}:
                state["model_calls"] += 1
            retry = error.retryable and not error.outcome_unknown and item["attempts"] <= self.profile.budget.max_retry
            if retry:
                item["retry_at"] = now + self.profile.budget.retry_delay_seconds
                reason = error.code
            else:
                state["queue"].pop(0)
                reason = "RETRY_BUDGET_EXHAUSTED" if error.retryable else error.code
            self._state("DEGRADED", reason, self._now(), {"error": error.code, "retryable": error.retryable,
                        "retry_scheduled": retry, "reservation_status": status, "http_status": error.http_status,
                        "request_id": request.request_id, "trace_id": request.trace_id})
            self._signal(error.code)
            return
        except Exception:
            # An unclassified port exception is never proof that nothing was sent.
            self.journal.settle(reservation_id, "UNKNOWN", reason="PROVIDER_PORT_FAILURE")
            state["model_calls"] += 1
            state["queue"].pop(0)
            self._state("DEGRADED", "PROVIDER_PORT_FAILURE", self._now())
            return
        state["model_calls"] += 1
        self.journal.settle(reservation_id, "COMMITTED", actual_units=response.usage.get("total_tokens"), reason="VALID_ADVICE")
        state["queue"].pop(0)
        self._state("SETTLED", "VALID_ADVICE", self._now(), {
            "request_id": response.request_id, "provider_request_id": response.provider_request_id,
            "trace_id": request.trace_id, "model_id": response.model_id,
            "http_status": response.http_status, "received_at": response.received_at,
            "finish_reason": response.finish_reason, "raw_size": response.raw_size,
            "validation_result": response.validation_result,
            "parsed_payload": dict(response.parsed_payload), "usage": dict(response.usage),
        })
        if self.profile.cpl_mode != "OFF":
            result = ({"status": "NO_CRITIC", "reason": "CPL_UNBOUND", "generation_requests": 0,
                       "knowledge_write": "ZERO_WRITE", "execution_authority": False}
                      if self.cpl is None else self.cpl.run(response, item, self.journal, self._now(), self._stop.is_set))
            state["model_calls"] += result["generation_requests"]
            state["reconciliation_required"] = state["reconciliation_required"] or self.journal.has_uncertain()
            self._state("DEGRADED" if result["status"] == "NO_CRITIC" else "SETTLED",
                        "CPL_" + result["status"], self._now(), result)

    def request_stop(self):
        # Signal-safe cooperative request: no SQLite or mutex work in a handler.
        self._stop.set()

    def _shutdown(self, now):
        self.journal.state["shutdown_requested"] = True
        self._state("STOPPING", "SHUTDOWN_REQUESTED", now)
        self._state("STOPPED", "READONLY_STOPPED", now)

    def run(self):
        try:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(min(1, self.profile.cadence.interval_seconds))
        finally:
            self.close()

    def close(self):
        self.request_stop()
        with self._mutex:
            if not self._closed:
                try:
                    self._shutdown(self._now())
                finally:
                    self.journal.close()
                    self._closed = True
