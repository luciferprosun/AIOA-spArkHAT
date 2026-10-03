from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import time
import unittest

from main import create_runtime
from nv03_support import DurableFactory, MemoryFixture
from nv09_support import SCOPE
from test_nebius_routing import LIGHTNING, catalog_receipt, quote, route_budgets
from test_serverless_effect_transport import FakeNebiusJobTransport, MemoryTargetStore

from runtime.core_admission import Capability, CoreAdmission, LocalOwnerAssignment
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.lite import MemoryContext
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.contracts import MissionContext
from runtime.mission.lite_contracts import LiteBudget, LiteCadence, LiteProfile
from runtime.mission.lite_runtime import LiteBindings
from runtime.personal_ai_demo import PersonalAIDemoBindings, PersonalAIDemoService
from runtime.providers.exact import ProviderResult
from runtime.providers.nebius_routing import ModelRole, NebiusModelRouter, NebiusProviderPort
from runtime.service_guard.contracts import EFFECT, ServicePolicy
from runtime.service_guard.serverless_worker import handle_target_request
from runtime.service_guard.service import CoreServiceGuard, GuardLoopBinding
from runtime.service_guard.target import CloudEffectTargetClient


PREFERENCE = (
    "Maintenance only after the approved window and never without explicit approval."
)


class ServiceProposalProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []

    def generate_exact(self, request, cancellation, deadline):
        self.calls.append(request)
        prompt = json.loads(request.messages[-1].content)
        observed = prompt["observation"]
        proposal = {
            "target_id": observed["target_id"],
            "observed_mode": observed["mode"],
            "expected_target_revision": observed["revision"],
            "proposed_effect": EFFECT,
            "reason_summary": "Private fixture model reason must never be persisted by the demo.",
            "needs_attention": True,
        }
        return ProviderResult(
            content=json.dumps(proposal),
            provider_connection_id="nebius",
            requested_model=request.requested_model,
            reported_model=request.requested_model,
            identity_status="EXACT_MATCH",
            request_id="fixture-personal-ai-request",
            usage={"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60},
            finish_reason="stop",
            transport_scope="LIVE",
            latency_ms=2,
        )


class NebiusGuardFixture:
    def __init__(self, root, *, store=None, transport=None, drop_apply_ack=False):
        self.root = Path(root)
        self.operation_id = "personal-ai-operation"
        self.target_id = "nebius-disposable-target"
        self.clock_value = int(time.time())
        self.store = store or MemoryTargetStore(SCOPE, self.target_id)
        self.transport = transport or FakeNebiusJobTransport(
            self.store, drop_apply_ack=drop_apply_ack
        )
        self.client = CloudEffectTargetClient(
            scope=SCOPE, target_id=self.target_id, transport=self.transport
        )
        assignment = LocalOwnerAssignment(
            SCOPE,
            frozenset(Capability),
            frozenset({"disposable-service"}),
            frozenset({LIGHTNING}),
            operator_approved=True,
        )
        self.core = CoreAdmission(
            assignment,
            clock=lambda: datetime.fromtimestamp(self.clock_value, timezone.utc),
        )
        self.factory = DurableFactory(self.root / "native-fixture.json")
        self.runner = TransactionRunner(self.core, self.factory)
        self.guard = CoreServiceGuard(
            self.core,
            self.runner,
            ServicePolicy(SCOPE, self.target_id),
            self.client,
            clock=lambda: self.clock_value,
        )
        self.budget = LiteBudget(
            max_requests_per_hour=8,
            max_retry=0,
            max_output_tokens=128,
            request_timeout_seconds=20,
        )
        self.profile = LiteProfile(
            SCOPE,
            "personal-ai-watch",
            "service-target",
            enabled=True,
            provider_id="nebius",
            model_id=LIGHTNING,
            route_role="FAST",
            budget=self.budget,
            cadence=LiteCadence(interval_seconds=1),
        )
        route = NebiusModelRouter(
            catalog_receipt(), role_budgets=route_budgets()
        ).select(ModelRole.FAST)
        self.model_instances = []
        provider = NebiusProviderPort(
            route,
            self.budget,
            quote(),
            secret_supplier=lambda: "fixture-not-a-real-key",
            provider_factory=lambda **kwargs: self.model_instances.append(
                ServiceProposalProvider(**kwargs)
            )
            or self.model_instances[-1],
            clock=lambda: self.clock_value,
        )
        observation = type(
            "UnusedReadOnlyProbe",
            (),
            {"source_id": "service-target", "observe": lambda *args: None},
        )()
        self.bindings = LiteBindings(
            self.root / "journal",
            observation,
            provider,
            clock=lambda: self.clock_value,
            service_guard=GuardLoopBinding(self.guard, self.operation_id),
        )
        self.runtime = create_runtime(
            lite_profile=self.profile,
            mission_context=MissionContext(
                SCOPE, frozenset({"service-target"}), "CONTRACT_TEST"
            ),
            lite_bindings=self.bindings,
        )
        self.demo_bindings = PersonalAIDemoBindings(
            memory_retrieve=None,
            guard=self.guard,
            scheduler=self.runtime._lite_scheduler,
            execution_mode="FIXTURE",
        )

    def service(self, state_root, memory_retrieve):
        return PersonalAIDemoService(
            state_root,
            PersonalAIDemoBindings(
                memory_retrieve=memory_retrieve,
                guard=self.guard,
                scheduler=self.runtime._lite_scheduler,
                execution_mode="FIXTURE",
            ),
        )

    def close(self):
        self.runtime.close()
        self.runner.close()
        self.core.close()


def empty_memory(_query):
    return MemoryContext("READY", (), (), (), "[]", 2, False)


class NebiusPersonalAITests(unittest.TestCase):
    def request(self, fixture):
        return {
            "operation_id": fixture.operation_id,
            "target_id": fixture.target_id,
            "memory_query": "maintenance approved window",
        }

    def test_private_hat_restart_prepares_redacted_advisory_without_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            memory = MemoryFixture(root / "memory", scope=SCOPE)
            memory.activate(
                text=PREFERENCE,
                key="maintenance",
                content_kind="MODEL_EXPERIENCE",
            )
            memory.close()
            reopened = MemoryFixture(root / "memory", scope=SCOPE)
            guard = NebiusGuardFixture(root / "guard")
            try:
                service = guard.service(
                    root / "demo", reopened.runtime.lite_memory_retrieve
                )
                result = service.prepare(self.request(guard))
                self.assertEqual("APPROVAL_REQUIRED", result["state"])
                self.assertEqual(
                    ["ADVISORY", "VERIFIED", "APPROVAL_REQUIRED"],
                    [step["state"] for step in result["timeline"]],
                )
                self.assertGreater(result["memory"]["selected_count"], 0)
                self.assertFalse(result["memory"]["execution_authority"])
                self.assertEqual("ADVISORY_ONLY", result["model_authority"])
                self.assertEqual("nebius", result["provider_id"])
                self.assertEqual(LIGHTNING, result["model_id"])
                self.assertEqual("FIXTURE", result["execution_mode"])
                self.assertEqual(0, guard.store.apply_count)
                rendered = json.dumps(result, sort_keys=True)
                persisted = (root / "demo" / "personal-ai-state.json").read_text()
                self.assertNotIn(PREFERENCE, rendered)
                self.assertNotIn(PREFERENCE, persisted)
                self.assertNotIn("Private fixture model reason", persisted)
            finally:
                guard.close()
                reopened.close()

    def test_zero_write_and_approval_do_not_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = NebiusGuardFixture(root / "guard")
            try:
                service = guard.service(root / "demo", empty_memory)
                prepared = service.prepare(self.request(guard))
                self.assertEqual(
                    ["ADVISORY", "ZERO_WRITE", "APPROVAL_REQUIRED"],
                    [step["state"] for step in prepared["timeline"]],
                )
                approved = service.approve(prepared["proposal_id"])
                self.assertEqual("APPROVED", approved["state"])
                self.assertEqual(0, guard.store.apply_count)
                self.assertNotIn("approval_digest", json.dumps(approved))
            finally:
                guard.close()

    def test_approval_executes_once_reconciles_and_blocks_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            guard = NebiusGuardFixture(root / "guard")
            try:
                service = guard.service(root / "demo", empty_memory)
                prepared = service.prepare(self.request(guard))
                service.approve(prepared["proposal_id"])
                completed = service.resume(guard.operation_id)
                self.assertEqual("RECONCILED", completed["state"])
                self.assertEqual(1, guard.store.apply_count)
                self.assertTrue(completed["verified_effect"])
                self.assertTrue(completed["receipt_id"].startswith("target-"))
                self.assertEqual(64, len(completed["receipt_digest"]))
                self.assertEqual(64, len(completed["measurement_digest"]))
                replay = service.resume(guard.operation_id)
                self.assertEqual("REPLAY_BLOCKED", replay["state"])
                self.assertEqual(1, guard.store.apply_count)
                self.assertEqual(
                    1, guard.transport.calls.count("APPLY_SET_MAINTENANCE")
                )
            finally:
                guard.close()

    def test_lost_ack_restart_reconciles_without_second_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = NebiusGuardFixture(root / "guard", drop_apply_ack=True)
            prepared = None
            try:
                service = first.service(root / "demo", empty_memory)
                prepared = service.prepare(self.request(first))
                service.approve(prepared["proposal_id"])
                uncertain = service.resume(first.operation_id)
                self.assertEqual("EXECUTED", uncertain["state"])
                self.assertTrue(uncertain["reconciliation_pending"])
                self.assertEqual(1, first.store.apply_count)
            finally:
                store, transport = first.store, first.transport
                first.close()

            restarted = NebiusGuardFixture(
                root / "guard", store=store, transport=transport
            )
            try:
                service = restarted.service(root / "demo", empty_memory)
                reconciled = service.resume(restarted.operation_id)
                self.assertEqual("RECONCILED", reconciled["state"])
                self.assertEqual(1, store.apply_count)
                replay = service.resume(restarted.operation_id)
                self.assertEqual("REPLAY_BLOCKED", replay["state"])
                self.assertEqual(1, store.apply_count)
                self.assertEqual(
                    1, transport.calls.count("APPLY_SET_MAINTENANCE")
                )
            finally:
                restarted.close()

    def test_conflicting_idempotency_key_reuse_fails_closed(self):
        store = MemoryTargetStore(SCOPE, "nebius-disposable-target")
        command = {
            "operation_id": "personal-ai-operation",
            "scope": list(SCOPE.binding()),
            "target_id": store.target_id,
            "expected_revision": 1,
            "before_effect_count": 0,
            "effect_class": EFFECT,
            "approval_digest": "a" * 64,
            "policy_digest": "b" * 64,
            "proposal_digest": "c" * 64,
            "expires_at": 2**53,
            "idempotency_key": "d" * 64,
        }
        command["request_digest"] = canonical_sha256(command)
        request = {
            "schema": "aioa.nebius-serverless-target.v1",
            "action": "APPLY_SET_MAINTENANCE",
            "target_id": store.target_id,
            "scope": list(SCOPE.binding()),
            "command": command,
        }
        handle_target_request(request, store)
        conflicting = dict(command, operation_id="different-operation")
        conflicting["request_digest"] = canonical_sha256(
            {key: value for key, value in conflicting.items() if key != "request_digest"}
        )
        with self.assertRaisesRegex(ValueError, "TARGET_IDEMPOTENCY_CONFLICT"):
            handle_target_request({**request, "command": conflicting}, store)
        self.assertEqual(1, store.apply_count)


if __name__ == "__main__":
    unittest.main()
