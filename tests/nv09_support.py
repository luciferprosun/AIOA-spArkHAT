"""NV09 LOCAL TEST composition: real disposable target, explicit file DB fixture."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import select
import subprocess
import sys
import time

from main import create_runtime
from live_gate_support import test_live_gate
from nv03_support import DurableFactory
from test_nv02_lite import FixtureTransport
from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment, OwnerScope
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.contracts import MissionContext
from runtime.mission.lite_contracts import LiteBudget, LiteCadence, LiteProfile, MODEL
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


class LocalTarget:
    def __init__(self, root, *, scope=SCOPE, target_id="disposable-nv09", drop_ack=False):
        self.root, self.scope, self.target_id = Path(root), scope, target_id
        self.key = secrets.token_bytes(32)
        self.config = {"root": str(self.root), "scope": list(scope.binding()),
                       "target_id": target_id, "key": self.key.hex(), "drop_ack": drop_ack}
        # The reviewer may launch from outside the checkout with no PYTHONPATH.
        self.process = subprocess.Popen([sys.executable, "-B", "-m", "runtime.service_guard.target"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.process.stdin.write(json.dumps(self.config).encode() + b"\n")
        self.process.stdin.close()
        if not select.select([self.process.stdout], [], [], 10)[0]:
            self.close()
            raise AssertionError("disposable target readiness deadline")
        line = self.process.stdout.readline()
        if not line:
            error = self.process.stderr.read().decode()
            self.close()
            raise AssertionError("target startup failed: " + error)
        self.port = json.loads(line)["port"]
        self.client = LoopbackTargetClient(port=self.port, scope=scope, target_id=target_id, key=self.key)
        self.state = DisposableTargetState(self.root, scope, target_id)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        for pipe in (self.process.stdout, self.process.stderr):
            if pipe is not None:
                pipe.close()


class GuardFixture:
    def __init__(self, root, client, *, operation_id="operation-a", actor=None,
                 scope=None, factory=None, clock=None):
        self.root, self.client, self.operation_id = Path(root), client, operation_id
        self.scope = scope or client.scope
        self.clock_value = int(time.time())
        self.clock = clock or (lambda: self.clock_value)
        self.core = CoreAdmission(LocalOwnerAssignment(self.scope, frozenset(Capability),
            frozenset({"disposable-service"}), frozenset({MODEL}), operator_approved=True),
            clock=lambda: datetime.fromtimestamp(self.clock(), timezone.utc))
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
