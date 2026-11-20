"""NV09 LOCAL TEST composition: real disposable target, explicit file DB fixture."""

import json
import os
import secrets
import select
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from live_gate_support import test_live_gate
from main import create_runtime
from nv03_support import DurableFactory
from test_nv02_lite import FixtureTransport

from runtime.core_admission import (
    Capability,
    CoreAdmission,
    LocalOwnerAssignment,
    OwnerScope,
)
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.contracts import MissionContext
from runtime.mission.lite_contracts import MODEL, LiteBudget, LiteCadence, LiteProfile
from runtime.mission.lite_runtime import LiteBindings
from runtime.providers.nvidia import NvidiaProvider
from runtime.service_guard.contracts import EFFECT, ServicePolicy
from runtime.service_guard.service import CoreServiceGuard, GuardLoopBinding
from runtime.service_guard.target import DisposableTargetState, LoopbackTargetClient

SCOPE = OwnerScope("nv09-test-tenant", "nv09-test-owner", "nv09-test-space", "nv09-test-slot")


def proposal(observation, **changes):
    value = {"target_id": observation["target_id"], "observed_mode": observation["mode"],
             "expected_target_revision": observation["revision"], "proposed_effect": EFFECT,
             "reason_summary": "The observed normal service can enter the planned maintenance window.",
             "needs_attention": True}
    value.update(changes)
    return value


def response(value):
    return 200, json.dumps({"model": MODEL, "id": "nv09-fixture-response",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 80, "total_tokens": 100}}).encode()


_TARGET_READY_SECONDS = 10
_TARGET_READY_BYTES = 1024
_TARGET_STDERR_BYTES = 32768


