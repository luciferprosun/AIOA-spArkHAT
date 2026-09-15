"""Controlled native runtime + NVIDIA adapter + original CPL HTTP fixture."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta

from critical_loop.fixture import LocalCPLFixture
from critical_loop.service import CriticalPromptLoopService
from main import create_runtime
from nv03_support import MemoryFixture
from providers import ProviderManager
from test_nv02_lite import FixtureTransport, success

from runtime.memory_patch.learning.contracts import (
    CoreVerifierBinding,
    EvidenceLiteralVerifier,
    LearningPolicy,
    ModelIdentity,
    RegisteredRuleVerifier,
)
from runtime.mission.lite_contracts import MODEL, LiteBudget
from runtime.mission.lite_cpl import CoreLiteCPLBindings, LiteCPLPolicy
from runtime.providers.nvidia import NvidiaProvider

WRONG = "The reviewed policy does not apply."
RIGHT = "The reviewed policy applies."


def actor_transport(claim):
    status, raw = success()
    payload = json.loads(raw)
    payload["choices"][0]["message"]["content"] = json.dumps(
        {"summary": claim, "needs_attention": True}
    )
    return FixtureTransport([(status, json.dumps(payload).encode())])


class LearningFixture(MemoryFixture):
    def __init__(
        self,
        root,
        *,
        actor=WRONG,
        revision_claim=RIGHT,
        cpl_mode="ACTIVE",
        faults=None,
        correlated=False,
        oracle_claim=RIGHT,
        malformed=False,
        requests=24,
        no_critic=False,
        scope=None,
        revision=1,
        dynamics=None,
    ):
        super().__init__(root, initialize=False, scope=scope)
        self.runtime.close()
        clock_file = self.root / "trusted-test-clock.txt"
        if clock_file.exists():
            self.now = datetime.fromisoformat(clock_file.read_text())
        self.learning_policy = LearningPolicy(
            self.scope,
            "test-hat",
            "reviewed-policy",
            "State the reviewed policy as one atomic claim.",
            ("policy",),
            ModelIdentity(
                "nvidia", MODEL, "exact-id-no-provider-fingerprint", "nemotron"
            ),
            ("authoritative-source", "independent-oracle"),
        )
        oracle = RegisteredRuleVerifier(
            self.scope,
            self.learning_policy.task_signature,
            oracle_claim,
            (("policy", "v1"),),
            self.now + timedelta(days=1),
        )
        if malformed:

            class Malformed:
                def verify(self, request):
                    return {"supported": True, "status": "VERIFIED", "owner": "public"}

            oracle = Malformed()
        self.verifiers = (
            CoreVerifierBinding(
                "authoritative-source",
                "literal-source-equality",
                "reviewed-policy",
                EvidenceLiteralVerifier(),
            ),
            CoreVerifierBinding(
                "independent-oracle",
                "registered-domain-test",
                "reviewed-policy" if correlated else "independent-test-registry",
                oracle,
            ),
        )
        self.http = LocalCPLFixture(faults=faults, atomic_claim=revision_claim)
        self.manager = ProviderManager(
            self.root / "provider-runtime", fixture_base_url=self.http.base_url
        )
        self.cpl_service = (
            None
            if no_critic
            else CriticalPromptLoopService(self.manager, self.root / "cpl-trace")
        )
        self.cpl_policy = LiteCPLPolicy(
            self.learning_policy,
            ("fixture/synthetic",) * 4,
            ("correlated-fixture-family",) * 3,
            mode=cpl_mode,
            allow_local_plan_start=True,
        )
        self.cpl_bindings = CoreLiteCPLBindings(
            self.cpl_policy, self.cpl_service, self.verifiers
        )
        self.profile = replace(
            self.profile,
            watch_id="nv04-watch",
            manifest_revision=revision,
            cpl_mode=cpl_mode,
            cpl_profile_digest=self.cpl_policy.digest,
            budget=LiteBudget(max_requests_per_hour=requests, max_hourly_units=500000),
        )
        self.transport = actor_transport(actor)
        self.provider = NvidiaProvider(
            self.profile.budget,
            secret_supplier=lambda: "fixture-key",
            transport=self.transport,
            clock=lambda: self.now.timestamp(),
        )
        self.bindings = replace(
            self.bindings,
            provider=self.provider,
            state_root=self.root / "learning-scheduler",
            cpl=self.cpl_bindings,
        )
        if dynamics is not None:
            self.profile, self.bindings = dynamics(self.profile, self.bindings)
        self.runtime = create_runtime(
            lite_profile=self.profile,
            mission_context=self.context,
            lite_bindings=self.bindings,
        )
        self.learning = self.runtime._lite_cpl.learning

    def changed(self, value="next"):
        self.runtime.lite_tick()
        self.now += timedelta(seconds=2)
        self.observe(value)
        result = self.runtime.lite_tick()
        (self.root / "trusted-test-clock.txt").write_text(self.now.isoformat())
        return result

    def close(self):
        if hasattr(self, "cpl_service") and self.cpl_service is not None:
            self.cpl_service.close()
        if hasattr(self, "http"):
            self.http.close()
        super().close()
