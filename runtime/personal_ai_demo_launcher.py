"""Explicit screen-recording composition of the existing Personal AI runtime.

Starting either mode cannot make a paid request. LIVE preparation fails closed
until a new, independently reviewed spend authorization is implemented.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

from main import create_runtime
from providers.config import ProviderManager, ProviderConfig
from critical_loop.fixture import LocalCPLFixture, FIXTURE_PROMPT, FIXTURE_EVIDENCE
from critical_loop.service import CriticalPromptLoopService
from runtime.core_admission import Capability
from runtime.memory_patch.persistence.ports import TransactionRunner
from runtime.mission.contracts import MissionContext
from runtime.mission.governor import CoreDualGovernor, GovernorPolicy, GovernorBinding, Limits
from runtime.memory_patch.retrieval.service import NativeRetrieval
from runtime.memory_patch.retrieval.contracts import HybridRetrievalRequest
from runtime.mission.lite_contracts import LiteBudget, LiteCadence, LiteProfile
from runtime.mission.lite_runtime import LiteBindings, FileObservationProbe
from runtime.personal_ai_demo import PersonalAIDemoBindings, PersonalAIDemoService, PersonalAIDemoError
from runtime.personal_ai_fixture import PrivateFixtureMemory, DurableFactory, MODEL, atomic_json
from runtime.providers.exact import ProviderResult
from runtime.providers.nvidia import ProviderError
from runtime.providers.nebius_routing import ModelRole, ModelRoute, RouteBudget, NebiusProviderPort
from runtime.service_guard.contracts import ServicePolicy, EFFECT
from runtime.service_guard.service import CoreServiceGuard, GuardLoopBinding
from runtime.service_guard.target import CloudEffectTargetClient, DisposableTargetState
from runtime.service_guard.serverless_worker import handle_target_request
from runtime.webapp import WebRuntimeService, make_server

PREFERENCE = "Maintenance only after the approved window and never without explicit approval."


class _BlockedLiveProvider:
    """Explicit fail-closed LIVE configuration, never a fixture fallback."""
    provider_id = "nebius"
    model_id = MODEL
    def __init__(self, budget):
        self.budget = budget

    def estimated_units(self, request):
        raise ProviderError("BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION")

    def request(self, request):
        raise ProviderError("BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION")


class _FixtureExact:
    def __init__(self, owner, **_kwargs):
        self.owner = owner

    def generate_exact(self, request, cancellation, deadline):
        self.owner.fixture_calls += 1
        observed = json.loads(request.messages[-1].content)["observation"]
        content = json.dumps({"target_id": observed["target_id"], "observed_mode": observed["mode"],
            "expected_target_revision": observed["revision"], "proposed_effect": EFFECT,
            "reason_summary": "Transient deterministic fixture advisory.", "needs_attention": True})
        return ProviderResult(content, "nebius", MODEL, MODEL, "EXACT_MATCH", "fixture-demo-request",
                              {"prompt_tokens": 20, "completion_tokens": 40, "total_tokens": 60}, getattr(self.owner, "fixture_finish_reason", "stop"), "TEST", 0)


class _FixtureTargetTransport:
    def __init__(self, state):
        self.state = state

    def invoke(self, request):
        return handle_target_request(request, self)

    def _identity(self, target_id, scope):
        if target_id != self.state.target_id or scope != list(self.state.scope.binding()):
            raise ValueError("FIXTURE_TARGET_IDENTITY_MISMATCH")

    def read_state(self, target_id, scope):
        self._identity(target_id, scope)
        return self.state.read()

    def read_receipt(self, target_id, scope, key):
        self._identity(target_id, scope)
        return self.state.receipt(key)

    def apply_once(self, command):
        return self.state.apply(command)


class DemoComposition:
    operation_id = "personal-ai-operation"
    target_id = "nebius-disposable-target"

    def __init__(self, state_root, *, mode="FIXTURE", live_provider_policy=None):
        if mode not in {"FIXTURE", "LIVE"}:
            raise ValueError("INVALID_DEMO_MODE")
        self.root = Path(state_root).absolute()
        if self.root.is_symlink():
            raise ValueError("UNSAFE_DEMO_STATE")
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.stat()
        if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
            raise ValueError("UNSAFE_DEMO_STATE")
        if live_provider_policy is not None and (mode != "LIVE" or type(live_provider_policy) is not dict
            or set(live_provider_policy) != {"catalog_receipt", "cost_quote"}):
            raise ValueError("INVALID_OFFLINE_LIVE_POLICY")
        self.live_provider_policy = live_provider_policy
        self.live_candidate = None
        self.mode, self.fixture_calls = mode, 0
        self.cpl_fixture = None
        # A persistent manifest prevents changing labels on an existing session.
        mode_file = self.root / "demo-mode.json"
        if mode_file.exists() and json.loads(mode_file.read_text()) != {"provider_mode": mode, "target_mode": "FIXTURE"}:
            raise ValueError("DEMO_MODE_BINDING_MISMATCH")
        atomic_json(mode_file, {"provider_mode": mode, "target_mode": "FIXTURE"})
        self.memory = PrivateFixtureMemory(self.root / "memory", runtime_builder=self._build_runtime,
                                          backend_id="explicit-demo-file-fixture")
        self.runtime = self.memory.runtime
        self.reader = self.memory.core.local_operator(Capability.READ)
        if not (self.root / "memory-seeded.json").exists():
            self.memory.activate(text=PREFERENCE, content_kind="MODEL_EXPERIENCE", key="demo-constraint")
            atomic_json(self.root / "memory-seeded.json", {"fixture_owner_constraint": True})
        self.personal_ai = PersonalAIDemoService(self.root, PersonalAIDemoBindings(
            self.runtime.lite_memory_retrieve, self.guard, self.runtime._lite_scheduler,
            "FIXTURE", cpl_prepare=self._prepare_cpl, provider_mode=mode, target_mode="FIXTURE"))
        self.web = WebRuntimeService(runtime=self.runtime, personal_ai=self.personal_ai,
                                    personal_ai_catalog=self.catalog, personal_ai_cost_quote=self.quote)
        self.web.personal_ai_demo_owner = self

    def _build_runtime(self, memory):
        self.target_state = DisposableTargetState(self.root / "target", memory.scope, self.target_id)
        self.target = CloudEffectTargetClient(scope=memory.scope, target_id=self.target_id,
                            transport=_FixtureTargetTransport(self.target_state))
        # Memory domain audit and effect audit have distinct storage namespaces.
        # They share one Core; the effect store is not a second memory engine.
        self.effect_factory = DurableFactory(self.root / "service-guard.json")
        self.runner = TransactionRunner(memory.core, self.effect_factory)
        policy = GovernorPolicy(memory.scope, "personal-ai-judge", Limits(1000000, 10), Limits(1000000, 15), Limits(1000000, 20))
        self.governor = CoreDualGovernor(memory.core, self.runner, policy, clock=time.time)
        management = memory.core.local_operator(Capability.MANAGE)
        self.epoch = self.governor.inspect(memory.core.local_operator(Capability.READ))["epoch"]
        if self.epoch == 0:
            self.epoch = self.governor.start_epoch(management)
        self.guard = CoreServiceGuard(memory.core, self.runner, ServicePolicy(memory.scope, self.target_id),
                                      self.target, clock=time.time,
            governor_binding=GovernorBinding(self.governor, memory.core.local_operator(Capability.COMMIT), self.epoch, self.operation_id, 3))
        now = datetime.now(timezone.utc).isoformat()
        # Synthetic routing inputs are always labelled FIXTURE, never live evidence.
        self.catalog = {"schema": "aioa.nebius-fixture-catalog.v1", "provider": "nebius", "status": "FIXTURE",
            "created_utc": now, "catalog_model_count": 1, "catalog_nemotron_ids": [MODEL],
            "live_catalog_validated": False, "authority": "ADVISORY_ONLY", "fallback": False,
            "response_content_persisted": False, "transport_scope": "TEST"}
        self.quote = {"model_id": MODEL, "currency": "USD", "input_usd_per_million": "0.06",
            "output_usd_per_million": "0.24", "quoted_utc": now, "input_bound_policy": "utf8-bytes-plus-framing-v1"}
        budget = LiteBudget(max_requests_per_hour=8, max_retry=0, max_input_bytes=4096, max_response_bytes=16384, max_output_tokens=128, request_timeout_seconds=20)
        route = ModelRoute(ModelRole.FAST, "nebius", MODEL, RouteBudget(8192, 128, 20, "0.001"), now)
        provider = NebiusProviderPort(route, budget, self.quote, secret_supplier=lambda: "explicit-fixture-handle",
                        provider_factory=lambda **kwargs: _FixtureExact(self, **kwargs), clock=time.time, transport_scope="TEST",
                        governor_binding=GovernorBinding(self.governor, memory.core.local_operator(Capability.COMMIT), self.epoch, self.operation_id, 1))
        if self.mode == "LIVE":
            if self.live_provider_policy is not None:
                from runtime.providers.nebius_routing import validate_competition_model
                catalog = self.live_provider_policy["catalog_receipt"]
                quote = self.live_provider_policy["cost_quote"]
                validate_competition_model(MODEL, catalog, quote)
                route = ModelRoute(ModelRole.FAST, "nebius", MODEL, RouteBudget(8192, 128, 20, "0.001"), catalog["created_utc"])
                def blocked_secret():
                    raise ProviderError("BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION")
                self.live_candidate = NebiusProviderPort(route, budget, quote, secret_supplier=blocked_secret,
                    transport_scope="LIVE", governor_binding=GovernorBinding(self.governor,
                    memory.core.local_operator(Capability.COMMIT), self.epoch, self.operation_id, 1))
            # A valid quote/catalog is input readiness, never permission to call.
            provider = _BlockedLiveProvider(budget)
        profile = LiteProfile(memory.scope, "personal-ai-watch", "service-target", enabled=True,
            provider_id="nebius", model_id=MODEL, route_role="FAST", memory_mode="ACTIVE",
            memory_profile_digest=memory.memory_profile.digest, budget=budget,
            cadence=LiteCadence(interval_seconds=1))
        observation_path = self.root / "observation.json"
        atomic_json(observation_path, {"value": "fixture-target", "health": "OK", "source_revision": "v1"})
        bindings = LiteBindings(self.root / "scheduler", FileObservationProbe("service-target", observation_path),
            provider, clock=time.time, memory=memory.memory_bindings,
            service_guard=GuardLoopBinding(self.guard, self.operation_id))
        runtime = create_runtime(lite_profile=profile, lite_bindings=bindings,
            mission_context=MissionContext(memory.scope, frozenset({"service-target"}), "CONTRACT_TEST"))
        return runtime

    def _prepare_cpl(self):
        if self.mode == "LIVE":
            raise PersonalAIDemoError("BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION")
        if self.cpl_fixture is None:
            self.cpl_fixture = LocalCPLFixture(delay_seconds=0)
            manager_root = self.root / "cpl-manager"
            manager_root.mkdir(mode=0o700, exist_ok=True)
            manager = ProviderManager(ROOT, fixture_base_url=self.cpl_fixture.base_url, state_dir=manager_root)
            # Fixture selection is explicit and independent of real user config.
            manager.provider_chain = [ProviderConfig("openrouter", "fixture/synthetic", True)]
            manager.current_model = "openrouter/fixture/synthetic"
            self.runtime._cpl_service = CriticalPromptLoopService(manager, self.root / "cpl")
        service = self.runtime._cpl_service
        plan = service.plan({"prompt": FIXTURE_PROMPT, "evidence": FIXTURE_EVIDENCE})
        service.start(plan["run_id"], plan["plan_hash"], plan["nonce"])
        result = service.wait(plan["run_id"])
        if result.get("execution_status") != "COMPLETED":
            raise PersonalAIDemoError("FIXTURE_CPL_FAILED")
        if result.get("generation_requests") != 5:
            raise PersonalAIDemoError("FIXTURE_CPL_SEQUENCE_FAILED")
        return "COMPLETED_ADVISORY"

    def context_capsule(self):
        reader = self.memory.core.local_operator(Capability.READ)
        request = HybridRetrievalRequest.admitted(self.memory.core, reader, hat_id=self.memory.hat_id,
            query="reviewed policy", context_budget_bytes=2048, limit=4)
        retrieval = NativeRetrieval(self.memory.core, self.memory.evidence, self.memory.sources,
            freshness=self.memory.freshness, clock=lambda: self.memory.now)
        lanes = retrieval.retrieve(reader, request, include_personal=False)
        return retrieval.context_capsule(reader, request, lanes)

    def validate_judge_request(self, request):
        if request != {"operation_id": self.operation_id, "target_id": self.target_id,
                       "memory_query": "maintenance approved window"}:
            raise PersonalAIDemoError("JUDGE_SCENARIO_ONLY")

    def offline_live_admission(self, request):
        if self.live_candidate is None:
            raise PersonalAIDemoError("BLOCKED_PROVIDER")
        data = json.loads(request.input_text)
        if type(data) is not dict:
            raise PersonalAIDemoError("INVALID_OFFLINE_REQUEST")
        data["context_capsule"] = self.context_capsule().as_dict()
        request = replace(request, input_text=json.dumps(data, sort_keys=True, separators=(",", ":")))
        # Existing native exact request/cost policy only. Never request/reserve.
        units = self.live_candidate.estimated_units(request)
        money = self.live_candidate.estimated_money_nano(request)
        return {"state": "UNSENT_OFFLINE_ADMISSION", "estimated_units": units, "money_nano_usd": money,
            "authority": "NONE", "advisory_authority": "ADVISORY_ONLY", "verification": "UNVERIFIED",
            "live_calls": 0, "operator_authorization_required": True}

    def readiness(self):
        # READ only: no key/environment lookup, network probe or live claim.
        capsule = self.context_capsule()
        return {"status": "ok", "state": "LOCAL_FIXTURE_READY" if self.mode == "FIXTURE" else "BLOCKED_PROVIDER",
            "provider_badge": "FIXTURE" if self.mode == "FIXTURE" else "LIVE_NEBIUS_TOKEN_FACTORY",
            "provider_state": "FIXTURE" if self.mode == "FIXTURE" else "NOT_LIVE",
            "provider_kind_badge": "FIXTURE_PROVIDER" if self.mode == "FIXTURE" else "LIVE_PROVIDER",
            "target_kind_badge": "FIXTURE_TARGET",
            "target_badge": "FIXTURE_ONLY", "model": MODEL, "authority": "NONE", "model_authority": "ADVISORY_ONLY",
            "live_validated": False, "fallback": False, "credentials": "NOT_INSPECTED", "provider_calls_on_read": 0,
            "context_capsule_digest": capsule.capsule_hash, "context_purpose": capsule.purpose,
            "caps": {"max_requests_per_hour": 8, "max_calls_per_prepare": 1, "retry": 0, "max_input_bytes": 4096,
                     "max_output_tokens": 128, "max_response_bytes": 16384, "request_timeout_seconds": 20, "usd_ceiling": "0.001"},
            "blocked_reason": "BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION" if self.mode == "LIVE" else None}

    def prepare(self):
        return self.personal_ai.prepare({"operation_id": self.operation_id, "target_id": self.target_id,
                                         "memory_query": "maintenance approved window"})

    def close(self):
        self.memory.close()
        self.runner.close()
        self.effect_factory.close()
        if self.cpl_fixture is not None:
            self.cpl_fixture.close()


def run_self_test(state_root):
    root = Path(state_root)
    demo = DemoComposition(root)
    sequence = []
    try:
        prepared = demo.prepare()
        sequence.append(prepared["state"])
        _require(prepared["memory"]["selected_count"] > 0 and demo.target.read()["effect_count"] == 0, "PREPARE_BOUNDARY_FAILED")
        _require(prepared["memory"]["execution_authority"] is False, "MEMORY_AUTHORITY_FAILED")
        approved = demo.personal_ai.approve(prepared["proposal_id"])
        sequence.append(approved["state"])
        _require(demo.target.read()["effect_count"] == 0, "APPROVAL_DISPATCHED_EFFECT")
        executed = demo.personal_ai.resume(demo.operation_id)
        sequence.append(executed["state"])
        _require(executed["verified_effect"] is True and executed["receipt_digest"] is not None, "RECEIPT_OR_READBACK_FAILED")
        _require(demo.target.read()["effect_count"] == 1, "EXECUTION_COUNT_FAILED")
        references = prepared["memory"]["selected_count"]
    finally:
        demo.web.personal_ai_demo_owner.close()
    restarted = DemoComposition(root)
    try:
        _require(bool(restarted.runtime.lite_memory_retrieve("maintenance approved window").selected), "MEMORY_RESTART_FAILED")
        reconciled = restarted.personal_ai.reconcile_restart(restarted.operation_id)
        sequence.append(reconciled["state"])
        replay = restarted.personal_ai.resume(restarted.operation_id)
        sequence.append(replay["state"])
        _require(sequence == ["APPROVAL_REQUIRED", "APPROVED", "EXECUTED", "RECONCILED", "REPLAY_BLOCKED"], "STATE_SEQUENCE_FAILED")
        _require(restarted.target.read()["effect_count"] == 1, "DUPLICATE_EFFECT_DETECTED")
        # Private memory is intentionally persisted in its private native backend;
        # it must never appear in public projection, receipts or self-test evidence.
        _require(PREFERENCE not in json.dumps(replay), "PRIVATE_PROJECTION_LEAK")
        for path in root.rglob("*"):
            if path.is_file() and not path.is_relative_to(root / "memory"):
                raw = path.read_bytes()
                _require(PREFERENCE.encode() not in raw, "PRIVATE_EVIDENCE_LEAK")
                _require(b"Transient deterministic fixture advisory." not in raw, "MODEL_CONTENT_PERSISTED")
        result = {"schema": "aioa.personal-ai-demo-self-test.v1", "status": "PASS", "provider_mode": "FIXTURE",
            "target_mode": "FIXTURE", "model_authority": "ADVISORY_ONLY", "memory_execution_authority": False,
            "private_content_persisted": False, "private_memory_storage": "OWNER_SCOPED_NATIVE_BACKEND",
            "fallback": False, "state_sequence": sequence, "effect_apply_count": 1, "duplicate_effect_count": 0,
            "memory_persistence": True, "hat_reference_count": references, "cpl_status": prepared["cpl_status"],
            "verification_status": prepared["verification_status"], "verified_delta_status": "ZERO_WRITE",
            "approval_gate": "PASS", "readback": "VERIFIED", "reconciliation": "RECONCILED",
            "replay": "REPLAY_BLOCKED", "receipt_digest": replay["receipt_digest"]}
        result["cpl_scope"] = "SEPARATE_SYNTHETIC_DEMONSTRATION"
        result["fixture_cpl_generation_requests"] = 5
        result["privacy_scope"] = "PUBLIC_PROJECTION_RECEIPTS_JOURNALS_AND_SELF_TEST"
        atomic_json(root / "demo-self-test.json", result)
        return result
    finally:
        restarted.close()


def _require(condition, code):
    if not condition:
        raise ValueError(code)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fixture", action="store_true")
    modes.add_argument("--live-provider", action="store_true")
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=4311)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    import subprocess
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    if branch not in {"nebius-personal-ai", "integration/nebius-unified-prototype-20261008"}:
        parser.error("STOP: demo requires an explicitly approved Nebius branch")
    if args.self_test:
        if args.live_provider:
            parser.error("self-test requires fixture mode")
        print(json.dumps(run_self_test(args.state_dir), sort_keys=True))
        return
    demo = DemoComposition(args.state_dir, mode="LIVE" if args.live_provider else "FIXTURE")
    server = make_server("127.0.0.1", args.port, demo.web)
    print("AIOA spArkHAT — Nebius Personal AI Demo", flush=True)
    print(f"Mode: {demo.mode}\nProvider: {'LIVE configured; calls BLOCKED_BY_ADDITIONAL_COST_AUTHORIZATION' if args.live_provider else 'Nebius-compatible fixture'}\nModel authority: ADVISORY_ONLY\nHuman approval: REQUIRED\nEffect target: FIXTURE\nState: {demo.root}\nURL: http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        demo.web.personal_ai_demo_owner.close()


if __name__ == "__main__":
    main()