def _ready_fields(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError('duplicate READY field')
        result[name] = value
    return result


def _target_ready_port(process, target_id):
    """Read one bounded READY frame, draining private stderr without echoing it."""
    deadline = time.monotonic() + _TARGET_READY_SECONDS
    output, stderr_bytes = bytearray(), 0
    streams = (process.stderr, process.stdout)
    original_blocking = [(stream, os.get_blocking(stream.fileno())) for stream in streams]
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        watched = list(streams)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AssertionError('LOCAL_TARGET_READY_TIMEOUT')
            readable = select.select(watched, [], [], remaining)[0]
            if not readable:
                raise AssertionError('LOCAL_TARGET_READY_TIMEOUT')
            for stream in readable:
                while True:
                    if time.monotonic() >= deadline:
                        raise AssertionError('LOCAL_TARGET_READY_TIMEOUT')
                    try:
                        chunk = os.read(stream.fileno(), 4096)
                    except BlockingIOError:
                        break
                    if not chunk:
                        if stream is process.stdout:
                            raise AssertionError('LOCAL_TARGET_READY_EOF')
                        watched.remove(stream)
                        break
                    if stream is process.stderr:
                        stderr_bytes += len(chunk)
                        if stderr_bytes > _TARGET_STDERR_BYTES:
                            raise AssertionError('LOCAL_TARGET_STARTUP_STDERR_LIMIT')
                        continue
                    output.extend(chunk)
                    if len(output) > _TARGET_READY_BYTES:
                        raise AssertionError('LOCAL_TARGET_READY_LIMIT')
                    if b'\n' not in output:
                        continue
                    line, trailing = bytes(output).split(b'\n', 1)
                    try:
                        ready = json.loads(line.decode('utf-8'), object_pairs_hook=_ready_fields)
                        valid = (not trailing and type(ready) is dict
                                 and set(ready) == {'port', 'target_id'}
                                 and type(ready['port']) is int and 1024 <= ready['port'] <= 65535
                                 and type(ready['target_id']) is str and ready['target_id'] == target_id)
                    except (ValueError, UnicodeError, RecursionError):
                        valid = False
                    if not valid:
                        raise AssertionError('LOCAL_TARGET_READY_INVALID') from None
                    if process.poll() is not None:
                        raise AssertionError('LOCAL_TARGET_READY_EOF')
                    return ready['port']
    finally:
        for stream, blocking in original_blocking:
            try:
                os.set_blocking(stream.fileno(), blocking)
            except (OSError, ValueError):
                pass


class LocalTarget:
    def __init__(self, root, *, scope=SCOPE, target_id="disposable-nv09", drop_ack=False):
        # Bind a relative root to the caller before changing the child cwd.
        self.root, self.scope, self.target_id = Path(root).absolute(), scope, target_id
        self.key = secrets.token_bytes(32)
        self.config = {"root": str(self.root), "scope": list(scope.binding()),
                       "target_id": target_id, "key": self.key.hex(), "drop_ack": drop_ack}
        # The reviewer may launch from outside the checkout with no PYTHONPATH.
        self.process = None
        try:
            self.process = subprocess.Popen([sys.executable, "-B", "-m", "runtime.service_guard.target"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=Path(__file__).resolve().parents[1],
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            self.process.stdin.write(json.dumps(self.config).encode() + b"\n")
            self.process.stdin.close()
            self.port = _target_ready_port(self.process, target_id)
            self.client = LoopbackTargetClient(port=self.port, scope=scope, target_id=target_id, key=self.key)
            self.state = DisposableTargetState(self.root, scope, target_id)
        except BaseException:
            self.close()
            raise

    def close(self):
        process = getattr(self, 'process', None)
        if process is None:
            return
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


class GuardFixture:
    def __init__(self, root, client, *, operation_id="operation-a", actor=None,
                 scope=None, factory=None, clock=None, extra_hat_ids=(), model_id=MODEL):
        self.root, self.client, self.operation_id = Path(root), client, operation_id
        self.scope = scope or client.scope
        self.clock_value = int(time.time())
        self.clock = clock or (lambda: self.clock_value)
        self.core = CoreAdmission(LocalOwnerAssignment(self.scope, frozenset(Capability),
            frozenset({"disposable-service",*extra_hat_ids}), frozenset({model_id}), operator_approved=True),
            clock=lambda: datetime.fromtimestamp(self.clock(), UTC))
        self.factory = factory or DurableFactory(self.root / "native-fixture.json")
        self.runner = TransactionRunner(self.core, self.factory)
        self.policy = ServicePolicy(self.scope, client.target_id)
        self.guard = CoreServiceGuard(self.core, self.runner, self.policy, client, clock=self.clock)
        self.budget = LiteBudget(max_requests_per_hour=8, max_retry=0, max_output_tokens=256)
        self.profile = LiteProfile(self.scope, "nv09-single-watch", "service-target", enabled=True,
                                   budget=self.budget, cadence=LiteCadence(interval_seconds=1))
        self.transport = FixtureTransport([response(actor or proposal(client.read()))])
        provider = NvidiaProvider(self.budget, transport=self.transport,
            secret_supplier=lambda: "fixture-not-a-real-key", clock=self.clock,
            live_gate=test_live_gate(self.root / "test-gate", clock=self.clock))
        observation = type("UnusedReadOnlyProbe", (), {"source_id": "service-target", "observe": lambda *a: None})()
        self.bindings = LiteBindings(self.root / "journal", observation, provider, clock=self.clock,
                                    service_guard=GuardLoopBinding(self.guard, operation_id))
        self.context = MissionContext(self.scope, frozenset({"service-target"}), "CONTRACT_TEST")
        self.runtime = create_runtime(lite_profile=self.profile, mission_context=self.context,
                                      lite_bindings=self.bindings)

    def approve(self, **kwargs):
        return self.guard.approve(self.core.local_operator(Capability.OWNER_APPROVAL), self.operation_id, **kwargs)

    def inspect(self):
        return self.guard.inspect(self.core.local_operator(Capability.READ), self.operation_id)

    def tick(self):
        self.clock_value += 1
        return self.runtime.lite_tick()["service_guard"]

    def close(self):
        self.runtime.close()
        self.runner.close()
        self.core.close()


def crash_worker(config):
    """An actual process exits after successful target POST, before Core receipt."""
    from unittest.mock import patch
    client = LoopbackTargetClient(port=config["port"], scope=OwnerScope(*config["scope"]),
                                 target_id=config["target_id"], key=bytes.fromhex(config["key"]))
    fx = GuardFixture(config["fixture_root"], client, operation_id=config["operation_id"])
    original = LoopbackTargetClient.dispatch

    def exit_after_effect(self, command, authorization=None):
        original(self, command, authorization)
        os._exit(73)

    with patch.object(LoopbackTargetClient, "dispatch", exit_after_effect):
        result = fx.tick()
    print(json.dumps(result), flush=True)
    fx.close()
    raise SystemExit(2)


if __name__ == "__main__":
    crash_worker(json.loads(sys.stdin.readline()))
