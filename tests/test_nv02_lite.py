"""NV-02 acceptance contracts. No live API, keys, domain state or cloud effects."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import io
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from main import AgentRuntime, create_runtime
from live_gate_support import test_live_gate
from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_json
from runtime.mission.contracts import MissionContext, MissionError
from runtime.mission.lite_cli import run_lite_cli
from runtime.mission.lite_contracts import LiteCadence, LiteProfile, MODEL, parse_lite_profile
from runtime.mission.lite_runtime import FileObservationProbe, LiteBindings
from runtime.providers.nvidia import NvidiaProvider, ProviderError, ProviderRequest, SYSTEM
from runtime.providers.live_gate import require_transport_authorization


def success(**changes):
    result = {"id": "fixture-response", "model": MODEL,
              "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"summary": "Observation changed.", "needs_attention": True})}}],
              "usage": {"prompt_tokens": 70, "completion_tokens": 12, "total_tokens": 82}}
    result.update(changes)
    return 200, json.dumps(result).encode()


class FixtureTransport:
    transport_scope = "TEST"

    def __init__(self, replies=None):
        self.calls, self.replies, self.before = [], list(replies or [success()]), None

    def __call__(self, payload, key, timeout, max_bytes, authorization=None):
        require_transport_authorization(
            authorization,
            "TEST",
            transport=self,
            payload=payload,
            timeout=timeout,
            max_bytes=max_bytes,
            provider_id="nvidia",
            model_id=MODEL,
        )
        if self.before:
            self.before()
        self.calls.append(json.loads(payload))
        value = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(value, Exception):
            raise value
        return value


class NV02Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.json"
        self.scope = OwnerScope("test-tenant", "test-owner", "test-space", "test-slot")
        self.context = MissionContext(self.scope, frozenset({"fixture"}), "CONTRACT_TEST")
        self.profile = LiteProfile(self.scope, "test-watch", "fixture", enabled=True,
                                   cadence=LiteCadence(interval_seconds=1))
        self.clock = 10000
        self.transport = FixtureTransport()
        self.write_source("a")

    def write_source(self, value, *, health="OK", revision="r1"):
        self.source.write_text(json.dumps(dict(value=value, health=health, source_revision=revision)))

    def provider(self, *, transport=None, key="fixture-not-a-real-key", budget=None):
        return NvidiaProvider(budget or self.profile.budget, secret_supplier=lambda: key,
                              transport=transport or self.transport, clock=lambda: self.clock,
                              live_gate=test_live_gate(self.root / "live-gate",
                                                       clock=lambda: self.clock))

    def runtime(self, *, profile=None, provider=None, **bindings):
        profile = profile or self.profile
        runtime = create_runtime(lite_profile=profile, mission_context=self.context,
            lite_bindings=LiteBindings(self.root / "state", FileObservationProbe("fixture", self.source),
                                      provider or self.provider(budget=profile.budget), clock=lambda: self.clock, **bindings))
        self.addCleanup(runtime.close)
        return runtime

    def changed(self, runtime, *, execute=True):
        runtime.lite_tick()
        self.clock += 1
        self.write_source("b")
        return runtime.lite_tick(execute=execute)

    def request(self, **changes):
        return replace(ProviderRequest("request1", "trace1", "nvidia", MODEL, '{"value":"b"}', "reservation1", 256, 30), **changes)

    def test_N201_disabled_profile_opens_no_services_or_journal(self):
        profile = replace(self.profile, enabled=False)
        with patch("runtime.mission.lite_runtime.LiteJournal", side_effect=AssertionError("unexpected IO")):
            runtime = self.runtime(profile=profile)
        self.assertIs(type(runtime), AgentRuntime)
        self.assertEqual("DISABLED", runtime.lite_status()["state"])
        self.assertIsNone(runtime.executor)
        self.assertIsNone(runtime._nonzero_service)
        self.assertFalse((self.root / "state").exists())

    def test_N202_manifest_roundtrip_digest_and_immutable_nested_policy(self):
        text = canonical_json(self.profile, exclude_fields=("digest",))
        parsed = parse_lite_profile(text, self.context)
        self.assertEqual(self.profile.digest, parsed.digest)
        data = json.loads(text)
        self.assertEqual(parsed.digest, parse_lite_profile(json.dumps(dict(reversed(list(data.items())))), self.context).digest)
        with self.assertRaises(FrozenInstanceError):
            parsed.budget.max_retry = 2

    def test_N202_manifest_rejects_unknown_duplicates_and_nonfinite(self):
        text = canonical_json(self.profile, exclude_fields=("digest",))
        data = json.loads(text)
        for altered in ({**data, "secret": "value"}, {**data, "execute": True},
                        {**data, "manifest_version": True}, {**data, "manifest_version": 2},
                        {**data, "budget": {"max_retry": -1}}, {**data, "budget": {"max_retry": float("inf")}},
                        {**data, "cadence": {"interval_seconds": float("nan")}},
                        {**data, "budget": {"max_retry": 1.0}}):
            with self.subTest(altered=str(altered)[:80]), self.assertRaises(MissionError):
                parse_lite_profile(json.dumps(altered), self.context)
        for key in ("watch_id", "owner_id", "max_retry"):
            bad = text.replace('"' + key + '":', '"' + key + '":null,"' + key + '":', 1)
            with self.subTest(key=key), self.assertRaises(MissionError):
                parse_lite_profile(bad, self.context)

    def test_N202_scope_source_and_revision_conflicts(self):
        with self.assertRaisesRegex(MissionError, "OWNER_SCOPE_MISMATCH"):
            self.profile.require_context(replace(self.context, owner_scope=replace(self.scope, tenant_id="other")))
        with self.assertRaisesRegex(MissionError, "UNREGISTERED_SOURCE"):
            self.profile.require_context(replace(self.context, registered_source_ids=frozenset()))
        runtime = self.runtime()
        runtime.close()
        with self.assertRaisesRegex(MissionError, "MANIFEST_REVISION_CONFLICT"):
            self.runtime(profile=replace(self.profile, max_queue_depth=3))
        revised = self.runtime(profile=replace(self.profile, max_queue_depth=3, manifest_revision=2))
        self.assertEqual(2, revised.lite_status()["coordinator_epoch"])

    def test_N203_second_owner_denied_and_lease_released_on_close(self):
        runtime = self.runtime()
        with self.assertRaisesRegex(MissionError, "SCHEDULER_ALREADY_OWNED"):
            self.runtime()
        first = runtime.lite_status()["lease_id"]
        runtime.close()
        second = self.runtime()
        self.assertNotEqual(first, second.lite_status()["lease_id"])

    def test_N203_process_lock_blocks_another_process(self):
        runtime = self.runtime()
        lock = runtime._lite_scheduler.journal.path.with_suffix(".lock")
        script = 'import fcntl,sys;f=open(sys.argv[1],"r");fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
        result = subprocess.run([sys.executable, "-c", script, str(lock)], capture_output=True)
        self.assertNotEqual(0, result.returncode)
        self.assertIn(b"BlockingIOError", result.stderr)

    def test_N204_ten_identical_fresh_probes_make_zero_model_calls(self):
        runtime = self.runtime()
        for _ in range(10):
            runtime.lite_tick()
            self.clock += 1
        self.assertEqual(10, runtime.lite_status()["probes"])
        self.assertEqual([], self.transport.calls)
        self.assertEqual([], runtime._lite_scheduler.journal.reservations())

    def test_N204_revision_only_changes_are_not_material(self):
        runtime = self.runtime()
        runtime.lite_tick()
        for i in range(10):
            self.clock += 1
            self.write_source("a", revision="r" + str(i))
            runtime.lite_tick()
        self.assertEqual([], self.transport.calls)

    def test_N205_material_change_queues_exactly_one_then_commits(self):
        runtime = self.runtime()
        status = self.changed(runtime, execute=False)
        self.assertEqual(("INFERENCE_QUEUED", 1), (status["state"], status["queue_depth"]))
        runtime.lite_tick(execute=False)
        self.assertEqual(1, runtime.lite_status()["queue_depth"])
        result = runtime.lite_tick()
        self.assertEqual((1, 0, "SETTLED"), (len(self.transport.calls), result["queue_depth"], result["state"]))
        self.assertEqual("COMMITTED", runtime._lite_scheduler.journal.reservations()[0]["status"])
        self.assertEqual("VALID", runtime._lite_scheduler.journal.evidence()[-1]["data"]["validation_result"])

    def test_N206_restart_idle_and_stable_baseline_remain_readonly(self):
        runtime = self.runtime()
        runtime.lite_tick()
        runtime.close()
        resumed = self.runtime()
        self.assertEqual("IDLE", resumed.lite_status()["state"])
        self.clock += 1
        resumed.lite_tick()
        self.assertEqual([], self.transport.calls)

    def test_N207_restart_queued_requires_reconciliation_without_replay(self):
        runtime = self.runtime()
        self.changed(runtime, execute=False)
        runtime.close()
        resumed = self.runtime()
        for _ in range(3):
            status = resumed.lite_tick()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", status["state"])
        self.assertEqual(1, status["queue_depth"])
        self.assertEqual([], self.transport.calls)

    def test_N207_crash_after_reservation_marks_unknown_and_preserves_budget(self):
        runtime = self.runtime()
        self.changed(runtime, execute=False)
        journal = runtime._lite_scheduler.journal
        journal.reserve("crash-reservation", "trace-crash", 1000, self.clock)
        journal.state["state"] = "INFERENCE_RUNNING"
        journal.record(self.clock, "CRASH_FIXTURE")
        journal.close()  # Simulate process death, deliberately no graceful save.
        runtime._lite_scheduler._closed = True
        resumed = self.runtime()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", resumed.lite_tick()["state"])
        record = resumed._lite_scheduler.journal.reservations()[0]
        self.assertEqual(("UNKNOWN", 1000), (record["status"], record["estimated_units"]))
        self.assertEqual([], self.transport.calls)

    def test_N208_bounded_queue_reports_backpressure(self):
        runtime = self.runtime(profile=replace(self.profile, max_queue_depth=1))
        self.changed(runtime, execute=False)
        self.clock += 1
        self.write_source("c")
        status = runtime.lite_tick(execute=False)
        self.assertEqual(("BACKPRESSURE", 1), (status["reason"], status["queue_depth"]))
        self.assertEqual([], self.transport.calls)

    def test_N209_missing_key_is_typed_and_never_enters_transport(self):
        runtime = self.runtime(provider=self.provider(key=""))
        status = self.changed(runtime)
        self.assertEqual("MISSING_API_KEY", status["reason"])
        self.assertEqual(0, status["model_calls"])
        self.assertEqual([], self.transport.calls)
        self.assertEqual("RELEASED", runtime._lite_scheduler.journal.reservations()[0]["status"])

    def test_N211_timeout_is_unknown_not_released(self):
        self.transport.replies = [TimeoutError("private fixture error")]
        runtime = self.runtime()
        status = self.changed(runtime)
        self.assertEqual("PROVIDER_TIMEOUT", status["reason"])
        self.assertEqual("UNKNOWN", runtime._lite_scheduler.journal.reservations()[0]["status"])

    def test_N210_json_mode_payload_preserves_pinned_model_and_disabled_thinking(self):
        request = self.request()
        provider = self.provider()
        response = provider.request(request)
        self.assertEqual([{
            "model": MODEL,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": request.input_text}],
            "max_tokens": 256, "temperature": 1, "top_p": 0.95,
            "response_format": {"type": "json_object"},
            "stream": False, "chat_template_kwargs": {"enable_thinking": False},
        }], self.transport.calls)
        self.assertEqual("VALID", response.validation_result)
        self.assertEqual(MODEL, response.model_id)
        encoded = json.dumps(self.transport.calls[0], ensure_ascii=False,
                             allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.assertEqual(len(encoded) + 256, provider.estimated_units(request))

    def test_N212_rate_limit_retries_with_delay_and_hard_attempt_limit(self):
        self.transport.replies = [(429, b"private upstream error")]
        runtime = self.runtime()
        first = self.changed(runtime)
        self.assertEqual("RATE_LIMITED", first["reason"])
        runtime.lite_tick()
        self.assertEqual(1, len(self.transport.calls))
        self.clock += 2
        final = runtime.lite_tick()
        self.assertEqual("RETRY_BUDGET_EXHAUSTED", final["reason"])
        self.assertEqual((2, 0), (len(self.transport.calls), final["queue_depth"]))
        for _ in range(10):
            self.clock += 1
            runtime.lite_tick()
        self.assertEqual(2, len(self.transport.calls))

    def test_N212_http_429_is_post_transport_provider_outcome(self):
        transport = FixtureTransport([(429, b"private upstream error")])
        provider = self.provider(transport=transport)
        with self.assertRaises(ProviderError) as caught:
            provider.request(self.request())
        self.assertEqual("RATE_LIMITED", caught.exception.code)
        self.assertEqual(429, caught.exception.http_status)
        self.assertTrue(caught.exception.retryable)
        self.assertFalse(caught.exception.outcome_unknown)
        self.assertEqual(1, len(transport.calls))

    def test_N212_rejected_attempts_count_against_hourly_budget(self):
        policy = replace(self.profile.budget, max_requests_per_hour=1)
        self.transport.replies = [(429, b"")]
        runtime = self.runtime(profile=replace(self.profile, budget=policy))
        self.changed(runtime)
        self.clock += 2
        self.assertEqual("BUDGET_EXHAUSTED", runtime.lite_tick()["reason"])
        self.assertEqual(1, len(self.transport.calls))

    def test_N213_truncation_invalid_json_schema_and_tools_fail_closed(self):
        cases = [
            ((200, b"{"), "INVALID_PROVIDER_RESPONSE"),
            (success(choices=[{"finish_reason": "length"}]), "TRUNCATED_RESPONSE"),
            (success(choices=[{"finish_reason": "stop", "message": {"content": '{"summary":"x","needs_attention":false,"auto_mode":"AUTO"}'}}]), "INVALID_PROVIDER_RESPONSE"),
            (success(choices=[{"finish_reason": "stop", "message": {"content": '{"summary":"x","needs_attention":false}', "tool_calls": [{"name": "execute"}]}}]), "INVALID_PROVIDER_RESPONSE"),
            ((200, b'{"model":"a","model":"b"}'), "INVALID_PROVIDER_RESPONSE"),
            (success(model="openai/other"), "MODEL_MISMATCH"),
            (success(usage={"completion_tokens": 257}), "OUTPUT_TOKEN_LIMIT_EXCEEDED"),
        ]
        for content in (
            '{\n \nsummary: "Shows service manager status for a unit.",\n needs_attention: false\n}',
            '{"summary":"x","summary":"y","needs_attention":false}',
            '{"summary":"x","needs_attention":NaN}',
            '{"summary":"x","needs_attention":"false"}',
            '{"summary":"x","needs_attention":false,"capabilities":[]}',
            '{"summary":"x","needs_attention":false,"reasoning":"private"}',
            '{"summary":"x","needs_attention":false,"metadata":{}}',
            '```json\n{"summary":"x","needs_attention":false}\n```',
            json.dumps({"summary": "x" * 801, "needs_attention": False}),
        ):
            cases.append((success(choices=[{"finish_reason": "stop", "message": {
                "content": content}}]), "INVALID_PROVIDER_RESPONSE"))
        cases.append((success(choices=[{"finish_reason": "stop", "message": {
            "content": '{"summary":"x","needs_attention":false}',
            "function_call": {"name": "execute", "arguments": "{}"},
        }}]), "INVALID_PROVIDER_RESPONSE"))
        for reply, expected in cases:
            transport = FixtureTransport([reply])
            with self.subTest(code=expected), self.assertRaises(ProviderError) as caught:
                self.provider(transport=transport).request(self.request())
            self.assertEqual(expected, caught.exception.code)
            self.assertTrue(caught.exception.outcome_unknown)
            self.assertFalse(caught.exception.retryable)
            self.assertEqual(200, caught.exception.http_status)
            self.assertEqual(1, len(transport.calls))
            self.assertEqual({"type": "json_object"}, transport.calls[0]["response_format"])

    def test_N213_byte_limit_and_invalid_input_are_bounded(self):
        with self.assertRaisesRegex(ProviderError, "RESPONSE_TOO_LARGE"):
            self.provider(transport=FixtureTransport([(200, b"x" * 65537)])).request(self.request())
        with self.assertRaisesRegex(ProviderError, "INPUT_TOO_LARGE"):
            self.provider().request(self.request(input_text="x" * 4096))
        self.assertEqual([], self.transport.calls)

    def test_N214_unknown_model_has_no_fallback_or_transport(self):
        for changes in ({"model_id": "unknown/model"}, {"provider_id": "other"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ProviderError, "MODEL_NOT_FOUND"):
                self.provider().request(self.request(**changes))
        self.assertEqual([], self.transport.calls)

    def test_N214_output_token_request_bounds_remain_strict_in_json_mode(self):
        provider = self.provider()
        for tokens in (0, -1, True, 1.5, self.profile.budget.max_output_tokens + 1):
            with self.subTest(tokens=tokens), self.assertRaisesRegex(ProviderError, "INVALID_PROVIDER_REQUEST"):
                provider.request(self.request(max_output_tokens=tokens))
        self.assertEqual([], self.transport.calls)

    def test_N215_reservation_is_committed_before_transport_in_another_connection(self):
        runtime = self.runtime()
        observed = []
        def check():
            db = sqlite3.connect(runtime._lite_scheduler.journal.path)
            try:
                observed.append(db.execute("SELECT status FROM reservations").fetchone()[0])
            finally:
                db.close()
        self.transport.before = check
        self.changed(runtime)
        self.assertEqual(["RESERVED"], observed)

    def test_N216_unknown_blocks_further_inference_even_after_hour_and_restart(self):
        self.transport.replies = [TimeoutError()]
        runtime = self.runtime()
        self.changed(runtime)
        self.clock += 3601
        self.write_source("c")
        for _ in range(10):
            self.assertEqual("RECONCILE_READONLY_REQUIRED", runtime.lite_tick()["state"])
        runtime.close()
        resumed = self.runtime()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", resumed.lite_tick()["state"])
        self.assertEqual(1, len(self.transport.calls))

    def test_N216_malformed_json_mode_reply_preserves_unknown_and_consumed_attempt(self):
        self.transport.replies = [success(choices=[{"finish_reason": "stop", "message": {
            "content": '{summary: "Observation changed.", needs_attention: false}'}}])]
        runtime = self.runtime()
        self.assertEqual("INVALID_PROVIDER_RESPONSE", self.changed(runtime)["reason"])
        journal = runtime._lite_scheduler.journal
        records = journal.reservations()
        self.assertEqual(1, len(records))
        self.assertEqual("UNKNOWN", records[0]["status"])
        self.assertGreater(records[0]["estimated_units"], 0)
        self.assertIsNone(records[0]["actual_units"])
        for status in ("COMMITTED", "RELEASED"):
            with self.subTest(status=status), self.assertRaisesRegex(MissionError, "INVALID_RESERVATION_TRANSITION"):
                journal.settle(records[0]["reservation_id"], status, reason="INVALID_CLEAR_ATTEMPT")
        self.assertEqual(records, journal.reservations())
        self.clock += 3601
        self.write_source("c")
        self.assertEqual("RECONCILE_READONLY_REQUIRED", runtime.lite_tick()["state"])
        runtime.close()
        resumed = self.runtime()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", resumed.lite_tick()["state"])
        self.assertEqual(records, resumed._lite_scheduler.journal.reservations())
        self.assertEqual(1, len(self.transport.calls))
        self.assertEqual({"type": "json_object"}, self.transport.calls[0]["response_format"])

    def test_N216_5xx_and_connection_failures_are_conservative_unknown(self):
        for reply, code in [((503, b"private"), "PROVIDER_UNAVAILABLE"), (OSError("private"), "CONNECTION_FAILURE")]:
            with self.subTest(code=code), self.assertRaises(ProviderError) as error:
                self.provider(transport=FixtureTransport([reply])).request(self.request())
            self.assertEqual(code, error.exception.code)
            self.assertTrue(error.exception.outcome_unknown)
            self.assertFalse(error.exception.retryable)
            self.assertNotIn("private", str(error.exception))

    def test_N217_all_mutable_profiles_and_execution_routes_are_denied(self):
        for change in ({"live_mutations": True}, {"auto_mode": "AUTO"}, {"cpl_mode": "LIVE"},
                       {"memory_mode": "LIVE"}, {"runtime_mode": "CONTROLLED"}, {"max_concurrent_inference": 2}):
            with self.subTest(change=change), self.assertRaises(MissionError):
                replace(self.profile, **change)
        runtime = self.runtime()
        with self.assertRaisesRegex(MissionError, "INSPECTION_ONLY"):
            runtime.run_text_request("execute")
        with self.assertRaisesRegex(MissionError, "INSPECTION_ONLY"):
            runtime.assistant_request("execute")
        self.assertIsNone(runtime.command_registry)
        self.assertIsNone(runtime.executor)
        self.assertIsNone(runtime._memory_patch_service)
        self.assertIsNone(runtime._nonzero_service)

    def test_N218_shadow_output_cannot_change_cadence_budget_or_authority(self):
        class Shadow:
            def shadow(self, reason):
                return {"max_retry": 999, "auto_mode": "AUTO", "next_check_at": 0}
        profile = replace(self.profile, dvm_mode="SHADOW", pheromone_mode="SHADOW")
        runtime = self.runtime(profile=profile, cadence_shadow=Shadow(), salience_shadow=Shadow())
        state = runtime.lite_tick()
        self.assertEqual(self.clock + 1, state["next_check_at"])
        self.assertEqual(1, state["budget_policy"]["max_retry"])
        self.assertEqual("DISABLED", state["auto_mode"])

    def test_N220_cli_doctor_and_status_are_readonly_and_redact_key(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(canonical_json(self.profile, exclude_fields=("digest",)))
        argv = ["--manifest", str(manifest), "--tenant", "test-tenant", "--owner", "test-owner",
                "--space", "test-space", "--slot", "test-slot", "--source-id", "fixture", "--state-root", str(self.root / "state"), "--json"]
        for operation in ("doctor", "status"):
            output = io.StringIO()
            with patch.dict(os.environ, {"NVIDIA_API_KEY": "do-not-show-this-value"}), redirect_stdout(output):
                code = run_lite_cli([operation, *argv], runtime_factory=create_runtime)
            self.assertEqual(0, code)
            self.assertNotIn("do-not-show-this-value", output.getvalue())
            result = json.loads(output.getvalue())
            self.assertEqual(MODEL, result["model_id"])
            self.assertEqual("LITE", result["runtime_mode"])
            self.assertTrue(result["key_present"])
        self.assertFalse((self.root / "state").exists())

    def test_scheduler_signal_request_stops_without_new_transport(self):
        runtime = self.runtime()
        self.changed(runtime, execute=False)
        runtime.lite_request_stop()
        result = runtime.lite_tick()
        self.assertEqual("STOPPED", result["state"])
        self.assertTrue(result["shutdown_requested"])
        self.assertEqual([], self.transport.calls)

    def test_scheduler_concurrent_tick_is_denied_while_inference_runs(self):
        runtime = self.runtime()
        self.changed(runtime, execute=False)
        entered, release = threading.Event(), threading.Event()
        self.transport.before = lambda: (entered.set(), release.wait(5))
        worker = threading.Thread(target=runtime.lite_tick)
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaisesRegex(MissionError, "SCHEDULER_BUSY"):
                runtime.lite_tick()
        finally:
            release.set()
            worker.join(5)
        self.assertEqual(1, len(self.transport.calls))

    def test_interpretive_deadline_is_explicit_and_not_every_heartbeat(self):
        runtime = self.runtime(profile=replace(self.profile, cadence=LiteCadence(interval_seconds=1, interpretation_interval_seconds=10)))
        for _ in range(10):
            runtime.lite_tick()
            self.clock += 1
        self.assertEqual([], self.transport.calls)
        runtime.lite_tick()
        self.assertEqual(1, len(self.transport.calls))

    def test_uncertain_probe_has_bounded_deduplication(self):
        self.write_source("a", health="UNCERTAIN")
        runtime = self.runtime()
        for _ in range(10):
            runtime.lite_tick()
            self.clock += 1
        self.assertEqual(1, len(self.transport.calls))

    def test_journal_evidence_and_budget_storage_are_bounded(self):
        profile = replace(self.profile, cadence=replace(self.profile.cadence, max_evidence_events=16),
                          budget=replace(self.profile.budget, max_reservations=1))
        runtime = self.runtime(profile=profile)
        self.changed(runtime)
        for _ in range(20):
            self.clock += 1
            runtime.lite_tick()
        self.assertLessEqual(len(runtime._lite_scheduler.journal.evidence()), 16)
        self.clock += 3601
        self.write_source("c")
        self.assertEqual("BUDGET_JOURNAL_FULL", runtime.lite_tick()["reason"])
        self.assertEqual(1, len(self.transport.calls))

    def test_input_file_is_readonly_and_symlinks_are_rejected(self):
        before = self.source.read_bytes()
        runtime = self.runtime()
        runtime.lite_tick()
        self.assertEqual(before, self.source.read_bytes())
        self.source.unlink()
        self.source.symlink_to(self.root / "not-read")
        self.clock += 1
        self.assertEqual("OBSERVATION_UNAVAILABLE", runtime.lite_tick()["reason"])
        self.assertEqual([], self.transport.calls)

    def test_stale_queued_observation_never_reaches_provider(self):
        runtime = self.runtime()
        self.changed(runtime, execute=False)
        self.clock += 121
        self.assertEqual("STALE_QUEUE_ITEM", runtime.lite_tick()["reason"])
        self.assertEqual([], self.transport.calls)

    def test_reconciliation_requirement_survives_two_clean_restarts(self):
        runtime = self.runtime()
        journal = runtime._lite_scheduler.journal
        journal.state["state"] = "PROBING"
        journal.record(self.clock, "INTERRUPTED_PROBE")
        journal.close()
        runtime._lite_scheduler._closed = True
        resumed = self.runtime()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", resumed.lite_status()["state"])
        resumed.close()
        again = self.runtime()
        self.assertEqual("RECONCILE_READONLY_REQUIRED", again.lite_tick()["state"])
        self.assertEqual([], self.transport.calls)

    def test_new_manifest_revision_does_not_reset_spent_hourly_budget(self):
        profile = replace(self.profile, budget=replace(self.profile.budget, max_requests_per_hour=1))
        runtime = self.runtime(profile=profile)
        self.changed(runtime)
        runtime.close()
        resumed = self.runtime(profile=replace(profile, manifest_revision=2))
        self.clock += 1
        self.write_source("c")
        self.assertEqual("BUDGET_EXHAUSTED", resumed.lite_tick()["reason"])
        self.assertEqual(1, len(self.transport.calls))

    def test_material_uncertainty_does_not_double_infer_on_next_probe(self):
        runtime = self.runtime()
        runtime.lite_tick()
        self.write_source("b", health="UNCERTAIN")
        for _ in range(10):
            self.clock += 1
            runtime.lite_tick()
        self.assertEqual(1, len(self.transport.calls))

    def test_real_cli_sigterm_and_sigint_persist_stopped_and_release_lease(self):
        import selectors
        repo = Path(__file__).resolve().parents[1]
        manifest = self.root / "manifest.json"
        manifest.write_text(canonical_json(self.profile, exclude_fields=("digest",)))
        command = [sys.executable, "-B", "-m", "runtime.cli", "lite", "watch", "--manifest", str(manifest),
                   "--tenant", "test-tenant", "--owner", "test-owner", "--space", "test-space", "--slot", "test-slot",
                   "--source-id", "fixture", "--source-file", str(self.source), "--state-root", str(self.root / "signals")]
        environment = {
            **os.environ,
            "AOIA_HOME": str(self.root / "provider-state"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for signum in (signal.SIGTERM, signal.SIGINT):
            child = subprocess.Popen(
                command,
                cwd=repo,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                with selectors.DefaultSelector() as selector:
                    selector.register(child.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(10), "CLI did not start")
                    started_line = child.stdout.readline()
                if not started_line:
                    out, err = child.communicate(timeout=10)
                    self.fail(
                        "CLI_STARTUP_EOF "
                        f"returncode={child.returncode} stdout={out!r} stderr={err[-4000:]!r}"
                    )
                started = json.loads(started_line)
                self.assertEqual("IDLE", started["state"])
                child.send_signal(signum)
                out, err = child.communicate(timeout=10)
                self.assertEqual(0, child.returncode, err)
                self.assertEqual("STOPPED", json.loads(out)["state"])
                db = sqlite3.connect(next((self.root / "signals").glob("*.sqlite3")))
                try:
                    state = json.loads(db.execute("SELECT data FROM watch").fetchone()[0])
                finally:
                    db.close()
                self.assertTrue(state["shutdown_requested"])
                self.assertEqual("STOPPED", state["state"])
                self.assertEqual(0, state["model_calls"])
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate()


if __name__ == "__main__":
    unittest.main()
