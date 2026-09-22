"""Offline Core/Cockroach-port fixture; never evidence of a live provider call."""
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path

from main import create_runtime
from nv03_support import MemoryFixture
from test_nv02_lite import FixtureTransport, success
from live_gate_support import test_live_gate
from runtime.core_admission import Capability
from runtime.memory_patch.learning.contracts import CoreVerifierBinding, LearningPolicy, ModelIdentity
from runtime.memory_patch.learning.nachwg import SOURCE_IDS, NachwgStatutoryVerifier, NachwgCommencementVerifier, source_text_digest
from runtime.memory_patch.learning.nachwg_contract import NACHWG_CASE_ID, NACHWG_HAT, HISTORICAL_QUESTION
from runtime.memory_patch.learning.personal_contracts import ConsentMode, PersonalDeltaPolicy
from runtime.mission.lite_contracts import LiteBudget, MODEL
from runtime.mission.lite_cpl import CoreLiteCPLBindings, LiteCPLPolicy
from runtime.providers.nvidia import NvidiaProvider


FIXTURES = Path(__file__).parent / "fixtures"
TEXTS = json.loads((FIXTURES / "nachwg_official_excerpts.json").read_text())["texts"]


def correct_answer():
    return json.loads((FIXTURES / "nachwg_correct_answer.json").read_text())


def reply(answer):
    if isinstance(answer, Exception):
        return answer
    content = answer if isinstance(answer, str) else json.dumps(answer)
    return success(choices=[{"finish_reason": "stop", "message": {"content": content}}])


class NachwgFixture(MemoryFixture):
    def add_source(self, source_id, version, text, **kwargs):
        if source_id == "policy":
            for identifier in SOURCE_IDS:
                result = super().add_source(identifier, "v1", TEXTS[identifier])
            return result
        return super().add_source(source_id, version, text, **kwargs)

    def __init__(self, root, *, replies=None, scope=None):
        super().__init__(root, initialize=False, scope=scope, hat_id=NACHWG_HAT,
                         profile_changes={"max_context_tokens": 8192})
        self.runtime.close()
        self.dependencies = replace(self.dependencies, packet_key=b"nachwg-offline-core-packet-key-32-bytes")
        memory = replace(self.memory_bindings, dependencies=self.dependencies)
        policy = LearningPolicy(self.scope, NACHWG_HAT, NACHWG_CASE_ID, HISTORICAL_QUESTION,
                                SOURCE_IDS, ModelIdentity("nvidia", MODEL, "offline-fixture", "nemotron"),
                                ("nachwg-statutes", "nachwg-commencement"))
        versions = tuple((sid, "v1") for sid in SOURCE_IDS)
        digests = tuple((sid, source_text_digest(TEXTS[sid])) for sid in SOURCE_IDS)
        verifiers = (
            CoreVerifierBinding("nachwg-statutes", "statutory-field-semantics", "german-statutes",
                                NachwgStatutoryVerifier(self.scope, versions, self.now + timedelta(days=1), digests)),
            CoreVerifierBinding("nachwg-commencement", "official-commencement", "federal-ministry",
                                NachwgCommencementVerifier(self.scope, versions, self.now + timedelta(days=1), digests)),
        )
        personal = PersonalDeltaPolicy(self.scope, (NACHWG_HAT,), NACHWG_HAT)
        cpl_policy = LiteCPLPolicy(policy, ("fixture/unused",) * 4, ("unused-critics",) * 3,
                                   mode="ACTIVE", allow_local_plan_start=True)
        self.profile = replace(self.profile, watch_id="nachwg-offline", cpl_mode="ACTIVE",
                               cpl_profile_digest=cpl_policy.digest, personal_profile_digest=personal.digest,
                               budget=LiteBudget(max_requests_per_hour=8, max_hourly_units=500000,
                                                 max_output_tokens=1024, max_input_bytes=16384,
                                                 max_response_bytes=24000))
        self.transport = FixtureTransport([reply(a) for a in (replies or [correct_answer()])])
        self.provider = NvidiaProvider(self.profile.budget, secret_supplier=lambda: "fixture-key",
                                       transport=self.transport, clock=lambda: self.now.timestamp(),
                                       live_gate=test_live_gate(self.root / "nachwg-gate",
                                                                clock=lambda: self.now.timestamp()))
        self.bindings = replace(self.bindings, memory=memory, provider=self.provider,
                                cpl=CoreLiteCPLBindings(cpl_policy, None, verifiers, personal_policy=personal),
                                state_root=self.root / "nachwg-journal")
        self.runtime = create_runtime(lite_profile=self.profile, mission_context=self.context,
                                       lite_bindings=self.bindings)
        self.learning = self.runtime._lite_cpl.learning

    def consent(self):
        return self.learning.personal.set_consent(
            self.core.local_operator(Capability.OWNER_APPROVAL), ConsentMode.AUTO_VERIFIED_SCOPED,
            expected_revision=self.learning.personal.describe()["revision"],
            allowed_hats=(NACHWG_HAT,), expires_at=self.now + timedelta(hours=1),
        )

    def ask(self, operation="case-1"):
        return self.runtime.lite_nachwg_chat(self.core.local_operator(Capability.READ), operation_id=operation)
