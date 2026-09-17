"""Offline NV07 composition: native ports and the original CPL, no sockets.

The actor outputs and independent rule oracle are explicit controlled fixtures.
They prove contracts, never fresh model behavior or live source certification.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from main import create_runtime
from critical_loop.service import CriticalPromptLoopService
from providers.exact import ProviderResult
from nv03_support import MemoryFixture
from nv05_support import dynamics_binding
from test_nv02_lite import FixtureTransport, success
from live_gate_support import test_live_gate

from runtime.core_admission import Capability
from runtime.memory_patch.learning.contracts import (
    CoreVerifierBinding, EvidenceLiteralVerifier, LearningPolicy, ModelIdentity,
    RegisteredRuleVerifier,
)
from runtime.memory_patch.learning.personal_contracts import (
    ConsentMode, CorrectionMode, PersonalDeltaPolicy,
)
from runtime.memory_patch.retrieval.temporal import FreshnessPolicy
from runtime.mission.lite_contracts import MODEL, LiteBudget
from runtime.mission.lite_cpl import CoreLiteCPLBindings, LiteCPLPolicy
from runtime.providers.nvidia import NvidiaProvider


SOURCE_FILE = Path(__file__).resolve().parents[1] / "runtime/knowledge/examples/systemctl-status.json"
SOURCE = json.loads(SOURCE_FILE.read_text())
RIGHT = SOURCE["description"]
WRONG = "Starts the sshd service."
QUESTION = "What does systemctl status sshd do?"
TASK = "linux-systemctl-status"


def reply(claim):
    if isinstance(claim, Exception):
        return claim
    return success(choices=[{"finish_reason": "stop", "message": {
        "content": json.dumps({"summary": claim, "needs_attention": True})}}])


class OfflineCPLManager:
    fixture_base_url = "in-process-fixture-no-network"

    def __init__(self, proposal=RIGHT):
        self.proposal, self.calls = proposal, []

    def strict_status(self):
        return {"enabled": True}

    def generate_exact(self, request, token, deadline):
        request.validate()
        token.check(deadline)
        self.calls.append(request)
        content = json.dumps({
            "summary": "Controlled proposal; Core must independently verify it.",
            "findings": [], "uncertainty": ["Fixture is not a live model."],
            "evidence_conflicts": [],
        }) if request.response_schema_json else self.proposal
        return ProviderResult(content, "openrouter", request.requested_model,
                              request.requested_model, "EXACT_MATCH", None, None,
                              "stop", "TEST")


class ChatFixture(MemoryFixture):
    def add_source(self, source_id, version, text, *, metadata=None):
        if text == "The reviewed policy applies.":
            text = self.source_text
        return super().add_source(source_id, version, text, metadata=metadata)

    def _source(self, record):
        source = super()._source(record)
        source = replace(source, source_kind="linux",
                         source_reference="repository:runtime/knowledge/examples/systemctl-status.json")
        self.sources.approve(source)
        return source

    def __init__(self, root, *, replies=(WRONG, RIGHT), scope=None, semantics=None,
                 critic=True, proposal=RIGHT, oracle=RIGHT, dynamics=False,
                 max_records=128, max_bytes=262144, private_values=(), revision=1,
                 requests=24, model_version="controlled-original-model", source_text=RIGHT):
        self.source_text = source_text
        super().__init__(root, initialize=False, scope=scope)
        self.runtime.close()
        self.freshness = FreshnessPolicy("nv03-freshness", "1", {"linux": 86400})
        self.dependencies = replace(
            self.dependencies, freshness=self.freshness,
            packet_key=b"nv07-controlled-packet-integrity-only",
            private_values=private_values,
        )
        memory = replace(self.memory_bindings, dependencies=self.dependencies)
        self.policy = LearningPolicy(
            self.scope, "test-hat", TASK, QUESTION, ("policy",),
            ModelIdentity("nvidia", MODEL, model_version, "nemotron"),
            ("linux-corpus", "controlled-domain-rule"), maximum_records=max_records,
        )
        verifiers = (
            CoreVerifierBinding("linux-corpus", "literal-source-equality",
                                "repository-linux-fixture", EvidenceLiteralVerifier()),
            CoreVerifierBinding("controlled-domain-rule", "registered-domain-test",
                                "controlled-rule-fixture", RegisteredRuleVerifier(
                                    self.scope, TASK, oracle, (("policy", "v1"),),
                                    self.now + timedelta(days=1))),
        )
        personal = PersonalDeltaPolicy(self.scope, ("test-hat",), "test-hat",
                                       semantics, maximum_learning_bytes=max_bytes)
        self.cpl_manager = OfflineCPLManager(proposal)
        self.cpl_service = (CriticalPromptLoopService(self.cpl_manager, self.root / "chat-cpl")
                            if critic else None)
        policy = LiteCPLPolicy(self.policy, ("fixture/synthetic",) * 4,
                               ("controlled-correlated-critics",) * 3,
                               mode="ACTIVE", allow_local_plan_start=True)
        cpl = CoreLiteCPLBindings(policy, self.cpl_service, verifiers,
                                  personal_policy=personal)
        self.profile = replace(self.profile, watch_id="nv07-chat", manifest_revision=revision,
                               cpl_mode="ACTIVE", cpl_profile_digest=policy.digest,
                               personal_profile_digest=personal.digest,
                               budget=LiteBudget(max_requests_per_hour=requests,
                                                 max_hourly_units=500000))
        self.transport = FixtureTransport([reply(value) for value in replies])
        self.provider = NvidiaProvider(self.profile.budget, secret_supplier=lambda: "fixture-key",
                                       transport=self.transport, clock=lambda: self.now.timestamp(),
                                       live_gate=test_live_gate(
                                           self.root / "live-gate",
                                           clock=lambda: self.now.timestamp(),
                                       ))
        self.bindings = replace(self.bindings, provider=self.provider, memory=memory,
                                cpl=cpl, state_root=self.root / "chat-journal")
        if dynamics:
            self.profile, self.bindings = dynamics_binding("ACTIVE")(self.profile, self.bindings)
        self.runtime = create_runtime(lite_profile=self.profile, mission_context=self.context,
                                       lite_bindings=self.bindings)
        self.learning = self.runtime._lite_cpl.learning
        self.personal = self.learning.personal

    def consent(self, mode=ConsentMode.AUTO_VERIFIED_SCOPED):
        return self.personal.set_consent(
            self.core.local_operator(Capability.OWNER_APPROVAL), mode,
            expected_revision=self.personal.describe()["revision"],
            allowed_hats=() if mode is ConsentMode.OFF else ("test-hat",),
            expires_at=self.now + timedelta(hours=1),
        )

    def ask(self, operation_id="episode-1", *, mode=CorrectionMode.HAT_ONLY,
            question=QUESTION, principal=None):
        return self.runtime.lite_chat(
            self.core.local_operator(Capability.READ) if principal is None else principal,
            question, operation_id=operation_id, mode=mode,
        )

    def change_source_version(self):
        for identifier, record in list(self.catalog.records.items()):
            self.metadata[identifier] = {
                **self.metadata[identifier], "document_identity": "policy",
                "provision_identifier": "rule", "version_identity": "v1",
                "superseded_by": ["v2"],
            }
            self._source(record)
        self.add_source("policy", "v2", RIGHT, metadata={
            "document_identity": "policy", "provision_identifier": "rule",
            "version_identity": "v2", "supersedes": ["v1"],
            "effective_from": "2020-01-01", "verified_at": self.now.isoformat(),
        })
        self.save_corpus()

    def close(self):
        if getattr(self, "cpl_service", None) is not None:
            self.cpl_service.close()
        super().close()
